# WED V1.3 Engine Upgrade

The area-geometry format (WED, version 1.3) was the first format whose structure could not be expressed by the engine as it then stood. This article explains why, records what the project found about the format, tells the story of the write-side failures and how a change of model removed them, and lists the engine features that resulted. For the design as it now stands, see [Relational Logic in WED](Relational-Logic-in-WED.md); this article is the account of how it came about.

It is drawn from the [WED Upgrade log](archive/Engineering-Log-WED-Upgrade.md) (1 to 3 April 2026). The earlier ITM, SPL, CRE and ARE work is covered in [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md) and [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md). Format facts are from [IESDP](https://iesdp.bgforge.net/) and Near Infinity.

## Why WED was different

In the earlier formats, every section's offset and count lived in the main header. WED breaks that assumption three ways:

1. **A second header.** The polygon and vertex sections are located by a secondary header that follows the overlays, not by the main header.
2. **Windows into shared pools.** Overlays and doors hold offsets into global arrays (tilemaps, lookup tables, cell indices). Each parent sees a window onto one pool.
3. **Counts with no field.** Several tables have no count anywhere. Their size is a sum or product over other entries, for example the sum of the tile counts of all overlays.

The log's stated aims were relational context (later sections resolving offsets from any header-like section), pointer management, computed fields and aggregate counts, and no regression in ITM, SPL, CRE or ARE. A decision made at the outset shaped everything after: WED would be **fully modelled** and would not rely on raw "tail" captures, so that the data would be readable and editable, not merely preserved.

## What the project found about the format

**Flat global pools.** WED files are a sequence of flat, contiguous arrays with no physical nesting. Overlays and doors store indices and offsets into the global sections. The verified physical order is: header, overlays, secondary header, doors, tilemaps, door tile cell indices, tile index lookup, wall groups, polygons, polygon index lookup, vertices.

**The 10-byte tilemap entry.** The principal cause of unexplained data and of offset drift was the size of a tilemap entry. At the time of the log, IESDP stated 8 bytes, while Near Infinity and binary analysis showed 10, the extra bytes holding a secondary tile index, an animation speed and an unknown word. IESDP now lists the entry as 10 bytes, so the log's claim that IESDP says 8 is out of date. (A comment in `wed_v1_3.yaml` still repeats the old claim; it is a stale code comment, not a docs matter, and is noted for the schema's next revision.)

This is the same class of fault as in [Offset Drift and Schema Versioning](Offset-Drift-and-Schema-Versioning.md): a wrong entry size, with a source document that was itself wrong or out of date. It is a useful reminder to verify against real files rather than a specification alone.

**Sparse overlay windows.** Some files use windows that are not contiguous. The schema therefore resolves a count by the maximum physical extent implied by the overlay offsets whenever that exceeds the plain sum.

## The write-side failures

Reading the format was largely settled by the structural findings. Writing it back was the hard part, and the log records a long run of attempts on 1 April, nearly all with the same symptom: zero bytes where tilemap or lookup data should be (at `0xAE`, `0xAC` and `0x630`), or real data captured as unstructured trailing bytes.

| Hypothesis recorded | Remedy tried |
|---------------------|--------------|
| The writer omits relational blocks from its write list | Include them, even when empty, if they have a valid offset |
| Read extent is under-tracked, so data lands in `trailing_data` | Track the furthest read position universally; fix its update order around jumps |
| An empty section sharing an offset with a data block zero-fills it | Deduplicate offsets; prefer non-empty over empty |
| The first candidate for a shared offset is a small one | Prefer the largest candidate |
| Collection was split across two loops, so ordering still mattered | Collect all candidates first, then choose in one pass |
| Sections and relational blocks of equal size still tie | Prefer the relational block |
| The extent tracker is clobbered by the jump's seek-back | Skip the update for jumped types; add trace logging |
| The writer pads relative to its position, so earlier discrepancies shift later blocks | Seek explicitly to each block's offset |

Each was a real defect and each got closer. The last, found only with trace logging that showed the right bytes being written and the wrong ones surviving in the file, was the actual cause of the final symptom.

### What the series shows

An interpretation, offered for review: most of these were consequences of one modelling choice. Because each overlay and door owned a "jump" to its own window, several blocks could claim the same offset, and the writer then needed rules (empty versus data, small versus large, section versus jump) to arbitrate. The arbitration rules kept growing because the model was creating the ambiguity.

The overhaul of 2 April removed the ambiguity. The shared arrays became **flat global sections**, each with one owner, and the parent entries' pointers became data to be *recomputed* on write. The log records the outcome: `AR4101` and `AR6009` pass round-trip. None of the intermediate machinery (the jump array type, the candidate registry, the offset-deduplication sets, the extent-tracking field) remains in `core/` or `drivers/` today, which is consistent with that reading.

The earlier ITM and SPL case followed the same pattern: [five fixes](Shared-and-Orphaned-Data-Blocks.md#how-the-bug-hid-itself) to a shared pool before the real cause appeared. In both, repeated patching of arbitration logic was a sign that the data model, not the logic, was at fault.

## Engine features that resulted

| Feature | Purpose | Where |
|---------|---------|-------|
| `promote` | A single-entry section (the secondary header) merges its fields into the global context for later sections | `Section` attribute |
| `offset_from` | Locate a section from a field in another (the tilemaps from the first overlay's pointer) | `Section` attribute |
| `count_expr` | Derive a count from other sections (`sum`, `ceil_product`) | `Section` attribute |
| `offset_update` | After repacking, rewrite each parent's pointer using a stride | `Section` attribute |
| `Computed` | A virtual, zero-size field evaluated from the entry's own values (for example a tile count) | field type |
| `WordScalarArray` | A flat array of 16-bit words, for lookup tables | field type |
| `evaluate_expr` | A restricted expression evaluator for schema-defined arithmetic, so schemas cannot run arbitrary code | `core/field_types.py` |

Two corrections from the same period are worth noting. The secondary header matches IESDP and carries no vertex count; the vertex count is derived from the maximum extent referenced by the polygons. The wall-group count uses `(width + 9) // 10`.

These are described from the perspective of use in [Relational Logic in WED](Relational-Logic-in-WED.md) and are specified in [Field Types Reference](Field-Types-Reference.md).

## Gaps that remained

After the structural fixes, several WED files still reported internal unmapped gaps. Rather than reintroduce raw tail capture, the project added the gap audit and exact allowlist described in [Unknown Bytes and the Gap Audit](Unknown-Bytes-and-the-Gap-Audit.md). The log's two final WED entries record that work: WED unknown-gap handling became explicit and auditable, and fast audit modes made routine runs practical.

## Verification and limits

The named schema attributes and field types were checked in `core/schema_loader.py`, `core/field_types.py` and `core/binary/parser.py`, and the flat-section definitions in `wed_v1_3.yaml`. The test results (`AR4101`, `AR6009`) are quoted from the log and were not re-run. The statement that the intermediate write machinery no longer exists is based on searching the source for those names.

## See also

- [Relational Logic in WED](Relational-Logic-in-WED.md)
- [Field Types Reference](Field-Types-Reference.md)
- [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
- [Archived WED Upgrade log](archive/Engineering-Log-WED-Upgrade.md)
