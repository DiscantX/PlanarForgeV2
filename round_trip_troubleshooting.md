# Round-Trip Test Troubleshooting Log

## Date: March 17, 2026

### Initial Brainstorming and Error Classification

Based on the nature of Infinity Engine file formats (specifically `ITM` and `SPL`), here is a classification of the error types we are likely encountering during the round-trip tests:

#### 1. Bitmask Fidelity Loss (Data Loss)
*   **The Mechanism:** The `Bitmask` field type in `core/field_types.py` converts the integer value from the file into a Python dictionary (`{ 'flag_name': True, ... }`) based on the flags defined in the schema.
*   **The Error:** Any bits set in the original file that are **not** defined in the schema's `flags` attribute are discarded during the `read` operation. When `write` reconstructs the integer, those undefined bits remain `0`.
*   **Impact:** Checksum mismatch. While the game might ignore these "garbage" bits, we fail the fidelity test.

#### 2. Orphaned Data Loss (Critical ITM/SPL Logic Error)
*   **The Mechanism:** In `ITM` and `SPL` files, "Feature Blocks" (Effects) are referenced in two places:
    1.  **Global/Equipping Effects:** Referenced by the main Header (`Offset` and `Count`).
    2.  **Ability Effects:** Referenced by *Extended Headers* (Abilities) via an `Index` and `Count`.
*   **The Error:** If the Schema only defines a "Feature Blocks" section based on the Header's count (Global Effects), the parser will read the Header, the Abilities, and the Global Effects. It will **completely ignore** the Ability Effects because they are stored outside the range of the Global Effects count.
*   **Impact:** Massive file truncation. The saved file will lack all effects associated with abilities (spells, weapon hits). This is a functional corruption, not just a binary mismatch.

#### 3. Binary Repacking & Offset Shifts (False Positives)
*   **The Mechanism:** `BinaryParser.write` strictly calculates new offsets for every section, packing them tightly one after another (`current_offset += entry_size * count`).
*   **The Error:** Original IE files often contain:
    *   "Dead" data gaps between sections.
    *   Sections in arbitrary orders (e.g., Effects appearing before Abilities).
    *   Garbage data at the end of the file.
*   **Impact:** The saved file is semantically correct (valid game data) and "cleaner" than the original, but the MD5 hash differs because the bytes are at different offsets or the file size is smaller. This is a "fidelity" failure but not necessarily a "functional" failure.

#### 4. Padding Byte Mismatch
*   **The Mechanism:** `CharArray` and fixed-size string writers usually pad with null bytes (`\x00`).
*   **The Error:** Original files (especially from older tools) might contain random memory garbage in the padding space of fixed-width strings (e.g., a 32-byte resource name where only 8 bytes are used, and the remaining 24 bytes are noise).
*   **Impact:** Checksum mismatch.

#### 5. Stale Header Data
*   **The Mechanism:** The parser updates offset fields in the header during `write`.
*   **The Error:** Original files often contain "stale" offsets for empty sections (e.g., an offset pointing to `0x700` even though the count is `0`).
*   **Impact:** Our parser might zero this out or point it to the end of the file. The difference triggers a hash mismatch.

### Clarification on Round-Trip Testing and Garbage Data

The primary purpose of our round-trip testing is to verify that our read/write operations can produce valid game files without any data loss when no modifications are made. This implies that, for an unmodified file, any "garbage data" (bits not explicitly defined in our schema but present in the original file) should ideally be preserved and written back to maintain exact binary fidelity.

However, this strict requirement for binary fidelity (including garbage data) is only relevant for the initial round-trip test of an *unmodified* file. Once a file has been loaded, modified (e.g., adding or removing extended headers, which inherently changes offset pointers and potentially introduces new data or removes old data), and then saved, the expectation of byte-for-byte identical output to the original input is no longer valid. In such modification scenarios, the system should produce a *semantically correct and valid* game file, even if its binary representation differs significantly from the original due to repacking, offset changes, or the removal of irrelevant "garbage" data.

