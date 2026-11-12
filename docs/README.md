# PlanarForgeV2 Documentation

PlanarForge is a modern development environment for Infinity Engine games, supporting the original titles (BG1, BG2, PST, IWD) and the Enhanced Editions.

See [Project Status](Project-Status.md) for the current state of each component. The project is currently at **Stage 1/2**—providing a robust, schema-driven binary parser and writer that maintains 100% round-trip fidelity for major formats including ARE, ITM, SPL, CRE, and WED.

## Core Philosophies

1. **Schema-Driven Architecture**: All binary formats are defined in YAML. The engine logic is generic, while domain knowledge resides in schemas.
2. **Byte-Perfect Fidelity**: For unmodified files, the tool guarantees a bit-identical output.
3. **Layered Data Representation**: A clean separation between raw binary formats and modern project-level editing structures.

## Current Status

| Milestone | Status |
|-----------|--------|
| Binary Parsing (Layer 1) | ✅ Complete |
| Round-trip Fidelity | ✅ Complete |
| Area Visualization | 🔜 Near-term |
| Scene Editing | 🔲 Long-term |

## Contents

### Introduction

* [Project Priorities](Project-Priorities.md)
* [Game Asset Policy](Game-Asset-Policy.md)

### Architecture

* [The Three-Layer Model](The-Three-Layer-Model.md)
* [Project Structure](Project-Structure.md)
* [Asset Management](Asset-Management.md)

### Project Layer (Layer 2)

* [Project Format and Schemas](Project-Format-and-Schemas.md)
* [Layer 2 Overview](Layer2-Overview.md)
    * [Project Model and Session](Layer2-Project-Model.md)
    * [Dependency Graph](Layer2-Dependency-Graph.md)
    * [Undo and Redo](Layer2-Undo-Redo.md)
    * [Project Schema Format](Layer2-Schema-Format.md)
    * [Widget Descriptors](Layer2-Widget-Descriptors.md)
    * [Assembler](Layer2-Assembler.md)
    * [Item Project Schema](Layer2-Item-Schema.md)
    * [Open Questions](Layer2-Open-Questions.md)

### Schema Development

* [Field Types Reference](Field-Types-Reference.md)
* [Schema Naming Style Guide](Schema-Naming-Style-Guide.md)
* [Relational Logic in WED](Relational-Logic-in-WED.md)
    * [WED V1.3 Engine Upgrade](WED-V1.3-Engine-Upgrade.md)

### Maintenance and QA

* [Round-trip Fidelity](Round-trip-Fidelity.md)
    * [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
    * [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md)
    * [Unknown Bytes and the Gap Audit](Unknown-Bytes-and-the-Gap-Audit.md)
    * [Offset Drift and Schema Versioning](Offset-Drift-and-Schema-Versioning.md)
* [Optimization Log](Optimization-Log.md)

### Future Vision

* [WeiDU Export Pipeline](WeiDU-Export-Pipeline.md)

### Tools

* [IESDP Converter](IESDP-Converter.md)

### Archive

* [Archive index](archive/README.md): frozen engineering logs, kept for reference

## Project Notes

* [Project Status](Project-Status.md)
* [Infinity Engine Format Notes](Format-Notes.md)
* [Workflow and Conventions](Workflow-and-Conventions.md)
