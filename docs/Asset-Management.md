# Asset Management

Assets (BAMs, Portraits, Sounds, Tilesets) are stored in a flat shared pool within the `assets/` directory. This architecture reflects the high degree of asset reuse within the Infinity Engine.

## Asset Mapping

| Asset Type | Location | Rationale |
|------------|----------|-----------|
| **TIS (tileset)** | `scenes/AR0001/` | 1:1 relationship with a specific scene. |
| **MOS (minimap)** | `scenes/AR0001/` | 1:1 relationship with a specific scene. |
| **BAM (sprites)** | `assets/bam/` | Shared across multiple items, spells, and creatures. |
| **Sounds** | `assets/sounds/` | Shared global audio pool. |

## The BAM Decision

BAM files are currently treated as **opaque binary assets**.

* **Strategy**: The editor stores the original `.bam` file. References in Layer 2 resources point to the relative path within the `assets/` pool.
* **Future**: If a BAM editor is implemented, they may be promoted to a `.animation` project format.

## Resource Dependency Graph

The editor maintains a global graph of all asset references. This enables:

* **"Used By" Lookups**: See every item that uses a specific inventory icon.
* **Safe Deletion**: Warn users if deleting an asset will break existing resources.
* **Smart Export**: Automatically include all referenced assets in the final WeiDU package.