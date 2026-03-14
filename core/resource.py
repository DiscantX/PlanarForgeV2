from core.change_event import ChangeEvent

class Resource:
    '''
    Resource class that represents an instance belonging to a schema type. It holds the values for each field and notifies listeners when changes occur.
    This is the core data structure that will hold resource data from the original files, as well as editor-sprecific data. 
    It holds a reference to the schema it belongs to, and a dictionary of field values. It also has a modified flag to track changes, and a listener system for notifying when fields are updated.
    
    Args:
        schema (Schema): The schema to which this resource belongs.
        name (str, optional): The name of the resource. Defaults to None.
        source (str, optional): The source file or identifier for this resource. Defaults to None
    Returns:
        Resource: An instance of the Resource class.
    Raises:
        KeyError: If a field name is set that does not exist in the schema.
    '''
    def __init__(self, schema, name=None, source=None):
        self.schema = schema
        self.name = name
        self.source = source

        self.modified = False

        self._listeners = []
        self.values = {}
        # Initialize default values for fields based on the schema. Use if you want all fields set to their default values,
        # but for now we'll leave them unset until explicitly set to avoid confusion between "unset" and "set to default".
        
        # for field in schema.fields:
        #     self.values[field.name] = field.default

    def get(self, field_name, default=None):
        '''Gets the value of a field by name.
        Args:
            field_name (str): The name of the field to retrieve.
        Returns:
            The value of the field, or None if it has not been set.
        '''
        return self.values.get(field_name, default)

    def set(self, field_name, value):
        '''
        Sets the value of a field and marks the resource as modified. Notifies listeners of the change.
        Args:
            field_name (str): The name of the field to set.
            value: The new value for the field.
        Raises:
            KeyError: If the field name does not exist in the schema.
        '''
        if field_name not in self.schema.field_map:
            raise KeyError(f"{field_name} not in schema")

        old_value = self.values.get(field_name)
        if old_value == value:
            return

        self.values[field_name] = value
        self.modified = True

        self._notify(field_name, old_value, value)

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.set(key, value)

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

        for listener in list(self._listeners): #list() avoids issues if listeners remove themselves.
            listener(event)

    def __repr__(self):
        return f"<Resource {self.name} ({self.schema.name})>"