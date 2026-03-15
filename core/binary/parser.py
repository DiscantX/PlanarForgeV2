from core.resource import Resource

class BinaryParser:
    def __init__(self, schema):
        self.schema = schema

    def read(self, reader, name=None, source=None):
        resource = Resource(self.schema, name=name, source=source)
        resource.sections = {}

        # Iterate over all sections defined in the schema
        for section in self.schema.sections:
            # Determine if the section is repeating
            # Convention: if a field exists like count_of_<section>, repeat that many times
            count_field_name = f"count_of_{section.name}"
            repeat_count = resource.values.get(count_field_name, 1)
            if repeat_count is None:
                repeat_count = 1

            section_values = []
            for _ in range(repeat_count):
                section_values.append(self._read_section(reader, section, resource))

            resource.sections[section.name] = section_values

        return resource

    def _read_section(self, reader, section, resource):
        section_data = {}
        for field in section:
            value = field.type.read(reader, field)
            section_data[field.name] = value
            resource.values[field.name] = value  # populate resource values immediately

        return section_data