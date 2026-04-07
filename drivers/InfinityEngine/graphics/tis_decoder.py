import numpy as np
from core.resource import Resource
from .bam_decoder import BamDecoder

class TisDecoder:
    """
    Handles decoding of Infinity Engine TIS (Tileset) files.
    Stitches 64x64 blocks into a single large texture for verification.
    """
    TILE_SIZE = 64

    def decode_tis(self, resource: Resource, palette_resource: Resource = None, grid_width: int = 10):
        """
        Decodes all tiles in a TIS resource and stitches them into one large NumPy array.
        """
        # TIS V1 tiles are 4096 bytes of indexed data (64x64)
        raw_data = resource._original_bytes[24:] # Skip header (Signature, Version, Count, BlockSize, etc.)
        tile_count = len(raw_data) // 4096
        
        if tile_count == 0:
            return None

        # Calculate dimensions for the "One Big Texture"
        grid_height = (tile_count + grid_width - 1) // grid_width
        canvas_width = grid_width * self.TILE_SIZE
        canvas_height = grid_height * self.TILE_SIZE

        # Initialize empty RGBA canvas
        canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
        
        # Get palette (TIS usually relies on an external palette or one from a companion BAM/WED)
        # For the standalone viewer, we'll fallback to a grayscale palette if none is provided
        if palette_resource:
            palette = BamDecoder.get_palette(palette_resource)
        else:
            # Create a basic grayscale palette for debugging
            palette = np.zeros((256, 4), dtype=np.uint8)
            for i in range(256):
                palette[i] = [i, i, i, 255]

        for i in range(tile_count):
            start = i * 4096
            end = start + 4096
            tile_indices = np.frombuffer(raw_data[start:end], dtype=np.uint8)
            tile_rgba = palette[tile_indices].reshape((self.TILE_SIZE, self.TILE_SIZE, 4))
            
            # Calculate grid position
            row = i // grid_width
            col = i % grid_width
            
            y_start = row * self.TILE_SIZE
            x_start = col * self.TILE_SIZE
            
            canvas[y_start:y_start+self.TILE_SIZE, x_start:x_start+self.TILE_SIZE] = tile_rgba

        return canvas