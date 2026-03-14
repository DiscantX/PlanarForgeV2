class ChangeEvent:
    """
    Represents a change to a field on a Resource.
    """

    def __init__(
        self,
        resource,
        field,
        old_value,
        new_value,
        source=None,
        batch_id=None,
        timestamp=None,
    ):
        self.resource = resource
        self.field = field
        self.old_value = old_value
        self.new_value = new_value

        # Optional metadata
        self.source = source
        self.batch_id = batch_id
        self.timestamp = timestamp

    @property
    def field_name(self):
        """
        Convenience accessor.
        """
        return self.field.name if self.field else None

    def is_noop(self):
        """
        Returns True if the change didn't actually modify the value.
        """
        return self.old_value == self.new_value

    def __repr__(self):
        return (
            f"<ChangeEvent "
            f"resource={self.resource!r} "
            f"field={self.field_name} "
            f"{self.old_value!r} -> {self.new_value!r}>"
        )