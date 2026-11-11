# Infinity Engine Format Notes

This page collects what the project has learned, usually the hard way, about the file formats used by the Infinity Engine games. It is aimed at readers who know programming but have not met these formats before. Entries that describe unmerged work say so.

## Background

The Infinity Engine stores game data as many small **resources**, each identified by a name of up to eight characters (a *resref*) and a type (for example `ARE` for an area, `WED` for the map layout of an area, `TIS` for its graphics tiles). Resources are either loose files or packed inside large archives called **BIFF** files (`.bif`). A master index, `CHITIN.KEY`, records for each resref which archive holds it and where. PlanarForge reads the index, locates the archive, extracts the bytes, and interprets them with a YAML schema.

Two community projects document these formats and are the project's constant companions:

* [IESDP](https://iesdp.bgforge.net/), the Infinity Engine Structures Description Project, is the written specification of the formats.
* [Near Infinity](https://github.com/NearInfinityBrowser/NearInfinity) is a Java viewer and editor for the same files, widely used for checking what a file really contains.

## How much to trust the references

IESDP is an excellent but human-maintained document, and it is sometimes wrong or incomplete. The project's rule of thumb, in order of authority:

1. What the bytes actually contain, checked in a hex editor.
2. What Near Infinity shows for the same file.
3. What IESDP says.

When these disagree, the disagreement is worth recording. Known cases:

* **Size of a WED tilemap entry.** Earlier project notes record IESDP as giving 8 bytes, while Near Infinity and hex dumps showed 10. The current IESDP [WED V1.3 page](https://iesdp.bgforge.net/file_formats/ie_formats/wed_v1.3.htm) ends the structure with three unknown bytes at offset `0x0007`, which gives 10, so the upstream error appears to have been fixed. The schema `wed_v1_3.yaml` uses 10.

Other IESDP errors were found during earlier work but were not written down. They are to be recovered and listed here as the maintainer re-reviews the code.

## Tileset files (TIS) in BIFF archives

A **TIS** file holds the picture tiles of an area. It is only graphics; where each tile goes is described by the area's WED file. IESDP's [TIS V1 page](https://iesdp.bgforge.net/file_formats/ie_formats/tis_v1) describes two variants:

* **Palette-based.** Each tile carries its own 256-colour palette followed by one byte per pixel. For 64 by 64 tiles that is 1,024 bytes of palette plus 4,096 bytes of pixels, 5,120 bytes in all.
* **PVRZ-based.** Enhanced Edition games only. Each tile is a small record pointing at a block of pixels inside a separate compressed texture file (`.pvrz`). In the project's reading of the format, each record is 12 bytes.

A loose TIS file begins with a 24-byte header. Inside a BIFF archive the layout is different, and two behaviours have caused bugs:

* **Tiles share a pool and are found by `resource_index`.** A BIFF tileset entry holds the tiles of many TIS resources, packed one after another. The key file's `resource_index` for a given TIS names the *first tile* belonging to it, so reading must start that many tiles into the pool. Starting at the beginning of the pool silently returns another area's tiles. The fix is implemented on the unmerged `uncommitted` branch, not yet on `main` ([issue #5](https://github.com/DiscantX/PlanarForgeV2/issues/5)).
* **There is no per-resource header, so one must be synthesised.** The archive stores tile payloads without the 24-byte TIS header, so the tool builds a header for the schema parser. The tile count has to be derived from the pool (the distance to the next TIS in the same pool) rather than assumed. IESDP also notes that Planescape: Torment can only load TIS files that live in a BIFF.

Choosing the palette or PVRZ schema is done by looking at the `tile_data_block_size` field of the header (12 or 5,120). On the `uncommitted` branch the single `tis_v1.yaml` is split into `tis_v1_palette.yaml` and `tis_v1_pvrz.yaml` for this purpose.

## Look-alike formats: PST versus Enhanced Edition

The original Planescape: Torment (PST) and the Enhanced Edition (PSTEE) share a lot of structure, and the later EE versions of several other formats resemble PST variants. Naive identification by a single field is therefore dangerous. The known example is area (ARE) files, where actor records are 268 bytes in the PST layout and 272 bytes in the EE layout. The loader currently decides by reading the double word at `0x84` of the header, but in the PST layout that field is `offset_to_ambients`, not an actor offset, so the test is unreliable ([issue #7](https://github.com/DiscantX/PlanarForgeV2/issues/7)). Format identification should rest on field-level verification, not on resemblance.

## Sections that share an offset

Real game files are not always tidy. In PST-format ARE files the `animations` and `song_entries` sections declare the same file offset. The parser handles this by seeking to each section independently, but a writer that emits sections one after another cannot step backwards, so the output is displaced and the file grows ([issue #6](https://github.com/DiscantX/PlanarForgeV2/issues/6)). Both reading and writing must allow for overlapping sections, because they are legitimate in original files. See also [Round-trip Fidelity](Round-trip-Fidelity.md).

## Design principles for schemas

These recur across the project's history and are summarised here so that they are not rediscovered:

* **The schema is the single source of truth.** The same YAML drives parsing, writing, enum and bitmask resolution, and user-interface field generation. Structural knowledge is not duplicated in code.
* **Keep schemas lean.** Do not redeclare enum or bitmask values, repeat display metadata, or create per-variant files where a single schema with a `games:` tag will do. Naming conventions are in the [Schema Naming Style Guide](Schema-Naming-Style-Guide.md), and the available field types in the [Field Types Reference](Field-Types-Reference.md).
* **Preserve what is unknown.** A bitmask keeps bits the schema does not name, so that an unmodified file can be written back byte for byte. Editing is different: once a resource is modified, a clean repacked file is the goal. See [Round-trip Fidelity](Round-trip-Fidelity.md#the-unknown-byte-policy).
