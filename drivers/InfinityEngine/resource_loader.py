import io
from pathlib import Path
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.binary.writer import BinaryWriter
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.resource import Resource

# Import internal driver components
from .installation_finder import InstallationFinder
from .resource_types import RESOURCE_TYPE_MAP, RESOURCE_TYPE_MAP_REV
from .biff_handler import BiffHandler
# Import types to ensure they register themselves with FieldTypes
from . import types

class ResourceLoader:
    default_resref = "CHITIN"
    default_restype = "KEY"
    default_game = "BG2EE"
     
    def __init__(self, install_finder=None, schema_loader=None):
        self.install_finder = install_finder or InstallationFinder()
        
        if schema_loader:
            self.schema_loader = schema_loader
        else:
            schema_path = Path(__file__).parent / "schemas"
            self.schema_loader = SchemaLoader(schema_path)

        self.schema_loader.load_all()
        self.schema_loader.resolve_types(FieldTypes)
        
        self.chitins = {}
        self.resource_maps = {}
        self.install_paths = {}
        self.biff_handler = BiffHandler()
        self._load_chitin(self.default_game)
        
    def load_file(self, resref = default_resref, restype = default_restype, game = default_game, file_path=None, schema=None):
        if schema is None:
            schema = self.schema_loader.get(restype)
        if file_path is None:
            print(f"No file path provided when loading resource {resref} of type {restype}.")
            return None
        
        with open(file_path, "rb") as f:
            reader = BinaryReader(f)
            parser = BinaryParser(schema, resource_class=Resource)
            resource = parser.read(reader, name=resref, source=file_path)
        return resource

    def save_file(self, resource, file_path):
        """
        Saves a Resource object to a specified file path.
        """
        if not resource or not resource.schema:
            print("Cannot save resource: Invalid resource or schema missing.")
            return

        parser = BinaryParser(resource.schema)
        
        try:
            with open(file_path, "wb") as f:
                writer = BinaryWriter(f)
                parser.write(writer, resource)
        except Exception as e:
            print(f"Error saving resource to {file_path}: {e}")

    def get_raw_bytes(self, resref, restype=None, game=default_game):
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

    def load(self, resref=default_resref, restype=default_restype, game=default_game, file_path=None, schema=None):
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
            resource_schema = schema or self.schema_loader.get(restype)
            if resource_schema is None:
                print(f"No schema found for resource type '{restype}'. Cannot parse {resref}.")
                return None

            # Use a BytesIO stream to treat the raw bytes as a file for the parser.
            bytes_reader = BinaryReader(io.BytesIO(raw_bytes))
            parser = BinaryParser(resource_schema, resource_class=Resource)
            
            # Parse the final resource and return it.
            return parser.read(bytes_reader, name=resref, source=f"BIF: {source_path}")
            
    def _find_bif_file(self, res_entry, game=default_game):
        chitin = self.chitins.get(game)
        if not chitin:
            return None
            
        bif_entries = chitin.sections.get("bif_entries", [])
        locator = res_entry.get("resource_locator")
        bif_index = locator.get("bif_index")
        if bif_index >= len(bif_entries):
            print(f"BIF index {bif_index} out of range.")
            return None
        filename =bif_entries[bif_index].get("filename")

        install_path = self._get_install_path(game)
        if not install_path:
             return None

        file_path = Path(f"{install_path}/{filename}")
        return file_path
    
    def _find_resource_location(self, resref, restype=None, game=default_game):
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
            target_code = RESOURCE_TYPE_MAP_REV.get(restype, restype)

            for entry in entries:
                if entry.get("resource_type") == target_code:
                    return entry
            
        if restype:
            print(f"Warning: Resource {resref} found, but type '{restype}' mismatch. Returning first match ({RESOURCE_TYPE_MAP.get(entries[0].get('resource_type'))}).")
        return entries[0]
    
    def _get_install_path(self, game):
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

        chitin_path = self.install_finder.find_chitin(game)
        if chitin_path is None:
            print(f"Failed to find CHITIN.KEY for game {game}.")
            return None
        chitin_schema = self.schema_loader.get("CHITIN")
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
