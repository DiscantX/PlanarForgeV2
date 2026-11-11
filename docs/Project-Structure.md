# Project Structure & Architecture

This document outlines the organization of PlanarForgeV2, identifying the responsibilities of each directory and the architectural decisions driving code placement.

## Directory Overview

### `core/`

The brain of the application. It contains all Python logic required to read, write, and manage resources.

#### `core/binary/` (Infrastructure Layer)

**Purpose:** Generic binary manipulation tools.
**Scope:** Code here should be **agnostic** to the specific game engine (Infinity Engine). It should not know what a "BIF" or "ResRef" is, only how to read integers, strings, and follow a schema.

**Contents:**

*   `Reader`/`Writer`: Low-level stream wrappers.
*   `BinaryParser`: The schema engine that interprets YAML definitions to process binary streams.

#### `drivers/` (Plugin Layer)

**Purpose:** Contains engine-specific logic and drivers.

#### `drivers/InfinityEngine/`

**Purpose:** The implementation for Baldur's Gate, Icewind Dale, etc.
**Contents:**

*   `ResourceLoader`: The driver entry point.
*   `BiffHandler`: Handles BIF/BIFC container logic.
*   `InstallationFinder`: Locates games on disk.
*   `schemas/`: Engine-specific YAML definitions (ITM, BIFF, etc.).
*   `types.py`: Engine-specific field types (ResRef, StrRef).
*   `extensions.py`: Mappings between integer type codes and string extensions (e.g., `2012` -> `ITM`).

#### `core/` (Shared/Root)

**Purpose:** Fundamental components that bridge Infrastructure and Domain.
**Contents:**

*   `resource.py`: The generic data container class.
*   `field_types.py`: Defines generic data types (UInt, Bitmask, Enum). Engine-specific types are delegated to drivers.
*   `schema_loader.py`: Handles loading and resolving the YAML schemas.

---

## Architectural Patterns

### Schema-Driven Parsing

The `BinaryParser` is intentionally "dumb"; the `Schema` is "smart." Logic regarding *what* to read resides in YAML definitions. Logic regarding *how* to read it (endianness, stream seeking) belongs in Python.

### Single Responsibility

*   **`BiffHandler`**: Manages I/O and decompression (getting the bytes).
*   **`BinaryParser`**: Interprets structure and relational pointers (interpreting the bytes).
*   **`ResourceLoader`**: Coordinates the retrieval and parsing lifecycle.

### Separation of Concerns

*   `core/binary` never imports from `drivers`.
*   `drivers` depends on `core/binary` to implement engine-specific formats.