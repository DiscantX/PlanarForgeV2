import numpy as np
import numba
import struct
import threading
from core.resource import Resource
from .pvrz_decoder import PvrzDecoder

class TisDecoder:
    """
    Handles decoding of Infinity Engine TIS (Tileset) files.
    Supports both classic palette-based TIS and Enhanced Edition PVRZ-based TIS.
    """
    TILE_SIZE = 64
    PALETTE_SIZE = 1024  # 256 * 4 bytes (BGRA)
    PIXEL_COUNT = 4096   # 64 * 64
    PALETTE_TILE_DATA_SIZE = PALETTE_SIZE + PIXEL_COUNT
    PVRZ_TILE_DATA_SIZE = 12
    _MISSING_PAGE = object()
    _CACHE_MISS = object()

    def __init__(self):
        self._page_cache = {}

    def decode_tis(
        self,
        resource: Resource,
        pvrz_page_provider=None,
        grid_width: int = 10,
        tile_indices=None,
        grid_height: int = None,
    ):
        """
        Decodes all tiles in a TIS resource and stitches them into one large NumPy array.
        """
        if resource is None:
            return None

        try:
            grid_width = int(grid_width)
        except (TypeError, ValueError):
            grid_width = 10
        if grid_width <= 0:
            grid_width = 10

        tile_data_size = resource.get("tile_data_block_size")
        tiles_section = resource.get_section("tiles") or []
        source_tile_count = int(resource.get("count_of_tiles") or 0)
        tile_count = source_tile_count
        if tile_count <= 0:
            tile_count = len(tiles_section)
            source_tile_count = tile_count

        mapped_indices = None
        if tile_indices is not None:
            mapped_indices = np.asarray(tile_indices, dtype=np.int32).ravel()
            tile_count = int(mapped_indices.size)

        if tile_count == 0:
            return None

        if grid_height is None:
            grid_height = (tile_count + grid_width - 1) // grid_width
        else:
            try:
                grid_height = int(grid_height)
            except (TypeError, ValueError):
                grid_height = (tile_count + grid_width - 1) // grid_width
            if grid_height <= 0:
                grid_height = (tile_count + grid_width - 1) // grid_width

        canvas_width = grid_width * self.TILE_SIZE
        canvas_height = grid_height * self.TILE_SIZE

        try:
            canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
        except (ValueError, MemoryError):
            return None

        if tile_data_size == self.PALETTE_TILE_DATA_SIZE:
            return self._decode_palette_tis(
                resource,
                tiles_section,
                source_tile_count,
                canvas,
                grid_width,
                mapped_indices=mapped_indices,
            )
        if tile_data_size == self.PVRZ_TILE_DATA_SIZE:
            return self._decode_pvrz_tis(
                resource,
                tiles_section,
                source_tile_count,
                canvas,
                grid_width,
                pvrz_page_provider,
                mapped_indices=mapped_indices,
            )

        return None

    def _decode_palette_tis(self, resource, tiles_section, tile_count, canvas, grid_width, mapped_indices=None):
        """Handles high-performance decoding of indexed TIS files."""
        payload = self._get_tile_payload(
            resource=resource,
            tiles_section=tiles_section,
            tile_count=tile_count,
            tile_data_size=self.PALETTE_TILE_DATA_SIZE,
        )
        if payload is None:
            return canvas

        data = np.frombuffer(payload, dtype=np.uint8)
        max_tiles = data.size // self.PALETTE_TILE_DATA_SIZE
        source_tile_count = min(tile_count, max_tiles)
        if source_tile_count <= 0:
            return canvas

        if mapped_indices is not None:
            self._decode_palette_tiles_mapped_numpy(canvas, data, mapped_indices, source_tile_count, grid_width)
        elif TisDecoder._decode_palette_tiles_numba.signatures:
            self._decode_palette_tiles_numba(canvas, data, source_tile_count, grid_width)
        else:
            self._decode_palette_tiles_numpy(canvas, data, source_tile_count, grid_width)
        return canvas

    @staticmethod
    @numba.njit(cache=True)
    def _decode_palette_tiles_numba(canvas, data, tile_count, grid_width):
        tile_size = 64
        block_size = 5120
        palette_bytes = 1024

        palette = np.zeros((256, 4), dtype=np.uint8)
        for i in range(tile_count):
            offset = i * block_size
            
            # Extract palette (BGRA -> RGBA)
            # Index 0 is hardcoded as transparent per IESDP
            for c in range(256):
                p_off = offset + (c * 4)
                palette[c, 0] = data[p_off + 2] # R
                palette[c, 1] = data[p_off + 1] # G
                palette[c, 2] = data[p_off]     # B
                palette[c, 3] = 255 if c > 0 else 0
            
            # Map indices
            row = i // grid_width
            col = i % grid_width
            y_base = row * tile_size
            x_base = col * tile_size

            for ty in range(tile_size):
                for tx in range(tile_size):
                    pixel_idx = data[offset + palette_bytes + (ty * tile_size) + tx]
                    canvas[y_base + ty, x_base + tx] = palette[pixel_idx]

    @staticmethod
    def _decode_palette_tiles_numpy(canvas, data, tile_count, grid_width):
        tile_size = 64
        block_size = 5120
        palette_bytes = 1024

        for i in range(tile_count):
            offset = i * block_size
            tile = data[offset:offset + block_size]
            if tile.size < block_size:
                break

            bgra = tile[:palette_bytes].reshape((256, 4))
            rgba = np.empty((256, 4), dtype=np.uint8)
            rgba[:, 0] = bgra[:, 2]
            rgba[:, 1] = bgra[:, 1]
            rgba[:, 2] = bgra[:, 0]
            rgba[:, 3] = 255
            rgba[0, 3] = 0

            indices = tile[palette_bytes:palette_bytes + 4096].reshape((tile_size, tile_size))
            row = i // grid_width
            col = i % grid_width
            y_base = row * tile_size
            x_base = col * tile_size
            canvas[y_base:y_base + tile_size, x_base:x_base + tile_size] = rgba[indices]

    @staticmethod
    def _decode_palette_tiles_mapped_numpy(canvas, data, tile_indices, source_tile_count, grid_width):
        tile_size = 64
        block_size = 5120
        palette_bytes = 1024

        for out_i, src_idx in enumerate(tile_indices):
            src_idx = int(src_idx)
            if src_idx < 0 or src_idx >= source_tile_count:
                continue

            offset = src_idx * block_size
            tile = data[offset:offset + block_size]
            if tile.size < block_size:
                continue

            bgra = tile[:palette_bytes].reshape((256, 4))
            rgba = np.empty((256, 4), dtype=np.uint8)
            rgba[:, 0] = bgra[:, 2]
            rgba[:, 1] = bgra[:, 1]
            rgba[:, 2] = bgra[:, 0]
            rgba[:, 3] = 255
            rgba[0, 3] = 0

            indices = tile[palette_bytes:palette_bytes + 4096].reshape((tile_size, tile_size))
            row = out_i // grid_width
            col = out_i % grid_width
            y_base = row * tile_size
            x_base = col * tile_size
            canvas[y_base:y_base + tile_size, x_base:x_base + tile_size] = rgba[indices]

    def _decode_pvrz_tis(self, resource, tiles_section, tile_count, canvas, grid_width, page_provider, mapped_indices=None):
        """Handles PVRZ-based TIS files by cropping blocks from page textures.
        """
        if not page_provider:
            return canvas

        payload = self._get_tile_payload(
            resource=resource,
            tiles_section=tiles_section,
            tile_count=tile_count,
            tile_data_size=self.PVRZ_TILE_DATA_SIZE,
        )
        if payload is None:
            return canvas
        
        # Each tile entry is 12 bytes: page_index, src_x, src_y
        try:
            tile_map = np.frombuffer(payload, dtype="<i4", count=tile_count * 3).reshape((-1, 3))
        except ValueError:
            # Fallback to unpacking in case of malformed payload lengths
            tile_map = []
            for i in range(tile_count):
                offset = i * self.PVRZ_TILE_DATA_SIZE
                raw = payload[offset:offset + self.PVRZ_TILE_DATA_SIZE]
                if len(raw) < self.PVRZ_TILE_DATA_SIZE:
                    break
                tile_map.append(struct.unpack("<iii", raw))

        if mapped_indices is not None:
            source_indices = [int(idx) for idx in mapped_indices if 0 <= int(idx) < len(tile_map)]
        else:
            source_indices = list(range(len(tile_map)))

        cache_scope = (getattr(resource, "game", None), resource.name)
        unique_pages = {
            int(tile_map[src_idx][0])
            for src_idx in source_indices
            if int(tile_map[src_idx][0]) != 0xFFFFFFFF
        }
        page_cache = {}
        for page_idx in unique_pages:
            page_cache[page_idx] = self._get_cached_page(page_idx, page_provider, cache_scope)

        for out_i, src_idx in enumerate(source_indices):
            tile = tile_map[src_idx]
            page_idx = int(tile[0])
            src_x = int(tile[1])
            src_y = int(tile[2])

            # --- DEBUG LOGGING ---
            if out_i < 15: # Log first few tiles for comparison with NearInfinity
                print(f"  [TIS_DEC] Cell {out_i:>3} (src_idx {src_idx:>3}): "
                      f"page={page_idx:>3}, src_x={src_x:>4}, src_y={src_y:>4}")

            # Calculate target grid position
            row = out_i // grid_width
            col = out_i % grid_width
            ty = row * self.TILE_SIZE
            tx = col * self.TILE_SIZE

            # Page index -1 is a solid black tile
            if page_idx == -1:
                canvas[ty:ty+64, tx:tx+64, :3] = 0
                canvas[ty:ty+64, tx:tx+64, 3] = 255
                continue

            page_image = page_cache.get(page_idx)
            if page_image is not None:
                # Extract the 64x64 block from the page and blit to canvas
                block = page_image[src_y:src_y+64, src_x:src_x+64]
                if block.size == 0:
                    continue
                h, w = block.shape[:2]
                canvas[ty:ty+h, tx:tx+w] = block

        return canvas

    def _get_tile_payload(self, resource, tiles_section, tile_count, tile_data_size):
        """
        Returns a contiguous tile payload buffer, preferring raw file bytes to
        avoid concatenating many per-tile byte objects.
        """
        raw_bytes = getattr(resource, "_original_bytes", None)
        offset = resource.get("offset_to_tiles")
        expected = int(tile_count) * int(tile_data_size)
        if (
            isinstance(raw_bytes, (bytes, bytearray, memoryview))
            and isinstance(offset, int)
            and offset >= 0
            and expected > 0
            and offset + expected <= len(raw_bytes)
        ):
            return memoryview(raw_bytes)[offset:offset + expected]

        if not tiles_section:
            return None

        chunks = []
        total = 0
        for entry in tiles_section:
            raw = entry.get("raw_data") if isinstance(entry, dict) else None
            if not raw:
                continue
            chunk = bytes(raw)
            chunks.append(chunk)
            total += len(chunk)
        if total <= 0:
            return None
        return b"".join(chunks)

    def _get_cached_page(self, page_idx, provider, cache_scope):
        cache_key = (cache_scope, int(page_idx))
        cached = self._page_cache.get(cache_key, self._CACHE_MISS)
        if cached is not self._CACHE_MISS:
            return None if cached is self._MISSING_PAGE else cached

        page_bytes = provider(page_idx)
        if page_bytes:
            try:
                img = PvrzDecoder.decode_pvrz_bytes(page_bytes)
            except Exception:
                img = None

            if img is None:
                self._page_cache[cache_key] = self._MISSING_PAGE
                return None

            self._page_cache[cache_key] = img
            return img

        self._page_cache[cache_key] = self._MISSING_PAGE
        return None


def _precompile_tis_numba():
    """Warm the palette decoder JIT in the background to reduce first-load hitching."""
    def compile():
        try:
            canvas = np.zeros((64, 64, 4), dtype=np.uint8)
            data = np.zeros(TisDecoder.PALETTE_TILE_DATA_SIZE, dtype=np.uint8)
            TisDecoder._decode_palette_tiles_numba(canvas, data, 1, 1)
        except Exception:
            pass

    thread = threading.Thread(target=compile, daemon=True)
    thread.start()


_precompile_tis_numba()
