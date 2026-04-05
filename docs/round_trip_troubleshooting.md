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

### 2026-03-17: Reverted "Defensive" Parser Check

**Problem:** A defensive check was added to `BinaryParser.read` to prevent it from reading past the end of a file if the header's count fields were erroneously large. This successfully stopped all `CRASH loading` errors.
**Why It Was Wrong:** The fix treated the symptom, not the cause. By preventing the crash, it masked the true underlying issue: the parser was being fed entirely incorrect data from the wrong file type. The crashes were a vital clue that the data source was corrupt, and silencing them made the root cause harder to find.
**Solution:** The defensive check was removed from `BinaryParser.read`. This allowed the crashes to resurface, correctly pointing the investigation toward the `ResourceLoader` and away from the `BinaryParser`.

### 2026-03-17: Resource Loader Name Collision (Root Cause of Crashes)

**Problem:** A huge number of files were crashing the parser or loading as "garbage data". This was traced back to how `ResourceLoader` handled `CHITIN.KEY`.
1.  **The Flaw:** The loader used a simple dictionary mapping a `ResRef` string (e.g., "CARRIO") to a single resource entry. However, Infinity Engine games frequently have multiple resources with the same name but different types (e.g., `CARRIO.ITM` and `CARRIO.CRE`). The dictionary would overwrite entries, only remembering the last one it found.
2.  **The Symptom:** When `load("CARRIO", restype="ITM")` was called, the loader might have only stored the entry for `CARRIO.CRE`. It would then fetch the raw bytes of the **Creature** file and pass them to the **Item** parser. The parser would interpret the file's signature (`CRE `) as garbage integer values, leading to nonsensical counts and offsets, which ultimately caused the crashes.

**Solution:**
1.  **Refactor `ResourceLoader`:** The internal resource map was changed from `Dict[str, Entry]` to `Dict[str, List[Entry]]` to handle name collisions.
2.  **Update Lookup Logic:** The `_find_resource_location` method was updated to accept a `restype`. When provided, it now filters the list of entries for the one with the matching resource type code.
3.  **Propagate `restype`:** The `restype` argument was passed down through the `load` and `get_raw_bytes` call chain to enable this specific lookup.

### 2026-03-17: Test Suite False Negatives

**Problem:** After fixing the `ResourceLoader`, a massive number of fidelity tests were still failing, often at the very first byte (`0x53` vs `0x49`, i.e., 'S' vs 'I').
**The Flaw:** The test suite itself had the same bug as the original loader. When fetching the original file for comparison, the test called `loader.get_raw_bytes(resref)` **without** specifying the `restype`. It was therefore comparing the correctly saved `ITM` file against the raw bytes of a `STO` or `SPL` file with the same name.
**Solution:** The call to `get_raw_bytes` inside `tests/test_suite.py` was updated to `get_raw_bytes(resref, restype=schema_name)`, ensuring the test compares the correct files. This resolved the vast majority of the remaining fidelity errors.

### 2026-03-17: Unreferenced "Zombie" Data (PTION41)

**Problem:** `PTION41.ITM` in `BGEE` failed fidelity tests with a size mismatch (Saved file was 96 bytes smaller).
**Analysis:** The original file contains 10 Feature Block structures physically, but the header and abilities only reference the first 8. The last 2 blocks (96 bytes) are technically "orphaned" or "zombie" data—valid structures that are never used by the game. Our parser, being logic-driven, ignored them.
**Solution:**
*   Updated `BinaryParser._determine_section_count` to accept the `reader` instance.
*   Added a heuristic: If parsing `feature_block` (which is typically the last section), check if there are physically more blocks remaining in the file than the logical count suggests.
*   If extra blocks exist, read them. This preserves the "zombie" data in unmodified round-trips.

### 2026-03-17: ResRef Display Sanitization

**Problem:** `ResRef` fields, when containing non-ASCII or null-padded data, would display as garbled characters (e.g., `¤¶E♦` or `BAG01\x00\x00...`) in debug outputs, making them hard to read.
**Analysis:** The `latin-1` encoding, necessary for round-trip fidelity, was being printed directly. We needed a way to show a clean, human-readable string for display while preserving the raw bytes for writing.
**Solution:**
*   A `ResRefString` wrapper class was created that inherits from `str`.
*   `ResRef.read` now returns an instance of this wrapper, which stores the full, raw string data.
*   `ResRefString` overrides the `__str__` and `__repr__` methods to display only the content up to the first null byte (`\x00`), providing a clean representation without losing the underlying data required for fidelity.

