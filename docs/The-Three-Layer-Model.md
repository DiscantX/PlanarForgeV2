# The Three-Layer Data Model

PlanarForgeV2 is built on a tiered architecture designed to isolate the complexities of the legacy Infinity Engine formats from the modern UI/UX of the editor.

## Layer 1: IE Binary Formats

* **Purpose**: Interaction with raw `.are`, `.cre`, `.itm` files.
* **Components**: `BinaryParser`, `ResourceLoader`, and the YAML schemas in `drivers/InfinityEngine/definitions/schemas/`.
* **Philosophy**: This layer is concerned with **fidelity**. It preserves unknown bytes, handles legacy offset logic, and ensures that the binary stream is valid for the game engine.

## Layer 2: Project Format

* **Purpose**: A clean, modern representation of game objects for version control and human readability.
* **Extension**: `.creature`, `.item`, `.scene`.
* **Philosophy**: Unknown byte preservation **stops here**. Once data enters Layer 2, it is a semantic representation. If a byte isn't mapped to a field name in a project schema, it is discarded. This creates a stable base for modding and diffing.

## Layer 3: Editor / UI

* **Purpose**: The visual workspace (Scene Assembly, Inspector Panels, etc.).
* **Philosophy**: The UI interacts exclusively with Layer 2. It never sees raw offsets or binary padding.

---

## The Boundary of Fidelity

When a resource is loaded from a game BIF:

1. It is parsed into Layer 1.
2. If unmodified, it can be written back to Layer 1 with 100% fidelity.
3. If the user begins editing, the resource is "promoted" to Layer 2.
4. Upon export, Layer 2 is compiled back to Layer 1, producing a "clean" binary file without legacy garbage data.

## Scene Assembly

Areas are unique because they are composites. A "Scene" in PlanarForge is a Layer 2 object that aggregates multiple Layer 1 resources:

* **ARE**: Actor and trigger placement.
* **WED**: Map geometry and polygons.
* **TIS**: Graphical tilesets.
* **BMP**: Search and light maps.

The **SceneAssembler** component is responsible for merging these disparate resources into a single cohesive workspace.