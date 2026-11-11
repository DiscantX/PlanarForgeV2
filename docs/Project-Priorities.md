# Project Priorities

This checklist tracks the implementation status of Infinity Engine resource types, prioritized by their importance to the core goal of a game editor.

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
* **STO** (Store)
    - Merchant inventories and container definitions.
* **EFF** (Effect)
    - External effect definitions.
* **ARE** (Area) - *Confirmed Working*
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
* **BAM** (Bitmap Animation)
    - Sprite animations (RLE compressed).
* **MOS** (Mosaic)
    - Background images.
* **TIS** (Tileset)
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