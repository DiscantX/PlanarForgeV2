"""
core/formats/pvrz.py

Parser for PVRZ files used by Infinity Engine Enhanced Edition games.

PVRZ files are zlib-compressed PVR3 texture containers.  EE games use
DXT5 (BC3) compressed textures — not PVRTC as older documentation suggests.

PVR3 header layout (52 bytes, little-endian):
    0x00  uint32  version        = 0x03525650  ("PVR\\x03")
    0x04  uint32  flags
    0x08  uint32  pixel_fmt_lo   11 = DXT5/BC3
    0x0C  uint32  pixel_fmt_hi   0  (unused for pre-defined formats)
    0x10  uint32  color_space    0 = linear RGB
    0x14  uint32  channel_type   0 = unsigned byte normalised
    0x18  uint32  height         texture height in pixels
    0x1C  uint32  width          texture width in pixels
    0x20  uint32  depth          1
    0x24  uint32  num_surfaces   1
    0x28  uint32  num_faces      1
    0x2C  uint32  mip_count      1
    0x30  uint32  metadata_size  bytes of metadata that follow the header

Pixel data starts at offset 52 + metadata_size.

DXT5 / BC3 decoding:
    Each 4×4 pixel block is 16 bytes:
      - 2 bytes alpha endpoints (a0, a1)
      - 6 bytes alpha index table (48 bits → 16 × 3-bit indices)
      - 4 bytes colour endpoints (c0, c1) in RGB565
      - 4 bytes colour index table (16 × 2-bit indices)

IESDP reference:
    https://gibberlings3.github.io/iesdp/file_formats/ie_formats/pvrz.htm
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# PVR3 constants
# ---------------------------------------------------------------------------

PVR3_MAGIC     = 0x03525650   # "PVR\x03" little-endian
PVR3_HDR_SIZE  = 52           # fixed header size in bytes
FMT_DXT1       = 7
FMT_DXT3       = 9
FMT_DXT5       = 11           # BC3 — used by all EE PVRZ files


# ---------------------------------------------------------------------------
# PvrzFile
# ---------------------------------------------------------------------------

class PvrzFile:
    """
    A decompressed PVRZ texture page (PVR3 + DXT5).

    Construct via :meth:`from_bytes` (compressed) or
    :meth:`from_decompressed` (already zlib-decompressed).
    """

    def __init__(
        self,
        width:       int,
        height:      int,
        pixel_fmt:   int,
        pixel_data:  bytes,
        source_path: Optional[Path] = None,
    ) -> None:
        self.width       = width
        self.height      = height
        self.pixel_fmt   = pixel_fmt
        self.pixel_data  = pixel_data
        self.source_path = source_path
        self._rgba_cache: Optional[bytes] = None  # Lazy decode cache

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_bytes(cls, data: bytes, source_path: Optional[Path] = None) -> "PvrzFile":
        """Decompress a raw PVRZ blob and parse it.

        PVRZ resources stored in KEY/BIFF archives have a 4-byte prefix
        before the zlib stream, so offset 4 is tried first.
        """
        for offset in (4, 0):
            if offset >= len(data):
                continue
            try:
                decompressed = zlib.decompress(data[offset:])
                return cls.from_decompressed(decompressed, source_path)
            except (zlib.error, ValueError):
                continue
        raise ValueError("Failed to decompress PVRZ data at offset 4 or 0")

    @classmethod
    def from_decompressed(cls, data: bytes, source_path: Optional[Path] = None) -> "PvrzFile":
        """Parse decompressed PVR3 data."""
        if len(data) < PVR3_HDR_SIZE:
            raise ValueError(
                f"Decompressed PVRZ too short: {len(data)} bytes (need {PVR3_HDR_SIZE})"
            )

        (version, flags, fmt_lo, fmt_hi,
         color_space, channel_type,
         height, width,
         depth, num_surfaces, num_faces, mip_count,
         metadata_size) = struct.unpack_from("<13I", data, 0)

        if version != PVR3_MAGIC:
            raise ValueError(f"Invalid PVR3 magic: 0x{version:08x} (expected 0x{PVR3_MAGIC:08x})")

        pixel_fmt = fmt_lo   # fmt_hi is 0 for all pre-defined formats

        pixel_data_offset = PVR3_HDR_SIZE + metadata_size
        pixel_data = data[pixel_data_offset:]

        return cls(
            width=width,
            height=height,
            pixel_fmt=pixel_fmt,
            pixel_data=pixel_data,
            source_path=source_path,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "PvrzFile":
        path = Path(path)
        return cls.from_bytes(path.read_bytes(), source_path=path)

    # ------------------------------------------------------------------
    # Pixel decoding
    # ------------------------------------------------------------------

    def to_rgba(self) -> Optional[bytes]:
        """Decode the full texture to a flat RGBA byte array (cached after first call)."""
        if self._rgba_cache is not None:
            return self._rgba_cache
        
        if self.pixel_fmt == FMT_DXT5:
            result = _decode_dxt5(self.pixel_data, self.width, self.height)
        elif self.pixel_fmt == FMT_DXT1:
            result = _decode_dxt1(self.pixel_data, self.width, self.height)
        else:
            # DXT3 and others: unsupported
            result = None
        
        if result is not None:
            self._rgba_cache = result
        return result

    def get_region_rgba(
        self, x: int, y: int, width: int, height: int
    ) -> Optional[bytes]:
        """
        Extract a rectangular region as RGBA bytes.

        Decodes the full texture once and copies the requested rectangle.
        """
        if width <= 0 or height <= 0:
            return None

        full = self.to_rgba()
        if full is None:
            return None

        out = bytearray(width * height * 4)
        tw  = self.width
        th  = self.height

        for row in range(height):
            sy = y + row
            if sy >= th:
                break
            for col in range(width):
                sx = x + col
                if sx >= tw:
                    break
                src = (sy * tw + sx) * 4
                dst = (row * width + col) * 4
                out[dst:dst + 4] = full[src:src + 4]

        return bytes(out)


# ---------------------------------------------------------------------------
# DXT5 / BC3 decoder
# ---------------------------------------------------------------------------

def _decode_dxt5(data: bytes, width: int, height: int) -> Optional[bytes]:
    """
    Decode DXT5 (BC3) compressed texture to RGBA.

    Each 4×4 block is 16 bytes:
      bytes  0-1:  alpha endpoints a0, a1
      bytes  2-7:  alpha indices (48 bits, 16 × 3 bits, little-endian)
      bytes  8-11: colour endpoints c0, c1 (RGB565)
      bytes 12-15: colour indices  (32 bits, 16 × 2 bits, little-endian)
    """
    try:
        bw = (width  + 3) // 4   # blocks wide
        bh = (height + 3) // 4   # blocks tall
        expected = bw * bh * 16

        if len(data) < expected:
            return None

        out = bytearray(width * height * 4)

        for by in range(bh):
            for bx in range(bw):
                off = (by * bw + bx) * 16

                # --- Alpha block ---
                a0 = data[off]
                a1 = data[off + 1]

                # 48-bit alpha index table packed into 6 bytes
                idx_bits = int.from_bytes(data[off + 2: off + 8], "little")

                if a0 > a1:
                    alpha_table = [
                        a0, a1,
                        (6 * a0 + 1 * a1) // 7,
                        (5 * a0 + 2 * a1) // 7,
                        (4 * a0 + 3 * a1) // 7,
                        (3 * a0 + 4 * a1) // 7,
                        (2 * a0 + 5 * a1) // 7,
                        (1 * a0 + 6 * a1) // 7,
                    ]
                else:
                    alpha_table = [
                        a0, a1,
                        (4 * a0 + 1 * a1) // 5,
                        (3 * a0 + 2 * a1) // 5,
                        (2 * a0 + 3 * a1) // 5,
                        (1 * a0 + 4 * a1) // 5,
                        0, 255,
                    ]

                # --- Colour block ---
                c0_raw, c1_raw, cidx = struct.unpack_from("<HHI", data, off + 8)

                r0, g0, b0 = _rgb565(c0_raw)
                r1, g1, b1 = _rgb565(c1_raw)

                if c0_raw > c1_raw:
                    colour_table = [
                        (r0, g0, b0),
                        (r1, g1, b1),
                        ((2*r0 + r1) // 3, (2*g0 + g1) // 3, (2*b0 + b1) // 3),
                        ((r0 + 2*r1) // 3, (g0 + 2*g1) // 3, (b0 + 2*b1) // 3),
                    ]
                else:
                    colour_table = [
                        (r0, g0, b0),
                        (r1, g1, b1),
                        ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2),
                        (0, 0, 0),
                    ]

                # Write 4×4 pixels
                for py in range(4):
                    for px in range(4):
                        dx = bx * 4 + px
                        dy = by * 4 + py
                        if dx >= width or dy >= height:
                            continue

                        pixel_i = py * 4 + px

                        ai = (idx_bits >> (pixel_i * 3)) & 0x7
                        ci = (cidx    >> (pixel_i * 2)) & 0x3

                        r, g, b = colour_table[ci]
                        a       = alpha_table[ai]

                        dst = (dy * width + dx) * 4
                        out[dst]     = r
                        out[dst + 1] = g
                        out[dst + 2] = b
                        out[dst + 3] = a

        return bytes(out)

    except Exception:
        return None


def _decode_dxt1(data: bytes, width: int, height: int) -> Optional[bytes]:
    """
    Decode DXT1 (BC1) compressed texture to RGBA.

    Each 4×4 block is 8 bytes:
      bytes 0-1: colour endpoint c0 (RGB565)
      bytes 2-3: colour endpoint c1 (RGB565)
      bytes 4-7: colour indices (16 × 2 bits, little-endian)
    """
    try:
        bw = (width  + 3) // 4
        bh = (height + 3) // 4
        expected = bw * bh * 8

        if len(data) < expected:
            return None

        out = bytearray(width * height * 4)

        for by in range(bh):
            for bx in range(bw):
                off = (by * bw + bx) * 8
                c0_raw, c1_raw, cidx = struct.unpack_from("<HHI", data, off)

                r0, g0, b0 = _rgb565(c0_raw)
                r1, g1, b1 = _rgb565(c1_raw)

                if c0_raw > c1_raw:
                    colour_table = [
                        (r0, g0, b0, 255),
                        (r1, g1, b1, 255),
                        ((2*r0 + r1) // 3, (2*g0 + g1) // 3, (2*b0 + b1) // 3, 255),
                        ((r0 + 2*r1) // 3, (g0 + 2*g1) // 3, (b0 + 2*b1) // 3, 255),
                    ]
                else:
                    colour_table = [
                        (r0, g0, b0, 255),
                        (r1, g1, b1, 255),
                        ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
                        (0, 0, 0, 0),   # transparent black
                    ]

                for py in range(4):
                    for px in range(4):
                        dx = bx * 4 + px
                        dy = by * 4 + py
                        if dx >= width or dy >= height:
                            continue

                        ci = (cidx >> ((py * 4 + px) * 2)) & 0x3
                        r, g, b, a = colour_table[ci]

                        dst = (dy * width + dx) * 4
                        out[dst]     = r
                        out[dst + 1] = g
                        out[dst + 2] = b
                        out[dst + 3] = a

        return bytes(out)

    except Exception:
        return None


def _rgb565(raw: int) -> tuple[int, int, int]:
    """Unpack a 16-bit RGB565 value to (r, g, b) in 0-255 range."""
    r = ((raw >> 11) & 0x1F) * 255 // 31
    g = ((raw >>  5) & 0x3F) * 255 // 63
    b = ( raw        & 0x1F) * 255 // 31
    return r, g, b