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

        header_section = self.schema.get_section("header")

        if header_section:
            # The header is a single entry. Read it and populate resource.values from it.
            header_data = self._read_section(reader, header_section, resource)
            resource.sections["header"] = [header_data]
            resource.values.update(header_data)

        # -----------------------------
        # Parse remaining sections
        # -----------------------------

        sections_to_parse = list(self.schema.sections)
        # Handle inter-section dependencies by reordering.
        # For ITM/SPL, 'feature_blocks' count depends on 'extended_headers', so parse extended_headers first.
        if any(s.name == "extended_header" for s in sections_to_parse) and \
           any(s.name == "feature_block" for s in sections_to_parse):
            
            def sort_key(section):
                if section.name == "extended_header":
                    return 0  # This should come first
                if section.name == "feature_block":
                    return 1  # This should come after
                return 2 # All others
            
            sections_to_parse.sort(key=sort_key)

        for section in sections_to_parse:

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
            count = self._determine_section_count(section, resource)
            entries = []

            for _ in range(count):

                # Safety guard: prevent reading past EOF
                if reader.tell() >= filesize:
                    break

                entry = self._read_section(reader, section, resource)
                entries.append(entry)

            resource.sections[section.name] = entries

        return resource

    def _determine_section_count(self, section, resource):
        """
        Calculates the number of entries to read for a section.
        Handles logic for 'orphaned' data (e.g. Feature Blocks referenced by Abilities
        outside the Global Effect count).
        """
        # Special handling for Feature Blocks to capture orphaned data
        if section.name == "feature_block" and "extended_header" in resource.sections:
            # Start with the count of global/equipping effects from the header.
            # This field name is specific to the ITM schema.
            global_effect_count = resource.values.get("count_of_equipping_feature_blocks", 0)
            max_needed = global_effect_count
            
            for ability in resource.sections["extended_header"]:
                idx = ability.get("index_into_feature_blocks")
                cnt = ability.get("count_of_feature_blocks")

                if isinstance(idx, int) and isinstance(cnt, int):
                    # If an ability references index 10 with count 5, we need at least 15 blocks (0-14)
                    needed = idx + cnt
                    if needed > max_needed:
                        max_needed = needed
            
            return max_needed

        # Default behavior for all other sections
        if section.count_field:
            count = resource.values.get(section.count_field, 0)
            return count
        
        # Default for sections with no count field (like the header)
        return 1


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

        return section_data

    def write(self, writer, resource):
        """
        Writes a Resource object back to a binary stream.
        - If the resource is unmodified, it preserves the original file layout (offsets and gaps).
        - If the resource has been modified, it repacks the file and recalculates all offsets.
        """
        
        # 1. Calculation Phase (only if modified)
        # If the resource has been modified, we recalculate all offsets and counts for a clean, repacked file.
        # Otherwise, we use the original offsets stored in resource.values to ensure byte-for-byte fidelity.
        if resource.modified:
            current_offset = 0
            header_section = self.schema.get_section("header")
            if header_section:
                # This simple sum assumes fixed-size fields in header (standard for IE games)
                header_size = sum(f.attributes.get("size", 0) for f in header_section.fields) 
                current_offset += header_size

            # Calculate new positions for remaining sections based on schema order
            for section in self.schema.sections:
                if section.name == "header":
                    continue

                entries = resource.sections.get(section.name, [])
                count = len(entries)
                
                if section.count_field:
                    resource.values[section.count_field] = count
                
                if section.offset_field:
                    # For repacked files, point empty sections to 0.
                    resource.values[section.offset_field] = current_offset if count > 0 else 0

                if count > 0:
                    # Note: This assumes fixed-size entries.
                    entry_size = sum(f.attributes.get("size", 0) for f in section.fields)
                    current_offset += (entry_size * count)

        # 2. Writing Phase
        # Determine the physical write order by sorting sections based on their offset.
        # This is critical for fidelity mode and makes repacking more robust.
        sections_to_write = []
        for section in self.schema.sections:
            if section.name == "header": continue
            # Only consider sections that have data and an offset field.
            if section.offset_field and resource.sections.get(section.name):
                sections_to_write.append(section)

        sections_to_write.sort(key=lambda s: resource.values.get(s.offset_field, 0))

        # Write header first (always at offset 0)
        header_section = self.schema.get_section("header")
        if header_section:
            header_entry = resource.sections.get("header", [{}])[0]
            for field in header_section.fields:
                # For header fields, always pull from the definitive 'values' map
                val = resource.values.get(field.name, header_entry.get(field.name))
                field.type.write(writer, val, field)

        # Write remaining sections in their physical order
        for section in sections_to_write:
            target_offset = resource.values.get(section.offset_field)
            padding_needed = target_offset - writer.file.tell()
            if padding_needed > 0:
                writer.write(b'\x00' * padding_needed)

            for entry in resource.sections.get(section.name, []):
                for field in section.fields:
                    field.type.write(writer, entry.get(field.name), field)