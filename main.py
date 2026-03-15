from pprint import pprint
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes

# Load schema
loader = SchemaLoader("schemas")
loader.load_all()
loader.resolve_types(FieldTypes)
cre_schema = loader.get("ITM")

# Open file
with open("BLUN30C.itm", "rb") as f:
    reader = BinaryReader(f)
    parser = BinaryParser(cre_schema)
    resource = parser.read(reader, name="sw1h01", source="sw1h01.itm")

# Pretty print sections
print("\nResource Sections:")
pprint(resource.sections)

# Optional: pretty print all top-level field values
print("\nResource Values:")
pprint(resource.values)
