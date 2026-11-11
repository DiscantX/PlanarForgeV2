# Layer 2: The Item Project Schema

Items (`.itm` files: weapons, armour, potions and so on) were chosen as the first resource type for Layer 2 because they exercise every feature of the schema format: strings, resource references, enums, bitmasks, repeating groups, nested groups, and game-specific fields. The schema below is the agreed reference implementation and the proving ground for the system. Read the [project schema format](Layer2-Schema-Format.md) first for the meaning of each attribute.

Two features are worth noticing as you read. The shared `effect_fields` block is defined once with a YAML anchor and reused for both the *Equipping Effects* group and the effects nested under each *Ability*. And the *Flags* group contains a field that appears twice, distinguished only by its `games:` tag; this is the subject of [open question 1](Layer2-Open-Questions.md#1-duplicate-field-names-in-flags-group).

This is the agreed schema for the ITM resource type. It serves as the reference
implementation and proving ground for the project schema system.

```yaml
name: Item
version: V1
resource_type: ITM

effect_fields: &effect_fields
  fields:
  - name: opcode_number
    type: number
    min: 0
    max: 65535
    section: feature_block

  - name: target_type
    type: enum
    section: feature_block

  - name: power
    type: number
    min: 0
    max: 255
    section: feature_block

  - name: parameter_1
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: parameter_2
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: timing_mode
    type: enum
    section: feature_block

  - name: dispel_resistance
    type: enum
    section: feature_block

  - name: duration
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: probability_1
    type: number
    min: 0
    max: 100
    section: feature_block

  - name: probability_2
    type: number
    min: 0
    max: 100
    section: feature_block

  - name: resource
    type: resref
    picker: generic
    section: feature_block

  - name: dice_thrown_maximum_level
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: dice_sides_minimum_level
    type: number
    min: 0
    max: 4294967295
    section: feature_block

  - name: saving_throw_type
    type: bitmask
    section: feature_block

  - name: saving_throw_bonus
    type: number
    min: -20
    max: 20
    section: feature_block

groups:

  - name: Identity
    fields:

    - name: identified_name
      type: strref

    - name: unidentified_name
      type: strref

    - name: identified_description
      type: strref

    - name: unidentified_description
      type: strref

    - name: inventory_icon
      type: resref
      picker: bam

    - name: ground_icon
      type: resref
      picker: bam

    - name: description_icon
      type: resref
      picker: bam
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: dialog
      type: resref
      picker: dialog
      games: [PST, PSTEE]

    - name: conversable_label
      type: strref
      games: [PST, PSTEE]

  - name: Properties
    fields:

    - name: item_type
      type: enum
      section: header

    - name: weight
      type: number
      min: 0
      max: 65535

    - name: price
      type: number
      min: 0
      max: 4294967295

    - name: stack_amount
      type: number
      min: 1
      max: 65535

    - name: lore_to_id
      type: number
      min: 0
      max: 65535

    - name: enchantment
      type: number
      min: 0
      max: 255

    - name: weapon_proficiency
      type: text
      section: header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: paperdoll_animation_colour
      type: number
      min: 0
      max: 65535
      games: [PST, PSTEE]

  - name: Requirements
    fields:

    - name: min_level
      type: number
      min: 0
      max: 65535

    - name: min_strength
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_strength_bonus
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_intelligence
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_dexterity
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_wisdom
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_constitution
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: min_charisma
      type: number
      min: 0
      max: 25
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

  - name: Flags
    fields:

    - name: flags
      type: bitmask
      section: header

    - name: usability_bitmask
      type: bitmask
      section: header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: usability_bitmask
      type: bitmask
      section: header
      games: [PST, PSTEE]

  - name: Abilities
    repeating: true
    from_section: extended_header
    fields:

    - name: attack_type
      type: enum
      section: extended_header

    - name: id_req
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: location
      type: enum
      section: extended_header

    - name: use_icon
      type: resref
      picker: bam
      section: extended_header

    - name: target_type
      type: enum
      section: extended_header

    - name: count_of_target
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: range
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: launcher_required
      type: enum
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, PSTEE, IWD, IWD2]

    - name: projectile_type
      type: enum
      section: extended_header
      games: [PST]

    - name: speed_factor
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: thac0_bonus
      type: number
      min: -128
      max: 127
      section: extended_header

    - name: dice_sides
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: dice_thrown
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: damage_bonus
      type: number
      min: -32768
      max: 32767
      section: extended_header

    - name: damage_type
      type: enum
      section: extended_header

    - name: alternative_dice_sides
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: alternative_dice_thrown
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: alternative_damage_bonus
      type: number
      min: 0
      max: 255
      section: extended_header

    - name: max_charges
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: charge_depletion_behaviour
      type: enum
      section: extended_header

    - name: flags
      type: bitmask
      section: extended_header

    - name: projectile_animation
      type: text
      section: extended_header

    - name: melee_animation_overhand
      from_bitfield:
        field: melee_animation
        subfield: overhand
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: melee_animation_backhand
      from_bitfield:
        field: melee_animation
        subfield: backhand
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: melee_animation_thrust
      from_bitfield:
        field: melee_animation
        subfield: thrust
      type: number
      min: 0
      max: 65535
      section: extended_header

    - name: arrow_qualifier_is_arrow
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: bolt_qualifier_is_bolt
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: bullet_qualifier_is_bullet
      type: number
      min: 0
      max: 65535
      section: extended_header
      games: [BG1, BG2, BG2EE, BGEE, IWDEE, IWD, IWD2]

    - name: Effects
      repeating: true
      from_section: feature_block
      <<: *effect_fields

  - name: Equipping Effects
    repeating: true
    from_section: feature_block
    equipping: true
    <<: *effect_fields
```

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Project Schema Format](Layer2-Schema-Format.md)
* [Open Questions](Layer2-Open-Questions.md)
