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

    def serialize(self, value, field, resource=None):
        return value


def _serialize_lookup(value, field, resource):
    if resource is None or value is None or isinstance(value, (dict, list)):
        return None

    lookup = field.attributes.get("lookup")
    if not lookup:
        return None

    resolver = getattr(resource, "table_resolver", None)
    game = getattr(resource, "game", None)
    if resolver is None or game is None:
        return None

    return resolver.resolve(value, lookup, game=game)

class BaseIntField(FieldType):
    default_size = 4

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", self.default_size)
        return reader.read_uint(size)

    def write(self, writer, value, field):
        size = field.attributes.get("size", self.default_size)
        writer.write_uint(value, size)

    def serialize(self, value, field, resource=None):
        lookup_value = _serialize_lookup(value, field, resource)
        if lookup_value is not None:
            return lookup_value

        display_value_map = field.attributes.get("display_value_map", {})
        if not display_value_map or isinstance(value, (dict, list)):
            return value
        return display_value_map.get(value, value)

class SignedBaseIntField(FieldType):
    default_size = 4

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", self.default_size)
        return reader.read_int(size)

    def write(self, writer, value, field):
        size = field.attributes.get("size", self.default_size)
        writer.write_int(value, size)

    def serialize(self, value, field, resource=None):
        lookup_value = _serialize_lookup(value, field, resource)
        if lookup_value is not None:
            return lookup_value

        display_value_map = field.attributes.get("display_value_map", {})
        if not display_value_map or isinstance(value, (dict, list)):
            return value
        return display_value_map.get(value, value)

class UInt8(BaseIntField):
    names = ["byte", "char"]
    default_size = 1

class UInt16(BaseIntField):
    names = ["word"]
    default_size = 2

class UInt32(BaseIntField):
    names = ["dword"]
    default_size = 4

class Int8(SignedBaseIntField):
    names = ["sbyte", "schar"]
    default_size = 1

class Int16(SignedBaseIntField):
    names = ["sword"]
    default_size = 2

class Int32(SignedBaseIntField):
    names = ["sdword"]
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

class ByteArray(FieldType):
    names = ["byte_array"]

    def _count(self, field):
        count = field.attributes.get("count")
        if count is not None:
            return count

        size = field.attributes.get("size")
        if size is None:
            raise ValueError(f"{field.name} requires a valid 'count' or 'size'")
        return size

    def _labels(self, field):
        labels = field.attributes.get("labels", {}) or {}
        if isinstance(labels, list):
            return {index: label for index, label in enumerate(labels)}
        return labels

    def _values(self, field):
        return field.attributes.get("values", {}) or {}

    def _parse_index(self, key, field):
        if isinstance(key, int):
            return key

        if isinstance(key, str):
            if key.isdigit():
                return int(key)

            reverse_labels = {label: index for index, label in self._labels(field).items()}
            if key in reverse_labels:
                return reverse_labels[key]

        raise ValueError(f"Unsupported key for {field.name}: {key!r}")

    def read(self, reader, field, context=None):
        return [reader.read_uint8() for _ in range(self._count(field))]

    def write(self, writer, value, field):
        count = self._count(field)
        pad_value = field.attributes.get("pad_value", 0)

        if value is None:
            entries = [pad_value] * count
        elif isinstance(value, dict):
            entries = [pad_value] * count
            values = self._values(field)
            reverse_values = {label: index for index, label in values.items()}
            for key, entry in value.items():
                index = self._parse_index(key, field)
                if 0 <= index < count:
                    if isinstance(entry, str) and entry in reverse_values:
                        entries[index] = reverse_values[entry]
                    else:
                        entries[index] = pad_value if entry is None else int(entry)
        else:
            entries = list(value)[:count]
            if len(entries) < count:
                entries.extend([pad_value] * (count - len(entries)))

        for entry in entries:
            writer.write_uint8(pad_value if entry is None else int(entry))

    def measure(self, value, field, context=None):
        return self._count(field)

    def serialize(self, value, field, resource=None):
        if value is None:
            return {}

        labels = self._labels(field)
        values = self._values(field)
        display_empty_values = set(field.attributes.get("display_empty_values", []))
        display_sparse = field.attributes.get("display_sparse", False)
        display_as_mapping = field.attributes.get("display_as_mapping", bool(labels))
        entries = list(value)[:self._count(field)]

        def display_value(entry):
            if entry is None or entry in display_empty_values:
                return None
            return values.get(entry, entry)

        if display_as_mapping:
            serialized = {}
            for index, entry in enumerate(entries):
                rendered = display_value(entry)
                if rendered is None and display_sparse:
                    continue
                serialized[labels.get(index, f"entry_{index}")] = rendered
            return serialized

        return [display_value(entry) for entry in entries]

