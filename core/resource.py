from core.change_event import ChangeEvent


class Resource:
    '''
    Resource instance belonging to a schema. Stores field values organized by sections
    and notifies listeners when changes occur.

    A resource may contain multiple sections (header, extended_header, etc.).
    Repeating sections are stored as lists.

    Args:
        schema (Schema): The schema to which this resource belongs.
        name (str, optional): The resource name.
        source (str, optional): The source file.
    '''

class Resource:
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

class Section:
    """
    Represents a section of a resource (header, extended_header, feature_block, etc.).
    Stores the fields for that section and their values.
    """
    def __init__(self, name, fields, count=1):
        self.name = name
        self.fields = fields
        self.count = count
        self.data = []  # List of dicts, each dict: field_name -> value

    def __repr__(self):
        return f"<Section {self.name} ({self.count} entries)>"
