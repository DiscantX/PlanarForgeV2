import io
import zlib
from contextlib import contextmanager
from pathlib import Path
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.binary.writer import BinaryWriter
from core.game.installation_finder import InstallationFinder
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.game.resource_types import RESOURCE_TYPE_MAP

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
        self.install_paths = {}
        self.bif_headers = {}
        self.decompressed_bif_cache = {}
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

    @contextmanager
    def _get_bif_stream(self, bif_file_path):
        """
        A context manager that provides a file-like object for BIFF data,
        decompressing BIFC files on the fly and caching the result.
        """
        cache_key = str(bif_file_path)
        if cache_key in self.decompressed_bif_cache:
            stream = self.decompressed_bif_cache[cache_key]
            stream.seek(0)
            yield stream
            return

        with open(bif_file_path, "rb") as f:
            signature = f.read(4)
            f.seek(0)

            if signature == b'BIFF':
                yield f
                return

            # If not BIFF, we decompress into memory and cache it.
            decompressed_stream = None
            reader = BinaryReader(f)

            if signature == b'BIF ':  # BIFC V1 wrapper
                reader.seek(8)  # Skip signature and version
                filename_len = reader.read_uint32()
                reader.read(filename_len)  # Skip filename
                uncompressed_size = reader.read_uint32()
                compressed_size = reader.read_uint32()
                
                compressed_data = reader.read(compressed_size)
                decompressed_data = zlib.decompress(compressed_data)
                
                if len(decompressed_data) != uncompressed_size:
                    raise ValueError(f"BIFC V1 decompression error in {bif_file_path}: size mismatch.")
                
                decompressed_stream = io.BytesIO(decompressed_data)

            elif signature == b'BIFC':  # BIFC V1.0 block-based
                reader.seek(8)  # Skip signature and version
                uncompressed_bif_size = reader.read_uint32()
                
                output_stream = io.BytesIO()
                total_decompressed = 0
                
                file_size = reader.size()
                while reader.tell() < file_size and total_decompressed < uncompressed_bif_size:
                    decompressed_block_size = reader.read_uint32()
                    compressed_block_size = reader.read_uint32()
                    
                    if compressed_block_size == 0 and decompressed_block_size == 0:
                        break

                    compressed_block = reader.read(compressed_block_size)
                    decompressed_block = zlib.decompress(compressed_block)
                    
                    if len(decompressed_block) != decompressed_block_size:
                        raise ValueError(f"BIFC V1.0 block decompression error in {bif_file_path}: block size mismatch.")
                    
                    output_stream.write(decompressed_block)
                    total_decompressed += len(decompressed_block)

                if total_decompressed != uncompressed_bif_size:
                    raise ValueError(f"BIFC V1.0 decompression error in {bif_file_path}: final size mismatch.")
                
                decompressed_stream = output_stream

            else:
                raise ValueError(f"Unknown or unsupported BIF format with signature {signature} in file {bif_file_path}")

            if decompressed_stream:
                self.decompressed_bif_cache[cache_key] = decompressed_stream
                decompressed_stream.seek(0)
                yield decompressed_stream

    def get_raw_bytes(self, resref, game=default_game):
        """
        Finds a resource and extracts its raw byte data from its source BIF.
        Returns a tuple of (raw_bytes, source_path, resource_type_code).
        """
        res_entry = self._find_resource_location(resref, game)
        if not res_entry:
            return None, None, None

        resource_index = res_entry.get("resource_locator").get("resource_index")
        bif_file_path = self._find_bif_file(res_entry, game)
        if not bif_file_path:
            return None, None, None

        try:
            with self._get_bif_stream(bif_file_path) as bif_stream:
                reader = BinaryReader(bif_stream)
                cache_key = str(bif_file_path)
                cached_header = self.bif_headers.get(cache_key)
                
                if cached_header:
                    file_count, file_entries_offset = cached_header
                else:
                    reader.seek(0x08)
                    file_count = reader.read_uint32()
                    reader.seek(0x10)
                    file_entries_offset = reader.read_uint32()
                    self.bif_headers[cache_key] = (file_count, file_entries_offset)
                
                if resource_index >= file_count:
                    return None, None, None
                
                entry_size = 16
                entry_offset = file_entries_offset + (resource_index * entry_size)
                
                reader.seek(entry_offset + 4)
                resource_offset = reader.read_uint32()
                resource_size = reader.read_uint32()
                
                reader.seek(resource_offset)
                raw_bytes = reader.read(resource_size)
                
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

            raw_bytes, source_path, res_type_code = self.get_raw_bytes(resref, game)
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
            parser = BinaryParser(resource_schema)
            
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
        self.resource_maps[game] = {
            entry.get("resource_name").upper(): entry 
            for entry in chitin.sections.get("resource_entries", [])
            if entry.get("resource_name")
        }
        
        return chitin
                