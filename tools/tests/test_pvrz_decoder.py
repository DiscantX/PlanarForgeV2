import unittest
import zlib
import numpy as np
from drivers.InfinityEngine.graphics.pvrz_decoder import PvrzDecoder


class TestPvrzDecoder(unittest.TestCase):
    def test_decode_raw_rgba_pvrz(self):
        width = 2
        height = 2
        header_size = 52
        pixel_data = bytes([
            1, 2, 3, 255,
            4, 5, 6, 255,
            7, 8, 9, 255,
            10, 11, 12, 255,
        ])

        header = (
            header_size.to_bytes(4, 'little') +
            height.to_bytes(4, 'little') +
            width.to_bytes(4, 'little') +
            (1).to_bytes(4, 'little') +  # mipmap count
            (0).to_bytes(4, 'little') +  # flags
            len(pixel_data).to_bytes(4, 'little') +
            (32).to_bytes(4, 'little') +  # bit count
            (0x000000FF).to_bytes(4, 'little') +
            (0x0000FF00).to_bytes(4, 'little') +
            (0x00FF0000).to_bytes(4, 'little') +
            (0xFF000000).to_bytes(4, 'little') +
            b'PVR!' +
            (1).to_bytes(4, 'little')
        )

        pvr_payload = header + pixel_data
        compressed = zlib.compress(pvr_payload)

        decoded = PvrzDecoder.decode_pvrz_bytes(compressed)
        self.assertEqual(decoded.shape, (height, width, 4))
        self.assertTrue(np.array_equal(decoded[0, 0], [1, 2, 3, 255]))
        self.assertTrue(np.array_equal(decoded[1, 1], [10, 11, 12, 255]))

    def test_decode_uncompressed_pvr(self):
        width = 2
        height = 2
        header_size = 52
        pixel_data = bytes([
            1, 2, 3, 255,
            4, 5, 6, 255,
            7, 8, 9, 255,
            10, 11, 12, 255,
        ])

        header = (
            header_size.to_bytes(4, 'little') +
            height.to_bytes(4, 'little') +
            width.to_bytes(4, 'little') +
            (1).to_bytes(4, 'little') +  # mipmap count
            (0).to_bytes(4, 'little') +  # flags
            len(pixel_data).to_bytes(4, 'little') +
            (32).to_bytes(4, 'little') +  # bit count
            (0x000000FF).to_bytes(4, 'little') +
            (0x0000FF00).to_bytes(4, 'little') +
            (0x00FF0000).to_bytes(4, 'little') +
            (0xFF000000).to_bytes(4, 'little') +
            b'PVR!' +
            (1).to_bytes(4, 'little')
        )

        pvr_payload = header + pixel_data

        decoded = PvrzDecoder.decode_pvrz_bytes(pvr_payload)
        self.assertEqual(decoded.shape, (height, width, 4))
        self.assertTrue(np.array_equal(decoded[0, 0], [1, 2, 3, 255]))
        self.assertTrue(np.array_equal(decoded[1, 1], [10, 11, 12, 255]))

    def test_decode_dxt1_block(self):
        color0 = 0xF800  # red
        color1 = 0x001F  # blue
        block = (
            color0.to_bytes(2, 'little') +
            color1.to_bytes(2, 'little') +
            b'\x00\x00\x00\x00'
        )

        decoded = PvrzDecoder._decode_dxt1(block, 4, 4)
        self.assertEqual(decoded.shape, (4, 4, 4))
        self.assertTrue((decoded[:, :, 3] == 255).all())
        self.assertTrue(np.all(decoded[0, 0, :3] == decoded[0, 1, :3]))
        self.assertTrue(np.any(decoded[:, :, 0] > decoded[:, :, 2]))


    @staticmethod
    def _v2_header(width, height, bit_count, masks, data_size):
        red, green, blue, alpha = masks
        return (
            (52).to_bytes(4, 'little') +
            height.to_bytes(4, 'little') +
            width.to_bytes(4, 'little') +
            (1).to_bytes(4, 'little') +  # mipmap count
            (0).to_bytes(4, 'little') +  # flags
            data_size.to_bytes(4, 'little') +
            bit_count.to_bytes(4, 'little') +
            red.to_bytes(4, 'little') +
            green.to_bytes(4, 'little') +
            blue.to_bytes(4, 'little') +
            alpha.to_bytes(4, 'little') +
            b'PVR!' +
            (1).to_bytes(4, 'little')
        )

    def test_class_has_all_decoder_methods(self):
        # Regression guard for #13: a mis-indented module-level function once
        # ended the class body early and orphaned the methods that followed it.
        for name in (
            'decode_pvrz_bytes', 'decode_pvr_bytes', '_decompress',
            '_parse_header', '_parse_v2_header', '_parse_v3_header',
            '_infer_compression', '_decode_dxt1', '_decode_dxt5',
            '_mask_shift', '_decode_raw_pixels', '_decode_dds',
        ):
            self.assertTrue(hasattr(PvrzDecoder, name), f"PvrzDecoder.{name} is missing")

    def test_mask_shift(self):
        self.assertEqual(PvrzDecoder._mask_shift(0), 0)
        self.assertEqual(PvrzDecoder._mask_shift(0x000000FF), 0)
        self.assertEqual(PvrzDecoder._mask_shift(0x0000FF00), 8)
        self.assertEqual(PvrzDecoder._mask_shift(0xFF000000), 24)

    def test_decode_raw_bgra_masks(self):
        pixel_data = bytes([30, 20, 10, 255])  # B, G, R, A in memory
        header = self._v2_header(
            1, 1, 32, (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000), len(pixel_data)
        )
        decoded = PvrzDecoder.decode_pvr_bytes(header + pixel_data)
        self.assertEqual(decoded.shape, (1, 1, 4))
        self.assertTrue(np.array_equal(decoded[0, 0], [10, 20, 30, 255]))

    def test_decode_raw_custom_masks(self):
        # Channel layout that matches neither fast path, so the generic mask/shift path runs.
        pixel_data = bytes([10, 20, 30, 40])  # little-endian uint32 0x281E140A
        header = self._v2_header(
            1, 1, 32, (0xFF000000, 0x00FF0000, 0x0000FF00, 0x000000FF), len(pixel_data)
        )
        decoded = PvrzDecoder.decode_pvr_bytes(header + pixel_data)
        self.assertTrue(np.array_equal(decoded[0, 0], [40, 30, 20, 10]))

    def test_decode_raw_24_bit(self):
        pixel_data = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        header = self._v2_header(
            2, 2, 24, (0x000000FF, 0x0000FF00, 0x00FF0000, 0), len(pixel_data)
        )
        decoded = PvrzDecoder.decode_pvr_bytes(header + pixel_data)
        self.assertEqual(decoded.shape, (2, 2, 4))
        self.assertTrue(np.array_equal(decoded[0, 0], [1, 2, 3, 255]))
        self.assertTrue(np.array_equal(decoded[1, 1], [10, 11, 12, 255]))

    def test_decode_dds_dxt1(self):
        block = (
            (0xF800).to_bytes(2, 'little') +  # red
            (0x001F).to_bytes(2, 'little') +  # blue
            b'\x00\x00\x00\x00'
        )
        dds_header = bytearray(124)
        dds_header[8:12] = (4).to_bytes(4, 'little')    # height
        dds_header[12:16] = (4).to_bytes(4, 'little')   # width
        dds_header[84:88] = b'DXT1'                     # fourCC (pixel format offset 76 + 8)
        decoded = PvrzDecoder.decode_pvr_bytes(b'DDS ' + bytes(dds_header) + block)
        self.assertEqual(decoded.shape, (4, 4, 4))
        self.assertTrue((decoded[:, :, 3] == 255).all())
        self.assertTrue(np.all(decoded[:, :, 0] > decoded[:, :, 2]))


if __name__ == '__main__':
    unittest.main()
