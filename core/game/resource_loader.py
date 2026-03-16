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
        
        self.chitin = self._load_chitin(self.default_game)
        
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
            bif_table = self.chitin.sections["bif_entries"]
            resource_table = self.chitin.sections["resource_entries"]
            for bif_entry in bif_table:
                print(bif_entry)
                print(self._resolve_resource_location(bif_entry, game))
            return self.chitin
    
    def _resolve_resource_location(self, bif_entry, game=default_game):
        chitin_path = self.install_finder.find_chitin(game)    
        with open(chitin_path, "rb") as f:
            BinaryReader(f).seek(bif_entry.get("offset_from_start_to_filename"))
            try:
                filename = BinaryReader(f).read_string(bif_entry.get("length_of_filename"))
            except Exception as e:
                print(f"Error reading filename for bif entry {bif_entry}: {e}")
                return None
            return filename
    
    def _load_chitin(self, game):
        ##NOTE: Look into caching this since it's needed for every resource load and is always the same for a given game
        chitin_path = self.install_finder.find_chitin(game)
        if chitin_path is None:
            print(f"Failed to find CHITIN.KEY for game {game}.")
            return None
        chitin_schema = self.schema_loader.get("CHITIN")
        chitin = self.load_file(resref="CHITIN", restype="KEY", game=game, file_path=chitin_path, schema=chitin_schema)
        if chitin is None:
            print(f"Failed to load CHITIN.KEY for game {game}.")
            return None
        return chitin
    
    def decode_resource_locator(self, locator):
        resource_index = locator & 0x3FFF
        reserved = (locator >> 14) & 0x3F
        bif_index = locator >> 20

        return {
            "bif_index": bif_index,
            "resource_index": resource_index,
            "reserved": reserved
        }
                