"""Decoder for Infinity Engine PVRZ texture pages.

A PVRZ file is a 4-byte little-endian uncompressed size followed by one zlib
stream holding a PVR v3 file: a 52-byte header, optional metadata, then the
texture data (PVR File Format Specification 3.0.0; IESDP "PVRZ file format").
Desktop Enhanced Edition pages are DXT1 (BC1) or DXT5 (BC3). A scan of every
PVRZ page in BG2EE and IWDEE (tools/pvrz_scan.py, issue #54) found no other
layout, header version, pixel format, mip count or metadata, so nothing else is
decoded here. Anything else raises ``PvrzError``.
"""
import logging
import struct
import threading
import zlib

import numba
import numpy as np

logger = logging.getLogger(__name__)

PVR3_MAGIC = 0x03525650
PVR3_HEADER_SIZE = 52
PIXEL_FORMAT_DXT1 = 7
PIXEL_FORMAT_DXT5 = 11
_BLOCK_BYTES = {PIXEL_FORMAT_DXT1: 8, PIXEL_FORMAT_DXT5: 16}
# version, flags, pixel format, colour space, channel type, height, width,
# depth, surfaces, faces, mip count, metadata size
_PVR3_HEADER = struct.Struct("<IIQ9I")


class PvrzError(ValueError):
    """Raised when a PVRZ or PVR payload is corrupt or not in a supported layout."""


@numba.njit
def _expand_565(value):
    """Expands a packed RGB565 value to 8-bit ``(r, g, b)``."""
    return ((value >> 11) & 0x1F) * 255 // 31, ((value >> 5) & 0x3F) * 255 // 63, (value & 0x1F) * 255 // 31


