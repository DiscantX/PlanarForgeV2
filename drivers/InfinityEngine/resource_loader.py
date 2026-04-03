import io
import sys
import threading
from pathlib import Path, PureWindowsPath
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.binary.writer import BinaryWriter
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.resource import Resource

# Import internal driver components
from .io.installation_finder import InstallationFinder
from .definitions.extensions import RESOURCE_TYPE_MAP, RESOURCE_TYPE_MAP_REV
from .io.biff_handler import BiffHandler
from .io.tlk_handler import TlkHandler
from .io.table_resolver import TableResolver, decode_ie_text_resource
# Import definitions to ensure types register themselves with FieldTypes
from .definitions import types

class ResourceLoader:
    default_resref = "CHITIN"
    default_restype = "KEY"
     
    def __init__(self, install_finder=None, schema_loader=None, parser_options=None):
        self.install_finder = install_finder or InstallationFinder()
        self.parser_options = dict(parser_options or {})
        
        if schema_loader:
            self.schema_loader = schema_loader
        else:
            schema_path = Path(__file__).parent / "definitions" / "schemas"
            self.schema_loader = SchemaLoader(schema_path)

        self.schema_loader.load_all()
        self.schema_loader.resolve_types(FieldTypes)
        
        self.chitins = {}
        self.resource_maps = {}
        self.install_paths = {}
        self._resolved_bif_paths = {}
        self._reported_missing_bifs = set()
        self._mounted_drive_roots = None
        self._lock = threading.RLock()
        self.biff_handler = BiffHandler()
        self.tlk_handlers = {}
        self.table_resolver = TableResolver(self)
        
        # Determine default game from available installations
        found_games = self.install_finder.find_all()
        if found_games:
            self.default_game = found_games[0].game_id
            # self._load_chitin(self.default_game)
        else:
            self.default_game = None
            print("Warning: No Infinity Engine game installations found.")
        
    def load_file(self, resref = default_resref, restype = default_restype, game = None, file_path=None, schema=None):
        game = game or self.default_game
        if file_path is None:
            print(f"No file path provided when loading resource {resref} of type {restype}.")
            return None
        
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        schema = self._resolve_resource_schema(restype, game, raw_bytes=raw_bytes, schema=schema)
        if schema is None:
            print(f"Error: No schema found for type '{restype}' (resref: {resref}).")
            return None

        reader = BinaryReader(io.BytesIO(raw_bytes))
        parser = BinaryParser(schema, resource_class=Resource, **self.parser_options)
        resource = parser.read(reader, name=resref, source=file_path)
        resource._original_bytes = raw_bytes
        return self._attach_runtime_context(resource, game)

    def save_file(self, resource, file_path):
        """
        Saves a Resource object to a specified file path.
        """
        if not resource or not resource.schema:
            print("Cannot save resource: Invalid resource or schema missing.")
            return

        parser = BinaryParser(resource.schema, **self.parser_options)
        
        try:
            with open(file_path, "wb") as f:
                writer = BinaryWriter(f)
                parser.write(writer, resource)
        except Exception as e:
            print(f"Error saving resource to {file_path}: {e}")

    def get_raw_bytes(self, resref, restype=None, game=None):
        game = game or self.default_game
        """
        Finds a resource and extracts its raw byte data from its source BIF.
        Returns a tuple of (raw_bytes, source_path, resource_type_code).
        """
        res_entry = self._find_resource_location(resref, restype=restype, game=game)
        if not res_entry:
            return None, None, None

        resource_index = res_entry.get("resource_locator").get("resource_index")
        bif_file_path = self._find_bif_file(res_entry, game)
        if not bif_file_path:
            return None, None, None

        try:
            raw_bytes = self.biff_handler.get_resource_data(bif_file_path, resource_index)
            if raw_bytes is None:
                return None, None, None
            
            res_type_code = res_entry.get("resource_type")
            return raw_bytes, bif_file_path, res_type_code

        except (FileNotFoundError, Exception) as e:
            print(f"Error processing BIF/resource for {resref} in {bif_file_path}: {e}")
            return None, None, None

    def get_string(self, strref, game=None):
        """
        Resolves a StrRef index to its text string for the specified game.
        """
        game = game or self.default_game
        handler = self._get_tlk_handler(game)
        if not handler:
            return f"<Missing TLK: {strref}>"
        
        text = handler.get_string(strref)
        # Return None if lookup failed, so caller can distinguish from empty string
        return text

    def get_text_resource(self, resref, restype, game=None):
        """
        Loads a text resource (IDS/2DA/etc.) from override or BIFF and returns
        its decoded text content.
        """
        game = game or self.default_game
        restype = str(restype).upper()
        resref = str(resref).upper()

        install_path = self._get_install_path(game)
        if install_path is not None:
            filename = f"{resref}.{restype.lower()}"
            for candidate in (install_path / "override" / filename, install_path / filename):
                if candidate.exists():
                    return decode_ie_text_resource(candidate.read_bytes())

        res_entry = self._find_exact_resource_location(resref, restype=restype, game=game)
        if not res_entry:
            return None

        resource_index = res_entry.get("resource_locator").get("resource_index")
        bif_file_path = self._find_bif_file(res_entry, game)
        if not bif_file_path:
            return None

        raw_bytes = self.biff_handler.get_resource_data(bif_file_path, resource_index)
        if raw_bytes is None:
            return None

        return decode_ie_text_resource(raw_bytes)

    def load(self, resref=default_resref, restype=default_restype, game=None, file_path=None, schema=None):
        game = game or self.default_game
        if file_path:
            return self.load_file(resref=resref, restype=restype, game=game, file_path=file_path, schema=schema)
        else:
            install_path = self._get_install_path(game)
            if install_path is None:
                print(f"No installation found for game {game}.")
                return None

            raw_bytes, source_path, res_type_code = self.get_raw_bytes(resref, restype=restype, game=game)
            if raw_bytes is None:
                return None
            
            if restype == self.default_restype and res_type_code in RESOURCE_TYPE_MAP:
                restype = RESOURCE_TYPE_MAP[res_type_code]

            # Get the schema for the actual resource type (e.g., ITM, CRE).
            resource_schema = self._resolve_resource_schema(restype, game, raw_bytes=raw_bytes, schema=schema)
            if resource_schema is None:
                print(f"No schema found for resource type '{restype}'. Cannot parse {resref}.")
                return None

            # Use a BytesIO stream to treat the raw bytes as a file for the parser.
            bytes_reader = BinaryReader(io.BytesIO(raw_bytes))
            parser = BinaryParser(resource_schema, resource_class=Resource, **self.parser_options)
            
            # Parse the final resource and return it.
            resource = parser.read(bytes_reader, name=resref, source=f"BIF: {source_path}")
            resource._original_bytes = raw_bytes
            return self._attach_runtime_context(resource, game)

    def iter_resources(self, game=None):
        """
        A generator that yields metadata for all known resources for a given game.
        Ensures CHITIN.KEY is loaded and yields a tuple for each resource entry.

        Yields:
            (resref_str, restype_str, chitin_entry_dict)
        """
        game = game or self.default_game
        if game not in self.chitins:
            self._load_chitin(game)

        resource_map = self.resource_maps.get(game)
        if not resource_map:
            # This should not happen if _load_chitin was successful
            print(f"Warning: No resource map available for {game} during iteration.")
            return

        for resref, entries in resource_map.items():
            for entry in entries:
                res_type_code = entry.get("resource_type")
                res_type_str = RESOURCE_TYPE_MAP.get(res_type_code, "UNKN")
                yield (resref, res_type_str, entry)

    def _resolve_resource_schema(self, restype, game, raw_bytes=None, schema=None):
        if schema is not None:
            return schema

        resolved = self.schema_loader.get(restype, game=game)
        if resolved is None or raw_bytes is None:
            return resolved

        def _field_offset(schema_obj, section_name, field_name):
            section = schema_obj.get_section(section_name) if schema_obj else None
            if not section:
                return None
            field = section.get_field(field_name)
            if not field:
                return None
            offset = field.attributes.get("offset")
            return offset if isinstance(offset, int) else None

        def _dword_at(blob, offset):
            if offset is None or offset < 0 or offset + 4 > len(blob):
                return None
            return int.from_bytes(blob[offset:offset + 4], "little")

        def _section_entry_span(schema_obj, section_name):
            section = schema_obj.get_section(section_name) if schema_obj else None
            if not section:
                return 0

            end = 0
            for field in section.fields:
                size = field.attributes.get("size", 0) or 0
                offset = field.attributes.get("offset", 0) or 0
                if size <= 0:
                    continue
                field_end = int(offset) + int(size)
                if field_end > end:
                    end = field_end
            return end

        # PSTEE mostly uses a dedicated V1.0 CRE layout, but four legacy CRE
        # resources in the game still use the older PST V1.1/V1.2-style header.
        # Their section offsets live later in the header (0x0344+), so routing
        # them through the PSTEE V1.0 schema truncates the file at the header.
        if restype == "CRE" and game == "PSTEE" and len(raw_bytes) >= 8:
            version = raw_bytes[4:8].decode("latin-1", errors="ignore").rstrip("\x00")
            if version == "V1.1":
                legacy_pst_schema = self.schema_loader.get("CRE", game="PST")
                if legacy_pst_schema is not None:
                    pst_item_slots_off_field = _field_offset(
                        legacy_pst_schema, "header", "offset_to_item_slots"
                    )
                    pst_item_slots_off = _dword_at(raw_bytes, pst_item_slots_off_field)
                    pst_item_slots_span = _section_entry_span(legacy_pst_schema, "item_slots")

                    # Route to legacy PST schema only if its item-slots pointer is
                    # physically valid for that schema's expected entry span.
                    # Some PSTEE placeholder CRE V1.1 files are zero-filled stubs
                    # where PST offsets point near EOF and would overrun.
                    if (
                        isinstance(pst_item_slots_off, int) and
                        pst_item_slots_off > 0 and
                        pst_item_slots_span > 0 and
                        pst_item_slots_off + pst_item_slots_span <= len(raw_bytes)
                    ):
                        return legacy_pst_schema

                    # Keep PSTEE schema for V1.1 stubs/placeholder records.
                    return resolved

                # No PST fallback available; keep PSTEE schema.
                return resolved

        # IWD2 mostly uses CRE V2.2, but four legacy test creatures are V9.1
        # and match the classic IWD CRE layout.
        if restype == "CRE" and game == "IWD2" and len(raw_bytes) >= 8:
            version = raw_bytes[4:8].decode("latin-1", errors="ignore").rstrip("\x00")
            if version == "V9.1":
                legacy_iwd_schema = self.schema_loader.get("CRE", game="IWD")
                if legacy_iwd_schema is not None:
                    return legacy_iwd_schema

        # PSTEE ARE files often use the legacy PST V1.0 header layout.
        # We use a heuristic to distinguish them from standard EE layouts:
        # Legacy PST has Actor offset at 0x84, standard EE has it at 0x54.
        if restype == "ARE" and game == "PSTEE" and len(raw_bytes) >= 0x88:
            version = raw_bytes[4:8].decode("latin-1", errors="ignore").rstrip("\x00")
            if version == "V1.0":
                ee_actor_off = int.from_bytes(raw_bytes[0x54:0x58], 'little')
                pst_actor_off = int.from_bytes(raw_bytes[0x84:0x88], 'little')
                
                if ee_actor_off == 0 and pst_actor_off > 0:
                    legacy_pst_schema = self.schema_loader.get("ARE", game="PST")
                    if legacy_pst_schema is not None:
                        return legacy_pst_schema

        return resolved
            
    def _find_bif_file(self, res_entry, game=None):
        game = game or self.default_game
        chitin = self.chitins.get(game)
        if not chitin:
            return None
            
        bif_entries = chitin.sections.get("bif_entries", [])
        locator = res_entry.get("resource_locator")
        bif_index = locator.get("bif_index")
        if bif_index >= len(bif_entries):
            print(f"BIF index {bif_index} out of range.")
            return None
        
        cache_key = (game, bif_index)
        cached_path = self._resolved_bif_paths.get(cache_key)
        if cached_path is not None:
            if cached_path.exists():
                return cached_path
            # Path may disappear if media is unmounted; re-resolve.
            self._resolved_bif_paths.pop(cache_key, None)

        bif_entry = bif_entries[bif_index]
        filename = bif_entry.get("filename")
        file_location = bif_entry.get("file_location")

        install_path = self._get_install_path(game)
        if not install_path:
             return None

        candidate_paths = self._build_bif_candidate_paths(
            install_path=install_path,
            filename=filename,
            file_location=file_location,
        )

        for candidate in candidate_paths:
            if candidate.exists():
                self._resolved_bif_paths[cache_key] = candidate
                return candidate

        if cache_key not in self._reported_missing_bifs:
            checked = ", ".join(str(path) for path in candidate_paths[:6])
            if len(candidate_paths) > 6:
                checked += ", ..."
            print(
                f"Unable to resolve BIF path for '{filename}' in {game}. "
                f"Checked: {checked}"
            )
            self._reported_missing_bifs.add(cache_key)

        return None

    def _build_bif_candidate_paths(self, install_path, filename, file_location):
        filename = self._normalize_bif_filename(filename)
        if not filename:
            return []

        candidates = []
        if self._looks_absolute_path(filename):
            candidates.append(Path(filename))

        relative_path = self._to_relative_bif_path(filename)
        if relative_path is None:
            return self._dedupe_paths(candidates)

        basename = Path(relative_path.name) if relative_path.name else None
        search_roots = self._build_bif_search_roots(install_path, file_location)

        for root in search_roots:
            candidates.append(root / relative_path)
            if basename is not None and basename != relative_path:
                candidates.append(root / basename)

        return self._dedupe_paths(candidates)

    def _build_bif_search_roots(self, install_path, file_location):
        file_location = file_location or {}
        roots = []

        cd_numbers = [
            cd_number
            for cd_number in range(1, 7)
            if file_location.get(f"is_on_cd{cd_number}")
        ]

        for cd_number in cd_numbers:
            cd_dir = f"CD{cd_number}"
            roots.append(install_path / cd_dir)
            roots.append(install_path.parent / cd_dir)

        if cd_numbers:
            roots.extend(self._get_mounted_drive_roots())

        if file_location.get("is_in_cache"):
            roots.append(install_path / "cache")

        if file_location.get("is_in_data"):
            roots.append(install_path / "data")

        # Always include install root as a generic fallback.
        roots.append(install_path)

        return self._dedupe_paths(roots)

    def _normalize_bif_filename(self, filename):
        if filename is None:
            return None

        normalized = str(filename).split("\x00", 1)[0].strip()
        return normalized or None

    def _looks_absolute_path(self, path_text):
        path_obj = Path(path_text)
        windows_path = PureWindowsPath(path_text)
        return path_obj.is_absolute() or windows_path.is_absolute()

    def _to_relative_bif_path(self, filename):
        normalized = filename.replace("\\", "/").strip()
        if len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/":
            normalized = normalized[3:]

        normalized = normalized.lstrip("/")
        if not normalized:
            return None

        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts:
            return None

        return Path(*parts)

    def _get_mounted_drive_roots(self):
        if self._mounted_drive_roots is not None:
            return self._mounted_drive_roots

        if sys.platform != "win32":
            self._mounted_drive_roots = []
            return self._mounted_drive_roots

        drive_roots = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:/")
            if root.exists():
                drive_roots.append(root)

        self._mounted_drive_roots = drive_roots
        return self._mounted_drive_roots

    def _dedupe_paths(self, paths):
        unique_paths = []
        seen = set()
        for path in paths:
            if path is None:
                continue
            key = str(path).replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(path)
        return unique_paths

    def _get_tlk_handler(self, game):
        if game in self.tlk_handlers:
            return self.tlk_handlers[game]

        with self._lock:
            if game in self.tlk_handlers:
                return self.tlk_handlers[game]
            
            tlk_path = self.install_finder.find_tlk(game)
            # We allow the handler to be created even if path is None, it just won't work.
            # Better to return None here to signal failure.
            if not tlk_path:
                return None
            
            self.tlk_handlers[game] = TlkHandler(tlk_path)
            return self.tlk_handlers[game]

    def _attach_runtime_context(self, resource, game):
        if resource is None:
            return None

        resource.game = game
        resource.strref_resolver = lambda strref, _game=game: self.get_string(strref, game=_game)
        resource.table_resolver = self.table_resolver
        return resource
    
    def _find_resource_location(self, resref, restype=None, game=None):
        game = game or self.default_game
        if game not in self.chitins:
            self._load_chitin(game)
            
        resource_map = self.resource_maps.get(game)
        if not resource_map:
            print(f"CHITIN.KEY map not found for game {game}.")
            return None
        
        entries = resource_map.get(resref.upper())
        if not entries:
            print(f"Resource {resref} not found in CHITIN.KEY for {game}.")
            return None

        if restype:
            target_code = RESOURCE_TYPE_MAP_REV.get(restype)
            if target_code is not None:
                target_code = int(target_code)

            for entry in entries:
                if int(entry.get("resource_type", -1)) == target_code:
                    return entry
            
        if restype:
            print(f"Warning: Resource {resref} found, but type '{restype}' mismatch. Returning first match ({RESOURCE_TYPE_MAP.get(entries[0].get('resource_type'))}).")
        return entries[0]

    def _find_exact_resource_location(self, resref, restype, game=None):
        game = game or self.default_game
        if game not in self.chitins:
            self._load_chitin(game)

        resource_map = self.resource_maps.get(game)
        if not resource_map:
            return None

        entries = resource_map.get(str(resref).upper())
        if not entries:
            return None

        # Ensure target_code and entry types are comparable (integers)
        target_code = RESOURCE_TYPE_MAP_REV.get(restype)
        if target_code is not None:
            target_code = int(target_code)

        for entry in entries:
            if int(entry.get("resource_type", -1)) == target_code:
                return entry

        return None

    
    def _get_install_path(self, game):
        if game in self.install_paths:
            return self.install_paths[game]

        with self._lock:
            if game in self.install_paths:
                return self.install_paths[game]
                
            found = self.install_finder.find(game)
            if found:
                self.install_paths[game] = found.install_path
                return found.install_path
            return None

    def _load_chitin(self, game):
        if game in self.chitins:
            return self.chitins[game]

        with self._lock:
            if game in self.chitins:
                return self.chitins[game]

            chitin_path = self.install_finder.find_chitin(game)
            if chitin_path is None:
                print(f"Failed to find CHITIN.KEY for game {game}.")
                return None
            chitin_schema = self.schema_loader.get("CHITIN", game=game)
            chitin = self.load_file(resref="CHITIN", restype="KEY", game=game, file_path=chitin_path, schema=chitin_schema)
            if chitin is None:
                print(f"Failed to load CHITIN.KEY for game {game}.")
                return None
                
            self.chitins[game] = chitin
            
            res_map = {}
            for entry in chitin.sections.get("resource_entries", []):
                res_name = entry.get("resource_name", "").upper()
                if res_name:
                    if res_name not in res_map:
                        res_map[res_name] = []
                    res_map[res_name].append(entry)
            self.resource_maps[game] = res_map
            
            return chitin
