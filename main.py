'''
Planar Forge V2
This is te entry point for the app. Currently it is used for testing and development, and in the future the entry point will likely move to something like ui.app.py
'''


from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes, UInt32, UInt16, ResRef, Enum, StrRef
from core.resource import Resource

schema_loader = SchemaLoader("schemas")
schema_loader.load_all()

cre_schema = schema_loader.get("CRE")

print(cre_schema)


registry = FieldTypes()

# for field in cre_schema:
#     print(field.name, field.type, field.attributes)
#     field.type = FieldTypes.get("uint32")
#     print(field.type)


def on_resource_change(event):
    print(event.resource.name, event.field_name, event.old_value, "→", event.new_value)

cre_resource = Resource(cre_schema, name="test_cre")
cre_resource.add_listener(on_resource_change)
cre_resource.set("xp", 1000)
cre_resource.set("xp", 2000)
print(cre_resource["xp"])
