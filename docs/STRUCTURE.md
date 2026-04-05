# Project Structure & Architecture

This document outlines the organization of PlanarForgeV2, identifying the responsibilities of each directory and the architectural decisions driving code placement.

## Directory Overview

### `core/`
The brain of the application. It contains all Python logic required to read, write, and manage resources.

#### `core/binary/` (Infrastructure Layer)
**Purpose:** Generic binary manipulation tools.
**Scope:** Code here should be **agnostic** to the specific game engine (Infinity Engine). It should not know what a "BIF" or "ResRef" is, only how to read integers, strings, and follow a schema.
**Contents:**
- `Reader`/`Writer`: Low-level stream wrappers.
- `BinaryParser`: The schema engine that interprets YAML definitions to process binary streams.

#### `drivers/` (Plugin Layer)
**Purpose:** Contains engine-specific logic and drivers.

#### `drivers/InfinityEngine/`
**Purpose:** The implementation for Baldur's Gate, Icewind Dale, etc.
**Contents:**
- `ResourceLoader`: The driver entry point.
- `BiffHandler`: Handles BIF/BIFC container logic.
- `InstallationFinder`: Locates games on disk.
- `schemas/`: Engine-specific YAML definitions (ITM, BIFF, etc.).
- `types.py`: Engine-specific field types (ResRef, StrRef).
- `extensions.py`: mappings between integer type codes and string extensions (e.g., `2012` -> `ITM`).

#### `core/` (Shared/Root)
**Purpose:** Fundamental components that bridge Infrastructure and Domain.
**Contents:**
- `resource.py`: The generic data container class.
- `field_types.py`: Defines generic data types (UInt, Bitmask, Enum). Engine-specific types are delegated to drivers.
- `schema_loader.py`: Handles loading and resolving the YAML schemas.

### `tests/`
**Purpose:** Automated testing.
**Strategy:**
- **Fidelity Tests:** Ensure that reading a file and writing it back produces a byte-perfect copy (round-trip).
- **Integration Tests:** Verify that the system can locate game installs and parse real game files without crashing.

### `tools/`
**Purpose:** Standalone utility scripts (e.g., converters, scrapers) used to aid development but not part of the core library runtime.

---

## Architectural Decisions & Guidelines

### Where does code belong?

#### 1. "I need to support a new binary primitive (e.g., a Float16)."
**Location:** `core/field_types.py` (and potentially `core/binary/reader.py`).
**Why:** This is a fundamental building block of data parsing.

#### 2. "I need to handle a specific file container (e.g., ERF or RIM files)."
**Location:** `drivers/<EngineName>/` (e.g., `drivers/Aurora/erf_handler.py`).
**Why:** Even though it involves reading binary data, handling a container format is specific to the game engine's storage method. It belongs in the Domain layer, not the generic Infrastructure layer.
*Decision Reference:* `BiffHandler` was placed here because it encapsulates domain knowledge (Signature detection, Decompression algorithms specific to BIFF) rather than generic binary parsing.

#### 3. "I need to fix a bug where a specific file type isn't parsing correctly."
**Location:** `drivers/<EngineName>/schemas/*.yaml`.
**Why:** We prefer fixing the data definition over hardcoding exceptions in the parser.

#### 4. "I want to change how we find game paths on Linux."
**Location:** `drivers/InfinityEngine/installation_finder.py`.
**Why:** Platform-specific discovery logic is part of the Domain layer's responsibility to abstract the environment from the rest of the app.

### Key Patterns

*   **Schema-Driven:** The `BinaryParser` is dumb; the `Schema` is smart. Logic regarding *what* to read should be in YAML. Logic regarding *how* to read it belongs in Python.
*   **Single Responsibility (IO vs Parsing):**
    *   `BiffHandler` gets the bytes (IO, Decompression).
    *   `BinaryParser` interprets the bytes (Structure).
    *   `ResourceLoader` coordinates the two.
*   **Separation of Concerns (Infrastructure vs Domain):**
    *   `core/binary` does not import `drivers`.
    *   `drivers` depends on `core/binary`.