@numba.njit
def _fill_colour_table(data, offset, four_colour_only, table):
    """Fills ``table`` (4x4 uint8, RGBA) from the 8-byte colour block at ``offset``.

    Args:
        data: Block-compressed bytes as a uint8 array.
        offset: Start of the colour block.
        four_colour_only: True for the colour block of DXT5, which always
            interpolates two colours; False for DXT1, where ``c0 <= c1``
            selects three colours plus transparent black.
        table: Output array, filled in place.
    """
    c0 = np.int64(data[offset]) | (np.int64(data[offset + 1]) << 8)
    c1 = np.int64(data[offset + 2]) | (np.int64(data[offset + 3]) << 8)
    r0, g0, b0 = _expand_565(c0)
    r1, g1, b1 = _expand_565(c1)
    table[0, 0], table[0, 1], table[0, 2], table[0, 3] = r0, g0, b0, 255
    table[1, 0], table[1, 1], table[1, 2], table[1, 3] = r1, g1, b1, 255
    if c0 > c1 or four_colour_only:
        table[2, 0], table[2, 1], table[2, 2], table[2, 3] = (2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255
        table[3, 0], table[3, 1], table[3, 2], table[3, 3] = (r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255
    else:
        table[2, 0], table[2, 1], table[2, 2], table[2, 3] = (r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255
        table[3, 0], table[3, 1], table[3, 2], table[3, 3] = 0, 0, 0, 0


@numba.njit
def _read_u32(data, offset):
    """Reads a little-endian uint32 from a uint8 array."""
    return (np.int64(data[offset]) | (np.int64(data[offset + 1]) << 8)
            | (np.int64(data[offset + 2]) << 16) | (np.int64(data[offset + 3]) << 24))


@numba.njit
def _decode_dxt1(data, width, height):
    """Decodes DXT1 (BC1) blocks to an ``(height, width, 4)`` RGBA uint8 array.

    ``data`` must hold every block; the caller checks its length.
    """
    blocks_x, blocks_y = (width + 3) // 4, (height + 3) // 4
    out = np.zeros((height, width, 4), dtype=np.uint8)
    table = np.zeros((4, 4), dtype=np.uint8)
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            offset = (block_y * blocks_x + block_x) * 8
            _fill_colour_table(data, offset, False, table)
            indices = _read_u32(data, offset + 4)
            for row in range(min(4, height - block_y * 4)):
                for col in range(min(4, width - block_x * 4)):
                    out[block_y * 4 + row, block_x * 4 + col, :] = table[(indices >> ((row * 4 + col) * 2)) & 3, :]
    return out


@numba.njit
def _decode_dxt5(data, width, height):
    """Decodes DXT5 (BC3) blocks to an ``(height, width, 4)`` RGBA uint8 array.

    ``data`` must hold every block; the caller checks its length.
    """
    blocks_x, blocks_y = (width + 3) // 4, (height + 3) // 4
    out = np.zeros((height, width, 4), dtype=np.uint8)
    table = np.zeros((4, 4), dtype=np.uint8)
    alphas = np.zeros(8, dtype=np.int64)
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            offset = (block_y * blocks_x + block_x) * 16
            alpha0, alpha1 = np.int64(data[offset]), np.int64(data[offset + 1])
            alphas[0], alphas[1] = alpha0, alpha1
            if alpha0 > alpha1:
                for i in range(1, 7):
                    alphas[i + 1] = ((7 - i) * alpha0 + i * alpha1 + 3) // 7
            else:
                for i in range(1, 5):
                    alphas[i + 1] = ((5 - i) * alpha0 + i * alpha1 + 2) // 5
                alphas[6], alphas[7] = 0, 255
            alpha_bits = np.int64(0)
            for j in range(6):
                alpha_bits |= np.int64(data[offset + 2 + j]) << (8 * j)
            _fill_colour_table(data, offset + 8, True, table)
            indices = _read_u32(data, offset + 12)
            for row in range(min(4, height - block_y * 4)):
                for col in range(min(4, width - block_x * 4)):
                    pixel = row * 4 + col
                    y, x = block_y * 4 + row, block_x * 4 + col
                    out[y, x, :3] = table[(indices >> (pixel * 2)) & 3, :3]
                    out[y, x, 3] = alphas[(alpha_bits >> (pixel * 3)) & 7]
    return out


class PvrzDecoder:
    """Decodes PVRZ pages (and bare PVR v3 payloads) to RGBA arrays."""

    @classmethod
    def decode_pvrz_bytes(cls, raw_bytes):
        """Decompresses a PVRZ file and decodes the texture inside it.

        Args:
            raw_bytes: The PVRZ file contents.

        Returns:
            A ``(height, width, 4)`` uint8 RGBA array.

        Raises:
            PvrzError: If the data is not a valid PVRZ file in a supported layout.
        """
        return cls.decode_pvr_bytes(cls._decompress(raw_bytes))

    @classmethod
    def decode_pvr_bytes(cls, pvr_bytes):
        """Decodes a decompressed PVR v3 payload (DXT1 or DXT5 only).

        Only the top mip level is decoded; the PVR 3.0.0 layout stores it first.

        Args:
            pvr_bytes: The PVR file contents.

        Returns:
            A ``(height, width, 4)`` uint8 RGBA array.

        Raises:
            PvrzError: If the header is invalid, the pixel format is not DXT1
                or DXT5, or the texture data is shorter than the top level.
        """
        width, height, pixel_format, data_offset = cls._parse_header(pvr_bytes)
        needed = ((width + 3) // 4) * ((height + 3) // 4) * _BLOCK_BYTES[pixel_format]
        if len(pvr_bytes) - data_offset < needed:
            raise PvrzError("Texture data is %d bytes; a %dx%d top level needs %d."
                            % (len(pvr_bytes) - data_offset, width, height, needed))
        data = np.frombuffer(pvr_bytes, dtype=np.uint8, count=needed, offset=data_offset)
        decode = _decode_dxt1 if pixel_format == PIXEL_FORMAT_DXT1 else _decode_dxt5
        return decode(data, width, height)

    @staticmethod
    def _decompress(raw_bytes):
        """Returns the PVR payload of a PVRZ file (size prefix, then one zlib stream)."""
        if raw_bytes is None or len(raw_bytes) < 5:
            raise PvrzError("PVRZ data is too small.")
        expected = struct.unpack_from("<I", raw_bytes, 0)[0]
        stream = zlib.decompressobj()
        try:
            data = stream.decompress(memoryview(raw_bytes)[4:])
        except zlib.error as exc:
            raise PvrzError("PVRZ zlib stream is corrupt: %s" % exc) from exc
        if not stream.eof:
            raise PvrzError("PVRZ zlib stream is truncated.")
        if len(data) != expected:
            raise PvrzError("PVRZ size field says %d bytes but the stream holds %d." % (expected, len(data)))
        return data

    @staticmethod
    def _parse_header(pvr_bytes):
        """Validates a PVR v3 header.

        Returns:
            ``(width, height, pixel_format, texture_data_offset)``.

        Raises:
            PvrzError: If the header is too small, has the wrong version, an
                unsupported pixel format, or a metadata size past the end.
        """
        if len(pvr_bytes) < PVR3_HEADER_SIZE:
            raise PvrzError("PVR data is %d bytes, smaller than its 52-byte header." % len(pvr_bytes))
        (version, _flags, pixel_format, _colour_space, _channel_type, height, width,
         _depth, _surfaces, _faces, _mips, metadata_size) = _PVR3_HEADER.unpack_from(pvr_bytes, 0)
        if version != PVR3_MAGIC:
            raise PvrzError("Not a PVR v3 header (version field 0x%08X)." % version)
        if pixel_format not in _BLOCK_BYTES:
            raise PvrzError("Unsupported PVR pixel format %d; only DXT1 (7) and DXT5 (11) are supported." % pixel_format)
        data_offset = PVR3_HEADER_SIZE + metadata_size
        if data_offset > len(pvr_bytes):
            raise PvrzError("PVR metadata size %d runs past the end of the data." % metadata_size)
        if width == 0 or height == 0:
            raise PvrzError("PVR texture has a zero dimension (%dx%d)." % (width, height))
        return width, height, pixel_format, data_offset


def _warm_up():
    """Compiles both decode kernels so the first real page does not pay for it."""
    try:
        # frombuffer on bytes gives the read-only array real pages use, so the
        # compiled signature matches.
        block = np.frombuffer(bytes(16), dtype=np.uint8)
        _decode_dxt1(block[:8], 4, 4)
        _decode_dxt5(block, 4, 4)
    except Exception:
        logger.warning("Numba warm-up failed; kernels will compile on first use.", exc_info=True)


threading.Thread(target=_warm_up, daemon=True).start()
