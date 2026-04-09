import numpy as np
from core.resource import Resource
from .pvrz_decoder import PvrzDecoder

class BamDecoder:
    """
    Handles the decompression and pixel mapping for Infinity Engine BAM V1 files.
    Transforms indexed RLE data into NumPy RGBA buffers.
    """
    
    def __init__(self):
        # Persistent cache: { (game_id, pvrz_resref): rgba_buffer }
        self._page_cache = {}

    @staticmethod
    def get_palette(resource: Resource):
        """
        Extracts the palette and identifies the transparency index.
        """
        palette_data = resource.get_section('palette')
        if not palette_data:
            return np.zeros((256, 4), dtype=np.uint8)

        # IE BAM V1 palettes are logically 256 entries.
        # We initialize as opaque (Alpha = 255) and treat the transparent index
        # explicitly by palette convention rather than raw alpha.
        palette = np.zeros((256, 4), dtype=np.uint8)
        palette[:, 3] = 255

        # Fill available colors from the parsed resource (BGRA)
        for i, entry in enumerate(palette_data):
            if i >= 256:
                break
            palette[i, 0:3] = entry['color'][0:3]

        transparent_index = None
        for i in range(min(256, len(palette_data))):
            raw_color = palette_data[i]['color']
            if len(raw_color) >= 3 and raw_color[0] == 0 and raw_color[1] == 255 and raw_color[2] == 0:
                transparent_index = i
                break

        # BGEE and other modern BAMs may store a transparent first palette entry
        # without using the classic green marker. If index 0 has alpha 0 and no
        # explicit green transparency marker exists, treat it as transparent.
        if transparent_index is None and palette_data:
            first_alpha = palette_data[0]['color'][3] if len(palette_data[0]['color']) > 3 else 255
            if first_alpha == 0:
                transparent_index = 0

        if transparent_index is not None:
            palette[transparent_index, 3] = 0
            # Also zero out the RGB channels for the transparent color so GPU interpolation
            # doesn't bleed green artifacts when scaling/zooming
            palette[transparent_index, 0:3] = 0

        rgba_palette = palette[:, [2, 1, 0, 3]]
        
        # DEBUG: Check how many colors are non-transparent
        non_transparent = np.count_nonzero(rgba_palette[:, 3])
        # print(f"DEBUG: Palette extracted. Total colors: {len(rgba_palette)}, Non-transparent: {non_transparent}")
        return rgba_palette

    def decode_frame(self, resource: Resource, frame_index: int, pvrz_page_provider=None):
        """
        Decompresses a specific frame and returns a NumPy RGBA buffer.
        """
        frames = resource.get_section('frame_entries')
        if frame_index >= len(frames):
            return None

        frame = frames[frame_index]
        width = frame['width']
        height = frame['height']
        # print(f"DEBUG: Decoding Frame {frame_index} ({width}x{height})")

        if (resource.schema and resource.schema.name == 'BAM_V2') or ('start_index_data_blocks' in frame):
            return self._decode_v2_frame(resource, frame_index, pvrz_page_provider=pvrz_page_provider)

        # frame_data_info is a bitfield (offset: 31 bits, is_uncompressed: 1 bit)
        info = frame['frame_data_info']
        data_offset = info['offset']
        is_compressed = not bool(info['is_uncompressed'])
        
        # Get raw pixel data from the resource's original byte buffer
        raw_data = resource._original_bytes[data_offset:]
        
        if is_compressed:
            pixel_indices = self._decompress_rle(
                raw_data, 
                width * height, 
                resource.get('rle_compressed_color_index')
            )
        else:
            pixel_indices = np.frombuffer(raw_data, dtype=np.uint8, count=width * height)

        # Map indices to RGBA using the palette
        palette = self.get_palette(resource)
        rgba_pixels = palette[pixel_indices.astype(np.uint32)]
        
        return rgba_pixels.reshape((height, width, 4))

    def _decompress_rle(self, data, expected_size, rle_index):
        """
        Standard BAM V1 RLE decompression.
        Any byte != rle_index represents itself.
        rle_index followed by byte X represents (X+1) copies of rle_index.
        """
        output = bytearray()
        data_ptr = 0
        
        while len(output) < expected_size and data_ptr < len(data):
            byte = data[data_ptr]
            data_ptr += 1
            
            if byte == rle_index:
                if data_ptr < len(data):
                    count = data[data_ptr] + 1
                    data_ptr += 1
                    output.extend([rle_index] * count)
                else:
                    output.append(rle_index)
            else:
                output.append(byte)
                
        return np.frombuffer(output[:expected_size], dtype=np.uint8)

    def _decode_v2_frame(self, resource: Resource, frame_index: int, pvrz_page_provider=None):
        """
        Decode BAM V2 frames from page-based PVRZ data when available.
        If no page provider is supplied, return a transparent placeholder.
        """
        frames = resource.get_section('frame_entries')
        if frame_index >= len(frames):
            return None

        frame = frames[frame_index]
        width = frame['width']
        height = frame['height']
        canvas = np.zeros((height, width, 4), dtype=np.uint8)

        data_blocks = resource.get_section('data_blocks') or []
        start = frame.get('start_index_data_blocks', 0)
        count = frame.get('count_data_blocks', 0)

        print(f"DEBUG: BAM_V2 frame {frame_index}: start={start}, count={count}, total_blocks={len(data_blocks)}")

        if count <= 0 or start < 0 or start >= len(data_blocks):
            print(f"DEBUG: BAM_V2 frame {frame_index} has no data blocks; returning transparent placeholder")
            return canvas

        page_decoder = pvrz_page_provider if pvrz_page_provider is not None else None
        if hasattr(resource, 'pvrz_page_provider') and callable(resource.pvrz_page_provider):
            page_decoder = resource.pvrz_page_provider

        print(f"DEBUG: Page decoder available: {page_decoder is not None}")

        drawn = False
        for i, block in enumerate(data_blocks[start:start + count]):
            page_index = block.get('pvrz_page')
            source_x = block.get('source_x', 0)
            source_y = block.get('source_y', 0)
            block_width = block.get('width', 0)
            block_height = block.get('height', 0)
            target_x = block.get('target_x', 0)
            target_y = block.get('target_y', 0)

            print(f"DEBUG: Block {i}: page={page_index}, src=({source_x},{source_y}), size=({block_width}x{block_height}), target=({target_x},{target_y})")

            if page_decoder is None or page_index is None:
                print(f"DEBUG: Skipping block {i} - decoder={page_decoder is not None}, page_index={page_index}")
                continue

            # Use a cache key that accounts for the game context
            game_id = getattr(resource, 'game', 'unknown')
            cache_key = (game_id, page_index)

            if cache_key in self._page_cache:
                page_image = self._page_cache[cache_key]
            else:
                page_bytes = page_decoder(page_index)
                if page_bytes is None:
                    print(f"DEBUG: Page decoder returned None for page {page_index}")
                    continue

                try:
                    page_image = PvrzDecoder.decode_pvrz_bytes(page_bytes)
                    self._page_cache[cache_key] = page_image
                    print(f"DEBUG: Decoded PVRZ page {page_index}, shape: {page_image.shape}")
                except Exception as exc:
                    print(f"DEBUG: Failed to decode PVRZ page {page_index} for BAM_V2 frame {frame_index}: {exc}")
                    continue

            block_image = page_image[
                source_y:source_y + block_height,
                source_x:source_x + block_width,
            ]

            if block_image.size == 0:
                print(f"DEBUG: Block image size is 0")
                continue

            target_end_y = min(target_y + block_image.shape[0], height)
            target_end_x = min(target_x + block_image.shape[1], width)
            canvas[target_y:target_end_y, target_x:target_end_x] = block_image[: target_end_y - target_y, : target_end_x - target_x]
            drawn = True
            print(f"DEBUG: Drew block {i} to canvas")

        if not drawn:
            print(f"DEBUG: BAM_V2 frame {frame_index} could not resolve any PVRZ page blocks; returning transparent placeholder")

        return canvas

    def get_cycle_frames(self, resource: Resource, cycle_index: int):
        """
        Helper to resolve frame indices for a specific animation cycle.
        """
        cycles = resource.get_section('cycle_entries')
        if not cycles or cycle_index >= len(cycles):
            return []
            
        cycle = cycles[cycle_index]
        
        if resource.schema and resource.schema.name == 'BAM_V2':
            # BAM V2 cycles point directly to a range of frame entries
            start = cycle.get('start_index_frame_entries', 0)
            count = cycle.get('count_of_frame_entries', 0)
            return [i for i in range(start, start + count)]
        else:
            # BAM V1 uses a lookup table
            lookup = resource.get_section('frame_lookup_table')
            if not lookup: return []
            
            start = cycle.get('index_into_lookup_table', 0)
            count = cycle.get('count_of_frame_indices', 0)
            return [lookup[i]['frame_index'] for i in range(start, start + count) if i < len(lookup)]