class FieldTypes:
    _types = {}

    @classmethod
    def register(cls, field_type_cls):
        cls._types[field_type_cls.name] = field_type_cls()

    @classmethod
    def get(cls, name):
        return cls._types[name]

    @classmethod
    def __getitem__(cls, name):
        return cls._types[name]

class FieldType:
    name = None

    def __init_subclass__(cls):
        super().__init_subclass__()

        if cls.name:
            FieldTypes.register(cls)

    def read(self, reader, field):
        raise NotImplementedError

    def write(self, writer, value, field):
        raise NotImplementedError
    
class UInt32(FieldType):
    name = "uint32"

    def read(self, reader, field):
        return reader.read_uint32()

    def write(self, writer, value, field):
        writer.write_uint32(value)
        
class UInt16(FieldType):
    name = "uint16"

    def read(self, reader, field):
        return reader.read_uint16()

    def write(self, writer, value, field):
        writer.write_uint16(value)
        
class ResRef(FieldType):
    name = "resref"

    def read(self, reader, field):
        return reader.read_resref()

    def write(self, writer, value, field):
        writer.write_resref(value)
        
class StrRef(FieldType):
    name = "strref"

    def read(self, reader, field):
        return reader.read_strref()

    def write(self, writer, value, field):
        writer.write_strref(value)
        
class Enum(FieldType):
    name = "enum"

    def read(self, reader, field):
        index = reader.read_uint16()
        values = field.attributes["values"]
        return values[index]

    def write(self, writer, value, field):
        values = field.attributes["values"]
        writer.write_uint16(values.index(value))
