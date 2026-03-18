import hashlib
from pathlib import Path
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from drivers.InfinityEngine.resource_loader import ResourceLoader
import sys

# ResourceLoader now automatically loads schemas from the driver's 'schemas' folder
resource_loader = ResourceLoader()

# 1. Load the resource from the game files
# Explicitly specify restype="BIFF" because load_file defaults to "KEY" (Chitin)
resource = resource_loader.load_file(file_path = Path("C:\\Program Files (x86)\\Steam\\steamapps\\common\\Baldur's Gate II Enhanced Edition\\data\\Items.bif"), restype="BIFF")

print(f"Loaded {resource.name} from {resource.source}")

print("\n--- Resource Data Inspection ---")
for section_name, entries in resource.sections.items():
    print(f"Section: {section_name} ({len(entries)} entries)")
    for i, entry in enumerate(entries):
        print(f"  Entry {i}:")
        for key, value in entry.items():
            print(f"    {key}: {value}")