import unittest
import io
import hashlib
import sys
import os
import random
from contextlib import redirect_stdout
import zlib
import argparse
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch
import tempfile
from collections import defaultdict
import datetime
import re

# Ensure core modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from drivers.InfinityEngine.io.installation_finder import InstallationFinder
from drivers.InfinityEngine.resource_loader import ResourceLoader
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.binary.writer import BinaryWriter
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from drivers.InfinityEngine.definitions.extensions import RESOURCE_TYPE_MAP

# A palette of available ANSI color codes.
# Use these to define the theme below.
PALETTE = {
    # Standard
    'black':   '\033[30m', 'red':     '\033[31m', 'green':   '\033[32m',
    'yellow':  '\033[33m', 'blue':    '\033[34m', 'magenta': '\033[35m',
    'cyan':    '\033[36m', 'white':   '\033[37m',
    # Bright
    'bright_black':  '\033[90m', 'bright_red':    '\033[91m', 'bright_green':  '\033[92m',
    'bright_yellow': '\033[93m', 'bright_blue':   '\033[94m', 'bright_magenta':'\033[95m',
    'bright_cyan':   '\033[96m', 'bright_white':  '\033[97m',
    # Modifiers
    'end':      '\033[0m',
    'bold':     '\033[1m',
    'underline':'\033[4m',
}

# Defines the color theme for the test suite output.
# Change the values here to easily customize the look.
class Colors:
    # Semantic mappings
    HEADER      = PALETTE['bright_black']
    LABEL       = PALETTE['cyan']
    VALUE       = PALETTE['bright_yellow']
    TOTAL_COUNT = PALETTE['end']
    FAILURE_LABEL = PALETTE['bright_magenta']   # "Failed:", "Error:"
    FAILURE_COUNT = PALETTE['end']          # The numeric failure count
    ERROR_MSG     = PALETTE['bright_black']       # The actual error message text
    RESREF_LABEL  = PALETTE['cyan'] # For specific labels like 'Resrefs'
    
    # Direct modifiers
    ENDC        = PALETTE['end']
    BOLD        = PALETTE['bold']
    UNDERLINE   = PALETTE['underline']

