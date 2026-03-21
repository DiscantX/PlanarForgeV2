import requests
from bs4 import BeautifulSoup
import yaml
import re
import argparse
import os
from urllib.parse import urlparse

SCHEMA_TABLE_HEADERS = {
    ('offset', 'size (datatype)', 'description'),
    ('offset', 'size (data type)', 'description'),
}

KNOWN_GAMES = {
    'BG1',
    'BG2',
    'BGEE',
    'BG2EE',
    'IWDEE',
    'IWD',
    'IWD2',
    'PST',
    'PSTEE',
}

GAME_MATCH_ALIASES = {
    'BGEE': {'BGEE', 'BG2EE', 'IWDEE'},
    'BG2EE': {'BGEE', 'BG2EE', 'IWDEE'},
    'IWDEE': {'BGEE', 'BG2EE', 'IWDEE'},
}

GAME_PRIORITY = [
    'BGEE',
    'BG2EE',
    'IWDEE',
    'BG2',
    'BG1',
    'IWD2',
    'IWD',
    'PST',
    'PSTEE',
]

GAME_SELECTION_FALLBACKS = {
    'BGEE': ['BGEE', 'BG2EE', 'IWDEE', 'BG2', 'BG1'],
    'BG2EE': ['BG2EE', 'BGEE', 'IWDEE', 'BG2', 'BG1'],
    'IWDEE': ['IWDEE', 'IWD', 'BGEE', 'BG2EE'],
    'BG2': ['BG2', 'BG1'],
    'BG1': ['BG1', 'BG2'],
    'IWD2': ['IWD2', 'IWD'],
    'IWD': ['IWD', 'IWDEE'],
    'PSTEE': ['PSTEE', 'PST'],
    'PST': ['PST', 'PSTEE'],
}

SECTION_NAME_ALIASES = {
    'overlay': 'overlays',
    'overlay_section': 'overlays',
    'extended_headers': 'extended_header',
    'feature_blocks': 'feature_block',
    'known_spell': 'known_spells',
    'known_spells': 'known_spells',
    'memorized_spell': 'memorized_spells',
    'memorized_spells': 'memorized_spells',
    'memorized_spells_table': 'memorized_spells',
    'items_table': 'items',
}

TYPE_ALIASES = {
    'signed_byte': 'byte',
    'signed_word': 'word',
    'signed_dword': 'dword',
}

FIELD_NAME_ALIASES = {
    'short_name_tooltip': 'short_name',
    'spell_level_1': 'spell_level',
    'memorised': 'memorized',
    'amount_memorised': 'amount_memorized',
    'eff_structure_version_0_version_1_eff_1_version_2_eff': 'eff_version',
}

NO_SCOPE_CHANGE = object()

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

