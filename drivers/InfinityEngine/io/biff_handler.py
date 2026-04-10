"""
Handles low-level access to BIFF files, including signature detection,
decompression of BIFC/BIF variants, and stream caching.
"""
import io
import struct
import zlib
from contextlib import contextmanager
from core.binary.reader import BinaryReader

class BiffHandler:
    FILE_ENTRY_SIZE = 16
    TILESET_ENTRY_SIZE = 20
    TIS_HEADER_SIZE = 24
    TIS_TILE_DIMENSION = 64

    def __init__(self):
        self.decompressed_bif_cache = {}
        self.bif_headers = {}

    def _get_layout(self, reader, cache_key):
        cached_header = self.bif_headers.get(cache_key)
        if cached_header:
            return cached_header

        reader.seek(0x08)
        file_count = reader.read_uint32()
        tileset_count = reader.read_uint32()
        file_entries_offset = reader.read_uint32()
        tileset_entries_offset = file_entries_offset + (file_count * self.FILE_ENTRY_SIZE)

        layout = (file_count, tileset_count, file_entries_offset, tileset_entries_offset)
        self.bif_headers[cache_key] = layout
        return layout

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

    def get_resource_data(self, bif_file_path, resource_index, tileset_index=None):
        """
        Extracts raw resource bytes from a BIFF container.

        If ``tileset_index`` is provided, data is read from the BIFF tileset-entry
        table and wrapped with a synthetic TIS header for schema-based parsing.
        """
        with self.get_stream(bif_file_path) as bif_stream:
            reader = BinaryReader(bif_stream)
            cache_key = str(bif_file_path)

            file_count, tileset_count, file_entries_offset, tileset_entries_offset = self._get_layout(reader, cache_key)

            if tileset_index is not None:
                if tileset_index < 0 or tileset_index >= tileset_count:
                    return None

                entry_offset = tileset_entries_offset + (tileset_index * self.TILESET_ENTRY_SIZE)
                reader.seek(entry_offset + 4)
                resource_offset = reader.read_uint32()
                tile_count = reader.read_uint32()
                tile_size = reader.read_uint32()

                if tile_count <= 0 or tile_size <= 0:
                    return None

                resource_size = tile_count * tile_size
                reader.seek(resource_offset)
                tile_payload = reader.read(resource_size)
                if len(tile_payload) != resource_size:
                    return None

                # BIFF tileset entries contain only tile payload. Build a standard
                # TIS header so the generic schema parser can process it.
                tis_header = struct.pack(
                    "<4s4sIIII",
                    b"TIS ",
                    b"V1  ",
                    tile_count,
                    tile_size,
                    self.TIS_HEADER_SIZE,
                    self.TIS_TILE_DIMENSION,
                )
                return tis_header + tile_payload

            if resource_index < 0 or resource_index >= file_count:
                return None

            entry_offset = file_entries_offset + (resource_index * self.FILE_ENTRY_SIZE)
            reader.seek(entry_offset + 4)
            resource_offset = reader.read_uint32()
            resource_size = reader.read_uint32()

            reader.seek(resource_offset)
            return reader.read(resource_size)
