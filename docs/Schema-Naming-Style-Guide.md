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

## Conventions settled in the ARE schemas

A review of the five ARE schemas ([issue #67](https://github.com/DiscantX/PlanarForgeV2/issues/67)) settled the following. Prefer them in other formats unless there is a reason not to.

* Use correct American spelling: `color`, `appearance`, `targeting`.
* Name a point `x_coordinate` and `y_coordinate`, with a prefix when an object stores more than one point (`trap_launch_x_coordinate`, `alternative_use_point_2_x_coordinate`).
* Name the distance limits on a creature's movement `movement_distance` and `movement_to_distance`, and the time after which a spawned creature is removed `removal_timer`, in every section that has them.
* Header pointers use the plural section name, as in `offset_to_animations`.
* In ARE, an index into the vertices section is `index_of_first_<what>_vertex` (for example `index_of_first_outline_vertex_open`), with a matching `count_of_<what>_vertices`. This differs from the `index_into_<section>` form used by ITM, SPL and CRE because an ARE object can point to several separate runs of vertices at once.
* A field that means the same thing in every version of a format keeps the same name in every schema, even where the IESDP page for one version words it differently (the IWD2 automap note fields are `strref_location` and `note_color`, like the other versions).
* Flag and enum value names are `snake_case` identifiers without spaces.