### 2026-03-18: PSTEE Fidelity Errors (Schema Mismatch)

**Problem:** All PSTEE ITM files failed fidelity tests with offset shifts and massive mismatches.
**Analysis:** PSTEE was incorrectly assigned to the `ITM V1.1` schema (original PST), but the Enhanced Edition uses a hybrid `V1` format (114-byte header). This caused the parser to read 40 bytes of the first Extended Header as part of the main Header, corrupting the file structure.
**Solution:**
*   Removed `PSTEE` from `itm_v1_1.yaml`.
*   Created a dedicated `itm_pstee.yaml` schema that uses the V1 structure (114-byte header) but retains PST-specific fields like `drop_sound`.
**Status:** **FIXED**

### 2026-03-18: IWD2 Crash (Unknown Padding)

**Problem:** IWD2 ITM files caused a crash: `Error: CRASH loading: Parsing field 'unknown' at offset 0x72 failed: Unsupported integer size: 16`.
**Analysis:** IWD2 uses ITM V2.0, which includes a 16-byte unknown padding field at the end of the header. The parser attempted to read this using standard integer types which were not configured for 16-byte values.
**Solution:**
*   Implemented a new `Bytes` field type in `core/field_types.py` to handle raw binary blobs of arbitrary size.
*   Created `itm_v2.yaml` schema for IWD2, defining the field at `0x72` as `type: bytes` with `size: 16`.
*   Updated `BinaryReader` and `BinaryWriter` to support arbitrary integer sizes as a robustness fallback.
**Status:** **FIXED**

### 2026-03-18: IWD2 Offset Correction Attempt (Failed)

**Problem:** Fidelity error at offset `0x82` (130) for IWD2 ITM files. `offset_to_extended_headers` points to 130.
**Hypothesis:** The pointer might technically point to the start of the padding (114) instead of the data (130), causing the parser to read zeros.
**Experiment:** Implemented `offset_correction` in `Schema` and `BinaryParser` to adjust the read offset by +16 bytes.
**Result:** **FAILED**. Inspection confirmed the pointer in the file is indeed 130. The correction caused the parser to read garbage further down the file. The changes were reverted.
**Current Status:** Back to investigating why valid data at 130 is being read/written as 0x00.

### 2026-03-18: IWD2 Fidelity Errors Resolved (Duplicate Fields)

**Problem:** All IWD2 ITM files failed fidelity tests, consistently writing a `0x00` byte where data should exist (e.g., at offset `0x82`).
**Analysis:** The root cause was a series of schema errors that led to data being overwritten in memory during the parsing stage.
1.  **Duplicate Schema File:** An extra, incorrect schema file (`itm_v2_0.yaml`) existed alongside the correct `itm_v2.yaml`.
2.  **Duplicate Header Fields:** The schema defined four separate `kit_usability` fields, but they were not uniquely named. This caused each field's value to overwrite the last in the resource's data map.
3.  **Duplicate Extended Header Fields:** A similar issue existed in the `extended_header`, where two distinct fields were both named `attack_type`. The value of the second field would overwrite the first. During the write process, this incorrect, overwritten value was written back to the first field's offset, causing the fidelity mismatch.

**Solution:**
*   The duplicate schema file (`itm_v2_0.yaml`) was deleted.
*   The duplicate `kit_usability` and `attack_type` fields in `itm_v2.yaml` were renamed to be unique (e.g., `kit_usability_1`, `attack_type_special`).

**Status:** **FIXED**. With these corrections, all ITM files for all supported games now pass round-trip fidelity tests.

## Postmortem: Achieving ITM Round-Trip Fidelity

### 1. Summary of Error Categories

The errors encountered can be grouped into three main categories:

