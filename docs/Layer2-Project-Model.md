# Layer 2: The Project Model and Session

This page explains what a PlanarForge *project* is on disk, how resources move between being merely viewed and being part of the project, and how the *session* object coordinates everything at run time. Terms used throughout the Layer 2 pages: a **resource** is one game file (for example an item or a creature) identified by a *resref*, a name of up to eight characters; a **node** is the in-memory object for one resource; **ephemeral** means "reconstructible from the base game on demand".

The design choice at the heart of this page is that a project directory contains only what the modder has changed. Everything else is read from the game installation when needed.

## Project file model

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

## Session object

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

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Dependency Graph](Layer2-Dependency-Graph.md): how references between resources are tracked, and how opening a resource creates an ephemeral node
* [Undo and Redo](Layer2-Undo-Redo.md): how edits move a node from ephemeral to persisted
* [Project Format and Schemas](Project-Format-and-Schemas.md): the on-disk layout and the *new* versus *derived* resource distinction
