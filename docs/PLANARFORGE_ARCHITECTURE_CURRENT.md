# PlanarForge — Architecture & Design Document

## Purpose

This document consolidates architectural decisions made across multiple planning sessions for PlanarForge, an Infinity Engine mod editor. It is intended to serve as a reference for both human developers and AI collaborators resuming work on the project.

---

## Project Overview

PlanarForge is a modern development environment for Infinity Engine games (BG1, BG2, BGEE, BG2EE, IWDEE, PSTEE, IWD, IWD2, PST). It is currently at **Stage 1/2** — a working binary parser/writer with round-trip fidelity across major IE formats.

The long-term goal is a scene-based area editor with a modern IDE-style UX, comparable to tools like Godot or VS Code.

---

## Development Stages

| Stage | Description | Status |
|-------|-------------|--------|
| 1 | Binary parsing (ARE, ITM, SPL, CRE, WED, etc.) | ✅ Complete |
| 2 | Resource editing with round-trip fidelity | ✅ Complete |
| 3 | Area visualization (render TIS, overlay BMPs) | 🔜 Near-term |
| 4 | Scene editing / area authoring | 🔲 Long-term |
| 5 | Advanced tools (terrain, procedural props, WeiDU export) | 🔲 Future |

---

## Current Backend State

- **Schema-driven binary parser/writer** — YAML schemas define IE binary formats; a generic `BinaryParser` reads/writes all formats
- **Round-trip fidelity** — Unmodified resources produce byte-identical output; modified resources produce clean, valid repacked files
- **Unknown byte policy** — Unmodified files: preserve unknown bytes for fidelity. Modified files: discard unknown bytes; only valid semantic fields are written
- **Game family support** — Separate schemas per game family (BG1/BG2, EE, PST, PSTEE, IWD, IWD2) with routing logic in `ResourceLoader`
- **Formats covered** — ITM, SPL, CRE, ARE, WED, KEY/BIFF, TLK, IDS, 2DA, VVC, plus supporting types
- **Gap audit framework** — Tracks unmapped bytes, classifies them, supports allowlisting known-safe gaps
- **Resource indexer** — Builds searchable index of game resources; currently caches full `to_dict()` output (known performance issue — see open questions)

---

## Data Layer Architecture

### Three Layers

```
Layer 1 — IE Binary Formats
  Described by: schemas/formats/ (existing YAML schemas)
  Handled by:   BinaryParser, ResourceLoader
  Output:       Parsed resource objects

Layer 2 — Project Format (to be built)
  Described by: schemas/project/ (new per-type schemas)
  Handled by:   SceneAssembler, ProjectLoader
  Output:       .creature, .item, .scene, etc. project files

Layer 3 — Editor / UI
  Works with:   Layer 2 project objects
  Never sees:   Raw binary or Layer 1 internals
```

### Key Rule
The boundary between Layer 1 and Layer 2 is where unknown byte preservation stops. Once a resource enters the project format, it is a clean modern representation. Unknown fields are discarded.

---

## Project File Format

### Directory Structure

```
MyMod/
  project.yaml          # project metadata
  assets/               # shared assets (BAM, portraits, sounds)
    bam/
    portraits/
    sounds/
  scenes/               # area scene files
    AR0001/
      AR0001.scene      # unified area scene
      AR0001.tis        # 1:1 with scene, lives here
      AR0001.mos
  creatures/
    bandit.creature
  items/
    sword.item
  spells/
    fireball.spell
  dialogs/
    bandit.dialog
  scripts/
    bandit_ai.script
  props/                # editor-native prop definitions
  exports/              # compiled output (gitignored)
```

### project.yaml

```yaml
name: My Mod
target_game: BG2EE
game_path: /path/to/bg2ee
author: Author Name
version: 0.1.0
```

### Resource File Format

Each project resource carries metadata indicating its origin:

```yaml
resref: BANDIT_CUSTOM
type: creature
game: BG2EE
origin: new           # "new" = created from scratch, "derived" = based on existing
base_resref: null     # populated for derived resources, e.g. "BANDIT"
data:
  name: 12345
  hp: 45
  script_override: my_script
```