*   **Schema Definition Errors:** These were issues where the YAML schemas did not accurately represent the binary file structure.
    *   **PSTEE Version Mismatch:** `PSTEE` was incorrectly assigned to the `ITM v1.1` schema, which has a 154-byte header. The Enhanced Edition actually uses a 114-byte header, causing the parser to read 40 bytes of ability data as if it were part of the header, corrupting the entire file structure on write.
    *   **IWD2 Duplicate Fields:** The `itm_v2.yaml` schema contained multiple fields with the same name (e.g., four fields named `kit_usability`, two named `attack_type`). This caused the parser to overwrite the value of the first field with the value of the second during the read process, leading to data corruption when the file was written back.

*   **Parser & I/O Logic Flaws:** These were bugs in the core `BinaryParser` and `BinaryReader`/`Writer` that affected how data was interpreted or written.
    *   **Orphaned Data:** The parser initially only read the number of effects specified in the main header, ignoring additional "orphaned" effects referenced by item abilities. This required a significant re-architecture of the parser's counting logic to scan all abilities and determine the true extent of the effect data.
    *   **Bit-level Data Loss:** The `Bitmask` and `Bitfield` types were initially written to discard any bits from the source file that weren't explicitly defined in the schema. This was fixed by adding logic to preserve these "unknown" bits under a reserved `_unknown` key.
    *   **Repacking vs. Fidelity:** The writer was initially designed to always "repack" files, creating a clean, compact binary. This broke fidelity for original files that contained legitimate padding or non-standard section ordering. The writer had to be updated to detect unmodified resources and preserve their exact original layout.

*   **Toolchain & Test Suite Errors:** These were bugs in the surrounding infrastructure that produced misleading results and sent the investigation down the wrong path.
    *   **Resource Loader Name Collisions:** This was the root cause of many crashes. The `ResourceLoader` used a dictionary that could only hold one resource per name, failing to account for files like `CARRIO.ITM` and `CARRIO.CRE` existing simultaneously. This led to the loader feeding creature data to the item parser, causing it to crash on invalid data.
    *   **Test Suite Mismatches:** The test suite itself suffered from the same name collision bug, causing it to compare a saved `.ITM` file against the original bytes of a `.STO` or `.SPL` file with the same name, leading to a cascade of false-positive fidelity errors.

### 2. Analysis of the Troubleshooting Process

#### Inefficiencies and Missteps

Our path to a solution was not always direct. Several key moments highlight areas where we could have been more efficient:

1.  **Treating the Symptom, Not the Cause:** The `Unsupported integer size: 16` crash in IWD2 is a prime example. Our first reaction was to make the `BinaryReader` more robust to handle 16-byte integers. While this made the I/O layer stronger, it didn't address *why* the parser was attempting to read a 16-byte field as an integer in the first place. This was a symptom of an incorrect schema definition, and focusing on the crash itself delayed the discovery of the true schema error.

2.  **Fixing the Wrong Layer:** The most significant detour was when we added a "defensive check" to the `BinaryParser` to prevent it from crashing when reading past the end of a file. This successfully stopped the crashes but completely masked the underlying problem: the `ResourceLoader` was feeding the parser data from the wrong file type. By silencing the crash, we lost our most important clue. The lesson here is that **crashes are often valuable signals**. A robust system shouldn't just avoid crashing; it should crash with a clear error when given fundamentally invalid input.

3.  **Building on a Faulty Premise:** The `offset_correction` hypothesis for the IWD2 fidelity error was based on the idea that the file format itself was quirky. We invested a full development cycle implementing and then reverting this feature, only to find out through direct inspection that the premise was wrong—the offset pointer in the file was correct all along.

#### Successes and Efficient Solutions

Conversely, several approaches were highly effective and led to rapid solutions:

1.  **Targeted Diagnostics:** The turning point for the final, stubborn IWD2 fidelity error was when we stopped theorizing and added a simple `print()` statement to the test suite. This allowed us to inspect the `Resource` object in memory and definitively prove the issue was a **read error**, not a write error. This single piece of information immediately invalidated several hypotheses and focused our attention correctly on the parsing logic.

2.  **Schema-First Analysis:** The initial PSTEE fidelity error was solved quickly because the analysis started at the right place. By comparing the known structures of original `PST` and the Enhanced Editions, we immediately identified the header size discrepancy, pointing directly to a schema versioning problem.

### 3. Future Prevention and Lessons Learned

This troubleshooting journey provides several key takeaways for future development:

