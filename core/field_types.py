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

    def measure(self, value, field, context=None):
        return field.attributes.get("size", 0)

class BaseIntField(FieldType):
    default_size = 4

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", self.default_size)
        return reader.read_uint(size)

    def write(self, writer, value, field):
        size = field.attributes.get("size", self.default_size)
        writer.write_uint(value, size)

class UInt8(BaseIntField):
    names = ["byte", "char"]
    default_size = 1

class UInt16(BaseIntField):
    names = ["word"]
    default_size = 2

class UInt32(BaseIntField):
    names = ["dword"]
    default_size = 4
    
class Bitfield(BaseIntField):
    names = ["bitfield"]
    default_size = 4

    def read(self, reader, field, context=None):
        value = super().read(reader, field, context)
            
        bitfields = field.attributes.get("bitfields")
        if not bitfields:
            return value

        result = {}
        known_mask = 0
        for name, params in bitfields.items():
            shift = params.get("shift", 0)
            mask = params.get("mask", 0xFFFFFFFF)
            # Add this field's mask to the total known mask
            known_mask |= (mask << shift)
            # Extract the value for this field
            result[name] = (value >> shift) & mask
        
        # Preserve any bits not covered by the known bitfields
        unknown_bits = value & ~known_mask
        if unknown_bits:
            result["_unknown"] = unknown_bits
            
        return result

    def write(self, writer, value, field):
        bitfields = field.attributes.get("bitfields")
        if bitfields and isinstance(value, dict):
            int_value = 0
            for name, params in bitfields.items():
                shift = params.get("shift", 0)
                mask = params.get("mask", 0xFFFFFFFF)
                val = value.get(name, 0)
                int_value |= (val & mask) << shift
            
            # Restore unknown bits if present
            int_value |= value.get("_unknown", 0)
            
            super().write(writer, int_value, field)
        else:
            super().write(writer, value, field)
        
class Bitmask(BaseIntField):
    names = ["bitmask"]
    default_size = 4

    def read(self, reader, field, context=None):
        value = super().read(reader, field, context)

        flags = field.attributes.get("flags")
        if flags:
            result = {name: bool(value & mask) for mask, name in flags.items()}
            
            # Calculate mask of all known flags
            known_mask = 0
            for mask in flags:
                known_mask |= mask
            
            # Preserve unknown bits
            unknown_bits = value & ~known_mask
            if unknown_bits:
                result["_unknown"] = unknown_bits
                
            return result
        
        return value

    def write(self, writer, value, field):
        flags = field.attributes.get("flags")
        if flags and isinstance(value, dict):
            int_value = 0
            for mask, name in flags.items():
                if value.get(name):
                    int_value |= mask
            
            # Restore unknown bits if present
            int_value |= value.get("_unknown", 0)
            
            super().write(writer, int_value, field)
        else:
            super().write(writer, value, field)

class CharArray(FieldType):
    names = ["char_array"]

    def read(self, reader, field, context=None):
        size_ref = field.attributes.get("size_ref")
        if size_ref and context:
            size = context.get(size_ref)
            if size is None:
                raise ValueError(f"CharArray field '{field.name}' references missing size field '{size_ref}'")
        else:
            size = field.attributes.get("size")
            if size is None:
                raise ValueError(f"CharArray field '{field.name}' requires a 'size' or 'size_ref' attribute.")
        return reader.read_string(size)

    def write(self, writer, value, field):
        size = field.attributes["size"]
        writer.write_string(value, size)

class Bytes(FieldType):
    names = ["bytes"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size")
        if size is None:
             raise ValueError(f"Bytes field '{field.name}' requires a 'size' attribute.")
        return reader.read(size)

    def write(self, writer, value, field):
        size = field.attributes.get("size")
        if size is None:
             raise ValueError(f"Bytes field '{field.name}' requires a 'size' attribute.")
        
        if value is None:
            value = b'\x00' * size
        writer.write(value)

class Enum(BaseIntField):
    names = ["enum"]
    default_size = 2

    def read(self, reader, field, context=None):
        index = super().read(reader, field, context)
        values = field.attributes["values"]
        if index >= len(values):
            # Gracefully handle corrupted data or invalid indices
            return None
        return values[index]

    def write(self, writer, value, field):
        values = field.attributes["values"]
        try:
            index = values.index(value)
        except ValueError:
            index = 0 # Default to first value if the provided one is invalid
        super().write(writer, index, field)

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
        # PointerString is a virtual field that reads from an offset.
        # Writing does not happen in-line with the struct; string data management is handled externally.
        pass
