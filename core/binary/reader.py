import struct

class BinaryReader:
    _int_formats = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}
    _signed_int_formats = {1: "<b", 2: "<h", 4: "<i", 8: "<q"}

    def __init__(self, file):
        self.file = file

    def read(self, size):
        return self.file.read(size)

    def read_uint(self, size):
        fmt = self._int_formats.get(size)
        if fmt:
            return struct.unpack(fmt, self.read(size))[0]
        
        # Fallback for non-standard sizes (3, 16, etc.)
        return int.from_bytes(self.read(size), byteorder="little", signed=False)

    def read_int(self, size):
        fmt = self._signed_int_formats.get(size)
        if fmt:
            return struct.unpack(fmt, self.read(size))[0]

        return int.from_bytes(self.read(size), byteorder="little", signed=True)

    def read_uint8(self):
        return self.read_uint(1)

    def read_uint16(self):
        return self.read_uint(2)

    def read_uint32(self):
        return self.read_uint(4)

    def read_int8(self):
        return self.read_int(1)

    def read_int16(self):
        return self.read_int(2)

    def read_int32(self):
        return self.read_int(4)

    def read_string(self, size):
        raw = self.read(size)
        return raw.rstrip(b"\x00").decode("latin-1")

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
