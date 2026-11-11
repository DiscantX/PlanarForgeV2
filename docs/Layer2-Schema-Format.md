# Layer 2: The Project Schema Format

Layer 1 is described by *binary schemas*: YAML files that say where each field sits in a game file. Layer 2 has its own YAML files, the *project schemas*, which say which of those fields the user should see, how they are grouped in the inspector, and how they map back to the binary fields. A project schema deliberately says as little as possible: it does not repeat anything the binary schema already knows, such as the names of enum values or bitmask flags.

For the binary side, see [Field Types Reference](Field-Types-Reference.md) and the [Schema Naming Style Guide](Schema-Naming-Style-Guide.md). For a complete worked example, see the [Item project schema](Layer2-Item-Schema.md).

## Design principles

- **Lean syntax** — only include attributes that carry information not inferrable
  from context
- **Binary schema is source of truth for enum values, bitmask flags** — project
  schema does not redefine them
- **Display names derived from field names** — `identified_name` → "Identified name"
  via snake_case formatting. No separate `display:` attribute required unless
  overriding
- **`from:` omitted when binary field name matches project field name**
- **`section:` required only when field name is ambiguous across binary sections**

## Unified vs per-game schemas

Project schemas use a **unified approach with `games:` tags** for game-specific fields.
This differs from binary schemas which are strictly per-variant.

Rationale: binary schemas describe physical memory layouts which differ precisely and
dramatically between game versions. Project schemas describe semantic content which is
largely consistent. The `from:` mapping bridges between them.

Rule for when to split vs tag:
- Field exists in all games with same semantic meaning → unified, no tag
- Field exists only in some games → unified with `games:` tag
- Field occupies same binary location but means something completely different →
  split into separate project schema (this should be rare)

## Top-level structure

```yaml
name: Item                  # human-readable resource type name
version: V1                 # project schema version
resource_type: ITM          # binary resource type code

# YAML anchors for shared field sets (see effect_fields example below)
effect_fields: &effect_fields
  fields: [ ... ]

groups:                     # ordered list of inspector groups
  - name: Identity
    fields: [ ... ]
  - name: Abilities
    repeating: true
    from_section: extended_header
    fields: [ ... ]
```

## Field attributes

| Attribute | Required | Description |
|-----------|----------|-------------|
| `name` | Yes | Field name. Used as binary field name unless `from:` overrides |
| `type` | Yes | Project-level field type (see types below) |
| `from` | No | Binary field name if different from project field name. String for all games, dict for game-specific |
| `from_bitfield` | No | Sub-field extraction from a bitfield type (see below) |
| `section` | No | Binary section to look up field in. Required when field name is ambiguous across sections |
| `games` | No | List of game IDs this field applies to. Absent means all games |
| `min` | No | Minimum value for number fields |
| `max` | No | Maximum value for number fields |
| `nullable` | No | Whether field may be null/empty. Defaults vary by type |
| `picker` | No | For resref fields: which resource picker to open (`bam`, `dialog`, `projectile`, `generic`) |
| `equipping` | No | For repeating groups: marks this as the equipping effects pool vs ability effects |
| `display` | No | Override display name. Use sparingly — prefer naming fields well |

## `from:` attribute

```yaml
# Same binary field name across all games — omit from: entirely
- name: identified_name
  type: strref

# Same binary field name, explicit shorthand form (equivalent to above)
- name: identified_name
  from: identified_name
  type: strref

# Different binary field name across games
- name: usability
  from:
    PST: usability_bitmask_pst
    PSTEE: usability_bitmask_pst
  type: bitmask
  games: [PST, PSTEE]
```

Only use explicit `from:` when the binary field name actually differs. Identical
name mappings are noise.

## `from_bitfield:` attribute

For exposing sub-fields of a binary `bitfield` type as separate project-level fields:

```yaml
- name: melee_animation_overhand
  from_bitfield:
    field: melee_animation
    subfield: overhand
  type: number
  min: 0
  max: 65535
  section: extended_header
```

This tells the assembler to read/write the `overhand` sub-field of the binary
`melee_animation` bitfield rather than the whole field.

## `section:` disambiguation

When a field name exists in multiple binary sections, `section:` is required:

```yaml
- name: flags
  type: bitmask
  section: header       # disambiguates from extended_header.flags
```

The `WidgetDescriptorFactory` raises a hard error if a field name matches multiple
sections and no `section:` is provided. Silent ambiguity is worse than a loud error.

## Repeating groups

Groups with `repeating: true` map to arrays of entries rather than single structs.
`from_section:` names the binary section they come from:

