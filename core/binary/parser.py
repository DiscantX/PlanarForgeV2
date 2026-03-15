from core.resource import Resource


class BinaryParser:

    def __init__(self, schema):
        self.schema = schema

    def read(self, reader, name=None, source=None):

        resource = Resource(self.schema, name=name, source=source)
        resource.sections = {}

        filesize = reader.size()

        # -----------------------------
        # Parse header first
        # -----------------------------

        header = self.schema.get_section("header")

        if header:
            header_entries = [self._read_section(reader, header, resource)]
            resource.sections["header"] = header_entries

        # -----------------------------
        # Parse remaining sections
        # -----------------------------

        for section in self.schema.sections:

            if section.name == "header":
                continue

            # Move to section offset if defined
            if section.offset_field:
                offset = resource.values.get(section.offset_field)

                if offset is None:
                    raise ValueError(
                        f"Section '{section.name}' references missing offset field '{section.offset_field}'"
                    )

                reader.seek(offset)

            # Determine entry count
            count = 1
            if section.count_field:
                count = resource.values.get(section.count_field, 0)

            entries = []

            for _ in range(count):

                # Safety guard: prevent reading past EOF
                if reader.tell() >= filesize:
                    break

                entry = self._read_section(reader, section, resource)
                entries.append(entry)

            resource.sections[section.name] = entries

        return resource


    def _read_section(self, reader, section, resource):

        section_data = {}

        for field in section.fields:

            value = field.type.read(reader, field)

            section_data[field.name] = value
            resource.values[field.name] = value

        return section_data