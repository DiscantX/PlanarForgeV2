# Layer 2: Overview

Layer 2 is PlanarForge's project-level editing layer. Where [Layer 1](The-Three-Layer-Model.md#layer-1-ie-binary-formats) deals with the raw binary game files (`.cre`, `.itm`, `.are` and so on), Layer 2 deals with human-editable *project files* (`.creature`, `.item`, `.scene` and so on) that the editor's user interface operates on exclusively.

The key principle: **the UI never touches Layer 1 directly.** It reads and writes Layer 2
project objects. The assembler handles translation between layers.

## Status

Layer 1 is implemented and passes the round-trip fidelity tests recorded in [Round-trip Fidelity](Round-trip-Fidelity.md). **Layer 2 is designed but not implemented.** The pages below record the design in full, so that implementation can proceed without the original design session. Five questions remain open: see [Open Questions](Layer2-Open-Questions.md).

## Map of the design

| Page | Covers |
|------|--------|
| [Project Model and Session](Layer2-Project-Model.md) | What is written to disk, ephemeral versus persisted resources, the session object and its cache |
| [Dependency Graph](Layer2-Dependency-Graph.md) | Tracking references between resources, background indexing, the asset boundary |
| [Undo and Redo](Layer2-Undo-Redo.md) | The command pattern, compound commands, the first-edit transition |
| [Project Schema Format](Layer2-Schema-Format.md) | The YAML format for project schemas and its attributes |
| [Widget Descriptors](Layer2-Widget-Descriptors.md) | Turning schema fields into framework-independent widget specifications |
| [Assembler](Layer2-Assembler.md) | Translating between binary resources and project objects |
| [Item Project Schema](Layer2-Item-Schema.md) | The complete reference schema for items |
| [Open Questions](Layer2-Open-Questions.md) | Unresolved design questions |

## Implementation order

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

## See also

* [The Three-Layer Model](The-Three-Layer-Model.md): where Layer 2 sits in the whole architecture
* [Project Format and Schemas](Project-Format-and-Schemas.md): the on-disk layout and the *new* versus *derived* distinction
* [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md): how Layer 2 objects become a mod
* [Project Status](Project-Status.md)
