from pathlib import Path
import yaml


class Field:
    def __init__(self, name, field_type, attributes=None, children=None):
        self.name = name
        self.type_name = field_type
        self.attributes = attributes or {}
        self.children = children or []
        self.type = None  # resolved later via FieldTypes registry

    def __repr__(self):
        return f"<Field {self.name}:{self.type_name}>"


class Section:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
        self.field_map = {f.name: f for f in fields}

    def get_field(self, name):
        return self.field_map.get(name)

    def __iter__(self):
        return iter(self.fields)

    def __repr__(self):
        return f"<Section {self.name} ({len(self.fields)} fields)>"


class Schema:
    def __init__(self, name, sections=None):
        self.name = name
        self.sections = sections or []
        self.section_map = {s.name: s for s in self.sections}

        # Flatten all fields across sections for quick lookup
        self.field_map = {}
        for section in self.sections:
            for field in section:
                self.field_map[field.name] = field

    def get_section(self, name):
        """Fetch a section by name (returns None if not present)."""
        return self.section_map.get(name)

    def get_field(self, name):
        """Fetch a field by name across all sections (returns None if not present)."""
        return self.field_map.get(name)

    def __iter__(self):
        """Iterate over all fields in all sections."""
        for section in self.sections:
            for field in section:
                yield field

    def __repr__(self):
        total_fields = sum(len(s.fields) for s in self.sections)
        section_names = ", ".join(s.name for s in self.sections)
        return f"<Schema {self.name} ({total_fields} fields) Sections: [{section_names}]>"


class SchemaLoader:
    def __init__(self, schema_directory):
        self.schema_directory = Path(schema_directory)
        self.schemas = {}

    def load_all(self):
        """Load all YAML schema files in the schema directory."""
        for file in self.schema_directory.glob("*.yaml"):
            schema = self._load_schema(file)
            self.schemas[schema.name] = schema

    def get(self, name):
        """Fetch a loaded schema by name (returns None if not present)."""
        return self.schemas.get(name)

    def resolve_types(self, registry):
        """
        Resolve Field.type using a FieldTypes registry.
        Must be called after all schemas are loaded.
        """
        for schema in self.schemas.values():
            for field in schema:
                field.type = registry.get(field.type_name)

    def _load_schema(self, filepath):
        """Load a single YAML schema file and construct a Schema object."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        name = data.pop("name")  # remove the name from the top-level dict

        sections = []
        for section_name, section_data in data.items():
            # Some schema sections might be empty or not have fields
            fields_data = section_data.get("fields", [])
            fields = [self._parse_field(f) for f in fields_data]
            sections.append(Section(section_name, fields))

        return Schema(name, sections)

    def _parse_field(self, field_data):
        """Recursively parse a field and its children from YAML."""
        name = field_data["name"]
        field_type = field_data["type"]
        attributes = {k: v for k, v in field_data.items() if k not in ("name", "type", "fields")}
        children = [self._parse_field(f) for f in field_data.get("fields", [])]
        return Field(name, field_type, attributes, children)