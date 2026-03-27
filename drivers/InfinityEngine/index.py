import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path


CACHE_FORMAT_VERSION = 16


@dataclass
class IndexEntry:
    """
    A lightweight, searchable entry for a single game resource.
    """
    resref: str
    restype: str
    source: str
    display_name: str = ""
    search_data: dict = field(default_factory=dict)


class ResourceIndexer:
    """
    Builds, caches, and searches an index of game resources.
    """
    def __init__(self, resource_loader, game_id):
        self.loader = resource_loader
        self.game_id = game_id
        self.index = {}  # { resref: [IndexEntry] }
        self.cache_dir = Path(".cache") / self.game_id

    def build_index(self, types=None, force_rebuild=False):
        """
        Builds the index for the specified resource types.
        'types' should be a list of uppercase strings (e.g., ['ITM', 'SPL']).
        If 'types' is None, all types will be considered.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Group resources by type for batch processing
        resources_by_type = {}
        for resref, restype, _ in self.loader.iter_resources(game=self.game_id):
            if types is None or restype in types:
                if restype not in resources_by_type:
                    resources_by_type[restype] = []
                resources_by_type[restype].append(resref)

        for restype, resrefs in resources_by_type.items():
            cache_path = self.cache_dir / f"{restype.lower()}_index.json"

            if not force_rebuild and self._load_from_cache(cache_path):
                print(f"Loaded {restype} index from cache.")
                continue

            print(f"Building index for {restype}...")
            count = 0
            for resref in resrefs:
                resource = self.loader.load(resref, restype=restype, game=self.game_id)
                if resource:
                    # Resolve display name from common fields
                    name_strref = resource.get("identified_name") or resource.get("name")
                    display_name = ""
                    if isinstance(name_strref, int):
                        display_name = self.loader.get_string(name_strref, game=self.game_id) or ""

                    entry = IndexEntry(
                        resref=resource.name,
                        restype=restype,
                        source=resource.source,
                        display_name=display_name.strip(),
                        search_data=resource.to_dict()
                    )

                    if resource.name not in self.index:
                        self.index[resource.name] = []
                    self.index[resource.name].append(entry)
                    count += 1

            print(f"Indexed {count} {restype} resources.")
            self._save_to_cache(cache_path, restype)

    def _get_chitin_mtime(self):
        chitin_path = self.loader.install_finder.find_chitin(self.game_id)
        if chitin_path and chitin_path.exists():
            return chitin_path.stat().st_mtime
        return 0

    def _save_to_cache(self, path, restype):
        """Saves the portion of the index for a given restype to a JSON file."""
        entries_to_save = [
            asdict(entry)
            for entries in self.index.values()
            for entry in entries
            if entry.restype == restype
        ]

        cache_data = {
            "cache_version": CACHE_FORMAT_VERSION,
            "chitin_mtime": self._get_chitin_mtime(),
            "entries": entries_to_save
        }

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            print(f"Saved {restype} index to cache: {path}")
        except Exception as e:
            print(f"Error saving cache for {restype}: {e}")

    def _load_from_cache(self, path):
        """Loads index entries from a JSON cache file."""
        if not path.exists():
            return False

        try:
            with open(path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            if cache_data.get("cache_version") != CACHE_FORMAT_VERSION:
                print(f"Cache for {path.name} uses an older format. Rebuilding.")
                return False

            current_mtime = self._get_chitin_mtime()
            if current_mtime != 0 and cache_data.get("chitin_mtime") != current_mtime:
                print(f"Cache for {path.name} is stale (CHITIN.KEY changed). Rebuilding.")
                return False

            for item in cache_data.get("entries", []):
                entry = IndexEntry(**item)
                if entry.resref not in self.index:
                    self.index[entry.resref] = []
                self.index[entry.resref].append(entry)
            return True
        except Exception as e:
            print(f"Error loading cache from {path}: {e}")
            try:
                os.remove(path)
            except OSError:
                pass
            return False

    def search(self, query, restype=None, where_clauses=None):
        """
        Performs a search on the index.
        - query: Simple text search on resref and display name.
        - where_clauses: Structured search (e.g., [('speed', '<', 3)]). Not yet implemented.
        """
        results = []
        query = query.lower()

        for entries in self.index.values():
            for entry in entries:
                if restype and entry.restype != restype:
                    continue

                match = (
                    query in entry.resref.lower() or
                    query in entry.display_name.lower()
                )

                if match:
                    results.append(entry)

        if where_clauses:
            print("Warning: 'where' clause search is not yet implemented.")

        return results
