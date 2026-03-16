from csv import reader

'''
Implementation note:
What is the context parameter?
The context parameter represents the data parsed so far within the current structure (section).

In parser.py, when _read_section iterates through fields, it builds a dictionary called section_data. This dictionary is passed as context to the read method of every field type.
This allows a field to be aware of its siblings. It turns the parsing process from a purely linear stream of bytes into a state-aware process where the value of Field A can determine how Field B is read.

Use case (for file versions):
Conditional Logic / Switch
You could implement logic where the interpretation of a field changes based on a "version" or "type" field read earlier.

Scenario: If version is 1, a field is 2 bytes. If version is 2, it is 4 bytes.
Scenario: Calculated / Derived Fields:
    You can create fields that don't read from the file at all but derive their value from existing data.
    You want a field that combines two previous numbers, or formats them.
The context parameter essentially upgrades your parser from handling Static Structures (C-struct style) to Dynamic Structures where the memory layout can change based on the data content itself.
'''

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

    def read(self, reader, field, context=None):
        raise NotImplementedError

    def write(self, writer, value, field):
        raise NotImplementedError

class UInt8(FieldType):
    names = ["byte", "char"]

    def read(self, reader, field, context=None):
        return reader.read_uint8()

    def write(self, writer, value, field):
        writer.write_uint8(value)

class UInt16(FieldType):
    names = ["word"]

    def read(self, reader, field, context=None):
        return reader.read_uint16()

    def write(self, writer, value, field):
        writer.write_uint16(value)

class UInt32(FieldType):
    names = ["dword",]

    def read(self, reader, field, context=None):
        return reader.read_uint32()

    def write(self, writer, value, field):
        writer.write_uint32(value)
        
class Bitmask(FieldType):
    names = ["bitmask"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size")
        value = 0
        
        if size == 4:
            value = reader.read_uint32()
        elif size == 2:
            value = reader.read_uint16()
        elif size == 1:
            value = reader.read_uint8()
        else:
            raise ValueError(f"Unsupported bitmask size: {size}")

        flags = field.attributes.get("flags")
        if flags:
            return {name: bool(value & mask) for mask, name in flags.items()}
        
        return value

    def write(self, writer, value, field): 
        if field.attributes.get("size") == 4:
            writer.write_uint32(value)
        elif field.attributes.get("size") == 2:
            writer.write_uint16(value)
        elif field.attributes.get("size") == 1:
            writer.write_uint8(value)
        else:
            raise ValueError(f"Unsupported bitmask size: {field.attributes.get('size')}")


class ResRef(FieldType):
    names = ["resref"]

    def read(self, reader, field, context=None):
        return reader.read_resref()

    def write(self, writer, value, field):
        writer.write_resref(value)  # you may also want safe writing later

class StrRef(FieldType):
    names = ["strref"]

    def read(self, reader, field, context=None):
        return reader.read_strref()

    def write(self, writer, value, field):
        writer.write_uint32(0 if value is None else value)

class CharArray(FieldType):
    names = ["char_array"]

    def read(self, reader, field, context=None):
        size = field.attributes["size"]
        return reader.read_string(size)

    def write(self, writer, value, field):
        size = field.attributes["size"]
        writer.write_string(value, size)

class Enum(FieldType):
    name = "enum"

    def read(self, reader, field, context=None):
        index = reader.read_uint16()
        values = field.attributes["values"]
        return values[index]

    def write(self, writer, value, field):
        values = field.attributes["values"]
        writer.write_uint16(values.index(value))

class PointerString(FieldType):
    names = ["pointer_string"]

    def read(self, reader, field, context=None):
        if context is None:
            return None

        offset_field_name = field.attributes.get("offset_ref")
        length_field_name = field.attributes.get("length_ref")

        if not offset_field_name or not length_field_name:
            raise ValueError("PointerString requires 'offset_ref' and 'length_ref' attributes.")

        offset = context.get(offset_field_name)
        length = context.get(length_field_name)

        if offset is None or length is None or length <= 1: # Also check for empty/null-terminator only strings
            return None

        # Store current position, seek to the string, read it, and restore the original position
        current_pos = reader.tell()
        try:
            reader.seek(offset)
            value = reader.read_string(length)
        finally:
            reader.seek(current_pos)

        return value

    def write(self, writer, value, field):
        raise NotImplementedError("Writing PointerString is not yet supported.")

class Bitfield(FieldType):
    names = ["bitfield"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", 4)
        value = 0
        
        if size == 4:
            value = reader.read_uint32()
        elif size == 2:
            value = reader.read_uint16()
        elif size == 1:
            value = reader.read_uint8()
        else:
            raise ValueError(f"Unsupported bitfield size: {size}")
            
        bitfields = field.attributes.get("bitfields")
        if not bitfields:
            return value

        result = {}
        for name, params in bitfields.items():
            shift = params.get("shift", 0)
            mask = params.get("mask", 0xFFFFFFFF)
            # Shift first, then mask (logic: (val >> shift) & mask)
            result[name] = (value >> shift) & mask
        
        return result

    def write(self, writer, value, field):
        raise NotImplementedError("Writing Bitfield is not yet supported.")
