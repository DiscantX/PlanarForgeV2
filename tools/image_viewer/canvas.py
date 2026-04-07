import dearpygui.dearpygui as dpg
import numpy as np

class PFCanvas:
    def __init__(self, tag="image_canvas"):
        self.tag = tag
        self.texture_tag = "active_texture"
        self.draw_node_tag = "canvas_draw_node"
        self.zoom = 1.0
        self.offset = [0, 0]
        self.current_texture_width = 0
        self.current_texture_height = 0

    def update_texture(self, rgba_buffer: np.ndarray):
        """Uploads a NumPy RGBA buffer to the GPU."""
        height, width, _ = rgba_buffer.shape
        
        # DPG dynamic textures require a flat float32 list (0.0 to 1.0)
        flat_buffer = rgba_buffer.astype(np.float32).flatten() / 255.0
        
        # --- Step 1: Always delete the draw node FIRST to release any texture references ---
        # This is crucial to ensure the texture is no longer in use before we try to delete it.
        if dpg.does_item_exist(self.draw_node_tag):
            dpg.delete_item(self.draw_node_tag)
            
        # --- Step 2: Manage the texture ---
        # If texture exists and dimensions match, just update its value.
        if dpg.does_item_exist(self.texture_tag) and \
           self.current_texture_width == width and \
           self.current_texture_height == height:
            dpg.set_value(self.texture_tag, flat_buffer)
        else:
            # Dimensions changed or texture doesn't exist, delete old and create new
            # Now that the draw_node is gone, this delete_item should be more reliable.
            if dpg.does_item_exist(self.texture_tag):
                dpg.delete_item(self.texture_tag) 

            with dpg.texture_registry():
                dpg.add_dynamic_texture(width=width, height=height, default_value=flat_buffer, tag=self.texture_tag)
            self.current_texture_width = width
            self.current_texture_height = height
        
        # --- Step 3: Recreate the draw node to display the (new or updated) texture ---
        with dpg.draw_node(parent=self.tag, tag=self.draw_node_tag):
            dpg.draw_image(self.texture_tag, [0, 0], [width, height])

    def apply_transform(self):
        """Apply zoom and pan to the draw node."""
        if dpg.does_item_exist(self.draw_node_tag):
            # Basic scale only to avoid matrix multiplication issues
            dpg.apply_transform(self.draw_node_tag, dpg.create_scale_matrix([self.zoom, self.zoom]))

    def set_zoom(self, delta):
        self.zoom = max(0.1, self.zoom + delta)
        self.apply_transform()
