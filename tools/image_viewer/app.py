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
        self.current_cycle = 0
        self.current_frame_idx = 0  # Index within the current cycle's frame list
        self.is_playing = False
        self.last_frame_time = 0
        self.all_resrefs = []
        
        dpg.create_context()
        self.canvas = PFCanvas(app=self)
        self._setup_ui()

        self._refresh_resource_list()

        dpg.create_viewport(title="PlanarForgeV2 - Image Viewer", width=1200, height=800)
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
            self.resource_list = dpg.add_listbox(
                label="##res_list", 
                items=[], 
                num_items=15, 
                width=-1,
                callback=self._on_list_selection
            )
            dpg.focus_item(self.resource_list)

            self.resref_input = dpg.add_input_text(label="ResRef", default_value="GMISC01", readonly=True)
            dpg.add_button(label="Load Resource", callback=self._load_resource)
            
            # BAM Animation Controls
            with dpg.group(tag="bam_controls", show=False):
                dpg.add_separator()
                dpg.add_text("Cycle Controls")
                with dpg.group(horizontal=True):
                    dpg.add_button(label="<<", callback=lambda: self._change_cycle(absolute=0))
                    dpg.add_button(label="<", callback=lambda: self._change_cycle(delta=-1))
                    self.cycle_text = dpg.add_text("Cycle 0 of 0")
                    dpg.add_button(label=">", callback=lambda: self._change_cycle(delta=1))
                    dpg.add_button(label=">>", callback=lambda: self._change_cycle(absolute=999))
                
                dpg.add_text("Frame Controls")
                with dpg.group(horizontal=True):
                    dpg.add_button(label="<<", callback=lambda: self._change_frame(absolute=0))
                    dpg.add_button(label="<", callback=lambda: self._change_frame(delta=-1))
                    self.frame_text = dpg.add_text("Frame 0 of 0")
                    dpg.add_button(label=">", callback=lambda: self._change_frame(delta=1))
                    dpg.add_button(label=">>", callback=lambda: self._change_frame(absolute=999))
                
                with dpg.group(horizontal=True):
                    self.play_button = dpg.add_button(label="Play", width=100, callback=self._toggle_animation)
                    self.fps_input = dpg.add_input_int(label="FPS", default_value=10, width=100)

            # Metadata info
            dpg.add_separator()
            self.info_text = dpg.add_text("No resource loaded")
            self.frame_info_text = dpg.add_text("")
            
            dpg.add_separator()
            self.zoom_slider = dpg.add_slider_float(label="Zoom", min_value=0.1, max_value=10.0, default_value=1.0, 
                                callback=lambda s, v: self.canvas.set_zoom_absolute(v))
            
            dpg.add_checkbox(label="Show Red Border", default_value=True, 
                            callback=lambda s, v: setattr(self.canvas, 'show_border', v) or self.canvas._redraw())
            
            dpg.add_combo(label="Alignment", items=["Top-Left", "Center"], default_value="Top-Left",
                         callback=lambda s, v: setattr(self.canvas, 'alignment', v) or self.canvas._redraw())

        with dpg.window(label="Canvas", tag="canvas_window", pos=[305, 0], width=895, height=800, no_scrollbar=True):
            dpg.add_drawlist(tag="image_canvas", width=875, height=760)
            with dpg.handler_registry():
                dpg.add_mouse_wheel_handler(callback=self._on_mouse_wheel)
                dpg.add_key_press_handler(callback=self._on_key_press)

    def _on_list_selection(self, sender, app_data):
        dpg.set_value(self.resref_input, app_data)
        self._load_resource()

    def _on_viewport_resize(self):
        """Update UI layout when the main window resizes."""
        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()
        cw = 300 # Fixed width for controls
        
        dpg.configure_item("controls_window", height=vh)
        
        if dpg.does_item_exist("canvas_window"):
            # Adjust canvas window to fill remaining width
            dpg.configure_item("canvas_window", pos=[cw + 5, 0], width=vw - cw - 20, height=vh)
            dpg.configure_item("image_canvas", width=vw - cw - 40, height=vh - 40)
        
        if hasattr(self, 'canvas'):
            self.canvas._redraw()

    def _on_mouse_wheel(self, sender, app_data):
        # Only zoom if the resource list is NOT focused
        if dpg.get_focused_item() != self.resource_list:
            self.canvas.on_mouse_wheel(app_data)

    def _on_key_press(self, sender, app_data):
        """Handle keyboard navigation for the resource list."""
        current_items = dpg.get_item_configuration(self.resource_list)['items']
        if not current_items:
            return
        
        current_value = dpg.get_value(self.resource_list)
        try:
            current_index = current_items.index(current_value) if current_value else 0
        except ValueError:
            current_index = 0
        
        # app_data contains the key code
        if app_data == dpg.mvKey_Up:
            new_index = max(0, current_index - 1)
            dpg.set_value(self.resource_list, current_items[new_index])
            self._on_list_selection(None, current_items[new_index])
        elif app_data == dpg.mvKey_Down:
            new_index = min(len(current_items) - 1, current_index + 1)
            dpg.set_value(self.resource_list, current_items[new_index])
            self._on_list_selection(None, current_items[new_index])

    def _toggle_animation(self):
        self.is_playing = not self.is_playing
        dpg.configure_item(self.play_button, label="Stop" if self.is_playing else "Play")

    def _change_cycle(self, delta=0, absolute=None):
        if not self.current_resource: return
        count = len(self.current_resource.get_section('cycle_entries') or [])
        if count == 0: return
        
        if absolute is not None:
            self.current_cycle = max(0, min(absolute, count - 1))
        else:
            self.current_cycle = (self.current_cycle + delta) % count
            
        self.current_frame_idx = 0
        self._update_display()

    def _change_frame(self, delta=0, absolute=None):
        if not self.current_resource: return
        frames = self.bam_decoder.get_cycle_frames(self.current_resource, self.current_cycle)
        count = len(frames)
        if count == 0: return
        
        if absolute is not None:
            self.current_frame_idx = max(0, min(absolute, count - 1))
        else:
            self.current_frame_idx = (self.current_frame_idx + delta) % count
            
        self._update_display()

    def _load_resource(self):
        resref = dpg.get_value(self.resref_input)
        restype = dpg.get_value(self.restype_input)
        game = dpg.get_value(self.game_input)
        
        resource = self.loader.load(resref=resref, restype=restype, game=game)
        if not resource:
            print(f"Failed to load {resref}.{restype}")
            return

        self.current_resource = resource
        self.current_cycle = 0
        self.current_frame_idx = 0
        self.is_playing = False
        dpg.configure_item(self.play_button, label="Play")

        is_bam = resource.schema and "BAM" in resource.schema.name
        dpg.configure_item("bam_controls", show=is_bam)
        
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
        
        if resource.schema and "BAM" in resource.schema.name:  # Handles BAM and BAM_V2
            cycle_frames = self.bam_decoder.get_cycle_frames(resource, self.current_cycle)
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
            dpg.set_value(self.frame_info_text, f"Real Frame: {real_frame_index} ({frame_data['width']}x{frame_data['height']})")

        elif restype == "PVRZ":
            buffer = self.pvrz_decoder.decode_pvrz_bytes(resource._original_bytes)
        elif restype == "TIS":
            # For TIS, we need a palette. We'll try to find a BAM with the same name or use default.
            pal_res = self.loader.load(resref=resref, restype="BAM", game=game)
            buffer = self.tis_decoder.decode_tis(resource, palette_resource=pal_res)

        if buffer is not None:
            print(f"DEBUG: Buffer decoded. Shape: {buffer.shape}, Max Value: {np.max(buffer)}, Min Value: {np.min(buffer)}")
            self.canvas.update_texture(buffer)
        else:
            print(f"DEBUG: Decoder returned None for {resref}")

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
                
                print(f"DEBUG: Failed to load PVRZ page {page_index} as {resref}")
                return None
            except Exception as e:
                print(f"DEBUG: Error loading PVRZ page {page_index}: {e}")
                return None
        
        return load_pvrz_page

    def _filter_list(self):
        filter_text = dpg.get_value(self.filter_input).upper()
        filtered = [r for r in self.all_resrefs if filter_text in r]
        dpg.configure_item(self.resource_list, items=filtered)
        if filtered:
            dpg.set_value(self.resource_list, filtered[0])
            self._on_list_selection(None, filtered[0])

    def run(self):
        dpg.focus_item("controls_window")
        dpg.focus_item(self.resource_list)
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
