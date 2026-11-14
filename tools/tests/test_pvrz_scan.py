"""Game-free tests for tools/pvrz_scan.py (issue #39)."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools import pvrz_scan

DXT1, DXT5 = 7, 11


def build_pvr(width=8, height=8, pixel_format=DXT1, mips=1, metadata=b"", texture=None):
    """Builds a PVR v3 file; texture defaults to the exact top level."""
    block = 8 if pixel_format == DXT1 else 16
    if texture is None:
        texture = bytes(((width + 3) // 4) * ((height + 3) // 4) * block)
    header = struct.pack("<IIQ9I", pvrz_scan.PVR3_MAGIC, 0, pixel_format, 0, 0, height, width, 1, 1, 1, mips, len(metadata))
    return header + metadata + texture


def build_pvrz(pvr):
    return struct.pack("<I", len(pvr)) + zlib.compress(pvr)


class AnalyzePvrzTests(unittest.TestCase):
    def test_documented_layout(self):
        facts = pvrz_scan.analyze_pvrz(build_pvrz(build_pvr()))
        self.assertEqual(facts["layout"], "size+zlib")
        self.assertEqual(facts["size_field"], facts["decompressed"])
        self.assertEqual((facts["trailing"], facts["nested_zlib"]), (0, False))
        self.assertEqual((facts["magic"], facts["format"], facts["width"], facts["height"]), ("PVR3", "DXT1", 8, 8))
        self.assertEqual((facts["mips"], facts["metadata"], facts["data_vs_expected"]), (1, 0, "top level"))

    def test_dxt5_block_size(self):
        facts = pvrz_scan.analyze_pvrz(build_pvrz(build_pvr(pixel_format=DXT5)))
        self.assertEqual((facts["format"], facts["top_level_bytes"], facts["data_vs_expected"]), ("DXT5", 64, "top level"))

    def test_mip_chain_is_recognised(self):
        # 8x8 DXT1: top level 32 bytes, chain 32 + 8 + 8 + 8 = 56.
        facts = pvrz_scan.analyze_pvrz(build_pvrz(build_pvr(mips=4, texture=bytes(56))))
        self.assertEqual((facts["full_chain_bytes"], facts["data_vs_expected"]), (56, "full chain"))

    def test_metadata_offsets_the_texture_data(self):
        facts = pvrz_scan.analyze_pvrz(build_pvrz(build_pvr(metadata=b"x" * 16)))
        self.assertEqual((facts["metadata"], facts["texture_bytes"], facts["data_vs_expected"]), (16, 32, "top level"))

    def test_other_layouts_are_reported_not_hidden(self):
        pvr = build_pvr()
        self.assertEqual(pvrz_scan.analyze_pvrz(zlib.compress(pvr))["layout"], "zlib")
        self.assertEqual(pvrz_scan.analyze_pvrz(pvr)["layout"], "uncompressed")
        self.assertEqual(pvrz_scan.analyze_pvrz(b"abcdefghij")["layout"], "unrecognised")
        self.assertEqual(pvrz_scan.analyze_pvrz(b"abc")["layout"], "too small")

    def test_trailing_bytes_and_nested_compression(self):
        trailing = pvrz_scan.analyze_pvrz(build_pvrz(build_pvr()) + b"\x00\x00")
        self.assertEqual(trailing["trailing"], 2)
        nested = pvrz_scan.analyze_pvrz(build_pvrz(zlib.compress(build_pvr())))
        self.assertIs(nested["nested_zlib"], True)
        self.assertNotEqual(nested["magic"], "PVR3")

    def test_non_pvr3_header(self):
        facts = pvrz_scan.analyze_pvrz(build_pvrz(bytes(range(60))))
        self.assertEqual(facts["layout"], "size+zlib")
        self.assertNotEqual(facts["magic"], "PVR3")
        self.assertNotIn("width", facts)


class FakeLoader:
    def __init__(self, pages):
        self.pages = pages

    def iter_resources(self, game=None):
        return iter([(name, "PVRZ", {}) for name in self.pages] + [("AR0072", "TIS", {})])

    def get_raw_bytes(self, resref, restype=None, game=None):
        if self.pages[resref] is Exception:
            raise OSError("unreadable")
        return self.pages[resref], "fake.bif", 0x404


class ScanGameTests(unittest.TestCase):
    def test_only_pvrz_resources_are_scanned_and_failures_are_reported(self):
        loader = FakeLoader({"B": build_pvrz(build_pvr()), "A": None, "C": Exception})
        rows = dict(pvrz_scan.scan_game(loader, "TEST"))
        self.assertEqual(sorted(rows), ["A", "B", "C"])
        self.assertEqual(rows["B"]["layout"], "size+zlib")
        self.assertEqual((rows["A"]["layout"], rows["C"]["layout"]), ("unreadable", "unreadable"))


class SummaryTests(unittest.TestCase):
    def test_clean_game_reports_no_deviations(self):
        rows = [("A", pvrz_scan.analyze_pvrz(build_pvrz(build_pvr()))),
                ("B", pvrz_scan.analyze_pvrz(build_pvrz(build_pvr(pixel_format=DXT5))))]
        summary = pvrz_scan.summarize(rows)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(dict(summary["examples"]), {})
        self.assertIn("No deviations", pvrz_scan.render(summary, "TEST"))

    def test_deviations_are_listed_by_resref(self):
        rows = [("GOOD", pvrz_scan.analyze_pvrz(build_pvrz(build_pvr()))),
                ("RAW", pvrz_scan.analyze_pvrz(zlib.compress(build_pvr()))),
                ("JUNK", pvrz_scan.analyze_pvrz(b"abcdefghij")),
                ("FMT", pvrz_scan.analyze_pvrz(build_pvrz(build_pvr(pixel_format=6, texture=bytes(32)))))]
        examples = pvrz_scan.summarize(rows)["examples"]
        self.assertEqual(examples["layout other than the documented size+zlib"], ["RAW", "JUNK"])
        self.assertEqual(examples["pixel format other than DXT1/DXT3/DXT5"], ["FMT"])

    def test_empty_scan_says_so(self):
        text = pvrz_scan.render(pvrz_scan.summarize([]), "TEST")
        self.assertIn("No PVRZ pages found", text)
        self.assertNotIn("No deviations", text)

    def test_csv_round_trip(self):
        import csv
        import os
        import tempfile
        rows = [("A", pvrz_scan.analyze_pvrz(build_pvrz(build_pvr())))]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scan.csv")
            pvrz_scan.write_csv(path, rows)
            with open(path, newline="", encoding="utf-8") as fh:
                record = next(csv.DictReader(fh))
        self.assertEqual((record["resref"], record["format"], record["width"]), ("A", "DXT1", "8"))


if __name__ == "__main__":
    unittest.main()