class WordArray(FieldType):
    names = ["word_array"]

    def _entry_size(self, field):
        return 2

    def _count(self, field):
        count = field.attributes.get("count")
        if count is not None:
            return count

        size = field.attributes.get("size")
        if size is None or size % self._entry_size(field) != 0:
            raise ValueError(f"{field.name} requires a valid 'count' or divisible 'size'")
        return size // self._entry_size(field)

    def _labels(self, field):
        labels = field.attributes.get("labels", {}) or {}
        if isinstance(labels, list):
            return {index: label for index, label in enumerate(labels)}
        return labels

    def _parse_index(self, key, field):
        if isinstance(key, int):
            return key

        if isinstance(key, str):
            if key.isdigit():
                return int(key)
            if key.startswith("slot_") and key[5:].isdigit():
                return int(key[5:])

            reverse_labels = {label: index for index, label in self._labels(field).items()}
            if key in reverse_labels:
                return reverse_labels[key]

        raise ValueError(f"Unsupported key for {field.name}: {key!r}")

    def read(self, reader, field, context=None):
        return [reader.read_uint16() for _ in range(self._count(field))]

    def write(self, writer, value, field):
        count = self._count(field)
        pad_value = field.attributes.get("pad_value", 0)

        if value is None:
            entries = [pad_value] * count
        elif isinstance(value, dict):
            entries = [pad_value] * count
            for key, entry in value.items():
                index = self._parse_index(key, field)
                if 0 <= index < count:
                    entries[index] = pad_value if entry is None else int(entry)
        else:
            entries = list(value)[:count]
            if len(entries) < count:
                entries.extend([pad_value] * (count - len(entries)))

        for entry in entries:
            writer.write_uint16(pad_value if entry is None else int(entry))

    def measure(self, value, field, context=None):
        return self._count(field) * self._entry_size(field)

    def _resolve_entry(self, entry, field, resource):
        if resource is None or not isinstance(entry, int):
            return entry

        section_name = field.attributes.get("resolve_indices_from_section")
        target_field = field.attributes.get("resolve_indices_to_field")
        if not section_name or not target_field:
            return entry

        section_entries = resource.get_section(section_name) or []
        if 0 <= entry < len(section_entries):
            resolved = section_entries[entry].get(target_field, entry)
            return resolved

        return entry

    def serialize(self, value, field, resource=None):
        if value is None:
            return {}

        labels = self._labels(field)
        empty_values = set(field.attributes.get("display_empty_values", []))
        display_sparse = field.attributes.get("display_sparse", False)
        display_as_mapping = field.attributes.get("display_as_mapping", bool(labels))
        entries = list(value)[:self._count(field)]

        if display_as_mapping:
            serialized = {}
            for index, entry in enumerate(entries):
                key = labels.get(index, f"slot_{index}")
                if entry is None or entry in empty_values:
                    if display_sparse:
                        continue
                    serialized[key] = None
                else:
                    serialized[key] = self._resolve_entry(entry, field, resource)
            return serialized

        return [None if entry in empty_values else entry for entry in entries]

class Enum(BaseIntField):
    names = ["enum"]
    default_size = 2

    def read(self, reader, field, context=None):
        index = super().read(reader, field, context)
        values = field.attributes["values"]

        if isinstance(values, dict):
            return values.get(index, index)

        if index >= len(values):
            # Preserve unknown values rather than hiding them.
            return index

        return values[index]

    def write(self, writer, value, field):
        values = field.attributes["values"]

        if isinstance(value, int):
            index = value
        elif isinstance(values, dict):
            index = next((key for key, label in values.items() if label == value), 0)
        else:
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
