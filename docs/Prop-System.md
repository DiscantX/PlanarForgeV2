# Prop System

> **Status: concept only.** Props were planned as part of the editor's scene layer but were never designed in detail or implemented. This page records the idea as the maintainer remembers it (November 2026). Everything under [Open questions](#open-questions) was not decided. Nothing here should be read as a specification.

## The idea

The Infinity Engine has no notion of a movable object that is part of the scenery. An area's background is a [tileset](Format-Notes.md#tileset-files-tis-in-biff-archives) (TIS) drawn once and fixed in place. The things that make the area behave (walls, doors, regions, containers and so on) are described by separate files and sections: the WED holds map geometry and wall polygons, and the ARE holds actors, regions, containers and similar entries (see [Relational Logic in WED](Relational-Logic-in-WED.md) and the schemas in `drivers/InfinityEngine/definitions/schemas/`). In the original formats, a table or a tree is not an object. It is a few pixels in the background image plus, perhaps, some bounding geometry in a different file.

A **prop** is a project-level object that adds the missing concept. A prop would be something like a table or a tree: a single thing with a sprite, a bounding box and whatever else it needs, which the user can place, move and delete in the editor like any other object.

Props are an additional layer on top of the engine's own model. They exist only in the project, as project files in the sense of [Layer 2](Layer2-Overview.md). The engine never sees them.

## Using props

The intended workflow, as described by the maintainer:

* The user places **pre-made props** in a scene, or **creates their own**, defining the sprite, the bounding box and whatever other properties are relevant.
* Placed props can be moved, deleted and otherwise edited at will, with the usual [undo and redo](Layer2-Undo-Redo.md) support expected of any Layer 2 edit.

## Export: flattening to the original formats

Props are removed at export. When the user exports the scene, every prop is **flattened** into the original Infinity Engine representation, so that the result is an ordinary area the unmodified game can load. The intent is that this happens seamlessly, without the user having to think about the original format.

This follows the same principle as the rest of the architecture: the project layer is free to be richer than the binary formats, and the compile step down to [Layer 1](The-Three-Layer-Model.md#layer-1-ie-binary-formats) is where the richness is translated back. Export as a whole is described in the [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md).

## Where props fit

| Layer | Role of props |
|-------|---------------|
| Layer 1 (binary formats) | None. Props have no binary form of their own. |
| Layer 2 (project format) | Props are stored as project files, alongside the scene that uses them. See [Project Format and Schemas](Project-Format-and-Schemas.md). |
| Layer 3 (editor) | Placement, movement, deletion, and a way to author new props. See [Scene Assembly](The-Three-Layer-Model.md#scene-assembly). |

## Open questions

These all follow from the description above and none was settled.

1. **What a prop contains.** A sprite and a bounding box were named. The full list of properties was not recorded. Settling it means surveying the Infinity Engine file types and deciding which of their information a prop should carry.
2. **How flattening works for the visible part.** The background is baked into tiles in a TIS. How a prop's sprite would be merged into that image, and what that means for the tile data the project stores, is not decided.
3. **How flattening works for the behavioural part.** A prop's bounding box would have to become entries in the engine's own structures. Which ones, and how a prop that touches more than one file (for example both walls and an ARE entry) is handled, is not decided.
4. **Where a prop is stored.** Whether props belong to a single scene, are shared across scenes like other assets (see [Asset Management](Asset-Management.md)), or both, is not decided.
5. **Pre-made props.** Where they come from and whether they ship with the editor, are user libraries, or are extracted from existing game areas is not decided.
6. **Export from an area that already exists.** Importing an existing game area yields no props, only a flat background. Whether any props could be recovered from it was not discussed.

## See also

* [The Three-Layer Model](The-Three-Layer-Model.md)
* [Layer 2 Overview](Layer2-Overview.md)
* [Asset Management](Asset-Management.md)
* [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md)
