import unittest
import io
import hashlib
import sys
import os
import random
from contextlib import redirect_stdout

# Ensure core modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.game.resource_loader import ResourceLoader
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from core.binary.writer import BinaryWriter
from core.binary.parser import BinaryParser
from core.game.resource_types import RESOURCE_TYPE_MAP

class TestPlanarForge(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        print("--- Setting up PlanarForge Test Suite ---")
        
        # Initialize the ecosystem
        cls.schema_loader = SchemaLoader("schemas")
        cls.schema_loader.load_all()
        cls.schema_loader.resolve_types(FieldTypes)
        cls.loader = ResourceLoader(schema_loader=cls.schema_loader)
        
        # Locate a game to test against
        cls.game = cls.loader.default_game
        
        # If the default game isn't found, try to auto-discover any installed IE game
        if cls.game not in cls.loader.resource_maps:
             known_games = ["BG2EE", "BGEE", "IWDEE", "PSTEE", "BG2", "BG1", "IWD"]
             for g in known_games:
                 if cls.loader._get_install_path(g):
                     print(f"Default game not found, switching to discovered: {g}")
                     cls.loader._load_chitin(g)
                     if g in cls.loader.resource_maps:
                         cls.game = g
                         break
        
        if cls.game not in cls.loader.resource_maps:
            print("WARNING: No game installation found. Integration tests will be skipped.")
            cls.skip_all = True
        else:
            cls.skip_all = False
            print(f"Running tests against: {cls.game}")

    def test_01_biff_structure(self):
        """
        Test reading of BIF files themselves using the BIFF schema.
        Verifies that headers and file entry tables can be parsed.
        """
        if self.skip_all:
            self.skipTest("No game installation found")
            
        biff_schema = self.schema_loader.get("BIFF") or self.schema_loader.get("biff")
        if not biff_schema:
            self.fail("BIFF schema is missing from schemas/ directory.")

        chitin = self.loader.chitins.get(self.game)
        bif_entries = chitin.sections.get("bif_entries", [])
        
        # Test a subset of BIFs to ensure the parser handles the container format correctly
        # We look for standard data biffs usually found in 'data/'
        samples = [b for b in bif_entries if "data" in b.get("filename", "").lower()]
        if not samples:
            samples = bif_entries[:3] # Fallback to first 3
        else:
            samples = samples[:3]

        for entry in samples:
            filename = entry.get("filename")
            install_path = self.loader._get_install_path(self.game)
            file_path = os.path.join(install_path, filename)
            
            # Fix path separators for mixed environments
            file_path = str(file_path).replace("\\", "/")

            if not os.path.exists(file_path):
                print(f"Skipping BIF test for {filename} (File not found)")
                continue

            print(f"Testing BIF Parser on: {filename}")
            
            try:
                # Force load using the BIFF schema
                resource = self.loader.load_file(
                    resref=filename, 
                    file_path=file_path, 
                    schema=biff_schema
                )
                
                self.assertIsNotNone(resource, f"Parser returned None for {filename}")
                self.assertIn("header", resource.sections)
                self.assertIn("file_entries", resource.sections)
                
                # logic check: entry count in header should match actual list size
                header = resource.sections["header"][0]
                expected_count = header.get("file_entries", 0)
                actual_count = len(resource.sections["file_entries"])
                
                self.assertEqual(expected_count, actual_count, 
                    f"BIF Header claims {expected_count} files, found {actual_count} in {filename}")

            except Exception as e:
                self.fail(f"Failed to parse BIF file {filename}: {e}")

    def test_02_resource_fidelity_roundtrip(self):
        """
        Test round-trip fidelity for every resource in CHITIN.KEY that has a corresponding schema.
        """
        if self.skip_all:
            self.skipTest("No game installation found")

        # Get all resource entries from the loaded CHITIN.KEY
        chitin = self.loader.chitins.get(self.game)
        if not chitin:
            self.fail(f"CHITIN.KEY for {self.game} not loaded.")
        
        all_resource_entries = chitin.sections.get("resource_entries", [])

        # Group resources by their schema name (e.g., 'ITM', 'SPL')
        resources_by_schema = {}
        for entry in all_resource_entries:
            res_type_code = entry.get("resource_type")
            res_name = entry.get("resource_name")
            
            # Use the resource type map to find the schema name
            schema_name = RESOURCE_TYPE_MAP.get(res_type_code)

            if schema_name and res_name:
                if schema_name not in resources_by_schema:
                    resources_by_schema[schema_name] = []
                resources_by_schema[schema_name].append(res_name.strip())

        tested_count = 0
        total_failures = []
        
        # Iterate through each schema we have loaded
        for schema_name, schema in self.schema_loader.schemas.items():
            # We only care about schemas that represent game resources (not container formats like BIFF)
            if schema_name not in resources_by_schema:
                continue

            print(f"\n--- Testing fidelity for schema: {schema_name} ---")
            
            resrefs_to_test = resources_by_schema[schema_name]
            failures = []
            
            for resref in resrefs_to_test:
                # We capture stdout to prevent "No schema found" spam
                f = io.StringIO()
                with redirect_stdout(f):
                    try:
                        # 1. Attempt Load
                        resource = self.loader.load(resref, restype=schema_name, game=self.game)
                    except Exception as e:
                        failures.append(f"CRASH loading {resref}: {e}")
                        continue

                if resource is None:
                    continue

                # 2. Get Original Data
                try:
                    original_bytes, _, _ = self.loader.get_raw_bytes(resref, game=self.game)
                    if not original_bytes:
                        continue
                except Exception as e:
                    failures.append(f"Error reading raw bytes for {resref}: {e}")
                    continue

                # 3. Save to Memory (Simulate File Write)
                try:
                    output = io.BytesIO()
                    writer = BinaryWriter(output)
                    parser = BinaryParser(resource.schema)
                    parser.write(writer, resource)
                    saved_bytes = output.getvalue()
                except Exception as e:
                    failures.append(f"Error writing {resref}: {e}")
                    continue

                # 4. Compare
                orig_hash = hashlib.md5(original_bytes).hexdigest()
                saved_hash = hashlib.md5(saved_bytes).hexdigest()

                if orig_hash != saved_hash:
                    version = resource.get("version")
                    
                    limit = min(len(original_bytes), len(saved_bytes))
                    diff_idx = next((i for i in range(limit) if original_bytes[i] != saved_bytes[i]), limit)
                    
                    fail_msg = (
                        f"Fidelity mismatch: {resref} [{schema_name}] (File Ver: {version})\n"
                        f"  Sizes: Orig={len(original_bytes)}, Saved={len(saved_bytes)}\n"
                        f"  First mismatch at offset {hex(diff_idx)}"
                    )
                    failures.append(fail_msg)
                
                tested_count += 1
            
            if failures:
                total_failures.extend(failures)
                print(f"Found {len(failures)} failures for {schema_name}:")
                for fail in failures:
                    print(f" - {fail}")

        print(f"\n--- Fidelity Test Suite Finished ---")
        print(f"Total resources tested: {tested_count}")
        
        if total_failures:
            self.fail(f"Round-trip fidelity failed for {len(total_failures)} resources across all schemas.")

if __name__ == "__main__":
    unittest.main()