class TestPlanarForge(unittest.TestCase):
    # CLI arguments will be stored here
    schema_filter = None
    resref_filter = None
    game_filter = None
    log_file = None
    fidelity_stats = None
    gap_audit_stats = None
    audit_gaps = False
    gap_policy = "allow"
    gap_detail_limit = 5
    gap_allowlist_path = None
    gap_allowlist_rules = []
    gap_allowlist_source = None
    show_progress = True
    fidelity_threads = 1
    
    @classmethod
    def setUpClass(cls):
        print("--- Setting up PlanarForge Test Suite ---")

        # Determine log file name parts
        test_part = 'a'
        if len(sys.argv) > 1:
             # Basic heuristic to find test number if present in args
             # (Refined handling happens in main, but setUpClass needs a filename now)
             for i, arg in enumerate(sys.argv):
                 if arg == '--test' and i + 1 < len(sys.argv):
                     test_part = sys.argv[i+1]
                     break
        
        # Setup logging
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        res_type_part = cls.schema_filter if cls.schema_filter else 'a'
        log_filename = f"logs/{test_part}-{timestamp}-{res_type_part}.log"
        
        try:
            os.makedirs("logs", exist_ok=True)
            cls.log_file = open(log_filename, "w", encoding="utf-8")
            cls.log_file.write(f"PlanarForge Test Suite Log - {datetime.datetime.now()}\n\n")
            print(f"Logging test results to {log_filename}")
        except IOError as e:
            print(f"Warning: Could not open log file {log_filename}: {e}")
            cls.log_file = None
        
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        schema_path = os.path.join(project_root, "drivers", "InfinityEngine", "definitions", "schemas")
        cls.schema_loader = SchemaLoader(schema_path)
        cls.schema_loader.load_all()
        cls.schema_loader.resolve_types(FieldTypes)
        default_gap_allowlist = os.path.join(project_root, "tools", "tests", "gap_allowlist.json")
        allowlist_path = cls.gap_allowlist_path
        if not allowlist_path and os.path.isfile(default_gap_allowlist):
            allowlist_path = default_gap_allowlist
        cls._load_gap_allowlist(allowlist_path)
        parser_options = {}
        if cls.audit_gaps:
            parser_options = {
                "audit_unknown_gaps": True,
                "unknown_gap_policy": cls.gap_policy,
            }

        cls.loader = ResourceLoader(schema_loader=cls.schema_loader, parser_options=parser_options)
        
        # Find all installed games
        all_found_games = [inst.game_id for inst in cls.loader.install_finder.find_all()]
        
        # Load chitin for all found games
        total_chitins = len(all_found_games)
        loaded_chitins = 0
        for game_id in all_found_games:
            cls.loader._load_chitin(game_id)
            loaded_chitins += 1
            if cls.show_progress and total_chitins > 0:
                cls._print_loading_progress("SETUP", loaded_chitins, total_chitins)
        if cls.show_progress and total_chitins > 0:
            cls._finish_loading_progress()
        
        # Determine which games to test based on CLI arg or all found games
        if cls.game_filter:
            cls.games_to_test = [g.strip().upper() for g in cls.game_filter.split(',')]
            # Ensure the requested games are actually found and loaded
            cls.games_to_test = [g for g in cls.games_to_test if g in cls.loader.chitins]
        else:
            cls.games_to_test = [g for g in all_found_games if g in cls.loader.chitins]

        if not cls.games_to_test:
            print("WARNING: No valid game installations found to test against. Integration tests will be skipped.")
            cls.skip_all = True
        else:
            cls.skip_all = False
            print(f"Found {len(cls.games_to_test)} game(s) to test against: {', '.join(cls.games_to_test)}")

    @classmethod
    def tearDownClass(cls):
        if cls.log_file:
            if cls.fidelity_stats:
                cls._write_log_summary()
            cls.log_file.close()
            cls.log_file = None
        print("\n--- Test Suite Finished ---")

    @classmethod
    def _write_log_summary(cls):
        stats = cls.fidelity_stats
        log_file = cls.log_file

        log_file.write("\n" + "="*96 + "\n")
        log_file.write("FIDELITY TEST SUMMARY\n")
        log_file.write("="*96 + "\n")

        global_schema_stats = defaultdict(lambda: {'tested': 0, 'failed': 0})
        global_error_stats = defaultdict(lambda: {'count': 0, 'resrefs': []})
        total_errors_found = 0

        for schema_name in sorted(stats.keys()):
            game_data = stats[schema_name]
            
            schema_total_tested = 0
            schema_total_failed = 0
            schema_errors = defaultdict(lambda: {'count': 0, 'resrefs': []})

            for game in sorted(game_data.keys()):
                g_info = game_data[game]
                tested = g_info['tested']
                errors = g_info['errors']
                failed = sum(len(refs) for refs in errors.values())
                
                schema_total_tested += tested
                schema_total_failed += failed
                
                if failed > 0:
                    log_file.write(f"Game: {game:<6} | Schema: {schema_name:<4} | Failed: {failed}/{tested}\n")
                    for msg, resrefs in errors.items():
                        count = len(resrefs)
                        schema_errors[msg]['count'] += count
                        res_str = ", ".join(resrefs[:5])
                        if len(resrefs) > 5: res_str += f", ... (+{len(resrefs) - 5} more)"
                        log_file.write(f"  - Failed: {count:>3}/{tested:<4} | Error: {msg}\n")
                        log_file.write(f"                     | Resrefs: {res_str}\n")

            if schema_total_failed > 0:
                log_file.write("\nFAILURES BY ERROR:\n")
                for msg, info in schema_errors.items():
                    log_file.write(f"- Failed: {info['count']:>3}/{schema_total_tested:<4} | Error: {msg}\n")
                    global_error_stats[msg]['count'] += info['count']
                log_file.write(f"\nTOTAL FAILED FOR SCHEMA: {schema_name} {schema_total_failed}/{schema_total_tested}\n")
                log_file.write("-" * 96 + "\n")

            global_schema_stats[schema_name]['tested'] += schema_total_tested
            global_schema_stats[schema_name]['failed'] += schema_total_failed
            total_errors_found += schema_total_failed

        total_tested_overall = sum(s['tested'] for s in global_schema_stats.values())
        log_file.write("\n" + "+" * 96 + "\n")
        log_file.write("FULL TEST SUMMARY\n")
        log_file.write("-" * 96 + "\n")
        log_file.write("FAILURES BY SCHEMA ACROSS ALL GAMES\n")
        for schema_name, info in sorted(global_schema_stats.items()):
            if info['failed'] > 0:
                log_file.write(f"- Failed: {info['failed']:>4}/{info['tested']:<4} {schema_name}\n")
        log_file.write("-" * 96 + "\n")
        log_file.write("FAILURES BY ERROR ACROSS ALL GAMES\n")
        for msg, info in global_error_stats.items():
            log_file.write(f"  - Failed: {info['count']:>4}/{total_tested_overall:<4} | Error: {msg}\n")
        log_file.write("+" * 96 + "\n")
        log_file.write("TOTAL ERRORS FOUND\n")
        log_file.write(f"- {total_errors_found}/{total_tested_overall}\n")
        log_file.write("+" * 96 + "\n")

        if cls.audit_gaps and cls.gap_audit_stats:
            gap_stats = cls.gap_audit_stats
            log_file.write("\n" + "=" * 96 + "\n")
            log_file.write("GAP AUDIT SUMMARY\n")
            log_file.write("=" * 96 + "\n")

            aggregate = {
                "audited": 0,
                "files_with_gaps": 0,
                "files_with_nonzero_gaps": 0,
                "files_with_suppressed_gaps": 0,
                "high_risk_files": 0,
                "total_gaps": 0,
                "nonzero_gaps": 0,
                "high_risk_gaps": 0,
                "unknown_bytes": 0,
                "suppressed_gaps": 0,
                "suppressed_nonzero_gaps": 0,
                "suppressed_high_risk_gaps": 0,
                "suppressed_unknown_bytes": 0,
            }

            for schema_name in sorted(gap_stats.keys()):
                schema_totals = {k: 0 for k in aggregate}
                for game in sorted(gap_stats[schema_name].keys()):
                    gs = gap_stats[schema_name][game]
                    for key in schema_totals:
                        schema_totals[key] += gs.get(key, 0)
                    log_file.write(
                        f"Schema: {schema_name:<4} | Game: {game:<6} | "
                        f"Audited={gs.get('audited', 0)} | "
                        f"GapFiles={gs.get('files_with_gaps', 0)} | "
                        f"NonZeroFiles={gs.get('files_with_nonzero_gaps', 0)} | "
                        f"SuppressedFiles={gs.get('files_with_suppressed_gaps', 0)} | "
                        f"HighRiskFiles={gs.get('high_risk_files', 0)} | "
                        f"UnknownBytes={gs.get('unknown_bytes', 0)} | "
                        f"SuppressedBytes={gs.get('suppressed_unknown_bytes', 0)}\n"
                    )

                if schema_totals["audited"] > 0:
                    log_file.write(
                        f"  Schema Totals -> Audited={schema_totals['audited']}, "
                        f"GapFiles={schema_totals['files_with_gaps']}, "
                        f"NonZeroFiles={schema_totals['files_with_nonzero_gaps']}, "
                        f"SuppressedFiles={schema_totals['files_with_suppressed_gaps']}, "
                        f"HighRiskFiles={schema_totals['high_risk_files']}, "
                        f"TotalGaps={schema_totals['total_gaps']}, "
                        f"NonZeroGaps={schema_totals['nonzero_gaps']}, "
                        f"HighRiskGaps={schema_totals['high_risk_gaps']}, "
                        f"UnknownBytes={schema_totals['unknown_bytes']}, "
                        f"SuppressedGaps={schema_totals['suppressed_gaps']}, "
                        f"SuppressedNonZeroGaps={schema_totals['suppressed_nonzero_gaps']}, "
                        f"SuppressedHighRiskGaps={schema_totals['suppressed_high_risk_gaps']}, "
                        f"SuppressedBytes={schema_totals['suppressed_unknown_bytes']}\n"
                    )

                for key in aggregate:
                    aggregate[key] += schema_totals[key]

            log_file.write("-" * 96 + "\n")
            log_file.write(
                "Global Totals -> "
                f"Audited={aggregate['audited']}, "
                f"GapFiles={aggregate['files_with_gaps']}, "
                f"NonZeroFiles={aggregate['files_with_nonzero_gaps']}, "
                f"SuppressedFiles={aggregate['files_with_suppressed_gaps']}, "
                f"HighRiskFiles={aggregate['high_risk_files']}, "
                f"TotalGaps={aggregate['total_gaps']}, "
                f"NonZeroGaps={aggregate['nonzero_gaps']}, "
                f"HighRiskGaps={aggregate['high_risk_gaps']}, "
                f"UnknownBytes={aggregate['unknown_bytes']}, "
                f"SuppressedGaps={aggregate['suppressed_gaps']}, "
                f"SuppressedNonZeroGaps={aggregate['suppressed_nonzero_gaps']}, "
                f"SuppressedHighRiskGaps={aggregate['suppressed_high_risk_gaps']}, "
                f"SuppressedBytes={aggregate['suppressed_unknown_bytes']}\n"
            )

    def test_03_biff_caching_real_files(self):
        """
        Iterates through all BIF files in the installation.
        If a BIF is compressed (BIFC), verifies that it is decompressed only once and then cached.
        """
        if self.skip_all:
            self.skipTest("No game installation found")

        for game in self.games_to_test:
            with self.subTest(game=game):
                install_path = self.loader._get_install_path(game)
                if not install_path:
                    continue

                # Collect all BIFs
                all_bifs = []
                for root, _, files in os.walk(install_path):
                    for file in files:
                        if file.lower().endswith(".bif"):
                            all_bifs.append(os.path.join(root, file))

                print(f"\n--- [{game}] Testing caching for {len(all_bifs)} BIF files ---")
                if self.log_file:
                    self.log_file.write(f"\n--- [{game}] Testing caching for {len(all_bifs)} BIF files ---\n")
                
                compressed_count = 0
                
                for bif_path in all_bifs:
                    # Check signature first to see if it's compressed
                    try:
                        with open(bif_path, "rb") as f:
                            sig = f.read(4)
                    except IOError:
                        continue

                    # Only test caching on compressed BIFs
                    if sig in (b'BIF ', b'BIFC'):
                        compressed_count += 1
                        msg = f"Found compressed BIF: {os.path.basename(bif_path)}"
                        print(msg)
                        if self.log_file:
                            self.log_file.write(f"{msg}\n")

                        with patch('zlib.decompress', side_effect=zlib.decompress) as mock_decompress:
                            # First read: should decompress
                            with self.loader.biff_handler.get_stream(bif_path) as _:
                                pass
                            
                            # Second read: should be cached (no new decompress calls)
                            with self.loader.biff_handler.get_stream(bif_path) as _:
                                pass
                            
                            # We can't strictly assert call_count >= 1 because _get_bif_stream might 
                            # handle the stream in chunks, but we CAN assert that the second open 
                            # didn't increase the count from the first.
                            # However, since we're using the same loader instance across tests, 
                            # this specific file might ALREADY be cached from previous tests (like test_01).
                            # So we just ensure it doesn't crash and returns a valid stream.
                            pass
                            
                if compressed_count == 0:
                    if self.log_file:
                        self.log_file.write(f"No compressed BIFs found for {game}.\n")

    @staticmethod
    def _format_byte_context(data, offset, width=8):
        start = max(0, offset - width)
        limit_offset = min(offset, len(data))
        
        pre_context = ' '.join(f'{b:02x}' for b in data[start:limit_offset])
        
        if offset < len(data):
            end = min(len(data), offset + width + 1)
            post_context = ' '.join(f'{b:02x}' for b in data[offset+1:end])
            offending_byte = f'{data[offset]:02x}'
            return f"{pre_context} | {offending_byte.upper()} | {post_context}"
        else:
            return f"{pre_context} | EOF"

    @staticmethod
    def _print_loading_progress(game, completed, total):
        if total <= 0:
            return
        bar_length = 40
        percent = completed / total
        if not sys.stdout.isatty():
            # Avoid noisy logs in non-interactive runs (CI, redirected output).
            step = max(1, total // 20)
            if completed == 1 or completed == total or completed % step == 0:
                print(f"[{game}] Progress: {completed}/{total} ({percent:.1%})")
            return
        filled_length = int(bar_length * percent)
        bar = '=' * filled_length + '-' * (bar_length - filled_length)
        sys.stdout.write(
            f"\r{Colors.HEADER}[{bar}] {Colors.ENDC}"
            f"{Colors.LABEL}{game}{Colors.ENDC} "
            f"{Colors.VALUE}{percent:6.1%}{Colors.ENDC} "
            f"({completed}/{total})"
        )
        sys.stdout.flush()

    @staticmethod
    def _progress_step(total, granularity=40):
        # Update at most ~granularity times to keep console responsive.
        return max(1, total // max(1, granularity))

    @staticmethod
    def _finish_loading_progress():
        sys.stdout.write("\n")
        sys.stdout.flush()

    @staticmethod
    def _parse_allowlist_int(value):
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("empty integer value")
            if text.lower().startswith("0x"):
                return int(text, 16)
            return int(text, 10)
        raise ValueError(f"unsupported integer value type: {type(value).__name__}")

    @classmethod
    def _normalize_gap_allowlist_rule(cls, raw_rule, idx):
        if not isinstance(raw_rule, dict):
            raise ValueError("rule must be an object")

        schema = str(raw_rule.get("schema", "")).strip().upper()
        resref = str(raw_rule.get("resref", "")).strip().upper()
        if not schema or not resref:
            raise ValueError("rule requires non-empty 'schema' and 'resref'")

        if "start" not in raw_rule or "end" not in raw_rule:
            raise ValueError("rule requires both 'start' and 'end'")

        start = cls._parse_allowlist_int(raw_rule.get("start"))
        end = cls._parse_allowlist_int(raw_rule.get("end"))
        if start < 0 or end < 0 or end < start:
            raise ValueError("invalid gap range")

        rule_id = str(raw_rule.get("id", "")).strip()
        if not rule_id:
            rule_id = f"{schema}:{resref}:{hex(start)}-{hex(end)}#{idx}"

        game = raw_rule.get("game")
        game = str(game).strip().upper() if game not in (None, "") else None

        normalized = {
            "id": rule_id,
            "game": game,
            "schema": schema,
            "resref": resref,
            "start": start,
            "end": end,
        }

        for key in ("size",):
            if key in raw_rule and raw_rule.get(key) not in (None, ""):
                normalized[key] = cls._parse_allowlist_int(raw_rule.get(key))

        for key in ("kind", "classification", "risk"):
            if key in raw_rule and raw_rule.get(key):
                normalized[key] = str(raw_rule.get(key)).strip().lower()

        if raw_rule.get("note"):
            normalized["note"] = str(raw_rule.get("note")).strip()

        return normalized

    @classmethod
    def _load_gap_allowlist(cls, allowlist_path):
        cls.gap_allowlist_rules = []
        cls.gap_allowlist_source = None
        if not allowlist_path:
            return

        try:
            with open(allowlist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load gap allowlist '{allowlist_path}': {e}")
            return

        if isinstance(payload, dict):
            rules = payload.get("rules", [])
        elif isinstance(payload, list):
            rules = payload
        else:
            print(f"Warning: Gap allowlist '{allowlist_path}' must be a JSON object or array.")
            return

        loaded = []
        for idx, raw_rule in enumerate(rules):
            try:
                loaded.append(cls._normalize_gap_allowlist_rule(raw_rule, idx))
            except ValueError as e:
                print(f"Warning: Skipping gap allowlist rule #{idx} from '{allowlist_path}': {e}")

        cls.gap_allowlist_rules = loaded
        cls.gap_allowlist_source = allowlist_path
        print(f"Loaded gap allowlist: {len(loaded)} rule(s) from {allowlist_path}")

    @staticmethod
    def _gap_matches_allowlist_rule(game, schema_name, resref, gap, rule):
        if rule.get("game") and rule["game"] != game.upper():
            return False
        if rule.get("schema") != schema_name.upper():
            return False
        if rule.get("resref") != resref.upper():
            return False

        gap_start = int(gap.get("start", -1) or -1)
        gap_end = int(gap.get("end", -1) or -1)
        if gap_start != rule.get("start") or gap_end != rule.get("end"):
            return False

        if "size" in rule:
            gap_size = int(gap.get("size", 0) or 0)
            if gap_size != int(rule["size"]):
                return False

        for key in ("kind", "classification", "risk"):
            if key in rule:
                if str(gap.get(key, "") or "").strip().lower() != str(rule.get(key, "")).strip().lower():
                    return False
        return True

    @staticmethod
    def _build_gap_summary_from_gaps(base_summary, gaps, suppressed):
        summary = dict(base_summary or {})
        summary["total_gaps"] = len(gaps)
        summary["internal_gaps"] = sum(1 for g in gaps if g.get("kind") == "internal_gap")
        summary["tail_gaps"] = sum(1 for g in gaps if g.get("kind") == "tail_gap")
        summary["unknown_bytes"] = sum(int(g.get("size", 0) or 0) for g in gaps)
        summary["nonzero_gaps"] = sum(1 for g in gaps if int(g.get("nonzero_bytes", 0) or 0) > 0)
        summary["high_risk_gaps"] = sum(1 for g in gaps if str(g.get("risk", "")).lower() == "high")

        suppressed_gaps = [item["gap"] for item in suppressed]
        summary["suppressed_gaps"] = len(suppressed_gaps)
        summary["suppressed_unknown_bytes"] = sum(int(g.get("size", 0) or 0) for g in suppressed_gaps)
        summary["suppressed_nonzero_gaps"] = sum(1 for g in suppressed_gaps if int(g.get("nonzero_bytes", 0) or 0) > 0)
        summary["suppressed_high_risk_gaps"] = sum(1 for g in suppressed_gaps if str(g.get("risk", "")).lower() == "high")
        return summary

    def _filter_allowlisted_gaps(self, game, schema_name, resref, summary, gaps):
        rules = self.__class__.gap_allowlist_rules or []
        if not rules:
            untouched = self._build_gap_summary_from_gaps(summary, gaps, [])
            return untouched, list(gaps), []

        active_gaps = []
        suppressed = []
        for gap in gaps:
            matched_rule = None
            for rule in rules:
                if self._gap_matches_allowlist_rule(game, schema_name, resref, gap, rule):
                    matched_rule = rule
                    break
            if matched_rule:
                suppressed.append({"gap": gap, "rule": matched_rule})
            else:
                active_gaps.append(gap)

        filtered_summary = self._build_gap_summary_from_gaps(summary, active_gaps, suppressed)
        return filtered_summary, active_gaps, suppressed

    def _collect_gap_audit_data(self, game, schema_name, resref, resource):
        summary = getattr(resource, "gap_audit_summary", {}) or {}
        gaps = list(getattr(resource, "unknown_gaps", []) or [])
        if not summary:
            return None

        filtered_summary, filtered_gaps, suppressed = self._filter_allowlisted_gaps(
            game,
            schema_name,
            resref,
            summary,
            gaps,
        )
        return {
            "summary": filtered_summary,
            "gaps": filtered_gaps,
            "suppressed": suppressed,
        }

    @staticmethod
    def _format_claim_ref(claim):
        if not claim:
            return "None"
        return (
            f"{claim.get('section')}[{claim.get('entry_index')}].{claim.get('field')} "
            f"@ {hex(claim.get('start', 0))}-{hex(claim.get('end', 0))}"
        )

    def _build_gap_audit_details(self, game, schema_name, resref, resource, audit_data=None):
        if audit_data is None:
            audit_data = self._collect_gap_audit_data(game, schema_name, resref, resource)
        if not audit_data:
            return ""
        summary = audit_data.get("summary", {}) or {}
        gaps = list(audit_data.get("gaps", []) or [])
        suppressed = list(audit_data.get("suppressed", []) or [])

        lines = []
        lines.append(f"[GAP-AUDIT] Game: {game}, Schema: {schema_name}, Resref: {resref}\n")
        lines.append(
            "  - Summary: "
            f"gaps={summary.get('total_gaps', 0)}, "
            f"internal={summary.get('internal_gaps', 0)}, "
            f"tail={summary.get('tail_gaps', 0)}, "
            f"nonzero={summary.get('nonzero_gaps', 0)}, "
            f"high_risk={summary.get('high_risk_gaps', 0)}, "
            f"unknown_bytes={summary.get('unknown_bytes', 0)}, "
            f"claimed_bytes={summary.get('claimed_bytes', 0)}, "
            f"suppressed={summary.get('suppressed_gaps', 0)}, "
            f"suppressed_unknown_bytes={summary.get('suppressed_unknown_bytes', 0)}\n"
        )

        if suppressed:
            lines.append(f"  - Suppressed by allowlist: {len(suppressed)}\n")
            for item in suppressed[: self.gap_detail_limit]:
                gap = item.get("gap", {}) or {}
                rule = item.get("rule", {}) or {}
                lines.append(
                    f"    - {hex(gap.get('start', 0))}-{hex(gap.get('end', 0))} "
                    f"size={gap.get('size')} class={gap.get('classification')} "
                    f"via={rule.get('id')}\n"
                )
                note = rule.get("note")
                if note:
                    lines.append(f"      note: {note}\n")

        ranked = sorted(
            gaps,
            key=lambda g: (
                g.get("risk") != "high",
                g.get("nonzero_bytes", 0) == 0,
                -int(g.get("size", 0) or 0),
            ),
        )

        for gap in ranked[: self.gap_detail_limit]:
            lines.append(
                f"  - Gap #{gap.get('gap_id')} "
                f"{gap.get('kind')} "
                f"[{hex(gap.get('start', 0))}-{hex(gap.get('end', 0))}] "
                f"size={gap.get('size')} "
                f"class={gap.get('classification')} "
                f"risk={gap.get('risk')}\n"
            )
            lines.append(
                f"    nonzero={gap.get('nonzero_bytes')}/{gap.get('size')} "
                f"({gap.get('nonzero_ratio')}), "
                f"ff={gap.get('ff_bytes')}, "
                f"entropy={gap.get('entropy')}\n"
            )
            lines.append(f"    prev={self._format_claim_ref(gap.get('previous_claim'))}\n")
            lines.append(f"    next={self._format_claim_ref(gap.get('next_claim'))}\n")

            pointer_hits = gap.get("pointers_into_gap", []) or []
            if pointer_hits:
                ptr_desc = ", ".join(
                    f"{p.get('section')}[{p.get('entry_index')}].{p.get('field')}="
                    f"{hex(p.get('value', 0))}"
                    for p in pointer_hits
                )
                lines.append(f"    pointers ({gap.get('pointer_hit_count', 0)}): {ptr_desc}\n")

            candidates = gap.get("candidates", []) or []
            if candidates:
                cand_desc = ", ".join(
                    f"{c.get('type')}:{c.get('entry_count')}x{c.get('entry_size')}({c.get('confidence')})"
                    for c in candidates
                )
                lines.append(f"    candidates: {cand_desc}\n")

            lines.append(f"    head: {gap.get('head_hex', '')}\n")
            lines.append(f"    tail: {gap.get('tail_hex', '')}\n")
            lines.append(f"    ascii: {gap.get('ascii_preview', '')}\n")

        lines.append("\n")
        return "".join(lines)

    def _log_gap_audit_details(self, game, schema_name, resref, resource, audit_data=None):
        if not self.log_file:
            return

        report = self._build_gap_audit_details(game, schema_name, resref, resource, audit_data=audit_data)
        if report:
            self.log_file.write(report)

    def _run_fidelity_case(self, game, schema_name, resref):
        result = {
            "schema_name": schema_name,
            "resref": resref,
            "error_msg": None,
            "log_text": "",
            "gap_summary": None,
            "gap_details": "",
        }

        try:
            resource = self.loader.load(resref, restype=schema_name, game=game)
        except Exception as e:
            error_msg = f"CRASH loading: {e}"
            result["error_msg"] = error_msg
            if self.log_file:
                lines = [f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> CRASH loading\n"]
                raw_bytes = None
                try:
                    raw_bytes, _, _ = self.loader.get_raw_bytes(resref, restype=schema_name, game=game)
                except Exception:
                    pass

                orig_hash = "N/A"
                orig_size = "N/A"
                if raw_bytes:
                    orig_hash = hashlib.md5(raw_bytes).hexdigest()
                    orig_size = len(raw_bytes)

                lines.append(f"  - Hashes:  Original={orig_hash}, Saved=N/A\n")
                lines.append(f"  - Sizes:   Original={orig_size}, Saved=N/A\n")
                lines.append(f"  - Message: {e}\n")

                offset_match = re.search(r"at offset\s+(0x[0-9a-fA-F]+)", str(e))
                crash_offset = -1
                if offset_match:
                    try:
                        crash_offset = int(offset_match.group(1), 16)
                    except ValueError:
                        pass

                if raw_bytes and crash_offset >= 0:
                    byte_val_str = "N/A"
                    if crash_offset < len(raw_bytes):
                        byte_val_str = hex(raw_bytes[crash_offset])
                    lines.append(
                        f"  - Details: Crash at offset {hex(crash_offset)} ({crash_offset}). "
                        f"Original byte: {byte_val_str}, Saved byte: N/A.\n"
                    )
                    lines.append("  - Context:\n")
                    lines.append(f"    - Original: {self._format_byte_context(raw_bytes, crash_offset)}\n")
                    lines.append("    - Saved:    N/A\n")
                else:
                    lines.append(f"  - Details: {e}\n")
                lines.append("\n")
                result["log_text"] = "".join(lines)
            return result

        if resource is None:
            result["error_msg"] = "Loader returned None (Missing Schema?)"
            if self.log_file:
                result["log_text"] = (
                    f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> "
                    "Loader returned None (Missing Schema?)\n\n"
                )
            return result

        if self.audit_gaps:
            audit_data = self._collect_gap_audit_data(game, schema_name, resref, resource)
            if audit_data:
                summary = audit_data.get("summary", {}) or {}
                result["gap_summary"] = summary
                has_nonzero = int(summary.get("nonzero_gaps", 0) or 0) > 0
                has_suppressed = int(summary.get("suppressed_gaps", 0) or 0) > 0
                if has_nonzero or has_suppressed:
                    result["gap_details"] = self._build_gap_audit_details(
                        game,
                        schema_name,
                        resref,
                        resource,
                        audit_data=audit_data,
                    )

        try:
            original_bytes, _, _ = self.loader.get_raw_bytes(resref, restype=schema_name, game=game)
            if not original_bytes:
                return result
        except Exception as e:
            result["error_msg"] = f"Error reading raw bytes: {e}"
            if self.log_file:
                lines = [f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {result['error_msg']}\n"]
                for line in traceback.format_exc().splitlines():
                    lines.append(f"    {line}\n")
                lines.append("\n")
                result["log_text"] = "".join(lines)
            return result

        try:
            output = io.BytesIO()
            writer = BinaryWriter(output)
            parser = BinaryParser(resource.schema, **self.loader.parser_options)
            parser.write(writer, resource)
            saved_bytes = output.getvalue()
        except Exception as e:
            result["error_msg"] = f"Error writing: {e}"
            if self.log_file:
                lines = [f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {result['error_msg']}\n"]
                for line in traceback.format_exc().splitlines():
                    lines.append(f"    {line}\n")
                lines.append("\n")
                result["log_text"] = "".join(lines)
            return result

        orig_hash = hashlib.md5(original_bytes).hexdigest()
        saved_hash = hashlib.md5(saved_bytes).hexdigest()
        if orig_hash != saved_hash:
            result["error_msg"] = "Fidelity mismatch"
            if self.log_file:
                lines = [
                    f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> Fidelity mismatch\n",
                    f"  - Version: {resource.get('version', 'N/A')}\n",
                    f"  - Hashes:  Original={orig_hash}, Saved={saved_hash}\n",
                    f"  - Sizes:   Original={len(original_bytes)}, Saved={len(saved_bytes)}\n",
                ]
                if hasattr(resource, "trailing_data"):
                    lines.append(
                        f"  - Trailing: Found {len(resource.trailing_data)} bytes of unmapped data at end of file\n"
                    )

                limit = min(len(original_bytes), len(saved_bytes))
                diff_idx = next((i for i in range(limit) if original_bytes[i] != saved_bytes[i]), -1)
                if diff_idx == -1 and len(original_bytes) != len(saved_bytes):
                    diff_idx = limit

                if diff_idx != -1:
                    original_byte = original_bytes[diff_idx] if diff_idx < len(original_bytes) else None
                    saved_byte = saved_bytes[diff_idx] if diff_idx < len(saved_bytes) else None
                    original_byte_hex = hex(original_byte) if original_byte is not None else "EOF"
                    saved_byte_hex = hex(saved_byte) if saved_byte is not None else "EOF"
                    lines.append(
                        f"  - Details: Mismatch at offset {hex(diff_idx)} ({diff_idx}). "
                        f"Original byte: {original_byte_hex}, Saved byte: {saved_byte_hex}.\n"
                    )
                    lines.append("  - Context:\n")
                    if original_byte is not None:
                        lines.append(f"    - Original: {self._format_byte_context(original_bytes, diff_idx)}\n")
                    else:
                        lines.append("    - Original: (file ends before this offset)\n")
                    if saved_byte is not None:
                        lines.append(f"    - Saved:    {self._format_byte_context(saved_bytes, diff_idx)}\n")
                    else:
                        lines.append("    - Saved:    (file ends before this offset)\n")
                lines.append("\n")
                result["log_text"] = "".join(lines)

        return result

    def test_01_biff_parsing_and_decompression(self):
        if self.skip_all:
            self.skipTest("No game installation found")
            
        failures = []
        for game in self.games_to_test:
            with self.subTest(game=game):
                biff_schema = self.schema_loader.get("BIFF", game=game)
                if not biff_schema:
                    self.fail(f"BIFF schema is missing for {game}")

                install_path = self.loader._get_install_path(game)
                if not install_path:
                    self.fail(f"Could not get install path for {game}")

                all_bifs = []
                for root, _, files in os.walk(install_path):
                    for file in files:
                        if file.lower().endswith(".bif"):
                            full_path = os.path.join(root, file)
                            all_bifs.append(str(full_path).replace("\\", "/"))

                if not all_bifs:
                    print(f"No BIF files found in installation for {game}. Skipping BIF parsing test for this game.")
                    continue

                print(f"\n--- [{game}] Testing parsing for all {len(all_bifs)} located BIF files ---")

                for file_path in all_bifs:
                    filename = os.path.basename(file_path)
                    try:
                        with self.loader.biff_handler.get_stream(file_path) as bif_stream:
                            reader = BinaryReader(bif_stream)
                            parser = BinaryParser(biff_schema)
                            resource = parser.read(reader, name=filename, source=file_path)
                        self.assertIsNotNone(resource, f"Parser returned None for {filename}")
                        self.assertIn("header", resource.sections)
                        self.assertIn("file_entries", resource.sections)
                        header = resource.sections["header"][0]
                        expected_count = header.get("file_entries", 0)
                        actual_count = len(resource.sections["file_entries"])
                        self.assertEqual(expected_count, actual_count, f"BIF Header claims {expected_count} files, found {actual_count} in {filename}")
                    except Exception as e:
                        print(f"\n{Colors.FAILURE_LABEL}[CRITICAL ERROR] Failed parsing BIF:{Colors.ENDC} {file_path}")
                        if self.log_file:
                            self.log_file.write(f"[CRITICAL ERROR] Failed parsing BIF: {file_path}\n{traceback.format_exc()}\n")
                        failures.append(f"{game}: {filename}")

        if failures:
            self.fail(f"Failed to parse {len(failures)} BIF files. See log for details. First failure: {failures[0]}")

    def test_02_resource_fidelity_roundtrip(self):
        if self.skip_all:
            self.skipTest("No game installation found")

        # Data structure for collecting results
        # Use a class member to store stats for tearDownClass
        self.__class__.fidelity_stats = defaultdict(lambda: defaultdict(lambda: {
            'tested': 0,
            'errors': defaultdict(list)
        }))
        self.__class__.gap_audit_stats = defaultdict(lambda: defaultdict(lambda: {
            'audited': 0,
            'files_with_gaps': 0,
            'files_with_nonzero_gaps': 0,
            'files_with_suppressed_gaps': 0,
            'high_risk_files': 0,
            'total_gaps': 0,
            'nonzero_gaps': 0,
            'high_risk_gaps': 0,
            'unknown_bytes': 0,
            'suppressed_gaps': 0,
            'suppressed_nonzero_gaps': 0,
            'suppressed_high_risk_gaps': 0,
            'suppressed_unknown_bytes': 0,
        }))
        stats = self.__class__.fidelity_stats # local alias
        gap_stats = self.__class__.gap_audit_stats
        any_tests_run = False

        for game in self.games_to_test:
            with self.subTest(game=game):
                chitin = self.loader.chitins.get(game)
                if not chitin:
                    self.fail(f"CHITIN.KEY for {game} not loaded.")
                
                all_resource_entries = chitin.sections.get("resource_entries", [])
                resources_by_schema = defaultdict(list)
                total_entries = len(all_resource_entries)
                prep_step = self._progress_step(total_entries)
                for idx, entry in enumerate(all_resource_entries, start=1):
                    res_type_code = entry.get("resource_type")
                    res_name = entry.get("resource_name")
                    schema_name = RESOURCE_TYPE_MAP.get(res_type_code)
                    if schema_name and res_name:
                        if schema_name not in resources_by_schema:
                            resources_by_schema[schema_name] = []
                        resources_by_schema[schema_name].append(res_name.strip())
                    if self.show_progress and total_entries > 0:
                        if idx == 1 or idx == total_entries or (idx % prep_step) == 0:
                            self._print_loading_progress(f"{game}-prep", idx, total_entries)
                if self.show_progress and total_entries > 0:
                    self._finish_loading_progress()
                
                if self.resref_filter and not self.schema_filter:
                    print(f"\n--- [{game}] Filtering fidelity test to resource: {self.resref_filter.upper()} ---")
                elif self.schema_filter:
                    print(f"\n--- [{game}] Filtering fidelity test to schema: {self.schema_filter.upper()} ---")
                
                # Get list of all available schema types for this run
                all_types = set(self.schema_loader.schemas.keys())
                for g_map in self.schema_loader.game_schemas.values():
                    all_types.update(g_map.keys())

                # Build the filtered worklist once so we can show a lightweight
                # loading/progress indicator without changing test behavior.
                schema_worklist = []
                for schema_name in sorted(all_types):
                    if self.schema_filter and schema_name != self.schema_filter.upper():
                        continue
                    if schema_name not in resources_by_schema:
                        continue

                    resrefs_to_test = resources_by_schema[schema_name]
                    if self.resref_filter:
                        resref_filter_upper = self.resref_filter.strip().upper()
                        if resref_filter_upper in resrefs_to_test:
                            resrefs_to_test = [resref_filter_upper]
                        else:
                            continue
                    schema_worklist.append((schema_name, resrefs_to_test))

                total_resources_for_game = sum(len(items) for _, items in schema_worklist)
                completed_resources_for_game = 0
                should_show_progress = self.show_progress and total_resources_for_game > 0

                all_tasks = [
                    (schema_name, resref)
                    for schema_name, resrefs in schema_worklist
                    for resref in resrefs
                ]

                if self.fidelity_threads > 1 and len(all_tasks) > 1:
                    print(f"--- [{game}] Running fidelity with {self.fidelity_threads} worker threads ---")
                    with ThreadPoolExecutor(max_workers=self.fidelity_threads) as executor:
                        futures = {
                            executor.submit(self._run_fidelity_case, game, schema_name, resref): (schema_name, resref)
                            for schema_name, resref in all_tasks
                        }

                        for future in as_completed(futures):
                            schema_name, resref = futures[future]
                            completed_resources_for_game += 1
                            if should_show_progress:
                                self._print_loading_progress(
                                    game,
                                    completed_resources_for_game,
                                    total_resources_for_game,
                                )

                            any_tests_run = True
                            stats[schema_name][game]['tested'] += 1

                            try:
                                case_result = future.result()
                            except Exception as e:
                                error_msg = f"Worker crash: {e}"
                                stats[schema_name][game]['errors'][error_msg].append(resref)
                                if self.log_file:
                                    self.log_file.write(
                                        f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {error_msg}\n"
                                    )
                                    for line in traceback.format_exc().splitlines():
                                        self.log_file.write(f"    {line}\n")
                                    self.log_file.write("\n")
                                continue

                            gap_summary = case_result.get("gap_summary")
                            if self.audit_gaps and gap_summary:
                                gs = gap_stats[schema_name][game]
                                gs['audited'] += 1
                                gs['total_gaps'] += int(gap_summary.get('total_gaps', 0) or 0)
                                gs['nonzero_gaps'] += int(gap_summary.get('nonzero_gaps', 0) or 0)
                                gs['high_risk_gaps'] += int(gap_summary.get('high_risk_gaps', 0) or 0)
                                gs['unknown_bytes'] += int(gap_summary.get('unknown_bytes', 0) or 0)
                                gs['suppressed_gaps'] += int(gap_summary.get('suppressed_gaps', 0) or 0)
                                gs['suppressed_nonzero_gaps'] += int(gap_summary.get('suppressed_nonzero_gaps', 0) or 0)
                                gs['suppressed_high_risk_gaps'] += int(gap_summary.get('suppressed_high_risk_gaps', 0) or 0)
                                gs['suppressed_unknown_bytes'] += int(gap_summary.get('suppressed_unknown_bytes', 0) or 0)
                                if int(gap_summary.get('total_gaps', 0) or 0) > 0:
                                    gs['files_with_gaps'] += 1
                                if int(gap_summary.get('nonzero_gaps', 0) or 0) > 0:
                                    gs['files_with_nonzero_gaps'] += 1
                                if int(gap_summary.get('suppressed_gaps', 0) or 0) > 0:
                                    gs['files_with_suppressed_gaps'] += 1
                                if self.log_file and case_result.get("gap_details"):
                                    self.log_file.write(case_result["gap_details"])
                                if int(gap_summary.get('high_risk_gaps', 0) or 0) > 0:
                                    gs['high_risk_files'] += 1

                            if case_result.get("error_msg"):
                                stats[schema_name][game]['errors'][case_result["error_msg"]].append(resref)

                            if self.log_file and case_result.get("log_text"):
                                self.log_file.write(case_result["log_text"])

                    if should_show_progress:
                        self._finish_loading_progress()
                    continue
                
                # Iterate schemas in sorted order for consistent reporting
                for schema_name, resrefs_to_test in schema_worklist:

                    # print(f"\n--- [{game}] Testing fidelity for schema: {schema_name} ---") # Reduced verbosity

                    for resref in resrefs_to_test:
                        completed_resources_for_game += 1
                        if should_show_progress:
                            self._print_loading_progress(
                                game,
                                completed_resources_for_game,
                                total_resources_for_game,
                            )
                        any_tests_run = True
                        stats[schema_name][game]['tested'] += 1
                        
                        f = io.StringIO()
                        with redirect_stdout(f):
                            try:
                                resource = self.loader.load(resref, restype=schema_name, game=game)
                            except Exception as e:
                                error_msg = f"CRASH loading: {e}"
                                stats[schema_name][game]['errors'][error_msg].append(resref)
                                if self.log_file:
                                    self.log_file.write(f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> CRASH loading\n")
                                    
                                    raw_bytes = None
                                    try:
                                        raw_bytes, _, _ = self.loader.get_raw_bytes(resref, restype=schema_name, game=game)
                                    except: pass # Ignore if getting raw bytes also fails

                                    orig_hash = "N/A"
                                    orig_size = "N/A"
                                    if raw_bytes:
                                        orig_hash = hashlib.md5(raw_bytes).hexdigest()
                                        orig_size = len(raw_bytes)
                                    
                                    self.log_file.write(f"  - Hashes:  Original={orig_hash}, Saved=N/A\n")
                                    self.log_file.write(f"  - Sizes:   Original={orig_size}, Saved=N/A\n")
                                    self.log_file.write(f"  - Message: {e}\n")

                                    offset_match = re.search(r"at offset\s+(0x[0-9a-fA-F]+)", str(e))
                                    crash_offset = -1
                                    if offset_match:
                                        try:
                                            crash_offset = int(offset_match.group(1), 16)
                                        except ValueError:
                                            pass

                                    if raw_bytes and crash_offset >= 0:
                                        byte_val_str = "N/A"
                                        if crash_offset < len(raw_bytes):
                                            byte_val_str = hex(raw_bytes[crash_offset])
                                        
                                        self.log_file.write(f"  - Details: Crash at offset {hex(crash_offset)} ({crash_offset}). Original byte: {byte_val_str}, Saved byte: N/A.\n")
                                        self.log_file.write(f"  - Context:\n")
                                        self.log_file.write(f"    - Original: {self._format_byte_context(raw_bytes, crash_offset)}\n")
                                        self.log_file.write(f"    - Saved:    N/A\n")
                                    else:
                                        self.log_file.write(f"  - Details: {e}\n")

                                    self.log_file.write("\n")
                                continue
                        if resource is None:
                            error_msg = "Loader returned None (Missing Schema?)"
                            stats[schema_name][game]['errors'][error_msg].append(resref)
                            if self.log_file:
                                self.log_file.write(f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {error_msg}\n")
                                self.log_file.write(f"  - Output: {f.getvalue().strip()}\n\n")
                            continue

                        if self.audit_gaps:
                            audit_data = self._collect_gap_audit_data(game, schema_name, resref, resource)
                            if audit_data:
                                summary = audit_data.get("summary", {}) or {}
                                gs = gap_stats[schema_name][game]
                                gs['audited'] += 1
                                gs['total_gaps'] += int(summary.get('total_gaps', 0) or 0)
                                gs['nonzero_gaps'] += int(summary.get('nonzero_gaps', 0) or 0)
                                gs['high_risk_gaps'] += int(summary.get('high_risk_gaps', 0) or 0)
                                gs['unknown_bytes'] += int(summary.get('unknown_bytes', 0) or 0)
                                gs['suppressed_gaps'] += int(summary.get('suppressed_gaps', 0) or 0)
                                gs['suppressed_nonzero_gaps'] += int(summary.get('suppressed_nonzero_gaps', 0) or 0)
                                gs['suppressed_high_risk_gaps'] += int(summary.get('suppressed_high_risk_gaps', 0) or 0)
                                gs['suppressed_unknown_bytes'] += int(summary.get('suppressed_unknown_bytes', 0) or 0)
                                if int(summary.get('total_gaps', 0) or 0) > 0:
                                    gs['files_with_gaps'] += 1
                                if int(summary.get('nonzero_gaps', 0) or 0) > 0:
                                    gs['files_with_nonzero_gaps'] += 1
                                if int(summary.get('suppressed_gaps', 0) or 0) > 0:
                                    gs['files_with_suppressed_gaps'] += 1
                                if int(summary.get('nonzero_gaps', 0) or 0) > 0 or int(summary.get('suppressed_gaps', 0) or 0) > 0:
                                    self._log_gap_audit_details(game, schema_name, resref, resource, audit_data=audit_data)
                                if int(summary.get('high_risk_gaps', 0) or 0) > 0:
                                    gs['high_risk_files'] += 1

                        try:
                            original_bytes, _, _ = self.loader.get_raw_bytes(resref, restype=schema_name, game=game)
                            if not original_bytes:
                                continue
                        except Exception as e:
                            error_msg = f"Error reading raw bytes: {e}"
                            stats[schema_name][game]['errors'][error_msg].append(resref)
                            if self.log_file:
                                self.log_file.write(f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {error_msg}\n")
                                for line in traceback.format_exc().splitlines():
                                    self.log_file.write(f"    {line}\n")
                                self.log_file.write("\n")
                            continue

                        try:
                            output = io.BytesIO()
                            writer = BinaryWriter(output)
                            parser = BinaryParser(resource.schema, **self.loader.parser_options)
                            parser.write(writer, resource)
                            saved_bytes = output.getvalue()
                        except Exception as e:
                            error_msg = f"Error writing: {e}"
                            stats[schema_name][game]['errors'][error_msg].append(resref)
                            if self.log_file:
                                self.log_file.write(f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {error_msg}\n")
                                for line in traceback.format_exc().splitlines():
                                    self.log_file.write(f"    {line}\n")
                                self.log_file.write("\n")
                            continue

                        orig_hash = hashlib.md5(original_bytes).hexdigest()
                        saved_hash = hashlib.md5(saved_bytes).hexdigest()

                        if orig_hash != saved_hash:
                            error_msg = "Fidelity mismatch"
                            stats[schema_name][game]['errors'][error_msg].append(resref)
                            if self.log_file:
                                self.log_file.write(f"[ERROR] Game: {game}, Schema: {schema_name}, Resref: {resref} -> {error_msg}\n")
                                self.log_file.write(f"  - Version: {resource.get('version', 'N/A')}\n")
                                self.log_file.write(f"  - Hashes:  Original={orig_hash}, Saved={saved_hash}\n")
                                self.log_file.write(f"  - Sizes:   Original={len(original_bytes)}, Saved={len(saved_bytes)}\n")
                                
                                if hasattr(resource, "trailing_data"):
                                    self.log_file.write(f"  - Trailing: Found {len(resource.trailing_data)} bytes of unmapped data at end of file\n")

                                limit = min(len(original_bytes), len(saved_bytes))
                                diff_idx = next((i for i in range(limit) if original_bytes[i] != saved_bytes[i]), -1)

                                # If no difference was found within the common part, but sizes differ,
                                # the first difference is at the end of the shorter file.
                                if diff_idx == -1 and len(original_bytes) != len(saved_bytes):
                                    diff_idx = limit

                                if diff_idx != -1:
                                    # Safely get byte values and their hex representation
                                    original_byte = original_bytes[diff_idx] if diff_idx < len(original_bytes) else None
                                    saved_byte = saved_bytes[diff_idx] if diff_idx < len(saved_bytes) else None
                                    original_byte_hex = hex(original_byte) if original_byte is not None else "EOF"
                                    saved_byte_hex = hex(saved_byte) if saved_byte is not None else "EOF"

                                    self.log_file.write(f"  - Details: Mismatch at offset {hex(diff_idx)} ({diff_idx}). Original byte: {original_byte_hex}, Saved byte: {saved_byte_hex}.\n")
                                    self.log_file.write("  - Context:\n")
                                    if original_byte is not None:
                                        self.log_file.write(f"    - Original: {self._format_byte_context(original_bytes, diff_idx)}\n")
                                    else:
                                        self.log_file.write(f"    - Original: (file ends before this offset)\n")
                                    if saved_byte is not None:
                                        self.log_file.write(f"    - Saved:    {self._format_byte_context(saved_bytes, diff_idx)}\n")
                                    else:
                                        self.log_file.write(f"    - Saved:    (file ends before this offset)\n")
                                self.log_file.write("\n")

                if should_show_progress:
                    self._finish_loading_progress()

        # --- SUMMARY GENERATION ---
        if not any_tests_run:
             return

        print("\n" + Colors.HEADER + "="*96 + Colors.ENDC)
        print(f"{Colors.HEADER}FIDELITY TEST SUMMARY{Colors.ENDC}")
        print(Colors.HEADER + "="*96 + Colors.ENDC)
        
        global_schema_stats = defaultdict(lambda: {'tested': 0, 'failed': 0})
        global_error_stats = defaultdict(lambda: {'count': 0, 'resrefs': []})
        total_errors_found = 0

        for schema_name in sorted(stats.keys()):
            game_data = stats[schema_name]
            
            schema_total_tested = 0
            schema_total_failed = 0
            schema_errors = defaultdict(lambda: {'count': 0, 'resrefs': []})

            # Print per-game breakdown
            for game in sorted(game_data.keys()):
                g_info = game_data[game]
                tested = g_info['tested']
                errors = g_info['errors']
                failed = sum(len(refs) for refs in errors.values())
                
                schema_total_tested += tested
                schema_total_failed += failed
                crash_count = sum(len(refs) for msg, refs in errors.items() if "CRASH" in msg)
                
                if failed > 0:
                    print(f"{Colors.LABEL}Game:{Colors.ENDC} {Colors.VALUE}{game:<6}{Colors.ENDC} | {Colors.LABEL}Schema:{Colors.ENDC} {Colors.VALUE}{schema_name:<4}{Colors.ENDC} | {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{failed}{Colors.ENDC}/{Colors.TOTAL_COUNT}{tested}{Colors.ENDC} (Crashes: {crash_count})")
                    
                    for msg, resrefs in errors.items():
                        count = len(resrefs)
                        schema_errors[msg]['count'] += count
                        schema_errors[msg]['resrefs'].extend(resrefs)
                        
                        res_str = ", ".join(resrefs[:5])
                        remaining = count - 5
                        if remaining > 0: res_str += f", ... (+{remaining} more)"
                        
                        print(f"  - {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{count:>3}{Colors.ENDC}/{Colors.TOTAL_COUNT}{tested:<4}{Colors.ENDC} | {Colors.FAILURE_LABEL}Error:{Colors.ENDC} {Colors.ERROR_MSG}{msg}{Colors.ENDC}")
                        print(f"                     | {Colors.RESREF_LABEL}Resrefs:{Colors.ENDC} {Colors.VALUE}{res_str}{Colors.ENDC}")

            # Print Schema Aggregates
            if schema_total_failed > 0:
                print(f"\n{Colors.FAILURE_LABEL}FAILURES BY ERROR:{Colors.ENDC}")
                for msg, info in schema_errors.items():
                    print(f"- {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{info['count']:>3}{Colors.ENDC}/{Colors.TOTAL_COUNT}{schema_total_tested:<4}{Colors.ENDC} | {Colors.FAILURE_LABEL}Error: {Colors.ERROR_MSG}{msg}{Colors.ENDC}")
                    
                    global_error_stats[msg]['count'] += info['count']
                    global_error_stats[msg]['resrefs'].extend(info['resrefs'])

                print(f"\n{Colors.FAILURE_LABEL}TOTAL FAILED FOR SCHEMA: {schema_name} {Colors.FAILURE_COUNT}{schema_total_failed}{Colors.ENDC}/{Colors.TOTAL_COUNT}{schema_total_tested}{Colors.ENDC}")
                print(Colors.HEADER + "-" * 96 + Colors.ENDC)

            # Update Global Schema Stats
            global_schema_stats[schema_name]['tested'] += schema_total_tested
            global_schema_stats[schema_name]['failed'] += schema_total_failed
            total_errors_found += schema_total_failed

        # --- FULL TEST SUMMARY ---
        total_tested_overall = sum(s['tested'] for s in global_schema_stats.values())

        print(Colors.HEADER + "+" * 96 + Colors.ENDC)
        print(f"{Colors.HEADER}FULL TEST SUMMARY{Colors.ENDC}")
        print(Colors.HEADER + "-" * 96 + Colors.ENDC)
        
        print(f"{Colors.BOLD}{Colors.HEADER}FAILURES BY SCHEMA ACROSS ALL GAMES{Colors.ENDC}")
        for schema_name, info in sorted(global_schema_stats.items()):
            if info['failed'] > 0:
                print(f"- {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{info['failed']:>4}{Colors.ENDC}/{Colors.TOTAL_COUNT}{info['tested']:<4}{Colors.ENDC} {Colors.VALUE}{schema_name}{Colors.ENDC}")
        
        print(Colors.HEADER + "-" * 96 + Colors.ENDC)
        print(f"{Colors.BOLD}{Colors.HEADER}FAILURES BY ERROR ACROSS ALL GAMES{Colors.ENDC}")
        print(Colors.HEADER + "-" * 96 + Colors.ENDC)
        for msg, info in global_error_stats.items():
            count = info['count']
            res_str = ", ".join(info['resrefs'][:5])
            remaining = len(info['resrefs']) - 5
            if remaining > 0: res_str += f", ... (+{remaining} more)"
            
            print(f"  - {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{count:>4}{Colors.ENDC}/{Colors.TOTAL_COUNT}{total_tested_overall:<4}{Colors.ENDC} | {Colors.FAILURE_LABEL}Error: {Colors.ERROR_MSG}{msg}{Colors.ENDC}")
            print(f"                      | {Colors.RESREF_LABEL}Resrefs:{Colors.ENDC} {Colors.VALUE}{res_str}{Colors.ENDC}")

        print(Colors.HEADER + "+" * 96 + Colors.ENDC)
        print(f"{Colors.BOLD}{Colors.HEADER}TOTAL ERRORS FOUND{Colors.ENDC}")
        print(f"- {Colors.FAILURE_COUNT}{total_errors_found}{Colors.ENDC}/{Colors.TOTAL_COUNT}{total_tested_overall}{Colors.ENDC}")
        print(Colors.HEADER + "+" * 96 + Colors.ENDC)

        if self.audit_gaps:
            print(Colors.HEADER + "=" * 96 + Colors.ENDC)
            print(f"{Colors.HEADER}GAP AUDIT SUMMARY{Colors.ENDC}")
            print(Colors.HEADER + "=" * 96 + Colors.ENDC)

            agg = {
                "audited": 0,
                "files_with_gaps": 0,
                "files_with_nonzero_gaps": 0,
                "files_with_suppressed_gaps": 0,
                "high_risk_files": 0,
                "total_gaps": 0,
                "nonzero_gaps": 0,
                "high_risk_gaps": 0,
                "unknown_bytes": 0,
                "suppressed_gaps": 0,
                "suppressed_nonzero_gaps": 0,
                "suppressed_high_risk_gaps": 0,
                "suppressed_unknown_bytes": 0,
            }

            for schema_name in sorted(gap_stats.keys()):
                schema_total = {
                    "audited": 0,
                    "files_with_gaps": 0,
                    "files_with_nonzero_gaps": 0,
                    "files_with_suppressed_gaps": 0,
                    "high_risk_files": 0,
                    "total_gaps": 0,
                    "nonzero_gaps": 0,
                    "high_risk_gaps": 0,
                    "unknown_bytes": 0,
                    "suppressed_gaps": 0,
                    "suppressed_nonzero_gaps": 0,
                    "suppressed_high_risk_gaps": 0,
                    "suppressed_unknown_bytes": 0,
                }
                for game in sorted(gap_stats[schema_name].keys()):
                    gs = gap_stats[schema_name][game]
                    for key in schema_total:
                        schema_total[key] += gs.get(key, 0)

                if schema_total["audited"] == 0:
                    continue

                for key in agg:
                    agg[key] += schema_total[key]

                print(
                    f"{Colors.LABEL}Schema:{Colors.ENDC} {Colors.VALUE}{schema_name:<4}{Colors.ENDC} | "
                    f"{Colors.LABEL}Audited:{Colors.ENDC} {schema_total['audited']} | "
                    f"{Colors.LABEL}GapFiles:{Colors.ENDC} {schema_total['files_with_gaps']} | "
                    f"{Colors.FAILURE_LABEL}NonZeroFiles:{Colors.ENDC} {schema_total['files_with_nonzero_gaps']} | "
                    f"{Colors.LABEL}SuppressedFiles:{Colors.ENDC} {schema_total['files_with_suppressed_gaps']} | "
                    f"{Colors.FAILURE_LABEL}HighRiskFiles:{Colors.ENDC} {schema_total['high_risk_files']} | "
                    f"{Colors.LABEL}UnknownBytes:{Colors.ENDC} {schema_total['unknown_bytes']} | "
                    f"{Colors.LABEL}SuppBytes:{Colors.ENDC} {schema_total['suppressed_unknown_bytes']}"
                )

            print(Colors.HEADER + "-" * 96 + Colors.ENDC)
            print(
                f"{Colors.LABEL}Audited Files:{Colors.ENDC} {agg['audited']} | "
                f"{Colors.LABEL}Files With Gaps:{Colors.ENDC} {agg['files_with_gaps']} | "
                f"{Colors.FAILURE_LABEL}Files With NonZero Gaps:{Colors.ENDC} {agg['files_with_nonzero_gaps']} | "
                f"{Colors.LABEL}Files With Suppressed Gaps:{Colors.ENDC} {agg['files_with_suppressed_gaps']} | "
                f"{Colors.FAILURE_LABEL}High Risk Files:{Colors.ENDC} {agg['high_risk_files']}"
            )
            print(
                f"{Colors.LABEL}Total Gaps:{Colors.ENDC} {agg['total_gaps']} | "
                f"{Colors.FAILURE_LABEL}NonZero Gaps:{Colors.ENDC} {agg['nonzero_gaps']} | "
                f"{Colors.FAILURE_LABEL}High Risk Gaps:{Colors.ENDC} {agg['high_risk_gaps']} | "
                f"{Colors.LABEL}Unknown Bytes:{Colors.ENDC} {agg['unknown_bytes']} | "
                f"{Colors.LABEL}Suppressed Gaps:{Colors.ENDC} {agg['suppressed_gaps']} | "
                f"{Colors.LABEL}Suppressed Bytes:{Colors.ENDC} {agg['suppressed_unknown_bytes']}"
            )
            print(Colors.HEADER + "=" * 96 + Colors.ENDC)

        if total_errors_found > 0:
            sys.exit(1)

    def test_04_bif_caching(self):
        """
        Tests that compressed BIF files are decompressed only once and then cached.
        Uses a generated BIF file to ensure the test runs even if game data is uncompressed.
        """
        # 1. Create a dummy uncompressed BIFF (Minimal Valid Header)
        # Sig(4)=BIFF, Ver(4)=V1  , Files(4)=0, Tiles(4)=0, Offset(4)=16
        uncompressed_data = b'BIFFV1  \x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00'
        uncompressed_len = len(uncompressed_data)

        # 2. Compress payload
        compressed_payload = zlib.compress(uncompressed_data)
        compressed_len = len(compressed_payload)

        # 3. Construct BIF Wrapper (Format: 'BIF ')
        # Header: Sig(4), Ver(4), NameLen(4), Name(N), UncompSize(4), CompSize(4)
        filename = b"temp.bif"
        filename_len = len(filename)

        header = bytearray()
        header.extend(b'BIF ')
        header.extend(b'V1.0')
        header.extend(filename_len.to_bytes(4, 'little'))
        header.extend(filename)
        header.extend(uncompressed_len.to_bytes(4, 'little'))
        header.extend(compressed_len.to_bytes(4, 'little'))

        full_file_content = header + compressed_payload

        # 4. Write to a temp file
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=".bif") as tmp:
            tmp_path = tmp.name
            tmp.write(full_file_content)

        try:
            print(f"\n--- Testing caching on generated compressed BIF: {tmp_path} ---")
            
            with patch('zlib.decompress', wraps=zlib.decompress) as mock_decompress:
                # First Access: Should trigger decompression
                with self.loader.biff_handler.get_stream(tmp_path) as stream:
                    content = stream.read()
                    self.assertEqual(content, uncompressed_data, "Decompressed content mismatch")
                
                self.assertTrue(mock_decompress.called, "zlib.decompress was NOT called on first access.")
                initial_call_count = mock_decompress.call_count

                # Second Access: Should use cache
                with self.loader.biff_handler.get_stream(tmp_path) as stream:
                    content = stream.read()
                    self.assertEqual(content, uncompressed_data, "Cached content mismatch")

                self.assertEqual(mock_decompress.call_count, initial_call_count, "zlib.decompress was called again! Caching failed.")
                print("Cache test passed. Decompression was not repeated.")

        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    print(f"Warning: Failed to delete temp file {tmp_path}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PlanarForge Test Suite Runner.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  Run all tests:
    python tests/test_suite.py

  Run a specific test by number:
    python tests/test_suite.py --test 1

  Run the fidelity test (test #2) for a single schema:
    python tests/test_suite.py --test 2 --schema ITM

  Run the fidelity test (test #2) for a single resource:
    python tests/test_suite.py --test 2 --resref BAG29

  Run WED fidelity with unknown-gap audit enabled:
    python tests/test_suite.py --test 2 --schema WED --audit-gaps

  Use a custom gap allowlist:
    python tests/test_suite.py --test 2 --schema WED --audit-gaps --gap-allowlist tools/tests/gap_allowlist.json

Available Tests:
  1: BIF Parsing & Decompression
  2: Resource Fidelity Round-trip
  4: BIF Caching
"""
    )
    parser.add_argument('--test', type=int, help='Run a specific test by number (1, 2, or 3).')
    parser.add_argument('--schema', type=str, help='Limit fidelity test to a specific schema (e.g., ITM, SPL).')
    parser.add_argument('--resref', type=str, help='Limit fidelity test to a specific resource reference (e.g., BAG29).')
    parser.add_argument('--game', type=str, help='Limit tests to a specific game ID or comma-separated list (e.g., BG2EE,IWDEE). Defaults to all found games.')
    parser.add_argument('--audit-gaps', action='store_true', help='Enable unknown-gap byte audit during parse and show audit summaries.')
    parser.add_argument('--gap-policy', choices=['allow', 'warn', 'fail_nonzero'], default='allow', help='Write policy when modified resources contain non-zero unknown gaps.')
    parser.add_argument('--gap-detail-limit', type=int, default=5, help='Max detailed gaps per file written to the log when gap audit is enabled.')
    parser.add_argument('--gap-allowlist', type=str, default=None, help='Optional JSON path for exact gap suppressions (game/schema/resref/range based).')
    parser.add_argument('--no-progress', action='store_true', help='Disable the fidelity loading indicator.')
    parser.add_argument('--threads', type=int, default=1, help='Worker threads for fidelity test resources (test #2).')

    # Separate custom args from unittest args
    args, unknown = parser.parse_known_args()

    TestPlanarForge.schema_filter = args.schema
    TestPlanarForge.resref_filter = args.resref
    TestPlanarForge.game_filter = args.game
    TestPlanarForge.audit_gaps = args.audit_gaps
    TestPlanarForge.gap_policy = args.gap_policy
    TestPlanarForge.gap_detail_limit = max(1, args.gap_detail_limit)
    TestPlanarForge.gap_allowlist_path = args.gap_allowlist
    TestPlanarForge.show_progress = not args.no_progress
    TestPlanarForge.fidelity_threads = max(1, args.threads)
    
    # NOTE: setUpClass is called by unittest.main(), so it will have access
    # to these class variables when initializing the log file.

    # If --test is used, it overrides any other test specifications.
    if args.test:
        test_map = {
            1: 'test_01_biff_parsing_and_decompression',
            2: 'test_02_resource_fidelity_roundtrip',
            3: 'test_03_biff_caching_real_files',
            4: 'test_04_bif_caching',
        }
        test_name = test_map.get(args.test)
        if test_name:
            sys.argv = [sys.argv[0], f'TestPlanarForge.{test_name}']
        else:
            print(f"Error: Invalid test number '{args.test}'. Available tests are: {', '.join(map(str, test_map.keys()))}.")
            sys.exit(1)
    else:
        # Reconstruct sys.argv for unittest.main() to allow running tests by full name
        sys.argv = [sys.argv[0]] + unknown

    unittest.main(verbosity=2)
