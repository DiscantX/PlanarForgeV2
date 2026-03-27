import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.resource import Resource
from drivers.InfinityEngine.io.table_resolver import (
    TableResolver,
    decode_ie_text_resource,
    _IE_TEXT_XOR_KEY,
)
from drivers.InfinityEngine.resource_loader import ResourceLoader


class FakeTextLoader:
    def __init__(self, texts):
        self.texts = {
            (game, resref.upper(), restype.upper()): value
            for (game, resref, restype), value in texts.items()
        }

    def get_text_resource(self, resref, restype, game=None):
        return self.texts.get((game, str(resref).upper(), str(restype).upper()))


class TestTableResolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = ResourceLoader()

    def test_decode_ie_text_resource_decrypts_xor_payload(self):
        plaintext = b"IDS V1.0\r\n0 TEST\r\n"
        encrypted = bytes(
            byte ^ _IE_TEXT_XOR_KEY[index % len(_IE_TEXT_XOR_KEY)]
            for index, byte in enumerate(plaintext)
        )

        self.assertEqual(
            decode_ie_text_resource(b"\xff\xff" + encrypted),
            plaintext.decode("latin-1"),
        )

    def test_table_resolver_parses_ids_and_2da_tables(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("BG2EE", "EA", "IDS"): "IDS V1.0\n4 ALLY\n",
                    ("BG2EE", "SAMPLE", "2DA"): (
                        "2DA V1.0\n"
                        "DEFAULT\n"
                        "        NAME VALUE\n"
                        "0       ALPHA 1\n"
                        "1\n"
                        "2       GAMMA 3\n"
                    ),
                }
            )
        )

        self.assertEqual(
            resolver.resolve(4, {"kind": "ids", "file": "EA.IDS"}, game="BG2EE"),
            "ALLY",
        )
        self.assertEqual(
            resolver.resolve(
                1,
                {"kind": "2da", "file": "SAMPLE.2DA", "column": "NAME", "row_mode": "label"},
                game="BG2EE",
            ),
            "DEFAULT",
        )
        self.assertEqual(
            resolver.resolve(
                2,
                {"kind": "2da", "file": "SAMPLE.2DA", "column": "VALUE", "row_mode": "index"},
                game="BG2EE",
            ),
            "3",
        )

    def test_table_resolver_supports_game_specific_table_files(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("IWD2", "SCHOOL", "2DA"): (
                        "2DA V1.0\n"
                        "4294967296\n"
                        "        RES_REF\n"
                        "NONE    0\n"
                        "ABJURER 1\n"
                    ),
                }
            )
        )

        self.assertEqual(
            resolver.resolve(
                1,
                {
                    "kind": "2da",
                    "file": "MSCHOOL.2DA",
                    "file_by_game": {"IWD2": "SCHOOL.2DA"},
                    "column": "_row_label",
                    "row_mode": "index",
                },
                game="IWD2",
            ),
            "ABJURER",
        )

    def test_schema_lookup_serializes_ids_backed_cre_fields(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("BG2EE", "ANIMATE", "IDS"): "IDS V1.0\n0x0100 CHUNKS\n",
                    ("BG2EE", "EA", "IDS"): "10\n0 ANYONE\n4 ALLY\n",
                    ("BG2EE", "GENERAL", "IDS"): "30\n4 UNDEAD\n",
                    ("BG2EE", "RACE", "IDS"): "IDS V1.0\n1 HUMAN\n",
                    ("BG2EE", "CLASS", "IDS"): "IDS V1.0\n2 FIGHTER\n",
                    ("BG2EE", "GENDER", "IDS"): "1 MALE\n2 FEMALE\n",
                    ("BG2EE", "ALIGN", "IDS"): "15\n0x21 NEUTRAL_GOOD\n",
                    ("BG2EE", "SLOTS", "IDS"): "IDS V1.0\n35 SLOT_WEAPON0\n36 SLOT_WEAPON1\n1000 FIST\n",
                }
            )
        )

        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        resource = Resource(cre_schema, name="TEST")
        resource.game = "BG2EE"
        resource.table_resolver = resolver
        resource.set_section(
            "header",
            {
                "animation_id": 0x0100,
                "enemy_ally": 4,
                "general": 4,
                "race": 1,
                "class": 2,
                "gender": 2,
                "alignment": 0x21,
            },
        )
        resource.set_section(
            "item_slots",
            [
                {
                    "selected_weapon": 0,
                    "selected_weapon_ability": 0,
                }
            ],
        )

        data = resource.to_dict()
        self.assertEqual(data["header"]["animation_id"], "CHUNKS")
        self.assertEqual(data["header"]["enemy_ally"], "ALLY")
        self.assertEqual(data["header"]["general"], "UNDEAD")
        self.assertEqual(data["header"]["race"], "HUMAN")
        self.assertEqual(data["header"]["class"], "FIGHTER")
        self.assertEqual(data["header"]["gender"], "FEMALE")
        self.assertEqual(data["header"]["alignment"], "NEUTRAL_GOOD")
        self.assertEqual(data["item_slots"][0]["selected_weapon"], "SLOT_WEAPON0")

    def test_schema_lookup_skip_values_preserves_negative_one(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("BG2EE", "SLOTS", "IDS"): "IDS V1.0\n35 SLOT_WEAPON0\n",
                }
            )
        )

        cre_schema = self.loader.schema_loader.get("CRE", game="BG2EE")
        resource = Resource(cre_schema, name="TEST")
        resource.game = "BG2EE"
        resource.table_resolver = resolver
        resource.set_section(
            "item_slots",
            [
                {
                    "selected_weapon": -1,
                    "selected_weapon_ability": 0,
                }
            ],
        )

        self.assertEqual(resource.to_dict()["item_slots"][0]["selected_weapon"], -1)

    def test_itm_schema_lookup_serializes_ids_and_2da_fields(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("BG2EE", "WPROF", "IDS"): "IDS V1.0\n89 PROFICIENCYBASTARDSWORD\n",
                    ("BG2EE", "ITEMCAT", "IDS"): "IDS V1.0\n1 BOW\n",
                    ("BG2EE", "MISSILE", "IDS"): "IDS V1.0\n68 Magic_Missiles_1\n",
                    ("BG2EE", "MSCHOOL", "2DA"): (
                        "2DA V1.0\n"
                        "4294967296\n"
                        "        RES_REF\n"
                        "None    4294967296\n"
                        "ABJURER 1\n"
                        "CONJURER 2\n"
                    ),
                    ("BG2EE", "MSECTYPE", "2DA"): (
                        "2DA V1.0\n"
                        "4294967296\n"
                        "        RES_REF\n"
                        "None    4294967296\n"
                        "SpellProtections 1\n"
                        "SpecificProtections 2\n"
                    ),
                }
            )
        )

        itm_schema = self.loader.schema_loader.get("ITM", game="BG2EE")
        resource = Resource(itm_schema, name="TEST")
        resource.game = "BG2EE"
        resource.table_resolver = resolver
        resource.set_section(
            "header",
            {
                "weapon_proficiency": 89,
            },
        )
        resource.set_section(
            "extended_header",
            [
                {
                    "primary_type": 1,
                    "secondary_type": 2,
                    "projectile_animation": 68,
                }
            ],
        )

        data = resource.to_dict()
        self.assertEqual(data["header"]["weapon_proficiency"], "PROFICIENCYBASTARDSWORD")
        self.assertEqual(data["extended_header"][0]["primary_type"], "ABJURER")
        self.assertEqual(data["extended_header"][0]["secondary_type"], "SpecificProtections")
        self.assertEqual(data["extended_header"][0]["projectile_animation"], "Magic_Missiles_1")

    def test_spl_schema_lookup_serializes_ids_and_2da_fields(self):
        resolver = TableResolver(
            FakeTextLoader(
                {
                    ("BG2EE", "MISSILE", "IDS"): "IDS V1.0\n68 Magic_Missiles_1\n",
                    ("BG2EE", "MSCHOOL", "2DA"): (
                        "2DA V1.0\n"
                        "4294967296\n"
                        "        RES_REF\n"
                        "None    4294967296\n"
                        "ABJURER 1\n"
                        "CONJURER 2\n"
                        "DIVINER 3\n"
                        "ENCHANTER 4\n"
                        "ILLUSIONIST 5\n"
                        "INVOKER 6\n"
                    ),
                    ("BG2EE", "MSECTYPE", "2DA"): (
                        "2DA V1.0\n"
                        "4294967296\n"
                        "        RES_REF\n"
                        "None    4294967296\n"
                        "SpellProtections 1\n"
                        "SpecificProtections 2\n"
                        "IllusionaryProtections 3\n"
                        "MagicAttack 4\n"
                        "DivinationAttack 5\n"
                        "Conjuration 6\n"
                        "CombatProtections 7\n"
                        "Contingency 8\n"
                        "Battleground 9\n"
                        "OffensiveDamage 10\n"
                    ),
                }
            )
        )

        spl_schema = self.loader.schema_loader.get("SPL", game="BG2EE")
        resource = Resource(spl_schema, name="TEST")
        resource.game = "BG2EE"
        resource.table_resolver = resolver
        resource.set_section(
            "header",
            {
                "primary_type": 6,
                "secondary_type": 10,
            },
        )
        resource.set_section(
            "extended_header",
            [
                {
                    "projectile": 68,
                }
            ],
        )

        data = resource.to_dict()
        self.assertEqual(data["header"]["primary_type"], "INVOKER")
        self.assertEqual(data["header"]["secondary_type"], "OffensiveDamage")
        self.assertEqual(data["extended_header"][0]["projectile"], "Magic_Missiles_1")
