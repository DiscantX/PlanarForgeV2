Current Bottlenecks
Full Parsing of BIF Files (Major I/O Bottleneck)

The Issue: inside load(), you call self.load_file(..., restype="BIFF", ...) which uses BinaryParser to read the entire BIF file structure into memory.
Why it's bad: BIF files can contain hundreds or thousands of file entries. Even though you aren't reading the raw data of every file, you are parsing the metadata headers for every single file in that archive just to find the location of one resource.
Impact: If a BIF is 500MB with 2,000 files, you perform 2,000 reads and object allocations just to find the offset for file #50.
Linear Search in Chitin (Algorithmic Bottleneck)

The Issue: _find_resource_location iterates through self.chitin.sections["resource_entries"] linearly:
python
for entry in resource_entries:
    if entry.get("resource_name") == resref: ...
Why it's bad: chitin.key contains thousands of resources (e.g., ~30,000 in BG2EE). Performing an O(N) search for every single resource load is extremely slow.
Impact: Loading a complex creature that references 20 items and scripts will trigger this linear search 20+ times.
Redundant File Opening

The Issue: In load():
self.load_file(...) opens the BIF, parses it, and closes it.
Immediately after, with open(bif_file_path, "rb") as f: opens the BIF again to read the raw bytes.
Impact: Double the file system overhead per resource.
Optimization Plan
1. Implement Chitin Lookup Caching (O(1) Access)
Instead of searching the list every time, we should build a hash map (dictionary) when chitin.key is first loaded.

Strategy: Create self._resource_map during __init__.
Structure: { "CHAN04": { "bif_index": 12, "resource_index": 455, ... } }
Result: Finding a resource becomes an instantaneous O(1) operation.
2. Implement "Random Access" BIF Reading
We can completely eliminate the need to parse the full BIF file structure using the BinaryParser.

Logic:
Read only the BIF Header (fixed size, very small).
Get the file_entries_offset from the header.
Calculate the exact offset of the specific file entry using the resource_index we got from Chitin.
target_entry_offset = file_entries_offset + (resource_index * ENTRY_SIZE)
Seek directly to target_entry_offset, read just that entry's offset and size.
Seek to the data offset and read the raw bytes.
Result: We skip parsing 99.9% of the BIF file.
3. Resource Type Mapping (The TODO)
As noted in your code comments, we need a static map to convert the integer resource_type found in Chitin (e.g., 1002) into a string extension (ITM).

Strategy: Add a dictionary constant mapping these IDs to schema names.
Result: load("CHAN04") works automatically without needing restype="ITM".
Proposed Architecture Changes
I recommend implementing these changes in the following order:

Lookup Map: Modify _load_chitin to generate a resref -> entry dictionary immediately after parsing.
Resource Type Map: Create the integer-to-string mapping.
Direct BIF Access: Rewrite the BIF logic in load to use BinaryReader directly for the headers/offsets, bypassing the full BinaryParser for the container format.
What to Cache?
Chitin Index: YES. The parsed chitin.key structure is heavy. The resref lookup map is essential.
Parsed Schemas: YES. (You are already doing this via SchemaLoader).
Raw File Handles: MAYBE. Keeping file handles open for the .bif files can be faster, but you risk hitting OS file handle limits. For now, rely on OS-level disk caching.
Parsed Resources: NO (for now). Caching the resulting Resource objects (like the parsed CHAN04) consumes significant memory. Only implement an LRU (Least Recently Used) cache for this if you find specific resources are being re-loaded constantly in a short timeframe.