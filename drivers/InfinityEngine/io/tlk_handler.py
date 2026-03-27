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
        self.file_size = 0
        self.offset_mode = "absolute"
        self._load_table()

    def _load_table(self):
        if not self.file_path or not os.path.exists(self.file_path):
            return

        try:
            with open(self.file_path, "rb") as f:
                self.file_size = os.path.getsize(self.file_path)
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
                self.offset_mode = self._detect_offset_mode()

        except Exception as e:
            print(f"Error loading TLK table {self.file_path}: {e}")
            self.entry_data = None

    def _detect_offset_mode(self):
        if self.entry_data is None or self.file_size <= 0:
            return "absolute"

        absolute_valid = 0
        relative_valid = 0
        samples = 0
        sample_limit = min(self.entry_count, 2048)

        for strref in range(sample_limit):
            start_idx = strref * self.ENTRY_SIZE
            offset = struct.unpack_from("<I", self.entry_data, start_idx + 18)[0]
            length = struct.unpack_from("<I", self.entry_data, start_idx + 22)[0]

            if length <= 0:
                continue

            samples += 1

            if offset >= self.string_offset_base and offset + length <= self.file_size:
                absolute_valid += 1

            if self.string_offset_base + offset + length <= self.file_size:
                relative_valid += 1

        if samples == 0:
            return "absolute"

        return "relative" if relative_valid > absolute_valid else "absolute"

    def _resolve_offset(self, offset):
        if self.offset_mode == "relative":
            return self.string_offset_base + offset
        return offset

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
        offset = self._resolve_offset(offset)

        # 2. Read the text from disk
        with open(self.file_path, "rb") as f:
            f.seek(offset)
            raw_bytes = f.read(length)
            # Decode and strip null terminators
            return raw_bytes.decode('latin-1', errors='replace').split('\x00')[0]
