# WeiDU Export Pipeline

The goal of PlanarForge is to produce industry-standard WeiDU mod packages. The export pipeline automates the conversion from Layer 2 Project files to a functional `.tp2` script.

## Export Workflow

1. **Compilation**: Layer 2 Project objects are compiled into "Clean" Layer 1 Binary resources using the Format Schemas.
2. **Diffing**: For `derived` resources, the compiler compares the clean binary against the original game asset.
3. **Script Generation**:
    * **New Resources**: Added to the mod folder; the `.tp2` is updated with `COPY ~mymod/res/new.cre~ ~override~`.
    * **Modified Resources**: The diff is converted into WeiDU commands: `COPY_EXISTING ~base.cre~ ~override~ WRITE_LONG 0x14 50`.

## Benefits of Diff-Based Export

* **Compatibility**: By only patching the specific fields the user changed, the resulting mod is significantly more compatible with other mods than a full-file overwrite.
* **Readability**: The generated `.tp2` serves as a human-readable log of exactly what the mod changes.
* **Efficiency**: Reduces the file size of the distribution by not including full binary copies of base game assets.

## Status

The export pipeline is currently in the **Design Phase** as we finalize the transition to Layer 2.