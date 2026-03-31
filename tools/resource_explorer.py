#!/usr/bin/env python3
"""
resource_explorer.py

Interactive CLI resource explorer for PlanarForgeV2.

Features:
- Uses ResourceIndexer to build/search persistent metadata caches.
- Supports fuzzy text search and structured 'where' clauses.
- Inspects full resource data (JSON dump) with StrRef resolution.
"""

import argparse
import sys
import os
import json
import re
import time
import random
from pathlib import Path
from typing import List, Callable, Optional, Dict, Any

# Add project root to path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from drivers.InfinityEngine.io.installation_finder import InstallationFinder, GameInstallation
from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.index import ResourceIndexer, IndexEntry
from drivers.InfinityEngine.definitions.extensions import RESOURCE_TYPE_MAP

# Try to import prompt_toolkit for better CLI experience
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
except ImportError:
    PromptSession = None
    Completer = None
    Completion = None


COMMAND_WORDS = [
    "list", "search", "open", "game", "type", "random", "help", "exit", "cls", "where"
]

KNOWN_TYPES = sorted(list(set(RESOURCE_TYPE_MAP.values())))


def _clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


class ExplorerCompleter(Completer):
    def __init__(self, candidates_provider):
        self.candidates_provider = candidates_provider

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)
        
        # Determine context
        parts = text.lstrip().split()
        if not parts or (len(parts) == 1 and not text.endswith(" ")):
             pool = COMMAND_WORDS
        elif parts[0] == "type":
             pool = KNOWN_TYPES + ["ALL"]
        elif parts[0] == "open":
             pool = self.candidates_provider(word)
        else:
             pool = []

        for item in pool:
            if item.upper().startswith(word.upper()):
                yield Completion(item, start_position=-len(word))


def _resolve_strrefs(data: Any, loader: ResourceLoader, game_id: str) -> Any:
    """
    Recursively walks a data structure. If it finds a key ending in 'name', 'desc', etc.
    with an integer value, it attempts to resolve it via the loader's TLK handler.
    """
    strref_suffixes = (
        "_name", "_description", "identified_desc", "unidentified_desc", "_text", "_tooltip", 
        "_strref", "_msg", "_message", "identified_name", "unidentified_name", 
        "identified_description", "unidentified_description", "journal_text", 
        "dialog_text", "encounter_text"
    )
    
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            new_val = _resolve_strrefs(v, loader, game_id)
            new_dict[k] = new_val
            
            # Heuristic: Check if this field looks like a StrRef
            if isinstance(v, int) and v > 0 and (k.lower().endswith(strref_suffixes) or k.lower() in ("name", "description", "strref", "area_name", "long_name")):
                resolved = loader.get_string(v, game=game_id)
                if resolved:
                    # Add a synthetic key for display
                    new_dict[f"{k}_text"] = resolved
        return new_dict
    elif isinstance(data, list):
        return [_resolve_strrefs(x, loader, game_id) for x in data]
    else:
        return data


# -----------------------------------------------------------------------------
# Structured Search Logic (Where Clauses)
# -----------------------------------------------------------------------------

def _get_field_values(data: Any, path_parts: List[str]) -> List[Any]:
    """
    Navigates a nested dict/list structure using a path like ['header', 'flags'].
    Returns a list of all matching values (to handle lists in the path).
    """
    if not path_parts:
        return [data]

    key = path_parts[0]
    remaining = path_parts[1:]
    results = []

    if isinstance(data, dict):
        if key in data:
            results.extend(_get_field_values(data[key], remaining))
    elif isinstance(data, list):
        # If data is a list, try applying the key to every item
        for item in data:
            results.extend(_get_field_values(item, path_parts))
    
    return results

def _clause_match(entry: IndexEntry, field: str, op: str, value: str) -> bool:
    # 1. Flatten the entry data for search
    # We look in 'search_data' which is the raw resource dict
    # We also allow searching top-level metadata
    
    values = []
    if field == "resref":
        values = [entry.resref]
    elif field == "type":
        values = [entry.restype]
    elif field == "name":
        values = [entry.display_name]
    else:
        # Traverse search_data
        values = _get_field_values(entry.search_data, field.split("."))

    if not values:
        return False

    # 2. Check conditions
    for val in values:
        str_val = str(val).lower()
        str_target = value.lower()
        
        try:
            num_val = float(val) if isinstance(val, (int, float)) else None
            num_target = float(value)
        except ValueError:
            num_val = None
            num_target = None

        if op == "=":
            if str_val == str_target: return True
        elif op == "!=":
            if str_val != str_target: return True
        elif op == "~":
            if str_target in str_val: return True
        elif num_val is not None and num_target is not None:
            if op == "<" and num_val < num_target: return True
            if op == ">" and num_val > num_target: return True
            if op == "<=" and num_val <= num_target: return True
            if op == ">=" and num_val >= num_target: return True
            
    return False

