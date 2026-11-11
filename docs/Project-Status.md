# Project Status

*Last reviewed: 2026-11-11, on reviving the project after several months of inactivity.*

PlanarForge is a modding and file-viewing tool for the Infinity Engine games (Baldur's Gate, Planescape: Torment, and the Icewind Dale series, including their Enhanced Editions). Its core idea, described in [The Three-Layer Model](The-Three-Layer-Model.md), is that every binary file format is described once, in a YAML schema, and a generic parser and writer interpret those schemas. This page records what works, what does not, and what is waiting on what.

## At a glance

| Area | State | Where to read more |
|------|-------|--------------------|
| Layer 1: schema-driven reading and writing (ARE, ITM, SPL, CRE, WED) | Complete; round-trip fidelity milestone recorded 2026-04-03 | [Round-trip Fidelity](Round-trip-Fidelity.md), [Engineering Log: Fidelity Fixes](Engineering-Log-Fidelity-Fixes.md) |
| WED V1.3 relational engine (pointer-based sections, computed fields) | Complete | [Relational Logic in WED](Relational-Logic-in-WED.md), [Engineering Log: WED Upgrade](Engineering-Log-WED-Upgrade.md) |
| Other schemas (BAM, KEY, BIFF, STO, PRO, VVC, PLT) | Present; not covered by the fidelity documentation | [Project Priorities](Project-Priorities.md) |
| Image viewer: BAM playback, controls, grid overlay | Implemented on `main`; not re-verified since the revival | `tools/image_viewer/` |
| Image viewer: TIS (tileset) rendering | **Incomplete.** `main` holds a partial fix; further work is unmerged and needs careful review | [issue #5](https://github.com/DiscantX/PlanarForgeV2/issues/5), [Format Notes](Format-Notes.md#tileset-files-tis-in-biff-archives) |
| ARE writer for overlapping section offsets (PST format) | Known bug | [issue #6](https://github.com/DiscantX/PlanarForgeV2/issues/6) |
| Distinguishing PST from PSTEE ARE files | Known bug; the current heuristic is unreliable | [issue #7](https://github.com/DiscantX/PlanarForgeV2/issues/7) |
| Layer 2: project format | Designed, not implemented; five design questions remain open | [Layer 2 Overview](Layer2-Overview.md), [Open Questions](Layer2-Open-Questions.md) |
| Widget descriptor layer, IDS-resolved field round-trip | Designed, not implemented | [Widget Descriptors](Layer2-Widget-Descriptors.md), [Assembler](Layer2-Assembler.md) |
| WeiDU export pipeline | Design phase | [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md) |
| MCP server (letting an AI assistant inspect the running program) | Under consideration | none yet |

## How to read the "complete" claims

The fidelity results were produced against real game installations, and the claims are recorded in the engineering logs rather than in automated tests that run anywhere. Three consequences follow.

1. **They cannot be re-checked without the games.** Only Baldur's Gate II: Enhanced Edition is currently installed on the maintainer's machine. Results for Planescape: Torment (and its Enhanced Edition) and Icewind Dale II were obtained earlier and cannot be reproduced until those games are installed again.
2. **Game data may never be committed.** The rules are set out in the [Game Asset Policy](Game-Asset-Policy.md). Tests that need real files read them from a local installation, and no test fixture may contain game content.
3. **Some past conclusions need re-checking.** The upstream format references contain errors, and some have since been corrected, so the project's own notes about them can go stale. [Format Notes](Format-Notes.md#how-much-to-trust-the-references) lists the cases known so far.

## What is in flight

* [Issue #3](https://github.com/DiscantX/PlanarForgeV2/issues/3): reorganise the documentation into a cross-referenced set (this page is part of that work).
* [Issue #4](https://github.com/DiscantX/PlanarForgeV2/issues/4): a real README, a dependency manifest, and issue and pull request templates.
* [Issue #5](https://github.com/DiscantX/PlanarForgeV2/issues/5): triage of the `uncommitted` branch, which holds an unfinished attempt at the TIS pipeline.

Work is deliberately ordered so that the documentation is in good order before the code is touched. TIS rendering will be examined closely once the project is ready to build against real game files, because earlier work on it was done with several different tools and is known to contain errors.

## How work is tracked

Every change has an issue, and every issue is closed by the pull request that makes the change. See [Workflow and Conventions](Workflow-and-Conventions.md).
