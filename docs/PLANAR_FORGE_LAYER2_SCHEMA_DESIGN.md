# PLANAR FORGE — Layer 2 Project Schema Design

## Status

This document describes all decisions made about the Layer 2 (project-level) schema
system for PLANAR FORGE. It is intended to be complete enough for implementation to
proceed without the original design session.

Layer 1 (binary parsing/writing) is fully implemented and passing round-trip fidelity
tests across all supported games. Layer 2 is not yet implemented. This document covers
its design in full.

---

## Overview

Layer 2 is the project-level editing layer. Where Layer 1 deals with raw binary file
formats (`.cre`, `.itm`, `.are`, etc.), Layer 2 deals with human-editable project files
(`.creature`, `.item`, `.scene`, etc.) that the editor UI operates on exclusively.

The key principle: **the UI never touches Layer 1 directly.** It reads and writes Layer 2
project objects. The assembler handles translation between layers.

---

## Project File Model

### What gets written to disk

Only **modified** resources are written to disk as project files. Unmodified base game
resources exist only as ephemeral in-memory objects during a session. The project
directory stays clean — it contains only the user's actual changes.

```
MyMod/
  creatures/
    bandit_custom.creature    ← modified, on disk
  items/
    my_sword.item             ← modified, on disk
  # vanilla resources NOT here even if viewed during the session
```

### Ephemeral vs persisted nodes

| Node type | On disk | In memory | Evictable |
|-----------|---------|-----------|-----------|
| Persisted (modified) | Yes | Always | Never |
| Ephemeral (unmodified) | No | LRU cache | Yes |

Ephemeral nodes are reconstructed from base game data on demand. They are held in a
bounded LRU cache (suggested capacity: 200–500 objects). When evicted they are simply
re-parsed on next access.

The transition from ephemeral to persisted happens on the **first edit**. At that point
the session writes the project file to disk and the node becomes permanent for the
session.

### Project discovery on load

The project directory is scanned on load. There is no explicit manifest of modified
files — the directory contents are the manifest. All `.creature`, `.item`, etc. files
found are loaded as persisted nodes.

---

## Dependency Graph

### What is tracked

The dependency graph tracks references between project resources (both persisted and
ephemeral). Nodes are resource identifiers (resref + type). Edges are directional
references (A depends on B).

The graph is stored as a **forward index** (what does X reference?) which can be
inverted on demand for "used by" queries.

```python
graph = {
    "bandit": {"bandit_dlg", "sw1h01", "leat01"},
    "my_sword": {"spwi302"},
}

def used_by(resref):
    return {src for src, deps in graph.items() if resref in deps}
```

### What is NOT tracked

- BCS script internals (scripts treated as opaque)
- TLK strref integers (not meaningful cross-resource dependencies)
- Unmodified base game resources that have never been accessed

### Graph completeness and background indexing

The graph is built in three phases:

**Phase 1 — Program load (synchronous, fast):**
- Load all persisted project files from disk
- Build partial graph from persisted nodes only
- UI is available immediately

**Phase 2 — Background indexing (starts after Phase 1):**
- Walk full base game resource index
- Extract resref-typed fields from metadata cache (no full binary parse needed)
- Complete the dependency graph
- Dependency-aware UI features (used-by, safe-delete, rename propagation) are
  disabled or show a progress indicator until this completes

**Phase 3 — Lazy, on access:**
- Full Layer 2 object construction happens on demand
- Graph is already complete, so dependency queries work immediately

### Implicit import on open

Opening any base game resource automatically creates an ephemeral project object for
it. There is no separate "import" step. The moment a resource is viewed in the editor,
it has a Layer 2 representation.

If the user edits it, it becomes persisted. If not, it stays ephemeral and may be
evicted from the LRU cache.

Recursive dependency closure (pulling in a resource and all its dependencies) is
available as an explicit **"Import with dependencies"** operation, and is also
triggered automatically during export preparation.

### Asset boundary

The recursive closure stops at the **asset boundary** — resources that have no project
schema (BAM, WAV, TIS, etc.) become leaf nodes referenced by resref string but not
expanded further. They appear in the graph but do not become project objects.