def _to_snake_case(text):
    text = re.sub(r'[^A-Za-z0-9]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text.replace(' ', '_')

def _extract_resource_name(soup):
    title = soup.find('div', class_='title_main')
    if not title:
        return "UNKNOWN"

    match = re.match(r'([A-Za-z0-9]+)\s+file\s+format', title.get_text(" ", strip=True), re.IGNORECASE)
    if not match:
        return "UNKNOWN"

    return match.group(1).upper()

def _normalize_game_id(game_text):
    if not game_text:
        return ""

    normalized = re.sub(r'\s*\(.*\)', '', game_text).strip().upper().split(':')[0]
    normalized = re.sub(r'[^A-Z0-9]+', '', normalized)
    return normalized

def _expand_games(game_ids, include_pstee=False):
    expanded_games = []

    for game_id in game_ids:
        expanded_targets = set(GAME_MATCH_ALIASES.get(game_id, {game_id}))
        if game_id == 'BGEE' and include_pstee:
            expanded_targets.add('PSTEE')

        for expanded in expanded_targets:
            if expanded and expanded not in expanded_games:
                expanded_games.append(expanded)

    return expanded_games

def _extract_applies_to_games(soup):
    games = []
    games_part = ""

    applies_to_node = soup.find(string=re.compile(r'Applies to:', re.IGNORECASE))

    if not applies_to_node:
        return games

    curr = applies_to_node.parent
    while curr and curr.name in ['strong', 'b', 'em', 'span', 'font', 'i', 'u', 'a']:
        curr = curr.parent

    block_container = curr
    full_text = block_container.get_text(" ", strip=True)
    match = re.search(r'Applies to:?[\s]*(.*)', full_text, re.IGNORECASE)

    if match and match.group(1).strip():
        games_part = match.group(1).strip()
    else:
        sibling = block_container.next_sibling
        while sibling:
            if getattr(sibling, 'name', None):
                if sibling.name not in ['br', 'hr']:
                    text = sibling.get_text(strip=True)
                    if text:
                        games_part = text
                        break
            else:
                text = str(sibling).strip()
                if text:
                    games_part = text
                    break
            sibling = sibling.next_sibling

    if not games_part:
        return games

    raw_games = []
    for token in re.split(r',|\band\b', games_part, flags=re.IGNORECASE):
        game_id = _normalize_game_id(token)
        if game_id in KNOWN_GAMES and game_id not in raw_games:
            raw_games.append(game_id)

    include_pstee = 'BGEE' in raw_games and 'PSTEE' not in soup.get_text(" ", strip=True).upper()
    return sorted(_expand_games(raw_games, include_pstee=include_pstee))

def _canonicalize_section_name(raw_name, resource_name=None, version_str=None):
    if not raw_name:
        return ""

    cleaned = raw_name.strip()

    if resource_name:
        cleaned = re.sub(
            rf'^{re.escape(resource_name)}\s+v?\d+(?:\.\d+)*\s+',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf'^{re.escape(resource_name)}\s+',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )

    if version_str:
        cleaned = re.sub(
            rf'^{re.escape(version_str)}\s+',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )

    normalized = _to_snake_case(cleaned)
    normalized = re.sub(r'_(table|section)$', '', normalized)
    return SECTION_NAME_ALIASES.get(normalized, normalized)

def _choose_preferred_game(selected_games, target_game=None):
    if target_game:
        return target_game

    for game_id in GAME_PRIORITY:
        if game_id in selected_games:
            return game_id

    return selected_games[0] if selected_games else None

def _parse_game_label(label_text):
    if not label_text:
        return None

    normalized_label = re.sub(r'\s+', ' ', label_text).strip()
    if normalized_label.lower() == 'other games':
        return {'OTHER_GAMES'}

    tokens = []
    for token in re.split(r',|/|\band\b', normalized_label, flags=re.IGNORECASE):
        game_id = _normalize_game_id(token)
        if not game_id:
            continue
        tokens.append(game_id)

    if not tokens:
        return None

    if any(token not in KNOWN_GAMES for token in tokens):
        return None

    expanded = set()
    for token in tokens:
        expanded.update(GAME_MATCH_ALIASES.get(token, {token}))

    return expanded

def _matches_game_scope(scope_games, target_game):
    if not scope_games or not target_game:
        return False

    aliases = GAME_MATCH_ALIASES.get(target_game, {target_game})
    return bool(scope_games & aliases)

def _selection_games(preferred_game):
    if not preferred_game:
        return []

    ordered_games = []
    for game_id in GAME_SELECTION_FALLBACKS.get(preferred_game, [preferred_game]):
        if game_id not in ordered_games:
            ordered_games.append(game_id)
    return ordered_games

def _is_commentary_line(line):
    normalized = re.sub(r'\s+', ' ', line).strip().lower()
    if not normalized:
        return True

    commentary_prefixes = (
        'note:',
        'nb.:',
        'nb:',
        'see ',
        'see also ',
        'most ',
        'default value ',
        'it is unclear',
        'for dual',
        'for multi',
        'for party members',
        'for non-party characters',
        'used by ',
        'known values',
        'actual order is',
        'there are ',
        'selected weapon is',
    )
    if normalized.startswith(commentary_prefixes):
        return True

    if normalized in {'(', ')'}:
        return True

    if re.fullmatch(r'[a-z0-9_.-]+\.ids', normalized):
        return True

    return False

def _should_append_name_line(current_text, next_line):
    if not next_line or _is_commentary_line(next_line):
        return False

    next_normalized = re.sub(r'\s+', ' ', next_line).strip().lower()
    if next_normalized in {'offset', 'count', 'type', 'file', 'entries count', 'entry count'}:
        return True

    if re.fullmatch(r'.+\s(count|offset|file|type)$', next_normalized):
        return True

    current_normalized = re.sub(r'\s+', ' ', current_text).strip().lower()
    connector_suffixes = (
        ' of',
        ' the',
        ' into',
        ' to',
        ' in',
        ' for',
    )
    if current_normalized.endswith(connector_suffixes):
        return True

    if re.search(r'(resource name of the|index into|count of|offset to)$', current_normalized):
        return True

    return False

def _select_description_text(cell, preferred_game=None):
    full_text = cell.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    if not lines:
        return full_text

    generic_lines = []
    labeled_lines = []
    pending_scope_games = None
    pending_scope_parts = []

    def flush_pending_scope():
        nonlocal pending_scope_games, pending_scope_parts
        if pending_scope_games:
            scoped_text = ' '.join(part for part in pending_scope_parts if part).strip()
            if scoped_text:
                labeled_lines.append((pending_scope_games, scoped_text))
        pending_scope_games = None
        pending_scope_parts = []

    for line in lines:
        match = re.match(r'^([^:]+):\s*(.*)$', line)
        if match:
            scope_games = _parse_game_label(match.group(1))
            if scope_games:
                flush_pending_scope()
                pending_scope_games = scope_games
                if match.group(2).strip():
                    pending_scope_parts.append(match.group(2).strip())
                continue

        if pending_scope_games:
            if _is_commentary_line(line):
                flush_pending_scope()
                generic_lines.append(line)
            else:
                pending_scope_parts.append(line)
        else:
            generic_lines.append(line)

    flush_pending_scope()

    meaningful_generic_lines = [line for line in generic_lines if not _is_commentary_line(line)]

    if meaningful_generic_lines:
        return '\n'.join(meaningful_generic_lines)

    if not labeled_lines:
        return '\n'.join(generic_lines) if generic_lines else full_text

    for game_id in _selection_games(preferred_game):
        for scope_games, scoped_text in labeled_lines:
            if _matches_game_scope(scope_games, game_id):
                return scoped_text

    for scope_games, scoped_text in labeled_lines:
        if 'OTHER_GAMES' in scope_games:
            return scoped_text

    for line in generic_lines:
        if not _is_commentary_line(line):
            return line

    return labeled_lines[0][1]

def _extract_scope_note(row_text):
    cleaned = re.sub(r'\s+', ' ', row_text).strip().rstrip(':')
    if not cleaned:
        return NO_SCOPE_CHANGE

    if re.search(r'\bfor all games\b', cleaned, re.IGNORECASE):
        return None

    match = re.search(
        r'(?:the following (?:entry|entries)|continued)\s+appl(?:y|ies)(?:\s+only)?\s+to\s+(.+)$',
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return NO_SCOPE_CHANGE

    scope_games = _parse_game_label(match.group(1))
    return scope_games if scope_games else NO_SCOPE_CHANGE

def _build_version_string(base_version, target_game, base_games, selected_games):
    if not target_game:
        return base_version

    if sorted(base_games) == sorted(selected_games):
        return base_version

    return f"{base_version}_{target_game}"

def _derive_output_filename(url, target_game=None):
    parsed_url = urlparse(url)
    path = parsed_url.path
    filename = os.path.basename(path)
    base, _ = os.path.splitext(filename)
    if not base:
        base = "resource"

    safe_name = base.replace('.', '_')

    if target_game:
        match = re.match(r'^(.*)_v\d+(?:_\d+)?$', safe_name, re.IGNORECASE)
        if match:
            safe_name = f"{match.group(1)}_{target_game.lower()}"
        else:
            safe_name = f"{safe_name}_{target_game.lower()}"

    return f"{safe_name}.yaml"

def _get_table_headers(table):
    header_row = None

    thead = table.find('thead', recursive=False)
    if thead:
        for row in thead.find_all('tr', recursive=False):
            if row.find('th', recursive=False):
                header_row = row
                break

    if header_row is None:
        for row in table.find_all('tr', recursive=False):
            if row.find('th', recursive=False):
                header_row = row
                break

    if header_row is None:
        return []

    return [th.get_text(" ", strip=True).lower() for th in header_row.find_all('th', recursive=False)]

def _get_table_rows(table):
    tbody = table.find('tbody', recursive=False)
    if tbody:
        return tbody.find_all('tr', recursive=False)
    return table.find_all('tr', recursive=False)

def _extract_field_name(full_text):
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    meaningful_lines = [line for line in lines if not _is_commentary_line(line)]
    if meaningful_lines:
        name_parts = [meaningful_lines[0]]
        for next_line in meaningful_lines[1:]:
            if _should_append_name_line(' '.join(name_parts), next_line):
                name_parts.append(next_line)
            else:
                break
        primary_text = ' '.join(name_parts)
    else:
        primary_text = lines[0] if lines else full_text

    flattened_text = re.sub(r'\([^)]*\)', '', primary_text)
    flattened_text = re.sub(r'\s+', ' ', flattened_text).strip()
    flattened_text = re.sub(r'(?i)\bspell level\s*-\s*1\b', 'Spell Level', flattened_text)
    flattened_text = re.sub(r'(?i)\bspell level\s*\(less 1\)\b', 'Spell Level', flattened_text)
    flattened_text = re.split(r'\bbit\s+0\b|\b0\s*=|\b0=', flattened_text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    first_sentence = re.split(r'(?<=[A-Za-z0-9\)])\.\s+', flattened_text, maxsplit=1)[0]
    candidate = _to_snake_case(first_sentence)

    if candidate.startswith('signature_'):
        return 'signature'
    if candidate.startswith('version_'):
        return 'version'

    candidate = re.sub(r'^resource_name_of_the_([a-z0-9]+)_file$', r'\1_file', candidate)
    candidate = re.sub(r'^offset_to_(.+)$', r'offset_to_\1', candidate)
    candidate = re.sub(r'^count_of_(.+)$', r'count_of_\1', candidate)
    candidate = re.sub(r'^index_into_(.+?)_array.*$', r'index_into_\1', candidate)
    candidate = re.sub(r'^count_of_(.+?)_entries.*$', r'count_of_\1', candidate)
    candidate = re.sub(r'^number_of_(.+?)_after_effects$', r'number_of_\1_after_effects', candidate)
    candidate = re.sub(r'^animation_id_.*externali[sz]ed.*$', 'animation_id', candidate)
    candidate = re.sub(r'^level_(first|second|third)_class.*$', r'level_\1_class', candidate)
    candidate = re.sub(r'^morale_default_value.*$', 'morale', candidate)
    candidate = re.sub(r'^morale_break_.*$', 'morale_break', candidate)
    candidate = re.sub(r'^gender_.*casting_voice.*$', 'gender', candidate)
    candidate = re.sub(r'^kit_information_.*$', 'kit_information', candidate)
    candidate = re.sub(r'^strrefs_pertaining_to_the_character$', 'character_strrefs', candidate)
    candidate = candidate.replace('memorised', 'memorized')
    candidate = FIELD_NAME_ALIASES.get(candidate, candidate)

    return candidate or "unknown_field"

def _dedupe_field_names(table_data):
    seen = {}
    for row in table_data:
        name = row.get('name')
        if not name:
            continue
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            row['name'] = f"{name}_{seen[name]}"

def parse_iesdp_tables_to_yaml(url, output_file=None, target_game=None):
    response = requests.get(url)
    response.raise_for_status()

    version_match = re.search(r'v(\d+(?:\.\d+)*)', url)
    base_version_str = f"V{version_match.group(1)}" if version_match else "V_UNKNOWN"
    
    soup = BeautifulSoup(response.content, 'html.parser')
    resource_name = _extract_resource_name(soup)
    base_games = _extract_applies_to_games(soup)

    normalized_target_game = _normalize_game_id(target_game)
    if normalized_target_game and normalized_target_game not in KNOWN_GAMES:
        raise ValueError(f"Unsupported target game '{target_game}'. Expected one of: {', '.join(sorted(KNOWN_GAMES))}.")
    selected_games = [normalized_target_game] if normalized_target_game else list(base_games)
    preferred_game = _choose_preferred_game(selected_games, normalized_target_game)
    version_str = _build_version_string(base_version_str, normalized_target_game, base_games, selected_games)
    
    all_tables = soup.find_all('table')
    collected_tables = []
    control_fields = {}

    for i, table in enumerate(all_tables, start=1):
        headers = _get_table_headers(table)
        
        # Filter tables: must strictly match these headers
        if tuple(headers) not in SCHEMA_TABLE_HEADERS:
            continue
            
        # Attempt to use the nearest preceding section header as the table name.
        prev_div = table.find_previous('div', class_='fileHeader')
        raw_table_name = prev_div.get_text(" ", strip=True) if prev_div else f"table_{i}"
        table_name = _canonicalize_section_name(raw_table_name, resource_name=resource_name, version_str=version_str)

        rows = _get_table_rows(table)
        table_data = []

        next_expected_offset = 0
        active_scope_games = None

        for row in rows:
            cells = row.find_all(['td', 'th'], recursive=False)

            scope_update = _extract_scope_note(row.get_text(" ", strip=True))
            if scope_update is not NO_SCOPE_CHANGE:
                active_scope_games = scope_update
                continue

            if len(cells) != len(headers):
                continue

            if cells and headers and cells[0].get_text(strip=True).lower() == headers[0]:
                continue

            if active_scope_games and not any(_matches_game_scope(active_scope_games, game_id) for game_id in selected_games):
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
                        clean_type = re.sub(r'\*\d+$', '', clean_type)
                        clean_type = TYPE_ALIASES.get(clean_type, clean_type)
                        
                        # specific override for 1*4 (byte) -> bitmask
                        if unit_size == 1 and multiplier == 4 and 'byte' in clean_type:
                            temp_data['type'] = 'bitmask'
                        # Repeated scalar entries (for example Strref*100) cannot be
                        # represented as a single scalar without desynchronizing the
                        # parser. Preserve the raw bytes instead.
                        elif multiplier > 1 and clean_type in {'byte', 'char', 'word', 'dword', 'strref', 'resref'}:
                            temp_data['type'] = 'bytes'
                        else:
                            temp_data['type'] = clean_type
                    else:
                        temp_data['size'] = None
                        temp_data['type'] = ''
                elif header == 'description':
                    # Get the original text content of the cell.
                    # Use separator='\n' to ensure <br> and block elements are treated as line breaks.
                    full_text = cells[j].get_text(separator='\n', strip=True)
                    selected_text = _select_description_text(cells[j], preferred_game=preferred_game)

                    # First, check the original text for the signature to extract the resource name.
                    # This must happen before we strip brackets to create the field name.
                    if 'signature' in full_text.lower():
                        # Very robust regex to capture signature value inside brackets, ignoring specific quote styles
                        sig_match = re.search(r"\([^\w]*(\w+)[^\w]*\)", full_text)
                        if sig_match:
                            resource_name = sig_match.group(1).upper()

                    temp_data['name'] = _extract_field_name(selected_text or full_text)

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
                    match_suffix = re.match(r'(.*?)(?:_entries)?_(offset|count)$', field_name)
                    
                    target_raw = None
                    attr_type = None
                    
                    if match_prefix:
                        attr_type = 'offset_field' if match_prefix.group(1) == 'offset_to' else 'count_field'
                        target_raw = match_prefix.group(2)
                    elif match_suffix:
                        attr_type = 'offset_field' if match_suffix.group(2) == 'offset' else 'count_field'
                        target_raw = match_suffix.group(1)
                        
                    if target_raw and attr_type:
                        canonical_target = _canonicalize_section_name(target_raw)
                        temp_data['name'] = (
                            f"offset_to_{canonical_target}"
                            if attr_type == 'offset_field'
                            else f"count_of_{canonical_target}"
                        )
                        field_name = temp_data['name']
                            
                        if canonical_target not in control_fields:
                            control_fields[canonical_target] = {}
                        
                        control_fields[canonical_target][attr_type] = field_name

                else:
                    temp_data[header] = cell_text

            for key in ['name', 'type', 'size', 'offset']:
                if key in temp_data:
                    row_dict[key] = temp_data.pop(key)
            row_dict.update(temp_data)

            row_offset = row_dict.get('offset')
            row_size = row_dict.get('size')
            if isinstance(row_offset, int) and isinstance(row_size, int):
                if row_offset < next_expected_offset:
                    # IESDP occasionally documents alternate game-specific layouts inline.
                    # Skip rows that overlap the active byte range so the generated schema
                    # remains a single contiguous structure for the page's primary format.
                    continue
                next_expected_offset = row_offset + row_size

            table_data.append(row_dict)

        _dedupe_field_names(table_data)
        collected_tables.append((table_name, table_data))

    # Construct final YAML structure
    yaml_data = {}
    yaml_data['name'] = resource_name
    yaml_data['version'] = version_str
    yaml_data['games'] = FlowList(selected_games)

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
        output_file = _derive_output_filename(url, target_game=normalized_target_game)
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
  python tools/iesdp_converter.py "https://gibberlings3.github.io/iesdp/file_formats/ie_formats/itm_v1.htm" -o itm_v1.yaml
"""
    )
    parser.add_argument("url", help="The URL of the IESDP page to parse.")
    parser.add_argument("-o", "--output", help="The name of the output YAML file. If not provided, it is derived from the URL.")
    parser.add_argument(
        "-g",
        "--game",
        "--variant",
        dest="target_game",
        help="Generate a game-specific schema variant from a mixed IESDP page (for example: PSTEE).",
    )
    
    args = parser.parse_args()
    
    parse_iesdp_tables_to_yaml(args.url, args.output, target_game=args.target_game)


def parse_itm_tables_to_yaml(url, output_file=None, target_game=None):
    """Backward-compatible wrapper for older callers."""
    return parse_iesdp_tables_to_yaml(url, output_file, target_game=target_game)
