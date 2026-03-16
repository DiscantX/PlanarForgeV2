import io
from pathlib import Path
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.game.installation_finder import InstallationFinder
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes

class ResourceLoader:
    default_resref = "CHITIN"
    default_restype = "KEY"
    default_game = "BG2EE"
     
    def __init__(self, install_finder=None, schema_loader=None):
        self.install_finder = install_finder or InstallationFinder()
        self.schema_loader = schema_loader or SchemaLoader("schemas")
        self.schema_loader.load_all()
        self.schema_loader.resolve_types(FieldTypes)
        
        self.chitins = {}
        self.resource_maps = {}
        self._load_chitin(self.default_game)
        
    def load_file(self, resref = default_resref, restype = default_restype, game = default_game, file_path=None, schema=None):
        if schema is None:
            schema = self.schema_loader.get(restype)
        if file_path is None:
            print(f"No file path provided when loading resource {resref} of type {restype}.")
            return None
        
        with open(file_path, "rb") as f:
            reader = BinaryReader(f)
            parser = BinaryParser(schema)
            resource = parser.read(reader, name=resref, source=file_path)
        return resource
    
    def load(self, resref=default_resref, restype=default_restype, game=default_game, file_path=None, schema=None):
        if file_path:
            return self.load_file(resref=resref, restype=restype, game=game, file_path=file_path, schema=schema)
        else:
            install_path = self.install_finder.find(game)
            if install_path is None:
                print(f"No installation found for game {game}.")
                return None
            res_entry = self._find_resource_location(resref, game)
            if not res_entry:
                return None

            # TODO: The resource type is an integer in the KEY file. We should have a map
            # to resolve this integer (e.g., 1002) to a string ("ITM") to automatically
            # select the correct schema, instead of relying on the `restype` parameter.
            
            resource_index = res_entry.get("resource_locator").get("resource_index")
            bif_file_path = self._find_bif_file(res_entry, game)
            if not bif_file_path:
                return None

            # Optimization: Random Access BIF Reading
            # Instead of parsing the whole BIF, we read the header and jump to the specific entry.
            with open(bif_file_path, "rb") as f:
                reader = BinaryReader(f)
                
                # BIFF Header: 
                # 0x08: Count of file entries (4 bytes)
                # 0x10: Offset to file entries (4 bytes)
                reader.seek(0x08)
                file_count = reader.read_uint32()
                
                reader.seek(0x10)
                file_entries_offset = reader.read_uint32()
                
                if resource_index >= file_count:
                    print(f"Resource index {resource_index} is out of bounds for BIF {bif_file_path}")
                    return None
                
                # BIF Entry format:
                # Locator (4), Offset (4), Size (4), Type (2), Unknown (2) = 16 bytes
                entry_size = 16
                entry_offset = file_entries_offset + (resource_index * entry_size)
                
                # Seek to entry (skip first 4 bytes for Locator) to read Offset and Size
                reader.seek(entry_offset + 4)
                resource_offset = reader.read_uint32()
                resource_size = reader.read_uint32()
                
                # Read the actual resource data
                reader.seek(resource_offset)
                raw_bytes = reader.read(resource_size)

            # Get the schema for the actual resource type (e.g., ITM, CRE).
            resource_schema = schema or self.schema_loader.get(restype)
            if resource_schema is None:
                print(f"No schema found for resource type '{restype}'. Cannot parse {resref}.")
                return None

            # Use a BytesIO stream to treat the raw bytes as a file for the parser.
            bytes_reader = BinaryReader(io.BytesIO(raw_bytes))
            parser = BinaryParser(resource_schema)
            
            # Parse the final resource and return it.
            return parser.read(bytes_reader, name=resref, source=f"BIF: {bif_file_path}")
            
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
        file_path = Path(f"{self.install_finder.find(game).install_path}/{filename}")
        return file_path
    
    def _find_resource_location(self, resref, game=default_game):
        if game not in self.chitins:
            self._load_chitin(game)
            
        resource_map = self.resource_maps.get(game)
        if not resource_map:
            print(f"CHITIN.KEY map not found for game {game}.")
            return None
        
        entry = resource_map.get(resref.upper())
        if not entry:
            print(f"Resource {resref} not found in CHITIN.KEY for {game}.")
            
        return entry
    
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
        self.resource_maps[game] = {
            entry.get("resource_name").upper(): entry 
            for entry in chitin.sections.get("resource_entries", [])
            if entry.get("resource_name")
        }
        
        return chitin
                