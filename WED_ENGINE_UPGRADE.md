# Engineering Log: WED V1.3 & Relational Engine Upgrades

## Overview
The WED (World Environment Definition) format V1.3 is significantly more complex than previous formats (ITM, SPL, CRE). It introduces hierarchical dependencies where offsets and counts for data blocks are stored not just in the main header, but within a "Secondary Header" and individual entries of the "Overlays" section.

This document tracks the architectural changes required in the `BinaryParser` and `FieldTypes` to support relational data modeling while maintaining 100% round-trip fidelity.

## Objectives
1. **Relational Context:** Allow subsequent sections to resolve offsets from any "Header-like" section (e.g., the Secondary Header).
2. **Pointer Management:** Support `offset_from` and `offset_update` mechanisms to handle sections pointed to by entries in other tables (like per-overlay tilemaps).
3. **Computed Fields & Counts:** Support virtual fields (`computed`) for intra-entry arithmetic and `count_expr` for inter-section aggregate counts.
4. **Zero Regression:** Ensure changes do not break existing fidelity for ITM, SPL, CRE, and ARE formats.

## Brainstorming & Identified Hurdles

### 1. The Secondary Header Scope
**Problem:** Currently, `BinaryParser.read` only merges fields from the "header" section into `resource.values`. Sections like `polygons` and `vertices` in WED rely on offsets found in the `secondary_header`.
**Plan:** Modify the parser to "promote" any section with a count of 1 to the global `resource.values` pool if it is defined before the sections that depend on it.

### 2. The Per-Overlay Tilemap Problem
**Problem:** Tilemaps and Lookup tables are described as "windows" into global pools by pointers inside `overlays` and `doors`.
**Plan:** Move away from "Jump" types. Instead, treat Tilemaps and Lookups as global flat sections whose physical `offset` is derived from the first referencing entry (e.g., `overlays[0].offset_to_tilemap`) and whose `count` is an aggregate (e.g., `sum(width * height)`).

### 3. Sum-Based Lookup Tables
**Problem:** Tables like `door_tile_cell_indices` don't have a single count field. Their size is the sum of `count_of_door_tile_cells` across all `doors`.
**Plan:** Add logic to `_determine_section_count` to allow for cross-section sum calculations or "Physical Extent" reading (reading until the next known offset).

---

## Implementation Roadmap

### Phase 1: Context Promotion
- [x] Update `BinaryParser.read` to identify single-entry sections (Promote context).
- [x] Merge promoted fields into `resource.values`.

### Phase 2: Relational Field Types
- [x] Create `Computed` field type for intra-entry arithmetic (e.g., `tile_count`).
- [x] Create `WordScalarArray` for flat lookup tables.
- [x] Implement `evaluate_expr` (AST-based) for safe schema-defined math.

### Phase 3: Lookup Table Fidelity
- [x] Implement `count_expr` (sum/ceil_product) in `BinaryParser._determine_section_count`.
- [x] Implement `offset_from` in `BinaryParser.read` to locate sections via external fields.

### Phase 4: Full Modding Support (Recomputation)
- [x] Overhaul `BinaryParser.write` to support `offset_update` logic.
- [x] Implement pointer recomputation for sections where multiple entries point to different "windows" of a global section.

---

## Success & Failure Log

### [2026-04-01] Initial Brainstorming
- **Status:** Planning Stage.
- **Decision:** We will avoid "Tail/Zombie" raw byte captures for WED. We will instead aim for a fully modeled relational approach to make the data human-readable and editable.
- **Risk:** The `BinaryParser.write` logic will need to be extremely careful when recalculating offsets for jumped blocks to avoid overlapping data or creating massive gaps.

### [2026-04-01] Validation & Fidelity Fixes
- **Success:** `wed_v1_3.yaml` successfully passed the `SchemaLoader` validation test.
- **Success:** Fixed "0xae" zero-fill and trailing data issues by including `JumpArray` blocks in the physical write list and tracking `_max_read_pos` during relational jumps.

### [2026-04-01] Fidelity Mismatches (Relational Sync)
- **Status:** Troubleshooting.
- **Problem:** Despite previous fixes, fidelity tests for WED files are still failing.
    - **Symptom 1: Zero-padding at `0xae` and `0x630`:** Data like the Tilemap or lookup tables are being replaced with null bytes. This indicates the writer is missing these blocks in its write-target list.
    - **Symptom 2: Unmapped data at the end of the file:** The `trailing_data` buffer is capturing bytes that were originally part of the file's structured content, suggesting the parser is not fully reading all relevant data.
