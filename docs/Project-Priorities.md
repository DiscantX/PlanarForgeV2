# Project Priorities

This checklist ranks Infinity Engine resource types by their importance to the core goal of a game editor, and records what the repository currently provides for each. For the wider picture, see [Project Status](Project-Status.md).

**Reading the labels.** *Confirmed Working* means the type has been parsed and, where applicable, round-tripped (see [Round-trip Fidelity](Round-trip-Fidelity.md)). *Schema present* means a YAML schema exists in `drivers/InfinityEngine/definitions/schemas/` but the type is not covered by the fidelity documentation. *Incomplete* means partial work exists. Types with no label have no schema or handler in the repository yet.

## 1. Infrastructure & Core Data (Critical)

These resources are required to locate files, read strings, or interpret basic game rules.

* **KEY** (Index) - *Confirmed Working*
    - The master index (`CHITIN.KEY`) mapping ResRefs to BIF locations.
* **BIF** (Archive) - *Confirmed Working*
    - Binary Information File. Holds the actual data.
* **TLK** (String Table) - *Confirmed Working*
    - Lookup table for all text in the game. Essential for displaying names/descriptions.
* **2DA** (2D Array) - *Confirmed Working (Handler Implemented)*
    - Text-based tables defining game rules.
* **IDS** (Identifiers) - *Confirmed Working (Handler Implemented)*
    - Maps integer IDs to symbolic names.

## 2. Game Objects (The "Forge" Core)

The primary entities users edit.

* **ITM** (Item) - *Confirmed Working*
    - Weapons, armor, consumables.
* **SPL** (Spell) - *Confirmed Working*
    - Magic spells and innate abilities.
* **CRE** (Creature) - *Confirmed Working*
    - Actors, enemies, and NPCs.
* **STO** (Store) - *Schema present*
    - Merchant inventories and container definitions.
* **EFF** (Effect)
    - External effect definitions.
* **ARE** (Area) - *Confirmed Working (PST layout: known bugs, issues #6 and #7)*
    - Defines actors, containers, traps, and regions.
* **WED** (World Environment) - *Confirmed Working*
    - Visual map definitions (overlays, door polygons).

## 3. Narrative & World (High Complexity)

Resources defining the game world, plot, and logic.

* **DLG** (Dialog)
    - Conversation trees and triggers.
* **BCS** (Bytecode Script)
    - Compiled AI scripts.
* **WMAP** (World Map)
    - The overworld map and travel times.

## 4. Audiovisual Assets (Media)

Standard or proprietary media formats.

* **BMP** (Bitmap)
    - Portraits and textures.
* **WAV** (Wave Audio)
    - Sound effects.
* **BAM** (Bitmap Animation) - *Schema present; viewer playback not re-verified since the revival*
    - Sprite animations (RLE compressed).
* **MOS** (Mosaic)
    - Background images.
* **TIS** (Tileset) - *Incomplete; see [issue #5](https://github.com/DiscantX/PlanarForgeV2/issues/5)*
    - The graphical tiles creating the map visual.

## 5. UI & Configuration

Interface layouts and system settings.

* **INI** (Configuration)
    - Text-based settings.
* **CHU** (UI Layout)
    - Legacy UI layout format.
* **GUI** (UI Definition)
    - Enhanced Edition UI definition.

## 6. Save Games (Stretch Goal)

Editing save states is low priority.

* **GAM** (Game Party)
    - Party roster, global variables, journal entries.
* **SAV** (Save Archive)
    - Compressed BIFF containing the GAM and CRE files.

## 7. Miscellaneous / Unknown Applicability

Types that are obscure, internal, or legacy.

* **MAZE**, **TOH**, **TOT**, **VAR**, **VEF**, **WBM**, **WFX**, **SRC**