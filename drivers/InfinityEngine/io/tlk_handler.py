import struct
import os

class TlkHandler:
    """
    Handles the reading of TLK (String Table) files.
    
    Architecture:
    - Parses the Header and Entry Table into memory upon initialization.
    - Keeps the file handle open (or re-opens) to lazy-load string text on demand.
    - This ensures O(1) lookup performance with minimal memory footprint (only offsets are cached).
    """
    
    # TLK V1 Header: Signature(4), Ver(4), LangId(2), Count(4), Offset(4)
    HEADER_FMT = "<4s4sHII" 
    HEADER_SIZE = 18
    
    # TLK Entry: Flags(2), Sound(8), Vol(4), Pitch(4), Offset(4), Length(4)
    ENTRY_FMT = "<H8sIIII"
    ENTRY_SIZE = 26

    def __init__(self, file_path):
        self.file_path = file_path
        self.entry_data = None
        self.string_offset_base = 0
        self.entry_count = 0
        self._load_table()

    def _load_table(self):
        if not self.file_path or not os.path.exists(self.file_path):
            return

        try:
            with open(self.file_path, "rb") as f:
                # 1. Read Header
                header_data = f.read(self.HEADER_SIZE)
                if len(header_data) < self.HEADER_SIZE:
                    return

                sig, ver, lang_id, count, string_data_offset = struct.unpack(self.HEADER_FMT, header_data)
                
                if sig != b'TLK ':
                    return

                self.entry_count = count
                self.string_offset_base = string_data_offset
                
                # 2. Read the entire Entry Table into a bytearray
                # 100,000 strings * 26 bytes = ~2.6 MB. This is cheap for modern RAM.
                f.seek(self.HEADER_SIZE)
                self.entry_data = bytearray(f.read(self.entry_count * self.ENTRY_SIZE))
                
                # The string data usually follows the entry table, but we use absolute offsets provided by the entries.
                # However, standard TLK offsets are absolute from file start.

        except Exception as e:
            print(f"Error loading TLK table {self.file_path}: {e}")
            self.entry_data = None

    def get_string(self, strref):
        if self.entry_data is None:
            return None
            
        if strref < 0 or strref >= self.entry_count:
            return None

        # 1. Extract Offset and Length from the cached table
        # The offset and length are the last two fields in the 26-byte struct (at index 18 and 22)
        start_idx = strref * self.ENTRY_SIZE
        # struct.unpack_from is slower than direct slicing for single fields, but cleaner.
        # Format: <H8sII(II) -> We need the last two II.
        offset = struct.unpack_from("<I", self.entry_data, start_idx + 18)[0]
        length = struct.unpack_from("<I", self.entry_data, start_idx + 22)[0]

        # Handle relative offsets:
        # In many EE games (and some classic mods), if the offset is less than the start 
        # of the string data block, it is relative to that block.
        # (An absolute offset to string data can never be less than the size of the header + table).
        if offset < self.string_offset_base:
            offset += self.string_offset_base

        # 2. Read the text from disk
        with open(self.file_path, "rb") as f:
            f.seek(offset)
            raw_bytes = f.read(length)
            # Decode and strip null terminators
            return raw_bytes.decode('latin-1', errors='replace').split('\x00')[0]