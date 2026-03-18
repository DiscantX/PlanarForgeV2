import requests
from bs4 import BeautifulSoup
import yaml
import re

class HexInt(int):
    pass

def represent_hexint(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:int', f'0x{data:04x}')

yaml.add_representer(HexInt, represent_hexint)

def parse_itm_tables_to_yaml(url, output_file):
    response = requests.get(url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    all_tables = soup.find_all('table')
    collected_tables = []
    resource_name = "UNKNOWN"

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

    for t_name, t_rows in collected_tables:
        yaml_data[t_name] = {'fields': t_rows}

    # Dump to string
    yaml_string = yaml.dump(yaml_data, sort_keys=False, allow_unicode=True)

    # Insert newline before each top-level section
    for key in yaml_data:
        if key != 'name':
            yaml_string = yaml_string.replace(f'\n{key}:', f'\n\n{key}:')

    # Insert newline between entries
    formatted_yaml = re.sub(r'\n(\s*)- name:', r'\n\n\1- name:', yaml_string)

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


# Example usage
url = 'https://gibberlings3.github.io/iesdp/file_formats/ie_formats/itm_v2.0.htm'  # Replace with actual page
output_file = 'resource.yaml'
parse_itm_tables_to_yaml(url, output_file)