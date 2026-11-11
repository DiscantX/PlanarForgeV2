# Project Format and Schemas

The Project Layer (Layer 2) defines how game data is stored in a human-readable, version-control-friendly format. Unlike Layer 1, this layer discards unknown bytes and focuses on semantic editing.

## Directory Structure

A PlanarForge project is organized as follows:

```yaml
MyMod/
  project.yaml          # Project metadata
  assets/               # Shared pool (BAM, portraits, sounds)
  scenes/               # Area scene files (.scene, .tis, .mos)
  creatures/            # .creature files
  items/                # .item files
  exports/              # Compiled output (gitignored)
```

## Resource Identity (New vs. Derived)

Every project resource tracks its origin to determine how it should be exported:

1. **New Resources**: Created from scratch. Exported as a full `COPY` command.
2. **Derived Resources**: Based on a game asset. The editor tracks the `base_resref`. On export, a diff is computed against the base game to generate `WRITE_BYTE/LONG` patches.

### Example .creature File

```yaml
resref: BANDIT_CUSTOM
type: creature
game: BG2EE
origin: derived
base_resref: BANDIT
data:
  name: 12345
  hp: 45
  script_override: my_script
```

## Schema Hierarchy

Three distinct schema types manage the data lifecycle:

| Schema Type | Directory | Purpose |
|-------------|-----------|---------|
| **Format** | `schemas/formats/` | Defines the Layer 1 binary layout (e.g., `itm_v1.yaml`). |
| **Project** | `schemas/project/` | Defines the Layer 2 semantic structure (e.g., `item.yaml`). |
| **Scene** | `schemas/scene/` | Defines how to merge ARE, WED, and TIS into a unified Scene object. |

## Projection-Based Indexing

To maintain high performance, the resource indexer does not cache the full content of these files. Instead, it uses a **Projection**:

* Only critical metadata (ResRef, Display Name, Weight, Price) is cached for searching.
* The full data is loaded into memory only when the user opens the resource for editing.