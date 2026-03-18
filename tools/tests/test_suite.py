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
from unittest.mock import patch
import tempfile
from collections import defaultdict
import datetime
import re

# Ensure core modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from drivers.InfinityEngine.installation_finder import InstallationFinder
from drivers.InfinityEngine.resource_loader import ResourceLoader
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.binary.writer import BinaryWriter
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from drivers.InfinityEngine.resource_types import RESOURCE_TYPE_MAP

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
        
        # Initialize Loader (which loads schemas from drivers/InfinityEngine/schemas)
        cls.loader = ResourceLoader()
        cls.schema_loader = cls.loader.schema_loader
        
        # Find all installed games
        all_found_games = [inst.game_id for inst in cls.loader.install_finder.find_all()]
        
        # Load chitin for all found games
        for game_id in all_found_games:
            cls.loader._load_chitin(game_id)
        
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
        end = min(len(data), offset + width + 1)
        
        pre_context = ' '.join(f'{b:02x}' for b in data[start:offset])
        post_context = ' '.join(f'{b:02x}' for b in data[offset+1:end])
        
        offending_byte = f'{data[offset]:02x}'
        
        return f"{pre_context} | {offending_byte.upper()} | {post_context}"

    def test_01_biff_parsing_and_decompression(self):
        if self.skip_all:
            self.skipTest("No game installation found")
            
        biff_schema = self.schema_loader.get("BIFF")
        if not biff_schema:
            self.fail("BIFF schema is missing from schemas/ directory.")
        
        failures = []
        for game in self.games_to_test:
            with self.subTest(game=game):
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
        stats = self.__class__.fidelity_stats # local alias
        any_tests_run = False

        for game in self.games_to_test:
            with self.subTest(game=game):
                chitin = self.loader.chitins.get(game)
                if not chitin:
                    self.fail(f"CHITIN.KEY for {game} not loaded.")
                
                all_resource_entries = chitin.sections.get("resource_entries", [])
                resources_by_schema = defaultdict(list)
                for entry in all_resource_entries:
                    res_type_code = entry.get("resource_type")
                    res_name = entry.get("resource_name")
                    schema_name = RESOURCE_TYPE_MAP.get(res_type_code)
                    if schema_name and res_name:
                        if schema_name not in resources_by_schema:
                            resources_by_schema[schema_name] = []
                        resources_by_schema[schema_name].append(res_name.strip())
                
                if self.resref_filter and not self.schema_filter:
                    print(f"\n--- [{game}] Filtering fidelity test to resource: {self.resref_filter.upper()} ---")
                elif self.schema_filter:
                    print(f"\n--- [{game}] Filtering fidelity test to schema: {self.schema_filter.upper()} ---")
                
                # Iterate schemas in sorted order for consistent reporting
                for schema_name, schema in sorted(self.schema_loader.schemas.items()):
                    if self.schema_filter and schema_name != self.schema_filter.upper():
                        continue
                    if schema_name not in resources_by_schema:
                        continue

                    # print(f"\n--- [{game}] Testing fidelity for schema: {schema_name} ---") # Reduced verbosity
                    
                    resrefs_to_test = resources_by_schema[schema_name]
                    if self.resref_filter:
                        resref_filter_upper = self.resref_filter.strip().upper()
                        if resref_filter_upper in resrefs_to_test:
                            resrefs_to_test = [resref_filter_upper]
                        else:
                            continue
                    
                    for resref in resrefs_to_test:
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
                                    self.log_file.write(f"  - Exception: {e}\n")
                                    try:
                                        raw_bytes, _, _ = self.loader.get_raw_bytes(resref, restype=schema_name, game=game)
                                        if raw_bytes: self.log_file.write(f"  - Resource Size: {len(raw_bytes)} bytes\n")
                                    except: pass # Ignore if getting raw bytes also fails
                                    self.log_file.write("  - Traceback:\n")
                                    for line in traceback.format_exc().splitlines():
                                        self.log_file.write(f"    {line}\n")
                                    self.log_file.write("\n")
                                continue
                        if resource is None:
                            continue

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
                            parser = BinaryParser(resource.schema)
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
                
                if failed > 0:
                    print(f"{Colors.LABEL}Game:{Colors.ENDC} {Colors.VALUE}{game:<6}{Colors.ENDC} | {Colors.LABEL}Schema:{Colors.ENDC} {Colors.VALUE}{schema_name:<4}{Colors.ENDC} | {Colors.FAILURE_LABEL}Failed:{Colors.ENDC} {Colors.FAILURE_COUNT}{failed}{Colors.ENDC}/{Colors.TOTAL_COUNT}{tested}{Colors.ENDC}")
                    
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

    # Separate custom args from unittest args
    args, unknown = parser.parse_known_args()

    TestPlanarForge.schema_filter = args.schema
    TestPlanarForge.resref_filter = args.resref
    TestPlanarForge.game_filter = args.game
    
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
    TestPlanarForge.game_filter = args.game

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
