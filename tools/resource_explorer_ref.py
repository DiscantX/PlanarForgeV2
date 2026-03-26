#!/usr/bin/env python3
"""
resource_explorer.py

Interactive CLI resource explorer for PlanarForge.

- Builds or loads a cached index for a selected game and resource type.
- Supports full listing by type (e.g. all ITM files).
- Supports text search, then interactive selection by ResRef for inspection.
- Pretty-prints parsed resource JSON to the terminal.

Usage examples
--------------
    python tools/resource_explorer.py --list-games
    python tools/resource_explorer.py --game BG2EE --type ITM --list-type ITM
    python tools/resource_explorer.py "sword" --game BG2EE --type ITM
    python tools/resource_explorer.py "potion" --type ITM --limit 50 --no-cache
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from collections import defaultdict
from typing import Callable

try:
    import readline  # type: ignore
except Exception:
    readline = None
try:
    from prompt_toolkit import PromptSession  # type: ignore
    from prompt_toolkit.completion import Completer, Completion  # type: ignore
except Exception:
    PromptSession = None
    Completer = None
    Completion = None

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from game.installation import InstallationFinder, GameInstallation
from game.string_manager import StringManager, StringManagerError
from core.formats.key_biff import BiffFile, KeyFile
from core.util.enums import ResType
from core.index import ResourceIndex, IndexEntry, SOURCE_BIFF
from core.util.strref import StrRef


SAFE_TYPES = {ResType.ITM, ResType.CRE}
CACHE_ROOT = Path(".cache")
EXIT_WORDS = {"exit()"}
CLEAR_WORDS = {"cls"}
STRREF_NONE = 0xFFFFFFFF
COMMAND_WORDS = [
    "list",
    "list types",
    "type",
    "game",
    "random",
    "open",
    "where",
    "exit()",
    "cls",
]


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _configure_tab_completion(candidates_provider: Callable[[str], list[str]]) -> bool:
    """
    Configure tab completion for interactive input, if readline is available.

    Completion suggests command keywords and resource identifiers from the
    current search/list context.
    """
    if readline is None:
        return False

    def _completer(text: str, state: int):
        buffer = readline.get_line_buffer()
        line = buffer.lstrip()
        words = line.split()

        if not words:
            pool = COMMAND_WORDS + candidates_provider(text)
        elif len(words) == 1 and not buffer.endswith(" "):
            pool = COMMAND_WORDS + candidates_provider(text)
        elif words[0].lower() == "open":
            # open <RESREF|RESREF.TYPE>
            pool = candidates_provider(text)
        else:
            pool = []

        seen = set()
        matches = []
        for item in pool:
            if item in seen:
                continue
            seen.add(item)
            if item.upper().startswith(text.upper()):
                matches.append(item)
        matches.sort()
        return matches[state] if state < len(matches) else None

    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")
    return True


def _completion_pool(line: str, word: str, candidates_provider: Callable[[str], list[str]]) -> list[str]:
    words = line.split()
    if not words:
        return COMMAND_WORDS + candidates_provider(word)
    if len(words) == 1 and not line.endswith(" "):
        return COMMAND_WORDS + candidates_provider(word)
    if words[0].lower() == "open":
        return candidates_provider(word)
    return []


def _make_prompt_toolkit_completer(candidates_provider: Callable[[str], list[str]]):
    if Completer is None or Completion is None:
        return None

    class ExplorerCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            word = document.get_word_before_cursor(WORD=True)
            pool = _completion_pool(text.lstrip(), word, candidates_provider)
            seen = set()
            for item in sorted(pool):
                if item in seen:
                    continue
                seen.add(item)
                if item.upper().startswith(word.upper()):
                    yield Completion(item, start_position=-len(word))

    return ExplorerCompleter()


def _expand_submitted_tab(line: str, candidates_provider: Callable[[str], list[str]]) -> str:
    """
    Fallback completion when terminal inserts literal tab characters.

    Expands the token containing ``\\t`` if there is exactly one match.
    """
    if "\t" not in line:
        return line

    # Treat tab as completion request marker, not a literal character.
    cleaned = line.replace("\t", "")
    prefix = cleaned.strip()
    if not prefix:
        return cleaned

    pool = COMMAND_WORDS + candidates_provider(prefix)
    matches = sorted({p for p in pool if p.upper().startswith(prefix.upper())})
    if len(matches) == 1:
        return matches[0]
    return cleaned


def _prompt_input(prompt_text: str, candidates_provider: Callable[[str], list[str]], use_ptk: bool):
    if use_ptk and PromptSession is not None:
        if not hasattr(_prompt_input, "_session"):
            setattr(_prompt_input, "_session", PromptSession())
        session = getattr(_prompt_input, "_session")
        completer = _make_prompt_toolkit_completer(candidates_provider)
        return session.prompt(prompt_text, completer=completer, complete_while_typing=True)
    return input(prompt_text)


_STRREF_SUFFIXES = (
    "_name",
    "_description",
    "_text",
    "_tooltip",
    "identified_name",
    "unidentified_name",
    "identified_desc",
    "unidentified_desc",
    "identified_description",
    "unidentified_description",
    "journal_text",
    "dialog_text",
    "encounter_text",
    "name",
    "tooltip",
    "description",
)


def _is_strref_field(key: str) -> bool:
    k = key.lower()
    return any(k == s or k.endswith(s) for s in _STRREF_SUFFIXES)


def _format_strref_for_display(raw_value: int, manager: StringManager) -> str:
    try:
        ref = StrRef(raw_value)
    except Exception:
        return str(raw_value)

    if ref.is_none or raw_value == STRREF_NONE:
        return f"(none) ({raw_value})"

    text = manager.get(ref.file_id, ref.tlk_index)
    if text:
        return f"{text} ({raw_value})"
    return f"(unresolved) ({raw_value})"


def _resolve_strrefs_for_display(obj, manager: StringManager):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, int) and _is_strref_field(k):
                out[k] = _format_strref_for_display(v, manager)
            else:
                out[k] = _resolve_strrefs_for_display(v, manager)
        return out
    if isinstance(obj, list):
        return [_resolve_strrefs_for_display(x, manager) for x in obj]
    return obj


def _coerce_scalar(value):
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return None


def _field_path_values(entry: IndexEntry, field: str):
    alias = {
        "name": ("display_name",),
        "weight": ("data", "header", "base_weight"),
        "value": ("data", "header", "base_value"),
    }

    if field in alias:
        path = alias[field]
    elif field == "resref":
        path = ("resref",)
    elif field == "type":
        path = ("res_type",)
    elif field.startswith("header."):
        path = ("data",) + tuple(field.split("."))
    else:
        path = ("data",) + tuple(field.split("."))

    current = [entry]
    for p in path:
        next_values = []
        for cur in current:
            if p == "display_name":
                next_values.append(entry.display_name)
                continue
            if p == "resref":
                next_values.append(str(entry.resref))
                continue
            if p == "res_type":
                next_values.append(entry.res_type.name)
                continue
            if p == "data":
                next_values.append(entry.data)
                continue

            if isinstance(cur, dict):
                if p in cur:
                    next_values.append(cur[p])
                continue

            if isinstance(cur, list):
                # Numeric path segment indexes into this list.
                if p.isdigit():
                    idx = int(p)
                    if 0 <= idx < len(cur):
                        next_values.append(cur[idx])
                else:
                    # Non-numeric path segment over a list means:
                    # traverse each element and pull that key when present.
                    for item in cur:
                        if isinstance(item, dict) and p in item:
                            next_values.append(item[p])
                continue

        current = next_values
        if not current:
            return []

    out = []
    for v in current:
        sv = _coerce_scalar(v)
        if sv is not None:
            out.append(sv)
    return out


def _parse_where(expr: str):
    parts = re.split(r"\s+and\s+", expr, flags=re.IGNORECASE)
    clauses = []
    for raw in parts:
        part = raw.strip()
        if not part:
            continue

        m = re.match(r"^([A-Za-z0-9_.]+)\s*(<=|>=|!=|=|<|>|~)\s*(.+)$", part)
        if not m:
            raise ValueError(f"Invalid clause: {part!r}")

        field, op, rhs = m.group(1).lower(), m.group(2), m.group(3).strip()
        if (rhs.startswith('"') and rhs.endswith('"')) or (rhs.startswith("'") and rhs.endswith("'")):
            rhs = rhs[1:-1]

        if op in {"<", "<=", ">", ">="}:
            try:
                rhs_val = float(rhs)
            except ValueError as exc:
                raise ValueError(f"Numeric comparison requires number: {part!r}") from exc
        else:
            rhs_val = rhs

        clauses.append((field, op, rhs_val))

    if not clauses:
        raise ValueError("No valid clauses provided.")
    return clauses


def _clause_match(entry: IndexEntry, field: str, op: str, rhs):
    lhs_values = _field_path_values(entry, field)
    if not lhs_values:
        return False

    def _match_one(lhs):
        if op == "~":
            return str(rhs).lower() in str(lhs).lower()

        if op in {"<", "<=", ">", ">="}:
            try:
                lhs_num = float(lhs)
            except (TypeError, ValueError):
                return False
            if op == "<":
                return lhs_num < rhs
            if op == "<=":
                return lhs_num <= rhs
            if op == ">":
                return lhs_num > rhs
            return lhs_num >= rhs

        if op == "=":
            return str(lhs).lower() == str(rhs).lower()
        if op == "!=":
            return str(lhs).lower() != str(rhs).lower()
        return False

    if op == "!=":
        return all(_match_one(lhs) for lhs in lhs_values)
    return any(_match_one(lhs) for lhs in lhs_values)


def _structured_search(index: ResourceIndex, res_type: ResType, expr: str) -> list[IndexEntry]:
    clauses = _parse_where(expr)
    scoped = index.search(query="", res_type=res_type)
    out = []
    for entry in scoped:
        ok = True
        for field, op, rhs in clauses:
            if not _clause_match(entry, field, op, rhs):
                ok = False
                break
        if ok:
            out.append(entry)
    return out


def _pick_game(finder: InstallationFinder, game_id: str | None) -> GameInstallation:
    games = finder.find_all()
    if not games:
        print("ERROR: No IE game installations found.")
        sys.exit(1)

    if game_id:
        inst = finder.find(game_id)
        if inst is None:
            print(f"ERROR: Game '{game_id}' not found. Available:")
            for g in games:
                print(f"  {g.game_id:12s}  {g.display_name}")
            sys.exit(1)
        return inst

    print("Installed IE games found:\n")
    for i, g in enumerate(games, 1):
        print(f"  [{i}]  {g.game_id:12s}  {g.display_name}")
        print(f"         {g.install_path}")
    print()

    while True:
        raw = input(f"Pick a game [1-{len(games)}]: ").strip()
        if raw.lower() in CLEAR_WORDS:
            _clear_screen()
            print("Installed IE games found:\n")
            for i, g in enumerate(games, 1):
                print(f"  [{i}]  {g.game_id:12s}  {g.display_name}")
                print(f"         {g.install_path}")
            print()
            continue
        try:
            choice = int(raw)
            if 1 <= choice <= len(games):
                return games[choice - 1]
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(games)}.")


def _parse_res_type(name: str) -> ResType:
    try:
        return ResType[name.upper()]
    except KeyError:
        print(f"ERROR: Unknown resource type '{name}'.")
        sys.exit(1)


def _parse_res_type_selector(name: str) -> ResType | None:
    if name.upper() == "ALL":
        return None
    return _parse_res_type(name)


def _res_type_label(res_type: ResType | None) -> str:
    return res_type.name if res_type is not None else "ALL"


def _print_available_types() -> None:
    print("  Available resource types:\n")
    print(f"  {'Type':<8} {'Ext':<6} {'Code':<8} Status")
    print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*10}")
    for rt in ResType:
        ext = ResType.extension(int(rt))
        code = f"0x{int(rt):04X}"
        status = "safe" if rt in SAFE_TYPES else "untested"
        print(f"  {rt.name:<8} {ext:<6} {code:<8} {status}")


def _safe_res_type(code: int) -> bool:
    try:
        ResType(code)
        return True
    except ValueError:
        return False


def _cache_path(inst: GameInstallation, res_type: ResType) -> Path:
    return CACHE_ROOT / inst.game_id / "index" / f"{res_type.name}_index.json"


def _parser_hash(res_type: ResType) -> str:
    import hashlib

    parser_files = {
        ResType.ITM: "core/formats/itm.py",
        ResType.SPL: "core/formats/spl.py",
        ResType.CRE: "core/formats/cre.py",
        ResType.DLG: "core/formats/dlg.py",
        ResType.ARE: "core/formats/are.py",
        ResType.WED: "core/formats/wed.py",
        ResType.TIS: "core/formats/tis.py",
        ResType.MOS: "core/formats/mos.py",
    }
    path = Path(_ROOT) / parser_files.get(res_type, "core/index.py")
    try:
        data = path.read_bytes()
        return hashlib.md5(data).hexdigest()[:8]
    except OSError:
        return "unknown"


def _save_index(index: ResourceIndex, path: Path, chitin_mtime: float, parser_hash: str = "") -> None:
    entries = []
    for e in index:
        entries.append(
            {
                "resref": str(e.resref),
                "res_type": int(e.res_type),
                "display_name": e.display_name,
                "source": e.source,
                "data": e.data,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "chitin_mtime": chitin_mtime,
                "parser_hash": parser_hash,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_index(path: Path, chitin_mtime: float, expected_hash: str = "") -> ResourceIndex | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if raw.get("chitin_mtime") != chitin_mtime:
        print("  (Cache outdated: CHITIN.KEY changed, rebuilding.)")
        return None
    if expected_hash and raw.get("parser_hash") != expected_hash:
        print("  (Cache outdated: parser changed, rebuilding.)")
        return None

    from core.util.resref import ResRef

    index = ResourceIndex()
    for e in raw.get("entries", []):
        try:
            index.add_or_update(
                resref=ResRef(e["resref"]),
                res_type=ResType(e["res_type"]),
                source=e["source"],
                data=e["data"],
                display_name=e["display_name"],
            )
        except Exception:
            pass
    return index


def _build_index_batched(entries_to_index: list, key: KeyFile, inst: GameInstallation, manager: StringManager) -> tuple[ResourceIndex, list[str]]:
    by_biff: dict[int, list] = defaultdict(list)
    for e in entries_to_index:
        by_biff[e.biff_index].append(e)

    index = ResourceIndex()
    errors: list[str] = []
    done = 0
    total = len(entries_to_index)

    for _, batch in sorted(by_biff.items()):
        try:
            biff_path = key.biff_path(batch[0], game_root=inst)
        except Exception as exc:
            for e in batch:
                errors.append(f"  PATH  {e.resref}: {exc}")
                done += 1
            continue

        try:
            biff = BiffFile.open(biff_path)
        except Exception as exc:
            for e in batch:
                errors.append(f"  OPEN  {e.resref} ({biff_path.name}): {exc}")
                done += 1
            _progress(done, total, "")
            continue

        for res_entry in batch:
            done += 1
            _progress(done, total, str(res_entry.resref))
            try:
                if res_entry.res_type == int(ResType.TIS):
                    raw = biff.read_tileset_raw(res_entry.tileset_index)
                else:
                    raw = biff.read(res_entry.file_index)
            except Exception as exc:
                errors.append(f"  READ  {res_entry.resref}: {exc}")
                continue

            try:
                index._index_raw(
                    resref=res_entry.resref,
                    res_type=ResType(res_entry.res_type),
                    source=SOURCE_BIFF,
                    raw=raw,
                    string_manager=manager,
                )
            except Exception as exc:
                errors.append(f"  PARSE {res_entry.resref}: {exc}")

    return index, errors


def _progress(current: int, total: int, resref: str) -> None:
    pct = int(current / total * 100) if total else 0
    print(f"\r  Indexing... {current}/{total} ({pct}%)  {resref:<12}", end="", flush=True)


def _print_result_table(results: list[IndexEntry], limit: int) -> None:
    print(f"  {len(results)} result(s):\n")
    print(f"  {'ResRef':<12} {'Type':<6} Name")
    print(f"  {'-'*12} {'-'*6} {'-'*60}")
    for entry in results[:limit]:
        name = entry.display_name or "(no name)"
        print(f"  {str(entry.resref):<12} {entry.res_type.name:<6} {name}")
    if len(results) > limit:
        print(f"\n  ... and {len(results) - limit} more (--limit N to see more).")


def _inspect_entry(
    entry: IndexEntry,
    key: KeyFile,
    inst: GameInstallation,
    index: ResourceIndex,
    manager: StringManager,
) -> None:
    parsed = index.resolve(entry, key, inst)
    if parsed is None:
        print(f"\nERROR: Could not resolve {entry.resref}.{entry.res_type.name.lower()}.")
        return

    try:
        payload = parsed.to_json()
    except Exception as exc:
        print(f"\nERROR: Could not serialize {entry.resref}: {exc}")
        return
    payload = _resolve_strrefs_for_display(payload, manager)

    print("\n" + "=" * 90)
    print(f"Resource: {entry.resref}.{entry.res_type.name.lower()}   Source: {entry.source}")
    print("=" * 90)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _handle_list_flow(
    results: list[IndexEntry],
    res_type_label: str,
    limit: int,
) -> list[IndexEntry]:
    print(f"\nListing all resources of type {res_type_label}:\n")
    _print_result_table(results, limit)
    return results


def _handle_search_flow(
    results: list[IndexEntry],
    res_type_label: str,
    query: str,
    limit: int,
) -> list[IndexEntry]:
    q = query.strip()
    print(f"\nSearching for: {query!r}  (type={res_type_label})\n")

    if not results:
        print("  No results found.")
        return []
    _print_result_table(results, limit)
    return results


def _load_or_build_index(
    *,
    key: KeyFile,
    inst: GameInstallation,
    manager: StringManager,
    res_type: ResType,
    no_cache: bool,
) -> ResourceIndex:
    chitin_mtime = inst.chitin_key.stat().st_mtime
    cache = _cache_path(inst, res_type)
    index: ResourceIndex | None = None

    phash = _parser_hash(res_type)
    if not no_cache:
        index = _load_index(cache, chitin_mtime, phash)
        if index is not None:
            print(f"Index loaded from cache ({len(index)} entries): {cache}")

    if index is None:
        entries_to_index = [
            e
            for e in key.iter_resources()
            if _safe_res_type(e.res_type)
            if ResType(e.res_type) == res_type
        ]
        total = len(entries_to_index)
        print(f"Building index for: {res_type.name}  ({total} resources)")

        t0 = time.time()
        index, errors = _build_index_batched(entries_to_index, key, inst, manager)
        elapsed = time.time() - t0
        print(f"\r  Indexed {len(index)} entries in {elapsed:.1f}s.{' ' * 30}")

        if errors:
            print(f"\n  {len(errors)} error(s) during indexing:")
            for e in errors[:10]:
                print(f"    {e}")
            if len(errors) > 10:
                print(f"    ... and {len(errors) - 10} more.")

        print(f"  Saving cache to {cache} ... ", end="", flush=True)
        try:
            _save_index(index, cache, chitin_mtime, phash)
            print("done.")
        except Exception as exc:
            print(f"failed ({exc}) -- continuing without cache.")

    return index


def run(args: argparse.Namespace) -> None:
    finder = InstallationFinder()

    if args.list_games:
        games = finder.find_all()
        if not games:
            print("No IE game installations found.")
        else:
            print(f"{'Game ID':<14} {'Display Name':<40} Install Path")
            print("-" * 90)
            for g in games:
                print(f"{g.game_id:<14} {g.display_name:<40} {g.install_path}")
        return

    def _activate_game(selected_inst: GameInstallation) -> tuple[KeyFile, StringManager]:
        print(f"\nUsing: {selected_inst.display_name}")
        print(f"       {selected_inst.install_path}\n")

        print("Opening CHITIN.KEY ... ", end="", flush=True)
        try:
            selected_key = KeyFile.open(selected_inst.chitin_key)
        except Exception as exc:
            print(f"\nERROR: Cannot open CHITIN.KEY: {exc}")
            sys.exit(1)
        print(f"{selected_key.num_resources} resources across {selected_key.num_biff} BIFF archives.")

        print("Loading TLK ... ", end="", flush=True)
        try:
            selected_manager = StringManager.from_installation(selected_inst)
        except StringManagerError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)

        langs = StringManager.available_languages(selected_inst)
        if langs:
            print(f"{selected_manager.base_entry_count} strings, {len(langs)} language(s): {', '.join(langs)}")
        else:
            print(f"{selected_manager.base_entry_count} strings (single-language install).")
        return selected_key, selected_manager

    inst = _pick_game(finder, args.game)
    key, manager = _activate_game(inst)

    current_type = _parse_res_type_selector(args.list_type or args.type)
    index_cache_by_game: dict[str, dict[ResType, ResourceIndex]] = {}
    last_results: list[IndexEntry] = []
    all_mode = current_type is None
    if all_mode:
        print("WARNING: ALL mode includes untested types. Parse errors will be skipped.")

    def get_index(res_type: ResType) -> ResourceIndex:
        game_cache = index_cache_by_game.setdefault(inst.game_id, {})
        if res_type not in game_cache:
            if (not all_mode) and res_type not in SAFE_TYPES:
                print(f"WARNING: {res_type.name} is marked untested. Parse errors will be skipped.")
            game_cache[res_type] = _load_or_build_index(
                key=key,
                inst=inst,
                manager=manager,
                res_type=res_type,
                no_cache=args.no_cache,
            )
        return game_cache[res_type]

    def selector_entries(query: str = "") -> list[IndexEntry]:
        if current_type is not None:
            return get_index(current_type).search(query=query, res_type=current_type)
        results: list[IndexEntry] = []
        for rt in ResType:
            results.extend(get_index(rt).search(query=query, res_type=rt))
        return results

    def selector_structured(expr: str) -> list[IndexEntry]:
        if current_type is not None:
            return _structured_search(get_index(current_type), current_type, expr)
        results: list[IndexEntry] = []
        for rt in ResType:
            results.extend(_structured_search(get_index(rt), rt, expr))
        return results

    def run_query_text(query: str) -> list[IndexEntry]:
        q = query.strip()
        if q.lower().startswith("where "):
            expr = q[6:].strip()
            try:
                return selector_structured(expr)
            except ValueError as exc:
                print(f"  Invalid where expression: {exc}")
                print("  Example: where name~sword and value>500 and weight<5")
                return []
        return selector_entries(query=q)

    completion_cache_key: tuple | None = None
    completion_cache_values: list[str] = []

    def completion_candidates(prefix: str = "") -> list[str]:
        nonlocal completion_cache_key, completion_cache_values
        pfx = prefix.upper()

        # Prefer focused suggestions from recent query/list results.
        if last_results:
            entries = last_results
            cache_key = (inst.game_id, _res_type_label(current_type), "last", id(entries), len(entries), pfx)
            if completion_cache_key == cache_key:
                return completion_cache_values

            out: list[str] = []
            seen: set[str] = set()
            for e in entries:
                base = str(e.resref).upper()
                typed = f"{base}.{e.res_type.name}"
                if (not pfx or base.startswith(pfx)) and base not in seen:
                    out.append(base)
                    seen.add(base)
                if (not pfx or typed.startswith(pfx)) and typed not in seen:
                    out.append(typed)
                    seen.add(typed)
                if len(out) >= 20000:
                    break

            completion_cache_key = cache_key
            completion_cache_values = out
            return out

        # Before any search, use raw KEY entries so completion is available
        # immediately without requiring prior search/list actions.
        cache_key = (inst.game_id, _res_type_label(current_type), "key", pfx)
        if completion_cache_key == cache_key:
            return completion_cache_values

        out: list[str] = []
        seen: set[str] = set()
        for e in key.iter_resources():
            if not _safe_res_type(e.res_type):
                continue
            rt = ResType(e.res_type)
            if current_type is not None and rt != current_type:
                continue
            base = str(e.resref).upper()
            typed = f"{base}.{rt.name}"
            if (not pfx or base.startswith(pfx)) and base not in seen:
                out.append(base)
                seen.add(base)
            if (not pfx or typed.startswith(pfx)) and typed not in seen:
                out.append(typed)
                seen.add(typed)
            if len(out) >= 50000:
                break

        completion_cache_key = cache_key
        completion_cache_values = out
        return out

    use_prompt_toolkit = PromptSession is not None
    if use_prompt_toolkit:
        print("Live tab completion enabled (prompt_toolkit).")
    elif _configure_tab_completion(completion_candidates):
        print("Tab completion enabled (readline).")
    else:
        print("NOTE: Tab completion unavailable in this Python environment.")

    # Initial one-shot action from CLI args (if provided), then continue in loop.
    if args.list_type:
        last_results = _handle_list_flow(selector_entries(query=""), _res_type_label(current_type), args.limit)
    elif args.query:
        last_results = _handle_search_flow(run_query_text(args.query), _res_type_label(current_type), args.query, args.limit)
    else:
        count = len(selector_entries(query=""))
        print(f"\nNo query supplied. Index contains {count} entries for {_res_type_label(current_type)}.")

    _clear_screen()
    print("Interactive mode.")
    print("Commands: <search text> | where <expr> | list | list types | list <TYPE|ALL> | type <TYPE|ALL> | game | random [TYPE|ALL] | open <RESREF[.TYPE]> | exit()")
    print("Where operators: = != < <= > >= ~   (where ~ means contains)")
    print("Where aliases: name, value, weight, resref, type")
    print("Example: where name~sword and value>500 and weight<5")

    while True:
        raw = _prompt_input(f"[{_res_type_label(current_type)}] > ", completion_candidates, use_prompt_toolkit).strip()
        raw = _expand_submitted_tab(raw, completion_candidates)
        lowered = raw.lower()

        if lowered in CLEAR_WORDS:
            _clear_screen()
            last_results = []
            print("Interactive mode.")
            print("Commands: <search text> | where <expr> | list | list types | list <TYPE|ALL> | type <TYPE|ALL> | game | random [TYPE|ALL] | open <RESREF[.TYPE]> | cls | exit()")
            print("Where operators: = != < <= > >= ~   (where ~ means contains)")
            print("Where aliases: name, value, weight, resref, type")
            print("Example: where name~sword and value>500 and weight<5")
            continue

        if lowered in EXIT_WORDS:
            print("Exiting.")
            return

        if not raw:
            continue

        if lowered == "list":
            last_results = _handle_list_flow(selector_entries(query=""), _res_type_label(current_type), args.limit)
            continue

        if lowered == "list types":
            _print_available_types()
            continue

        if lowered in {"game", "games", "switch game"}:
            inst = _pick_game(finder, None)
            key, manager = _activate_game(inst)
            last_results = []
            print(f"  Switched to game {inst.game_id}.")
            continue

        if lowered == "random" or lowered.startswith("random "):
            random_arg = raw.split(None, 1)[1].strip() if len(raw.split(None, 1)) > 1 else ""
            if not random_arg:
                random_type = current_type
            else:
                try:
                    random_type = _parse_res_type_selector(random_arg)
                except SystemExit:
                    continue

            if random_type is None:
                candidates = selector_entries(query="")
                label = "ALL"
            else:
                candidates = get_index(random_type).search(query="", res_type=random_type)
                label = random_type.name

            if not candidates:
                print(f"  No resources available for type {label}.")
                continue

            picked = random.choice(candidates)
            print(f"  Random pick: {picked.resref}.{picked.res_type.name.lower()}  ({label})")
            _inspect_entry(picked, key, inst, get_index(picked.res_type), manager)
            continue

        if lowered.startswith("list "):
            list_arg = raw.split(None, 1)[1].strip() if len(raw.split(None, 1)) > 1 else ""
            if not list_arg:
                print("  Usage: list <TYPE|ALL>   (example: list ITM)")
                continue
            try:
                list_type = _parse_res_type_selector(list_arg)
            except SystemExit:
                continue
            if list_type is None:
                scoped = selector_entries(query="")
                label = "ALL"
            else:
                scoped = get_index(list_type).search(query="", res_type=list_type)
                label = list_type.name
            last_results = _handle_list_flow(scoped, label, args.limit)
            continue

        if lowered.startswith("type "):
            next_type_name = raw.split(None, 1)[1].strip() if len(raw.split(None, 1)) > 1 else ""
            if not next_type_name:
                print("  Usage: type <TYPE>   (example: type ITM)")
                continue
            current_type = _parse_res_type_selector(next_type_name)
            all_mode = current_type is None
            if all_mode:
                print("WARNING: ALL mode includes untested types. Parse errors will be skipped.")
                count = len(selector_entries(query=""))
                print(f"  Switched type to ALL. Indexed entries: {count}.")
                last_results = []
                continue
            index = get_index(current_type)
            last_results = []
            print(f"  Switched type to {current_type.name}. Indexed entries: {len(index)}.")
            continue

        if lowered.startswith("open "):
            target = raw.split(None, 1)[1].strip().upper() if len(raw.split(None, 1)) > 1 else ""
            if not target:
                print("  Usage: open <RESREF> or open <RESREF.TYPE>   (example: open HSWORD or HSWORD.ITM)")
                continue
            if "." in target:
                resref, ext = target.rsplit(".", 1)
                try:
                    wanted_type = _parse_res_type(ext)
                except SystemExit:
                    continue
            else:
                resref = target
                wanted_type = None
            picked = None
            candidates: list[IndexEntry] = []
            for e in last_results:
                if str(e.resref).upper() == resref and (wanted_type is None or e.res_type == wanted_type):
                    candidates.append(e)
            if picked is None:
                typed = selector_entries(query="")
                for e in typed:
                    if str(e.resref).upper() == resref and (wanted_type is None or e.res_type == wanted_type):
                        candidates.append(e)
            # Deduplicate candidates collected from last_results + full selector scan.
            unique = {}
            for e in candidates:
                unique[(str(e.resref), int(e.res_type), e.source)] = e
            candidates = list(unique.values())
            if not candidates:
                print(f"  {resref} not found for type {_res_type_label(current_type)}.")
                continue
            if len(candidates) > 1:
                print(f"  Multiple matches for {resref}:")
                for c in candidates[:10]:
                    print(f"    {c.resref}.{c.res_type.name.lower()}  {c.display_name or '(no name)'}")
                print("  Disambiguate with: open <RESREF.TYPE>  (example: open HSWORD.ITM)")
                continue
            picked = candidates[0]
            _inspect_entry(picked, key, inst, get_index(picked.res_type), manager)
            last_results = []
            continue

        last_results = _handle_search_flow(run_query_text(raw), _res_type_label(current_type), raw, args.limit)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PlanarForge CLI resource explorer.",
    )
    parser.add_argument("query", nargs="?", help="Search query (substring in name or any field).")
    parser.add_argument("--game", "-g", metavar="GAME_ID", help="Game ID (e.g. BG2EE). Prompted if omitted.")
    parser.add_argument("--type", "-t", metavar="TYPE", default="ALL", help="Resource type for search (default: ALL).")
    parser.add_argument("--list-type", metavar="TYPE", help="List all resources for this type (e.g. ITM, or ALL).")
    parser.add_argument("--limit", "-n", type=int, default=100, help="Max rows to display (default: 20).")
    parser.add_argument("--list-games", action="store_true", help="List detected installations and exit.")
    parser.add_argument("--no-cache", action="store_true", help="Force index rebuild even if cache exists.")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
