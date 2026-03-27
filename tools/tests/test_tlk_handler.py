import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from drivers.InfinityEngine.io.tlk_handler import TlkHandler


class TestTlkHandler(unittest.TestCase):
    def _build_tlk(self, entries, string_data):
        header_size = TlkHandler.HEADER_SIZE
        entry_size = TlkHandler.ENTRY_SIZE
        entry_count = len(entries)
        string_offset_base = header_size + (entry_count * entry_size)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name
            tmp.write(struct.pack("<4s4sHII", b"TLK ", b"V1  ", 0, entry_count, string_offset_base))
            for offset, length in entries:
                tmp.write(struct.pack("<H8sIIII", 0, b"\x00" * 8, 0, 0, offset, length))
            tmp.write(string_data)

        return path

    def test_detects_relative_offsets_even_when_offset_exceeds_string_block_base(self):
        string_data = bytearray(b"\x00" * 200)
        string_data[0:5] = b"Hello"
        string_data[80:85] = b"World"
        path = self._build_tlk(
            entries=[
                (0, 5),
                (80, 5),
            ],
            string_data=bytes(string_data),
        )

        try:
            handler = TlkHandler(path)
            self.assertEqual(handler.offset_mode, "relative")
            self.assertEqual(handler.get_string(0), "Hello")
            self.assertEqual(handler.get_string(1), "World")
        finally:
            os.unlink(path)

    def test_detects_absolute_offsets(self):
        header_size = TlkHandler.HEADER_SIZE
        entry_size = TlkHandler.ENTRY_SIZE
        string_offset_base = header_size + (2 * entry_size)
        string_data = bytearray(b"\x00" * 40)
        string_data[0:5] = b"Alpha"
        string_data[10:15] = b"Beta!"
        path = self._build_tlk(
            entries=[
                (string_offset_base, 5),
                (string_offset_base + 10, 5),
            ],
            string_data=bytes(string_data),
        )

        try:
            handler = TlkHandler(path)
            self.assertEqual(handler.offset_mode, "absolute")
            self.assertEqual(handler.get_string(0), "Alpha")
            self.assertEqual(handler.get_string(1), "Beta!")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
