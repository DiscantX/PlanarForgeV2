# Schema Naming Style Guide

This guide defines how field names in PlanarForge YAML schemas should be written to maintain consistency across game families.

## Goals

* Prefer short names over long names.
* Keep enough semantic information to tell fields apart.
* Use the same name for the same concept across resource types and versions.

## Core Rules

1. Use lowercase `snake_case`.

2. A field name should be a noun phrase, not a sentence.

3. Use singular names for scalar fields.

4. Use prefix forms for control fields:
    * `offset_to_<section>`
    * `count_of_<section>`
    * `index_into_<section>`

## CROSS-RESOURCE CONSISTENCY

When the same concept appears in multiple resources or versions, keep the same name unless the binary meaning actually changes. Examples:

* `signature`, `version`
* `flags`
* `offset_to_extended_headers`
* `count_of_feature_blocks`

## BAD VS GOOD EXAMPLES

* **Bad**: `animation_id_bgee_animation_slots_have_been_externalised`
* **Good**: `animation_id`

* **Bad**: `resource_name_of_the_spl_file`
* **Good**: `spl_file`

* **Bad**: `known_spells_offset`
* **Good**: `offset_to_known_spells`