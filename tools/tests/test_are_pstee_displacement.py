"""Synthetic fixtures for PST/PSTEE ARE section displacement (issue #68).

In PSTEE areas the header pointers for song entries, rest interruptions,
automap notes and projectile traps are short by the size of the animations
block: the real position is the header value plus 76 * count_of_animations.
These tests need no installed game.
"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.binary.parser import BinaryParser
from core.binary.reader import BinaryReader
from core.binary.writer import BinaryWriter
from core.resource import Resource
from core.schema_loader import SchemaLoader
from core.field_types import FieldTypes
from drivers.InfinityEngine.definitions import types  # noqa: F401  (registers field types)

SCHEMA_DIR = (Path(__file__).resolve().parents[2]
              / "drivers" / "InfinityEngine" / "definitions" / "schemas")


def _entry_size(section):
    return sum(f.attributes.get("size", 0) for f in section.fields)


class TestPsteeAreDisplacement(unittest.TestCase):
    N_ANIM = 2
    DISPLACED = ("song_entries", "rest_interruptions", "automap_notes")

    @classmethod
    def setUpClass(cls):
        loader = SchemaLoader(SCHEMA_DIR)
        loader.load_all()
        loader.resolve_types(FieldTypes)
        cls.schema = loader.get("ARE", game="PSTEE")

    def _put(self, buf, base, section, name, value):
        field = section.get_field(name)
        off, size = field.attributes["offset"], field.attributes["size"]
        buf[base + off: base + off + size] = value.to_bytes(size, "little")

    def _build(self):
        """Header + animations + song + rest + one automap note, as in AR1001."""
        s = self.schema
        hdr = s.get_section("header")
        hdr_size = _entry_size(hdr)
        sizes = {n: _entry_size(s.get_section(n))
                 for n in ("animations",) + self.DISPLACED}
        anim_block = self.N_ANIM * sizes["animations"]

        real = {"animations": hdr_size}
        cursor = hdr_size + anim_block
        counts = {"automap_notes": 1}
        for name in self.DISPLACED:
            real[name] = cursor
            cursor += sizes[name] * counts.get(name, 1)
        buf = bytearray(cursor)
        buf[0:8] = b"AREAV1.0"

        def h(name, value):
            self._put(buf, 0, hdr, name, value)

        h("count_of_animations", self.N_ANIM)
        h("offset_to_animations", real["animations"])
        # Real files point every empty section somewhere harmless.
        for f in hdr.fields:
            if f.name.startswith("offset_to_") and not buf[f.attributes["offset"]:f.attributes["offset"] + 4].strip(b"\0"):
                h(f.name, real["animations"])
        # Displaced pointers omit the animations block, as the game files do.
        for name in self.DISPLACED:
            h(f"offset_to_{name}", real[name] - anim_block)
        h("count_of_automap_notes", 1)

        # Markers: day song = 24 / night song = 25 at the real song position.
        song = s.get_section("song_entries")
        self._put(buf, real["song_entries"], song, "day_song_reference_number", 24)
        self._put(buf, real["song_entries"], song, "night_song_reference_number", 25)
        # Animation entries carry bytes that would be garbage if read as songs.
        anim = s.get_section("animations")
        for i in range(self.N_ANIM):
            self._put(buf, real["animations"] + i * sizes["animations"],
                      anim, "x_coordinate", 0x7000 + i)
        return bytes(buf), real, sizes, anim_block

    def _read(self, data):
        parser = BinaryParser(self.schema, resource_class=Resource)
        res = parser.read(BinaryReader(io.BytesIO(data)), name="SYNTH")
        res._original_bytes = data
        return parser, res

    def test_schema_marks_displaced_sections(self):
        for name in self.DISPLACED + ("projectile_traps",):
            self.assertEqual(self.schema.get_section(name).offset_displacement,
                             {"section": "animations"}, name)
        self.assertIsNone(self.schema.get_section("animations").offset_displacement)

    def test_sections_are_located_after_the_animations(self):
        data, *_ = self._build()
        _, res = self._read(data)
        self.assertEqual(len(res.sections["animations"]), self.N_ANIM)
        song = res.sections["song_entries"][0]
        self.assertEqual(song["day_song_reference_number"], 24)
        self.assertEqual(song["night_song_reference_number"], 25)
        self.assertEqual(len(res.sections["automap_notes"]), 1)

    def test_unmodified_roundtrip_is_byte_exact(self):
        data, *_ = self._build()
        parser, res = self._read(data)
        out = io.BytesIO()
        parser.write(BinaryWriter(out), res)
        self.assertEqual(out.getvalue(), data)

    def test_repack_keeps_original_header_pointer_convention(self):
        data, _, sizes, anim_block = self._build()
        parser, res = self._read(data)
        res.modified = True
        out = io.BytesIO()
        parser.write(BinaryWriter(out), res)
        repacked = out.getvalue()
        self.assertEqual(len(repacked), len(data))
        again = BinaryParser(self.schema, resource_class=Resource).read(
            BinaryReader(io.BytesIO(repacked)), name="SYNTH2")
        # Header pointers omit the animations block, exactly like the originals:
        # the section nearest the animations is pointed at 76 * N bytes too low.
        starts = sorted(again.values[f"offset_to_{n}"] + anim_block
                        for n in self.DISPLACED)
        self.assertEqual(starts[0], again.values["offset_to_animations"]
                         + self.N_ANIM * sizes["animations"])
        # And every section re-parses to the same content.
        song = again.sections["song_entries"][0]
        self.assertEqual(song["day_song_reference_number"], 24)
        self.assertEqual(song["night_song_reference_number"], 25)
        self.assertEqual(len(again.sections["automap_notes"]), 1)
        self.assertEqual(len(again.sections["animations"]), self.N_ANIM)


if __name__ == "__main__":
    unittest.main()
