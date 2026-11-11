# Layer 2: Open Questions

These questions were identified during the Layer 2 design but not resolved. They should be answered before, or during, implementation. Each question names the pages of the design it affects.

## 1. Duplicate field names in Flags group

*Affects: [Item Project Schema](Layer2-Item-Schema.md) and [Project Schema Format](Layer2-Schema-Format.md).*

The `usability_bitmask` field appears twice in the Flags group, distinguished only by
`games:` tag. The project schema loader needs explicit handling for this — two fields
with the same name that are mutually exclusive by target game. Decide whether this is
valid schema syntax or whether they need distinct project-level names (e.g.
`usability_bitmask_bg`, `usability_bitmask_pst`) with `from:` pointing at the same
binary field.

## 2. Unknown fields on round-trip

*Affects: [Assembler](Layer2-Assembler.md) and [Project Schema Format](Layer2-Schema-Format.md#handling-unknown-fields).*

Binary fields not covered by the project schema (unknown padding, undocumented regions)
must be preserved on round-trip. The assembler strategy for this has not been fully
specified. Options:
- Store unknown fields as opaque blobs attached to the project object
- Always re-parse from base game on export and overlay only the known changes
- Track original binary bytes per-section and write them back for uncovered ranges

## 3. kit_usability fields

*Affects: [Item Project Schema](Layer2-Item-Schema.md).*

The four `kit_usability_1` through `kit_usability_4` bytes in BG/EE binary schemas
have no semantic definition in the current binary schemas (raw bytes). Decide whether
to expose them as raw numeric fields, research their meaning and add proper bitmask
definitions, or omit them from the project schema entirely.

## 4. Validation

*Affects: [Widget Descriptors](Layer2-Widget-Descriptors.md) and [Undo and Redo](Layer2-Undo-Redo.md) (a failed command must not be applied).*

Field validation (min/max enforcement, resref existence checks, strref validity) has
been identified as necessary but not designed. Suggest: validation logic lives in the
project schema (a `validate:` attribute per field) and runs in the command's `apply()`
before committing. Failed validation rejects the command and the widget reverts.

## 5. PST extra_data in effects

*Affects: the shared `effect_fields` block in the [Item Project Schema](Layer2-Item-Schema.md).*

PSTEE and PST CRE/ITM effects have an additional 216-byte `extra_data` field
(EFF V2 structure). This is not currently covered in the effect_fields anchor. Decide
whether to expose it as a structured sub-object or carry it as an opaque blob.

## Inconsistencies between pages

Two statements elsewhere in the documentation conflict with this design and should be reconciled when question 2 is settled:

* [The Three-Layer Model](The-Three-Layer-Model.md) and [Project Format and Schemas](Project-Format-and-Schemas.md) say that Layer 2 discards bytes no schema field names. The [schema format](Layer2-Schema-Format.md#known-inconsistency-unknown-fields) and the [assembler](Layer2-Assembler.md) pages describe carrying them through unchanged.
* [Project Format and Schemas](Project-Format-and-Schemas.md) shows a project directory with `scenes/` and `assets/`, whereas the [project model](Layer2-Project-Model.md) shows `creatures/` and `items/`. These are probably two views of the same layout, but the full directory structure has not been written down in one place.

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Item Project Schema](Layer2-Item-Schema.md)
* [Assembler](Layer2-Assembler.md)
* [Widget Descriptors](Layer2-Widget-Descriptors.md)
