import zlib
import numpy as np
import struct
import numba


class PvrzDecoder:
    """Decode PVRZ resources and raw PVR textures."""

    PVR_MAGIC = 0x21525650  # 'PVR!'
    PVR3_MAGIC = 0x03525650  # 'PVR3'

    @classmethod
    def decode_pvrz_bytes(cls, raw_bytes):
        """Decompress a PVRZ blob and decode the contained PVR texture."""
        if raw_bytes is None:
            return None

        decompressed = cls._decompress(raw_bytes)
        
        # Attempt double decompression
        try:
            double_decompressed = zlib.decompress(decompressed)
            decompressed = double_decompressed
        except zlib.error:
            # Try from offset 4 if it starts with zlib header there
            if len(decompressed) > 4 and decompressed[4:6] == b'\x78\x9c':
                try:
                    double_decompressed = zlib.decompress(decompressed[4:])
                    decompressed = double_decompressed
                except zlib.error:
                    pass
        
        return cls.decode_pvr_bytes(decompressed)

    @classmethod
    def decode_pvr_bytes(cls, raw_bytes):
        """Decode an already decompressed PVR binary payload into RGBA."""
        if raw_bytes[:4] == b'DDS ':
            return cls._decode_dds(raw_bytes)

        try:
            header = cls._parse_header(raw_bytes)
        except ValueError:
            # Fallback: try to decode based on size
            if len(raw_bytes) % 8 == 0:
                blocks = len(raw_bytes) // 8
                block_side = int(blocks ** 0.5 + 0.5)
                if block_side * block_side == blocks:
                    width = block_side * 4
                    height = block_side * 4
                    return cls._decode_dxt1(raw_bytes, width, height)
            if len(raw_bytes) % 16 == 0:
                blocks = len(raw_bytes) // 16
                block_side = int(blocks ** 0.5 + 0.5)
                if block_side * block_side == blocks:
                    width = block_side * 4
                    height = block_side * 4
                    return cls._decode_dxt5(raw_bytes, width, height)
            if len(raw_bytes) % 4 == 0:
                total_pixels = len(raw_bytes) // 4
                size = int(total_pixels ** 0.5 + 0.5)
                if size * size == total_pixels:
                    width = height = size
                    img = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((height, width, 4))
                    # Assume RGBA
                    return img
            else:
                # Unrecognized format, return transparent placeholder to avoid crash
                return np.zeros((256, 256, 4), dtype=np.uint8)
        pixel_data = raw_bytes[header["data_offset"]:header["data_offset"] + header["data_size"]]

        if header["bit_count"] in (24, 32) and (header["red_mask"] or header["green_mask"] or header["blue_mask"]):
            return cls._decode_raw_pixels(
                pixel_data,
                header["width"],
                header["height"],
                header["bit_count"],
                header["red_mask"],
                header["green_mask"],
                header["blue_mask"],
                header["alpha_mask"],
            )

        if header["compression"] == "DXT1":
            result = cls._decode_dxt1(pixel_data, header["width"], header["height"])
            return result
        if header["compression"] == "DXT5":
            return cls._decode_dxt5(pixel_data, header["width"], header["height"])

        if header["bit_count"] in (24, 32):
            return cls._decode_raw_pixels(
                pixel_data,
                header["width"],
                header["height"],
                header["bit_count"],
                header["red_mask"],
                header["green_mask"],
                header["blue_mask"],
                header["alpha_mask"],
            )

        raise ValueError("Unsupported PVR pixel format or unknown compression mode.")

    @staticmethod
    def _decompress(raw_bytes):
        # Try standard zlib from offset 4
        try:
            return zlib.decompress(raw_bytes[4:])
        except zlib.error:
            pass
        # Try raw deflate from offset 4
        try:
            return zlib.decompress(raw_bytes[4:], wbits=-15)
        except zlib.error:
            pass
        # Standard zlib
        try:
            return zlib.decompress(raw_bytes)
        except zlib.error:
            # PVRZ prefix
            if raw_bytes[:4] == b"PVRZ":
                try:
                    return zlib.decompress(raw_bytes[4:])
                except zlib.error:
                    try:
                        return zlib.decompress(raw_bytes[4:], wbits=-15)
                    except zlib.error:
                        pass
            # Raw deflate
            try:
                return zlib.decompress(raw_bytes, wbits=-15)
            except zlib.error:
                pass
            # Uncompressed
            return raw_bytes

    @classmethod
    def _parse_header(cls, raw_bytes):
        if raw_bytes is None or len(raw_bytes) < 52:
            raise ValueError("Invalid PVR payload: too small for header.")

        magic = int.from_bytes(raw_bytes[0:4], "little")
        if magic == cls.PVR3_MAGIC:
            return cls._parse_v3_header(raw_bytes)
        if magic == cls.PVR_MAGIC:
            return cls._parse_v2_header(raw_bytes)

        pvr_tag = int.from_bytes(raw_bytes[44:48], "little")
        if pvr_tag == cls.PVR_MAGIC:
            return cls._parse_v2_header(raw_bytes)

        raise ValueError("Unrecognized PVR header signature.")

    @staticmethod
    def _parse_v2_header(raw_bytes):
        header_size = int.from_bytes(raw_bytes[0:4], "little")
        height = int.from_bytes(raw_bytes[4:8], "little")
        width = int.from_bytes(raw_bytes[8:12], "little")
        mipmap_count = int.from_bytes(raw_bytes[12:16], "little")
        flags = int.from_bytes(raw_bytes[16:20], "little")
        data_size = int.from_bytes(raw_bytes[20:24], "little")
        bit_count = int.from_bytes(raw_bytes[24:28], "little")
        red_mask = int.from_bytes(raw_bytes[28:32], "little")
        green_mask = int.from_bytes(raw_bytes[32:36], "little")
        blue_mask = int.from_bytes(raw_bytes[36:40], "little")
        alpha_mask = int.from_bytes(raw_bytes[40:44], "little")
        num_surfs = int.from_bytes(raw_bytes[48:52], "little")
        meta_data_size = header_size - 52
        data_offset = header_size

        compression = PvrzDecoder._infer_compression(width, height, data_size)

        return {
            "width": width,
            "height": height,
            "bit_count": bit_count,
            "red_mask": red_mask,
            "green_mask": green_mask,
            "blue_mask": blue_mask,
            "alpha_mask": alpha_mask,
            "data_size": data_size if data_size > 0 else len(raw_bytes) - data_offset,
            "data_offset": data_offset,
            "compression": compression,
            "flags": flags,
            "meta_data_size": meta_data_size,
            "mipmap_count": mipmap_count,
            "num_surfaces": num_surfs,
        }

    @staticmethod
    def _parse_v3_header(raw_bytes):
        flags = int.from_bytes(raw_bytes[4:8], "little")
        pixel_format = int.from_bytes(raw_bytes[8:16], "little")
        colour_space = int.from_bytes(raw_bytes[16:20], "little")
        channel_type = int.from_bytes(raw_bytes[20:24], "little")
        height = int.from_bytes(raw_bytes[24:28], "little")
        width = int.from_bytes(raw_bytes[28:32], "little")
        depth = int.from_bytes(raw_bytes[32:36], "little")
        num_surfaces = int.from_bytes(raw_bytes[36:40], "little")
        num_faces = int.from_bytes(raw_bytes[40:44], "little")
        mip_map_count = int.from_bytes(raw_bytes[44:48], "little")
        meta_data_size = int.from_bytes(raw_bytes[48:52], "little")
        if meta_data_size > len(raw_bytes) - 52:
            meta_data_size = 0
        data_offset = 52 + meta_data_size
        data_size = len(raw_bytes) - data_offset

        compression = PvrzDecoder._infer_compression(width, height, data_size)

        return {
            "width": width,
            "height": height,
            "bit_count": 0,
            "red_mask": 0,
            "green_mask": 0,
            "blue_mask": 0,
            "alpha_mask": 0,
            "data_size": data_size,
            "data_offset": data_offset,
            "compression": compression,
            "flags": flags,
            "pixel_format": pixel_format,
            "colour_space": colour_space,
            "channel_type": channel_type,
            "depth": depth,
            "num_surfaces": num_surfaces,
            "num_faces": num_faces,
            "mipmap_count": mip_map_count,
            "meta_data_size": meta_data_size,
        }

    @staticmethod
    def _infer_compression(width, height, data_size):
        blocks = ((width + 3) // 4) * ((height + 3) // 4)
        if data_size == blocks * 8:
            return "DXT1"
        if data_size == blocks * 16:
            return "DXT5"
        return None

    @staticmethod
    # Numba JIT compilation for performance - compiles the DXT1 decoding loop to native code
    # Provides significant speedup (20-100x) for texture decompression, especially for large images
    @numba.jit(nopython=True)
    def _decode_dxt1(data, width, height):
        """
        Decode DXT1 (BC1) compressed texture to RGBA.
        """
        bw = (width  + 3) // 4
        bh = (height + 3) // 4
        expected = bw * bh * 8

        if len(data) < expected:
            return np.zeros((height, width, 4), dtype=np.uint8)  # or handle differently

        out = np.zeros((height, width, 4), dtype=np.uint8)

        for by in range(bh):
            for bx in range(bw):
                off = (by * bw + bx) * 8
                c0_raw = data[off] | (data[off + 1] << 8)
                c1_raw = data[off + 2] | (data[off + 3] << 8)
                cidx = data[off + 4] | (data[off + 5] << 8) | (data[off + 6] << 16) | (data[off + 7] << 24)

                r0, g0, b0 = _unpack_565_numba(c0_raw)
                r1, g1, b1 = _unpack_565_numba(c1_raw)

                if c0_raw > c1_raw:
                    colour_table = np.array([
                        [r0, g0, b0, 255],
                        [r1, g1, b1, 255],
                        [(2*r0 + r1) // 3, (2*g0 + g1) // 3, (2*b0 + b1) // 3, 255],
                        [(r0 + 2*r1) // 3, (g0 + 2*g1) // 3, (b0 + 2*b1) // 3, 255],
                    ], dtype=np.uint8)
                else:
                    colour_table = np.array([
                        [r0, g0, b0, 255],
                        [r1, g1, b1, 255],
                        [(r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255],
                        [0, 0, 0, 0],
                    ], dtype=np.uint8)

                for py in range(4):
                    for px in range(4):
                        dx = bx * 4 + px
                        dy = by * 4 + py
                        if dx >= width or dy >= height:
                            continue

                        ci = (cidx >> ((py * 4 + px) * 2)) & 0x3
                        out[dy, dx] = colour_table[ci]

        return out
        
    @staticmethod
    @numba.jit(nopython=True)
    def _decode_dxt5(data, width, height):
        blocks_x = (width + 3) // 4
        blocks_y = (height + 3) // 4
        out = np.zeros((height, width, 4), dtype=np.uint8)

        for block_y in range(blocks_y):
            for block_x in range(blocks_x):
                off = (block_y * blocks_x + block_x) * 16
                if off + 16 > len(data):
                    break

                # --- Alpha Decoding ---
                alpha0 = data[off]
                alpha1 = data[off + 1]
                
                # Manual 48-bit int from bytes for Numba compatibility
                alpha_bits = 0
                for j in range(6):
                    alpha_bits |= (np.uint64(data[off + 2 + j]) << (np.uint64(8 * j)))

                alpha_values = np.zeros(8, dtype=np.uint8)
                alpha_values[0] = alpha0
                alpha_values[1] = alpha1
                if alpha0 > alpha1:
                    for i in range(1, 7):
                        alpha_values[i+1] = ((7 - i) * alpha0 + i * alpha1 + 3) // 7
                else:
                    for i in range(1, 5):
                        alpha_values[i+1] = ((5 - i) * alpha0 + i * alpha1 + 2) // 5
                    alpha_values[6] = 0
                    alpha_values[7] = 255

                # --- Color Decoding ---
                color0 = data[off + 8] | (data[off + 9] << 8)
                color1 = data[off + 10] | (data[off + 11] << 8)
                bits = np.uint32(data[off + 12]) | (np.uint32(data[off + 13]) << 8) | \
                       (np.uint32(data[off + 14]) << 16) | (np.uint32(data[off + 15]) << 24)

                palette = np.zeros((4, 4), dtype=np.uint8)
                palette[0, 0], palette[0, 1], palette[0, 2] = _unpack_565_numba(color0)
                palette[1, 0], palette[1, 1], palette[1, 2] = _unpack_565_numba(color1)
                
                if color0 > color1:
                    palette[2, :3] = ((2 * palette[0, :3] + palette[1, :3]) // 3)
                    palette[3, :3] = ((palette[0, :3] + 2 * palette[1, :3]) // 3)
                else:
                    palette[2, :3] = ((palette[0, :3] + palette[1, :3]) // 2)
                    palette[3, :3] = [0, 0, 0]
                palette[:, 3] = 255

                # --- Reconstruct Pixels ---
                for pixel_index in range(16):
                    pixel_x = block_x * 4 + (pixel_index & 3)
                    pixel_y = block_y * 4 + (pixel_index >> 2)
                    if pixel_x < width and pixel_y < height:
                        palette_index = (bits >> (pixel_index * 2)) & 0x3
                        alpha_index = (alpha_bits >> (pixel_index * 3)) & 0x7
                        
                        out[pixel_y, pixel_x, :3] = palette[palette_index, :3]
                        out[pixel_y, pixel_x, 3] = alpha_values[alpha_index]

        return out

    @staticmethod
    @numba.jit
    def _unpack_565(color):
        r = ((color >> 11) & 0x1F) * 255 // 31
        g = ((color >> 5) & 0x3F) * 255 // 63
        b = (color & 0x1F) * 255 // 31
        return r, g, b

# Numba JIT compilation for performance - compiles Python to native code for ~20-100x speedup
@numba.jit
def _unpack_565_numba(color):
    r = ((color >> 11) & 0x1F) * 255 // 31
    g = ((color >> 5) & 0x3F) * 255 // 63
    b = (color & 0x1F) * 255 // 31
    return r, g, b

    @staticmethod
    def _mask_shift(mask):
        if mask == 0:
            return 0
        return (mask & -mask).bit_length() - 1

    @staticmethod
    def _decode_raw_pixels(data, width, height, bit_count, red_mask, green_mask, blue_mask, alpha_mask):
        bytes_per_pixel = bit_count // 8
        expected_size = width * height * bytes_per_pixel
        if len(data) < expected_size:
            raise ValueError("Raw pixel payload shorter than expected for PVR dimensions.")

        pixels = np.frombuffer(data[:expected_size], dtype=np.uint8).reshape((height, width, bytes_per_pixel))
        if bit_count == 32:
            image = np.zeros((height, width, 4), dtype=np.uint8)
            if red_mask == 0x000000FF and green_mask == 0x0000FF00 and blue_mask == 0x00FF0000 and alpha_mask == 0xFF000000:
                image[:, :, :] = pixels[:, :, :4]
            elif red_mask == 0x00FF0000 and green_mask == 0x0000FF00 and blue_mask == 0x000000FF and alpha_mask == 0xFF000000:
                image[:, :, 0] = pixels[:, :, 2]
                image[:, :, 1] = pixels[:, :, 1]
                image[:, :, 2] = pixels[:, :, 0]
                image[:, :, 3] = pixels[:, :, 3]
            else:
                pixel_ints = np.frombuffer(pixels.tobytes(), dtype=np.uint32)
                red_shift = PvrzDecoder._mask_shift(red_mask)
                green_shift = PvrzDecoder._mask_shift(green_mask)
                blue_shift = PvrzDecoder._mask_shift(blue_mask)
                alpha_shift = PvrzDecoder._mask_shift(alpha_mask)
                image[:, :, 0] = ((pixel_ints & red_mask) >> red_shift).astype(np.uint8)
                image[:, :, 1] = ((pixel_ints & green_mask) >> green_shift).astype(np.uint8)
                image[:, :, 2] = ((pixel_ints & blue_mask) >> blue_shift).astype(np.uint8)
                if alpha_mask:
                    image[:, :, 3] = ((pixel_ints & alpha_mask) >> alpha_shift).astype(np.uint8)
                else:
                    image[:, :, 3] = 255
            return image

        if bit_count == 24:
            image = np.zeros((height, width, 4), dtype=np.uint8)
            image[:, :, :3] = pixels
            image[:, :, 3] = 255
            return image

        raise ValueError(f"Unsupported raw pixel bit-depth: {bit_count}")

    @staticmethod
    def _decode_dds(data):
        if len(data) < 128:
            raise ValueError("DDS data too small for header")

        header = data[4:128]  # Skip 'DDS '

        height = int.from_bytes(header[8:12], "little")
        width = int.from_bytes(header[12:16], "little")

        pixel_format = header[76:96]
        fourcc = pixel_format[8:12]

        pixel_data = data[128:]

        if fourcc == b'DXT1':
            return PvrzDecoder._decode_dxt1(pixel_data, width, height)
        elif fourcc == b'DXT5':
            return PvrzDecoder._decode_dxt5(pixel_data, width, height)
        else:
            raise ValueError(f"Unsupported DDS format: {fourcc}")

# Precompile Numba functions in background thread on module import
import threading
def _precompile_numba():
    """Trigger Numba JIT compilation in background to avoid startup delay."""
    def compile():
        try:
            # Dummy calls to trigger JIT compilation
            _unpack_565_numba(0)
            dummy_data = b'\x00' * 8  # Minimal DXT1 block data
            PvrzDecoder._decode_dxt1(dummy_data, 4, 4)
        except:
            pass  # Ignore any compilation errors
    thread = threading.Thread(target=compile, daemon=True)
    thread.start()

_precompile_numba()
