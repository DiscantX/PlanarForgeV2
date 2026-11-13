"""Game-free tests for BiffHandler tileset entry selection (issue #47)."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from drivers.InfinityEngine.io.biff_handler import BiffHandler

TILE = 12


def build_bif(entries):
    """entries: list of (locator, tile_count, fill_byte). Zero file entries; the
    tileset table starts right after the 20-byte header."""
    header_size = 20
    table_size = 20 * len(entries)
    data_offset = header_size + table_size
    table, data = b"", b""
    for locator, count, fill in entries:
        table += struct.pack("<IIIIHH", locator, data_offset + len(data), count, TILE, 0x3EB, 0)
        data += bytes([fill]) * (count * TILE)
    head = b"BIFF" + b"V1  " + struct.pack("<III", 0, len(entries), header_size)
    return head + table + data


class TilesetSelectionTests(unittest.TestCase):
    def read(self, entries, tileset_index, resource_index=0):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(build_bif(entries))
            path = fh.name
        try:
            return BiffHandler().get_resource_data(path, resource_index, tileset_index=tileset_index)
        finally:
            os.unlink(path)

    @staticmethod
    def count_and_fill(blob):
        return struct.unpack_from("<I", blob, 8)[0], blob[24]

    def test_locator_bits_not_position_select_the_entry(self):
        # KEY tileset indices 1..3 against entries at positions 0..2 (the AREA150C.bif shape).
        entries = [(1 << 14, 1211, 0xA1), (2 << 14, 822, 0xB2), (3 << 14, 1060, 0xC3)]
        self.assertEqual(self.count_and_fill(self.read(entries, 1)), (1211, 0xA1))
        self.assertEqual(self.count_and_fill(self.read(entries, 2)), (822, 0xB2))
        self.assertEqual(self.count_and_fill(self.read(entries, 3)), (1060, 0xC3))

    def test_zero_based_locators_still_work(self):
        entries = [(0 << 14, 10, 0x11), (1 << 14, 20, 0x22)]
        self.assertEqual(self.count_and_fill(self.read(entries, 0)), (10, 0x11))
        self.assertEqual(self.count_and_fill(self.read(entries, 1)), (20, 0x22))

    def test_no_matching_locator_returns_none_instead_of_guessing_by_position(self):
        entries = [(1 << 14, 5, 0x01), (2 << 14, 6, 0x02), (3 << 14, 7, 0x03)]
        self.assertIsNone(self.read(entries, 0))   # position 0 exists, but no locator says 0
        self.assertIsNone(self.read(entries, 4))

    def test_only_tileset_bits_are_matched(self):
        # Bits 0-13 and 20-31 of the entry locator must not affect the match.
        entries = [((7 << 20) | (2 << 14) | 0x123, 9, 0x5A)]
        self.assertEqual(self.count_and_fill(self.read(entries, 2)), (9, 0x5A))

    def test_payload_is_the_selected_entrys_data(self):
        entries = [(1 << 14, 2, 0xAA), (2 << 14, 3, 0xBB)]
        blob = self.read(entries, 2)
        self.assertEqual(len(blob), 24 + 3 * TILE)
        self.assertEqual(blob[24:], bytes([0xBB]) * (3 * TILE))


if __name__ == "__main__":
    unittest.main()
