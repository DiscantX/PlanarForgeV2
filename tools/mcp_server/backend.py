"""Game data backends for the MCP tools.

``LoaderBackend`` reads from the installed games through ``ResourceLoader``.
``FakeBackend`` serves a few synthetic resources so the server can be tested
without any game installed (and without game content entering the repository).

Both implement the same small interface:

    list_games() -> list[dict]
    locate(game, resref, restype) -> dict
    describe(game, resref, restype) -> dict
    read_raw(game, resref, restype) -> bytes
"""

from pathlib import Path

_MAX_HEADER_FIELDS = 60
_MAX_STRING_CHARS = 80


class ResourceNotFound(LookupError):
    """Raised when a game or resource cannot be found."""


def _summarise_sections(sections):
    """Builds a facts-only summary (counts and field names) of parsed sections."""
    summary = {}
    for name, entries in sections.items():
        entries = list(entries) if not isinstance(entries, dict) else [entries]
        first = entries[0] if entries and isinstance(entries[0], dict) else {}
        summary[name] = {"entries": len(entries), "fields": list(first.keys())}
    return summary


def _scalar_header(sections):
    """Returns the first header entry's scalar values, without any bytes or text blocks."""
    entries = sections.get("header")
    if not entries:
        return {}
    first = entries[0] if isinstance(entries, list) else entries
    values = {}
    for key, value in first.items():
        if len(values) >= _MAX_HEADER_FIELDS:
            break
        if isinstance(value, (bool, int, float)):
            values[key] = value
        elif isinstance(value, str):
            values[key] = value[:_MAX_STRING_CHARS]
    return values


class LoaderBackend:
    """Backend that reads the installed games through ``ResourceLoader``."""

    def __init__(self):
        self._loader_instance = None

    def _loader(self):
        if self._loader_instance is None:
            from drivers.InfinityEngine.resource_loader import ResourceLoader
            self._loader_instance = ResourceLoader()
        return self._loader_instance

    def _install(self, game):
        install = self._loader()._get_install_path(game)
        if install is None:
            raise ResourceNotFound("Game %s is not installed. Installed: %s"
                                   % (game, ", ".join(g["game_id"] for g in self.list_games())
                                      or "none"))
        return Path(install)

    def list_games(self):
        found = self._loader().install_finder.find_all()
        return [{"game_id": g.game_id, "display_name": g.display_name,
                 "install_path": str(g.install_path), "source": g.source} for g in found]

    def _override_path(self, game, resref, restype):
        loader = self._loader()
        name = "%s.%s" % (loader._normalize_resref(resref), restype.lower())
        candidate = self._install(game) / "override" / name
        return candidate if candidate.exists() else None

    def read_raw(self, game, resref, restype):
        override = self._override_path(game, resref, restype)
        if override is not None:
            return override.read_bytes()
        raw, _, _ = self._loader().get_raw_bytes(resref, restype=restype, game=game)
        if raw is None:
            raise ResourceNotFound("%s.%s not found in %s" % (resref, restype, game))
        return raw

    def locate(self, game, resref, restype):
        loader = self._loader()
        override = self._override_path(game, resref, restype)
        result = {"game": game, "resref": resref.upper(), "restype": restype,
                  "override": None, "key_entry": None}
        if override is not None:
            result["override"] = {"file": override.name, "size": override.stat().st_size}
        entry = loader._find_resource_location(resref, restype=restype, game=game)
        if entry:
            locator = entry.get("resource_locator") or {}
            bif_path = loader._find_bif_file(entry, game)
            raw, _, _ = loader.get_raw_bytes(resref, restype=restype, game=game)
            result["key_entry"] = {
                "bif": Path(bif_path).name if bif_path else None,
                "resource_index": locator.get("resource_index"),
                "tileset_index": locator.get("tileset_index"),
                "resource_type_code": entry.get("resource_type"),
                "size": len(raw) if raw is not None else None,
            }
        if result["override"] is None and result["key_entry"] is None:
            raise ResourceNotFound("%s.%s not found in %s" % (resref, restype, game))
        return result

    def describe(self, game, resref, restype):
        resource = self._loader().load(resref, restype=restype, game=game)
        if resource is None:
            raise ResourceNotFound("%s.%s could not be loaded from %s" % (resref, restype, game))
        schema = getattr(resource, "schema", None)
        return {
            "game": game, "resref": resref.upper(), "restype": restype,
            "schema": getattr(schema, "name", None) or str(schema),
            "sections": _summarise_sections(resource.sections),
            "header": _scalar_header(resource.sections),
        }


class FakeBackend:
    """Backend serving synthetic data, for tests."""

    _RESOURCES = {
        ("TEST01", "ARE"): b"AREAV1.0" + bytes((i * 7) % 256 for i in range(600)),
        ("TEST02", "ITM"): b"ITM V1  " + bytes(range(120)),
    }

    def list_games(self):
        return [{"game_id": "FAKE", "display_name": "Fake Game", "install_path": None,
                 "source": "synthetic"}]

    def _get(self, game, resref, restype):
        if game != "FAKE":
            raise ResourceNotFound("Game %s is not installed. Installed: FAKE" % game)
        data = self._RESOURCES.get((resref.upper(), restype.upper()))
        if data is None:
            raise ResourceNotFound("%s.%s not found in %s" % (resref, restype, game))
        return data

    def read_raw(self, game, resref, restype):
        return self._get(game, resref, restype)

    def locate(self, game, resref, restype):
        data = self._get(game, resref, restype)
        return {"game": game, "resref": resref.upper(), "restype": restype, "override": None,
                "key_entry": {"bif": "FAKE.BIF", "resource_index": 0, "tileset_index": None,
                              "resource_type_code": 0, "size": len(data)}}

    def describe(self, game, resref, restype):
        data = self._get(game, resref, restype)
        return {"game": game, "resref": resref.upper(), "restype": restype, "schema": "fake",
                "sections": {"header": {"entries": 1, "fields": ["signature", "size"]}},
                "header": {"signature": data[:4].decode("latin-1"), "size": len(data)}}
