"""
Game-aware resolver for IDS and 2DA lookup tables.
"""

from pathlib import PurePath

from .ids_handler import IdsHandler
from .twoda_handler import TwoDAHandler


_IE_TEXT_XOR_KEY = bytes.fromhex(
    "88 a8 8f ba 8a d3 b9 f5 ed b1 cf ea aa e4 b5 fb "
    "eb 82 f9 90 ca c9 b5 e7 dc 8e b7 ac ee f7 e0 ca "
    "8e ea ca 80 ce c5 ad b7 c4 d0 84 93 d5 f0 eb c8 "
    "b4 9d cc af a5 95 ba 99 87 d2 9d e3 91 ba 90 ca"
)


def decode_ie_text_resource(raw_bytes):
    if raw_bytes is None:
        return None

    payload = raw_bytes
    if len(raw_bytes) >= 2 and raw_bytes[:2] == b"\xff\xff":
        encrypted = raw_bytes[2:]
        payload = bytes(
            byte ^ _IE_TEXT_XOR_KEY[index % len(_IE_TEXT_XOR_KEY)]
            for index, byte in enumerate(encrypted)
        )

    return payload.decode("latin-1", errors="replace").lstrip("\ufeff")


class TableResolver:
    def __init__(self, loader):
        self.loader = loader
        self._ids_cache = {}
        self._twoda_cache = {}

    def _normalize_reference(self, file_name, default_restype):
        path = PurePath(str(file_name))
        stem = path.stem or path.name
        suffix = path.suffix[1:] if path.suffix else default_restype
        return stem.upper(), suffix.upper()

    def _load_text(self, file_name, default_restype, game):
        resref, restype = self._normalize_reference(file_name, default_restype)
        return self.loader.get_text_resource(resref, restype=restype, game=game)

    def _lookup_file(self, lookup, game):
        game_files = lookup.get("file_by_game", {}) or {}
        return game_files.get(game, lookup.get("file"))

    def get_ids(self, file_name, game):
        resref, restype = self._normalize_reference(file_name, "IDS")
        cache_key = (game, resref, restype)
        if cache_key not in self._ids_cache:
            text = self._load_text(file_name, "IDS", game)
            self._ids_cache[cache_key] = IdsHandler(text) if text is not None else None
        return self._ids_cache[cache_key]

    def get_2da(self, file_name, game):
        resref, restype = self._normalize_reference(file_name, "2DA")
        cache_key = (game, resref, restype)
        if cache_key not in self._twoda_cache:
            text = self._load_text(file_name, "2DA", game)
            self._twoda_cache[cache_key] = TwoDAHandler(text) if text is not None else None
        return self._twoda_cache[cache_key]

    def resolve(self, value, lookup, game):
        if not lookup or value is None:
            return None

        skip_values = set(lookup.get("skip_values", []))
        if value in skip_values:
            return None

        lookup_value = value
        value_offset = lookup.get("value_offset", 0)
        if isinstance(lookup_value, int) and value_offset:
            lookup_value += value_offset

        kind = str(lookup.get("kind", "")).lower()
        file_name = self._lookup_file(lookup, game)
        if not file_name:
            return None

        resolved = None
        if kind == "ids":
            table = self.get_ids(file_name, game)
            if table is not None:
                resolved = table.resolve(lookup_value)
        elif kind == "2da":
            table = self.get_2da(file_name, game)
            if table is not None:
                resolved = table.resolve(
                    lookup_value,
                    column=lookup.get("column"),
                    row_mode=lookup.get("row_mode", "label"),
                )

        if resolved is None:
            return None

        display = lookup.get("display", "resolved")
        if display == "value":
            return value
        if display == "both" and not isinstance(resolved, (dict, list)):
            return f"({value}) {resolved}"
        return resolved