- **Fixes Implemented:**
    - **Universal Read Extent Tracking:** Modified `BinaryParser._read_section` to update `resource._max_read_pos` after every field read.
    - **Relational Block Discovery:** Updated `_get_all_jumped_blocks` to include entries with empty values (empty lists) if they have a valid offset, ensuring they aren't treated as empty gaps.
    - **Context Inheritance:** Ensured `JumpArray` correctly updates the resource's read position *before* performing the `finally` seek-back.
    - **Shared Offset Deduplication Priority:** Updated `BinaryParser.write` to deduplicate shared offsets while prioritizing non-empty data blocks, preventing empty sections (like Doors) from zero-filling shared relational data (like Tilemaps).
    - **Shared Offset Deduplication:** Updated `BinaryParser.write` to deduplicate between Sections and JumpArrays using a single `seen_offsets` set, preventing the zeroing of shared data.
- **Analysis:**
    1.  **Shared Relational Data (Zero-padding):** The `0xae` zero-padding is highly indicative of shared `JumpArray` blocks (e.g., `tile_index_lookup_table`). If multiple `overlays` point to the same `tile_index_lookup_table`, the `BinaryParser.write` logic for unmodified resources was not correctly identifying and writing these shared blocks. Instead, it was treating the space as a gap and filling it with zeros. This suggests that some `JumpArray` blocks are being read as empty when they should contain data, which would happen if their `count_ref` (e.g., `count_of_unique_tiles`, `width * height`) is `0` in the parsed `resource`, but non-zero in the original file.
    2.  **`_max_read_pos` Tracking (Unmapped Data):** The `resource._max_read_pos` was intended to track the furthest byte read by the `BinaryReader` (including during `JumpArray` operations). However, the placement of its update within `JumpArray.read` was not correctly capturing the absolute furthest extent of the read operation, leading to legitimate data being classified as `trailing_data`.
- **Fixes Implemented:**
    1.  **Correct `_max_read_pos` Tracking in `JumpArray.read`:** The `JumpArray.read` method now explicitly updates `resource._max_read_pos` to `reader.tell()` *before* it seeks back to the `current_pos` in its `finally` block. This ensures that the furthest point reached by the reader during a jump operation is correctly recorded.
    2.  **Refined `JumpArray` Count Evaluation:** Added additional logging to `JumpArray.read` to help diagnose if `count_ref` or `count_mult_ref` are unexpectedly evaluating to `0` for blocks that should contain data.
    3.  **Robust `BinaryParser.write` for Unmodified Resources:** The `write` method's fidelity path (`resource.modified == False`) has been reviewed to ensure that all `JumpArray` blocks are correctly identified, their `original_offset` is respected, and they are written in the correct physical order, preventing unintended zero-padding.
- **Verification:** Re-running fidelity tests.

### [2026-04-01] Fidelity Mismatches (Relational Overlap Conflict)
- **Status:** Troubleshooting.
- **Problem:** Still seeing zero-padding at `0xAE` (Tilemap count) and `0x630` (Tilemap index lookup), indicating that empty sections are still "hijacking" shared offsets and preventing non-empty data from being written.
- **Analysis:** The previous `seen_offsets` logic was not robust enough to handle cases where an empty section and a non-empty `JumpArray` shared the same offset. The empty section was added to `write_targets` and, because it wrote no data, effectively zeroed out the space that the non-empty `JumpArray` should have occupied.
- **Fixes Implemented:**
    1.  **Offset Candidate Registry:** Introduced `offset_candidates` in `BinaryParser.write` to collect all potential writers for a given offset.
    2.  **Prioritize Data:** Implemented logic to prioritize candidates with actual data over empty ones when multiple blocks share an offset.
    3.  **Final `write_targets` Construction:** Built `write_targets` from the prioritized `offset_candidates`, ensuring only one (the best) block is written per unique offset.
    4.  **`_max_read_pos` Update Removal from `_read_section`:** Removed the `resource._max_read_pos` update from `BinaryParser._read_section` to prevent it from overwriting the correct furthest extent recorded by `JumpArray.read`.
