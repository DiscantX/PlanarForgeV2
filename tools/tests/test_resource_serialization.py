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

        self.assertEqual(data["header"][0]["inventory_icon"], "II083")
        self.assertEqual(
            data["extended_header"][0]["melee_animation"],
            {
                "overhand": 34,
                "backhand": 33,
                "thrust": 33,
            },
        )
        self.assertIsNone(data["feature_block"][0]["resource"])
        self.assertIsNone(data["feature_block"][1]["resource"])


if __name__ == "__main__":
    unittest.main()
