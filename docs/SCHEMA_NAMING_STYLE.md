# Schema Naming Style Guide

This guide defines how field names in PlanarForge YAML schemas should be written.

It applies to:

- Current schema families in this repo: `BIFF/BIFC`, `CRE`, `ITM`, `KEY`, `SPL`
- Current checked-in schema versions:
  - `CRE`: `V1`, `V1_PSTEE`, `V1.2`, `V2.2`, `V9`
  - `ITM`: `V1`, `V1.1`, `V1_PSTEE`, `V2.0`
  - `SPL`: `V1`, `V2`
  - `KEY`: `V1`
  - `BIFF/BIFC`: `V1`, `V1.0`
- IESDP source material used by the converter, especially the Infinity Engine file format pages:
  - https://gibberlings3.github.io/iesdp/file_formats/index.htm
  - Resource-specific pages such as `cre_v1.htm`, `itm_v1.htm`, `spl_v1.htm`

As of this guide, the checked-in schema surface is 14 schema files across 5 resource families and 1172 field definitions. Most naming problems are concentrated in importer-generated `CRE` schemas. `ITM`, `SPL`, `KEY`, and `BIFF/BIFC` are the baseline to preserve.

## Goals

- Prefer short names over long names.
- Keep enough semantic information to tell fields apart.
- Use the same name for the same concept across resource types and versions.
- Keep names stable enough that parser logic and tool code can rely on them.
- Treat IESDP descriptions as source material, not as ready-made field names.

## Core Rules

1. Use lowercase `snake_case`.
2. A field name should be a noun phrase, not a sentence.
3. Keep only the primary semantic label. Drop commentary, examples, ranges, and explanations.
4. Use singular names for scalar fields.
5. Use plural names only for sections/tables or values that are inherently plural.
6. Do not embed game names in a field name unless the field exists only in a game-specific schema variant.
7. Do not encode documentation notes into names.
8. Do not encode numeric ranges into names.
9. Do not encode IDS references, examples, or value tables into names.
10. Use numbered suffixes only when the file format truly exposes repeated channels or slots.

## Canonical Patterns

These forms should be preferred across all schemas.

### Identity and metadata

- `signature`
- `version`
- `flags`
- `<thing>_type`
- `<thing>_id`
- `<thing>_index`

### Resource references

- `<resource>_file` for resource-name fields such as `itm_file`, `spl_file`
- `<thing>_icon`
- `<thing>_portrait`
- `<thing>_script_<scope>`
- `<thing>_sound`

### Control fields

Use prefix form consistently:

- `offset_to_<section>`
- `count_of_<section>`
- `index_into_<section>`

Examples:

- `offset_to_extended_headers`
- `count_of_feature_blocks`
- `index_into_memorized_spells`

Suffix forms such as `known_spells_offset` and `known_spells_count` are legacy importer output and should not be generated going forward.

### Flags and masks

- `<thing>_flags`
- `<thing>_bitmask`

Do not append the bit descriptions themselves.

### Quantities and repeated slots

- `<thing>_1`, `<thing>_2`, `<thing>_3` only when the format really has numbered peers
- `parameter_1`, `parameter_2`
- `quantity_charges_1`, `quantity_charges_2`, `quantity_charges_3`

Do not use numbered suffixes as a substitute for bad name extraction.

### Unknown and unused fields

- Use `unknown`, `unknown_2`, `unknown_3`, ... only when the field is genuinely unknown.
- Use `unused`, `unused_2`, ... only when the field is explicitly documented as unused in the active schema variant.
- Never produce names like `note_*`, `comment_*`, `see_*`, or `range_*`.

## Cross-Resource Consistency

When the same concept appears in multiple resources or versions, keep the same name unless the binary meaning actually changes.

Examples that should stay aligned:

- `signature`, `version`
- `flags`
- `offset_to_extended_headers`
- `count_of_feature_blocks`
- `index_into_feature_blocks`
- `small_portrait`, `large_portrait`
- `memorized_spells`
- `creature_script_override`
- `opcode_number`
- `timing_mode`
- `saving_throw_bonus`

## IESDP Extraction Rules

The converter must extract names from the IESDP description column using these rules.

### Keep

- The primary noun phrase.
- Stable semantic qualifiers that distinguish sibling fields.
- True structural labels such as `override`, `class`, `race`, `general`, `default`.

### Drop

- Game labels: `BG1:`, `BG2:`, `BGEE:`, `PSTEE:`
- Commentary prefixes: `Note:`, `NB.:`
- Ranges: `(0-100)`, `(1-25)`, `(range: 0-255)`
- IDS references: `(EA.IDS)`, `(RACE.IDS)`
- Example values and enumerations
- Explanatory prose after the main label
- Bit listings beginning with `Bit 0`, `0=`, etc.

### Variant handling

- If IESDP provides separate game-specific labels in one row, choose the label for the active schema variant.
- If a page mixes alternate layouts, generate separate schema variants rather than baking game tags into field names.
- If the active variant has no explicit label, prefer the closest compatible label, not any trailing note text.

## Preferred Shortening

Prefer the shorter stable form when meaning is preserved.

- `short_name_tooltip` -> `short_name`
- `spell_level_1` -> `spell_level`
- `eff_structure_version_0_version_1_eff_1_version_2_eff` -> `eff_version`
- `animation_id_bgee_animation_slots_have_been_externalised` -> `animation_id`
- `level_first_class_highest_attained_level_in_class...` -> `level_first_class`
- `morale_default_value_is_10_it_is_unclear_what_increases_decreases_morale_or_by_how_much` -> `morale`
- `kit_information_none_0x00000000_...` -> `kit_information`

## Bad vs Good Examples

- Bad: `note_proficiencies_are_packed_into_3_bit_chunks_for_primary_and_secondary_classes_6`
- Good: `unused_proficiency_6`

- Bad: `animation_id_bgee_animation_slots_have_been_externalised`
- Good: `animation_id`

- Bad: `spell_level_1`
- Good: `spell_level`

- Bad: `known_spells_offset`
- Good: `offset_to_known_spells`

- Bad: `known_spells_count`
- Good: `count_of_known_spells`

- Bad: `resource_name_of_the_spl_file`
- Good: `spl_file`

## Converter Requirements

The converter should:

- select the correct game-specific text before name extraction
- merge split IESDP lines such as `BGEE:` followed by the actual label on later lines
- ignore commentary-only lines when naming
- normalize control fields to `offset_to_*`, `count_of_*`, `index_into_*`
- preserve existing good names from `ITM`, `SPL`, `KEY`, and `BIFF/BIFC`
- prefer `bytes` over fake scalar names when IESDP describes repeated scalar arrays the schema system cannot model directly

## Migration Guidance

When cleaning existing schemas:

1. Fix names that encode notes, ranges, or prose first.
2. Normalize control fields next.
3. Align cross-version names within a resource family.
4. Only then rename broad shared concepts across resource families.

Renames should preserve parser behavior and control-field linkage.
