"""
Infinity Engine specific field types.
Automatically registered with core.field_types.FieldTypes when imported.
"""
from core.field_types import FieldType

class ResRef(FieldType):
    names = ["resref"]

    def read(self, reader, field, context=None):
        # Formerly BinaryReader.read_resref
        raw = reader.read(8)
        stripped = raw.rstrip(b"\x00")
        val = stripped.decode("latin-1")
        return ResRefString(val)

    def write(self, writer, value, field):
        # Formerly BinaryWriter.write_resref
        writer.write_string(value, 8)

class ResRefString(str):
    """
    A string wrapper for ResRefs that preserves raw binary data (decoded as latin-1)
    but sanitizes the string representation for display.
    """
    def __str__(self):
        return self.split('\x00')[0]

    def __repr__(self):
        return repr(self.__str__())

class StrRef(FieldType):
    names = ["strref"]

    def read(self, reader, field, context=None):
        # Formerly BinaryReader.read_strref
        value = reader.read_uint32()
        return None if value == 0 else value

    def write(self, writer, value, field):
        writer.write_uint32(0 if value is None else value)