def _parse_where(query: str) -> List[tuple]:
    """
    Parses a string like "speed < 5 and damage_type = 1" into tuples.
    Returns: [(field, op, value), ...]
    """
    clauses = []
    # Split by 'and' (case insensitive)
    raw_clauses = re.split(r'\s+and\s+', query, flags=re.IGNORECASE)
    
    pattern = re.compile(r'([a-zA-Z0-9_.]+)\s*(=|!=|<=|>=|<|>|~)\s*(.+)')
    
    for raw in raw_clauses:
        m = pattern.match(raw.strip())
        if m:
            field, op, val = m.groups()
            # Strip quotes if present
            val = val.strip(' "\'')
            clauses.append((field, op, val))
        else:
            print(f"Warning: Could not parse clause '{raw}'")
            
    return clauses


# -----------------------------------------------------------------------------
# Main App Logic
# -----------------------------------------------------------------------------

class ResourceExplorer:
    def __init__(self):
        self.loader = ResourceLoader()
        self.finder = self.loader.install_finder
        self.indexer = None # type: ResourceIndexer
        self.active_game = None
        self.active_type = "ALL"
        self.last_results = []
        self.session = PromptSession() if PromptSession else None

    def pick_game(self, game_id: str = None):
        games = self.finder.find_all()
        if not games:
            print("No Infinity Engine installations found.")
            sys.exit(1)

        if game_id:
            for g in games:
                if g.game_id.upper() == game_id.upper():
                    self._activate_game(g)
                    return
            print(f"Game ID '{game_id}' not found.")

        print("\nFound installations:")
        for i, g in enumerate(games):
            print(f"  [{i+1}] {g.game_id:<8} ({g.display_name}) - {g.install_path}")

        while True:
            choice = input("\nSelect game [1-{}]: ".format(len(games))).strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(games):
                    self._activate_game(games[idx])
                    return
            except ValueError:
                pass

    def _activate_game(self, install: GameInstallation):
        print(f"\nInitializing for {install.game_id}...")
        self.active_game = install.game_id
        self.indexer = ResourceIndexer(self.loader, self.active_game)
        
        # Ensure TLK is loaded
        self.loader.get_string(0, game=self.active_game) 
        
        print(f"Ready. Loaded {self.active_game}.")

    def ensure_index(self, restype=None):
        if not self.indexer:
            return
        
        types_to_index = [restype] if restype and restype != "ALL" else ["ITM", "SPL", "CRE", "ARE"]
        self.indexer.build_index(types=types_to_index)

    def run_repl(self):
        print("\n--- PlanarForge Resource Explorer ---")
        print("Commands: list, search <query>, where <clause>, open <resref>, type <type>, game, exit")
        print("Example: 'where header.price > 5000 and header.weight < 2'")
        
        self.ensure_index(self.active_type)

        while True:
            label = f"[{self.active_game}][{self.active_type}]> "
            try:
                if self.session:
                    completer = ExplorerCompleter(self._get_completion_candidates)
                    text = self.session.prompt(label, completer=completer)
                else:
                    text = input(label)
            except (KeyboardInterrupt, EOFError):
                print("Exiting.")
                break

            if not text.strip():
                continue

            self._handle_command(text)

    def _get_completion_candidates(self, word):
        # Return list of resrefs from last search for auto-completion
        return [entry.resref for entry in self.last_results]

    def _handle_command(self, text):
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            sys.exit(0)
        elif cmd == "cls":
            _clear_screen()
        elif cmd == "help":
            self._print_help()
        elif cmd == "game":
            self.pick_game()
        elif cmd == "type":
            self._set_type(arg)
        elif cmd == "list":
            self._search("")
        elif cmd == "search":
            self._search(arg)
        elif cmd == "where":
            self._search_where(arg)
        elif cmd == "open":
            self._open_resource(arg)
        elif cmd == "random":
            self._random_resource()
        else:
            # Default to search if no command matched
            self._search(text)

    def _print_help(self):
        print("""
Available Commands:
  list              List all resources of current type
  search <text>     Fuzzy search in ResRef and Name
  where <clause>    Structured search. 
                    Ops: =, !=, <, >, <=, >=, ~ (contains)
                    Ex: where header.price > 100
  open <resref>     Load and inspect a resource
  type <type|ALL>   Filter by resource type (ITM, SPL, CRE, ARE...)
  game              Switch active game
  random            Pick a random resource
  cls               Clear screen
  exit              Quit
""")

    def _set_type(self, arg):
        if not arg:
            print("Current type:", self.active_type)
            return
        
        arg = arg.upper()
        if arg != "ALL" and arg not in KNOWN_TYPES:
            print(f"Unknown type '{arg}'. Known types: {', '.join(KNOWN_TYPES[:10])}...")
            return
            
        self.active_type = arg
        print(f"Active type set to {self.active_type}")
        self.ensure_index(self.active_type)

    def _search(self, query):
        print(f"Searching for '{query}' in {self.active_type}...")
        
        # Use the indexer's basic search
        t_filter = self.active_type if self.active_type != "ALL" else None
        results = self.indexer.search(query, restype=t_filter)
        
        self.last_results = results
        self._print_results(results)

    def _search_where(self, clause_str):
        print(f"Structured search: {clause_str}")
        clauses = _parse_where(clause_str)
        if not clauses:
            return
            
        t_filter = self.active_type if self.active_type != "ALL" else None
        # Start with all/filtered resources
        candidates = self.indexer.search("", restype=t_filter)
        
        results = []
        for entry in candidates:
            match = True
            for field, op, val in clauses:
                if not _clause_match(entry, field, op, val):
                    match = False
                    break
            if match:
                results.append(entry)
                
        self.last_results = results
        self._print_results(results)

    def _print_results(self, results: List[IndexEntry]):
        count = len(results)
        limit = 50
        print(f"Found {count} results.")
        print(f"{'RESREF':<10} {'TYPE':<6} {'NAME'}")
        print("-" * 60)
        
        for i, entry in enumerate(results):
            if i >= limit:
                print(f"... and {count - limit} more.")
                break
            print(f"{entry.resref:<10} {entry.restype:<6} {entry.display_name}")

    def _open_resource(self, arg):
        if not arg:
            print("Usage: open <ResRef>")
            return
            
        parts = arg.split('.')
        resref = parts[0].upper()
        restype = parts[1].upper() if len(parts) > 1 else None

        # Try to resolve type from active context or find it
        if not restype:
            if self.active_type != "ALL":
                restype = self.active_type
            else:
                # Find the entry in last results or index to guess type
                candidates = self.indexer.search(resref)
                # Exact match filter
                exact = [c for c in candidates if c.resref.upper() == resref]
                if len(exact) == 1:
                    restype = exact[0].restype
                elif len(exact) > 1:
                    print(f"Ambiguous ResRef. Please specify type (e.g., {resref}.ITM):")
                    for e in exact:
                        print(f"  - {e.resref}.{e.restype}")
                    return
                else:
                    # Fallback to loader auto-detection (requires type usually)
                    # If we really don't know, we can't load easily without iterating schema
                    print(f"Could not determine type for {resref}. Specify as RESREF.TYPE")
                    return

        try:
            print(f"Loading {resref}.{restype}...")
            resource = self.loader.load(resref, restype=restype, game=self.active_game)
            if not resource:
                print("Failed to load resource.")
                return
                
            data = resource.to_dict()

            # Expose unmapped trailing data for manual inspection
            if hasattr(resource, "trailing_data"):
                data["_unmapped_trailing_data"] = {
                    "size_bytes": len(resource.trailing_data),
                    "data_hex": resource.trailing_data.hex(' ').upper()
                }

            # Resolve StrRefs for readable display
            data = _resolve_strrefs(data, self.loader, self.active_game)
            
            print("\n" + "="*60)
            print(f"FILE: {resref}.{restype}")
            print(f"SOURCE: {resource.source}")
            print("="*60)
            print(json.dumps(data, indent=2))
            
        except Exception as e:
            print(f"Error opening resource: {e}")

    def _random_resource(self):
        if not self.last_results:
            # Fetch some if empty
            t_filter = self.active_type if self.active_type != "ALL" else None
            self.last_results = self.indexer.search("", restype=t_filter)
            
        if not self.last_results:
            print("No resources found in current context.")
            return
            
        entry = random.choice(self.last_results)
        print(f"Random pick: {entry.resref}.{entry.restype} - {entry.display_name}")
        self._open_resource(f"{entry.resref}.{entry.restype}")


def main():
    parser = argparse.ArgumentParser(description="PlanarForge Resource Explorer")
    parser.add_argument("-g", "--game", help="Game ID to load (e.g. BG2EE)")
    parser.add_argument("-t", "--type", help="Initial resource type (e.g. ITM)")
    parser.add_argument("query", nargs="?", help="Initial search query")

    args = parser.parse_args()

    explorer = ResourceExplorer()
    try:
        explorer.pick_game(args.game)
        
        if args.type:
            explorer._set_type(args.type)
            
        if args.query:
            explorer._search(args.query)
        
        explorer.run_repl()
        
    except KeyboardInterrupt:
        print("\nExiting.")

if __name__ == "__main__":
    main()