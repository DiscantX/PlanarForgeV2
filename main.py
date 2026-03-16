from pprint import pprint
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.game.resource_loader import ResourceLoader

# Load schema
schema_loader = SchemaLoader("schemas")
schema_loader.load_all()
schema_loader.resolve_types(FieldTypes)

resource_loader = ResourceLoader(schema_loader=schema_loader)
resource = resource_loader.load("CHAN04", restype="ITM")

print(f"Resource: {resource.name} source: {resource.source}")

# Access data directly from the flattened values dictionary
print(f"Identified Name StrRef: {resource.values.get('identified_name')}")

for section in resource.sections:
    print(f"Section: {section}")
    for entry in resource.sections[section]:
        print(f"{entry}")