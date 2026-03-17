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
            current_offset = reader.tell()
            try:
                # Pass the currently parsed section data for context-aware fields
                value = field.type.read(reader, field, section_data)
            except Exception as e:
                # Re-raise with more context for better error reporting
                error_message = f"Parsing field '{field.name}' at offset {hex(current_offset)} failed: {e}"
                # Create a new exception of the same type to preserve the original error type
                raise type(e)(error_message) from e

            section_data[field.name] = value
            resource.values[field.name] = value

        return section_data

    def write(self, writer, resource):
        """
        Writes a Resource object back to a binary stream.
        Automatically recalculates offsets and counts for sections.
        """
        
        # 1. Calculate Offsets & Counts
        # We simulate the write position to determine where dynamic sections will land.
        
        current_offset = 0
        
        # Header is always first
        header_section = self.schema.get_section("header")
        if header_section:
            # Header size is fixed based on its fields
            header_size = sum(f.attributes.get("size", 0) for f in header_section.fields) 
            # Note: This simple sum assumes fixed-size fields in header (standard for IE games)
            current_offset += header_size

        # Calculate positions for remaining sections
        for section in self.schema.sections:
            if section.name == "header":
                continue

            entries = resource.sections.get(section.name, [])
            count = len(entries)
            
            # Update the resource's values for count/offset fields
            if section.count_field:
                resource.values[section.count_field] = count
            
            if section.offset_field:
                if count > 0:
                    resource.values[section.offset_field] = current_offset
                else:
                    # If section is empty, preserve the original offset if it exists.
                    # This helps maintain binary fidelity with files that have 'stale' pointers.
                    if resource.values.get(section.offset_field) is None:
                        resource.values[section.offset_field] = 0

            # Calculate size of this section to advance offset
            # Note: This assumes fixed-size entries. If entries have dynamic size (rare in IE structs),
            # we would need to iterate entries.
            if count > 0:
                # access the first entry to get the structure if needed, or just sum field sizes
                entry_size = sum(f.attributes.get("size", 0) for f in section.fields)
                current_offset += (entry_size * count)

        # 2. Write Data
        for section in self.schema.sections:
            entries = resource.sections.get(section.name, [])
            
            # If it's the header, it's a list of 1 dict, but usually stored as just the dict in some parsers.
            # Our parser stored it as a list of 1.
            
            for entry in entries:
                for field in section.fields:
                    val = entry.get(field.name)
                    # If value is missing, check resource.values (for offsets/counts we just updated)
                    if val is None:
                        val = resource.values.get(field.name)
                    
                    field.type.write(writer, val, field)