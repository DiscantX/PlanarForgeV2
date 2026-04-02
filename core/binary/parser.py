from core.resource import Resource


class BinaryParser:

    def __init__(self, schema, resource_class=Resource):
        self.schema = schema
        self.resource_class = resource_class

    def read(self, reader, name=None, source=None):
 
        resource = self.resource_class(self.schema, name=name, source=source)
        resource.sections = {}
 
        max_pos  = reader.tell()
        filesize = reader.size()
 
        # ------------------------------------------------------------------
        # Parse header first
        # ------------------------------------------------------------------
        header_section = self.schema.get_section("header")
        if header_section:
            header_data = self._read_section(reader, header_section, resource)
            resource.sections["header"] = [header_data]
            resource.values.update(header_data)
            max_pos = max(max_pos, reader.tell())
 
        # ------------------------------------------------------------------
        # Parse remaining sections
        # ------------------------------------------------------------------
        sections_to_parse = list(self.schema.sections)
 
        # Sort extended_header before feature_block for orphaned-effect logic.
        def _is_ext_hdr(n): return n in ("extended_header", "extended_headers")
        def _is_feat_blk(n): return n in ("feature_block", "feature_blocks", "effects")
 
        if (any(_is_ext_hdr(s.name) for s in sections_to_parse) and
                any(_is_feat_blk(s.name) for s in sections_to_parse)):
            def sort_key(section):
                if _is_ext_hdr(section.name): return 0
                if _is_feat_blk(section.name): return 1
                return 2
            sections_to_parse.sort(key=sort_key)
 
        for section in sections_to_parse:
            if section.name == "header":
                continue
 
            # --- Locate section start --------------------------------------
            if section.offset_from:
                # Derive offset from a field inside another section\'s entry.
                # e.g. offset_from: {section: overlays, index: 0, field: offset_to_tilemap}
                spec        = section.offset_from
                src_name    = spec["section"]
                entry_index = int(spec.get("index", 0))
                src_field   = spec["field"]
                src_entries = resource.sections.get(src_name, [])
                offset = None
                if entry_index < len(src_entries):
                    offset = src_entries[entry_index].get(src_field)
                if offset is None:
                    raise ValueError(
                        f"Section \'{section.name}\' offset_from "
                        f"\'{src_name}[{entry_index}].{src_field}\' could not be resolved"
                    )
                if offset == 0 and not section.count_field and not section.count_expr:
                    resource.sections[section.name] = []
                    continue
                reader.seek(offset)
                max_pos = max(max_pos, reader.tell())
 
            elif section.offset_field:
                offset = resource.values.get(section.offset_field)
                if offset is None:
                    raise ValueError(
                        f"Section \'{section.name}\' references missing offset field "
                        f"\'{section.offset_field}\'"
                    )
                if offset == 0 and not section.count_field and not section.count_expr:
                    resource.sections[section.name] = []
                    continue
                reader.seek(offset)
                max_pos = max(max_pos, reader.tell())
 
            # --- Determine entry count ------------------------------------
            count   = self._determine_section_count(section, resource, reader)
            entries = []
            for _ in range(count):
                entry = self._read_section(reader, section, resource)
                entries.append(entry)
 
            resource.sections[section.name] = entries
            max_pos = max(max_pos, reader.tell())
 
            # Promoted sections (e.g. secondary_header) merge their single
            # parsed entry into resource.values so subsequent sections can
            # reference the offset/count fields by name.
            if section.promote and entries:
                resource.values.update(entries[0])
 
        # ------------------------------------------------------------------
        # Capture unreferenced trailing data for fidelity on unmodified files.
        # ------------------------------------------------------------------
        remaining_bytes = filesize - max_pos
        if remaining_bytes > 0:
            reader.seek(max_pos)
            resource.trailing_data = reader.read(remaining_bytes)
 
        return resource

    def _determine_section_count(self, section, resource, reader=None):
        """
        Calculates the number of entries to read for a section.
 
        Resolution order:
          1. count_expr  — declarative derivation from another section
          2. feature_block heuristic (orphaned effects)
          3. count_field  — standard header/promoted-section field reference
          4. default 1   (header-like single-entry sections)
        """

        def _section_entry_size(sec):
            return sum(
                f.attributes.get("size", 0)
                for f in sec.fields
                if f.attributes.get("size", 0) != 0
            )

        def _max_index_extent(entries, index_field, count_field):
            max_needed = 0
            for entry in entries:
                idx = int(entry.get(index_field, 0) or 0)
                cnt = int(entry.get(count_field, 0) or 0)
                needed = idx + cnt
                if needed > max_needed:
                    max_needed = needed
            return max_needed

        def _max_offset_extent(entries, offset_field, count_field, base_offset, unit_size):
            if unit_size <= 0:
                return 0

            max_needed = 0
            for entry in entries:
                offset = int(entry.get(offset_field, 0) or 0)
                count = int(entry.get(count_field, 0) or 0)

                if count <= 0 or offset < base_offset:
                    continue

                rel = offset - base_offset
                if rel % unit_size != 0:
                    continue

                idx = rel // unit_size
                needed = idx + count
                if needed > max_needed:
                    max_needed = needed

            return max_needed
 
        # ------------------------------------------------------------------
        # 1. count_expr
        # ------------------------------------------------------------------
        if section.count_expr:
            expr = section.count_expr
 
            # {"sum": {"section": "X", "field": "Y"}}
            # Sum field Y across all entries of section X.
            if "sum" in expr:
                spec       = expr["sum"]
                src_name   = spec["section"]
                field_name = spec["field"]
                entries    = resource.sections.get(src_name, [])
                total = 0
                for entry in entries:
                    val = entry.get(field_name, 0)
                    total += int(val) if val is not None else 0

                # WED uses sparse "windowed" pools in some files:
                # counts derived as sums can under-read physical data.
                # We preserve fidelity by honoring the max indexed/offset extent.
                if resource.schema.name == "WED":
                    if section.name == "door_tile_cell_indices":
                        door_entries = resource.sections.get("doors", [])
                        max_extent = _max_index_extent(
                            door_entries,
                            "first_door_tile_cell_index",
                            "count_of_door_tile_cells",
                        )
                        if max_extent > total:
                            return max_extent

                    if section.name == "tilemaps":
                        overlay_entries = resource.sections.get("overlays", [])
                        base_offset = reader.tell() if reader else 0
                        max_extent = _max_offset_extent(
                            overlay_entries,
                            "offset_to_tilemap",
                            "tile_count",
                            base_offset,
                            _section_entry_size(section),
                        )
                        if max_extent > total:
                            return max_extent

                    if section.name == "tile_index_lookup":
                        overlay_entries = resource.sections.get("overlays", [])
                        base_offset = reader.tell() if reader else 0
                        max_extent = _max_offset_extent(
                            overlay_entries,
                            "offset_to_tile_index_lookup",
                            "tile_count",
                            base_offset,
                            _section_entry_size(section),
                        )
                        if max_extent > total:
                            return max_extent

                return total
 
            # {"ceil_product": {"section": "X", "index": 0,
            #                   "numerators": ["width","height"],
            #                   "denominators": [10, 7.5]}}
            # Compute product of ceil(field/divisor) for each pair.
            # Used for wall_groups: ceil(w/10) * ceil(h/7.5).
            if "ceil_product" in expr:
                import math
                spec         = expr["ceil_product"]
                src_name     = spec["section"]
                idx          = int(spec.get("index", 0))
                numerators   = spec["numerators"]    # list of field names
                denominators = spec["denominators"]  # list of numeric divisors
                entries      = resource.sections.get(src_name, [])
                if idx >= len(entries):
                    return 0
                entry  = entries[idx]
                result = 1
                for num_field, denom in zip(numerators, denominators):
                    val = entry.get(num_field) or 0
                    result *= math.ceil(val / denom)
                return result
 
            raise ValueError(
                f"Unknown count_expr type in section \'{section.name}\': "
                f"{list(expr.keys())}"
            )
 
        # ------------------------------------------------------------------
        # 2. Feature-block / effects heuristic (orphaned effect blocks)
        # ------------------------------------------------------------------
        is_feat_blk  = section.name in ("feature_block", "feature_blocks", "effects")
        ext_hdr_name = next(
            (n for n in ("extended_header", "extended_headers")
             if n in resource.sections),
            None,
        )
 
        if is_feat_blk and ext_hdr_name:
            global_effect_count = (
                resource.values.get("count_of_equipping_feature_blocks") or
                resource.values.get("count_of_effects") or
                0
            )
            max_needed = global_effect_count
 
            for ability in resource.sections[ext_hdr_name]:
                idx = (ability.get(f"index_into_{section.name}")
                       or ability.get(f"index_into_{section.name}s")
                       or ability.get("index_into_feature_blocks"))
                cnt = (ability.get(f"count_of_{section.name}")
                       or ability.get(f"count_of_{section.name}s")
                       or ability.get("count_of_feature_blocks"))
                if isinstance(idx, int) and isinstance(cnt, int):
                    needed = idx + cnt
                    if needed > max_needed:
                        max_needed = needed
 
            if reader:
                current_offset = reader.tell()
                is_last_section = True
                for s in self.schema.sections:
                    if s.name != section.name and s.offset_field:
                        off = resource.values.get(s.offset_field, 0)
                        if off > current_offset:
                            is_last_section = False
                            break
                if is_last_section:
                    entry_size = sum(
                        f.attributes.get("size", 0) for f in section.fields
                    )
                    if entry_size > 0:
                        remaining_bytes = reader.size() - current_offset
                        physical_count  = remaining_bytes // entry_size
                        if physical_count > max_needed:
                            return physical_count
 
            return max_needed
 
        # ------------------------------------------------------------------
        # 3. count_field
        # ------------------------------------------------------------------
        if section.count_field:
            count = resource.values.get(section.count_field, 0)

            # WED door polygons often extend beyond secondary_header.count_of_polygons.
            # Preserve all physically referenced polygons by using the max door extent.
            if resource.schema.name == "WED" and section.name == "polygons":
                base_offset = reader.tell() if reader else int(resource.values.get(section.offset_field, 0) or 0)
                entry_size = _section_entry_size(section)
                if entry_size > 0:
                    door_entries = resource.sections.get("doors", [])
                    max_needed = count
                    for door in door_entries:
                        for off_field, cnt_field in (
                            ("offset_to_polygons_open", "count_of_polygons_open"),
                            ("offset_to_polygons_closed", "count_of_polygons_closed"),
                        ):
                            offset = int(door.get(off_field, 0) or 0)
                            cnt = int(door.get(cnt_field, 0) or 0)
                            if cnt <= 0 or offset < base_offset:
                                continue
                            rel = offset - base_offset
                            if rel % entry_size != 0:
                                continue
                            idx = rel // entry_size
                            needed = idx + cnt
                            if needed > max_needed:
                                max_needed = needed
                    return max_needed

            return count
 
        # ------------------------------------------------------------------
        # 4. Default: single-entry section (header-like)
        # ------------------------------------------------------------------
        return 1


    def _read_section(self, reader, section, resource):

        section_data = {}

        for field in section.fields:
            current_offset = reader.tell()
            try:
                # Let field types see both header-level values and the fields
                # already parsed in the current section.
                context = dict(resource.values)
                context.update(section_data)
                value = field.type.read(reader, field, context)
            except Exception as e:
                # Re-raise with more context for better error reporting
                error_message = f"Parsing field '{field.name}' at offset {hex(current_offset)} failed: {e}"
                # Create a new exception of the same type to preserve the original error type
                raise type(e)(error_message) from e

            if field.attributes.get("flatten"):
                if not isinstance(value, dict):
                    raise TypeError(
                        f"Field '{field.name}' in section '{section.name}' is marked flatten=true but returned {type(value).__name__}"
                    )
                section_data.update(value)
            else:
                section_data[field.name] = value

        return section_data

    def write(self, writer, resource):
        """
        Writes a Resource object back to a binary stream.
 
        Unmodified resources: preserves the original file layout exactly
        (offsets and gaps), giving byte-for-byte fidelity.
 
        Modified resources: repacks the file cleanly, recalculating all
        offsets and counts.
        """
 
        # ==================================================================
        # Helper: resolve the physical offset of a section for writing.
        # Returns None if the section has no data and no fixed position.
        # ==================================================================
        def _section_write_offset(section):
            """Return the value in resource.values that gives this section's offset."""
            if section.offset_field:
                return resource.values.get(section.offset_field)
            if section.offset_from:
                spec      = section.offset_from
                src_name  = spec["section"]
                entry_idx = int(spec.get("index", 0))
                src_field = spec["field"]
                entries   = resource.sections.get(src_name, [])
                if entry_idx < len(entries):
                    return entries[entry_idx].get(src_field)
            return None
 
        # ==================================================================
        # Helper: measure one entry of a section (skip computed fields).
        # ==================================================================
        def _measure_entry(section, entry, entry_context):
            total = 0
            for field in section.fields:
                if field.attributes.get("size", 0) == 0:
                    continue  # computed / virtual field
                value = entry if field.attributes.get("flatten") else entry.get(field.name)
                total += field.type.measure(value, field, entry_context)
            return total
 
        # ==================================================================
        # Helper: write one entry of a section (skip computed fields).
        # ==================================================================
        def _write_entry(section, entry):
            for field in section.fields:
                if field.attributes.get("size", 0) == 0:
                    continue  # computed / virtual field — never serialized
                value = entry if field.attributes.get("flatten") else entry.get(field.name)
                field.type.write(writer, value, field)
 
        # ==================================================================
        # 1. CALCULATION PHASE (modified files only)
        # ==================================================================
        if resource.modified:
            current_offset = 0
 
            # --- Header size ---
            header_section = self.schema.get_section("header")
            if header_section:
                for f in header_section.fields:
                    if f.attributes.get("size", 0) == 0:
                        continue
                    current_offset += f.attributes.get("size", 0)
 
            # --- Remaining sections ---
            for section in self.schema.sections:
                if section.name == "header":
                    continue
 
                entries = resource.sections.get(section.name, [])
                count   = len(entries)
 
                # Update count_field if present.
                if section.count_field:
                    resource.values[section.count_field] = count
 
                # Compute and store the section\'s new offset.
                new_offset = current_offset if count > 0 else 0
 
                if section.offset_field:
                    resource.values[section.offset_field] = new_offset
 
                if section.offset_from and count > 0:
                    # Write the new offset back into the source entry field.
                    spec      = section.offset_from
                    src_name  = spec["section"]
                    entry_idx = int(spec.get("index", 0))
                    src_field = spec["field"]
                    src_entries = resource.sections.get(src_name, [])
                    if entry_idx < len(src_entries):
                        src_entries[entry_idx][src_field] = new_offset
 
                # Advance current_offset by the byte size of all entries.
                if count > 0:
                    for entry in entries:
                        entry_context = dict(resource.values)
                        entry_context.update(entry)
                        current_offset += _measure_entry(section, entry, entry_context)
 
                # --- offset_update: per-entry pointer rewrite ---
                # After we know where this section starts, patch each entry
                # in the referenced section so its pointer field reflects the
                # correct sub-offset within the flat array we are about to write.
                if section.offset_update and count > 0:
                    upd         = section.offset_update
                    upd_src     = upd["section"]
                    upd_field   = upd["field"]
                    stride_spec = upd.get("stride_expr")
 
                    upd_entries        = resource.sections.get(upd_src, [])
                    current_sub_offset = new_offset
 
                    for upd_entry in upd_entries:
                        upd_entry[upd_field] = current_sub_offset
                        if stride_spec:
                            stride_field = stride_spec.get("field")
                            stride_val   = int(upd_entry.get(stride_field, 0) or 0)
                        else:
                            stride_val = 0
                        # word_scalar_array entries are 2 bytes each;
                        # tilemap entries use the section\'s measured entry size.
                        # Determine the byte width of one logical stride unit.
                        # For tile_index_lookup the stride is in words (×2).
                        # For tilemaps the stride is tile_count entries × entry_size.
                        #
                        # We detect which case we are in by checking whether
                        # the section has a single word-per-entry field or multi-
                        # byte entries, using the entry size of the first entry.
                        if entries:
                            first_entry = entries[0]
                            first_ctx   = dict(resource.values)
                            first_ctx.update(first_entry)
                            single_entry_size = _measure_entry(section, first_entry, first_ctx)
                        else:
                            single_entry_size = 2  # fallback: word
 
                        current_sub_offset += stride_val * single_entry_size
 
        # ==================================================================
        # 2. WRITING PHASE
        # ==================================================================
 
        # Collect all non-header sections that have data and a known offset,
        # regardless of whether that offset comes from offset_field or
        # offset_from.
        sections_to_write = []
        for section in self.schema.sections:
            if section.name == "header":
                continue
            if not resource.sections.get(section.name):
                continue
            offset = _section_write_offset(section)
            if offset is not None and offset > 0:
                sections_to_write.append((offset, section))
 
        # Sort by physical offset so we write in file order.
        sections_to_write.sort(key=lambda t: t[0])
 
        # --- Write header (always at offset 0) ---
        header_section = self.schema.get_section("header")
        if header_section:
            header_entry = resource.sections.get("header", [{}])[0]
            for field in header_section.fields:
                if field.attributes.get("size", 0) == 0:
                    continue
                val = resource.values.get(field.name)
                field.type.write(writer, val, field)
 
        # --- Write remaining sections in physical order ---
        for target_offset, section in sections_to_write:
            # Insert padding to reach the target offset.
            current_pos    = writer.file.tell()
            padding_needed = target_offset - current_pos
            if padding_needed > 0:
                if (
                    not resource.modified and
                    hasattr(resource, "_original_bytes") and
                    isinstance(resource._original_bytes, (bytes, bytearray)) and
                    target_offset <= len(resource._original_bytes)
                ):
                    writer.write(resource._original_bytes[current_pos:target_offset])
                else:
                    writer.write(b'\x00' * padding_needed)
 
            for entry in resource.sections.get(section.name, []):
                _write_entry(section, entry)
 
        # --- Append trailing data (unmodified fidelity mode only) ---
        if not resource.modified and hasattr(resource, "trailing_data"):
            writer.write(resource.trailing_data)