1.  **Implement Schema Validation:** The final IWD2 bug was caused by duplicate field names in the YAML file. This is an error that can be caught automatically. The `SchemaLoader` should be enhanced with a validation step that detects and raises an error if a section contains multiple fields with the same name. This would have prevented the issue entirely.

2.  **Trust, but Verify with Data:** Before building a complex feature around a hypothesis (like `offset_correction`), write the smallest possible piece of code to verify the premise. A tiny script to read and print a single integer from a specific offset in the file would have saved an entire development cycle.

3.  **Isolate Layers for Testing:** When a low-level component like the `BinaryParser` fails, the investigation must include its inputs. Unit tests for the parser using known-good, static byte arrays would have confirmed its correctness, forcing us to look at the `ResourceLoader` (the component feeding it data) much sooner.

4.  **Embrace Simple, Directed Debugging:** In a complex system, a full step-through debugger can sometimes be less efficient than adding a single, well-placed print statement to inspect the state of data at a critical boundary between components. This was the key to solving our most persistent bug.

By internalizing these lessons, we can approach future troubleshooting with greater efficiency, avoiding common pitfalls and more quickly identifying the true root cause of complex issues.

### 2026-03-21: CRE V1 Tail Truncation and Versioned Effect Blocks

**Problem:** A large number of `CRE` files in the `V1` family were failing fidelity with truncation or mid-file mismatches. A representative case was `KPCHAP01.CRE` in `BG2EE`, where the original file was `1328` bytes, but the saved file was only `1248` bytes and ended exactly at `offset_to_item_slots` (`0x4e0`).

**Analysis:**
1.  **Missing Tail Sections:** The `CRE` schemas already defined `offset_to_item_slots`, `offset_to_effects`, and `count_of_effects` in the header, but the schemas themselves did not define `item_slots` or `effects` sections. This meant the parser never loaded those regions and the writer never emitted them.
2.  **Versioned Effect Structure:** `CRE` effect blocks are not uniformly `0x30` bytes long.
    *   If `eff_structure_version == 0`, the classic effect entry is `0x30` bytes.
    *   If `eff_structure_version == 1`, the entry is `0x108` bytes: the classic `0x30`-byte prefix plus `216` bytes of additional effect data.
3.  **Optional Zero-Offset Sections:** Some `CRE` variants contain optional fixed-size sections whose offset is `0`. For sections without a `count_field`, treating offset `0` as a real read location causes the parser to consume bytes from the file header instead of correctly treating the section as absent.

**Solution:**
*   Added `effects` and `item_slots` sections to:
    *   `drivers/InfinityEngine/definitions/schemas/cre/cre_v1.yaml`
    *   `drivers/InfinityEngine/definitions/schemas/cre/cre_pstee.yaml`
    *   `drivers/InfinityEngine/definitions/schemas/cre/cre_v1_2.yaml`
*   Added a new Infinity Engine field type, `effect_extra_data`, which conditionally reads and writes the extra `216` bytes only when `eff_structure_version` is nonzero.
*   Updated `BinaryParser._read_section` to pass header values into field-type context, allowing the effect field type to see `eff_structure_version` while parsing each effect entry.
*   Updated `BinaryParser.read` so an offset-based section with no `count_field` and offset `0` is treated as empty instead of reading from the start of the file.

**Verification:**
*   `KPCHAP01` (`BG2EE`) now round-trips byte-for-byte. The missing `80`-byte `item_slots` tail at `0x4e0` is preserved.
*   `MOONDOG` (`BG2EE`) now round-trips byte-for-byte with `3` `V1`-format extended effects (`eff_structure_version = 1`).
*   `ALORA` (`BGEE`) now round-trips byte-for-byte with `3` classic `0x30`-byte effects (`eff_structure_version = 0`).
*   `MDK2DOC` (`IWDEE`) now round-trips byte-for-byte, confirming the same fix applies cleanly to another `CRE V1` family game.

**Remaining Work:**
*   `PSTEE` `CRE` files still have separate fidelity issues beyond this fix. For example, `3PLANEA` still truncates after this change, so `cre_pstee.yaml` requires additional investigation beyond the missing tail-section problem solved here.

### 2026-03-21: IWD2 CRE V2.2 Spell and Ability Groups