```yaml
- name: Abilities
  repeating: true
  from_section: extended_header
  fields: [ ... ]
```

Repeating groups can be nested (Effects inside Abilities):

```yaml
- name: Abilities
  repeating: true
  from_section: extended_header
  fields:
    - name: damage_type
      type: enum
      section: extended_header
    - name: Effects
      repeating: true
      from_section: feature_block
      <<: *effect_fields
```

Nesting implies ownership: effects belong to the ability they are nested under. The
assembler reconstructs the binary `index_into_feature_blocks` / `count_of_feature_block`
control fields from this nesting when writing back to binary. These control fields do
**not** appear in the project schema.

The `equipping: true` attribute on a top-level repeating group marks it as the
equipping effects pool, mapping to `index_into_equipping_feature_blocks` /
`count_of_equipping_feature_blocks` in the binary header:

```yaml
- name: Equipping Effects
  repeating: true
  from_section: feature_block
  equipping: true
  <<: *effect_fields
```

## YAML anchors for shared field sets

Use YAML anchors to avoid duplicating field definitions that appear in multiple
groups (e.g. effect fields used in both Abilities and Equipping Effects):

```yaml
effect_fields: &effect_fields
  fields:
  - name: opcode_number
    type: number
    ...

groups:
  - name: Equipping Effects
    repeating: true
    from_section: feature_block
    equipping: true
    <<: *effect_fields

  - name: Abilities
    repeating: true
    from_section: extended_header
    fields:
      - name: Effects
        repeating: true
        from_section: feature_block
        <<: *effect_fields
```

## Project-level field types

| Type | Binary types it maps from | Widget |
|------|--------------------------|--------|
| `strref` | `strref` | Text box (shows resolved TLK string, writes back strref integer) |
| `resref` | `resref` | Text input + resource picker button |
| `number` | `byte`, `word`, `dword`, `sword`, `sbyte`, `sdword`, `char` | Numeric input |
| `enum` | `enum` | Dropdown. Options sourced from binary schema `values` map |
| `bitmask` | `bitmask` | Checkbox group. Options sourced from binary schema `flags` map |
| `text` | `byte`/`word` with IDS `lookup:` | Plain text input. IDS resolution happens at binary layer; reverse lookup handles export |

**On `text` type and IDS-resolved fields:**

Fields like `weapon_proficiency` (WPROF.IDS) and `projectile_animation` (MISSILE.IDS)
are resolved to string symbols by the binary parser's `TableResolver` during import.
At the project level they are stored and edited as plain strings. On export, the
reverse lookup in `IdsHandler.lookup(symbol)` converts them back to integers.

This works because:
1. The binary parser always stores exactly the IDS symbol string
2. `IdsHandler` already has `reverse_entries` populated at parse time
3. The IDS file must exist for the target game (normal export precondition)

No special handling is needed at the project schema level. Declare these fields as
`type: text`.

## Enum and bitmask values

**Do not redefine enum values or bitmask flags in project schemas.** They are already
defined in binary schemas and the `WidgetDescriptorFactory` reads them directly from
there. Redefining them would create a maintenance burden and a source of divergence.

Display names for enum options and bitmask flags are derived from the binary schema
symbol names using the same snake_case formatter used for field names:
`unsellable_critical_item` → "Unsellable critical item".

If a binary schema symbol name is unclear, fix it in the binary schema. The improvement
propagates automatically to the UI.

## Handling unknown fields

Fields marked as `unknown` in the binary schema (e.g. padding bytes, undocumented
regions) are **not exposed in the project schema**. They are preserved transparently
on round-trip by the assembler, which carries them through unchanged. The user never
sees them.

## Known inconsistency: unknown fields

The section above says unknown binary fields are carried through unchanged on round-trip. Other pages describe the opposite: [The Three-Layer Model](The-Three-Layer-Model.md) and [Project Format and Schemas](Project-Format-and-Schemas.md) say Layer 2 *discards* bytes that no schema field names. The design's own [open question 2](Layer2-Open-Questions.md#2-unknown-fields-on-round-trip) records that the preservation strategy was never fully specified. Until that question is settled, treat this section as a design intention rather than a decision.

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Item Project Schema](Layer2-Item-Schema.md): the reference implementation of this format
* [Widget Descriptors](Layer2-Widget-Descriptors.md): the code that consumes project schemas
* [Assembler](Layer2-Assembler.md): the code that uses `from:` mappings to translate between layers
* [Open Questions](Layer2-Open-Questions.md): unresolved issues, including duplicate field names and unknown-field handling
