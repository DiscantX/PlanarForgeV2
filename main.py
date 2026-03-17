import hashlib
from pathlib import Path
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.game.resource_loader import ResourceLoader
import sys

# Load schema
schema_loader = SchemaLoader("schemas")
schema_loader.load_all()
schema_loader.resolve_types(FieldTypes)

resource_loader = ResourceLoader(schema_loader=schema_loader)

# --- Round-trip Test ---
if len(sys.argv) > 1:
    resref_to_test = sys.argv[1].upper()
else:
    resref_to_test = "MUMGREW"  # Default example


output_path = Path(f"./{resref_to_test}.saved.itm")

print(f"--- Running Round-Trip Test for {resref_to_test} ---")

# 1. Load the resource from the game files
resource = resource_loader.load(resref_to_test, restype="ITM")
if not resource:
    raise SystemExit(f"Failed to load {resref_to_test}")

print(f"Loaded {resource.name} from {resource.source}")

print("\n--- Resource Data Inspection ---")
for section_name, entries in resource.sections.items():
    print(f"Section: {section_name} ({len(entries)} entries)")
    for i, entry in enumerate(entries):
        print(f"  Entry {i}:")
        for key, value in entry.items():
            print(f"    {key}: {value}")
print("--------------------------------\n")

# 2. Save the in-memory resource object to a new file
resource_loader.save_file(resource, output_path)
print(f"Saved resource to '{output_path}'")

# 3. Get the original bytes from the BIF for comparison
original_bytes, _, _ = resource_loader.get_raw_bytes(resref_to_test, restype="ITM")
if not original_bytes:
    raise SystemExit("Failed to get original bytes for comparison.")

# 4. Compare the original bytes with the newly saved file's bytes
with open(output_path, "rb") as f:
    saved_bytes = f.read()

original_hash = hashlib.md5(original_bytes).hexdigest()
saved_hash = hashlib.md5(saved_bytes).hexdigest()

print(f"Original MD5: {original_hash}")
print(f"Saved MD5:    {saved_hash}")

if original_hash == saved_hash:
    print("\nSUCCESS: Round-trip test passed! Files are identical.")
else:
    print("\nFAILURE: Round-trip test failed. Files are different.")
    
    # Find the first mismatch
    limit = min(len(original_bytes), len(saved_bytes))
    for i in range(limit):
        if original_bytes[i] != saved_bytes[i]:
            print(f"First mismatch at offset {hex(i)} (Decimal: {i})")
            print(f"Original: {hex(original_bytes[i])}  Saved: {hex(saved_bytes[i])}")
            break
    
    if len(original_bytes) != len(saved_bytes):
        print(f"Size mismatch: Original {len(original_bytes)} bytes, Saved {len(saved_bytes)} bytes")