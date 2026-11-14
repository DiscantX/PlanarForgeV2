"""Tests for the PVRZ decoder (issue #39). Uses synthetic PVRZ pages; no game files."""
import struct
import unittest
import zlib

import numpy as np

from drivers.InfinityEngine.graphics.pvrz_decoder import (
    PIXEL_FORMAT_DXT1, PIXEL_FORMAT_DXT5, PVR3_MAGIC, PvrzDecoder, PvrzError)

RED, BLUE = 0xF800, 0x001F


def dxt1_block(c0, c1, indices=0):
    return struct.pack("<HHI", c0, c1, indices)


def dxt5_block(alpha0, alpha1, alpha_bits, c0, c1, indices=0):
    return bytes([alpha0, alpha1]) + alpha_bits.to_bytes(6, "little") + struct.pack("<HHI", c0, c1, indices)


def build_pvr(width, height, texture, pixel_format=PIXEL_FORMAT_DXT1, mips=1, metadata=b"", version=PVR3_MAGIC):
    header = struct.pack("<IIQ9I", version, 0, pixel_format, 0, 0, height, width, 1, 1, 1, mips, len(metadata))
    return header + metadata + texture


def build_pvrz(pvr, size=None):
    return struct.pack("<I", len(pvr) if size is None else size) + zlib.compress(pvr)


class DecodeTests(unittest.TestCase):
    def test_dxt1_page_round_trip(self):
        block = dxt1_block(RED, BLUE, 0b01 << 2)  # pixel 1 uses colour 1
        decoded = PvrzDecoder.decode_pvrz_bytes(build_pvrz(build_pvr(4, 4, block)))
        self.assertEqual(decoded.shape, (4, 4, 4))
        self.assertEqual(list(decoded[0, 0]), [255, 0, 0, 255])
        self.assertEqual(list(decoded[0, 1]), [0, 0, 255, 255])

    def test_dxt1_three_colour_mode_has_transparent_black(self):
        # c0 <= c1: index 2 is the midpoint, index 3 is transparent black.
        block = dxt1_block(BLUE, RED, 0b11 << 2 | 0b10 << 4)
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(4, 4, block))
        self.assertEqual(list(decoded[0, 1]), [0, 0, 0, 0])
        self.assertEqual(list(decoded[0, 2]), [127, 0, 127, 255])

    def test_dxt5_alpha_and_colour(self):
        # 8-alpha mode (alpha0 > alpha1); pixel 0 -> alpha index 0, pixel 1 -> alpha index 1.
        block = dxt5_block(200, 40, 0b001 << 3, RED, BLUE, 0b01 << 2)
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(4, 4, block, PIXEL_FORMAT_DXT5))
        self.assertEqual(list(decoded[0, 0]), [255, 0, 0, 200])
        self.assertEqual(list(decoded[0, 1]), [0, 0, 255, 40])

    def test_dxt5_six_alpha_mode_has_transparent_and_opaque_ends(self):
        # alpha0 <= alpha1: indices 6 and 7 are 0 and 255.
        block = dxt5_block(10, 20, 6 | 7 << 3, RED, BLUE)
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(4, 4, block, PIXEL_FORMAT_DXT5))
        self.assertEqual((decoded[0, 0, 3], decoded[0, 1, 3]), (0, 255))

    def test_dxt5_colour_block_is_always_four_colour(self):
        # c0 < c1 would give transparent black at index 3 in DXT1; DXT5 interpolates instead.
        block = dxt5_block(255, 255, 0, BLUE, RED, 0b11)
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(4, 4, block, PIXEL_FORMAT_DXT5))
        self.assertEqual(list(decoded[0, 0]), [170, 0, 85, 255])

    def test_size_not_a_multiple_of_four_is_cropped(self):
        blocks = dxt1_block(RED, BLUE) * 4  # 6x5 needs 2x2 blocks
        self.assertEqual(PvrzDecoder.decode_pvr_bytes(build_pvr(6, 5, blocks)).shape, (5, 6, 4))

    def test_blocks_are_laid_out_row_by_row(self):
        blocks = dxt1_block(RED, BLUE) + dxt1_block(BLUE, RED)
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(8, 4, blocks))
        self.assertEqual((list(decoded[0, 0]), list(decoded[0, 4])), ([255, 0, 0, 255], [0, 0, 255, 255]))

    def test_metadata_is_skipped_and_mip_chain_ignored(self):
        top = dxt1_block(RED, BLUE) * 4  # 8x8
        decoded = PvrzDecoder.decode_pvr_bytes(build_pvr(8, 8, top + bytes(24), mips=4, metadata=b"x" * 16))
        self.assertEqual(list(decoded[0, 0]), [255, 0, 0, 255])

    def test_works_on_a_bytearray_or_view_of_the_page(self):
        page = build_pvrz(build_pvr(4, 4, dxt1_block(RED, BLUE)))
        self.assertEqual(PvrzDecoder.decode_pvrz_bytes(bytearray(page)).shape, (4, 4, 4))


