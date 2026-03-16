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
resource = resource_loader.load()
print(resource.sections["bif_entries"][:20])


# itm_schema = loader.get("ITM")
# biff_schema = loader.get("BIFF")
# key_schema = loader.get("KEY")

# with open("chitin.key", "rb") as f:
#     reader = BinaryReader(f)
#     parser = BinaryParser(key_schema)
#     resource = parser.read(reader, name="CHITIN", source="chitin.key")
    
#     test = BinaryReader(f).seek(2433)
#     string = BinaryReader(f).read_string(18)
#     print(f"String at offset 2433: {string}")

# # # Open file
# # with open("Items.bif", "rb") as f:
# #     reader = BinaryReader(f)
# #     parser = BinaryParser(biff_schema)
# #     resource = parser.read(reader, name="CHAN04", source="CHAN04.itm")

# # # Optional: pretty print all top-level field values
# # print("\nResource Values:")
# # pprint(resource.values)
# def decode_resource_locator(locator):
#     resource_index = locator & 0x3FFF
#     reserved = (locator >> 14) & 0x3F
#     bif_index = locator >> 20

#     return {
#         "bif_index": bif_index,
#         "resource_index": resource_index,
#         "reserved": reserved
#     }

# def print_sections(resource):
#     print("\nResource Sections:")
#     for section in resource.sections:
#         print(f"\nSection: {section}")
#         for entry in resource.sections[section][:50]:
#             if section == "bif_entries":
#                 entry["decoded_location"] = decode_resource_locator(entry.get("file_location"))
#             print(entry)

# print_sections(resource)

# Pretty print sections
# print("\nResource Sections:")
# for section in resource.sections:
#     print(f"\nSection: {section}")
#     for entry in resource.sections[section]:
#         pprint(entry)
#         print("222"*20)
#         print()