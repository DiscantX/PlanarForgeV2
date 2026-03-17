"""
Handles low-level access to BIFF files, including signature detection,
decompression of BIFC/BIF variants, and stream caching.
"""
import io
import zlib
from contextlib import contextmanager
from core.binary.reader import BinaryReader

class BiffHandler:
    def __init__(self):
        self.decompressed_bif_cache = {}
        self.bif_headers = {}

    @contextmanager
    def get_stream(self, bif_file_path):
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

    def get_resource_data(self, bif_file_path, resource_index):
        """
        Extracts the raw data for a specific resource index from the BIF file.
        """
        with self.get_stream(bif_file_path) as bif_stream:
            reader = BinaryReader(bif_stream)
            cache_key = str(bif_file_path)
            
            # Use cached header info if available to avoid re-reading/parsing
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
                return None
            
            entry_size = 16
            entry_offset = file_entries_offset + (resource_index * entry_size)
            
            reader.seek(entry_offset + 4)
            resource_offset = reader.read_uint32()
            resource_size = reader.read_uint32()
            
            reader.seek(resource_offset)
            return reader.read(resource_size)
