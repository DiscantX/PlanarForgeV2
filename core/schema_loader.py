from pathlib import Path
import yaml
from collections import defaultdict

class Schema:
    def __init__(self, metadata, sections=None):
        self.metadata = metadata or {}
        self.name = self.metadata.get("name")
        self.sections = sections or []
        self.games = self.metadata.get("games") or self.metadata.get("Games") or []
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

class Section:
    def __init__(self, name, fields, offset_field=None, count_field=None):
        self.name = name
        self.fields = fields
        self.offset_field = offset_field
        self.count_field = count_field
        self.field_map = {f.name: f for f in fields}

    def get_field(self, name):
        return self.field_map.get(name)

    def __iter__(self):
        return iter(self.fields)

    def __repr__(self):
        return f"<Section {self.name} ({len(self.fields)} fields)>"

class Field:
    def __init__(self, name, field_type, attributes=None, children=None):
        self.name = name
        self.type_name = field_type
        self.attributes = attributes or {}
        self.children = children or []
        self.type = None  # resolved later via FieldTypes registry

    def __repr__(self):
        return f"<Field {self.name}:{self.type_name}>"

class SchemaLoader:
    def __init__(self, schema_directory):
        self.schema_directory = Path(schema_directory)
        self.schemas = {} # Default/Fallback schemas
        self.game_schemas = defaultdict(dict) # { "BG1": { "ITM": schema } }

    def load_all(self):
        """Load all YAML schema files in the schema directory."""
        for file in self.schema_directory.rglob("*.yaml"):
            schema = self._load_schema(file)
            
            # Register for specific games if listed
            if schema.games:
                for game in schema.games:
                    self.game_schemas[game][schema.name] = schema
            else:
                # Otherwise register as a default/generic schema
                self.schemas[schema.name] = schema

    def get(self, name, game=None):
        """
        Fetch a loaded schema by name, optionally for a specific game.
        Prioritizes game-specific schemas, falls back to default.
        """
        if game and game in self.game_schemas:
            if name in self.game_schemas[game]:
                return self.game_schemas[game][name]
        
        # Fallback
        return self.schemas.get(name)

    def resolve_types(self, registry):
        """
        Resolve Field.type using a FieldTypes registry.
        Must be called after all schemas are loaded.
        """
        def resolve_field(field):
            field.type = registry.get(field.type_name)
            for child in field.children:
                resolve_field(child)

        # Collect all unique schema instances to avoid double-processing
        all_schemas = set(self.schemas.values())
        for game_map in self.game_schemas.values():
            all_schemas.update(game_map.values())

        for schema in all_schemas:
            for field in schema:
                resolve_field(field)

    def _load_schema(self, filepath):
        """Load a single YAML schema file and construct a Schema object."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        metadata = {}
        sections = []

        for key, value in data.items():
            if isinstance(value, dict):
                fields_data = value.get("fields", [])
                fields = [self._parse_field(f) for f in fields_data]
                
                # Validate for duplicate field names within the section
                seen_names = set()
                for field in fields:
                    if field.name in seen_names:
                        raise ValueError(f"Schema validation error in '{filepath.name}': Duplicate field name '{field.name}' found in section '{key}'.")
                    seen_names.add(field.name)

                # The parser walks structures sequentially and does not seek to per-field offsets.
                # Fixed-size fields therefore need to form a contiguous layout.
                expected_offset = 0
                for field in fields:
                    offset = field.attributes.get("offset")
                    size = field.attributes.get("size")
                    if isinstance(offset, int):
                        if offset != expected_offset:
                            raise ValueError(
                                f"Schema validation error in '{filepath.name}': "
                                f"Section '{key}' expected next field at {hex(expected_offset)}, "
                                f"but field '{field.name}' starts at {hex(offset)}."
                            )
                        if not isinstance(size, int):
                            raise ValueError(
                                f"Schema validation error in '{filepath.name}': "
                                f"Section '{key}' field '{field.name}' must define an integer size."
                            )
                        expected_offset = offset + size

                section = Section(
                    key,
                    fields,
                    offset_field=value.get("offset_field"),
                    count_field=value.get("count_field")
                )
                sections.append(section)
            else:
                metadata[key] = value

        # Post-validation for inter-section references to the header
        header_section = next((s for s in sections if s.name == 'header'), None)
        if header_section:
            header_field_names = {f.name for f in header_section.fields}
            for section in sections:
                if section.name == 'header':
                    continue

                if not section.offset_field:
                    raise ValueError(
                        f"Schema validation error in '{filepath.name}': "
                        f"Section '{section.name}' is missing required 'offset_field'."
                    )

                if section.offset_field not in header_field_names:
                    raise ValueError(
                        f"Schema validation error in '{filepath.name}': "
                        f"Section '{section.name}' references non-existent offset_field '{section.offset_field}' in header."
                    )

        return Schema(metadata, sections)

    def _parse_field(self, field_data):
        """Recursively parse a field and its children from YAML."""
        name = field_data["name"]
        field_type = field_data["type"]
        attributes = {k: v for k, v in field_data.items() if k not in ("name", "type", "fields")}
        children = [self._parse_field(f) for f in field_data.get("fields", [])]
        return Field(name, field_type, attributes, children)
