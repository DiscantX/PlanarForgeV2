# IESDP Converter

The IESDP (Infinity Engine Structure Description Project) is the community standard for documenting IE binary formats. To maintain high-fidelity schemas, PlanarForgeV2 includes a converter tool to bootstrap YAML definitions from IESDP data.

## Purpose

Manually writing schemas for hundreds of versions of IE formats is error-prone. The IESDP Converter automates the initial extraction of offsets, sizes, and field labels, ensuring that the base structure is accurate before developer refinement.

## Features

*   **Label Extraction**: Automatically pulls field names from IESDP tables.
*   **EE Split Handling**: Correctly identifies fields that differ between Original and Enhanced Editions (e.g., `BGEE:` prefixes).
*   **Comment Filtering**: Ignores purely descriptive text to keep the YAML clean while preserving functional field names.
*   **Normalization**: Automatically converts control fields to the standard PlanarForge naming convention:
    *   `offset_to_<section>`
    *   `count_of_<section>`
    *   `index_into_<section>`

## Usage

The converter is located in the `tools/` directory. It typically takes a raw text or HTML scrap from an IESDP page and outputs a YAML draft.

```bash
python tools/iesdp_converter.py --input raw_itm_v1.txt --output itm_v1.yaml
```

## Refining the Output

The converter provides a "Layer 1" structural map. After generation, developers should review the output for:

1.  **Bitmask Definitions**: Mapping hex masks to semantic flag names.
2.  **Enum Values**: Mapping integers to meaningful string labels.
3.  **Relational Logic**: Defining `offset_ref` and `count_ref` for sections that aren't fixed-length.

## Reference

For more information on naming standards used during conversion, see the [Schema Naming Style Guide](Schema-Naming-Style-Guide.md).