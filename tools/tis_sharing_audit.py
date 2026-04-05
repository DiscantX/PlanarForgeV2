#!/usr/bin/env python3
"""
tis_sharing_audit.py

A one-use script to identify TIS (Tileset) files that are shared by multiple 
ARE (Area) resources across all detected Infinity Engine installations.
"""

import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path to ensure internal imports work
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from drivers.InfinityEngine.resource_loader import ResourceLoader

def _get_clean_resref(resource, field_names, debug_label=None):
    """
    Attempts to retrieve and clean a ResRef from a list of possible field names.
    Returns the cleaned uppercase string or None if no field is found.
    """
    for name in field_names:
        val = resource.get(name)
        if val:
            cleaned = str(val).split('\x00', 1)[0].strip().upper()
            if cleaned:
                return cleaned
    
    # Diagnostic: If lookup fails, show available keys to help identify schema mismatches
    if debug_label:
        all_keys = []
        # Scan sections to find available keys
        for sec_data in resource.sections.values():
            if isinstance(sec_data, dict):
                all_keys.extend(sec_data.keys())
            elif isinstance(sec_data, list) and len(sec_data) > 0:
                all_keys.extend(sec_data[0].keys())
        
        keys_str = ", ".join(sorted(set(all_keys))[:20])
        print(f"  [Debug] {debug_label}: Keys found: {keys_str}...")

    return None

def run_audit():
    print("Starting TIS Sharing Audit...")

    loader = ResourceLoader()
    # Structure: tis_map[game_id][tis_resref] = [are_resref1, are_resref2, ...]
    tis_map = defaultdict(lambda: defaultdict(list))
    stats = defaultdict(lambda: {"ares": 0, "weds": 0, "errors": 0})

    found_games = loader.install_finder.find_all()
    if not found_games:
        print("Error: No Infinity Engine game installations detected.")
        return

    for game_info in found_games:
        game_id = game_info.game_id
        print(f"Scanning {game_id} for Area resources...")
        
        # Use iter_resources to avoid loading every single file index manually
        for resref, restype, _ in loader.iter_resources(game=game_id):
            if restype != 'ARE':
                continue
            
            stats[game_id]["ares"] += 1
            # Use split/strip to clean the iteration's resref
            resref_clean = str(resref).split('\x00', 1)[0].strip().upper()

            try:
                # 1. Load the Area to find its associated WED file
                are_res = loader.load(resref_clean, restype='ARE', game=game_id)
                if not are_res:
                    continue
                
                # Check common names for the WED reference in ARE files
                wed_resref = _get_clean_resref(are_res, ['area_wed', 'wed_file', 'wed_name', 'wed_resource', 'wed', 'parent_wed'], debug_label=resref_clean)
                if not wed_resref:
                    continue

                # 2. Load the WED to find the Tileset (TIS) reference
                wed_res = loader.load(wed_resref, restype='WED', game=game_id)
                if not wed_res:
                    # Missing WED schema or file
                    continue
                
                stats[game_id]["weds"] += 1

                # Based on WED schemas, the TIS name is usually in the overlays
                tis_name = _get_clean_resref(wed_res, ['tileset_name', 'tileset', 'tis_file'])
                
                if tis_name:
                    if resref_clean not in tis_map[game_id][tis_name]:
                        tis_map[game_id][tis_name].append(resref_clean)
                else:
                    # Optional: uncomment to debug schema naming issues
                    print(f"  [Debug] {wed_resref}: No TIS reference found in WED.")
                    pass
            
            except Exception as e:
                # print(f"  [Error] Failed to process {resref_clean}: {e}")
                stats[game_id]["errors"] += 1
                continue

    # Final Report
    print("\n" + "="*60)
    print(f"{'GAME':<12} | {'SHARED TIS':<12} | {'USED BY AREAS'}")
    print("-"*60)
    
    found_any = False
    for game_id, mapping in tis_map.items():
        for tis, areas in mapping.items():
            if len(areas) > 1:
                found_any = True
                area_list = ", ".join(areas)
                print(f"{game_id:<12} | {tis:<12} | {area_list}")
    
    if not found_any:
        print("No shared Tilesets (TIS) were found across the scanned areas.")

    print("="*60)
    print("Execution Summary:")
    for game_id, s in stats.items():
        unique_tis = len(tis_map[game_id])
        print(f"  - {game_id}: Scanned {s['ares']} Areas, {s['weds']} WEDs. Found {unique_tis} unique TIS files. ({s['errors']} errors)")
    
    print("Audit complete.")

if __name__ == "__main__":
    run_audit()