---

## Undo / Redo

### Command pattern

Every user action is a command object with `apply()` and `undo()` methods. A stack of
commands on the session object provides undo history. History is not persisted between
sessions.

```python
class FieldEditCommand:
    def __init__(self, resource, field_name, old_value, new_value):
        self.resource = resource
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value

    def apply(self):
        self.resource.set(self.field_name, self.new_value)

    def undo(self):
        self.resource.set(self.field_name, self.old_value)
```

### Compound commands

Operations that span multiple resources (e.g. resref rename propagation) are wrapped
in a compound command that applies and undoes as a single unit:

```python
class CompoundCommand:
    def __init__(self, commands):
        self.commands = commands

    def apply(self):
        for cmd in self.commands:
            cmd.apply()

    def undo(self):
        for cmd in reversed(self.commands):
            cmd.undo()
```

### Session as mediator

The UI layer never writes directly to resource objects. Instead it creates a command
and pushes it to the session's undo stack, which applies it:

```python
widget.on_change(lambda v, f=field:
    session.execute(FieldEditCommand(resource, f.name, resource.get(f.name), v))
)
```

This means the **session object must exist before the UI layer is built**.

### Dirty state on first edit

When a command is applied to an ephemeral node for the first time, the session:
1. Marks the resource as dirty
2. Determines the output file path
3. Writes the project file to disk
4. Promotes the node from ephemeral to persisted in the graph

---

## Project Schema Format

### Design principles

- **Lean syntax** — only include attributes that carry information not inferrable
  from context
- **Binary schema is source of truth for enum values, bitmask flags** — project
  schema does not redefine them
- **Display names derived from field names** — `identified_name` → "Identified name"
  via snake_case formatting. No separate `display:` attribute required unless
  overriding
- **`from:` omitted when binary field name matches project field name**
- **`section:` required only when field name is ambiguous across binary sections**

### Unified vs per-game schemas

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

### Top-level structure

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

### Field attributes

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

### `from:` attribute

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

### `from_bitfield:` attribute

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

### `section:` disambiguation

When a field name exists in multiple binary sections, `section:` is required:

```yaml
- name: flags
  type: bitmask
  section: header       # disambiguates from extended_header.flags
```

The `WidgetDescriptorFactory` raises a hard error if a field name matches multiple
sections and no `section:` is provided. Silent ambiguity is worse than a loud error.

### Repeating groups

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

### YAML anchors for shared field sets

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

### Project-level field types

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

### Enum and bitmask values

**Do not redefine enum values or bitmask flags in project schemas.** They are already
defined in binary schemas and the `WidgetDescriptorFactory` reads them directly from
there. Redefining them would create a maintenance burden and a source of divergence.

Display names for enum options and bitmask flags are derived from the binary schema
symbol names using the same snake_case formatter used for field names:
`unsellable_critical_item` → "Unsellable critical item".

If a binary schema symbol name is unclear, fix it in the binary schema. The improvement
propagates automatically to the UI.

### Handling unknown fields

Fields marked as `unknown` in the binary schema (e.g. padding bytes, undocumented
regions) are **not exposed in the project schema**. They are preserved transparently
on round-trip by the assembler, which carries them through unchanged. The user never
sees them.

---

## Widget Descriptor Layer

The widget descriptor layer sits between the project schema and the UI framework. It
is pure Python with no UI framework dependencies.

### Purpose

- Translates project schema fields into self-contained widget specifications
- Resolves the two-schema lookup (project schema + binary schema) once at
  descriptor build time
- Produces descriptors the UI can render without consulting any schema again
- Keeps framework-specific code isolated in the widget factory

### WidgetDescriptor

```python
@dataclass
class WidgetDescriptor:
    widget_type: str        # "text", "number", "dropdown", "checkbox_group",
                            # "resref_picker"
    label: str              # display name, derived from field name
    field_name: str         # project-level field name
    options: dict = None    # for dropdown/checkbox_group: {raw_value: display_label}
    min_val: int = None     # for number
    max_val: int = None     # for number
    nullable: bool = False
    picker: str = None      # for resref_picker: "bam", "dialog", "projectile",
                            # "generic"
```

