from core.resource import Resource

class BinaryParser:
    def __init__(self, schema):
        self.schema = schema

    def read(self, reader, name=None, source=None):
        resource = Resource(self.schema, name=name, source=source)
        resource.sections = {}  # Initialize empty sections

        # Pre-register all sections in the resource
        for sec_name in ("header", "extended_header", "feature_block"):
            resource.sections[sec_name] = []

        # Read header section
        header_section = self.schema.header
        resource.sections["header"] = [self._read_section(reader, header_section, resource)]

        # Read extended header section(s)
        count_ext = resource.get("count_of_extended_headers", 0)
        ext_section = self.schema.extended_header
        ext_values = []
        for _ in range(count_ext):
            ext_values.append(self._read_section(reader, ext_section, resource))
        resource.sections["extended_header"] = ext_values

        # Read feature block section(s)
        count_feat = resource.get("count_of_equipping_feature_blocks", 0)
        feat_section = self.schema.feature_block
        feat_values = []
        for _ in range(count_feat):
            feat_values.append(self._read_section(reader, feat_section, resource))
        resource.sections["feature_block"] = feat_values

        return resource

    def _read_section(self, reader, section, resource):
        section_data = {}
        for field in section:
            value = field.type.read(reader, field)
            section_data[field.name] = value

        # Set the fields all at once to avoid KeyError
        for fname, val in section_data.items():
            resource.values[fname] = val  # bypass set() temporarily
        return section_data