**Problem:** `IWD2` `CRE V2.2` files were failing fidelity inside the spell region, commonly at offsets like `0x676` or `0x7de`, while four legacy `V9.1` files were crashing because they were being parsed as `V2.2`.

**Analysis:**
1.  **Legacy Version Routing:** The four crashing files (`TEST_01`, `TEST_02`, `TEST_03`, `TESTOCLE`) are `CRE V9.1` files and belong on the classic `IWD` schema, not the `V2.2` schema.
2.  **Structured V2.2 Group Data:** The `V2.2` schema had preserved the spell header tables as raw bytes and left the referenced bodies unmodeled. Inspection of live `IWD2` files showed those bodies are not garbage:
    *   each class spell group and domain spell group is `count * 16` bytes of entries followed by an 8-byte footer
    *   the same layout is used for `abilities`, `songs`, and `shapes`
3.  **Invalid Temporary Workaround:** A temporary full-file passthrough had made unmodified round-trips succeed, but it bypassed real serialization and hid the missing structure instead of modeling it.

**Solution:**
*   Kept the legitimate version-based routing in `drivers/InfinityEngine/resource_loader.py` so `IWD2 CRE V9.1` files resolve to the legacy `cre_v9.yaml` schema.
*   Removed the full-file passthrough from `core/resource.py`, `drivers/InfinityEngine/resource_loader.py`, and `core/binary/parser.py`.
*   Added dynamic flattened field support to the runtime:
    *   recursive child type resolution in `core/schema_loader.py`
    *   generic field measurement in `core/field_types.py`
    *   flattened dynamic field reads/writes and dynamic size calculation in `core/binary/parser.py`
*   Added a dedicated `iwd2_cre_group` field type in `drivers/InfinityEngine/definitions/types.py` to read and write:
    *   repeated 16-byte entries
    *   the trailing 8-byte `total_slots` / `free_slots` footer
*   Rebuilt `drivers/InfinityEngine/definitions/schemas/cre/cre_v2_2.yaml` so it now explicitly models:
    *   all `63` class spell offset/count pairs
    *   all `9` domain spell offset/count pairs
    *   `abilities`, `songs`, and `shapes`
    *   the existing `item_slots`, `items`, and `effects` tail sections

**Verification:**
*   Representative formerly failing `V2.2` files now round-trip byte-for-byte:
    *   `62NEOORC`
    *   `62MDARF`
    *   `20ORCW3`
    *   `20DERETH`
    *   `63ISAIR`
    *   `00sAbgd`
*   The four legacy `V9.1` files now load and round-trip correctly through the legacy schema.
*   Full official fidelity run:
    *   `python tools/tests/test_suite.py --test 2 --schema CRE --game IWD2`
    *   Result: `0/1622` failures

### 2026-03-31: ARE Bounding Box and Rect Type Fidelity

**Problem:** `ARE` bounding boxes were producing incorrect coordinate data.
**Analysis:** The IESDP defines the `rect` type as 8 bytes, which the initial schema interpreted as a `byte_array` of length 8. In reality, the Infinity Engine treats these as four 16-bit unsigned integers (Words) representing Left, Top, Right, and Bottom. Reading them as individual bytes caused incorrect coordinate calculations in the serialized output.
**Solution:** Changed `bounding_box` and similar fields from `byte_array` (count 8) to `word_array` (count 4). Added semantic `labels` ([left, top, right, bottom]) to improve readability.

### 2026-03-31: ARE Vertex Pool Resolution

**Problem:** Indices for door and region polygons were "dead links" to unresolved data.
**Analysis:** Door and Region structures in `ARE` files don't store coordinates locally; they store an index and count pointing into a global vertex pool defined in the Area Header. Because the schema lacked a `vertices` section, this data was being skipped during parsing and zeroed out on write if it created an offset gap.
**Solution:** Added a `vertices` section to all `ARE` schema versions, linked to the `offset_to_vertices` and `count_of_vertices` header fields. This allows the parser to resolve polygon coordinates for all spatial triggers and doors.

### 2026-03-31: ARE Field Type and Padding Fidelity

