import struct
import unittest

import numpy as np

from core.resource import Resource
from drivers.InfinityEngine.graphics.tis_decoder import TisDecoder


def _make_palette_tile():
    palette = bytearray(1024)
    # BGRA for red in entry 1
    palette[4:8] = bytes([0, 0, 255, 0])
    pixels = bytes([1]) * 4096
    return bytes(palette) + pixels


def _build_tis_blob(tile_count, tile_data_block_size, payload):
    header = (
        b"TIS "
        + b"V1  "
        + int(tile_count).to_bytes(4, "little")
        + int(tile_data_block_size).to_bytes(4, "little")
        + (24).to_bytes(4, "little")
        + (64).to_bytes(4, "little")
    )
    return header + payload


def _make_resource(tile_count, tile_data_block_size, payload, with_tiles_section=False):
    resource = Resource(schema=None, name="TEST_TIS")
    resource.sections = {
        "header": [{
            "count_of_tiles": int(tile_count),
            "tile_data_block_size": int(tile_data_block_size),
            "offset_to_tiles": 24,
            "tile_dimension": 64,
        }],
    }
    if with_tiles_section:
        tiles = []
        for i in range(tile_count):
            off = i * tile_data_block_size
            tiles.append({"raw_data": payload[off:off + tile_data_block_size]})
        resource.sections["tiles"] = tiles
    resource._original_bytes = _build_tis_blob(tile_count, tile_data_block_size, payload)
    return resource


class TestTisDecoder(unittest.TestCase):
    def test_palette_decode_uses_raw_bytes_without_tiles_section(self):
        tile = _make_palette_tile()
        resource = _make_resource(
            tile_count=1,
            tile_data_block_size=5120,
            payload=tile,
            with_tiles_section=False,
        )

        buffer = TisDecoder().decode_tis(resource, grid_width=1)

        self.assertEqual(buffer.shape, (64, 64, 4))
        self.assertTrue(np.array_equal(buffer[0, 0], np.array([255, 0, 0, 255], dtype=np.uint8)))

    def test_pvrz_missing_page_is_negative_cached(self):
        entry = struct.pack("<III", 7, 0, 0)
        payload = entry * 4
        resource = _make_resource(
            tile_count=4,
            tile_data_block_size=12,
            payload=payload,
            with_tiles_section=False,
        )

        call_counter = {"count": 0}

        def missing_provider(_page_index):
            call_counter["count"] += 1
            return None

        buffer = TisDecoder().decode_tis(resource, pvrz_page_provider=missing_provider, grid_width=2)

        self.assertEqual(call_counter["count"], 1)
        self.assertEqual(buffer.shape, (128, 128, 4))
        self.assertEqual(int(buffer.sum()), 0)

    def test_pvrz_black_tile_sentinel(self):
        entry = struct.pack("<III", 0xFFFFFFFF, 0, 0)
        resource = _make_resource(
            tile_count=1,
            tile_data_block_size=12,
            payload=entry,
            with_tiles_section=False,
        )

        buffer = TisDecoder().decode_tis(resource, pvrz_page_provider=lambda _idx: None, grid_width=1)

        self.assertEqual(buffer.shape, (64, 64, 4))
        self.assertTrue(np.array_equal(buffer[0, 0], np.array([0, 0, 0, 255], dtype=np.uint8)))


if __name__ == "__main__":
    unittest.main()
