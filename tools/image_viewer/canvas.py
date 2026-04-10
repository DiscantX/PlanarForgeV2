import dearpygui.dearpygui as dpg
import numpy as np

class PFCanvas:
    def __init__(self, app, tag="image_canvas"):
        self.app = app
        self.tag = tag
        self.texture_tag = None
        self.image_item = dpg.generate_uuid()
        self.border_item = dpg.generate_uuid()
        self.bg_item = dpg.generate_uuid()
        self.marker_node = dpg.generate_uuid()

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

        # Optimization: Pass the NumPy array directly to DPG to avoid expensive .tolist() conversion
        flat_buffer = rgba_buffer.ravel().astype(np.float32) / 255.0
            
        # --- Step 2: Manage the texture ---
        old_texture = None

        # If texture exists and dimensions match, just update its value.
        if self.texture_tag and dpg.does_item_exist(self.texture_tag) and \
           self.current_texture_width == width and \
           self.current_texture_height == height:
            dpg.set_value(self.texture_tag, flat_buffer)
        else:
            # Dimensions changed or texture doesn't exist. Prepare to swap.
            if self.texture_tag and dpg.does_item_exist(self.texture_tag):
                old_texture = self.texture_tag

            self.texture_tag = dpg.generate_uuid()
            dpg.add_dynamic_texture(width=width, height=height, default_value=flat_buffer, tag=self.texture_tag, parent=self.registry_tag)
            self.current_texture_width = width
            self.current_texture_height = height
        
        # --- Step 3: Trigger a redraw with new dimensions ---
        self._redraw()

        # --- Step 4: Cleanup old texture after the new one is visible ---
        if old_texture:
            dpg.delete_item(old_texture)

    def _redraw(self):
        """Calculates coordinates manually and draws to the node, avoiding apply_transform."""
        if not self.texture_tag or not dpg.does_item_exist(self.texture_tag):
            return
        
        # Get canvas dimensions
        canvas_width = dpg.get_item_width(self.tag)
        canvas_height = dpg.get_item_height(self.tag)
        
        image_width = self.current_texture_width * self.zoom
        image_height = self.current_texture_height * self.zoom
        
        if self.alignment == "Center":
            bx = (canvas_width - image_width) / 2
            by = (canvas_height - image_height) / 2
        elif self.alignment == "Pivot":
            bx = (canvas_width / 2) - (self.pivot_x * self.zoom)
            by = (canvas_height / 2) - (self.pivot_y * self.zoom)
        elif self.alignment == "Top-Center":
            bx = (canvas_width - image_width) / 2
            by = 0
        elif self.alignment == "Left-Center":
            bx = 0
            by = (canvas_height - image_height) / 2
        elif self.alignment == "Right-Center":
            bx = canvas_width - image_width
            by = (canvas_height - image_height) / 2
        elif self.alignment == "Top-Right":
            bx = canvas_width - image_width
            by = 0
        elif self.alignment == "Bottom-Center":
            bx = (canvas_width - image_width) / 2
            by = canvas_height - image_height
        elif self.alignment == "Bottom-Right":
            bx = canvas_width - image_width
            by = canvas_height - image_height
        else:  # Top-Left and fallback
            bx, by = 0, 0
        
        x1, y1 = bx + self.offset[0], by + self.offset[1]
        x2, y2 = x1 + image_width, y1 + image_height

        # --- Step 1: Ensure persistent items exist ---
        if not dpg.does_item_exist(self.bg_item):
            dpg.draw_rectangle([-10000, -10000], [10000, 10000], fill=[30, 30, 30, 255], tag=self.bg_item, parent=self.tag)
        
        if not dpg.does_item_exist(self.image_item):
            dpg.draw_image(self.texture_tag, [x1, y1], [x2, y2], tag=self.image_item, parent=self.tag)
        else:
            dpg.configure_item(self.image_item, texture_tag=self.texture_tag, pmin=[x1, y1], pmax=[x2, y2])

        if not dpg.does_item_exist(self.border_item):
            dpg.draw_rectangle([x1, y1], [x2, y2], color=[255, 0, 0, 255], thickness=2, tag=self.border_item, parent=self.tag)
        
        # --- Step 2: Update Visibility & Coordinates ---
        dpg.configure_item(self.border_item, pmin=[x1, y1], pmax=[x2, y2], show=self.show_border)

        # --- Step 3: Markers (Draw Node approach to avoid flickering markers) ---
        if not dpg.does_item_exist(self.marker_node):
            dpg.add_draw_node(tag=self.marker_node, parent=self.tag)
        
        dpg.delete_item(self.marker_node, children_only=True)

        if self.show_markers:
            # Marker size (crosshair half-length)
            ms = 15
            
            # 1. Pivot Point (Yellow)
            px = x1 + (self.pivot_x * self.zoom)
            py = y1 + (self.pivot_y * self.zoom)
            dpg.draw_line([px - ms, py], [px + ms, py], color=[255, 255, 0, 200], thickness=1, parent=self.marker_node)
            dpg.draw_line([px, py - ms], [px, py + ms], color=[255, 255, 0, 200], thickness=1, parent=self.marker_node)
            dpg.draw_text([px + 4, py + 4], "Pivot", color=[255, 255, 0, 200], size=13, parent=self.marker_node)

            # 2. Image Center (Cyan)
            cx = x1 + image_width / 2
            cy = y1 + image_height / 2
            dpg.draw_line([cx - ms, cy], [cx + ms, cy], color=[0, 255, 255, 200], thickness=1, parent=self.marker_node)
            dpg.draw_line([cx, cy - ms], [cx, cy + ms], color=[0, 255, 255, 200], thickness=1, parent=self.marker_node)
            dpg.draw_text([cx + 4, cy - 18], "Center", color=[0, 255, 255, 200], size=13, parent=self.marker_node)

            # 3. Image Origin 0,0 (Green)
            dpg.draw_circle([x1, y1], 4, color=[0, 255, 0, 200], fill=[0, 255, 0, 200], parent=self.marker_node)
            dpg.draw_text([x1 + 4, y1 + 4], "Origin (0,0)", color=[0, 255, 0, 200], size=13, parent=self.marker_node)

    def clear_texture(self):
        """Clears the canvas by showing a transparent placeholder and hiding image/border."""
        # Create a small transparent texture
        transparent_buffer = np.zeros((1, 1, 4), dtype=np.uint8)
        self.update_texture(transparent_buffer, pivot_x=0, pivot_y=0)
        # Optionally, hide the image item and border
        if dpg.does_item_exist(self.image_item):
            dpg.hide_item(self.image_item)
        if dpg.does_item_exist(self.border_item):
            dpg.hide_item(self.border_item)
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
