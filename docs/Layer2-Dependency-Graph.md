# Layer 2: The Dependency Graph

Game resources refer to each other constantly: a creature names its dialogue, its items and its scripts; an item names its icon and spells. A mod editor needs to know these links to answer questions such as "what uses this item?", to warn before deleting something that is still in use, and to gather every resource a mod depends on when exporting it. This page describes how PlanarForge records those links, how the record is built without freezing the interface, and where it deliberately stops.

## What is tracked

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

## What is NOT tracked

- BCS script internals (scripts treated as opaque)
- TLK strref integers (not meaningful cross-resource dependencies)
- Unmodified base game resources that have never been accessed

## Graph completeness and background indexing

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

## Implicit import on open

Opening any base game resource automatically creates an ephemeral project object for
it. There is no separate "import" step. The moment a resource is viewed in the editor,
it has a Layer 2 representation.

If the user edits it, it becomes persisted. If not, it stays ephemeral and may be
evicted from the LRU cache.

Recursive dependency closure (pulling in a resource and all its dependencies) is
available as an explicit **"Import with dependencies"** operation, and is also
triggered automatically during export preparation.

## Asset boundary

The recursive closure stops at the **asset boundary** — resources that have no project
schema (BAM, WAV, TIS, etc.) become leaf nodes referenced by resref string but not
expanded further. They appear in the graph but do not become project objects.

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Project Model and Session](Layer2-Project-Model.md)
* [Asset Management](Asset-Management.md): how the project's own asset pool and its dependency lookups are described there
* [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md): where the closure of dependencies is used at export
