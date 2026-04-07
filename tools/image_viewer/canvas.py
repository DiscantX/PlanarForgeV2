import dearpygui.dearpygui as dpg
import numpy as np

class PFCanvas:
    def __init__(self, tag="image_canvas"):
        self.tag = tag
        self.texture_base_tag = "active_texture"
        self.texture_id = 0
        self.texture_tag = f"{self.texture_base_tag}_{self.texture_id}"
        self.registry_tag = "canvas_texture_registry"
        self.zoom = 1.0
        self.offset = [20.0, 20.0]  # Start with a 2D offset from the corner
        self.current_texture_width = 0
        self.current_texture_height = 0
        
        # Create a single, persistent registry for the canvas
        with dpg.texture_registry(tag=self.registry_tag):
            pass

    def update_texture(self, rgba_buffer: np.ndarray):
        """Uploads a NumPy RGBA buffer to the GPU."""
        height, width, _ = rgba_buffer.shape
        
        # DPG dynamic textures require a flat float32 list (0.0 to 1.0)
        flat_buffer = (rgba_buffer.astype(np.float32).flatten() / 255.0).tolist()
        
        print(f"DEBUG: Texture update requested. Dimensions: {width}x{height}, Buffer Size: {len(flat_buffer)}")
            
        # --- Step 2: Manage the texture ---
        # If texture exists and dimensions match, just update its value.
        if dpg.does_item_exist(self.texture_tag) and \
           self.current_texture_width == width and \
           self.current_texture_height == height:
            dpg.set_value(self.texture_tag, flat_buffer)
            print(f"DEBUG: Existing texture '{self.texture_tag}' updated with dpg.set_value")
        else:
            # Dimensions changed or texture doesn't exist. Use a fresh tag if needed.
            if dpg.does_item_exist(self.texture_tag):
                try:
                    dpg.delete_item(self.texture_tag)
                    print(f"DEBUG: Deleted old texture '{self.texture_tag}'")
                except Exception as exc:
                    print(f"DEBUG: Could not delete old texture '{self.texture_tag}': {exc}")

            self.texture_id += 1
            self.texture_tag = f"{self.texture_base_tag}_{self.texture_id}"
            print(f"DEBUG: Creating new dynamic texture '{self.texture_tag}'")
            dpg.add_dynamic_texture(width=width, height=height, default_value=flat_buffer, tag=self.texture_tag, parent=self.registry_tag)
            self.current_texture_width = width
            self.current_texture_height = height
        
        # --- Step 3: Trigger a redraw with new dimensions ---
        self._redraw()

    def _redraw(self):
        """Calculates coordinates manually and draws to the node, avoiding apply_transform."""
        if not dpg.does_item_exist(self.texture_tag):
            return

        # Clear the entire drawlist to ensure a clean state for the new frame
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag, children_only=True)
        
        # Calculate visual boundaries manually to avoid matrix-related system freezes
        x1, y1 = self.offset[0], self.offset[1]
        x2 = x1 + self.current_texture_width * self.zoom
        y2 = y1 + self.current_texture_height * self.zoom

        print(f"DEBUG: Redrawing. Zoom={self.zoom:.2f}, Pos=[{x1:.1f}, {y1:.1f}] to [{x2:.1f}, {y2:.1f}]")
        
        # Draw a dark background rectangle to verify the drawlist itself is visible
        dpg.draw_rectangle([-10000, -10000], [10000, 10000], fill=[30, 30, 30, 255], parent=self.tag)

        # Draw the actual image at calculated coordinates directly into the drawlist
        dpg.draw_image(self.texture_tag, [x1, y1], [x2, y2], parent=self.tag)
        
        # DIAGNOSTIC: Keep the red border test
        dpg.draw_rectangle([x1, y1], [x2, y2], color=[255, 0, 0, 255], thickness=2, parent=self.tag)

    def set_zoom(self, delta):
        self.zoom = max(0.1, self.zoom + delta)
        self._redraw()
