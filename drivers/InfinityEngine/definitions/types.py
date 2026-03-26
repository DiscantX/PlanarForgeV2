"""
Infinity Engine specific field types.
Automatically registered with core.field_types.FieldTypes when imported.
"""
from core.field_types import FieldType

class ResRef(FieldType):
    names = ["resref"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", 8)
        raw = reader.read(size)

        # Some imported schemas use resref semantics for repeated blocks.
        # In that case preserve the raw bytes so the stream position remains correct.
        if size != 8:
            return raw

        stripped = raw.rstrip(b"\x00")
        val = stripped.decode("latin-1")
        return ResRefString(val)

    def write(self, writer, value, field):
        size = field.attributes.get("size", 8)
        if size != 8:
            if value is None:
                value = b"\x00" * size
            elif isinstance(value, str):
                value = value.encode("latin-1")
            writer.write(bytes(value)[:size].ljust(size, b"\x00"))
            return

        writer.write_string(value, 8)

class ResRefString(str):
    """
    A string wrapper for ResRefs that preserves raw binary data (decoded as latin-1)
    but sanitizes the string representation for display.
    """
    def _display_value(self):
        return str.__str__(self).split('\x00', 1)[0]

    def __str__(self):
        return self._display_value()

    def __repr__(self):
        return repr(self._display_value())

    def __eq__(self, other):
        """
        Allows comparison with standard strings ignoring null padding.
        Example: ResRefString("SW1H01\x00\x00") == "SW1H01" -> True
        """
        if isinstance(other, str):
            return self._display_value() == other.split('\x00', 1)[0]
        return super().__eq__(other)
    
    def __hash__(self):
        return hash(self._display_value())

class StrRef(FieldType):
    names = ["strref"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", 4)
        if size != 4:
            # Preserve raw repeated/padded data when the schema declares a
            # non-standard width instead of desynchronizing the remaining fields.
            return reader.read(size)

        value = reader.read_uint32()
        return None if value == 0 else value

    def write(self, writer, value, field):
        size = field.attributes.get("size", 4)
        if size != 4:
            if value is None:
                value = b"\x00" * size
            elif isinstance(value, int):
                value = value.to_bytes(size, byteorder="little", signed=False)
            writer.write(bytes(value)[:size].ljust(size, b"\x00"))
            return

        writer.write_uint32(0 if value is None else value)

class EffectExtraData(FieldType):
    names = ["effect_extra_data"]

    def read(self, reader, field, context=None):
        size = field.attributes.get("size", 0)
        eff_structure_version = 0 if context is None else context.get("eff_structure_version", 0)
        if eff_structure_version:
            return reader.read(size)
        return b""

    def write(self, writer, value, field):
        if value:
            writer.write(value)

    def measure(self, value, field, context=None):
        return len(value) if value else 0

class Iwd2CreGroup(FieldType):
    names = ["iwd2_cre_group"]

    def _entry_size(self, field):
        return sum(child.type.measure(None, child) for child in field.children)

    def read(self, reader, field, context=None):
        if context is None:
            raise ValueError(f"{field.name} requires a parsing context")

        count_ref = field.attributes.get("count_ref")
        if not count_ref:
            raise ValueError(f"{field.name} requires a 'count_ref' attribute")

        count = context.get(count_ref, 0) or 0
        entries = []

        for _ in range(count):
            entry = {}
            entry_context = {}
            for child in field.children:
                value = child.type.read(reader, child, entry_context)
                entry[child.name] = value
                entry_context[child.name] = value
            entries.append(entry)

        total_slots = reader.read_uint32()
        free_slots = reader.read_uint32()

        return {
            "entries": entries,
            "total_slots": total_slots,
            "free_slots": free_slots,
        }

    def write(self, writer, value, field):
        value = value or {}
        entries = value.get("entries", [])

        for entry in entries:
            for child in field.children:
                child.type.write(writer, entry.get(child.name), child)

        writer.write_uint32(value.get("total_slots", 0))
        writer.write_uint32(value.get("free_slots", 0))

    def measure(self, value, field, context=None):
        value = value or {}
        entries = value.get("entries", [])
        return (len(entries) * self._entry_size(field)) + 8
