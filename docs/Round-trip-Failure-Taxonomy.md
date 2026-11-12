# Round-trip Failure Taxonomy

A round-trip test reads a game resource, writes it back without modification, and compares the result byte for byte with the original (see [Round-trip Fidelity](Round-trip-Fidelity.md)). When the comparison fails, the cause is almost always one of a small number of kinds. This article classifies those kinds, gives the symptom by which each is recognised, and records how the project resolved the first instance of each.

The classification was assembled retrospectively from the [Fidelity Fixes engineering log](archive/Engineering-Log-Fidelity-Fixes.md) (March to April 2026). Entries from that log are cited by date and title.

## Reading a failure

A mismatch has a *location* (the first differing offset) and a *shape* (what the two bytes look like). Both are informative:

| Observation | Likely class |
|-------------|--------------|
| Saved file shorter than the original | [Unmapped data](#3-unmapped-or-unreferenced-data) |
| First byte already differs, and it is a different file signature (for example `S` against `I`) | [Wrong input](#6-wrong-input-loader-and-test-harness-errors) |
| Everything after some offset is shifted | [Schema size error](#4-schema-definition-errors) or [layout change](#2-layout-changes-on-write) |
| A single field differs, saved value is a default or zero | [Field loss](#1-field-level-information-loss) or a duplicate name |
| Saved bytes are `0x00` where the original has `0xFF` | [Padding typed as a scalar](#5-padding-and-unused-regions) |

## 1. Field-level information loss

The parser decodes a value into a friendlier form, and the friendlier form cannot represent every original bit pattern.

**Bitmasks and bitfields.** A `Bitmask` turns an integer into a dictionary of named flags. Bits that the schema does not name were discarded on read, so the written integer differed. The fix keeps the remainder, `value & ~known_mask`, under a reserved `_unknown` key and merges it back on write (2026-03-17, *Bitmask Fidelity Fix* and *Bitfield Fidelity Fix*; implemented in `core/field_types.py`). The consequence for schema authors is that `_unknown` is a reserved key in every bitmask dictionary.

**Enumerations with duplicate labels.** An enumeration is written by looking up the label, so two values that share a label are indistinguishable on write. In IWD2 item `00GENIR`, `item_type` `0x47` and `0x0D` both carried the label `Food`, and `0x47` was written back as `0x0D` (2026-04-03, *IWD2 ITM Single-Byte Fidelity Mismatch*). The fix was to make labels unique (`Food (IWD2)`). Labels must be unique within an enumeration.

**Display-only transformation.** Sanitising a value for display must not alter what is stored. `ResRef` fields keep the full latin-1 string including bytes after the first null, and a `str` subclass shows only the text before the null (2026-03-17, *ResRef Display Sanitization*).

## 2. Layout changes on write

The writer originally "repacked" every file tightly, in schema order. Real files contain alignment gaps and sections in non-standard order, so semantically identical data produced a different binary and a different checksum.

For an unmodified resource, the writer now sorts sections by their original offsets and pads with zero bytes to reproduce the original layout. For a modified resource it repacks (2026-03-17, *Binary Repacking & Offset Shifts*).

This reflects a distinction the project holds deliberately. Byte identity is required only for an *unmodified* file. Once the in-memory model is edited, offsets legitimately change and the goal becomes a valid, schema-correct file, not a copy of the original's quirks (log, *Clarification on Round-Trip Testing and Garbage Data*).

## 3. Unmapped or unreferenced data

The parser is logic-driven: it reads what the header and the structures reference. Data that exists in the file but is not reached by that logic is dropped.

**Shared blocks.** In ITM and SPL, feature blocks (effects) are referenced both by the header and by each ability. A section sized only from the header's count ignores the effects the abilities own, truncating the file severely. The fix was to derive the true extent by scanning all abilities (2026-03-17, *Orphaned Data Loss*, whose entries record two corrections before the root cause was settled).

**Unreferenced "zombie" data.** `PTION41.ITM` in BGEE physically holds 10 feature blocks but is referenced by only 8, leaving 96 bytes that nothing points at. These are valid structures the game never uses. A heuristic reads any surplus blocks at the end of the file so that an unmodified round trip preserves them (2026-03-17, *Unreferenced "Zombie" Data*). Later entries generalise this to automatic tail preservation and an audit of every byte range the schema does not map.

These patterns are treated in detail in [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md). The audit is covered in [Unknown Bytes and the Gap Audit](Unknown-Bytes-and-the-Gap-Audit.md).

## 4. Schema definition errors

When the YAML does not describe the binary accurately, no amount of parser correctness helps.

**Wrong schema selected.** PSTEE items were assigned to the original PST schema (`ITM V1.1`, 154-byte header). The Enhanced Edition uses a V1-style 114-byte header, so the parser consumed 40 bytes of the first extended header as header fields. The fix was a dedicated `itm_pstee.yaml` (2026-03-18, *PSTEE Fidelity Errors*). For the structure of the formats themselves, see [Format Notes](Format-Notes.md) and the item format at [IESDP](https://iesdp.bgforge.net/).

**Duplicate field names.** Fields in a section are stored in a map keyed by name, so two fields with one name overwrite each other on read, and the surviving value is written to both offsets. IWD2 items had four `kit_usability` fields and two `attack_type` fields, producing a stray `0x00` at offset `0x82` (2026-03-18, *IWD2 Fidelity Errors Resolved*). Names were made unique. The log's own recommendation, not yet implemented as far as this article can verify, is that the schema loader should reject duplicate names automatically.

**Wrongly sized fields.** In ARE, several 2-byte values were declared as `dword`, so they consumed neighbouring bytes (2026-03-31, *ARE Field Type and Padding Fidelity*).

## 5. Padding and unused regions

Padding in original files is not reliably zero; it often holds `0xFF` or leftover memory. A fixed-length string writer pads with zeros, which changes such bytes. For large unused blocks, declaring a scalar type with a large `size` caused the parser to read zeros instead of the true contents. Declaring them as the `bytes` type preserves the raw values (2026-03-31, *ARE Field Type and Padding Fidelity*). The `bytes` type itself was introduced for a 16-byte unknown field in the IWD2 item header (2026-03-18, *IWD2 Crash (Unknown Padding)*).

## 6. Wrong input: loader and test-harness errors

Some failures are not in the parser at all.

**Name collisions.** `CHITIN.KEY` allows several resources with the same name and different types (`CARRIO.ITM`, `CARRIO.CRE`). The loader kept one entry per name, so a request for an item could return the creature's bytes, and the item parser then read the creature's signature as counts and offsets, producing crashes and nonsense. The map became `Dict[str, List[Entry]]` with a `restype` filter threaded through `load` and `get_raw_bytes` (2026-03-17, *Resource Loader Name Collision*).

**The same bug in the test.** After the loader was fixed, many tests still failed at the first byte because the test harness fetched the original bytes without a `restype`, comparing a saved item against a store or spell of the same name. Passing `restype=schema_name` removed most of the remaining failures (2026-03-17, *Test Suite False Negatives*).

The practical lesson is to suspect the inputs first when the failure is at byte zero or involves a wrong signature. Lessons of this kind are collected in the planned debugging-lessons article.

## Recommended order of investigation

1. Confirm the compared bytes are the right resource (signature, `restype`).
2. Confirm the right schema version was selected for the game.
3. Look for duplicate field and enumeration-label names.
4. Check field sizes against the format specification for cumulative offset drift.
5. Look for data the parser never reaches (shorter saved file).
6. Only then suspect layout, padding or the writer.

## Discrepancies noticed while writing

The archived log and the current repository disagree in two places. The maintainer's ruling is that **the repository is correct and the log is outdated**; the log is kept as a historical record only.

- The 2026-03-18 entry says the duplicate `itm_v2_0.yaml` was deleted and `itm_v2.yaml` kept. The repository contains `itm_v2_0.yaml` and no `itm_v2.yaml`.
- That entry says the renamed fields became `kit_usability_1` and `attack_type_special`. The current schema uses `kit_usability`, `kit_usability_2` to `_4`, and `attack_type`, `attack_type_2`.

Two points are flagged for verification when active development resumes: whether the schema loader really rejects duplicate field names (the log recommends it, and this article could not confirm it exists), and whether other log statements about schema file names still hold.

## See also

- [Round-trip Fidelity](Round-trip-Fidelity.md)
- [Field Types Reference](Field-Types-Reference.md)
- [Relational Logic in WED](Relational-Logic-in-WED.md)
- [Archived Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md)
