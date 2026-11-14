import sys
import time
import math
from pathlib import Path
import numpy as np

# Add the project root to sys.path so 'drivers' and 'core' can be found when running standalone
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import dearpygui.dearpygui as dpg
from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.graphics.bam_decoder import BamDecoder
from drivers.InfinityEngine.graphics.pvrz_decoder import PvrzDecoder, PvrzError
from drivers.InfinityEngine.graphics.tis_decoder import TisDecoder
from canvas import PFCanvas

class ImageViewerApp:
    def __init__(self):
        self.loader = ResourceLoader()
        self.bam_decoder = BamDecoder()
        self.pvrz_decoder = PvrzDecoder()
        self.tis_decoder = TisDecoder()
        self._tis_page_bytes_cache = {}
        self._pvrz_resref_index_cache = {}
        self._tis_wed_map_cache = {}
        self._tis_wed_metadata_cache = {}
        
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
        self.current_overlay_idx = 0
        
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
            dpg.add_text("Tile Inspector")
            dpg.add_text("Hover map tiles in Map Layout mode", tag="tile_inspector_text")

        with dpg.window(label="Canvas", tag="canvas_window", pos=[305, 0], width=895, height=800, no_scrollbar=True):
            dpg.add_drawlist(tag="image_canvas", width=875, height=760)

            with dpg.handler_registry():
                dpg.add_mouse_wheel_handler(callback=self._on_mouse_wheel)
                dpg.add_key_press_handler(callback=self._on_key_press)
                dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_down)
                dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_drag)
                dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_release)

        # Move Top Window and its theme here so it is created AFTER the canvas (starting on top)
        with dpg.theme(tag="top_window_theme"):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 2)
                dpg.add_theme_style(dpg.mvStyleVar_WindowMinSize, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)

        with dpg.window(tag="top_window", no_title_bar=True, no_move=True, no_resize=True, no_scrollbar=True, no_focus_on_appearing=True, no_bring_to_front_on_focus=True):
            dpg.bind_item_theme("top_window", "top_window_theme")
            with dpg.group(horizontal=True):
                dpg.add_button(label="Reset View", callback=self._reset_view)
                self.alignment_combo = dpg.add_combo(label="Alignment", items=["Pivot", "Center", "Top-Left", "Top-Center", "Top-Right", "Left-Center", "Right-Center", "Bottom-Left", "Bottom-Center", "Bottom-Right"], default_value="Pivot",
                             callback=lambda s, v: setattr(self.canvas, 'alignment', v) or self.canvas._redraw(), width=120)
                self.zoom_slider = dpg.add_slider_float(label="Zoom", min_value=0.1, max_value=10.0, default_value=1.0, 
                                    callback=lambda s, v: self.canvas.set_zoom_absolute(v), width=150) 
                self.overlay_combo = dpg.add_combo(label="Overlay", items=[], show=False, width=150,
                                                  callback=self._on_overlay_change)

                dpg.add_checkbox(label="Show Border", default_value=True, 
                                callback=lambda s, v: setattr(self.canvas, 'show_border', v) or self.canvas._redraw())
                dpg.add_checkbox(label="Show Markers", default_value=True,
                                callback=lambda s, v: setattr(self.canvas, 'show_markers', v) or self.canvas._redraw())
                self.show_grid_checkbox = dpg.add_checkbox(label="Show Grid", default_value=False, show=False,
                                callback=lambda s, v: setattr(self.canvas, 'show_grid', v) or self.canvas._redraw())
                self.use_wed_layout = dpg.add_checkbox(label="Map Layout", default_value=True, show=False,
                                callback=self._on_layout_change)
                self.tis_grid_slider = dpg.add_slider_int(label="Grid Width", min_value=1, max_value=80, default_value=10, 
                                                         show=False, callback=self._update_display, width=150)

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
        th = 30  # Height for top panel
        bh = 120 if dpg.is_item_shown("bottom_window") else 0
        
        dpg.configure_item("controls_window", height=vh)
        
        if dpg.does_item_exist("top_window"):
            dpg.configure_item("top_window", pos=[cw + 5, 0], width=vw - cw - 20, height=30)

        if dpg.does_item_exist("canvas_window"):
            # Canvas window starts below the top panel
            dpg.configure_item("canvas_window", pos=[cw + 5, th], width=vw - cw - 20, height=vh - bh - th)
            dpg.configure_item("image_canvas", width=vw - cw - 40, height=vh - bh - th - 40)
            
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

    def _on_layout_change(self):
        """Callback for the 'Map Layout' checkbox to toggle slider visibility."""
        use_wed = dpg.get_value(self.use_wed_layout)
        dpg.configure_item(self.tis_grid_slider, show=not use_wed)
        self._update_display()

    def _on_overlay_change(self, sender, app_data):
        """Callback for the Overlay dropdown."""
        try:
            # Extract index from "Overlay X: name" string.
            self.current_overlay_idx = int(str(app_data).split(":", 1)[0].replace("Overlay ", "").strip())
        except (TypeError, ValueError):
            self.current_overlay_idx = 0
        self._update_display()

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
        
        # Clear current resource and stop playback to prevent stale animation loops
        self.current_resource = None
        self.is_playing = False
        
        resource = self.loader.load(resref=resref, restype=restype, game=game)
        if not resource:
            return

        self.current_resource = resource
        self.canvas.offset = [0.0, 0.0]
        self.current_overlay_idx = 0

        # Set default alignment based on resource type
        if restype == "PVRZ" or restype == "TIS":
            self.canvas.alignment = "Center"
        else:
            self.canvas.alignment = "Pivot" # Default for other types
        dpg.set_value(self.alignment_combo, self.canvas.alignment)
        is_bam = bool(resource.schema and "BAM" in resource.schema.name)
        self.is_playing = dpg.get_value(self.autoplay_toggle) if is_bam else False

        # Update TIS grid controls visibility and initial values
        is_tis = (restype == "TIS")
        
        # Pre-fetch WED metadata to populate overlay list
        wed_metadata = self._get_wed_metadata(game, resource.name) if is_tis else None
        has_wed = wed_metadata is not None
        
        if is_tis and has_wed:
            overlays = wed_metadata["overlays"]
            items = [f"Overlay {i}: {self._normalize_tileset_name(ov.get('tileset_name')) or '(unnamed)'}" for i, ov in enumerate(overlays)]
            chosen_overlay = self._choose_overlay_for_tis(resource.name, overlays)
            if chosen_overlay is None:
                chosen_overlay = self._choose_best_overlay_for_tis(game, resource, overlays)
            self.current_overlay_idx = chosen_overlay
            dpg.configure_item(
                self.overlay_combo,
                items=items,
                default_value=items[self.current_overlay_idx] if items else "",
                show=True,
            )
        else:
            dpg.configure_item(self.overlay_combo, show=False)

        map_info = self._get_tis_wed_map_info(game, resource, self.current_overlay_idx) if is_tis and has_wed else None
        use_wed = has_wed and map_info is not None and dpg.get_value(self.use_wed_layout)
        if is_tis and has_wed and map_info is None and dpg.get_value(self.use_wed_layout):
            dpg.set_value(self.use_wed_layout, False)
            use_wed = False

        dpg.configure_item(self.use_wed_layout, show=has_wed)
        dpg.configure_item(self.show_grid_checkbox, show=is_tis)
        dpg.configure_item(self.tis_grid_slider, show=is_tis and not use_wed)

        if is_tis:
            if has_wed and map_info:
                dpg.set_value(self.tis_grid_slider, map_info["width"])
            else:
                dpg.set_value(self.tis_grid_slider, self._compute_tis_grid_width(resource))

            tile_dim = int(resource.get("tile_dimension") or 64)
            self.canvas.grid_size = [tile_dim, tile_dim]
        else:
            self.canvas.show_grid = False
            dpg.set_value(self.show_grid_checkbox, False)

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
            try:
                buffer = self.pvrz_decoder.decode_pvrz_bytes(resource._original_bytes)
            except PvrzError as exc:
                dpg.set_value(self.info_text, f"PVRZ decode failed: {exc}")
        elif restype == "TIS":
            pvrz_provider = self._get_tis_pvrz_page_provider(game)
            map_info = self._get_tis_wed_map_info(game, resource, self.current_overlay_idx)
            source_tile_limit = self._compute_tis_source_tile_limit(resource, map_info=map_info)
            header_tile_count = int(resource.get("count_of_tiles") or 0)
            effective_tile_count = source_tile_limit if source_tile_limit is not None else header_tile_count

            if dpg.get_value(self.use_wed_layout) and map_info:
                buffer = self.tis_decoder.decode_tis(
                    resource,
                    pvrz_page_provider=pvrz_provider,
                    grid_width=map_info["width"],
                    grid_height=map_info["height"],
                    tile_indices=map_info["tile_indices"],
                    source_tile_limit=source_tile_limit,
                )
                dpg.set_value(
                    self.info_text,
                    f"TIS: {effective_tile_count}/{header_tile_count} tiles | "
                    f"WED {map_info['width']}x{map_info['height']} | "
                    f"resolved {map_info.get('resolved_count', 0)}/{map_info.get('cell_count', 0)} | "
                    f"non-black {map_info.get('non_black_count', 0)} | "
                    f"max-idx {map_info.get('max_tis_index', -1)} "
                    f"({map_info.get('mapping_mode', 'overlay0')})",
                )
            else:
                grid_width = dpg.get_value(self.tis_grid_slider)
                buffer = self.tis_decoder.decode_tis(
                    resource,
                    pvrz_page_provider=pvrz_provider,
                    grid_width=grid_width,
                    source_tile_limit=source_tile_limit,
                )
                dpg.set_value(
                    self.info_text,
                    f"TIS: {effective_tile_count}/{header_tile_count} tiles | Grid {grid_width}",
                )

        if buffer is not None:
            self.canvas.update_texture(buffer, pivot_x=pivot_x, pivot_y=pivot_y)
        else:
            self.canvas.clear_texture()


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

    def _get_tis_pvrz_page_provider(self, game):
        """
        Specialized provider for TIS PVRZ naming conventions.
        Example: AR2600.TIS references A2600xx.PVRZ
        """
        tis_name = (self.current_resref or "").upper()
        if not tis_name:
            return lambda _page_index: None

        pvrz_resrefs = self._get_pvrz_resrefs(game)
        
        # Convention: Char 1 + Chars 3-6 + optional 'N' + PageIndex
        # e.g. AR2600 -> A + 2600 -> A2600
        # e.g. AR2600N -> A + 2600 + N -> A2600N
        prefix = tis_name[0] + tis_name[2:6]
        if len(tis_name) > 6 and tis_name[6] == 'N':
            prefix += 'N'

        def load_tis_pvrz_page(page_index):
            try:
                page_index = int(page_index)
            except (TypeError, ValueError):
                return None

            cache_key = (game, tis_name, page_index)
            if cache_key in self._tis_page_bytes_cache:
                return self._tis_page_bytes_cache[cache_key]

            candidate_resrefs = []

            def add_candidate(resref):
                if not resref:
                    return
                if resref not in candidate_resrefs:
                    candidate_resrefs.append(resref)

            # Primary naming (documented by IESDP for EE area tilesets)
            add_candidate(f"{prefix}{page_index:02d}")

            # Alternate base observed in some resources/tools
            if len(tis_name) >= 6:
                add_candidate(f"{tis_name[:6]}{page_index:02d}")

            # Some assets encode page suffixes in hex-like form for higher pages.
            if page_index >= 10:
                add_candidate(f"{prefix}{page_index:02X}")
                if len(tis_name) >= 6:
                    add_candidate(f"{tis_name[:6]}{page_index:02X}")

            # Fallback used by a subset of BGEE content: global MOS page ids.
            add_candidate(f"MOS{page_index:04d}")

            for resref in candidate_resrefs:
                if resref not in pvrz_resrefs:
                    continue
                try:
                    resource = self.loader.load(resref=resref, restype="PVRZ", game=game)
                except Exception:
                    resource = None
                if resource:
                    data = resource._original_bytes
                    self._tis_page_bytes_cache[cache_key] = data
                    return data

            self._tis_page_bytes_cache[cache_key] = None
            return None

        return load_tis_pvrz_page

    def _compute_tis_grid_width(self, resource):
        """
        Chooses a TIS stitching width that keeps texture dimensions under a
        conservative GPU-safe limit to prevent DPG/OpenGL texture crashes.
        """
        preferred = 10
        tile_size = int(resource.get("tile_dimension") or 64)
        tile_count = int(resource.get("count_of_tiles") or 0)
        if tile_size <= 0 or tile_count <= 0:
            return preferred

        max_dim = getattr(self.canvas, "SAFE_MAX_TEXTURE_DIM", 8192)
        max_tiles_axis = max(1, max_dim // tile_size)

        # Keep default layout when already safe.
        if (
            preferred <= max_tiles_axis and
            math.ceil(tile_count / preferred) <= max_tiles_axis
        ):
            return preferred

        # Minimum width required to satisfy height limit.
        min_width_for_height = math.ceil(tile_count / max_tiles_axis)
        width = max(1, min_width_for_height)

        # Clamp by what can still satisfy width limit.
        width = min(width, max_tiles_axis)
        return width

    def _compute_tis_source_tile_limit(self, resource, map_info=None):
        """
        Derive an effective source tile count cap when BIFF-pool headers expose
        more tiles than this specific TIS logically uses.
        """
        try:
            header_count = int(resource.get("count_of_tiles") or 0)
        except (TypeError, ValueError):
            header_count = 0
        if header_count <= 0:
            return None

        candidates = []

        # Map-driven cap: highest referenced TIS index + 1.
        if map_info:
            max_idx = map_info.get("max_tis_index")
            try:
                max_idx = int(max_idx)
            except (TypeError, ValueError):
                max_idx = -1
            if max_idx >= 0:
                candidates.append(max_idx + 1)

        # Overlay metadata cap: unique_tile_count (when present and sane).
        game = dpg.get_value(self.game_input)
        wed_meta = self._get_wed_metadata(game, resource.name)
        overlays = (wed_meta or {}).get("overlays") or []
        if 0 <= self.current_overlay_idx < len(overlays):
            unique = overlays[self.current_overlay_idx].get("unique_tile_count", 0)
            try:
                unique = int(unique or 0)
            except (TypeError, ValueError):
                unique = 0
            if unique > 0:
                candidates.append(unique)

        valid = [c for c in candidates if 0 < c <= header_count]
        if not valid:
            return None

        # Prefer the broadest plausible cap to avoid clipping legitimate tiles
        # when mapping heuristics are uncertain.
        limit = max(valid)
        return limit if limit < header_count else None

    @staticmethod
    def _normalize_tileset_name(value):
        return str(value or "").split("\x00", 1)[0].strip().upper()

    def _tis_name_aliases(self, value):
        base = self._normalize_tileset_name(value)
        aliases = {base}
        if len(base) >= 6 and base[0].isalpha() and base[1].isalpha() and base[2:6].isdigit():
            area = base[2:6]
            # ARxxxx -> Axxxx variants observed in EE area assets.
            aliases.add(base[0] + area)          # A0107
            aliases.add(base[0] + area + "00")   # A010700
            aliases.add(base[:2] + area + "00")  # AR010700
        return aliases

    def _choose_overlay_for_tis(self, tis_name, overlays):
        if not overlays:
            return None
        tis_aliases = self._tis_name_aliases(tis_name)
        for idx, overlay in enumerate(overlays):
            if self._normalize_tileset_name(overlay.get("tileset_name")) in tis_aliases:
                return idx
        return None

    def _choose_best_overlay_for_tis(self, game, tis_resource, overlays):
        if not overlays:
            return 0
        best_idx = 0
        best_key = (-1, -1, -1)
        for idx in range(len(overlays)):
            info = self._get_tis_wed_map_info(game, tis_resource, idx)
            if not info:
                continue
            key = (
                int(info.get("non_black_count", 0)),
                int(info.get("resolved_count", 0)),
                int(info.get("max_tis_index", -1)),
            )
            if key > best_key:
                best_key = key
                best_idx = idx
        return best_idx

    def _get_wed_metadata(self, game, wed_name):
        """Loads and caches basic WED section metadata."""
        wed_name = str(wed_name).upper()
        cache_key = (game, wed_name)
        if cache_key in self._tis_wed_metadata_cache:
            return self._tis_wed_metadata_cache[cache_key]
            
        try:
            wed_resource = self.loader.load(resref=wed_name, restype="WED", game=game)
        except Exception as e:
            wed_resource = None

        if wed_resource is None:
            self._tis_wed_metadata_cache[cache_key] = None
            return None
            
        meta = {
            "overlays": wed_resource.get_section("overlays") or [],
            "tilemaps": wed_resource.get_section("tilemaps") or [],
            "lookup":   wed_resource.get_section("tile_index_lookup") or []
        }
        self._tis_wed_metadata_cache[cache_key] = meta
        return meta

    def _get_tis_wed_map_info(self, game, tis_resource, overlay_idx):
        """
        Builds mapping for a SPECIFIC overlay index.
        """
        if tis_resource is None or not tis_resource.name:
            return None

        tis_name = self._normalize_tileset_name(tis_resource.name)
        try:
            overlay_idx = int(overlay_idx)
        except (TypeError, ValueError):
            overlay_idx = 0
        cache_key = (game, tis_name, overlay_idx)
        if cache_key in self._tis_wed_map_cache:
            return self._tis_wed_map_cache[cache_key]

        wed_meta = self._get_wed_metadata(game, tis_name)
        if not wed_meta:
            self._tis_wed_map_cache[cache_key] = None
            return None

        overlays, tilemaps, lookup = wed_meta["overlays"], wed_meta["tilemaps"], wed_meta["lookup"]

        if not overlays:
            self._tis_wed_map_cache[cache_key] = None
            return None

        if overlay_idx < 0 or overlay_idx >= len(overlays):
            return None

        TILEMAP_ENTRY_BYTES = 10   # 2+2+2+1+3 bytes per WED v1.3 tilemap entry.
        LOOKUP_ENTRY_BYTES  = 2

        ov          = overlays[overlay_idx]
        width       = int(ov.get("width",  0) or 0)
        height      = int(ov.get("height", 0) or 0)
        this_tm_off = int(ov.get("offset_to_tilemap",           0) or 0)
        this_lk_off = int(ov.get("offset_to_tile_index_lookup", 0) or 0)
        if width <= 0 or height <= 0:
            self._tis_wed_map_cache[cache_key] = None
            return None

        cell_count = width * height

        tiles_section = tis_resource.get_section("tiles") or []
        is_pvrz_tiles = bool(tis_resource.schema and tis_resource.schema.name == "TIS_PVRZ")

        def is_non_black_tile_index(tis_index):
            if tis_index < 0:
                return False
            if not is_pvrz_tiles:
                return True
            if tis_index >= len(tiles_section):
                return False
            tile_entry = tiles_section[tis_index]
            if not isinstance(tile_entry, dict):
                return False
            raw_page = tile_entry.get("pvrz_page")
            try:
                pvrz_page = int(raw_page)
            except (TypeError, ValueError):
                pvrz_page = 0xFFFFFFFF
            return pvrz_page != 0xFFFFFFFF

        def resolve_tis_index(primary_tile_index, primary_tile_count, lookup_start, lookup_mode):
            try:
                p_index = int(primary_tile_index)
            except (TypeError, ValueError):
                p_index = -1
            if p_index < 0:
                return -1, -1, -1, False

            try:
                p_count = int(primary_tile_count)
            except (TypeError, ValueError):
                p_count = 1
            if p_count <= 0:
                p_count = 1

            first_valid_tis = -1
            first_valid_lookup = -1

            for frame_off in range(p_count):
                if lookup_mode == "absolute":
                    lookup_idx = p_index + frame_off
                else:
                    lookup_idx = lookup_start + p_index + frame_off

                if lookup_idx < 0 or lookup_idx >= len(lookup):
                    continue

                lk_entry = lookup[lookup_idx]
                try:
                    tis_index = int(lk_entry.get("tis_index")) if isinstance(lk_entry, dict) else int(lk_entry)
                except (TypeError, ValueError):
                    continue
                if tis_index < 0:
                    continue

                if first_valid_tis < 0:
                    first_valid_tis = tis_index
                    first_valid_lookup = lookup_idx

                if is_non_black_tile_index(tis_index):
                    return tis_index, lookup_idx, frame_off, True

            if first_valid_tis >= 0:
                return first_valid_tis, first_valid_lookup, 0, is_non_black_tile_index(first_valid_tis)

            return -1, -1, -1, False

        def build_map_from_starts(tilemap_start, lookup_start, base_mode, lookup_mode):
            if tilemap_start < 0 or lookup_start < 0:
                return None

            tile_indices = np.full(cell_count, -1, dtype=np.int32)
            debug_info = [None] * cell_count

            resolved = 0
            non_black = 0
            for cell in range(cell_count):
                tm_idx = tilemap_start + cell
                primary_tile_index = -1
                lookup_idx = -1
                tis_index = -1
                chosen_frame = -1

                if 0 <= tm_idx < len(tilemaps):
                    tm = tilemaps[tm_idx]
                    primary_tile_index = int(tm.get("primary_tile_index", 0) or 0)
                    primary_tile_count = int(tm.get("primary_tile_count", 1) or 1)
                    tis_index, lookup_idx, chosen_frame, is_non_black = resolve_tis_index(
                        primary_tile_index=primary_tile_index,
                        primary_tile_count=primary_tile_count,
                        lookup_start=lookup_start,
                        lookup_mode=lookup_mode,
                    )
                    if tis_index >= 0:
                        resolved += 1
                        if is_non_black:
                            non_black += 1
                else:
                    primary_tile_count = 0

                tile_indices[cell] = tis_index
                debug_info[cell] = {
                    "tm_idx": tm_idx,
                    "primary": primary_tile_index,
                    "primary_count": primary_tile_count,
                    "lookup_idx": lookup_idx,
                    "tis_index": tis_index,
                    "chosen_frame": chosen_frame,
                    "mode": f"{base_mode}-{lookup_mode}",
                }

            valid = tile_indices[tile_indices >= 0]
            max_tis_index = int(valid.max()) if valid.size > 0 else -1
            return {
                "width": width,
                "height": height,
                "tile_indices": tile_indices,
                "debug_info": debug_info,
                "resolved_count": resolved,
                "cell_count": cell_count,
                "non_black_count": non_black,
                "max_tis_index": max_tis_index,
                "mapping_mode": f"{base_mode}-{lookup_mode}",
            }

        def build_map_from_offsets(base_tm_off, base_lk_off, base_mode, lookup_mode):
            if base_tm_off <= 0 or base_lk_off <= 0:
                return None

            tm_delta = this_tm_off - base_tm_off
            lk_delta = this_lk_off - base_lk_off
            if tm_delta < 0 or lk_delta < 0:
                return None
            if tm_delta % TILEMAP_ENTRY_BYTES != 0 or lk_delta % LOOKUP_ENTRY_BYTES != 0:
                return None

            tilemap_start = tm_delta // TILEMAP_ENTRY_BYTES
            lookup_start  = lk_delta // LOOKUP_ENTRY_BYTES
            return build_map_from_starts(tilemap_start, lookup_start, base_mode, lookup_mode)

        # Primary path: schema/spec anchor is overlays[0] offsets.
        overlay0 = overlays[0]
        base_tm_overlay0 = int(overlay0.get("offset_to_tilemap") or 0)
        base_lk_overlay0 = int(overlay0.get("offset_to_tile_index_lookup") or 0)
        candidates = []
        for lookup_mode in ("relative", "absolute"):
            info_primary = build_map_from_offsets(base_tm_overlay0, base_lk_overlay0, "overlay0", lookup_mode)
            if info_primary:
                candidates.append(info_primary)

        # Fallback path for sparse/legacy edge files: minimum positive bases.
        tilemap_offsets = [int(o.get("offset_to_tilemap") or 0) for o in overlays]
        lookup_offsets = [int(o.get("offset_to_tile_index_lookup") or 0) for o in overlays]
        min_tm = min((x for x in tilemap_offsets if x > 0), default=0)
        min_lk = min((x for x in lookup_offsets if x > 0), default=0)
        if (min_tm, min_lk) != (base_tm_overlay0, base_lk_overlay0):
            for lookup_mode in ("relative", "absolute"):
                info_min = build_map_from_offsets(min_tm, min_lk, "min", lookup_mode)
                if info_min:
                    candidates.append(info_min)

        # Fallback: cumulative overlay windows. Useful for edge files where
        # offsets are sparse/stale but parser materialized packed arrays.
        cumulative_tilemaps = 0
        cumulative_tiles = 0
        cumulative_unique = 0
        for oi in range(overlay_idx):
            o = overlays[oi]
            cumulative_tilemaps += int(o.get("tile_count", 0) or 0)
            cumulative_tiles += int(o.get("tile_count", 0) or 0)
            cumulative_unique += int(o.get("unique_tile_count", 0) or 0)

        for lookup_mode in ("relative", "absolute"):
            info_cum_tiles = build_map_from_starts(
                tilemap_start=cumulative_tilemaps,
                lookup_start=cumulative_tiles,
                base_mode="cumulative-tilecount",
                lookup_mode=lookup_mode,
            )
            if info_cum_tiles:
                candidates.append(info_cum_tiles)

            if cumulative_unique != cumulative_tiles:
                info_cum_unique = build_map_from_starts(
                    tilemap_start=cumulative_tilemaps,
                    lookup_start=cumulative_unique,
                    base_mode="cumulative-unique",
                    lookup_mode=lookup_mode,
                )
                if info_cum_unique:
                    candidates.append(info_cum_unique)

        if not candidates:
            self._tis_wed_map_cache[cache_key] = None
            return None

        # Choose the best-resolving candidate.
        info = max(
            candidates,
            key=lambda x: (
                int(x.get("non_black_count", 0)),
                int(x.get("resolved_count", 0)),
                int(x.get("max_tis_index", -1)),
            ),
        )
        self._tis_wed_map_cache[cache_key] = info
        return info

    def _handle_tile_inspector(self):
        """Update the Tile Inspector readout text."""
        if not dpg.is_item_hovered("image_canvas") or not self.current_resource:
            return
            
        if dpg.get_value(self.restype_input) != "TIS" or not dpg.get_value(self.use_wed_layout):
            dpg.set_value("tile_inspector_text", "No WED mapping active")
            return

        game = dpg.get_value(self.game_input)
        map_info = self._get_tis_wed_map_info(game, self.current_resource, self.current_overlay_idx)
        if not map_info:
            return

        # Map mouse to tile coord
        m_pos = dpg.get_drawing_mouse_pos()
        canvas_width = dpg.get_item_width("image_canvas")
        canvas_height = dpg.get_item_height("image_canvas")
        
        # Calculate tile offset (bx, by from canvas.py logic)
        image_width = self.canvas.current_texture_width * self.canvas.zoom
        image_height = self.canvas.current_texture_height * self.canvas.zoom
        bx = (canvas_width - image_width) / 2 + self.canvas.offset[0]
        by = (canvas_height - image_height) / 2 + self.canvas.offset[1]

        tile_x = int((m_pos[0] - bx) // (64 * self.canvas.zoom))
        tile_y = int((m_pos[1] - by) // (64 * self.canvas.zoom))
        
        if 0 <= tile_x < map_info['width'] and 0 <= tile_y < map_info['height']:
            cell_idx = tile_y * map_info['width'] + tile_x
            debug_info = map_info.get("debug_info") or []
            if cell_idx >= len(debug_info) or debug_info[cell_idx] is None:
                dpg.set_value("tile_inspector_text",
                    f"Coord: ({tile_x}, {tile_y})\n"
                    f"No debug entry for this cell")
                return
            info = debug_info[cell_idx]
            dpg.set_value("tile_inspector_text",
                f"Coord: ({tile_x}, {tile_y})\n"
                f"Tilemap Index: {info['tm_idx']}\n"
                f"Primary Index: {info['primary']}\n"
                f"Primary Count: {info.get('primary_count', 0)}\n"
                f"Chosen Frame:  {info.get('chosen_frame', -1)}\n"
                f"Lookup Index:  {info['lookup_idx']}\n"
                f"TIS Index:     {info['tis_index']}\n"
                f"Mode:          {info.get('mode', 'overlay0')}\n"
                f"Map Anchor:    {map_info.get('mapping_mode', 'overlay0')}\n"
                f"Resolved:      {map_info.get('resolved_count', 0)}/{map_info.get('cell_count', 0)}")
        else:
            dpg.set_value("tile_inspector_text", "Outside map bounds")

    def _get_pvrz_resrefs(self, game):
        cached = self._pvrz_resref_index_cache.get(game)
        if cached is not None:
            return cached

        pvrz_resrefs = {
            resref
            for resref, restype, _ in self.loader.iter_resources(game=game)
            if restype == "PVRZ"
        }
        self._pvrz_resref_index_cache[game] = pvrz_resrefs
        return pvrz_resrefs

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
            self._handle_tile_inspector()
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