- **New resources** → `COPY` in WeiDU export
- **Derived resources** → `COPY_EXISTING` + `WRITE_*` patches in WeiDU export (diff computed at export time against base game)

---

## Project Schemas

Two new schema layers sit above the existing binary format schemas:

### Schema Directory Layout

```
schemas/
  formats/      # existing binary schemas (are_v1_ee.yaml, wed_v1_3.yaml, etc.)
  project/      # per-type project schemas (creature.yaml, item.yaml, etc.)
  scene/        # scene assembly schemas (scene_bg2ee.yaml, etc.)
  types/        # shared type definitions (vertex, polygon, etc.)
```

### Project Type Schemas

Each resource type gets a project schema defining its clean, editor-friendly structure, independent of the binary layout. Example:

```yaml
# schemas/project/creature.yaml
name: creature
version: V1
games: [BG2EE, BGEE, IWDEE, PSTEE]

sections:
  identity:
    fields:
      - name: long_name
        type: strref
        from: header.long_name
      - name: short_name
        type: strref
        from: header.short_name

  combat:
    fields:
      - name: hp
        type: word
        from: header.current_hit_points
      - name: thac0
        type: byte
        from: header.thac0
```

Unknown fields are not mapped and are not preserved.

### Scene Assembly Schemas

Scene schemas define how multiple parsed IE resources are assembled into a unified scene object:

```yaml
# schemas/scene/scene_bg2ee.yaml
name: SCENE
version: V1
games: [BG2EE, BGEE]

sources:
  are: ARE
  wed: WED
  tis: TIS
  search_map: BMP_SR
  height_map: BMP_HT
  light_map: BMP_LM

doors:
  fields:
    - name: name
      from: are.sections.doors[*].name
    - name: id
      from: are.sections.doors[*].door_id
    - name: flags
      from: are.sections.doors[*].flags
    - name: polygon_closed
      from: wed.sections.polygons
      resolve: are.sections.doors[*].index_of_first_outline_vertex_closed
```

### Shared Types

```yaml
# schemas/types/spatial.yaml
types:
  vertex:
    fields:
      - name: x
        type: word
      - name: y
        type: word

  polygon:
    fields:
      - name: vertices
        type: array
        element: vertex
```

---

## Asset Management

Assets are stored in a flat shared pool rather than alongside the resources that reference them. This reflects the reuse patterns of IE assets:
(Note: investesgation reveals TIS files are somewhat shared across multiple resources. It wil need to be dicided if these should be stored seperate from the scene).

| Asset Type | Location | Rationale |
|------------|----------|-----------|
| TIS (tileset) | `scenes/AR0001/` | 1:1 with scene |
| MOS (minimap) | `scenes/AR0001/` | 1:1 with scene |
| BAM (animations) | `assets/bam/` | Shared across many resources |
| Portraits | `assets/portraits/` | Shared |
| Sounds | `assets/sounds/` | Shared |

Resources reference assets by path:
```yaml
inventory_icon: assets/bam/sw1h01.bam
```

---

## Parsed Resource Lifecycle

```
Binary file
    ↓
BinaryParser (Layer 1)
    ↓
Parsed resource object
    ↓
SceneAssembler / ProjectLoader (Layer 2)
    ↓
Project file (.scene, .creature, .item, etc.)
    ↓  [parsed resource retained silently for export only]
Editor operates on project files
    ↓
Export pipeline
    ↓
Clean binary output + WeiDU patch scripts
```

The parsed resource is retained after scene assembly **only** to provide field values for export that were not mapped into the project schema. It is never surfaced in the editor UI.

---

## Resource Indexer (Performance Issue)

The current `ResourceIndexer` stores full `to_dict()` output per resource, causing large cache files and slow load times. The planned fix is a **projection-based index**:

- Each resource type defines a small set of fields to index (resref, display name, key scalars like price/weight/type)
- Only those fields are cached
- Full resource data is loaded on demand when a resource is opened

This balances fast search with fast startup.

---

## UI Architecture (Planned)

### Layout

```
+----------------------------------------------------+
| Menu Bar / Toolbar / Command Palette               |
+----------------------------------------------------+
| Browser Panel | Workspace Tabs  | Inspector Panel  |
|               |                 |                  |
|               |  Area Editor /  |                  |
|               |  Resource Editor|                  |
+----------------------------------------------------+
| Bottom Panel (logs, search, compiler output)       |
+----------------------------------------------------+
```

