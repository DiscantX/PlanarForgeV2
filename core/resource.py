from core.change_event import ChangeEvent


class Resource:
    """
    Resource instance belonging to a schema. Stores field values organized by sections
    and notifies listeners when changes occur.

    A resource may contain multiple sections (header, extended_header, etc.).
    Repeating sections are stored as lists.
    
    Args:
        schema (Schema): The schema to which this resource belongs.
        name (str, optional): The resource name.
        source (str, optional): The source file.
    """
    def __init__(self, schema, name=None, source=None):
        self.schema = schema
        self.name = name
        self.source = source
        self.modified = False
        self._listeners = []
        self.values = {}
        self.sections = {}  # header, extended_header, feature_blocks

    # ------------------------------
    # Section Management
    # ------------------------------

    def set_section(self, section_name, data):
        """
        Sets an entire section.

        data may be:
            dict (single section)
            list[dict] (repeating section)
        """
        self.sections[section_name] = data

    def get_section(self, section_name):
        return self.sections.get(section_name)

    # ------------------------------
    # Field Access
    # ------------------------------

    def get(self, field_name, default=None):
        """
        Retrieve a field value by searching sections.
        """
        for section in self.sections.values():

            if isinstance(section, dict):
                if field_name in section:
                    return section[field_name]

            else:  # list of dicts
                for entry in section:
                    if field_name in entry:
                        return entry[field_name]

        return default

    def set(self, field_name, value):
        """
        Sets a field value within its section.

        Raises:
            KeyError if field does not exist.
        """

        field = self.schema.get_field(field_name)
        if not field:
            raise KeyError(f"{field_name} not in schema")

        # find the field in sections
        for section_name, section in self.sections.items():

            if isinstance(section, dict):
                if field_name in section:
                    old_value = section[field_name]
                    if old_value == value:
                        return

                    section[field_name] = value
                    self.modified = True
                    self._notify(field_name, old_value, value)
                    return

            else:
                for entry in section:
                    if field_name in entry:
                        old_value = entry[field_name]
                        if old_value == value:
                            return

                        entry[field_name] = value
                        self.modified = True
                        self._notify(field_name, old_value, value)
                        return

        raise KeyError(f"{field_name} not found in resource sections")

    # ------------------------------
    # Python Accessors
    # ------------------------------

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        self.set(key, value)

    # ------------------------------
    # Listener System
    # ------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def remove_listener(self, callback):
        self._listeners.remove(callback)

    def _notify(self, field_name, old_value, new_value):

        field = self.schema.get_field(field_name)

        event = ChangeEvent(
            resource=self,
            field=field,
            old_value=old_value,
            new_value=new_value
        )

        for listener in list(self._listeners):
            listener(event)

    # ------------------------------
    # Debug
    # ------------------------------

    def __repr__(self):
        return f"<Resource {self.name} ({self.schema.name})>"

    # ------------------------------
    # Serialization
    # ------------------------------

    def to_dict(self):
        """
        Serializes the resource using schema field types for readable JSON output.
        """
        serialized = {}

        for section_name, section_data in self.sections.items():
            section = self.schema.get_section(section_name)
            serialized[section_name] = self._serialize_section(section_data, section)

        return serialized

    def _serialize_section(self, value, section=None):
        if isinstance(value, list):
            return [self._serialize_section(entry, section) for entry in value]

        if isinstance(value, dict):
            serialized = {}
            for key, item in value.items():
                field = section.get_field(key) if section else None
                serialized[key] = self._serialize_value(item, field=field)
            return serialized

        return self._serialize_value(value)

    def _serialize_value(self, value, field=None):
        """
        Recursively converts a value to a plain Python type for serialization.
        """
        field_type_name = getattr(field, "type_name", None)

        if field is not None and getattr(field, "type", None) is not None:
            custom_serialized = field.type.serialize(value, field)
            if custom_serialized is not value:
                return self._serialize_value(custom_serialized)

        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]

        if field_type_name == "resref":
            return self._serialize_resref(value)

        if isinstance(value, bytes):
            return self._serialize_bytes(value)

        if isinstance(value, str):
            return value.rstrip('\x00')

        if not isinstance(value, (int, float, bool, type(None))):
            return str(value).rstrip('\x00')

        return value

    def _serialize_bytes(self, value):
        if not value:
            return ""

        return f"0x{value.hex()}"

    def _serialize_resref(self, value):
        if value is None:
            return None

        if isinstance(value, bytes):
            raw_bytes = value
        elif isinstance(value, str):
            raw_bytes = str.__str__(value).encode("latin-1", errors="replace")
        else:
            raw_bytes = str(value).encode("latin-1", errors="replace")

        text_bytes = raw_bytes.split(b"\x00", 1)[0]
        if not text_bytes:
            return None

        display = text_bytes.decode("latin-1", errors="ignore")
        if display and self._is_printable_text(display):
            return display

        return f"<non-text resref:{raw_bytes.hex()}>"

    @staticmethod
    def _is_printable_text(value):
        return all(32 <= ord(char) <= 126 for char in value)
