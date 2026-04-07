import sys
from pathlib import Path

# Add the project root to sys.path so 'drivers' and 'core' can be found when running standalone
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import dearpygui.dearpygui as dpg
from drivers.InfinityEngine.resource_loader import ResourceLoader
from drivers.InfinityEngine.graphics.bam_decoder import BamDecoder
from drivers.InfinityEngine.graphics.tis_decoder import TisDecoder
from canvas import PFCanvas

class ImageViewerApp:
    def __init__(self):
        self.loader = ResourceLoader()
        self.bam_decoder = BamDecoder()
        self.tis_decoder = TisDecoder()
        self.all_resrefs = []
        
        dpg.create_context()
        self.canvas = PFCanvas()
        self._setup_ui()

        self._refresh_resource_list()

        dpg.create_viewport(title="PlanarForgeV2 - Image Viewer", width=1200, height=800)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def _setup_ui(self):
        with dpg.window(label="Controls", width=300, height=700, no_close=True):
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
                items=["BAM", "TIS"], 
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

            self.resref_input = dpg.add_input_text(label="ResRef", default_value="GMISC01", readonly=True)
            dpg.add_button(label="Load Resource", callback=self._load_resource)
            
            dpg.add_separator()
            dpg.add_slider_float(label="Zoom", min_value=0.1, max_value=10.0, default_value=1.0, 
                                callback=lambda s, v: self.canvas.set_zoom(v - self.canvas.zoom))

        with dpg.window(label="Canvas", pos=[305, 0], width=895, height=800, no_scrollbar=True):
            dpg.add_drawlist(tag="image_canvas", width=-1, height=-1)

    def _on_list_selection(self, sender, app_data):
        dpg.set_value(self.resref_input, app_data)
        self._load_resource()

    def _load_resource(self):
        resref = dpg.get_value(self.resref_input)
        restype = dpg.get_value(self.restype_input)
        game = dpg.get_value(self.game_input)
        
        resource = self.loader.load(resref=resref, restype=restype, game=game)
        print(resource)
        if not resource:
            print(f"Failed to load {resref}.{restype}")
            return

        buffer = None
        if "BAM" in resource.schema.name: # Handles BAM and BAM_V2
            buffer = self.bam_decoder.decode_frame(resource, 0)
        elif restype == "TIS":
            # For TIS, we need a palette. We'll try to find a BAM with the same name or use default.
            pal_res = self.loader.load(resref=resref, restype="BAM", game=game)
            buffer = self.tis_decoder.decode_tis(resource, palette_resource=pal_res)

        if buffer is not None:
            self.canvas.update_texture(buffer)

    def _refresh_resource_list(self):
        game = dpg.get_value(self.game_input)
        target_type = dpg.get_value(self.restype_input)
        
        # Collect all unique resrefs for the given game and type
        resrefs = {resref for resref, restype, _ in self.loader.iter_resources(game=game) if restype == target_type}
        self.all_resrefs = sorted(list(resrefs))
        self._filter_list()

    def _filter_list(self):
        filter_text = dpg.get_value(self.filter_input).upper()
        filtered = [r for r in self.all_resrefs if filter_text in r]
        dpg.configure_item(self.resource_list, items=filtered)

    def run(self):
        while dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

if __name__ == "__main__":
    app = ImageViewerApp()
    app.run()
