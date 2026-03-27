import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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


if __name__ == "__main__":
    unittest.main()