The key decision point is *when* to preserve garbage data. For a pure read-then-write operation without any intermediate model manipulation, we should strive for maximum fidelity. For any operation that involves modifying the in-memory representation, the focus shifts to producing a clean, valid output according to the schema, rather than replicating original file quirks.

### Proposed Strategy

To fix these issues, we should prioritize them in this order:

1.  **Orphaned Data Loss:** This breaks the file functionally and is the most critical to address first.
2.  **Bitmask Fidelity:** This loses potentially relevant flags (even if unknown to us) and directly impacts the integrity of the data we are trying to represent.
3.  **Repacking/Padding/Stale Header Data:** These are mostly harmless in terms of game functionality but prevent us from verifying the correctness of the other two. Addressing these will allow our fidelity tests to pass for semantically identical files, making it easier to detect true data loss.

We will start by addressing **Bitmask Fidelity** as it requires a targeted fix in `field_types.py` and directly relates to data integrity.

### 2026-03-17: Bitmask Fidelity Fix

**Problem:** `Bitmask` fields drop bits not defined in the schema, causing checksum mismatches on round-trip.
**Solution:**
*   Modify `Bitmask.read` to calculate `unknown_bits = value & ~known_mask`.
*   Store these bits in the result dictionary under the reserved key `_unknown`.
*   Modify `Bitmask.write` to look for `_unknown` and merge it back into the integer to be written.
**Architecture Note:** This adds a reserved key `_unknown` to the dictionary representation of Bitmasks.

### 2026-03-17: Orphaned Data Loss (Feature Blocks)

**Problem:**
1.  **Read Under-counting:** The `feature_blocks` section is typically linked to `global_effect_count`. The parser reads only global effects, ignoring effects referenced by abilities (Extended Headers).
2.  **Write Corruption:** If we link `feature_blocks` to `global_effect_count`, the writer updates the header with the *total* count, effectively promoting all ability effects to global effects.

**Proposed Solution:**
1.  **Decouple Count:** In the Schema, `feature_blocks` should **not** reference `global_effect_count` as its `count_field`.
2.  **Dynamic Read Count:** Modify `BinaryParser.read` to use a `_determine_section_count` helper.
    *   For `feature_blocks`, calculate the count by scanning `extended_headers` for the highest referenced index (`index + count`) and comparing it with `global_effect_count`.
    *   Read the maximum of these values.
3.  **Selective Write Update:** Modify `BinaryParser.write`.
    *   If a section does *not* have a `count_field` defined in the schema, do not attempt to update a field in `resource.values`.
    *   This allows us to write all blocks in the list while leaving `global_effect_count` (which tracks only the first N blocks) untouched.

**Action Items:**
*   Modify `BinaryParser` to support `_determine_section_count`.
*   Implement the logic to scan `extended_headers`.
*   Ensure `write` respects sections without `count_field`.

### 2026-03-17: Orphaned Data Loss (Correction)

**Problem:** The initial fix was insufficient. A deeper architectural flaw was discovered.
1.  **`resource.values` Pollution:** The `BinaryParser._read_section` method was writing the fields of *every* section entry into the `resource.values` dictionary. This dictionary is intended to hold only the global header values (like offsets and primary counts).
2.  **Symptom:** When the parser read the `extended_headers` (abilities), it overwrote the header's `count_of_equipping_feature_blocks` with the ability's `count_of_feature_blocks`. This corrupted the input for the `_determine_section_count` logic, causing it to still under-count the total effects.

**Solution:**
1.  **Isolate `resource.values` Population:** Modify `BinaryParser.read` to explicitly populate `resource.values` *only* from the header data, immediately after the header is parsed.
2.  **Clean `_read_section`:** Remove the line `resource.values[field.name] = value` from `_read_section`. This method's only job should be to return a dictionary of the fields for the current entry being read.

