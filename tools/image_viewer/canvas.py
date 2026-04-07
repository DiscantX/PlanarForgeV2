import dearpygui.dearpygui as dpg
import numpy as np

class PFCanvas:
    def __init__(self, app, tag="image_canvas"):
        self.app = app
        self.tag = tag
        self.texture_tag = None
        self.registry_tag = "canvas_texture_registry"
        self.zoom = 1.0
        self.offset = [0.0, 0.0]  # No offset from the corner
        self.current_texture_width = 0
        self.current_texture_height = 0
        self.show_border = True
        self.show_markers = False
        self.alignment = "Pivot"
        self.pivot_x = 0
        self.pivot_y = 0
        
        # Create a single, persistent registry for the canvas
        with dpg.texture_registry(tag=self.registry_tag):
            pass

    def update_texture(self, rgba_buffer: np.ndarray, pivot_x=0, pivot_y=0):
        """Uploads a NumPy RGBA buffer to the GPU."""
        height, width, _ = rgba_buffer.shape
        
        self.pivot_x = pivot_x
        self.pivot_y = pivot_y

        # DPG dynamic textures require a flat float32 list (0.0 to 1.0)
        flat_buffer = (rgba_buffer.astype(np.float32).flatten() / 255.0).tolist()
        
        print(f"DEBUG: Texture update requested. Dimensions: {width}x{height}, Buffer Size: {len(flat_buffer)}")
            
        # --- Step 2: Manage the texture ---
        # If texture exists and dimensions match, just update its value.
        if self.texture_tag and dpg.does_item_exist(self.texture_tag) and \
           self.current_texture_width == width and \
           self.current_texture_height == height:
            dpg.set_value(self.texture_tag, flat_buffer)
            print(f"DEBUG: Existing texture '{self.texture_tag}' updated with dpg.set_value")
        else:
            # Dimensions changed or texture doesn't exist. Use a fresh tag if needed.
            if self.texture_tag and dpg.does_item_exist(self.texture_tag):
                try:
                    dpg.delete_item(self.texture_tag)
                    print(f"DEBUG: Deleted old texture '{self.texture_tag}'")
                except Exception as exc:
                    print(f"DEBUG: Could not delete old texture '{self.texture_tag}': {exc}")

            # Generate a unique integer identifier to prevent tag collisions
            self.texture_tag = dpg.generate_uuid()
            print(f"DEBUG: Creating new dynamic texture with UUID '{self.texture_tag}'")
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
        
        # Get canvas dimensions
        canvas_width = dpg.get_item_width(self.tag)
        canvas_height = dpg.get_item_height(self.tag)
        
        image_width = self.current_texture_width * self.zoom
        image_height = self.current_texture_height * self.zoom
        
        if self.alignment == "Center":
            x1 = (canvas_width - image_width) / 2
            y1 = (canvas_height - image_height) / 2
        elif self.alignment == "Pivot":
            x1 = (canvas_width / 2) - (self.pivot_x * self.zoom)
            y1 = (canvas_height / 2) - (self.pivot_y * self.zoom)
        else:  # Top-Left
            x1, y1 = self.offset[0], self.offset[1]
        
        x2 = x1 + image_width
        y2 = y1 + image_height

        print(f"DEBUG: Redrawing. Zoom={self.zoom:.2f}, Pos=[{x1:.1f}, {y1:.1f}] to [{x2:.1f}, {y2:.1f}]")
        
        # Draw a dark background rectangle to verify the drawlist itself is visible
        dpg.draw_rectangle([-10000, -10000], [10000, 10000], fill=[30, 30, 30, 255], parent=self.tag)

        # Draw the actual image at calculated coordinates directly into the drawlist
        dpg.draw_image(self.texture_tag, [x1, y1], [x2, y2], parent=self.tag)
        
        # Draw red border if enabled
        if self.show_border:
            dpg.draw_rectangle([x1, y1], [x2, y2], color=[255, 0, 0, 255], thickness=2, parent=self.tag)

        if self.show_markers:
            # Marker size (crosshair half-length)
            ms = 15
            
            # 1. Pivot Point (Yellow)
            px = x1 + (self.pivot_x * self.zoom)
            py = y1 + (self.pivot_y * self.zoom)
            dpg.draw_line([px - ms, py], [px + ms, py], color=[255, 255, 0, 200], thickness=1, parent=self.tag)
            dpg.draw_line([px, py - ms], [px, py + ms], color=[255, 255, 0, 200], thickness=1, parent=self.tag)
            dpg.draw_text([px + 4, py + 4], "Pivot", color=[255, 255, 0, 200], size=13, parent=self.tag)

            # 2. Image Center (Cyan)
            cx = x1 + image_width / 2
            cy = y1 + image_height / 2
            dpg.draw_line([cx - ms, cy], [cx + ms, cy], color=[0, 255, 255, 200], thickness=1, parent=self.tag)
            dpg.draw_line([cx, cy - ms], [cx, cy + ms], color=[0, 255, 255, 200], thickness=1, parent=self.tag)
            dpg.draw_text([cx + 4, cy - 18], "Center", color=[0, 255, 255, 200], size=13, parent=self.tag)

            # 3. Image Origin 0,0 (Green)
            dpg.draw_circle([x1, y1], 4, color=[0, 255, 0, 200], fill=[0, 255, 0, 200], parent=self.tag)
            dpg.draw_text([x1 + 4, y1 + 4], "Origin (0,0)", color=[0, 255, 0, 200], size=13, parent=self.tag)

    def set_zoom(self, delta):
        self.zoom = max(0.1, self.zoom + delta)
        self._redraw()
        if hasattr(self.app, 'zoom_slider'):
            dpg.set_value(self.app.zoom_slider, self.zoom)

    def set_zoom_absolute(self, zoom):
        self.zoom = max(0.1, zoom)
        self._redraw()
        if hasattr(self.app, 'zoom_slider'):
            dpg.set_value(self.app.zoom_slider, self.zoom)

    def on_mouse_wheel(self, delta):
        """Handle mouse wheel for zoom."""
        zoom_factor = 0.1  # Adjust as needed
        self.set_zoom(delta * zoom_factor)
