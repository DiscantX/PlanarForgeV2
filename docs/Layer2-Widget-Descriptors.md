# Layer 2: The Widget Descriptor Layer

Between the project schema and whatever user-interface toolkit is eventually chosen sits a thin layer of plain Python that turns each schema field into a self-contained *widget descriptor*: a small record saying "show a dropdown with these options" or "show a number box between 0 and 255". The interface renders descriptors without ever consulting a schema again, and none of this code depends on a particular UI framework. This page specifies the descriptor, the factory that builds it, and how an inspector panel is populated.

The widget descriptor layer sits between the project schema and the UI framework. It
is pure Python with no UI framework dependencies.

## Purpose

- Translates project schema fields into self-contained widget specifications
- Resolves the two-schema lookup (project schema + binary schema) once at
  descriptor build time
- Produces descriptors the UI can render without consulting any schema again
- Keeps framework-specific code isolated in the widget factory

## WidgetDescriptor

```python
@dataclass
class WidgetDescriptor:
    widget_type: str        # "text", "number", "dropdown", "checkbox_group",
                            # "resref_picker"
    label: str              # display name, derived from field name
    field_name: str         # project-level field name
    options: dict = None    # for dropdown/checkbox_group: {raw_value: display_label}
    min_val: int = None     # for number
    max_val: int = None     # for number
    nullable: bool = False
    picker: str = None      # for resref_picker: "bam", "dialog", "projectile",
                            # "generic"
```

## WidgetDescriptorFactory

**Constructor receives:**
- `binary_schema_loader` — the existing `SchemaLoader` instance
- `table_resolver` — the existing `TableResolver` instance (for IDS lookups if needed)

**`build(project_field, target_game)` method:**

1. Resolve binary field name via `from:` + target game
2. Look up binary schema for target game and resource type
3. Find binary field, using `section:` hint if provided, erroring on ambiguity
4. Build and return `WidgetDescriptor` based on project field type

**Binary field lookup — ambiguity handling:**

```python
def _find_binary_field(self, binary_schema, field_name, section_hint=None):
    if section_hint:
        section = binary_schema.get_section(section_hint)
        field = section.get_field(field_name)
        # raises if not found
        return field

    matches = []
    for section in binary_schema.sections:
        field = section.get_field(field_name)
        if field is not None:
            matches.append((section.name, field))

    if not matches:
        raise ValueError(f"Field '{field_name}' not found in schema")

    if len(matches) > 1:
        found_in = ", ".join(s for s, _ in matches)
        raise ValueError(
            f"Ambiguous field '{field_name}' in sections ({found_in}). "
            f"Add 'section:' to project schema field."
        )

    return matches[0][1]
```

**Display name formatting:**

```python
def _format_display_name(self, field_name):
    return field_name.replace("_", " ").capitalize()
```

**Type dispatch in `_build_descriptor`:**

- `strref` → `widget_type="text"`
- `resref` → `widget_type="resref_picker"`, passes through `picker` attribute
- `number` → `widget_type="number"`, passes through `min`/`max`
- `enum` → `widget_type="dropdown"`, options from `binary_field.attributes["values"]`
- `bitmask` → `widget_type="checkbox_group"`, options from `binary_field.attributes["flags"]`
- `text` → `widget_type="text"` (same as strref widget, different semantics)

For `enum` and `bitmask`, options are passed through directly from the binary schema.
No transformation. The binary schema is the single source of truth.

## Inspector population

```python
def populate_inspector(resource, section_name, session, factory, target_game):
    section = resource.project_schema.get_group(section_name)
    for field in section.fields:
        descriptor = factory.build(field, target_game)
        widget = WidgetFactory.create(descriptor)
        widget.set_value(resource.get(field.name))
        widget.on_change(lambda v, f=field:
            session.execute(
                FieldEditCommand(resource, f.name, resource.get(f.name), v)
            )
        )
        inspector_layout.add(widget)
```

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Project Schema Format](Layer2-Schema-Format.md): the input to the factory
* [Undo and Redo](Layer2-Undo-Redo.md): the commands that widgets emit on change
* [Field Types Reference](Field-Types-Reference.md): the binary field types whose `values` and `flags` populate dropdowns and checkbox groups
