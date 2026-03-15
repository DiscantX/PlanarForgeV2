from pprint import pprint
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes

# Load schema
loader = SchemaLoader("schemas")
loader.load_all()
loader.resolve_types(FieldTypes)
# itm_schema = loader.get("ITM")

# itm_schema = loader.get("ITM")
biff_schema = loader.get("BIFF")
# print(biff_schema)


# Open file
with open("Items.bif", "rb") as f:
    reader = BinaryReader(f)
    parser = BinaryParser(biff_schema)
    resource = parser.read(reader, name="CHAN04", source="CHAN04.itm")

# Pretty print sections
print("\nResource Sections:")
pprint(resource.sections)

# Optional: pretty print all top-level field values
print("\nResource Values:")
pprint(resource.values)
