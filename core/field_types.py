class FieldTypes:
    _types = {}

    @classmethod
    def register(cls, field_type_cls):
        instance = field_type_cls()

        for name in field_type_cls.names:
            cls._types[name] = instance

    @classmethod
    def get(cls, name):
        if name not in cls._types:
            raise KeyError(f"Unknown field type: {name}")
        return cls._types[name]

    @classmethod
    def __getitem__(cls, name):
        return cls.get(name)
    

class FieldType:
    names = []

    def __init_subclass__(cls):
        super().__init_subclass__()

        if cls.names:
            FieldTypes.register(cls)

    def read(self, reader, field):
        raise NotImplementedError

    def write(self, writer, value, field):
        raise NotImplementedError

class UInt8(FieldType):
    names = ["byte", "char"]

    def read(self, reader, field):
        return reader.read_uint8()

    def write(self, writer, value, field):
        writer.write_uint8(value)

class UInt16(FieldType):
    names = ["word"]

    def read(self, reader, field):
        return reader.read_uint16()

    def write(self, writer, value, field):
        writer.write_uint16(value)

class UInt32(FieldType):
    names = ["dword", "bitmask"]

    def read(self, reader, field):
        return reader.read_uint32()

    def write(self, writer, value, field):
        writer.write_uint32(value)

class ResRef(FieldType):
    names = ["resref"]

    def read(self, reader, field):
        return reader.read_resref()

    def write(self, writer, value, field):
        writer.write_resref(value)  # you may also want safe writing later

class StrRef(FieldType):
    names = ["strref"]

    def read(self, reader, field):
        return reader.read_strref()

    def write(self, writer, value, field):
        writer.write_uint32(0 if value is None else value)

class CharArray(FieldType):
    names = ["char_array"]

    def read(self, reader, field):
        size = field.attributes["size"]
        return reader.read_string(size)

    def write(self, writer, value, field):
        size = field.attributes["size"]
        writer.write_string(value, size)

class Enum(FieldType):
    name = "enum"

    def read(self, reader, field):
        index = reader.read_uint16()
        values = field.attributes["values"]
        return values[index]

    def write(self, writer, value, field):
        values = field.attributes["values"]
        writer.write_uint16(values.index(value))
