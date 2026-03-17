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
```
<!--
[PROMPT_SUGGESTION]Let's start by addressing the Bitmask Fidelity Loss. How can we modify the `Bitmask` class in `core/field_types.py` to preserve unknown bits during the read and write operations?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Can you provide a more detailed explanation of the "Orphaned Data Loss" problem, specifically how it relates to ITM/SPL schemas and how we might identify these orphaned sections in the schema definition?[/PROMPT_SUGGESTION]
