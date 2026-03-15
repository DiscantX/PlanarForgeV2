from pprint import pprint
from core.binary.reader import BinaryReader
from core.binary.parser import BinaryParser
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes

# Load schema
loader = SchemaLoader("schemas")
loader.load_all()
loader.resolve_types(FieldTypes)

itm_schema = loader.get("ITM")
biff_schema = loader.get("BIFF")

with open("DAGG11.itm", "rb") as f:
    reader = BinaryReader(f)
    parser = BinaryParser(itm_schema)
    resource = parser.read(reader, name="CHAN04", source="CHAN04.itm")

# # Open file
# with open("Items.bif", "rb") as f:
#     reader = BinaryReader(f)
#     parser = BinaryParser(biff_schema)
#     resource = parser.read(reader, name="CHAN04", source="CHAN04.itm")

# # Optional: pretty print all top-level field values
# print("\nResource Values:")
# pprint(resource.values)


# Pretty print sections
pprint(resource.sections)
# print("\nResource Sections:")
# for section in resource.sections:
#     print(f"\nSection: {section}")
#     for entry in resource.sections[section]:
#         pprint(entry)
#         print("222"*20)
#         print()