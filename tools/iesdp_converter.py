import requests
from bs4 import BeautifulSoup
import yaml
import re
import argparse
import os
from urllib.parse import urlparse

class HexInt(int):
    pass

def represent_hexint(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:int', f'0x{data:04x}')

yaml.add_representer(HexInt, represent_hexint)

class FlowList(list):
    pass

def represent_flow_list(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

yaml.add_representer(FlowList, represent_flow_list)

def parse_itm_tables_to_yaml(url, output_file=None):
    response = requests.get(url)
    response.raise_for_status()

    version_match = re.search(r'v(\d+(?:\.\d+)*)', url)
    version_str = f"V{version_match.group(1)}" if version_match else "V_UNKNOWN"
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    games = []
    games_part = ""
    
    # Locate the specific text node containing "Applies to:"
    applies_to_node = soup.find(string=re.compile(r'Applies to:', re.IGNORECASE))
    
    if applies_to_node:
        # Get immediate parent tag
        curr = applies_to_node.parent
        
        # Traverse up if it's an inline element to find the block container
        while curr.name in ['strong', 'b', 'em', 'span', 'font', 'i', 'u', 'a']:
            if curr.parent:
                curr = curr.parent
            else:
                break
        
        block_container = curr
        
        # Check text within the same block first
        full_text = block_container.get_text(" ", strip=True)
        match = re.search(r'Applies to:?[\s]*(.*)', full_text, re.IGNORECASE)
        
        if match and match.group(1).strip():
            # Found in same block (e.g. <p>Applies to: BG1</p>)
            games_part = match.group(1).strip()
        else:
            # Not in same block (e.g. <div class="header">Applies to:</div><div class="indent">IWD2</div>)
            # Search next siblings for content, skipping breaks/lines
            sibling = block_container.next_sibling
            while sibling:
                if sibling.name: # It's a Tag
                    if sibling.name not in ['br', 'hr']:
                        text = sibling.get_text(strip=True)
                        if text:
                            games_part = text
                            break
                else: # It's a NavigableString
                    text = str(sibling).strip()
                    if text:
                        games_part = text
                        break
                sibling = sibling.next_sibling

    if games_part:
        game_texts = [g.strip() for g in games_part.split(',') if g.strip()]

        # BGEE expansion rule
        if 'BGEE' in game_texts:
            game_texts.extend(['BGEE', 'BG2EE', 'IWDEE', 'PSTEE'])
        
        # Process and deduplicate (moved from inside the 'if' to a shared location)
        processed_games = []
        for game_text in game_texts:
            # Remove version info like (v2.5), take part before ':', uppercase
            game_id = re.sub(r'\s*\(.*\)', '', game_text).strip().upper().split(':')[0]
            if game_id and game_id not in processed_games:
                processed_games.append(game_id)
        games = sorted(processed_games)
    
    all_tables = soup.find_all('table')
    collected_tables = []
    resource_name = "UNKNOWN"
    control_fields = {}

    for i, table in enumerate(all_tables, start=1):
        headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
        
        # Filter tables: must strictly match these headers
        if headers != ['offset', 'size (datatype)', 'description'] and headers != ['offset', 'size (data type)', 'description']:
            continue
            
        # Attempt to use preceding div > a as table name
        prev_div = table.find_previous('div', class_='fileHeader')
        link = prev_div.find('a') if prev_div else None
        raw_table_name = link.get_text(strip=True) if link else f"table_{i}"
        table_name = raw_table_name.lower().strip().replace(' ', '_')

        rows = table.find_all('tr')
        table_data = []

        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) != len(headers):
                continue

            if cells and headers and cells[0].get_text(strip=True).lower() == headers[0]:
                continue

            row_dict = {}
            temp_data = {}

            for j, header in enumerate(headers):
                cell_text = cells[j].get_text(strip=True)
                if header == 'offset':
                    try:
                        temp_data['offset'] = HexInt(int(cell_text, 16))
                    except ValueError:
                        temp_data['offset'] = cell_text
                elif header == 'size (datatype)' or header == 'size (data type)':
                    # split number and type
                    # Handles standard "4 (dword)" and multiplier "1*4 (byte)"
                    match = re.match(r'(\d+)(?:\*(\d+))?\s*\(?([^\)]+)?\)?', cell_text)
                    if match:
                        unit_size = int(match.group(1))
                        multiplier = int(match.group(2)) if match.group(2) else 1
                        temp_data['size'] = unit_size * multiplier
                        
                        raw_type = match.group(3).strip() if match.group(3) else ''
                        clean_type = raw_type.lower().replace(' ', '_')
                        
                        # specific override for 1*4 (byte) -> bitmask
                        if unit_size == 1 and multiplier == 4 and 'byte' in clean_type:
                            temp_data['type'] = 'bitmask'
                        else:
                            temp_data['type'] = clean_type
                    else:
                        temp_data['size'] = None
                        temp_data['type'] = ''
                elif header == 'description':
                    # Get the original text content of the cell.
                    # Use separator='\n' to ensure <br> and block elements are treated as line breaks.
                    full_text = cells[j].get_text(separator='\n', strip=True)

                    # First, check the original text for the signature to extract the resource name.
                    # This must happen before we strip brackets to create the field name.
                    if 'signature' in full_text.lower():
                        # Very robust regex to capture signature value inside brackets, ignoring specific quote styles
                        sig_match = re.search(r"\([^\w]*(\w+)[^\w]*\)", full_text)
                        if sig_match:
                            resource_name = sig_match.group(1)

                    # Now, determine the field name, prioritizing link text if it exists.
                    first_link = cells[j].find('a')
                    if first_link:
                        # Use link text, stop at first line break
                        raw_name = first_link.get_text(separator='\n', strip=True).split('\n')[0]
                    else:
                        # Fallback to cell text, stop at first line break
                        raw_name = full_text.split('\n')[0]

                    # Strip everything after a punctuation mark (anything not alphanumeric or space)
                    # This effectively handles "strip non-alphanumeric" by cutting the string there.
                    truncated_name = re.split(r'[^a-zA-Z0-9\s]', raw_name)[0]

                    # Collapse multiple spaces and strip
                    clean_name = re.sub(r'\s+', ' ', truncated_name).strip()

                    temp_data['name'] = clean_name.lower().replace(' ', '_')

                    # --- Field Renaming Heuristics ---
                    # Ensure naming conventions match BinaryParser expectations (e.g. index vs offset)
                    
                    f_name = temp_data['name']
                    f_size = temp_data.get('size')
                    
                    # Rule: 2-byte "offsets" are usually indices (e.g. index_into_feature_blocks)
                    if f_size == 2 and ('offset' in f_name or 'index' in f_name):
                        # Identify the target (e.g. "feature_blocks")
                        # Remove 'offset_to_', 'index_to_', '_offset', etc.
                        target = f_name.replace('offset_to_', '').replace('index_to_', '').replace('_offset', '').replace('index_into_', '')
                        # Ensure plural target for consistency
                        if not target.endswith('s'): 
                            target += 's'
                        
                        # Standardize to "index_into_{target}"
                        temp_data['name'] = f"index_into_{target}"
                    
                    field_name = temp_data['name']
                    
                    # --- Control Field Linking ---
                    # Detect offset/count fields and link them to their target sections
                    
                    # Matches: offset_to_X, count_of_X, X_offset, X_count
                    match_prefix = re.match(r'(offset_to|count_of)_(.*)', field_name)
                    match_suffix = re.match(r'(.*)_(offset|count)$', field_name)
                    
                    target_raw = None
                    attr_type = None
                    
                    if match_prefix:
                        attr_type = 'offset_field' if match_prefix.group(1) == 'offset_to' else 'count_field'
                        target_raw = match_prefix.group(2)
                    elif match_suffix:
                        attr_type = 'offset_field' if match_suffix.group(2) == 'offset' else 'count_field'
                        target_raw = match_suffix.group(1)
                        
                    if target_raw and attr_type:
                        # Normalize target to canonical section name
                        # 1. Singularize (extended_headers -> extended_header)
                        target_singular = target_raw[:-1] if target_raw.endswith('s') else target_raw
                        
                        # 2. Canonical mappings (e.g. casting_feature_block -> feature_block)
                        # This ensures that specific header fields map to the generic section definition
                        canonical_target = target_singular
                        if 'feature_block' in target_singular:
                            canonical_target = 'feature_block'
                        elif 'extended_header' in target_singular:
                            canonical_target = 'extended_header'
                            
                        if canonical_target not in control_fields:
                            control_fields[canonical_target] = {}
                        
                        control_fields[canonical_target][attr_type] = field_name

                else:
                    temp_data[header] = cell_text

            for key in ['name', 'type', 'size', 'offset']:
                if key in temp_data:
                    row_dict[key] = temp_data.pop(key)
            row_dict.update(temp_data)

            table_data.append(row_dict)

        collected_tables.append((table_name, table_data))

    # Construct final YAML structure
    yaml_data = {}
    yaml_data['name'] = resource_name
    yaml_data['version'] = version_str
    yaml_data['games'] = FlowList(games)

    for t_name, t_rows in collected_tables:
        section_data = {}
        if t_name in control_fields:
            section_data.update(control_fields[t_name])
        section_data['fields'] = t_rows
        yaml_data[t_name] = section_data

    # Dump to string
    yaml_string = yaml.dump(yaml_data, sort_keys=False, allow_unicode=True)

    # Insert newline before each top-level section
    for key in yaml_data:
        if key not in ['name', 'version', 'games']:
            yaml_string = yaml_string.replace(f'\n{key}:', f'\n\n{key}:', 1)

    # Insert newline between entries
    formatted_yaml = re.sub(r'\n(\s*)- name:', r'\n\n\1- name:', yaml_string)

    if output_file is None:
        parsed_url = urlparse(url)
        path = parsed_url.path
        filename = os.path.basename(path)
        base, _ = os.path.splitext(filename)
        if not base:
            base = "resource"
        safe_name = base.replace('.', '_')
        output_file = f"{safe_name}.yaml"
        print(f"Auto-generating output filename: {output_file}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(formatted_yaml)

    print(f"YAML file saved to {output_file}")

    # Verify validity
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            yaml.safe_load(f)
        print("YAML validation successful.")
    except yaml.YAMLError as e:
        print(f"YAML validation failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert IESDP HTML file format pages to PlanarForge YAML schemas.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example:
  python tools/iesdp_converter.py "https://gibberlings3.github.io/iesdp/file_formats/ie_formats/itm_v1.0.htm" -o itm_v1.yaml
"""
    )
    parser.add_argument("url", help="The URL of the IESDP page to parse.")
    parser.add_argument("-o", "--output", help="The name of the output YAML file. If not provided, it is derived from the URL.")
    
    args = parser.parse_args()
    
    parse_itm_tables_to_yaml(args.url, args.output)