### WidgetDescriptorFactory

**Constructor receives:**
- `binary_schema_loader` — the existing `SchemaLoader` instance
- `table_resolver` — the existing `TableResolver` instance (for IDS lookups if needed)

**`build(project_field, target_game)` method:**

1. Resolve binary field name via `from:` + target game
2. Look up binary schema for target game and resource type
3. Find binary field, using `section:` hint if provided, erroring on ambiguity
4. Build and return `WidgetDescriptor` based on project field type

**Binary field lookup — ambiguity handling:**

```python
def _find_binary_field(self, binary_schema, field_name, section_hint=None):
    if section_hint:
        section = binary_schema.get_section(section_hint)
        field = section.get_field(field_name)
        # raises if not found
        return field

    matches = []
    for section in binary_schema.sections:
        field = section.get_field(field_name)
        if field is not None:
            matches.append((section.name, field))

    if not matches:
        raise ValueError(f"Field '{field_name}' not found in schema")

    if len(matches) > 1:
        found_in = ", ".join(s for s, _ in matches)
        raise ValueError(
            f"Ambiguous field '{field_name}' in sections ({found_in}). "
            f"Add 'section:' to project schema field."
        )

    return matches[0][1]
```

**Display name formatting:**

```python
def _format_display_name(self, field_name):
    return field_name.replace("_", " ").capitalize()
```

**Type dispatch in `_build_descriptor`:**

- `strref` → `widget_type="text"`
- `resref` → `widget_type="resref_picker"`, passes through `picker` attribute
- `number` → `widget_type="number"`, passes through `min`/`max`
- `enum` → `widget_type="dropdown"`, options from `binary_field.attributes["values"]`
- `bitmask` → `widget_type="checkbox_group"`, options from `binary_field.attributes["flags"]`
- `text` → `widget_type="text"` (same as strref widget, different semantics)

For `enum` and `bitmask`, options are passed through directly from the binary schema.
No transformation. The binary schema is the single source of truth.

### Inspector population

```python
def populate_inspector(resource, section_name, session, factory, target_game):
    section = resource.project_schema.get_group(section_name)
    for field in section.fields:
        descriptor = factory.build(field, target_game)
        widget = WidgetFactory.create(descriptor)
        widget.set_value(resource.get(field.name))
        widget.on_change(lambda v, f=field:
            session.execute(
                FieldEditCommand(resource, f.name, resource.get(f.name), v)
            )
        )
        inspector_layout.add(widget)
```

---

## Session Object

The session is the central runtime object. It owns:

- The dependency graph
- The LRU cache of ephemeral nodes
- The set of persisted nodes
- The undo/redo stack
- The target game setting for the project

### Responsibilities

- `get(resref, resource_type)` — returns project object, loading/creating as needed
- `execute(command)` — applies command and pushes to undo stack
- `undo()` / `redo()` — standard undo/redo
- `save(resource)` — writes project file to disk, promotes ephemeral to persisted
- `export()` — triggers graph completion then writes mod files

### LRU cache

Ephemeral nodes are held in a bounded LRU cache. Suggested capacity: 200–500 objects.
Persisted nodes are never in the LRU cache — they live in a separate always-in-memory
dict.

Eviction is safe because ephemeral nodes are reconstructible from base game data.

---

## Assembler

The assembler translates between Layer 1 (binary `Resource` objects) and Layer 2
(project objects).

### Import direction (binary → project)

1. Load binary resource via existing `ResourceLoader`
2. Call `resource.to_dict()` to get serialized field values (IDS/2DA already resolved)
3. Walk project schema fields
4. For each field, extract value from the dict using `from:` mapping
5. For `from_bitfield:` fields, extract the sub-field value
6. Build project object with extracted values

Control fields (offsets, counts, indices) are discarded — they are binary layout
artifacts that the assembler reconstructs on export.

### Export direction (project → binary)

