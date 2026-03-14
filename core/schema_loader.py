from pathlib import Path
import yaml


class Field:
    def __init__(self, name, field_type, attributes=None, children=None):
        self.name = name
        self.type_name = field_type
        self.attributes = attributes or {}
        self.children = children or []
        self.type = None

    def __repr__(self):
        return f"<Field {self.name}:{self.type}>"


class Schema:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
        self.field_map = {f.name: f for f in fields}

    def get_field(self, name):
        return self.field_map.get(name)

    def __iter__(self):
        return iter(self.fields)

    def __repr__(self):
        return f"<Schema {self.name} ({len(self.fields)} fields)>"


class SchemaLoader:
    def __init__(self, schema_directory):
        self.schema_directory = Path(schema_directory)
        self.schemas = {}

    def load_all(self):
        for file in self.schema_directory.glob("*.yaml"):
            schema = self._load_schema(file)
            self.schemas[schema.name] = schema

    def get(self, name):
        return self.schemas.get(name)

    def _load_schema(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        name = data["name"]
        fields = [self._parse_field(f) for f in data.get("fields", [])]

        return Schema(name, fields)

    def _parse_field(self, field_data):
        name = field_data["name"]
        field_type = field_data["type"]

        attributes = {
            k: v for k, v in field_data.items()
            if k not in ("name", "type", "fields")
        }

        children = []

        if "fields" in field_data:
            children = [self._parse_field(f) for f in field_data["fields"]]

        return Field(name, field_type, attributes, children)