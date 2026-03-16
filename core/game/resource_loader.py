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
            res_entry = self._find_resource_location(resref)
            if not res_entry:
                return None

            # TODO: The resource type is an integer in the KEY file. We should have a map
            # to resolve this integer (e.g., 1002) to a string ("ITM") to automatically
            # select the correct schema, instead of relying on the `restype` parameter.
            
            resource_index = res_entry.get("resource_locator").get("resource_index")
            bif_file_path = self._find_bif_file(res_entry)
            if not bif_file_path:
                return None

            # Parse the BIF file's structure to find the resource's location and size
            bif_file = self.load_file(resref="BIF", restype="BIFF", game=game, file_path=bif_file_path, schema=self.schema_loader.get("BIFF"))
            if not bif_file:
                print(f"Failed to parse BIF file: {bif_file_path}")
                return None

            file_entries = bif_file.sections.get('file_entries', [])
            if resource_index >= len(file_entries):
                print(f"Resource index {resource_index} is out of bounds for BIF {bif_file_path}")
                return None

            bif_resource_entry = file_entries[resource_index]
            offset = bif_resource_entry.get("offset")
            size = bif_resource_entry.get("size_of_this_resource")

            # Extract the raw bytes of the final resource from the BIF file.
            with open(bif_file_path, "rb") as f:
                f.seek(offset)
                raw_bytes = f.read(size)

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
        bif_entries = self.chitin.sections.get("bif_entries", [])
        locator = res_entry.get("resource_locator")
        bif_index = locator.get("bif_index")
        if bif_index >= len(bif_entries):
            print(f"BIF index {bif_index} out of range.")
            return None
        filename =bif_entries[bif_index].get("filename")
        file_path = Path(f"{self.install_finder.find(game).install_path}/{filename}")
        return file_path
    
    def _find_resource_location(self, resref):
        if self.chitin is None:
            print("CHITIN.KEY not loaded, cannot find resource location.")
            return None
        
        resource_entries = self.chitin.sections.get("resource_entries", [])
        for entry in resource_entries:
            if entry.get("resource_name") == resref:
                return entry
        
        print(f"Resource {resref} not found in CHITIN.KEY.")
        return None
    
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
                