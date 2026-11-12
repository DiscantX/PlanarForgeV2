import sys
from pathlib import Path
import dearpygui.dearpygui as dpg
import numpy as np

# Add project root to sys.path so we can import internal modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.graphics.tis_decoder import TisDecoder

class TISTroubleshooter:
    """
    A minimal Dear PyGui application designed for troubleshooting TIS file
    resolution and coordinate mapping.
    """
    def __init__(self):
        dpg.create_context()

        self.loader = ResourceLoader()
        self.decoder = TisDecoder()
        self.all_tis_resrefs = []
        self.filtered_resrefs = []
        self.selected_resref = None
        self.active_texture_tag = dpg.generate_uuid()
        self.pan_start_offset = [0.0, 0.0]
        self.reference_bytes = None
        self.is_panning = False
        
        # Viewport and Canvas state
        self.zoom = 1.0
        self.offset = [0.0, 0.0]
        self.tex_width = 1
        self.tex_height = 1
        
        # Create a persistent texture registry
        with dpg.texture_registry(tag="tex_registry"):
            # Initial 1x1 black placeholder
            dpg.add_dynamic_texture(width=1, height=1, default_value=[0.0, 0.0, 0.0, 1.0], tag=self.active_texture_tag)

        self._setup_ui()
        self._setup_handlers()

    def _setup_ui(self):
        # File dialog for reference selection
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._on_load_reference, tag="ref_file_dialog", width=600, height=400):
            dpg.add_file_extension(".TIS", color=[255, 255, 0, 255])
            dpg.add_file_extension(".*")

        with dpg.window(label="TIS Troubleshooter", tag="main_window", no_close=True):
            with dpg.group(horizontal=True):
                # Sidebar for controls
                with dpg.child_window(width=200):
                    dpg.add_text("Game Setup")
                    found_games = [g.game_id for g in self.loader.install_finder.find_all()]
                    dpg.add_combo(
                        label="Game", 
                        items=found_games, 
                        default_value=self.loader.default_game,
                        callback=self._on_game_change,
                        tag="game_select"
                    )
                    dpg.add_separator()
                    
                    dpg.add_text("TIS Selection")
                    dpg.add_input_text(label="Filter", callback=self._filter_resources, tag="filter_input")
                    dpg.add_listbox(items=[], num_items=15, tag="tis_list", callback=self._on_tis_select)
                    
                    dpg.add_separator()
                    dpg.add_text("Metadata", color=[255, 255, 0])
                    self.meta_sig = dpg.add_text("Sig: -")
                    self.meta_count = dpg.add_text("Tiles: -")
                    self.meta_block = dpg.add_text("Block: -")
                    self.meta_dim = dpg.add_text("Dim: -")

                    dpg.add_separator()
                    dpg.add_text("Integrity", color=[255, 100, 100])
                    self.int_source = dpg.add_text("Src: -", wrap=180)
                    self.int_phys = dpg.add_text("Phys Size: -")
                    self.int_exp = dpg.add_text("Exp Size: -")
                    self.int_offset = dpg.add_text("Offset: -")
                    dpg.add_button(label="Print Header Hex", callback=self._print_header_hex)

                    dpg.add_separator()
                    dpg.add_text("Reference Comparison", color=[100, 255, 100])
                    self.ref_path_text = dpg.add_text("Ref: -", wrap=180)
                    self.comp_result = dpg.add_text("Match: -")
                    dpg.add_button(label="Load Reference TIS", callback=lambda: dpg.show_item("ref_file_dialog"))
                    dpg.add_button(label="Clear Reference", callback=self._clear_reference)

                    dpg.add_separator()
                    dpg.add_text("Inspector", color=[0, 255, 255])
                    self.inspect_coord = dpg.add_text("Pixel: -")
                    self.inspect_tile = dpg.add_text("Tile: -")

                    dpg.add_slider_int(label="Grid Width", min_value=1, max_value=40, default_value=10, tag="grid_width", callback=self._update_display)

                    dpg.add_separator()
                    dpg.add_text("Canvas Controls")
                    dpg.add_button(label="Reset View", callback=self._reset_view)
                    dpg.add_button(label="Load Test Pattern", callback=self._load_test_pattern)
                    dpg.add_separator()
                    dpg.add_text("Navigation:", color=[200, 200, 200])
                    dpg.add_text("Middle Mouse: Pan", color=[150, 150, 255])
                    dpg.add_text("Scroll: Zoom", color=[150, 150, 255])
                    dpg.add_separator()
                    self.status_text = dpg.add_text("Status: Idle", color=[0, 255, 0])
                
                # Canvas for rendering
                with dpg.child_window(tag="canvas_parent", width=-1, height=-1):
                    dpg.add_drawlist(tag="canvas_drawlist", width=800, height=600)
                    dpg.draw_rectangle([-10000, -10000], [10000, 10000], fill=[30, 30, 30, 255], parent="canvas_drawlist")
                    dpg.draw_image(self.active_texture_tag, [0, 0], [1, 1], tag="canvas_image", parent="canvas_drawlist")
                    dpg.draw_rectangle([0, 0], [1, 1], color=[255, 0, 255, 255], thickness=2, tag="canvas_border", parent="canvas_drawlist")

    def _on_game_change(self, sender=None, app_data=None):
        game = dpg.get_value("game_select")
        if not game:
            dpg.set_value(self.status_text, "Status: No game selected")
            return
            
        dpg.set_value(self.status_text, f"Status: Scanning {game}...")
        
        # Collect all unique TIS resrefs for the given game
        resrefs = {resref for resref, restype, _ in self.loader.iter_resources(game=game) if restype == "TIS"}
        self.all_tis_resrefs = sorted(list(resrefs))
        self._filter_resources()
        dpg.set_value(self.status_text, f"Status: {game} ready")

    def _filter_resources(self):
        query = dpg.get_value("filter_input").upper()
        self.filtered_resrefs = [r for r in self.all_tis_resrefs if query in r.upper()]
        dpg.configure_item("tis_list", items=self.filtered_resrefs)

    def _on_tis_select(self, sender, app_data):
        self.selected_resref = app_data
        self._update_display()

    def _update_display(self):
        if not self.selected_resref:
            return

        game = dpg.get_value("game_select")
        grid_width = dpg.get_value("grid_width")

        # 1. Load the resource
        resource = self.loader.load(resref=self.selected_resref, restype="TIS", game=game)
        
        if not resource:
            dpg.set_value(self.status_text, "Status: Load Failed")
            return

        # 2. Update Metadata UI
        sig = resource.get("signature")
        ver = resource.get("version")
        count = resource.get("count_of_tiles")
        block_size = resource.get("tile_data_block_size")
        dim = resource.get("tile_dimension")
        offset_to_tiles = resource.get("offset_to_tiles") or 0
        flavor = "PVRZ (EE)" if block_size == 12 else "Palette (Classic)" if block_size == 5120 else "Unknown"

        # Integrity Calculations
        raw_bytes = getattr(resource, "_original_bytes", b"")
        phys_size = len(raw_bytes)
        expected_size = (count * block_size) + offset_to_tiles
        delta = phys_size - expected_size

        dpg.set_value(self.status_text, f"Status: Decoding {self.selected_resref}...")
        dpg.set_value(self.meta_sig, f"Sig: {sig} / {ver}")
        dpg.set_value(self.meta_count, f"Tiles: {count}")
        dpg.set_value(self.meta_block, f"Block: {block_size} ({flavor})")
        dpg.set_value(self.meta_dim, f"Dim: {dim}x{dim}")

        dpg.set_value(self.int_source, f"Src: {resource.source}")
        dpg.set_value(self.int_phys, f"Phys: {phys_size:,} bytes")
        dpg.set_value(self.int_exp, f"Exp: {expected_size:,} ({'+' if delta >= 0 else ''}{delta})")
        dpg.set_value(self.int_offset, f"Tile Offset: {offset_to_tiles}")

        # Update comparison if a reference is loaded
        self._run_comparison()

        # 3. Handle PVRZ Page Resolution (for EE games)
        pvrz_provider = self._get_pvrz_provider(game, self.selected_resref)

        # 4. Decode the TIS into a linear grid
        # We limit the decode to a reasonable number of tiles for a troubleshooter tool
        max_tiles = min(count, 500) 
        rgba_buffer = self.decoder.decode_tis(
            resource, 
            grid_width=grid_width, 
            pvrz_page_provider=pvrz_provider,
            source_tile_limit=max_tiles
        )

        if rgba_buffer is not None:
            self._upload_to_canvas(rgba_buffer)
            dpg.set_value(self.status_text, f"Status: {rgba_buffer.shape[1]}x{rgba_buffer.shape[0]} rendered")
        else:
            dpg.set_value(self.status_text, "Status: Decode Failed")

    def _get_pvrz_provider(self, game, tis_name):
        """Standard naming convention for PVRZ pages: e.g. AR2600 -> A2600xx"""
        prefix = tis_name[0] + tis_name[2:6]
        if len(tis_name) > 6 and tis_name[6] == 'N':
            prefix += 'N'

        def provider(page_index):
            resref = f"{prefix}{page_index:02d}"
            res = self.loader.load(resref=resref, restype="PVRZ", game=game)
            return res._original_bytes if res else None
        return provider

    def _upload_to_canvas(self, rgba_buffer):
        """Converts NumPy RGBA [0-255] to DPG Float RGBA [0.0-1.0] and updates texture."""
        h, w, _ = rgba_buffer.shape

        # Normalize to 0.0-1.0 float32 for DPG
        flat_buffer = rgba_buffer.ravel().astype(np.float32) / 255.0

        # If size matches, update existing texture to avoid alias collisions and performance overhead
        if dpg.does_item_exist(self.active_texture_tag) and w == self.tex_width and h == self.tex_height:
            dpg.set_value(self.active_texture_tag, flat_buffer)
        else:
            # Size changed or item missing: Create new texture with UUID to prevent "Alias already exists"
            old_tag = self.active_texture_tag
            self.active_texture_tag = dpg.generate_uuid()
            
            dpg.add_dynamic_texture(
                width=w, 
                height=h, 
                default_value=flat_buffer, 
                tag=self.active_texture_tag, 
                parent="tex_registry"
            )
            
            if old_tag and dpg.does_item_exist(old_tag):
                dpg.delete_item(old_tag)

        # Always ensure the drawing item is linked to the current texture ID
        dpg.configure_item("canvas_image", texture_tag=self.active_texture_tag)

        self.tex_width, self.tex_height = w, h
        self._redraw()

    def _setup_handlers(self):
        with dpg.handler_registry():
            dpg.add_mouse_wheel_handler(callback=self._on_mouse_wheel)
            dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_down)
            dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_drag)
            dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Middle, callback=self._on_mouse_release)

    def _on_mouse_wheel(self, sender, data):
        if not dpg.is_item_hovered("canvas_parent"): return
        zoom_speed = 0.1
        self.zoom = max(0.1, self.zoom + data * zoom_speed)
        self._redraw()

    def _on_mouse_down(self, sender, data):
        if dpg.is_item_hovered("canvas_parent"):
            self.pan_start_offset = list(self.offset)
            self.is_panning = True

    def _on_mouse_drag(self, sender, data):
        if self.is_panning:
            # data is [button, total_delta_x, total_delta_y] from drag start
            self.offset[0] = self.pan_start_offset[0] + data[1]
            self.offset[1] = self.pan_start_offset[1] + data[2]
            self._redraw()

    def _on_mouse_release(self, sender, data):
        self.is_panning = False

    def _reset_view(self):
        self.zoom = 1.0
        self.offset = [0.0, 0.0]
        self._redraw()

    def _redraw(self):
        if not dpg.does_item_exist("canvas_drawlist"): return

        # Match drawlist size to parent window
        cw = dpg.get_item_width("canvas_parent")
        ch = dpg.get_item_height("canvas_parent")
        if cw > 0 and ch > 0:
            dpg.configure_item("canvas_drawlist", width=cw, height=ch)

        # Calculate centering base offset
        img_w = self.tex_width * self.zoom
        img_h = self.tex_height * self.zoom
        
        bx = (cw - img_w) / 2
        by = (ch - img_h) / 2

        pmin = [bx + self.offset[0], by + self.offset[1]]
        pmax = [pmin[0] + img_w, pmin[1] + img_h]

        dpg.configure_item("canvas_image", pmin=pmin, pmax=pmax)
        dpg.configure_item("canvas_border", pmin=pmin, pmax=pmax)

    def _on_resize(self):
        self._redraw()

    def _print_header_hex(self, sender, app_data):
        """Prints the first 48 bytes of the current TIS to the terminal for inspection."""
        if not self.selected_resref:
            return

        game = dpg.get_value("game_select")
        resource = self.loader.load(resref=self.selected_resref, restype="TIS", game=game)
        
        if resource:
            raw_bytes = getattr(resource, "_original_bytes", b"")
            header_chunk = raw_bytes[:48]
            
            print(f"\n--- Raw Header Hex: {self.selected_resref} ---")
            for i in range(0, len(header_chunk), 16):
                chunk = header_chunk[i:i+16]
                hex_str = chunk.hex(' ').upper()
                ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
                print(f"{i:04X} | {hex_str:<47} | {ascii_str}")
            print("------------------------------------------\n")

    def _on_load_reference(self, sender, app_data):
        """Callback when a reference file is selected."""
        file_path = app_data['file_path_name']
        try:
            self.reference_bytes = Path(file_path).read_bytes()
            dpg.set_value(self.ref_path_text, f"Ref: {Path(file_path).name}")
            self._run_comparison()
        except Exception as e:
            dpg.set_value(self.comp_result, f"Error: {str(e)}")

    def _clear_reference(self):
        """Clears the current reference data."""
        self.reference_bytes = None
        dpg.set_value(self.ref_path_text, "Ref: -")
        dpg.set_value(self.comp_result, "Match: -")

    def _run_comparison(self):
        """Compares current resource bytes to loaded reference bytes."""
        if not self.selected_resref or self.reference_bytes is None:
            return
            
        game = dpg.get_value("game_select")
        resource = self.loader.load(resref=self.selected_resref, restype="TIS", game=game)
        if not resource: return
        
        current_bytes = getattr(resource, "_original_bytes", b"")
        ref_bytes = self.reference_bytes
        
        match = (current_bytes == ref_bytes)
        size_match = (len(current_bytes) == len(ref_bytes))
        
        if match:
            dpg.set_value(self.comp_result, "Match: EXACT")
        else:
            res_str = f"Match: FAIL ({'Size' if not size_match else 'Bytes'})"
            dpg.set_value(self.comp_result, res_str)
            
            # Detailed output to terminal for troubleshooting
            print(f"\n--- Binary Diff: {self.selected_resref} vs {dpg.get_value(self.ref_path_text)} ---")
            min_len = min(len(current_bytes), len(ref_bytes))
            mismatch_idx = next((i for i in range(min_len) if current_bytes[i] != ref_bytes[i]), -1)
            
            if mismatch_idx != -1:
                print(f"First mismatch at offset: 0x{mismatch_idx:04X} ({mismatch_idx})")
                print(f"BIF Data: {current_bytes[mismatch_idx:mismatch_idx+8].hex(' ').upper()}")
                print(f"Ref File: {ref_bytes[mismatch_idx:mismatch_idx+8].hex(' ').upper()}")
            elif not size_match:
                print(f"Mismatch type: Length (BIF: {len(current_bytes)} vs Ref: {len(ref_bytes)})")

    def _handle_inspector(self):
        """Calculates which tile is under the mouse based on canvas transforms."""
        if not dpg.is_item_hovered("canvas_parent") or self.tex_width <= 1:
            return

        # Get mouse pos relative to the drawlist
        mx, my = dpg.get_drawing_mouse_pos()
        cw = dpg.get_item_width("canvas_parent")
        ch = dpg.get_item_height("canvas_parent")
        grid_width = dpg.get_value("grid_width")

        # Reverse the centering and offset logic from _redraw
        bx = (cw - self.tex_width * self.zoom) / 2
        by = (ch - self.tex_height * self.zoom) / 2
        
        local_x = (mx - bx - self.offset[0]) / self.zoom
        local_y = (my - by - self.offset[1]) / self.zoom

        if 0 <= local_x < self.tex_width and 0 <= local_y < self.tex_height:
            tile_x = int(local_x // 64)
            tile_y = int(local_y // 64)
            tile_idx = tile_y * grid_width + tile_x
            dpg.set_value(self.inspect_coord, f"Pixel: {int(local_x)}, {int(local_y)}")
            dpg.set_value(self.inspect_tile, f"Tile Index: {tile_idx}")

    def _load_test_pattern(self):
        """Generates a 512x512 grid pattern to verify the canvas logic."""
        w, h = 512, 512
        # Generate RGB gradient using numpy
        x = np.linspace(0, 255, w)
        y = np.linspace(0, 255, h)
        xv, yv = np.meshgrid(x, y)
        
        # Stack into RGBA (uint8)
        buffer = np.stack([xv, yv, np.full_like(xv, 128), np.full_like(xv, 255)], axis=-1).astype(np.uint8)

        # Draw a white 32px grid for visual reference
        buffer[::32, :, :3] = 255
        buffer[:, ::32, :3] = 255

        self._upload_to_canvas(buffer)

    def run(self):
        print("Initializing TIS Troubleshooter UI...")
        dpg.create_viewport(title="TIS Troubleshooter", width=1200, height=800)
        dpg.setup_dearpygui()
        dpg.set_primary_window("main_window", True)
        dpg.show_viewport()
        dpg.maximize_viewport()
        dpg.set_viewport_resize_callback(self._on_resize)

        # Initial load of resource list once DPG is running and viewport is visible
        print("Running initial game scan...")
        self._on_game_change()
        self._redraw()

        print("TIS Troubleshooter loop started.")
        while dpg.is_dearpygui_running():
            self._handle_inspector()
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

if __name__ == "__main__":
    TISTroubleshooter().run()