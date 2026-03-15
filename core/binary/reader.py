import struct

class BinaryReader:
    def __init__(self, file):
        self.file = file

    def read(self, size):
        return self.file.read(size)

    def read_uint8(self):
        return struct.unpack("<B", self.read(1))[0]

    def read_uint16(self):
        return struct.unpack("<H", self.read(2))[0]

    def read_uint32(self):
        return struct.unpack("<I", self.read(4))[0]

    def read_string(self, size):
        raw = self.read(size)
        return raw.rstrip(b"\x00").decode("ascii")

    def read_resref(self):
        raw = self.read(8)
        stripped = raw.rstrip(b"\x00")

        # Empty or non-printable bytes → None
        if not stripped or any(b < 32 or b > 126 for b in stripped):
            return None

        return stripped.decode("ascii")

    def read_strref(self):
        value = self.read_uint32()
        # 0 means no string
        return None if value == 0 else value

    def tell(self):
        return self.file.tell()

    def seek(self, offset):
        self.file.seek(offset)

