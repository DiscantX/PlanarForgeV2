import sys
import unittest
import io
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.binary.reader import BinaryReader
from core.binary.writer import BinaryWriter
from core.resource import Resource
from drivers.InfinityEngine.definitions.types import ResRefString
from drivers.InfinityEngine.resource_loader import ResourceLoader


class TestResourceSerialization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]
        cls.sample_path = cls.project_root / "FEMUR.saved.itm"
        cls.loader = ResourceLoader()
        cls.resource = cls.loader.load_file(
            resref="FEMUR",
            restype="ITM",
            file_path=cls.sample_path,
        )

    def test_resref_string_repr_uses_display_value(self):
        value = ResRefString("II083\x00\x00")

        self.assertEqual(str(value), "II083")
        self.assertEqual(repr(value), "'II083'")

    def test_to_dict_formats_resrefs_and_bytes_for_display(self):
        data = self.resource.to_dict()

        self.assertEqual(data["header"][0]["item_type"], "Maces (in BG, this includes clubs)")
        self.assertEqual(data["header"][0]["inventory_icon"], "II083")
        self.assertIsInstance(data["header"][0]["identified_name"], str)
        self.assertIsInstance(data["header"][0]["unidentified_name"], str)
        self.assertRegex(data["header"][0]["identified_name"], r"^\(\d+\)")
        self.assertRegex(data["header"][0]["unidentified_name"], r"^\(\d+\)")
        self.assertIsInstance(data["header"][0]["usability_bitmask"], dict)
        self.assertEqual(
            data["extended_header"][0]["melee_animation"],
            {
                "overhand": 34,
                "backhand": 33,
                "thrust": 33,
            },
        )
        self.assertEqual(data["extended_header"][0]["damage_type"], "Crushing")
        self.assertEqual(data["feature_block"][0]["target_type"], "Self")
        self.assertEqual(data["feature_block"][0]["timing_mode"], "Instant/While equipped")
        self.assertEqual(data["feature_block"][0]["dispel_resistance"], "Natural/Nonmagical")
        self.assertIsInstance(data["feature_block"][0]["saving_throw_type"], dict)
        self.assertIsNone(data["feature_block"][0]["resource"])
        self.assertIsNone(data["feature_block"][1]["resource"])

    def test_classic_and_ee_schemas_expose_different_effect_flags(self):
        classic_itm = self.loader.schema_loader.get("ITM", game="BG2")
        ee_itm = self.loader.schema_loader.get("ITM", game="BG2EE")

        classic_flags = classic_itm.get_section("feature_block").get_field("saving_throw_type").attributes["flags"]
        ee_flags = ee_itm.get_section("feature_block").get_field("saving_throw_type").attributes["flags"]

        self.assertNotIn(0x00000020, classic_flags)
        self.assertIn(0x00000020, ee_flags)
        self.assertEqual(ee_flags[0x00000020], "alternate_spells")

    def test_pst_and_pstee_itm_schemas_keep_pst_header_flags_but_split_effect_flags(self):
        pst_itm = self.loader.schema_loader.get("ITM", game="PST")
        pstee_itm = self.loader.schema_loader.get("ITM", game="PSTEE")

        pst_header_flags = pst_itm.get_section("header").get_field("flags").attributes["flags"]
        pstee_header_flags = pstee_itm.get_section("header").get_field("flags").attributes["flags"]
        pst_effect_flags = pst_itm.get_section("feature_block").get_field("saving_throw_type").attributes["flags"]
        pstee_effect_flags = pstee_itm.get_section("feature_block").get_field("saving_throw_type").attributes["flags"]

        self.assertEqual(pst_header_flags[0x00000400], "steel")
        self.assertEqual(pst_header_flags[0x00000800], "conversable")
        self.assertEqual(pst_header_flags[0x00001000], "pulsating")
        self.assertEqual(pstee_header_flags[0x00000400], "steel")
        self.assertEqual(pstee_header_flags[0x00000800], "conversable")
        self.assertEqual(pstee_header_flags[0x00001000], "pulsating")
        self.assertNotIn(0x00000200, pst_itm.get_section("extended_header").get_field("flags").attributes["flags"])
        self.assertNotIn(0x00000200, pstee_itm.get_section("extended_header").get_field("flags").attributes["flags"])
        self.assertNotIn(0x00000020, pst_effect_flags)
        self.assertEqual(pstee_effect_flags[0x00000020], "alternate_spells")

    def test_cre_character_strrefs_uses_structured_strref_arrays(self):
        ee_cre = self.loader.schema_loader.get("CRE", game="BG2EE")
        iwd2_cre = self.loader.schema_loader.get("CRE", game="IWD2")

        ee_field = ee_cre.get_section("header").get_field("character_strrefs")
        iwd2_field = iwd2_cre.get_section("header").get_field("character_strrefs")

        self.assertEqual(ee_field.type_name, "strref_array")
        self.assertEqual(ee_field.attributes["count"], 100)
        self.assertEqual(iwd2_field.type_name, "strref_array")
        self.assertEqual(iwd2_field.attributes["count"], 64)

    def test_strref_array_serializes_sparse_slots(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("header").get_field("character_strrefs")

        entries = [0xFFFFFFFF] * field.attributes["count"]
        entries[9] = 60296
        entries[10] = 60297
        entries[20] = 0
        entries[26] = 60295
        raw = b"".join(entry.to_bytes(4, byteorder="little", signed=False) for entry in entries)

        parsed = field.type.read(BinaryReader(io.BytesIO(raw)), field)
        resource = Resource(cre_schema, name="TEST")
        resource.set_section("header", {"character_strrefs": parsed})

        self.assertEqual(
            resource.to_dict()["header"]["character_strrefs"],
            {
                "slot_9": 60296,
                "slot_10": 60297,
                "slot_26": 60295,
            },
        )

    def test_strref_array_write_preserves_raw_entries(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("header").get_field("character_strrefs")

        entries = [0xFFFFFFFF] * field.attributes["count"]
        entries[2] = 0
        entries[9] = 60296
        entries[10] = 60297
        entries[26] = 60295
        raw = b"".join(entry.to_bytes(4, byteorder="little", signed=False) for entry in entries)

        output = io.BytesIO()
        field.type.write(BinaryWriter(output), entries, field)

        self.assertEqual(output.getvalue(), raw)

    def test_strref_fields_serialize_text_with_resource_resolver(self):
        itm_schema = self.loader.schema_loader.get("ITM", game="BG2EE")
        resource = Resource(itm_schema, name="TEST")
        resource.strref_resolver = lambda strref: f"text:{strref}"
        resource.set_section(
            "header",
            {
                "identified_name": 123,
                "unidentified_name": 456,
            },
        )

        self.assertEqual(
            resource.to_dict()["header"],
            {
                "identified_name": "(123) text:123",
                "unidentified_name": "(456) text:456",
            },
        )

    def test_strref_array_serializes_text_with_resource_resolver(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("header").get_field("character_strrefs")

        entries = [0xFFFFFFFF] * field.attributes["count"]
        entries[9] = 60296
        entries[10] = 60297
        raw = b"".join(entry.to_bytes(4, byteorder="little", signed=False) for entry in entries)

        parsed = field.type.read(BinaryReader(io.BytesIO(raw)), field)
        resource = Resource(cre_schema, name="TEST")
        resource.strref_resolver = lambda strref: f"text:{strref}"
        resource.set_section("header", {"character_strrefs": parsed})

        self.assertEqual(
            resource.to_dict()["header"]["character_strrefs"],
            {
                "slot_9": "(60296) text:60296",
                "slot_10": "(60297) text:60297",
            },
        )

    def test_cre_item_slots_use_structured_word_arrays(self):
        ee_cre = self.loader.schema_loader.get("CRE", game="BG2EE")
        iwd2_cre = self.loader.schema_loader.get("CRE", game="IWD2")

        ee_field = ee_cre.get_section("item_slots").get_field("equipped_slots")
        iwd2_field = iwd2_cre.get_section("item_slots").get_field("equipped_slots")
        ee_selected_weapon = ee_cre.get_section("item_slots").get_field("selected_weapon")
        ee_selected_ability = ee_cre.get_section("item_slots").get_field("selected_weapon_ability")
        iwd2_selected_weapon = iwd2_cre.get_section("item_slots").get_field("selected_weapon")

        self.assertEqual(ee_field.type_name, "word_array")
        self.assertEqual(ee_field.attributes["count"], 38)
        self.assertEqual(ee_selected_weapon.type_name, "sword")
        self.assertEqual(ee_selected_ability.type_name, "sword")
        self.assertEqual(iwd2_field.type_name, "word_array")
        self.assertEqual(iwd2_field.attributes["count"], 50)
        self.assertEqual(iwd2_selected_weapon.type_name, "sdword")

    def test_word_array_serializes_item_slots_with_resrefs(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("item_slots").get_field("equipped_slots")

        entries = [0xFFFF] * field.attributes["count"]
        entries[0] = 1
        entries[4] = 0
        entries[5] = 5
        entries[6] = 6
        entries[9] = 4
        entries[21] = 3
        entries[22] = 2
        raw = b"".join(entry.to_bytes(2, byteorder="little", signed=False) for entry in entries)

        parsed = field.type.read(BinaryReader(io.BytesIO(raw)), field)
        resource = Resource(cre_schema, name="TEST")
        resource.set_section(
            "items",
            [
                {"itm_file": "ring95"},
                {"itm_file": "helmnoan"},
                {"itm_file": "clck28"},
                {"itm_file": "dagg18"},
                {"itm_file": "VAMP"},
                {"itm_file": "IMMUNE2"},
                {"itm_file": "minhp1"},
            ],
        )
        resource.set_section(
            "item_slots",
            [
                {
                    "equipped_slots": parsed,
                    "selected_weapon": 0,
                    "selected_weapon_ability": 0,
                }
            ],
        )

        self.assertEqual(
            resource.to_dict()["item_slots"][0]["equipped_slots"],
            {
                "helmet": "helmnoan",
                "armor": None,
                "shield": None,
                "gloves": None,
                "left_ring": "ring95",
                "right_ring": "IMMUNE2",
                "amulet": "minhp1",
                "belt": None,
                "boots": None,
                "weapon_1": "VAMP",
                "weapon_2": None,
                "weapon_3": None,
                "weapon_4": None,
                "quiver_1": None,
                "quiver_2": None,
                "quiver_3": None,
                "quiver_4": None,
                "cloak": None,
                "quick_item_1": None,
                "quick_item_2": None,
                "quick_item_3": None,
                "inventory_item_1": "dagg18",
                "inventory_item_2": "clck28",
                "inventory_item_3": None,
                "inventory_item_4": None,
                "inventory_item_5": None,
                "inventory_item_6": None,
                "inventory_item_7": None,
                "inventory_item_8": None,
                "inventory_item_9": None,
                "inventory_item_10": None,
                "inventory_item_11": None,
                "inventory_item_12": None,
                "inventory_item_13": None,
                "inventory_item_14": None,
                "inventory_item_15": None,
                "inventory_item_16": None,
                "magic_weapon": None,
            },
        )
        self.assertEqual(resource.to_dict()["item_slots"][0]["selected_weapon"], 0)
        self.assertEqual(resource.to_dict()["item_slots"][0]["selected_weapon_ability"], 0)

    def test_word_array_write_preserves_raw_item_slots(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("item_slots").get_field("equipped_slots")

        entries = [0xFFFF] * field.attributes["count"]
        entries[0] = 1
        entries[4] = 0
        entries[5] = 5
        entries[6] = 6
        entries[9] = 4
        entries[21] = 3
        entries[22] = 2
        raw = b"".join(entry.to_bytes(2, byteorder="little", signed=False) for entry in entries)

        output = io.BytesIO()
        field.type.write(BinaryWriter(output), entries, field)

        self.assertEqual(output.getvalue(), raw)

    def test_cre_object_id_references_use_structured_byte_arrays(self):
        ee_cre = self.loader.schema_loader.get("CRE", game="BG2EE")
        pst_cre = self.loader.schema_loader.get("CRE", game="PST")

        ee_field = ee_cre.get_section("header").get_field("references")
        pst_field = pst_cre.get_section("header").get_field("object_ids_references")

        self.assertEqual(ee_field.type_name, "byte_array")
        self.assertEqual(pst_field.type_name, "byte_array")

    def test_byte_array_serializes_object_references(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        field = cre_schema.get_section("header").get_field("references")

        raw = bytes([0, 5, 0, 0, 0])
        parsed = field.type.read(BinaryReader(io.BytesIO(raw)), field)
        resource = Resource(cre_schema, name="TEST")
        resource.set_section("header", {"references": parsed})

        self.assertEqual(
            resource.to_dict()["header"]["references"],
            {
                "reference_1": "Nothing",
                "reference_2": 5,
                "reference_3": "Nothing",
                "reference_4": "Nothing",
                "reference_5": "Nothing",
            },
        )

    def test_signed_integer_io_round_trips_negative_values(self):
        output = io.BytesIO()
        writer = BinaryWriter(output)
        writer.write_int16(-1)
        writer.write_int32(-1)
        writer.write_int16(-2)

        output.seek(0)
        reader = BinaryReader(output)
        self.assertEqual(reader.read_int16(), -1)
        self.assertEqual(reader.read_int32(), -1)
        self.assertEqual(reader.read_int16(), -2)

    def test_cre_signed_fields_display_negative_one(self):
        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        resource = Resource(cre_schema, name="TEST")
        equipped_slots_count = cre_schema.get_section("item_slots").get_field("equipped_slots").attributes["count"]

        resource.set_section(
            "header",
            {
                "armor_class": -1,
                "armor_class_2": -2,
                "global_actor_enumeration_value": 65535,
                "local_actor_enumeration_value": 65535,
            },
        )
        resource.set_section(
            "item_slots",
            [
                {
                    "equipped_slots": [0xFFFF] * equipped_slots_count,
                    "selected_weapon": -1,
                    "selected_weapon_ability": -1,
                }
            ],
        )

        data = resource.to_dict()
        self.assertEqual(data["header"]["armor_class"], -1)
        self.assertEqual(data["header"]["armor_class_2"], -2)
        self.assertEqual(data["header"]["global_actor_enumeration_value"], -1)
        self.assertEqual(data["header"]["local_actor_enumeration_value"], -1)
        self.assertEqual(data["item_slots"][0]["selected_weapon"], -1)
        self.assertEqual(data["item_slots"][0]["selected_weapon_ability"], -1)


if __name__ == "__main__":
    unittest.main()
