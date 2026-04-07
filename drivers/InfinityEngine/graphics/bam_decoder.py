import numpy as np
from core.resource import Resource

class BamDecoder:
    """
    Handles the decompression and pixel mapping for Infinity Engine BAM V1 files.
    Transforms indexed RLE data into NumPy RGBA buffers.
    """

    @staticmethod
    def get_palette(resource: Resource):
        """
        Extracts the palette and identifies the transparency index.
        """
        palette_data = resource.get_section('palette')
        if not palette_data:
            return np.zeros((256, 4), dtype=np.uint8)

        # IE BAM V1 palettes are logically 256 entries. 
        # We pre-allocate to ensure we never have an IndexError during mapping.
        palette = np.zeros((256, 4), dtype=np.uint8)
        
        # Fill available colors from the parsed resource (BGRA)
        for i, entry in enumerate(palette_data):
            if i >= 256: break
            palette[i] = entry['color']

        # IE Transparency: First occurrence of (0, 255, 0) is transparent.
        # We set its Alpha channel to 0.
        for i in range(min(256, len(palette_data))):
            if palette[i, 0] == 0 and palette[i, 1] == 255 and palette[i, 2] == 0:
                palette[i, 3] = 0
                break
        
        # Special case: Alpha is often only used in EE. 
        # Standard BAMs usually have 0 in the alpha channel which means opaque in modern RGBA.
        # We ensure opaque if alpha wasn't explicitly set by transparency or EE rules.
        # However, for now we stick to the 0,255,0 rule.
        
        # Convert BGRA to RGBA for modern GPU compatibility
        return palette[:, [2, 1, 0, 3]]

    def decode_frame(self, resource: Resource, frame_index: int):
        """
        Decompresses a specific frame and returns a NumPy RGBA buffer.
        """
        frames = resource.get_section('frame_entries')
        if frame_index >= len(frames):
            return None

        frame = frames[frame_index]
        width = frame['width']
        height = frame['height']
        
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

    def get_cycle_frames(self, resource: Resource, cycle_index: int):
        """
        Helper to resolve frame indices for a specific animation cycle.
        """
        cycles = resource.get_section('cycle_entries')
        lookup = resource.get_section('frame_lookup_table')
        if cycle_index >= len(cycles):
            return []
            
        cycle = cycles[cycle_index]
        start = cycle['index_into_lookup_table']
        count = cycle['count_of_frame_indices']
        
        return [lookup[i]['frame_index'] for i in range(start, start + count)]