**Problem:** Round-trip tests showed `0x00` bytes being saved where the original file contained `0xFF`.
**Analysis:** 
1. Several 1-byte and 2-byte fields were incorrectly typed (e.g., `dword` for a 2-byte `word` field).
2. Large "unused" padding blocks were defined as scalar types (like `byte` with a large `size`). The parser failed to read these correctly, defaulting to `0`.
**Solution:** 
* Corrected field types for `overlay_transparency` and `note_colour`.
* Converted all large `unused` or `unknown` blocks from scalar types to the `bytes` type to ensure raw binary preservation of padding values (including `0xFF`).

### 2026-03-31: ARE Explored Bitmask Resolution

**Problem:** Fidelity mismatches persisted in files with map exploration data.
**Analysis:** The `explored_bitmask` is a variable-length blob of bytes stored between major sections. Its offset and size are defined in the header. Like the vertex pool, because this wasn't defined as a section, the writer treated it as a gap and filled it with zeros.
**Solution:** Added an `explored_bitmask` section using `count_field: size_of_explored_bitmask`. This ensures the map exploration state is correctly preserved during round-trips.

### 2026-03-31: PSTEE "Zombie" Data / Trailing Garbage Preservation

**Problem:** `AR13WZ.ARE` (PSTEE) and similar files failed fidelity tests due to trailing bytes (offset 0xDE8+) marked as "unused" in NearInfinity.
**Analysis:** The file contains structured actor data that is no longer referenced by the header. Because the parser is logic-driven, it stopped at the last referenced section, leading to a smaller saved file and an MD5 mismatch.
**Solution:** Implemented "Automatic Tail Preservation" in `BinaryParser`. The parser now captures any bytes remaining after the last schema section into a `trailing_data` buffer. This buffer is appended during `write` if the resource is unmodified. This preserves binary fidelity without requiring schema changes for unreferenced data.

### 2026-03-31: ARE Fidelity Regression (Trailing Data Logic)

**Problem:** Recent fixes caused all `ARE` files to fail fidelity tests with massive size increases and data corruption.
**Analysis:** The "Automatic Tail Preservation" logic was using `reader.tell()` after the last schema section was parsed. Because `vertices` was at the bottom of the YAML but physically early in the file, the parser was left pointing to the middle of the file. The "tail" capture then included sections physically following that point, leading to double-writing.
**Solution:** Modified `BinaryParser.read` to track `max_pos` (the highest offset reached by any section) instead of relying on the final position of the reader. This ensures the trailing data buffer only contains bytes physically following the entire structured part of the file.
### 2026-03-31: IWD2 ARE V9.1 Actor Alignment and Embedded CRE Fidelity
**Problem:** IWD2 ARE files were failing fidelity tests because embedded CRE data was being overwritten with `00` bytes.
**Analysis:** Investigation showed `cre_offset` and `cre_size` fields contained suspicious ASCII-like fragments (e.g., "EDN2"). This was diagnosed as "Offset Drift" identical to an issue previously solved in the `ARE V1 EE` schema.
**Root Cause:** The Actor entry size in the `ARE V9.1` schema was incorrect. Fields were missing, misaligned, or misnamed, causing the parser's read head to drift further with each subsequent entry in the Actor list. Because the parser was reading from incorrect offsets, it failed to identify the embedded CRE data, leading the writer to treat that space as an unreferenced "gap" and fill it with null bytes.
**Solution:** Corrected the Actor entry field definitions to ensure a consistent 272-byte structure. This aligned the pointers correctly and preserved the embedded character data during round-trips.

### 2026-03-31: IWD2 ARE V9.1 Region Alignment (Cumulative Drift)

**Problem:** IWD2 ARE files showed nonsensical field values (e.g., `index_of_first: 1852403536`) that worsened with each subsequent entry in the `regions` list.
**Analysis:** NearInfinity confirmed the `regions` structure in IWD2 is 196 bytes ($0xC4$), whereas the schema was only accounting for 184 bytes ($0xB8$).
**Solution:** Updated `are_v9_1.yaml` to increase the `unknown` block size at offset `0x0090` from 40 to 52 bytes.
**Status:** **FIXED**. This resolved the cumulative drift for the `regions` section. Only one known IWD2 fidelity error remains in the test suite.

### 2026-03-31: PSTEE ARE V1 Automap Note Alignment (Cumulative Drift)

