# Relational Logic & Pointer Recomputation

The WED format (V1.3) is significantly more complex than standard IE headers because it uses "Global Pools" of data that multiple sections point into.

## Relational Context Promotion

The `BinaryParser` supports a "Promotion" mechanism. If a section is defined with a count of 1 (like the `secondary_header`), its fields are promoted to the global parsing context. Subsequent sections can then resolve offsets and counts from this header as if they were in the main file header.

## Aggregate Counts

The engine supports `count_expr` for sections like `door_tile_cell_indices`. These tables do not have a single count field; their size is the **sum** of counts across all entries in the `doors` section.

## Pointer Recomputation

When writing a modified WED file, the tool performs **Relational Writing**:

1. It places a section (e.g., `tilemaps`) in the file.
2. It calculates the cumulative offset for each "window" of data.
3. It iterates back through the parent section (e.g., `overlays`) and updates their `offset_to_tilemap` pointers to match the new physical layout.

## Structural Layout

The WED file follows this physical sequence:

1. Header
2. Overlays -> (Points to Tilemaps & Lookups)
3. Secondary Header
4. Doors -> (Points to Cell Indices)
5. Global Data Pools (Tilemaps, Polygons, Vertices, etc.)

By modeling these as flat global sections and using recomputation logic, PlanarForge allows for resizing map overlays or adding/removing polygons without breaking the file's internal integrity.

---

For the chronological development history and troubleshooting details of these features, see [WED V1.3 Engine Upgrade](WED-V1.3-Engine-Upgrade.md) (source: the [archived log](archive/Engineering-Log-WED-Upgrade.md)).