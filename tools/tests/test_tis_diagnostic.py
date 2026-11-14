"""Game-free tests for tools/tis_diagnostic.py analysis functions."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools import tis_diagnostic as td


def build_wed(overlays, tilemaps, lookup):
    """Minimal WED v1.3 bytes: header, overlays, secondary header, tilemaps, lookup."""
    n = len(overlays)
    ov_off = 32
    sec_off = ov_off + 24 * n
    tm_off = sec_off + 20
    lk_off = tm_off + 10 * len(tilemaps)
    end = lk_off + 2 * len(lookup)
    header = (b"WED " + b"V1.3" + struct.pack("<IIIIII", n, 0, ov_off, sec_off, tm_off, lk_off))
    body = b""
    for (w, h, name, unique) in overlays:
        body += struct.pack("<HH8sHHII", w, h, name.encode().ljust(8, b"\0"), unique, 0, tm_off, lk_off)
    # secondary header: 0 polygons, all offsets point at end of file
    sec = struct.pack("<IIIII", 0, end, end, end, end)
    tms = b"".join(struct.pack("<HHHBBH", p, c, 0xFFFF, 0, 0, 0) for p, c in tilemaps)
    lks = struct.pack("<%dH" % len(lookup), *lookup)
    return header + body + sec + tms + lks


class WedRawTests(unittest.TestCase):
    def test_round_trip(self):
        raw = build_wed([(2, 2, "AR0001", 4)], [(i, 1) for i in range(4)], [10, 11, 12, 13])
        wed = td.parse_wed_raw(raw)
        self.assertNotIn("error", wed)
        self.assertEqual(wed["overlays"][0]["width"], 2)
        self.assertEqual(wed["overlays"][0]["tileset_name"], "AR0001")
        self.assertEqual(len(wed["tilemaps"]), 4)
        self.assertEqual(wed["lookup"], [10, 11, 12, 13])
        self.assertEqual(wed["lookup_room"], 4)

    def test_too_short(self):
        self.assertIn("error", td.parse_wed_raw(b"WED V1.3"))

    def test_layout_check_flags_gap(self):
        ovs = [
            {"width": 2, "height": 2, "offset_to_tilemap": 100, "offset_to_tile_index_lookup": 200},
            {"width": 1, "height": 1, "offset_to_tilemap": 100 + 10 * 5, "offset_to_tile_index_lookup": 208},
        ]
        notes = td.check_overlay_layout(ovs)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0][0], 1)


class MappingTests(unittest.TestCase):
    OV = [{"width": 4, "height": 3, "offset_to_tilemap": 100, "offset_to_tile_index_lookup": 400}]

    def tilemaps(self, n, count=1):
        return [{"primary_tile_index": i, "primary_tile_count": count} for i in range(n)]

    def test_identity_mapping_resolves_everything(self):
        m = td.analyze_mapping(self.OV, self.tilemaps(12), list(range(12)), 12, 0)
        self.assertEqual(m["reasons"]["ok"], 12)
        self.assertIsNone(m["first_unresolved"])
        self.assertEqual(m["identity_cells"], 12)
        self.assertEqual(m["tis_indices"], list(range(12)))

    def test_truncated_tilemaps_report_first_unresolved_cell(self):
        m = td.analyze_mapping(self.OV, self.tilemaps(7), list(range(12)), 12, 0)
        self.assertEqual(m["reasons"]["no_tilemap_entry"], 5)
        fu = m["first_unresolved"]
        self.assertEqual((fu["cell"], fu["row"], fu["col"]), (7, 1, 3))
        self.assertEqual(fu["reason"], "no_tilemap_entry")

    def test_lookup_shorter_than_needed(self):
        m = td.analyze_mapping(self.OV, self.tilemaps(12), list(range(10)), 12, 0)
        self.assertEqual(m["reasons"]["lookup_out_of_range"], 2)
        self.assertEqual(m["first_unresolved"]["cell"], 10)

    def test_multi_frame_cells_need_more_lookup_entries(self):
        tms = self.tilemaps(12)
        tms[11] = {"primary_tile_index": 11, "primary_tile_count": 4}
        m = td.analyze_mapping(self.OV, tms, list(range(12)), 12, 0)
        self.assertEqual(m["animated_cells"], 1)
        self.assertEqual(m["required_lookup_entries"], 15)

    def test_tis_index_beyond_tile_count(self):
        m = td.analyze_mapping(self.OV, self.tilemaps(12), list(range(12)), 8, 0)
        self.assertEqual(m["reasons"]["tis_out_of_range"], 4)

    def test_second_overlay_starts_after_first(self):
        ovs = [
            {"width": 2, "height": 1, "offset_to_tilemap": 100, "offset_to_tile_index_lookup": 400},
            {"width": 2, "height": 1, "offset_to_tilemap": 120, "offset_to_tile_index_lookup": 404},
        ]
        tms = [{"primary_tile_index": i, "primary_tile_count": 1} for i in range(4)]
        m = td.analyze_mapping(ovs, tms, [5, 6, 7, 8], 20, 1)
        self.assertEqual(m["tilemap_start"], 2)
        self.assertEqual(m["tis_indices"], [7, 8])

    def test_compare_mappings(self):
        self.assertEqual(td.compare_mappings([1, 2, 3], [1, 2, 3]), (0, None))
        self.assertEqual(td.compare_mappings([1, 2, 3], [1, 9, -1]), (2, 1))


class TisRecordTests(unittest.TestCase):
    def test_parse_and_analyze_records(self):
        raw = b"\0" * 4 + struct.pack("<IIIIIIIII", 0, 0, 0, 1, 64, 0, 0xFFFFFFFF, 0, 0)
        recs = td.parse_pvrz_records(raw, 4, 3)
        self.assertEqual(recs, [(0, 0, 0), (1, 64, 0), (0xFFFFFFFF, 0, 0)])
        stats = td.analyze_pvrz_records(recs, {0: (128, 128), 1: (64, 64)})
        self.assertEqual(stats["no_page"], 1)
        self.assertEqual(stats["pages"], {0: 1, 1: 1})
        self.assertEqual(stats["out_of_bounds"], 1)  # page 1 is only 64 wide, tile at x=64

    def test_records_truncated_by_data_length(self):
        raw = b"\0" * 20
        self.assertEqual(len(td.parse_pvrz_records(raw, 0, 5)), 1)

    def test_unaligned_records_counted(self):
        stats = td.analyze_pvrz_records([(0, 10, 0), (0, 64, 64)])
        self.assertEqual(stats["unaligned"], 1)

    def test_page_candidates(self):
        c = td.pvrz_page_candidates("AR0072", 3)
        self.assertEqual(c[0], "A007203")
        self.assertIn("AR007203", c)
        self.assertEqual(td.pvrz_page_candidates("AR0072N", 3)[0], "A0072N03")
        self.assertIn("A00720A", td.pvrz_page_candidates("AR0072", 10))


class BifTableTests(unittest.TestCase):
    def test_slack_and_tiles_that_fit(self):
        files = [{"offset": 1000, "size": 100}]
        tilesets = [{"offset": 2000, "tile_count": 10, "tile_size": 12},
                    {"offset": 2200, "tile_count": 5, "tile_size": 12}]
        rows = td.analyze_bif_table(3000, 100, files, 140, tilesets)
        self.assertEqual(rows[0]["data_end"], 2120)
        self.assertEqual(rows[0]["next_start"], 2200)
        self.assertEqual(rows[0]["slack_bytes"], 80)
        self.assertEqual(rows[0]["tiles_that_fit"], 16)   # 200 // 12
        self.assertEqual(rows[1]["next_start"], 3000)

    def test_overlap_gives_negative_slack(self):
        tilesets = [{"offset": 2000, "tile_count": 30, "tile_size": 12},
                    {"offset": 2100, "tile_count": 5, "tile_size": 12}]
        rows = td.analyze_bif_table(5000, 100, [], 140, tilesets)
        self.assertLess(rows[0]["slack_bytes"], 0)

    def test_read_bif_table_round_trip(self):
        import tempfile, os
        fe_off = 20
        blob = (b"BIFF" + b"V1  " + struct.pack("<III", 1, 1, fe_off)
                + struct.pack("<IIIHH", 0, 500, 64, 1, 0)           # one file entry (16 bytes)
                + struct.pack("<IIIIHH", 0, 600, 4, 12, 1003, 0))   # one tileset entry (20 bytes)
        blob += b"\0" * 100
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(blob)
            name = fh.name
        try:
            info = td.read_bif_table(name)
        finally:
            os.unlink(name)
        self.assertEqual(info["files"], [{"offset": 500, "size": 64}])
        self.assertEqual(info["tilesets"], [{"locator": 0, "offset": 600, "tile_count": 4, "tile_size": 12}])
        self.assertEqual(info["tileset_entries_offset"], fe_off + 16)

    def test_locator_bits_exposed_and_matched(self):
        tilesets = [{"locator": 1 << 14, "offset": 2000, "tile_count": 10, "tile_size": 12},
                    {"locator": 2 << 14, "offset": 2200, "tile_count": 5, "tile_size": 12}]
        rows = td.analyze_bif_table(3000, 100, [], 140, tilesets)
        self.assertEqual([r["ts_bits"] for r in rows], [1, 2])

    def test_not_a_biff(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"NOPE" * 10)
            name = fh.name
        try:
            self.assertIn("error", td.read_bif_table(name))
        finally:
            os.unlink(name)


class OutOfRangeKeepsRawIndexTest(unittest.TestCase):
    def test_raw_index_kept_for_comparison_with_viewer(self):
        ov = [{"width": 2, "height": 1, "offset_to_tilemap": 0, "offset_to_tile_index_lookup": 0}]
        tms = [{"primary_tile_index": 0, "primary_tile_count": 1}, {"primary_tile_index": 1, "primary_tile_count": 1}]
        m = td.analyze_mapping(ov, tms, [0, 900], 10, 0)
        self.assertEqual(m["reasons"]["tis_out_of_range"], 1)
        self.assertEqual(m["tis_indices"], [0, 900])


class _Schema:
    def __init__(self, name):
        self.name = name


class _Res:
    def __init__(self, name, values, sections, raw, schema=None):
        self.name, self.values, self.sections = name, values, sections
        self._original_bytes, self.schema, self.source = raw, schema, "fake"

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_section(self, key):
        return self.sections.get(key)


class _FakeLoader:
    default_game = "FAKE"

    def __init__(self, tis, wed):
        self.resources = {"TIS": tis, "WED": wed}

    def load(self, resref, restype, game=None):
        return self.resources.get(restype)

    def _get_install_path(self, game):
        return None

    def _find_exact_resource_location(self, *args):
        return None

    def _estimate_tis_tile_count(self, *args):
        return None

    def iter_resources(self, game=None):
        return iter(())


class RunOneSmokeTest(unittest.TestCase):
    def test_report_flags_truncated_tilemaps(self):
        import argparse
        tilemaps = [(i, 1) for i in range(7)]          # 7 of 12 cells present
        lookup = list(range(12))
        wed_raw = build_wed([(4, 3, "AR0001", 12)], tilemaps, lookup)
        tm_off, lk_off = struct.unpack_from("<II", wed_raw, 32 + 16)
        tiles = b"".join(struct.pack("<III", 0, (i % 4) * 64, 0) for i in range(12))
        tis_raw = b"TIS V1  " + struct.pack("<IIII", 12, 12, 24, 64) + tiles
        tis = _Res("AR0001", {"count_of_tiles": 12, "tile_data_block_size": 12,
                              "offset_to_tiles": 24, "tile_dimension": 64}, {"tiles": []},
                   tis_raw, _Schema("TIS_PVRZ"))
        wed = _Res("AR0001", {}, {
            "overlays": [{"width": 4, "height": 3, "tileset_name": "AR0001", "unique_tile_count": 12,
                          "offset_to_tilemap": tm_off, "offset_to_tile_index_lookup": lk_off}],
            "tilemaps": [{"primary_tile_index": p, "primary_tile_count": c} for p, c in tilemaps],
            "tile_index_lookup": [{"tis_index": x} for x in lookup],
        }, wed_raw)
        args = argparse.Namespace(overlay=None, cells=4, no_pages=True, no_viewer=True)
        text = td.run_one(_FakeLoader(tis, wed), "FAKE", "AR0001", args).render()
        self.assertIn("first unresolved cell: 7 (row 1, col 3)", text)
        self.assertIn("schema parsed 7 tilemap entries but the overlays declare 12 cells", text)
        self.assertIn("SUMMARY OF FLAGS (2)", text)


class BifSectionIsReportedTest(unittest.TestCase):
    def test_bif_section_printed_when_key_entry_exists(self):
        import argparse, os, tempfile
        fe_off = 20
        blob = (b"BIFF" + b"V1  " + struct.pack("<III", 1, 1, fe_off)
                + struct.pack("<IIIHH", 0, 500, 64, 1, 0)
                + struct.pack("<IIIIHH", 0, 600, 4, 12, 1003, 0)) + b"\0" * 100
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(blob)
            bif_path = fh.name

        class _Chitin:
            sections = {"resource_entries": [
                {"resource_name": "AR0001", "resource_type": 1003,
                 "resource_locator": {"bif_index": 7, "tileset_index": 0, "resource_index": 0}}]}

        class _KeyedLoader(_FakeLoader):
            chitins = {"FAKE": _Chitin()}

            def _find_exact_resource_location(self, *args):
                return {"resource_locator": {"bif_index": 7, "tileset_index": 0, "resource_index": 0}}

            def _find_bif_file(self, entry, game):
                return bif_path

        tilemaps = [(i, 1) for i in range(12)]
        wed_raw = build_wed([(4, 3, "AR0001", 12)], tilemaps, list(range(12)))
        tm_off, lk_off = struct.unpack_from("<II", wed_raw, 32 + 16)
        tis_raw = b"TIS V1  " + struct.pack("<IIII", 4, 12, 24, 64) + b"\0" * 48
        tis = _Res("AR0001", {"count_of_tiles": 4, "tile_data_block_size": 12, "offset_to_tiles": 24,
                              "tile_dimension": 64}, {"tiles": []}, tis_raw, _Schema("TIS_PVRZ"))
        wed = _Res("AR0001", {}, {
            "overlays": [{"width": 4, "height": 3, "tileset_name": "AR0001", "unique_tile_count": 12,
                          "offset_to_tilemap": tm_off, "offset_to_tile_index_lookup": lk_off}],
            "tilemaps": [{"primary_tile_index": p, "primary_tile_count": c} for p, c in tilemaps],
            "tile_index_lookup": [{"tis_index": i} for i in range(12)]}, wed_raw)
        args = argparse.Namespace(overlay=None, cells=2, no_pages=True, no_viewer=True)
        try:
            text = td.run_one(_KeyedLoader(tis, wed), "FAKE", "AR0001", args).render()
        finally:
            os.unlink(bif_path)
        self.assertIn("== BIF tileset table", text)
        self.assertIn("entry at position 0: locator=0x00000000 (tileset bits=0) offset=0x258", text)
        self.assertIn("<== matched by locator (IESDP) for this TIS", text)
        self.assertIn("AR0001(ts=0,res=0)", text)


class ScanTests(unittest.TestCase):
    @staticmethod
    def rows(counts, first_bits=1, size=12):
        return [{"index": i, "ts_bits": first_bits + i, "tile_count": c, "tile_size": size}
                for i, c in enumerate(counts)]

    def entries(self):
        return [
            {"name": "AR0072", "bif_index": 74, "ts": 1, "res": 0},
            {"name": "AR1515", "bif_index": 74, "ts": 2, "res": 0},
            {"name": "AR1516", "bif_index": 74, "ts": 3, "res": 0},
        ]

    def test_one_based_locators_are_flagged_for_the_old_lookup(self):
        tables = {74: {"name": "AREA150C.bif", "rows": self.rows([1211, 822, 1060])}}
        res = td.scan_tilesets(self.entries(), tables)
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["old_wrong_entry"], ["AR0072", "AR1515"])
        self.assertEqual(res["old_cannot_load"], ["AR1516"])
        self.assertEqual(res["by_tile_size"], {12: 3})
        self.assertEqual(res["items"][0]["tile_count"], 1211)
        self.assertEqual(res["items"][0]["pos"], 0)

    def test_zero_based_locators_match_the_old_lookup(self):
        tables = {1: {"name": "A.bif", "rows": self.rows([5, 6], first_bits=0)}}
        ents = [{"name": "X", "bif_index": 1, "ts": 0, "res": 0}, {"name": "Y", "bif_index": 1, "ts": 1, "res": 0}]
        res = td.scan_tilesets(ents, tables)
        self.assertEqual(res["old_wrong_entry"], [])
        self.assertEqual(res["old_cannot_load"], [])

    def test_missing_bif_and_missing_entry(self):
        tables = {1: {"error": "x"}, 2: {"name": "B.bif", "rows": self.rows([3])}}
        ents = [{"name": "A", "bif_index": 1, "ts": 1, "res": 0},
                {"name": "B", "bif_index": 2, "ts": 9, "res": 0},
                {"name": "C", "bif_index": 3, "ts": 1, "res": 0}]
        res = td.scan_tilesets(ents, tables)
        self.assertEqual(res["no_bif"], ["A", "C"])
        self.assertEqual(res["no_entry"], ["B"])

    def test_nonzero_resource_index_and_shared_claims(self):
        tables = {1: {"name": "A.bif", "rows": self.rows([100])}}
        ents = [{"name": "P", "bif_index": 1, "ts": 1, "res": 0}, {"name": "Q", "bif_index": 1, "ts": 1, "res": 40}]
        res = td.scan_tilesets(ents, tables)
        self.assertEqual(res["res_nonzero"], [{"name": "Q", "res": 40, "tile_count": 100,
                                               "inside_entry": True, "shared_with": ["P"]}])
        self.assertEqual(res["shared_claims"], [{"bif_index": 1, "ts": 1, "names": ["P", "Q"]}])
        self.assertIn("evidence FOR pooling", td.pool_verdict(res))

    def test_pool_verdict_when_everything_is_zero(self):
        tables = {74: {"name": "A.bif", "rows": self.rows([1, 2, 3])}}
        self.assertIn("no evidence", td.pool_verdict(td.scan_tilesets(self.entries(), tables)))

    def test_unreferenced_and_duplicate_bits(self):
        rows = self.rows([1, 2, 3])
        rows.append({"index": 3, "ts_bits": 1, "tile_count": 4, "tile_size": 12})
        tables = {74: {"name": "A.bif", "rows": rows}}
        res = td.scan_tilesets(self.entries()[:2], tables)
        self.assertEqual([u["ts_bits"] for u in res["unreferenced"]], [3])
        self.assertEqual(res["duplicate_bits"], [{"bif": "A.bif", "ts_bits": 1, "positions": [0, 3]}])

    def test_wed_check(self):
        tables = {74: {"name": "A.bif", "rows": self.rows([1211, 822, 1060])}}
        res = td.scan_tilesets(self.entries(), tables, {"AR0072": 1200, "AR1515": 900, "AR1516": None})
        self.assertEqual(res["wed_checked"], 2)
        self.assertEqual(res["wed_missing"], 1)
        self.assertEqual(res["wed_short"], [{"name": "AR1515", "tiles": 822, "needed": 900}])

    def test_render_mentions_key_findings(self):
        tables = {74: {"name": "AREA150C.bif", "rows": self.rows([1211, 822, 1060])}}
        text = td.render_scan(td.scan_tilesets(self.entries(), tables, {"AR0072": 1200}), "FAKE", limit=1)
        self.assertIn("TIS ENTRIES IN KEY".lower(), text.lower())
        self.assertIn("WRONG entry", text)
        self.assertIn("... and 1 more", text)


class RunScanSmokeTest(unittest.TestCase):
    def test_run_scan_with_fake_loader_and_synthetic_bif(self):
        import argparse, contextlib, os, tempfile
        fe_off = 20
        entries = [(1 << 14, 3, 12), (2 << 14, 2, 12)]
        data_off = fe_off + 20 * len(entries)
        blob = b"BIFF" + b"V1  " + struct.pack("<III", 0, len(entries), fe_off)
        for i, (loc, cnt, sz) in enumerate(entries):
            blob += struct.pack("<IIIIHH", loc, data_off + 100 * i, cnt, sz, 1003, 0)
        blob += b"\0" * 400
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(blob)
            bif_path = fh.name

        class _Chitin:
            sections = {"resource_entries": [
                {"resource_name": "AR0001", "resource_type": 1003,
                 "resource_locator": {"bif_index": 5, "tileset_index": 1, "resource_index": 0}},
                {"resource_name": "AR0002", "resource_type": 1003,
                 "resource_locator": {"bif_index": 5, "tileset_index": 2, "resource_index": 0}},
                {"resource_name": "ITEM01", "resource_type": 1005,
                 "resource_locator": {"bif_index": 5, "tileset_index": 0, "resource_index": 3}}]}

        class _Handler:
            @staticmethod
            @contextlib.contextmanager
            def get_stream(path):
                with open(path, "rb") as f:
                    yield f

        class _Loader:
            chitins = {"FAKE": _Chitin()}
            biff_handler = _Handler()

            def _load_chitin(self, game):
                pass

            def _find_bif_file(self, entry, game):
                return bif_path

            def _find_exact_resource_location(self, *a):
                return None   # no WEDs

        args = argparse.Namespace(no_wed=False, csv=None, limit=5)
        try:
            text = td.run_scan(_Loader(), "FAKE", args)
        finally:
            os.unlink(bif_path)
        self.assertIn("TIS entries in KEY: 2", text)
        self.assertIn("12 bytes: 2", text)
        self.assertIn("WRONG entry", text)
        self.assertIn("2 do not", text)


if __name__ == "__main__":
    unittest.main()
