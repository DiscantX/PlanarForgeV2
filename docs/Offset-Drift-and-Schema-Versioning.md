# Offset Drift and Schema Versioning

Most Infinity Engine sections are arrays of fixed-size entries. A schema that misjudges the size of one entry is wrong by that amount for every entry after the first, so errors grow along the array. A second, related problem is that the *same* version string can hide different layouts in different games. This article covers both: how to recognise cumulative offset drift, the cases the project met, and how the loader chooses between schemas that share a version.

It continues the series begun in [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md). The history is in the [Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md), entries of 2026-03-18 and 2026-03-31. Format facts are those of [IESDP](https://iesdp.bgforge.net/) and Near Infinity; see also [Format Notes](Format-Notes.md).

## Recognising drift

Drift has a distinctive signature. The first entry of an array reads correctly; later entries show values that are nonsense and get worse with each step. In the log's examples:

- Offset and size fields containing ASCII-like fragments (for example `EDN2`), meaning the parser is reading text as numbers.
- Implausible values such as `index_of_first: 1852403536` in a region entry, increasing in absurdity down the list.
- Embedded data (a creature inside an area file) written back as zero bytes, because the parser never located it and the writer filled the space as an unreferenced gap.

Each of these is a *read* error that surfaces as a *write* mismatch. The log makes this point directly in an earlier case: inspecting the in-memory resource proved the fault was in reading, not writing, and removed several wrong hypotheses at once.

A useful consistency test needs no game knowledge: the entry size implied by the file (the distance between consecutive entries, or the section length divided by the count) must equal the size the schema declares.

## Cases

| Date | Resource | Schema said | File has | Effect |
|------|----------|-------------|----------|--------|
| 2026-03-18 | PSTEE ITM header | 154 bytes (PST V1.1) | 114 bytes (V1-style) | First extended header read as 40 bytes of header |
| 2026-03-31 | IWD2 ARE V9.1 actor | fields missing, misaligned, misnamed | 272 bytes | Pointers to embedded CRE drifted; creatures zeroed on write |
| 2026-03-31 | IWD2 ARE V9.1 region | 184 bytes (`0xB8`) | 196 bytes (`0xC4`) | Values nonsensical after the first region |
| 2026-03-31 | PSTEE ARE automap note | 52 bytes (shared V1 EE) | 68 bytes (`0x44`) | 16 bytes of drift per note |

The sizes are those recorded in the log, confirmed there against Near Infinity. They have not been re-measured for this article.

**Regions in IWD2.** The fix was to widen an `unknown` block at offset `0x0090` from 40 to 52 bytes. This is the standard remedy when the true meaning of the bytes is unknown: declare them as an opaque `bytes` field of the right size so that later fields line up and the data survives.

**Actors in IWD2.** The same defect had earlier been fixed in the Enhanced Edition ARE schema, and recognising it as "the same thing" shortened the diagnosis. Where one game's schema has been verified, the others in the same family are worth checking for the same class of error.

**Automap notes in PSTEE.** The area version reads `V1`, as in the Baldur's Gate games, yet the note entries are larger. Using the shared schema was therefore correct for the header and wrong for one section.

## Why a version string is not a layout

A schema is selected by resource type, game and version. That key fails in two ways:

1. **Same version, different layout.** The Enhanced Edition of Planescape: Torment declares `V1` but keeps Torment-specific structures. Items, creatures and areas each showed this, in different ways.
2. **Different version, same layout, or mixed content.** A game may ship a few legacy resources next to its usual format. IWD2 has four test creatures in the classic `V9.1` format among `V2.2` creatures, and PSTEE has a few creatures and areas in the original Torment layout.

The project's answer to (1) is a dedicated schema per game family where the layouts differ, with the game list in each schema's header. For PSTEE this gave separate item, creature and area schemas rather than a patched shared one. The repository's area schemas now include `are_v1_pstee.yaml` for the Enhanced Edition, `are_v1_pst.yaml` for the original, `are_v1_ee.yaml` for the Baldur's Gate and Icewind Dale Enhanced Editions, and `are_v9_1.yaml` for IWD2. (The log calls the PSTEE schema `are_pstee.yaml`; the repository name is authoritative.)

## Per-resource routing

For (2) the schema loader's choice is refined by inspecting the resource itself. `_resolve_resource_schema` in `drivers/InfinityEngine/resource_loader.py` starts from the game-and-type default and then overrides it in three cases:

| Resource | Condition | Routed to |
|----------|-----------|-----------|
| PSTEE creature | version `V1.1` and the legacy item-slot offset is physically plausible | the original PST creature schema |
| IWD2 creature | version `V9.1` | the classic IWD creature schema |
| PSTEE area | version `V1.0` and the word at `0xC4` is `0xFFFFFFFF` (original Torment's marker) with plausible automap offset and count | the original PST area schema |

The PSTEE creature rule has a subtlety recorded in the code. Some placeholder `V1.1` creatures are zero-filled stubs whose legacy offsets would point past the end of the file, so the loader keeps the Enhanced Edition schema for those. A rule that checks only the version would break them.

The area rule has a primary detector (the sentinel) and an older fallback that infers the original layout from the actor offset. Issue [#7](https://github.com/DiscantX/PlanarForgeV2/issues/7) records that this fallback probes a field that has a different meaning in the original layout, so it is not reliable; finding a dependable discriminator needs verification against real files. That is open work, not a finished design.

## Method

1. Compute the implied entry size from the file and compare with the schema.
2. Look at the first wrong entry, not the last: the earliest error shows where the sizes diverge.
3. Check whether a sibling game's schema was already fixed for the same structure.
4. Prefer a small script that reads one integer at a known offset over building a feature on a hypothesis. The log records one development cycle spent on an offset-correction feature that this check would have refuted.
5. Where meaning is unknown, pad with a `bytes` field of the correct size and record the gap in the [gap audit](Unknown-Bytes-and-the-Gap-Audit.md).

## Open points

- The sizes in the table come from the log and were not re-measured here.
- Issue #7 (PST and PSTEE area routing) and issue [#6](https://github.com/DiscantX/PlanarForgeV2/issues/6) (the area writer for overlapping offsets in the original format) both bear on this subject and need game files to resolve.
- The log's statement that duplicate schema files were removed does not match the repository in every case; the repository is authoritative (see [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md#discrepancies-noticed-while-writing)).

## See also

- [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
- [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md)
- [Format Notes](Format-Notes.md)
- [Archived Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md)
