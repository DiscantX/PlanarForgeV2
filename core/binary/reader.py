import struct

class BinaryReader:
    _int_formats = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}

    def __init__(self, file):
        self.file = file

    def read(self, size):
        return self.file.read(size)

    def read_uint(self, size):
        fmt = self._int_formats.get(size)
        if not fmt:
            raise ValueError(f"Unsupported integer size: {size}")
        return struct.unpack(fmt, self.read(size))[0]

    def read_uint8(self):
        return self.read_uint(1)

    def read_uint16(self):
        return self.read_uint(2)

    def read_uint32(self):
        return self.read_uint(4)

    def read_string(self, size):
        raw = self.read(size)
        return raw.rstrip(b"\x00").decode("latin-1")

    def read_resref(self):
        raw = self.read(8)
        stripped = raw.rstrip(b"\x00")
        
        return stripped.decode("latin-1")

    def read_strref(self):
        value = self.read_uint32()
        # 0 means no string
        return None if value == 0 else value

    def tell(self):
        return self.file.tell()

    def seek(self, offset):
        self.file.seek(offset)
        
    def size(self):
        current = self.file.tell()
        self.file.seek(0, 2)  # seek to end
        size = self.file.tell()
        self.file.seek(current)
        return size
