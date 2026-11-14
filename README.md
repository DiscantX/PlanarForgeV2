# Planar Forge V2

Planar Forge is a modding and file-viewing tool for the Infinity Engine games: Baldur's Gate, Planescape: Torment, and the Icewind Dale series, including their Enhanced Editions.

Its central idea is that every binary file format is described once, in a YAML schema, and a generic parser and writer interpret those schemas. The goals are byte-perfect reading and writing of the original files, a cleaner project format for modders on top of that, and eventually an editor that exports WeiDU mods.

This is the second version of the repository, aimed to be (mostly) human edited so that its author can understand it.

## Status

The binary reading and writing layer is complete for the major formats, but the project is being revived after a period of inactivity, and the tileset (TIS) viewer is unfinished. The detailed, current picture is in [Project Status](docs/Project-Status.md).

## Documentation

Start at the [documentation index](docs/README.md). Useful entry points:

* [The Three-Layer Model](docs/The-Three-Layer-Model.md): the architecture
* [Project Structure](docs/Project-Structure.md): what each directory is for
* [Infinity Engine Format Notes](docs/Format-Notes.md): hard-won knowledge about the file formats
* [Workflow and Conventions](docs/Workflow-and-Conventions.md): how work is done here

## Requirements

* **Python 3.9 or newer.** The code was checked on Python 3.12.
* **A game installation** to do anything useful. Planar Forge reads the games in place and never copies game data into the repository. Installations are found automatically for Steam, GOG, Beamdog and classic retail installs (see `drivers/InfinityEngine/io/installation_finder.py`). Read the [Game Asset Policy](docs/Game-Asset-Policy.md) before adding any file to the repository.

## Setup

```bash
git clone https://github.com/DiscantX/PlanarForgeV2.git
cd PlanarForgeV2
python -m venv .venv
# Windows:  .venv\Scripts\activate      Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
```

For the command-line developer tools as well, use `pip install -r requirements-tools.txt`.

## Running

All commands are run from the repository root.

| Command | What it does |
|---------|--------------|
| `python tools/image_viewer/app.py` | Opens the image viewer for BAM and TIS resources (needs `dearpygui` and a game installation) |
| `python tools/tis_diagnostic.py AR0072 --game BG2EE` (or `--scan` for every TIS) | Text-only TIS/WED diagnostic: header, PVRZ page and WED mapping facts for one or more tilesets, for comparing with Near Infinity (needs a game installation; prints only resrefs, sizes, offsets and counts) |
| `python main.py FEMUR` | Loads an item from the game and writes it back out for a round-trip check (edit `target_game` in `main.py` first) |
| `python tools/tests/test_suite.py --help` | Round-trip fidelity suite against installed games |
| `python tools/resource_explorer.py` | Interactive resource browser (needs `requirements-tools.txt`) |
| `python tools/iesdp_converter.py --help` | Draft a YAML schema from an IESDP page (needs `requirements-tools.txt`); see [IESDP Converter](docs/IESDP-Converter.md) |

## Tests

Some unit tests need no game files:

```bash
python -m unittest tools.tests.test_tis_decoder tools.tests.test_table_resolver tools.tests.test_tlk_handler
```

These pass on a clean install. Other tests do not currently work out of the box:

* `tools.tests.test_pvrz_decoder` fails because of a known bug ([#13](https://github.com/DiscantX/PlanarForgeV2/issues/13)).
* `tools.tests.test_resource_serialization` needs a file produced by a manual run of `main.py` ([#14](https://github.com/DiscantX/PlanarForgeV2/issues/14)).
* `tools/tests/test_suite.py` needs installed games. The round-trip fidelity claims in the documentation come from this suite and can only be reproduced for games you have installed.

## Contributing

Every change begins with an issue and ends with a pull request that closes it. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

No licence has been chosen yet.