1. Walk project schema fields in section order
2. For each field, write value back to the correct binary field using `from:` mapping
3. For `from_bitfield:` fields, pack the sub-field back into the bitfield
4. For `text` type fields with IDS backing, perform reverse IDS lookup via
   `IdsHandler.lookup(symbol)`
5. Reconstruct control fields:
   - `offset_to_*` — calculated from section order during write
   - `count_of_*` — calculated from array lengths
   - `index_into_feature_blocks` / `count_of_feature_block` — calculated from
     nested Effects arrays per ability
   - `index_into_equipping_feature_blocks` / `count_of_equipping_feature_blocks` —
     calculated from Equipping Effects array length
6. Pass reconstructed binary resource to existing `BinaryParser.write()`

### Unknown fields

Binary fields not referenced by any project schema field are carried through unchanged.
The assembler reads the full binary resource, modifies only the fields it knows about,
and writes the rest back verbatim.

---

## Complete Item Project Schema

This is the agreed schema for the ITM resource type. It serves as the reference
implementation and proving ground for the project schema system.

```yaml
name: Item
version: V1
resource_type: ITM

effect_fields: &effect_fields
  fields:
  - name: opcode_number
    type: number
    min: 0
    max: 65535
    section: feature_block

  - name: target_type
    type: enum
    section: feature_block

  - name: power
    type: number
    min: 0
    max: 255
    section: feature_block

  - name: parameter_1
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: parameter_2
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: timing_mode
    type: enum
    section: feature_block

  - name: dispel_resistance
    type: enum
    section: feature_block

  - name: duration
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: probability_1
    type: number
    min: 0
    max: 100
    section: feature_block

  - name: probability_2
    type: number
    min: 0
    max: 100
    section: feature_block

  - name: resource
    type: resref
    picker: generic
    section: feature_block

  - name: dice_thrown_maximum_level
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: dice_sides_minimum_level
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: saving_throw_type
    type: bitmask
    section: feature_block

  - name: saving_throw_bonus
    type: number
    min: -20
    max: 20
    section: feature_block

groups:

  - name: Identity
    fields:

    - name: identified_name
      type: strref

    - name: unidentified_name
      type: strref

    - name: identified_description
      type: strref

    - name: unidentified_description
      type: strref

    - name: inventory_icon
      type: resref
      picker: bam

    - name: ground_icon
      type: resref
      picker: bam

    - name: description_icon
      type: resref
      picker: bam
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: dialog
      type: resref
      picker: dialog
      games: [PST, PSTEE]

    - name: conversable_label
      type: strref
      games: [PST, PSTEE]

  - name: Properties
    fields:

    - name: item_type
      type: enum
      section: header

    - name: weight
      type: number
      min: 0
      max: 65535

    - name: price
      type: number
      min: 0
      max: 4294967295

    - name: stack_amount
      type: number
      min: 1
      max: 65535

    - name: lore_to_id
      type: number
      min: 0
      max: 65535

    - name: enchantment
      type: number
      min: 0
      max: 255

    - name: weapon_proficiency
      type: text
      section: header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: paperdoll_animation_colour
      type: number
      min: 0
      max: 65535
      games: [PST, PSTEE]

  - name: Requirements
    fields:

    - name: min_level
      type: number
      min: 0
      max: 65535

    - name: min_strength
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_strength_bonus
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_intelligence
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_dexterity
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_wisdom
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_constitution
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_charisma
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

  - name: Flags
    fields:

    - name: flags
      type: bitmask
      section: header

    - name: usability_bitmask
      type: bitmask
      section: header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: usability_bitmask
      type: bitmask
      section: header
      games: [PST, PSTEE]

  - name: Abilities
    repeating: true
    from_section: extended_header
    fields:

    - name: attack_type
      type: enum
      section: extended_header

    - name: id_req
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: location
      type: enum
      section: extended_header

    - name: use_icon
      type: resref
      picker: bam
      section: extended_header

    - name: target_type
      type: enum
      section: extended_header

    - name: count_of_target
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: range
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: launcher_required
      type: enum
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: projectile_type
      type: enum
      section: extended_header
      games: [PST]

    - name: speed_factor
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: thac0_bonus
      type: number
      min: -128
      max: 127
      section: extended_header

    - name: dice_sides
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: dice_thrown
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: damage_bonus
      type: number
      min: -32768
      max: 32767
      section: extended_header

    - name: damage_type
      type: enum
      section: extended_header

    - name: alternative_dice_sides
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: alternative_dice_thrown
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: alternative_damage_bonus
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: max_charges
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: charge_depletion_behaviour
      type: enum
      section: extended_header

    - name: flags
      type: bitmask
      section: extended_header

    - name: projectile_animation
      type: text
      section: extended_header

    - name: melee_animation_overhand
      from_bitfield:
        field: melee_animation
        subfield: overhand
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: melee_animation_backhand
      from_bitfield:
        field: melee_animation
        subfield: backhand
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: melee_animation_thrust
      from_bitfield:
        field: melee_animation
        subfield: thrust
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: arrow_qualifier_is_arrow
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: bolt_qualifier_is_bolt
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: bullet_qualifier_is_bullet
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: Effects
      repeating: true
      from_section: feature_block
      <<: *effect_fields

  - name: Equipping Effects
    repeating: true
    from_section: feature_block
    equipping: true
    <<: *effect_fields
```

