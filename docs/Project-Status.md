# Project Status

*Last reviewed: 2026-11-14, during the revival of the project after several months of inactivity.*

PlanarForge is a modding and file-viewing tool for the Infinity Engine games (Baldur's Gate, Planescape: Torment, and the Icewind Dale series, including their Enhanced Editions). Its core idea, described in [The Three-Layer Model](The-Three-Layer-Model.md), is that every binary file format is described once, in a YAML schema, and a generic parser and writer interpret those schemas. This page records what works, what does not, and what is waiting on what.

## At a glance

| Area | State | Where to read more |
|------|-------|--------------------|
| Layer 1: schema-driven reading and writing (ARE, ITM, SPL, CRE, WED) | Complete; round-trip fidelity milestone recorded 2026-04-03 | [Round-trip Fidelity](Round-trip-Fidelity.md), [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md) |
| WED V1.3 relational engine (pointer-based sections, computed fields) | Complete | [Relational Logic in WED](Relational-Logic-in-WED.md), [WED V1.3 Engine Upgrade](WED-V1.3-Engine-Upgrade.md) |
| Other schemas (BAM, KEY, BIFF, STO, PRO, VVC, PLT) | Present; not covered by the fidelity documentation | [Project Priorities](Project-Priorities.md) |
| Image viewer: BAM playback, controls, grid overlay | Implemented on `main`; not re-verified since the revival | `tools/image_viewer/` |
| Image viewer: TIS (tileset) rendering | Fixed on `main`: BIFF tileset entries are selected by the locator bits, the PVRZ decoder was rewritten, and `tools/tis_diagnostic.py` and `tools/pvrz_scan.py` exist for checking real installs. The TIS scan has only been run on BG2EE (460 tilesets, no anomalies); the PVRZ scan matches the documented layout on BG2EE, IWDEE and PSTEE. Loading time is still slow ([issue #49](https://github.com/DiscantX/PlanarForgeV2/issues/49)) | [Format Notes](Format-Notes.md#tileset-files-tis-in-biff-archives) |
| ARE writer for overlapping section offsets (PST format) | Latent bug. The original PST layout has not been tested since the revival, because the installed games are all Enhanced Editions | [issue #6](https://github.com/DiscantX/PlanarForgeV2/issues/6) |
| Distinguishing PST from PSTEE ARE files | Latent bug; the current heuristic is unreliable by construction, but every PSTEE area in the installed game routes and round-trips correctly | [issue #7](https://github.com/DiscantX/PlanarForgeV2/issues/7) |
| Layer 2: project format | Designed, not implemented; five design questions remain open | [Layer 2 Overview](Layer2-Overview.md), [Open Questions](Layer2-Open-Questions.md) |
| Widget descriptor layer, IDS-resolved field round-trip | Designed, not implemented | [Widget Descriptors](Layer2-Widget-Descriptors.md), [Assembler](Layer2-Assembler.md) |
| WeiDU export pipeline | Design phase | [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md) |
| MCP server (letting an AI assistant inspect the running program) | Planned next, read-only; not started | none yet |

## Latest ARE round-trip run

On 2026-11-14 the round-trip suite (`python tools/tests/test_suite.py --test 2 --schema ARE --game BG2EE,IWDEE,PSTEE --audit-gaps`) re-read and re-wrote every area in the three installed games: 804 files (423 BG2EE, 173 IWDEE, 208 PSTEE) with no differences and no unmapped bytes. Four PSTEE areas (AR0501, AR1001, AR13WZ, AR3017) carry allowlisted regions that Near Infinity also treats as unused; three of them are pointed to by a header offset, which is still to be explained. A byte-exact round trip shows that reading and writing agree with each other, not that the schemas name every field correctly; that is what the IESDP review checks. See [Round-trip Fidelity](Round-trip-Fidelity.md).

## How to read the "complete" claims

The fidelity results were produced against real game installations, and the claims are recorded in the engineering logs rather than in automated tests that run anywhere. Three consequences follow.

1. **They cannot be re-checked without the games.** Baldur's Gate II: Enhanced Edition, Icewind Dale: Enhanced Edition and Planescape: Torment: Enhanced Edition are currently installed on the maintainer's machine. Results for the original Planescape: Torment and for Icewind Dale II were obtained earlier and cannot be reproduced until those games are installed again.
2. **Game data may never be committed.** The rules are set out in the [Game Asset Policy](Game-Asset-Policy.md). Tests that need real files read them from a local installation, and no test fixture may contain game content.
3. **Some past conclusions need re-checking.** The upstream format references contain errors, and some have since been corrected, so the project's own notes about them can go stale. [Format Notes](Format-Notes.md#how-much-to-trust-the-references) lists the cases known so far.

## What is in flight

* [Issue #14](https://github.com/DiscantX/PlanarForgeV2/issues/14) and [issue #40](https://github.com/DiscantX/PlanarForgeV2/issues/40): test suite usage and the image viewer import, both with open pull requests.
* [Issue #34](https://github.com/DiscantX/PlanarForgeV2/issues/34): Scene Assembly and UI Architecture pages.
* [Issue #49](https://github.com/DiscantX/PlanarForgeV2/issues/49): TIS loading time.

Next, in order: the MCP server; a review of the ARE schemas against IESDP; synthetic test fixtures for issues #6 and #7 and then the fixes, with the original Planescape: Torment as the real-data check once it is installed; then the formats an area references (the second tier of "full ARE support") and Layer 2.

## How work is tracked

Every change has an issue, and every issue is closed by the pull request that makes the change. See [Workflow and Conventions](Workflow-and-Conventions.md).
