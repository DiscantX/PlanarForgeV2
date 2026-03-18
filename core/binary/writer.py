import struct

class BinaryWriter:
    _int_formats = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}

    def __init__(self, file):
        self.file = file

    def write(self, data):
        self.file.write(data)

    def write_uint(self, value, size):
        if value is None:
            value = 0
        fmt = self._int_formats.get(size)
        if fmt:
            self.write(struct.pack(fmt, value))
        else:
            # Fallback for non-standard sizes
            self.write(value.to_bytes(size, byteorder="little", signed=False))

    def write_uint8(self, value):
        self.write_uint(value, 1)

    def write_uint16(self, value):
        self.write_uint(value, 2)

    def write_uint32(self, value):
        self.write_uint(value, 4)

    def write_string(self, value, size):
        if value is None:
            value = ""
        encoded = value.encode("latin-1", errors="replace")
        if len(encoded) > size:
            encoded = encoded[:size]
        else:
            encoded = encoded.ljust(size, b"\x00")
        self.write(encoded)