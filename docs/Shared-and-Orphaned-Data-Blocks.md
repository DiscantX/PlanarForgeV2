# Shared and Orphaned Data Blocks

Infinity Engine files are not simple sequences of self-contained records. Many structures are stored in one pool and referenced by index from several other places, and some structures are stored but referenced by nothing. A parser that discovers data only by following the references it knows about will silently drop the rest. This article describes the recurring patterns, how they showed up as round-trip failures (see [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)), and the mechanism the project uses for each.

The material is drawn from the [Fidelity Fixes engineering log](archive/Engineering-Log-Fidelity-Fixes.md). Format definitions are those of [IESDP](https://iesdp.bgforge.net/) and Near Infinity; see also [Format Notes](Format-Notes.md).

## Three patterns

| Pattern | Meaning | Example in this project |
|---------|---------|-------------------------|
| **Shared pool** | One array referenced by several parents, each with its own index and count | ITM/SPL feature blocks; ARE vertices |
| **Missing section** | The header holds an offset and count, but the schema defines no section for it | CRE `item_slots` and `effects`; IWD2 spell groups |
| **Unreferenced data** | Valid structures present in the file that nothing points at | Surplus feature blocks; trailing actors in PSTEE areas |

The first two are errors of *modelling*: the information is reachable, but the schema or parser did not follow it. The third cannot be reached by following references at all and needs a different mechanism (see [Unreferenced data](#unreferenced-data) below and [Unknown Bytes and the Gap Audit](Unknown-Bytes-and-the-Gap-Audit.md)).

## Shared pool: ITM and SPL feature blocks

In items and spells, effects ("feature blocks") live in a single array. The header owns the first *N* (the global or equipping effects). Each ability in the extended-header array then owns a further run of the same array through an index and a count.

A schema that sizes the feature-block section from the header's count alone therefore reads only the global effects and ignores every ability's effects. For items with abilities this truncated the file severely.

### The reading rule

The section's length is the *largest extent referenced by anyone*:

```
count = max(global_effect_count,
            max over abilities of (index_into_feature_blocks + count_of_feature_blocks))
```

Implemented in `BinaryParser._determine_section_count` (`core/binary/parser.py`), which for feature-block sections scans the extended headers first. The parser sorts extended headers ahead of feature blocks for this reason.

### The writing rule

The feature-block section must **not** be linked to the header count as its `count_field`. If it were, the writer would overwrite the header with the total, promoting every ability's effects to global effects and changing the meaning of the file. Leaving the section without a `count_field` makes the writer emit all blocks and leave `global_effect_count` untouched.

### How the bug hid itself

The log records five consecutive entries for this single fault (2026-03-17, *Orphaned Data Loss*, through *Resolved*), and each fixed a real but insufficient problem:

1. The count was linked to the header (read under-count, write corruption).
2. Reading ability fields overwrote header values in `resource.values`, so the inputs to the count were wrong. Only header data may populate `resource.values`.
3. The base count defaulted to 1 instead of the header's global effect count.
4. The special-case code never ran at all, because the parser tested the plural section names (`feature_blocks`) while the schemas use the singular (`feature_block`).
5. With the names corrected, the test item `SW2H10` round-tripped, all 16 feature blocks intact.

The lesson is methodological: after two fixes that did not change the checksum, diagnostic logging showed the code path was never executed. The parser today accepts both singular and plural names. The log also records that this fix hardcodes feature-block knowledge into the parser, accepted as a pragmatic coupling because the "maximum extent" logic is awkward to express in the schema language.

## Missing section: CRE tail data

Creature headers carry `offset_to_item_slots`, `offset_to_effects` and `count_of_effects`, but the CRE V1 schemas defined no `item_slots` or `effects` sections. Nothing read those regions and nothing wrote them, so saved files ended early. The representative case, `KPCHAP01` in BG2EE, saved at 1,248 bytes instead of 1,328, ending exactly at `offset_to_item_slots` (2026-03-21, *CRE V1 Tail Truncation*).

Two details made the fix more than adding sections:

- **Versioned effect size.** A CRE effect entry is `0x30` bytes when `eff_structure_version` is 0, and `0x108` bytes when it is 1 (the classic prefix plus 216 extra bytes). A field type, `effect_extra_data`, reads and writes the extra bytes only for the newer version, and the parser passes header values into field-type context so the type can see the version.
- **Optional zero-offset sections.** Some variants carry an offset of `0` for an absent section. For a section with no `count_field`, treating `0` as a real location made the parser read the file header as section data. An offset-based section without a count and with offset 0 is now treated as empty.

## Missing section: IWD2 spell and ability groups

IWD2 creatures (`CRE V2.2`) held their spell tables as raw bytes and left the bodies they point to unmodelled. Inspection showed the bodies were structured: each group is `count * 16` bytes of entries followed by an 8-byte footer of total and free slots, and the same layout serves class spells, domain spells, abilities, songs and shapes (2026-03-21, *IWD2 CRE V2.2 Spell and Ability Groups*).

The decision worth recording is what was *rejected*. A temporary whole-file passthrough had made unmodified round trips pass, but it bypassed real serialisation and hid the missing structure. It was removed, and the groups were modelled properly with a dedicated `iwd2_cre_group` type and 63 class plus 9 domain offset/count pairs. A passing round trip is evidence of fidelity only if the writer actually serialises the model.

A related routing error: four legacy `V9.1` creatures were being parsed as `V2.2` and crashed. They belong on the classic IWD schema, selected by version in the resource loader.

## Shared pool: ARE vertices

Door and region polygons in areas do not hold their own coordinates. Each stores an index and count into a single vertex array in the area header. With no `vertices` section in the schema, the polygon data was skipped on read and zeroed on write wherever it left a gap. Adding a `vertices` section tied to the header's offset and count to every ARE schema version resolved it (2026-03-31, *ARE Vertex Pool Resolution*).

The same entry period corrected `rect` fields: the format treats a rectangle as four 16-bit values (left, top, right, bottom), not eight bytes (2026-03-31, *ARE Bounding Box and Rect Type Fidelity*).

## Unreferenced data

Some data cannot be found by any reference:

- `PTION41.ITM` physically holds 10 feature blocks but only 8 are referenced; a heuristic reads surplus blocks from the end of the file.
- `AR13WZ.ARE` (PSTEE) has structured actor data after the last referenced section, marked unused in Near Infinity. The parser now captures bytes after the last section into `trailing_data` and appends them on write if the resource is unmodified.

An early version of the tail logic used the reader's final position. Because `vertices` sits last in the YAML but early in the file, that position fell mid-file and sections were written twice (2026-03-31, *ARE Fidelity Regression*). The parser now tracks `max_pos`, the highest offset reached by any section. Any logic of the form "what remains after the structured part" must be measured by extent, not by the order in which sections happen to be parsed.

Preserving this data only for unmodified resources is deliberate; see the discussion in [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md#2-layout-changes-on-write).

## Practical guidance for schema authors

1. For every header offset and count, ask whether a section consumes it. A header field that nothing reads is a warning sign.
2. When two structures index into the same array, size the array by the maximum extent, and do not let a single parent's count rewrite it.
3. Prefer modelling an unknown structure to passing it through opaquely, so the writer remains the thing under test.
4. Keep `resource.values` for header values only; section entries are returned, not stored globally.
5. Check that special-case parser logic is triggered, using the exact section names in the schema.

## Status of the described code

The behaviours above were checked against `core/binary/parser.py` and `drivers/InfinityEngine/definitions/types.py` for the existence of the named mechanisms (`_determine_section_count`, `trailing_data`, `max_pos`, `effect_extra_data`, `iwd2_cre_group`). The numerical results quoted come from the log and have not been re-run in the current repository.

## See also

- [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
- [Field Types Reference](Field-Types-Reference.md)
- [Relational Logic in WED](Relational-Logic-in-WED.md), where the same pattern recurs with shared offsets
- [Archived Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md)
