# Game Asset Policy

PlanarForge reads files that belong to commercial games. This page states what may and may not be stored in this repository, and how to write tests without breaking that rule.

## The rule

**No game assets are stored anywhere in the project**: not in the source tree, not in `docs/`, not on any branch, and not in issue or pull request attachments.

## What counts as a game asset

Any file or file fragment extracted from, or copied out of, a game installation. This covers:

* Resource files in any Infinity Engine format: `ARE`, `BAM`, `CRE`, `ITM`, `SPL`, `TIS`, `WED`, `MOS`, `PLT`, `STO`, `TLK`, `2DA`, `IDS`, `BCS`, `DLG`, and the rest.
* Archives and indexes: `BIF`, `KEY`.
* Texture and media files, including converted forms such as `PVRZ` and `PVR`, and extracted images, audio, and video.
* Hex dumps or byte arrays that reproduce a meaningful part of a resource.

The [Asset Management](Asset-Management.md) page uses "assets" differently: it describes how *project* resources are organised inside a mod. This policy is about *game* data.

## Why

The games and their data belong to their rights holders. A public repository that redistributes that data is a distribution channel for it, even if the intent is only to debug a parser. Keeping the repository free of game data also means anyone can clone it without carrying content they have no right to redistribute.

## What is allowed

* **Reading game files from a local installation at run time.** The tool finds installed games through `InstallationFinder` and reads them in place. Nothing is copied into the working tree.
* **Reporting facts about files**: resource names (resrefs), sizes, offsets, field names, counts, and checksums. The gap allowlist in `tools/tests/gap_allowlist.json` is an example: it records file names and byte offsets, not content.
* **Quoting a few bytes or fields to explain a format**, as the documentation does when it describes a header. Quotations must be short and illustrative, never a usable reproduction of a file.

## Testing without game files

Tests that need real game data currently read it from a local installation, so they only run on a machine where the game is installed. For tests that must run anywhere, build **synthetic fixtures**: small files that we author ourselves, for example by writing a few bytes with `struct.pack` that follow the schema. A synthetic fixture should be:

* constructed by code in the test, or by a generator script kept in the repository;
* minimal, with only the fields the test needs;
* clearly labelled as synthetic.

## Safeguards

* `.gitignore` excludes the common resource extensions and the `game-data/` and `extracted/` directories. If a genuinely synthetic fixture matches an ignored pattern, add an explicit `!` exception for that one path and say why in the commit message.
* Before pushing, run `git status` and look for unfamiliar binary files.

## If an asset is committed by mistake

1. Do not push. Remove the file from the commit, or rewrite the local history to drop it.
2. If it has already been pushed, tell the maintainer straight away. Deleting a branch is not enough on its own, because GitHub keeps commits reachable by their hash for some time; the history must be rewritten and, where needed, GitHub Support asked to purge the cached objects.