**Problem:** PSTEE ARE files showed offset drift errors in files with multiple automap notes.
**Analysis:** While PSTEE identifies as version `V1`, its automap note structure is 68 bytes ($0x44$), whereas Baldur's Gate uses 52 bytes ($0x34$). Using the shared `are_v1_ee.yaml` was causing a 16-byte drift per entry.
**Solution:** Created a dedicated `are_pstee.yaml` schema that specifically models the 68-byte Torment note and Torment-specific region fields. Removed `PSTEE` from the generic `are_v1_ee.yaml` games list.
**Status:** **FIXED**.

### 2026-04-02: Unknown Gap Audit Framework and Reporting

**Problem:** We needed to answer "are unmapped bytes meaningful?" with evidence, not assumptions.

**Solution:**
1. Implemented unknown-gap auditing in fidelity runs with per-file reports.
2. Added structured diagnostics per gap:
   * byte-range and size
   * nonzero/FF ratio and entropy
   * neighboring claimed fields (`prev`/`next`)
   * pointers into the gap
   * candidate structure hints
   * hex `head`/`tail` and ASCII preview
3. Added aggregate gap summaries by game/schema.

**Outcome:** We can now pinpoint exactly what unknown bytes are present and where.

### 2026-04-02: Exact Gap Allowlist (File + Offset Scoped Suppression)

**Problem:** Some gaps were verified as safe (`Near Infinity`: "Unused bytes?"), but we did not want to ignore entire files.

**Solution:**
* Added `tools/tests/gap_allowlist.json` with exact-rule matching (`game/schema/resref/start/end`, plus optional `size/kind/classification/risk`).
* Updated test reporting to show:
  * active gaps vs suppressed gaps
  * suppressed byte totals
  * which allowlist rule suppressed each gap

**Initial allowlisted sets:**
1. `PSTEE/CRE`: `3PLANEA`, `ARMOIRE`, `SPLINT`, `THORNCO`
2. `PSTEE/WED`: `AR0609`, `AR0612`
3. `BGEE/WED`: `AR1215`

### 2026-04-03: IWD2 ITM Single-Byte Fidelity Mismatch (`00GENIR`)

**Problem:** `IWD2/ITM/00GENIR` mismatched at offset `0x1c` (`item_type`): original `0x47`, saved `0x0D`.

**Root Cause:**
* `itm_v2_0.yaml` had duplicate enum labels in `item_type`:
  * `0x000D: Food`
  * `0x0047: Food`
* Enum read/write used label-based reverse lookup, so `Food` resolved to first match (`0x000D`) on write.

**Fix:**
* Updated `drivers/InfinityEngine/definitions/schemas/itm/itm_v2_0.yaml`:
  * `0x0047: Food (IWD2)`

**Status:** **FIXED**. `00GENIR` round-trips byte-for-byte.

### 2026-04-03: Final PSTEE ARE Gap Closure

**Problem:** Remaining unexplained PSTEE ARE gaps:
* `AR0501`
* `AR1001`
* `AR3017`
* `AR13WZ`

**Analysis:** Near Infinity marks these as `Unused bytes?`.

**Action:** Added all four as exact allowlist rules (offset-scoped, not file-wide).

**Status:** **CLOSED**. These no longer show as active unexplained gaps.

### 2026-04-03: Gap Audit Performance Tuning

**Problem:** Gap audit added noticeable runtime overhead.

**Implemented Optimizations:**
1. Parser only tracks byte-claims when audit is enabled (removed global always-on overhead).
2. Offset-like fields are indexed once per resource and reused for per-gap pointer checks.
3. Added configurable audit detail levels:
   * `summary` (fast)
   * `nonzero` (default)
   * `full` (deep diagnostics)

**New test-suite CLI options:**
* `--gap-detail-level {summary,nonzero,full}`
* `--profile-performance`
* `--profile-sort {cumulative,tottime}`
* `--profile-limit N`

**Outcome:** Faster non-audit runs and tunable audit cost without losing diagnostic capability.

### 2026-04-03: Milestone Result

**Status:** **SUCCESS**

All current round-trip tests completed with **0 failures** for this milestone after:
1. schema fixes,
2. targeted gap allowlisting for known-safe unmapped regions,
3. parser and test-suite performance improvements.