**Action Items:**
*   Refactor `BinaryParser.read` to handle header parsing and `resource.values` population separately.
*   Clean up `_read_section` to remove the side effect of modifying `resource.values`.

### 2026-03-17: Orphaned Data Loss (Final Correction)

**Problem:** The previous fixes were necessary prerequisites but did not solve the issue. The hash remained identical, indicating the read data was still truncated. The root cause was a logical flaw in `_determine_section_count`.
1.  **Incorrect Base Count:** After decoupling `feature_blocks` from a `count_field` in the schema, the function defaulted to an initial count of `1` instead of using the global effect count from the header (`count_of_equipping_feature_blocks`).
2.  **Symptom:** The calculation to find the total number of effects was `max(1, needed_by_abilities...)` instead of the correct `max(global_effects_count, needed_by_abilities...)`. This continued to result in an under-read of the `feature_blocks` section.

**Solution:**
1.  **Refactor `_determine_section_count`:** Create a dedicated logic path for `feature_blocks`.
2.  **Correct Initialization:** Inside this new path, explicitly fetch the `count_of_equipping_feature_blocks` from `resource.values` to use as the starting value for the `max()` calculation. This ensures the baseline for global effects is always respected.

### 2026-03-17: Bitfield Fidelity Fix

**Problem:** Similar to `Bitmask`, the `Bitfield` class was discarding any bits from the source integer that were not explicitly defined by a field in the schema.
**Solution:**
*   Modify `Bitfield.read` to calculate a `known_mask` of all defined bitfields.
*   Calculate `unknown_bits = value & ~known_mask` and store this remainder in the result dictionary under the reserved key `_unknown`.
*   Modify `Bitfield.write` to look for the `_unknown` key and merge its value back into the final integer before writing.

### 2026-03-17: Orphaned Data Loss (Root Cause Identified)

**Problem:** Diagnostic logging revealed that the special logic to calculate the total `feature_block` count was never being executed.
1.  **Typo in Section Name:** The parser code was checking for section names `feature_blocks` and `extended_headers` (plural).
2.  **Actual Schema Names:** The schema defines these sections as `feature_block` and `extended_header` (singular).

**Solution:** Correct the typos in `core/binary/parser.py` to use the singular section names, ensuring the special count calculation logic is correctly triggered.

### 2026-03-17: Orphaned Data Loss (Resolved)

**Status:** **FIXED**
**Verification:** The fidelity test for `SW2H10` (a complex item with both global and ability-based effects) now passes. The `MD5` hashes match, indicating that all 16 feature blocks are being correctly read and written back to the file.
**Note:** This fix involved hardcoding specific logic for `feature_block` sections into the `BinaryParser`. While slightly coupled, this is necessary to handle the unique "max extent" logic of IE formats without over-complicating the schema system.

### 2026-03-17: Binary Repacking & Offset Shifts

**Problem:** `BinaryParser.write` was always repacking the file tightly. This meant that valid files with gaps (alignment padding) or sections in non-standard orders would result in a different binary layout, causing MD5 mismatches even if the data was semantically identical.
**Solution:**
*   Modified `BinaryParser.write` to check `resource.modified`.
*   If `False` (unmodified), the writer now sorts sections based on their original offsets found in `resource.values` and writes them in that physical order.
*   The writer inserts `\x00` padding to align sections with their original offsets.
**Status:** Implemented. Verification needed via test suite run.
```
<!--
[PROMPT_SUGGESTION]Let's start by addressing the Bitmask Fidelity Loss. How can we modify the `Bitmask` class in `core/field_types.py` to preserve unknown bits during the read and write operations?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Can you provide a more detailed explanation of the "Orphaned Data Loss" problem, specifically how it relates to ITM/SPL schemas and how we might identify these orphaned sections in the schema definition?[/PROMPT_SUGGESTION]
