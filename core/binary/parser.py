import math

from core.resource import Resource


class BinaryParser:

    def __init__(
        self,
        schema,
        resource_class=Resource,
        audit_unknown_gaps=False,
        gap_audit_max_entries=10,
        gap_audit_sample_size=4096,
        unknown_gap_policy="allow",
    ):
        self.schema = schema
        self.resource_class = resource_class
        self.audit_unknown_gaps = bool(audit_unknown_gaps)
        self.gap_audit_max_entries = max(1, int(gap_audit_max_entries or 10))
        self.gap_audit_sample_size = max(64, int(gap_audit_sample_size or 4096))
        self.unknown_gap_policy = (unknown_gap_policy or "allow").strip().lower()
        if self.unknown_gap_policy not in {"allow", "warn", "fail_nonzero"}:
            raise ValueError(
                "unknown_gap_policy must be one of: allow, warn, fail_nonzero"
            )

    def _append_byte_claim(self, resource, section_name, entry_index, field_name, field_type, start, end):
        if end <= start:
            return
        resource.byte_claims.append(
            {
                "start": int(start),
                "end": int(end),
                "size": int(end - start),
                "section": section_name,
                "entry_index": int(entry_index),
                "field": field_name,
                "field_type": field_type,
            }
        )

    @staticmethod
    def _merge_claimed_ranges(claims):
        if not claims:
            return []

        sorted_claims = sorted(claims, key=lambda c: (c["start"], c["end"]))
        merged = [{"start": sorted_claims[0]["start"], "end": sorted_claims[0]["end"]}]

        for claim in sorted_claims[1:]:
            last = merged[-1]
            if claim["start"] <= last["end"]:
                if claim["end"] > last["end"]:
                    last["end"] = claim["end"]
            else:
                merged.append({"start": claim["start"], "end": claim["end"]})

        for rng in merged:
            rng["size"] = rng["end"] - rng["start"]
        return merged

    @staticmethod
    def _ascii_preview(data, limit=64):
        snippet = data[:limit]
        return "".join(chr(b) if 32 <= b <= 126 else "." for b in snippet)

    def _summarize_gap_bytes(self, data):
        size = len(data)
        if size == 0:
            return {
                "size": 0,
                "zero_bytes": 0,
                "ff_bytes": 0,
                "nonzero_bytes": 0,
                "nonzero_ratio": 0.0,
                "entropy": 0.0,
                "head_hex": "",
                "tail_hex": "",
                "ascii_preview": "",
            }

        counts = [0] * 256
        for b in data:
            counts[b] += 1

        zero_bytes = counts[0]
        ff_bytes = counts[0xFF]
        nonzero_bytes = size - zero_bytes
        nonzero_ratio = nonzero_bytes / size

        entropy = 0.0
        for count in counts:
            if count:
                p = count / size
                entropy -= p * math.log2(p)

        head_len = min(32, size)
        tail_len = min(32, size)
        head_hex = data[:head_len].hex(" ")
        tail_hex = data[-tail_len:].hex(" ") if size > head_len else head_hex

        return {
            "size": size,
            "zero_bytes": zero_bytes,
            "ff_bytes": ff_bytes,
            "nonzero_bytes": nonzero_bytes,
            "nonzero_ratio": round(nonzero_ratio, 6),
            "entropy": round(entropy, 6),
            "head_hex": head_hex,
            "tail_hex": tail_hex,
            "ascii_preview": self._ascii_preview(data),
        }

    @staticmethod
    def _serialize_claim_ref(claim):
        if not claim:
            return None
        return {
            "section": claim["section"],
            "entry_index": claim["entry_index"],
            "field": claim["field"],
            "field_type": claim["field_type"],
            "start": claim["start"],
            "end": claim["end"],
            "size": claim["size"],
        }

    def _collect_gap_pointer_hits(self, resource, gap_start, gap_end):
        hits = []
        for section_name, entries in resource.sections.items():
            if not isinstance(entries, list):
                continue
            for entry_idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                for key, value in entry.items():
                    if not isinstance(value, int):
                        continue
                    if "offset" not in key.lower():
                        continue
                    if gap_start <= value < gap_end:
                        hits.append(
                            {
                                "section": section_name,
                                "entry_index": entry_idx,
                                "field": key,
                                "value": value,
                                "offset_in_gap": value - gap_start,
                            }
                        )
        return hits

    def _detect_gap_candidates(self, schema_name, gap_size, pointer_hit_count, nonzero_ratio):
        candidates = []

        def add_candidate(name, stride):
            if stride <= 0 or gap_size == 0 or gap_size % stride != 0:
                return

            confidence = "medium"
            if pointer_hit_count > 0 and nonzero_ratio > 0:
                confidence = "high"
            elif nonzero_ratio == 0:
                confidence = "low"

            candidates.append(
                {
                    "type": name,
                    "entry_size": stride,
                    "entry_count": gap_size // stride,
                    "confidence": confidence,
                }
            )

        add_candidate("word_scalar_array", 2)
        add_candidate("dword_array", 4)
        add_candidate("qword_array", 8)

        if schema_name == "WED":
            add_candidate("wed_tilemap_entry", 10)
            add_candidate("wed_polygon_entry", 18)
            add_candidate("wed_vertex_entry", 4)

        return candidates[: self.gap_audit_max_entries]

    def _build_unknown_gap_report(self, resource, full_bytes):
        filesize = len(full_bytes)
        claims = sorted(resource.byte_claims, key=lambda c: (c["start"], c["end"]))
        merged = self._merge_claimed_ranges(claims)
        resource.claimed_ranges = merged

        gaps = []
        cursor = 0
        for rng in merged:
            if rng["start"] > cursor:
                gaps.append({"start": cursor, "end": rng["start"]})
            cursor = max(cursor, rng["end"])
        if cursor < filesize:
            gaps.append({"start": cursor, "end": filesize})

        max_claim_end = max((c["end"] for c in claims), default=0)
        detailed_gaps = []
        for idx, gap in enumerate(gaps):
            start = gap["start"]
            end = gap["end"]
            size = end - start
            gap_bytes = full_bytes[start:end]
            byte_summary = self._summarize_gap_bytes(gap_bytes)
            pointer_hits = self._collect_gap_pointer_hits(resource, start, end)
            candidates = self._detect_gap_candidates(
                resource.schema.name,
                size,
                len(pointer_hits),
                byte_summary["nonzero_ratio"],
            )

            prev_claim = next(
                (c for c in reversed(claims) if c["end"] <= start),
                None,
            )
            next_claim = next(
                (c for c in claims if c["start"] >= end),
                None,
            )

            if byte_summary["nonzero_bytes"] == 0:
                classification = "all_zero_padding"
                risk = "low"
            elif pointer_hits:
                classification = "pointer_referenced_nonzero"
                risk = "high"
            else:
                classification = "nonzero_unreferenced"
                risk = "medium"

            detailed_gaps.append(
                {
                    "gap_id": idx,
                    "start": start,
                    "end": end,
                    "size": size,
                    "kind": "tail_gap" if start >= max_claim_end else "internal_gap",
                    "classification": classification,
                    "risk": risk,
                    "zero_bytes": byte_summary["zero_bytes"],
                    "ff_bytes": byte_summary["ff_bytes"],
                    "nonzero_bytes": byte_summary["nonzero_bytes"],
                    "nonzero_ratio": byte_summary["nonzero_ratio"],
                    "entropy": byte_summary["entropy"],
                    "head_hex": byte_summary["head_hex"],
                    "tail_hex": byte_summary["tail_hex"],
                    "ascii_preview": byte_summary["ascii_preview"],
                    "previous_claim": self._serialize_claim_ref(prev_claim),
                    "next_claim": self._serialize_claim_ref(next_claim),
                    "pointers_into_gap": pointer_hits[: self.gap_audit_max_entries],
                    "pointer_hit_count": len(pointer_hits),
                    "candidates": candidates,
                }
            )

        resource.unknown_gaps = detailed_gaps
        resource.gap_audit_summary = {
            "filesize": filesize,
            "claimed_bytes": sum(r["size"] for r in merged),
            "unknown_bytes": sum(g["size"] for g in detailed_gaps),
            "total_gaps": len(detailed_gaps),
            "internal_gaps": sum(1 for g in detailed_gaps if g["kind"] == "internal_gap"),
            "tail_gaps": sum(1 for g in detailed_gaps if g["kind"] == "tail_gap"),
            "nonzero_gaps": sum(1 for g in detailed_gaps if g["nonzero_bytes"] > 0),
            "pointer_referenced_gaps": sum(1 for g in detailed_gaps if g["pointer_hit_count"] > 0),
            "high_risk_gaps": sum(1 for g in detailed_gaps if g["risk"] == "high"),
            "largest_gap_size": max((g["size"] for g in detailed_gaps), default=0),
        }

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
            header_data = self._read_section(reader, header_section, resource, entry_index=0)
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
            for entry_index in range(count):
                entry = self._read_section(reader, section, resource, entry_index=entry_index)
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

        if self.audit_unknown_gaps:
            original_pos = reader.tell()
            reader.seek(0)
            full_bytes = reader.read(filesize)
            reader.seek(original_pos)
            self._build_unknown_gap_report(resource, full_bytes)
 
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

        def _max_lookup_needed_from_tilemaps(tilemap_entries, overlay_entries, base_lookup_offset, unit_size):
            """
            Derive required tile_index_lookup length from tilemap references.

            Tilemap indices are interpreted relative to each overlay's lookup
            window (offset_to_tile_index_lookup). We map tilemaps to overlays
            via cumulative overlay.tile_count.
            """
            if unit_size <= 0:
                return 0

            max_needed = 0
            tile_cursor = 0
            for overlay in overlay_entries:
                tile_count = int(overlay.get("tile_count", 0) or 0)
                lookup_offset = int(overlay.get("offset_to_tile_index_lookup", 0) or 0)

                if tile_count <= 0:
                    continue
                if lookup_offset < base_lookup_offset:
                    tile_cursor += tile_count
                    continue

                rel = lookup_offset - base_lookup_offset
                if rel % unit_size != 0:
                    tile_cursor += tile_count
                    continue

                overlay_base_index = rel // unit_size
                overlay_tilemaps = tilemap_entries[tile_cursor: tile_cursor + tile_count]

                for tilemap in overlay_tilemaps:
                    primary_idx = int(tilemap.get("primary_tile_index", 0) or 0)
                    primary_cnt = int(tilemap.get("primary_tile_count", 0) or 0)
                    need_primary = overlay_base_index + primary_idx + primary_cnt
                    if need_primary > max_needed:
                        max_needed = need_primary

                    secondary_idx = tilemap.get("secondary_tile_index")
                    if isinstance(secondary_idx, int) and secondary_idx not in (0xFFFF, 65535):
                        need_secondary = overlay_base_index + secondary_idx + 1
                        if need_secondary > max_needed:
                            max_needed = need_secondary

                tile_cursor += tile_count

            return max_needed

        def _physical_cap_count(current_section, base_offset, unit_size):
            """
            Cap count by next known section offset to avoid overlap.
            """
            if unit_size <= 0:
                return None

            next_offsets = []
            for sec in self.schema.sections:
                if sec.name == current_section.name:
                    continue

                offset = None
                if sec.offset_field:
                    offset = resource.values.get(sec.offset_field)
                elif sec.offset_from:
                    spec = sec.offset_from
                    src_entries = resource.sections.get(spec["section"], [])
                    src_idx = int(spec.get("index", 0))
                    if src_idx < len(src_entries):
                        offset = src_entries[src_idx].get(spec["field"])

                if isinstance(offset, int) and offset > base_offset:
                    next_offsets.append(offset)

            if not next_offsets:
                return None

            next_offset = min(next_offsets)
            return max(0, (next_offset - base_offset) // unit_size)
 
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
                        # Some files have stale/zero unique_tile_count and/or sparse
                        # lookup windows. Derive required extent from tilemap indices.
                        # This captures real lookup payload past sum(width*height).
                        tilemap_entries = resource.sections.get("tilemaps", [])
                        max_from_tilemaps = _max_lookup_needed_from_tilemaps(
                            tilemap_entries,
                            overlay_entries,
                            base_offset,
                            _section_entry_size(section),
                        )

                        # Also consider offset windows that may be keyed by
                        # unique_tile_count when present.
                        max_from_unique = _max_offset_extent(
                            overlay_entries,
                            "offset_to_tile_index_lookup",
                            "unique_tile_count",
                            base_offset,
                            _section_entry_size(section),
                        )

                        max_extent = max(max_extent, max_from_tilemaps, max_from_unique)
                        physical_cap = _physical_cap_count(
                            section,
                            base_offset,
                            _section_entry_size(section),
                        )
                        if physical_cap is not None and max_extent > physical_cap:
                            max_extent = physical_cap
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


    def _read_section(self, reader, section, resource, entry_index=0):

        section_data = {}

        for field in section.fields:
            current_offset = reader.tell()
            try:
                # Let field types see both header-level values and the fields
                # already parsed in the current section.
                context = dict(resource.values)
                context.update(section_data)
                value = field.type.read(reader, field, context)
                end_offset = reader.tell()
                self._append_byte_claim(
                    resource,
                    section_name=section.name,
                    entry_index=entry_index,
                    field_name=field.name,
                    field_type=field.type_name,
                    start=current_offset,
                    end=end_offset,
                )
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
        if resource.modified and self.unknown_gap_policy in {"warn", "fail_nonzero"}:
            unknown_gaps = getattr(resource, "unknown_gaps", []) or []
            nonzero_gaps = [g for g in unknown_gaps if int(g.get("nonzero_bytes", 0) or 0) > 0]
            if nonzero_gaps:
                message = (
                    f"Modified save blocked by unknown-gap policy: "
                    f"{len(nonzero_gaps)} non-zero unknown gap(s) detected."
                )
                if self.unknown_gap_policy == "fail_nonzero":
                    raise ValueError(message)
                print(f"Warning: {message}")
 
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
            current_pos    = writer.file.tell()

            # In fidelity mode, section pointers from legacy/edge-case files can
            # overlap or move backwards. Re-seek to the declared offset so
            # subsequent writes do not drift forward from an earlier overlap.
            if not resource.modified and current_pos > target_offset:
                writer.file.seek(target_offset)
                current_pos = target_offset

            # Insert padding to reach the target offset.
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
