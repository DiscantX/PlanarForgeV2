# Layer 2: The Assembler

The assembler is the translator between the two layers. Going *in*, it takes a binary resource that the Layer 1 parser has read and produces a project object containing only the fields the schema exposes. Going *out*, it takes an edited project object and rebuilds a binary resource that the Layer 1 writer can serialise, recomputing the offsets, counts and indices that the project object does not carry. The user interface never sees those layout details.

The assembler translates between Layer 1 (binary `Resource` objects) and Layer 2
(project objects).

## Import direction (binary → project)

1. Load binary resource via existing `ResourceLoader`
2. Call `resource.to_dict()` to get serialized field values (IDS/2DA already resolved)
3. Walk project schema fields
4. For each field, extract value from the dict using `from:` mapping
5. For `from_bitfield:` fields, extract the sub-field value
6. Build project object with extracted values

Control fields (offsets, counts, indices) are discarded — they are binary layout
artifacts that the assembler reconstructs on export.

## Export direction (project → binary)

1. Walk project schema fields in section order
2. For each field, write value back to the correct binary field using `from:` mapping
3. For `from_bitfield:` fields, pack the sub-field back into the bitfield
4. For `text` type fields with IDS backing, perform reverse IDS lookup via
   `IdsHandler.lookup(symbol)`
5. Reconstruct control fields:
   - `offset_to_*` — calculated from section order during write
   - `count_of_*` — calculated from array lengths
   - `index_into_feature_blocks` / `count_of_feature_block` — calculated from
     nested Effects arrays per ability
   - `index_into_equipping_feature_blocks` / `count_of_equipping_feature_blocks` —
     calculated from Equipping Effects array length
6. Pass reconstructed binary resource to existing `BinaryParser.write()`

## Unknown fields

Binary fields not referenced by any project schema field are carried through unchanged.
The assembler reads the full binary resource, modifies only the fields it knows about,
and writes the rest back verbatim.

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Project Schema Format](Layer2-Schema-Format.md): the `from:`, `from_bitfield:` and `section:` attributes the assembler follows
* [Round-trip Fidelity](Round-trip-Fidelity.md): the Layer 1 guarantees the assembler builds on
* [Relational Logic in WED](Relational-Logic-in-WED.md): how Layer 1 already recomputes pointers for pointer-heavy formats
* [Open Questions](Layer2-Open-Questions.md): the unknown-field strategy is still undecided
