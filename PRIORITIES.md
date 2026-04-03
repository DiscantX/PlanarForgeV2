# PlanarForgeV2 Implementation Priorities

This checklist tracks the implementation status of Infinity Engine resource types, prioritized by their importance to the core goal of a game editor.

## 1. Infrastructure & Core Data (Critical)
These resources are required to locate files, read strings, or interpret basic game rules.

- [x] **KEY** (Index) - *Confirmed Working*
    - The master index (`CHITIN.KEY`) mapping ResRefs to BIF locations.
- [x] **BIF** (Archive) - *Confirmed Working*
    - Binary Information File. Holds the actual data.
- [x] **TLK** (String Table) - *Confirmed Working*
    - Lookup table for all text in the game. Essential for displaying names/descriptions.
- [x] **2DA** (2D Array) - *Confirmed Working (Handler Implemented)*
    - Text-based tables defining game rules (XP caps, UI layouts, etc.). Handler is implemented, integration with schema system is next.
- [x] **IDS** (Identifiers) - *Confirmed Working (Handler Implemented)*
    - Maps integer IDs to symbolic names (e.g., `144` -> `BERSERKER`). Handler is implemented, integration with schema system is next.

## 2. Game Objects (The "Forge" Core)
The primary entities users edit.

- [x] **ITM** (Item) - *Confirmed Working*
    - Weapons, armor, consumables.
- [x] **SPL** (Spell) - *Confirmed Working*
    - Magic spells and innate abilities.
- [x] **CRE** (Creature) - *Confirmed Working*
    - Actors, enemies, and NPCs.
- [ ] **STO** (Store)
    - Merchant inventories and container definitions.
- [ ] **EFF** (Effect)
    - External effect definitions (often embedded, but can be separate).
- [x] **ARE** (Area) - *Confirmed Working*
    - Defines actors, containers, traps, and regions within a map.
- [x] **WED** (World Environment) - *Confirmed Working*
    - Visual map definitions (overlays, door polygons).
- [ ] **PRO** (Projectile)
    - Definition of missiles and spell visual travel speeds/areas.
- [ ] **VVC** (Visual Effect)
    - Visual effects animations and overlays.

## 3. Narrative & World (High Complexity)
Resources defining the game world, plot, and logic.

- [ ] **DLG** (Dialog)
    - Conversation trees and triggers. Complex recursive structure.
- [ ] **BCS** (Bytecode Script)
    - Compiled AI scripts. Requires Decompiler/Compiler to be useful.
- [ ] **WMAP** (World Map)
    - The overworld map and travel times.

## 4. Audiovisual Assets (Media)
Standard or proprietary media formats.

- [ ] **BMP** (Bitmap)
    - Portraits and textures. Standard Windows BMP (often specific bit-depths).
- [ ] **WAV** (Wave Audio)
    - Sound effects. Standard WAV format.
- [ ] **WAVC** (Compressed Wave)
    - Proprietary compressed audio wrapper.
- [ ] **BAM** (Bitmap Animation)
    - Sprite animations (RLE compressed).
- [ ] **MOS** (Mosaic)
    - Background images (loading screens, UI).
- [ ] **TIS** (Tileset)
    - The graphical tiles creating the map visual.
- [ ] **PLT** (Paperdoll)
    - Inventory character graphics (palette mapped).
- [ ] **MUS** (Music Playlist)
    - Text-based playlist definitions.
- [ ] **ACM** (Audio)
    - Interplay proprietary audio format (music).
- [ ] **MVE** (Movie)
    - Interplay video format.
- [ ] **PVRZ** (Texture)
    - Compressed texture format (Enhanced Editions).
- [ ] **PNG** (Image)
    - Standard PNG format (Enhanced Editions).
- [ ] **FNT** (Font)
    - Bitmap fonts.
- [ ] **TTF** (TrueType Font)
    - Standard font format (Enhanced Editions).
- [ ] **GLSL** (Shader)
    - OpenGL Shading Language files (Enhanced Editions).

## 5. UI & Configuration
Interface layouts and system settings.

- [ ] **INI** (Configuration)
    - Text-based settings.
- [ ] **CHU** (UI Layout)
    - Legacy UI layout format.
- [ ] **GUI** (UI Definition)
    - Enhanced Edition UI definition.
- [ ] **MENU** (UI Menu)
    - Enhanced Edition menu definition.
- [ ] **LUA** (Script)
    - Used for UI logic in Enhanced Editions.
- [ ] **SQL** (Database)
    - SQLite databases used in Enhanced Editions.

## 6. Save Games (Stretch Goal)
Editing save states is low priority.

- [ ] **GAM** (Game Party)
    - Party roster, global variables, journal entries.
- [ ] **SAV** (Save Archive)
    - Actually a compressed BIFF containing the GAM and CRE files.
- [ ] **CHR** (Character)
    - Single character export (wrapper around CRE).

## 7. Miscellaneous / Unknown Applicability
Types that are obscure, internal, or legacy.

- [ ] **MAZE**, **TOH**, **TOT**, **VAR**, **VEF**, **WBM**, **WFX**, **SRC**