- **Verification:** Re-running fidelity tests.

### [2026-04-01] Fidelity Mismatches (Secondary Header and Vertices)
- **Status:** Resolved.
- **Problem:** `vertices` section was empty in serialized output. 
- **Analysis:** Corrected a mistaken assumption about the `secondary_header` layout. The header matches IESDP (no vertex count). The empty vertices were caused by a dangling `count_field` reference.
- **Fixes Implemented:**
    1.  **Header Verification:** Confirmed `secondary_header` matches IESDP exactly.
    2.  **Vertex Count Resolution:** Updated `BinaryParser._determine_section_count` to calculate the vertex count by scanning the maximum extent referenced by the `polygons` section.
    3.  **Wall Group Correction:** Updated wall group count formula to use the `(width + 9) // 10` standard.

### [2026-04-01] Fidelity Mismatches (Shared Block Truncation)
- **Status:** Troubleshooting.
- **Problem:** Zero-padding still occurring at `0xAE`. Debug logs confirm multiple Overlays share the same offset but with different calculated counts.
- **Analysis:** The writer was picking the first candidate for a shared offset. If a "small" overlay was processed before a "large" one, the data was truncated and the remainder zero-filled.
- **Fixes Implemented:** Updated `BinaryParser.write` to perform size-based prioritization for shared offsets, ensuring the largest (most complete) version of shared data is written.

### [2026-04-01] Fidelity Mismatches (Shared Offset Overwrite)
- **Status:** Troubleshooting.
- **Problem:** Debug output shows an empty `doors` section overwriting a non-empty `tilemap` in `offset_candidates` for `0xAC`, leading to zero-filling.
- **Analysis:** The `offset_candidates` population was done in two separate loops (sections then relational blocks). If an empty section was processed after a non-empty relational block, and `resource.modified` was `False`, the empty section would overwrite the valid candidate due to the `elif has_data or not resource.modified` condition.
- **Fixes Implemented:** Refactored `BinaryParser.write` to collect all potential candidates (sections and relational blocks) into a single list first. Then, a single pass populates `offset_candidates` by applying the prioritization logic (non-empty over empty, larger over smaller) consistently, ensuring the best candidate always wins.

### [2026-04-01] Fidelity Mismatches (Relational Priority)
- **Status:** Troubleshooting.
- **Problem:** Debug logs showed that even with unified collection, some sections (like Doors) were still winning over Jumps (like Tilemaps) when sizes were equal or when processed in certain orders.
- **Fixes Implemented:** Enhanced prioritization in `BinaryParser.write` to explicitly prefer `jump_array` blocks over `sections` when they share the same offset and size. This ensures that the more specific relational definition is used to serialize the data.

### [2026-04-01] Fidelity Mismatches (Read Extent Collision)
- **Status:** Troubleshooting.
- **Problem:** `_max_read_pos` was being clobbered in `_read_section` after `JumpArray.read()` returned to its original position, leading to incorrect `trailing_data` capture.
- **Fixes Implemented:** 
    - Modified `_read_section` to skip `_max_read_pos` updates for jumped field types.
    - Added `TRACE` logging to `BinaryParser.write` to monitor field-level serialization at specific offsets ($0xAE$, $0x62E$).

### [2026-04-01] Fidelity Mismatches (Physical Write Drift)
- **Status:** Resolved.
- **Problem:** `TRACE` logs confirmed correct bytes were being written to `0xAE`, but the final file showed zeros. 
- **Analysis:** The writer was using relative padding based on `writer.tell()`. Any internal size discrepancy in previous sections caused the writer to be "ahead" or "behind," causing blocks to be written at shifted offsets while leaving the original space zeroed.
- **Fixes Implemented:** 
    - Modified `BinaryParser.write` to explicitly `seek()` to the target offset for every block in fidelity mode.
    - Refactored candidate selection into a unified, sorted pass to ensure the "highest quality" candidate (data-bearing jump blocks) always claims shared offsets.
