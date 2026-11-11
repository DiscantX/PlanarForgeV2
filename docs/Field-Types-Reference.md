# Field Types Reference

This page documents the data types available for use in the `fields` section of YAML schemas.

## Basic Numeric Types

| Name | Size | Description |
|------|------|-------------|
| `byte`, `char` | 1 | Unsigned 8-bit integer. |
| `word` | 2 | Unsigned 16-bit integer (little-endian). |
| `dword` | 4 | Unsigned 32-bit integer (little-endian). |
| `sbyte`, `schar` | 1 | Signed 8-bit integer. |
| `sword` | 2 | Signed 16-bit integer. |
| `sdword` | 4 | Signed 32-bit integer. |

## Strings and Blobs

### `char_array`

A fixed-length string. 
* **Attributes**: `size` (int) or `size_ref` (name of a sibling field containing the size).

### `bytes`

A raw binary blob.
* **Attributes**: `size` (int).

## Data Structures

### `bitmask`

Maps bits to boolean flags. 
* **Attributes**: `flags` (Dictionary of `hex_mask: flag_name`).
* **Note**: Unmapped bits are preserved in a reserved `_unknown` field for fidelity.

### `bitfield`

Extracts multiple numeric values from a single integer.
* **Attributes**: `bitfields` (Dictionary of `name: {shift: X, mask: Y}`).

### `enum`

Maps an integer to a string label.
* **Attributes**: `values` (List or Dictionary).

## Array Types

### `word_array` / `byte_array`

A collection of scalars.
* **Attributes**: `count` (fixed) or `size` (total bytes to divide).

### `word_scalar_array`

Used for high-performance flat lookup tables (e.g., in WED files).
* **Attributes**: `count_field` (resolves count from the parsing context).

## Relational & Virtual Types

### `computed`

A virtual field that calculates a value from its siblings using an arithmetic expression. It has **size 0** and does not exist in the binary file.
* **Usage**: `expr: "width * height"`

### `pointer_string`

Reads a string from a distant offset within the same section entry.
* **Attributes**: `offset_ref`, `length_ref`.

## Infinity Engine Specific

### `resref`

An 8-byte, null-padded resource reference. Automatically sanitized for display (strips trailing nulls).

### `strref`

A 4-byte integer pointing to a string in the TLK table. In-editor display resolves this to the actual text.

### `resref_array` / `strref_array`

Specialized handlers for blocks of references, often used in spell/item slots.

### `effect_extra_data`

A conditional field used in CRE files. It reads 216 bytes of additional data only if the `eff_structure_version` in the context is non-zero.

---

## Common Attributes
* **`lookup`**: Used for fields that reference external tables (IDS files).
* **`display_value_map`**: Overrides the raw integer display in the UI with a string.
* **`display_empty_values`**: List of integers (like `0` or `0xFFFFFFFF`) that should be treated as `null/None` in the editor.
* **`hidden: true`**: The field is parsed but not shown in the standard inspector.