All panels are dockable.

### Key UI Concepts

- **In-game UI recreation** — Inventory, spellbook, and record screens recreated using original CHU/BAM assets as interactive editing surfaces
- **Resource browsers** — Icon grid and list views, filterable, drag-and-drop sources
- **Inspector panel** — Auto-generated from project schemas; field types map to widgets (strref → text field, resref → resource picker, enum → dropdown, bitmask → checkboxes)
- **Workspace tabs** — Each resource opens in a tab; tab type determined by resource type

### Resource Dependency Graph

Every resource reference is tracked as an edge in a graph. Enables:
- "Used by" lookup
- Safe delete warnings
- Automatic export packaging
- WeiDU diff generation

---

## Prop System (Long-Term / Stage 4+)

Editor-native objects that don't exist in IE formats. Defined in `.prop` files:

```yaml
name: Wooden Table
sprite: assets/props/table01.png
collision: polygon
blocks_search_map: true
height_offset: 8
generates_container: false
```

On export, props are flattened into:
- TIS tile changes
- WED wall polygon additions
- Search map pixel edits
- Height map edits

This is a Stage 4+ feature requiring complete TIS and WED writers.

---

## WeiDU Integration (Planned)

Export pipeline output:

```
Project files
    ↓
Compiler (project → binary resources)
    ↓
Diff against base game
    ↓
WeiDU script generator
    ↓
/MyMod/
  setup-MyMod.tp2
  /override or /resources
```

New resources → `COPY`
Modified resources → `COPY_EXISTING` + field patches

---

## Open Questions / Next Steps

1. **BAM files** — Treat as opaque imported assets, or give them a `.animation` project format with a BAM editor? This affects whether `assets/bam/` contains binary BAMs or source project files.

2. **Resource indexer** — Design and implement the projection-based index before UI work begins.

3. **Scene assembler** — The component that reads parsed Layer 1 resources and produces Layer 2 scene/project objects using the scene schemas. This is the next major backend piece to build.

4. **Project schema design** — Which fields are included in `.creature`, `.item`, `.spell`, etc.? Need to decide coverage per type.

5. **Undo/redo** — Must be a first-class concern before the editor is usable. Command pattern (`apply()` / `undo()`) is the planned approach.

6. **Virtual filesystem** — Should the editor model the IE resource resolution order (project → override → DLC → BIFs) explicitly? This affects how base game assets are referenced and how conflicts are detected.

7. **Area visualization** — First visual milestone. Requires rendering TIS tiles and overlaying ARE actors/regions. WED is already parsed; TIS parsing is the remaining piece.

---

## Resumption Prompt

Use the following prompt when starting a new chat to resume this work:

---

> I am building PlanarForge, a modern Infinity Engine mod editor in Python. Here is the architectural context you need:
>
> **Current backend state:** I have a working schema-driven binary parser/writer with round-trip fidelity across major IE formats (ITM, SPL, CRE, ARE, WED, KEY/BIFF, TLK, IDS, 2DA). Schemas are YAML files in `schemas/formats/`. A generic `BinaryParser` reads/writes all formats. Unknown bytes are preserved for unmodified files and discarded for modified files. Multiple game families are supported (BG1/BG2, EE, PST, PSTEE, IWD, IWD2) with separate schemas per family.
>
> **Architecture decisions made:** The project uses a three-layer data model: (1) IE binary formats handled by existing parser, (2) a project format layer with clean modern representations (.creature, .item, .scene, etc.), (3) the editor UI. Unknown fields are not preserved in the project format. A scene assembler will translate parsed Layer 1 resources into Layer 2 project objects using scene assembly schemas. Assets are stored in a flat shared pool. The resource dependency graph tracks all cross-resource references.
>
> **The design document is in PLANARFORGE_ARCHITECTURE.md** which I will share with you.
>
> The last thing we were discussing was BAM files — whether to treat them as opaque imported binary assets or give them a project-level `.animation` format. Before that we had settled on the project directory structure, the .scene/.creature/.item file format, and the scene assembly schema design.
>
> Please read the architecture document and then help me continue from the BAM question.