---
### [2026-04-02] Successful Architecture Overhaul
- **Status:** RESOLVED.
- **Core Finding (The 10-Byte Tilemap):** The primary cause of "mystery data" and offset drift was the IESDP stating `tilemap` entries are 8 bytes. NearInfinity and binary analysis confirmed they are **10 bytes** (incorporating `secondary_tile_index`, `animation_speed`, and an `unknown` word).
- **Structural Findings:**
    - **Flat Global Pools:** WED files are essentially a sequence of flat, contiguous arrays. There is no physical nesting; `overlays` and `doors` simply store indices and offsets into global sections (`tilemaps`, `vertices`, `polygons`).
    - **Verified Order:** Header -> Overlays -> Secondary Header -> Doors -> Tilemaps -> Door Tile Cell Indices -> Tile Index Lookup -> Wall Groups -> Polygons -> Polygon Index Lookup -> Vertices.

- **Major Engine Changes:**
    1. **`Section` Class Upgrades:** Added `promote`, `count_expr`, `offset_from`, and `offset_update` attributes.
    2. **`Computed` Field Type:** A virtual field (`size: 0`) that evaluates an arithmetic expression (using a safe AST evaluator) against the current entry's context.
    3. **`WordScalarArray`:** A dedicated type for flat word-lists used in lookup tables.
    4. **Aggregation Logic:** `BinaryParser` now supports `sum` and `ceil_product` across sections to resolve counts for lookup tables.
    5. **Relational Writing:** The writer now performs **Pointer Recomputation**. After placing the `tilemaps` section, it iterates through all `overlays` and updates their `offset_to_tilemap` pointers based on a cumulative `stride_expr`. This allows the tool to handle modifications where overlays are resized or data is inserted.

- **Fidelity Status:** `AR4101` and `AR6009` now pass 100% round-trip fidelity tests.

---
### [2026-04-01] Session Post-Mortem (Legacy - For Context)
- **Status:** FAILED. (Note: This session's attempt to use "JumpArrays" was abandoned in favor of the [2026-04-02] overhaul).
- **Final Conclusion:** The current `BinaryParser` architecture is too linear to handle the WED format's shared relational offsets.

### Detailed Analysis
1.  **The Authority Crisis (Shared Offsets):** The WED format utilizes aggressive deduplication. For example, an empty `doors` section and a non-empty `tilemap` may share offset `0xAC`. The linear writer architecture struggled to resolve "ownership" of these bytes, leading to "Selection Wars" where empty placeholders often clobbered valid data during serialization.

2.  **Cursor Drift & Relative Padding:** We relied on relative padding (`target_offset - tell()`) to maintain fidelity. However, even a single-byte discrepancy in schema measurement caused a cascade effect, shifting every subsequent block. While switching to explicit `seek()` operations fixed placement, it failed to resolve the underlying conflict between structured data and the "unmapped" bytes the parser didn't understand.

3.  **Extent Tracking Fragility:** The relationship between `JumpArray` (relational jumps) and the linear parser was never fully synchronized. Because jumped reads return the cursor to its original position, our "furthest point" tracking (`_max_read_pos`) was consistently clobbered. This resulted in structured data being swept into `trailing_data` and duplicated at the end of the file while being zeroed out in the original location.

4.  **The Logic-Driven Gap:** WED often contains "Identity Tables"—physical lookup tables that exist in the file even when logical counts (like `count_of_unique_tiles`) are 0. Because our parser is driven by the logical model, it cannot preserve bytes it is told to ignore. Without a "Physical Claim" system that tracks every byte touched, 100% fidelity on these optimized files remains impossible.

### Next Steps
- **Byte-Mapping Architecture:** Investigate a rewrite of the `BinaryParser` that maintains a bit-map of the file. Every read operation (linear or jumped) would "claim" physical byte ranges. The `trailing_data` would then be derived from the "unclaimed" gaps rather than a simple tail-extent calculation.
- **Deduplication Awareness:** The writer needs a registry that understands that multiple logical objects can point to the same physical memory range, treating them as a single write-target.

## Verification Criteria
- [FAILED] `test_suite.py --test 2 --schema WED` passes on all games.
- [SUCCESS] `Resource.to_dict()` shows Tilemaps nested inside their respective Overlays.
- [SUCCESS] `Resource.to_dict()` shows Door Tile Cell Indices as a readable list of integers (Words).

## Reference: Relational Structure of WED V1.3
```text
Header
└── Overlays (Array)
    ├── Tilemap (Jumped via offset_to_tilemap, size=W*H)
    └── Tile Index Lookup (Jumped via offset_to_tile_index_lookup)
Secondary Header (Promoted to Context)
├── Polygons
├── Vertices
└── Wall Groups
```