---

## Open Questions

The following questions were identified but not resolved at the time this document
was written. They should be addressed before or during implementation.

**1. Duplicate field names in Flags group**

The `usability_bitmask` field appears twice in the Flags group, distinguished only by
`games:` tag. The project schema loader needs explicit handling for this — two fields
with the same name that are mutually exclusive by target game. Decide whether this is
valid schema syntax or whether they need distinct project-level names (e.g.
`usability_bitmask_bg`, `usability_bitmask_pst`) with `from:` pointing at the same
binary field.

**2. Unknown fields on round-trip**

Binary fields not covered by the project schema (unknown padding, undocumented regions)
must be preserved on round-trip. The assembler strategy for this has not been fully
specified. Options:
- Store unknown fields as opaque blobs attached to the project object
- Always re-parse from base game on export and overlay only the known changes
- Track original binary bytes per-section and write them back for uncovered ranges

**3. kit_usability fields**

The four `kit_usability_1` through `kit_usability_4` bytes in BG/EE binary schemas
have no semantic definition in the current binary schemas (raw bytes). Decide whether
to expose them as raw numeric fields, research their meaning and add proper bitmask
definitions, or omit them from the project schema entirely.

**4. Validation**

Field validation (min/max enforcement, resref existence checks, strref validity) has
been identified as necessary but not designed. Suggest: validation logic lives in the
project schema (a `validate:` attribute per field) and runs in the command's `apply()`
before committing. Failed validation rejects the command and the widget reverts.

**5. PST extra_data in effects**

PSTEE and PST CRE/ITM effects have an additional 216-byte `extra_data` field
(EFF V2 structure). This is not currently covered in the effect_fields anchor. Decide
whether to expose it as a structured sub-object or carry it as an opaque blob.

---

## Implementation Order

1. **Project schema loader** — parse the YAML format described above into an object
   model analogous to the existing `SchemaLoader` / `Schema` / `Section` / `Field`
   hierarchy. Support `groups`, `repeating`, `from_section`, `from_bitfield`,
   `equipping`, `games`, YAML anchors.

2. **Assembler — import direction** — given a binary `Resource` object and a project
   schema, produce a project object. Validate against the ITM schema using real game
   files.

3. **Session object** — LRU cache, persisted node tracking, undo stack, target game
   setting.

4. **Assembler — export direction** — given a project object, produce a binary
   `Resource` object ready for `BinaryParser.write()`. Validate round-trip fidelity
   against known good files.

5. **WidgetDescriptorFactory** — as specified above.

6. **UI / Inspector** — consumes descriptors, renders widgets, routes changes through
   session commands.

Background dependency indexing (Phase 2 graph completion) can be developed in parallel
with steps 3–4 as it has no dependencies on the UI layer.