class ErrorTests(unittest.TestCase):
    def assert_rejected(self, data, fragment, pvrz=True):
        decode = PvrzDecoder.decode_pvrz_bytes if pvrz else PvrzDecoder.decode_pvr_bytes
        with self.assertRaises(PvrzError) as ctx:
            decode(data)
        self.assertIn(fragment, str(ctx.exception))

    def test_pvrz_error_is_a_value_error(self):
        self.assertTrue(issubclass(PvrzError, ValueError))

    def test_too_small_or_missing(self):
        self.assert_rejected(None, "too small")
        self.assert_rejected(b"abc", "too small")

    def test_unrecognised_data_is_an_error_not_a_blank_image(self):
        # Previously 3 bytes gave a blank 256x256 image and 12 bytes raised UnboundLocalError.
        self.assert_rejected(b"abcdefghij", "corrupt")
        self.assert_rejected(bytes(range(12)), "corrupt")

    def test_truncated_stream(self):
        page = build_pvrz(build_pvr(4, 4, dxt1_block(RED, BLUE)))
        self.assert_rejected(page[:-6], "truncated")

    def test_size_field_mismatch(self):
        self.assert_rejected(build_pvrz(build_pvr(4, 4, dxt1_block(RED, BLUE)), size=7), "size field")

    def test_headerless_payload_is_not_guessed_at(self):
        self.assert_rejected(bytes(64), "Not a PVR v3", pvrz=False)
        self.assert_rejected(bytes(16), "smaller than", pvrz=False)

    def test_wrong_version(self):
        self.assert_rejected(build_pvr(4, 4, bytes(8), version=0x21525650), "Not a PVR v3", pvrz=False)

    def test_unsupported_pixel_format_is_named(self):
        self.assert_rejected(build_pvr(4, 4, bytes(8), pixel_format=6), "pixel format 6", pvrz=False)

    def test_metadata_past_end(self):
        pvr = build_pvr(4, 4, bytes(8))
        corrupt = pvr[:48] + struct.pack("<I", 9999) + pvr[52:]
        self.assert_rejected(corrupt, "metadata size", pvrz=False)

    def test_zero_dimension(self):
        self.assert_rejected(build_pvr(0, 4, bytes(8)), "zero dimension", pvrz=False)

    def test_short_texture_data_is_not_padded_with_blank_pixels(self):
        self.assert_rejected(build_pvr(8, 8, dxt1_block(RED, BLUE)), "top level needs", pvrz=False)
        self.assert_rejected(build_pvr(4, 4, bytes(8), PIXEL_FORMAT_DXT5), "top level needs", pvrz=False)


class StructureTests(unittest.TestCase):
    def test_class_has_all_decoder_methods(self):
        # Regression guard for #13: a mis-indented module-level function once
        # ended the class body early and orphaned the methods that followed it.
        for name in ("decode_pvrz_bytes", "decode_pvr_bytes", "_decompress", "_parse_header"):
            self.assertTrue(hasattr(PvrzDecoder, name), f"PvrzDecoder.{name} is missing")

    def test_instance_can_decode_like_the_viewer_does(self):
        page = build_pvrz(build_pvr(4, 4, dxt1_block(RED, BLUE)))
        self.assertEqual(PvrzDecoder().decode_pvrz_bytes(page).shape, (4, 4, 4))


if __name__ == "__main__":
    unittest.main()
