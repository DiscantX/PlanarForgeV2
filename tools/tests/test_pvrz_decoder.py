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


if __name__ == '__main__':
    unittest.main()
