import sys
import time
from pathlib import Path
import numpy as np

# Add the project root to sys.path so 'drivers' and 'core' can be found when running standalone
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import dearpygui.dearpygui as dpg
from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.graphics.bam_decoder import BamDecoder
from drivers.InfinityEngine.graphics.pvrz_decoder import PvrzDecoder
from drivers.InfinityEngine.graphics.tis_decoder import TisDecoder
from canvas import PFCanvas

class ImageViewerApp:
    def __init__(self):
        self.loader = ResourceLoader()
        self.bam_decoder = BamDecoder()
        self.pvrz_decoder = PvrzDecoder()
        self.tis_decoder = TisDecoder()
        
        self.current_resource = None
        self.current_resref = None
        self.filtered_resrefs = []
        self.selectable_tags = {}  # resref -> tag
        self.last_selected_tag = None
        self.current_cycle = 0
        self.current_frame_idx = 0  # Index within the current cycle's frame list
        self.is_playing = False
        self.last_frame_time = 0
        self.pan_start_offset = [0.0, 0.0]
        self.is_panning = False
        self.all_resrefs = []
        
        dpg.create_context()
        self.canvas = PFCanvas(app=self)
        self._setup_ui()

        dpg.create_viewport(title="PlanarForgeV2 - Image Viewer", width=1200, height=800)

        self._refresh_resource_list()

        dpg.set_viewport_resize_callback(self._on_viewport_resize)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.maximize_viewport()
        self._on_viewport_resize()

    def _setup_ui(self):
        with dpg.window(label="Controls", tag="controls_window", width=300, height=700, no_close=True):
            # Game Selection
            found_games = [g.game_id for g in self.loader.install_finder.find_all()]
            self.game_input = dpg.add_combo(
                label="Game", 
                items=found_games, 
                default_value=self.loader.default_game,
                callback=self._refresh_resource_list
            )

            self.restype_input = dpg.add_combo(
                label="Type", 
                items=["BAM", "TIS", "PVRZ"], 
                default_value="BAM",
                callback=self._refresh_resource_list
            )

            dpg.add_separator()
            dpg.add_text("Resource Browser")
            self.filter_input = dpg.add_input_text(label="Filter", callback=self._filter_list)
            with dpg.child_window(tag="resource_list_container", height=300):
                self.resource_list_layout = dpg.add_group(tag="resource_list_layout")

            self.resref_input = dpg.add_input_text(label="ResRef", default_value="GMISC01", readonly=True)

            # Metadata info
            dpg.add_separator()
            self.info_text = dpg.add_text("No resource loaded")
            
            dpg.add_separator()
            self.zoom_slider = dpg.add_slider_float(label="Zoom", min_value=0.1, max_value=10.0, default_value=1.0, 
                                callback=lambda s, v: self.canvas.set_zoom_absolute(v))
            
            dpg.add_combo(label="Alignment", items=["Pivot", "Center", "Top-Left", "Top-Center", "Top-Right", "Left-Center", "Right-Center", "Bottom-Left", "Bottom-Center", "Bottom-Right"], default_value="Pivot",
                         callback=lambda s, v: setattr(self.canvas, 'alignment', v) or self.canvas._redraw())
            
            dpg.add_checkbox(label="Show Border", default_value=True, 
                            callback=lambda s, v: setattr(self.canvas, 'show_border', v) or self.canvas._redraw())
            
            dpg.add_checkbox(label="Show Markers", default_value=True,
                            callback=lambda s, v: setattr(self.canvas, 'show_markers', v) or self.canvas._redraw())

            dpg.add_button(label="Reset View", callback=self._reset_view)

        with dpg.window(label="Canvas", tag="canvas_window", pos=[305, 0], width=895, height=800, no_scrollbar=True):
            dpg.add_drawlist(tag="image_canvas", width=875, height=760)
            with dpg.handler_registry():
                dpg.add_mouse_wheel_handler(callback=self._on_mouse_wheel)
                dpg.add_key_press_handler(callback=self._on_key_press)
                dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_down)
                dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_drag)
                dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_release)

        # Bottom Panel for BAM Controls
        with dpg.window(tag="bottom_window", show=False, no_title_bar=True, no_move=True, no_resize=True, no_scrollbar=True):
            with dpg.group(horizontal=True, horizontal_spacing=60):
                # Animation Controls
                with dpg.group():
                    dpg.add_text("Playback")
                    with dpg.group(horizontal=True):
                        self.play_button = dpg.add_button(label="Play", width=80, callback=self._toggle_animation)
                        self.fps_input = dpg.add_input_int(label="FPS", default_value=10, width=80)  
                
                # Cycle Controls
                with dpg.group():
                    dpg.add_text("Cycle")
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="<<", callback=lambda: self._change_cycle(absolute=0))
                        dpg.add_button(label="<", callback=lambda: self._change_cycle(delta=-1))
                        self.cycle_text = dpg.add_text("Cycle 0 of 0")
                        dpg.add_button(label=">", callback=lambda: self._change_cycle(delta=1))
                        dpg.add_button(label=">>", callback=lambda: self._change_cycle(absolute=999))
                
                # Frame Controls
                with dpg.group():
                    dpg.add_text("Frame")
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="<<", callback=lambda: self._change_frame(absolute=0))
                        dpg.add_button(label="<", callback=lambda: self._change_frame(delta=-1))
                        self.frame_text = dpg.add_text("Frame 0 of 0")
                        dpg.add_button(label=">", callback=lambda: self._change_frame(delta=1))
                        dpg.add_button(label=">>", callback=lambda: self._change_frame(absolute=999))
                    self.frame_info_text = dpg.add_text("")
                
                #Toggles
                with dpg.group():
                    self.autoplay_toggle = dpg.add_checkbox(label="Autoplay", default_value=True)    
                    self.filter_empty_frames = dpg.add_checkbox(label="Filter empty frames", default_value=True, callback=self._on_filter_toggle)
                    self.preserve_frame_toggle = dpg.add_checkbox(label="Preserve frame number", default_value=True)
                    
    def _on_viewport_resize(self):
        """Update UI layout when the main window resizes."""
        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()
        cw = 300 # Fixed width for controls
        bh = 120 if dpg.is_item_shown("bottom_window") else 0
        
        dpg.configure_item("controls_window", height=vh)
        
        if dpg.does_item_exist("canvas_window"):
            # Adjust canvas window to fill remaining width and account for bottom panel
            dpg.configure_item("canvas_window", pos=[cw + 5, 0], width=vw - cw - 20, height=vh - bh)
            dpg.configure_item("image_canvas", width=vw - cw - 40, height=vh - bh - 40)
            
        if dpg.does_item_exist("bottom_window"):
            dpg.configure_item("bottom_window", pos=[cw + 5, vh - bh], width=vw - cw - 20, height=bh)
        
        if hasattr(self, 'canvas'):
            self.canvas._redraw()

    def _on_mouse_down(self, sender, app_data):
        """Capture initial offset when middle mouse starts dragging."""
        if not self.is_panning and dpg.is_item_hovered("image_canvas"):
            self.pan_start_offset = list(self.canvas.offset)
            self.is_panning = True

    def _on_mouse_drag(self, sender, app_data):
        """Update canvas offset based on mouse displacement."""
        if self.is_panning:
            self.canvas.offset[0] = self.pan_start_offset[0] + app_data[1]
            self.canvas.offset[1] = self.pan_start_offset[1] + app_data[2]
            self.canvas._redraw()

    def _on_mouse_release(self, sender, app_data):
        """Stop panning state."""
        self.is_panning = False

    def _on_mouse_wheel(self, sender, app_data):
        if dpg.is_item_hovered("image_canvas"):
            self.canvas.on_mouse_wheel(app_data)

    def _reset_view(self):
        """Resets the canvas zoom and pan offset to defaults."""
        self.canvas.offset = [0.0, 0.0]
        self.canvas.set_zoom_absolute(1.0)

    def _on_key_press(self, sender, app_data):
        """Handle keyboard navigation based on hover context."""
        # Determine if we should navigate the BAM (hovering canvas or playback bar)
        is_hovering_view = dpg.is_item_hovered("image_canvas") or dpg.is_item_hovered("bottom_window")

        if is_hovering_view and self.current_resource:
            if app_data == dpg.mvKey_Left:
                self._change_frame(delta=-1)
            elif app_data == dpg.mvKey_Right:
                self._change_frame(delta=1)
            elif app_data == dpg.mvKey_Up:
                self._change_cycle(delta=-1)
            elif app_data == dpg.mvKey_Down:
                self._change_cycle(delta=1)
            elif app_data == dpg.mvKey_Spacebar:
                self._toggle_animation()
            return # Intercepted; don't trigger list navigation

        if not self.filtered_resrefs:
            return
        
        try:
            current_index = self.filtered_resrefs.index(self.current_resref) if self.current_resref else 0
        except ValueError:
            current_index = 0
        
        # app_data contains the key code
        if app_data == dpg.mvKey_Up:
            new_index = max(0, current_index - 1)
        elif app_data == dpg.mvKey_Down:
            new_index = min(len(self.filtered_resrefs) - 1, current_index + 1)
        else:
            return

        new_resref = self.filtered_resrefs[new_index]
        self._on_list_selection(None, new_resref)

        # Smart scroll: ensure the item is visible in the container
        # Selectables are 19 pixels high by default in DPG
        item_height = 19
        curr_scroll = dpg.get_y_scroll("resource_list_container")
        window_height = dpg.get_item_height("resource_list_container")
        
        item_top = new_index * item_height
        item_bottom = item_top + item_height
        
        if item_top < curr_scroll:
            dpg.set_y_scroll("resource_list_container", item_top)
        elif item_bottom > curr_scroll + window_height:
            dpg.set_y_scroll("resource_list_container", item_bottom - window_height)

    def _on_filter_toggle(self):
        """Handles toggling the empty frame filter, ensuring we don't stay on an empty view."""
        if not self.current_resource:
            return
            
        if dpg.get_value(self.filter_empty_frames):
            # If current cycle is now empty, jump to the next valid one
            if not self._get_filtered_cycle_frames(self.current_cycle):
                self._change_cycle(delta=1)
                return
        self._update_display()

    def _toggle_animation(self):
        self.is_playing = not self.is_playing
        dpg.configure_item(self.play_button, label="Stop" if self.is_playing else "Play")

    def _get_filtered_cycle_frames(self, cycle_idx):
        """Returns the list of frame indices for a cycle, optionally filtered for 1px frames."""
        if not self.current_resource: return []
        all_frames = self.bam_decoder.get_cycle_frames(self.current_resource, cycle_idx)
        if not dpg.get_value(self.filter_empty_frames):
            return all_frames
            
        frame_entries = self.current_resource.get_section('frame_entries')
        return [i for i in all_frames if frame_entries[i]['width'] > 1 or frame_entries[i]['height'] > 1]

    def _change_cycle(self, delta=0, absolute=None):
        if not self.current_resource: return
        cycles = self.current_resource.get_section('cycle_entries') or []
        count = len(cycles)
        if count == 0: return
        
        new_cycle = self.current_cycle
        if absolute is not None:
            if absolute == 0: # First
                indices = range(count)
            elif absolute == 999: # Final
                indices = range(count - 1, -1, -1)
            else: # Specific
                indices = [absolute]
            
            for i in indices:
                if self._get_filtered_cycle_frames(i):
                    new_cycle = i
                    break
        else:
            step = 1 if delta >= 0 else -1
            # Find next cycle that has at least one valid frame
            for i in range(1, count + 1):
                candidate = (self.current_cycle + i * step) % count
                if self._get_filtered_cycle_frames(candidate):
                    new_cycle = candidate
                    break
            
        self.current_cycle = new_cycle
        if not dpg.get_value(self.preserve_frame_toggle):
            self.current_frame_idx = 0
        self._update_display()

    def _change_frame(self, delta=0, absolute=None):
        if not self.current_resource: return
        valid_frames = self._get_filtered_cycle_frames(self.current_cycle)
        count = len(valid_frames)
        if count == 0: return
        
        if absolute is not None:
            if absolute == 999:
                self.current_frame_idx = count - 1
            else:
                self.current_frame_idx = max(0, min(absolute, count - 1))
        else:
            self.current_frame_idx = (self.current_frame_idx + delta) % count
            
        self._update_display()

    def _on_list_selection(self, sender, app_data):
        self.current_resref = app_data
        dpg.set_value(self.resref_input, app_data)
        
        # Clear last highlight
        if self.last_selected_tag and dpg.does_item_exist(self.last_selected_tag):
            dpg.set_value(self.last_selected_tag, False)
            
        # Set new highlight
        tag = self.selectable_tags.get(app_data)
        if tag and dpg.does_item_exist(tag):
            dpg.set_value(tag, True)
            self.last_selected_tag = tag
            
        self._load_resource()

    def _load_resource(self):
        resref = dpg.get_value(self.resref_input)
        restype = dpg.get_value(self.restype_input)
        game = dpg.get_value(self.game_input)
        
        resource = self.loader.load(resref=resref, restype=restype, game=game)
        if not resource:
            return

        self.current_resource = resource
        self.canvas.offset = [0.0, 0.0]
        is_bam = bool(resource.schema and "BAM" in resource.schema.name)
        self.is_playing = dpg.get_value(self.autoplay_toggle) if is_bam else False
        dpg.configure_item(self.play_button, label="Stop" if self.is_playing else "Play")

        # Initialize navigation to the first valid cycle
        self.current_cycle = 0
        if is_bam:
            count = len(resource.get_section('cycle_entries') or [])
            for i in range(count):
                if self._get_filtered_cycle_frames(i):
                    self.current_cycle = i
                    break
        self.current_frame_idx = 0

        dpg.configure_item("bottom_window", show=is_bam)
        self._on_viewport_resize()
        
        if is_bam:
            cycles = resource.get_section('cycle_entries') or []
            dpg.set_value(self.info_text, f"BAM: {len(cycles)} cycles")
        else:
            dpg.set_value(self.info_text, f"Type: {restype}")

        self._update_display()

    def _update_display(self):
        if not self.current_resource:
            return

        resource = self.current_resource
        game = dpg.get_value(self.game_input)
        restype = dpg.get_value(self.restype_input)
        buffer = None
        pivot_x, pivot_y = 0, 0
        
        if resource.schema and "BAM" in resource.schema.name:  # Handles BAM and BAM_V2
            cycle_frames = self._get_filtered_cycle_frames(self.current_cycle)
            if not cycle_frames:
                # Fallback if cycle is empty or invalid
                real_frame_index = 0
                frame_count = 0
            else:
                frame_count = len(cycle_frames)
                self.current_frame_idx = max(0, min(self.current_frame_idx, frame_count - 1))
                real_frame_index = cycle_frames[self.current_frame_idx]

            dpg.set_value(self.cycle_text, f"Cycle {self.current_cycle} of {len(resource.get_section('cycle_entries') or []) - 1}")
            dpg.set_value(self.frame_text, f"Frame {self.current_frame_idx} of {frame_count - 1}")
            
            # For BAM V2, we need to provide a PVRZ page provider
            pvrz_provider = self._get_pvrz_page_provider(game) if resource.schema.name == 'BAM_V2' else None
            buffer = self.bam_decoder.decode_frame(resource, real_frame_index, pvrz_page_provider=pvrz_provider)
            
            # Update frame info
            frame_data = resource.get_section('frame_entries')[real_frame_index]
            pivot_x = frame_data.get('center_x', 0)
            pivot_y = frame_data.get('center_y', 0)
            dpg.set_value(self.frame_info_text, f"Real Frame: {real_frame_index} ({frame_data['width']}x{frame_data['height']})")

        elif restype == "PVRZ":
            buffer = self.pvrz_decoder.decode_pvrz_bytes(resource._original_bytes)
        elif restype == "TIS":
            # For TIS, we need a palette. We'll try to find a BAM with the same name or use default.
            pal_res = self.loader.load(resref=self.current_resref, restype="BAM", game=game)
            buffer = self.tis_decoder.decode_tis(resource, palette_resource=pal_res)

        if buffer is not None:
            self.canvas.update_texture(buffer, pivot_x=pivot_x, pivot_y=pivot_y)

    def _refresh_resource_list(self):
        game = dpg.get_value(self.game_input)
        target_type = dpg.get_value(self.restype_input)
        
        # Collect all unique resrefs for the given game and type
        resrefs = {resref for resref, restype, _ in self.loader.iter_resources(game=game) if restype == target_type}
        self.all_resrefs = sorted(list(resrefs))
        self._filter_list()

    def _get_pvrz_page_provider(self, game):
        """
        Returns a callable that loads raw PVRZ page bytes by index.
        Used for BAM V2 frames that reference PVRZ pages.
        The decoder expects raw bytes, not decoded images.
        """
        def load_pvrz_page(page_index):
            try:
                # BAM V2 files reference PVRZ textures using the MOSxxxx convention.
                # The index is represented as a zero-padded four-digit decimal string.
                resref = f"MOS{page_index:04d}"
                resource = self.loader.load(resref=resref, restype="PVRZ", game=game)
                if resource:
                    return resource._original_bytes
                return None
            except Exception as e:
                return None
        
        return load_pvrz_page

    def _filter_list(self):
        filter_text = dpg.get_value(self.filter_input).upper()
        self.filtered_resrefs = [r for r in self.all_resrefs if filter_text in r]
        
        # Clear and repopulate the scrollable list
        dpg.delete_item("resource_list_layout", children_only=True)
        self.selectable_tags = {}
        self.last_selected_tag = None
        
        for resref in self.filtered_resrefs:
            tag = dpg.add_selectable(
                label=resref, 
                parent="resource_list_layout", 
                callback=lambda s, a, u: self._on_list_selection(s, u),
                user_data=resref
            )
            self.selectable_tags[resref] = tag
            
        if self.filtered_resrefs:
            self._on_list_selection(None, self.filtered_resrefs[0])
            dpg.set_y_scroll("resource_list_container", 0)

    def run(self):
        dpg.focus_item("controls_window")
        while dpg.is_dearpygui_running():
            if self.is_playing and self.current_resource:
                fps = dpg.get_value(self.fps_input)
                frame_time = 1.0 / max(1, fps)
                current_time = time.time()
                
                if current_time - self.last_frame_time >= frame_time:
                    cycle_frames = self.bam_decoder.get_cycle_frames(self.current_resource, self.current_cycle)
                    if cycle_frames:
                        self.current_frame_idx = (self.current_frame_idx + 1) % len(cycle_frames)
                        self._update_display()
                    self.last_frame_time = current_time

            dpg.render_dearpygui_frame()
        dpg.destroy_context()

if __name__ == "__main__":
    app = ImageViewerApp()
    app.run()
