"""Tests for game discovery (issue #57). Uses temporary directories and a fake registry."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from drivers.InfinityEngine.io import installation_finder as finder


def make_game(root, *parts):
    """Creates a directory holding an empty CHITIN.KEY and returns it."""
    path = Path(root).joinpath(*parts)
    path.mkdir(parents=True)
    (path / "chitin.key").write_bytes(b"")
    return path


class SteamTests(unittest.TestCase):
    def probe(self, library):
        with mock.patch.object(finder, "winreg", object()), \
                mock.patch.object(finder, "_steam_library_roots", return_value=[Path(library)]):
            return {inst.game_id: inst for inst in finder._probe_steam()}

    def test_pstee_in_its_current_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = make_game(tmp, "steamapps", "common", "Planescape Torment Enhanced Edition")
            self.assertEqual(self.probe(tmp)["PSTEE"].install_path, game)

    def test_pstee_in_the_legacy_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = make_game(tmp, "steamapps", "common", "Project P")
            self.assertEqual(self.probe(tmp)["PSTEE"].install_path, game)

    def test_current_folder_wins_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_game(tmp, "steamapps", "common", "Project P")
            current = make_game(tmp, "steamapps", "common", "Planescape Torment Enhanced Edition")
            found = list(self.probe_all(tmp))
            self.assertEqual([i.install_path for i in found if i.game_id == "PSTEE"], [current])

    def probe_all(self, library):
        with mock.patch.object(finder, "winreg", object()), \
                mock.patch.object(finder, "_steam_library_roots", return_value=[Path(library)]):
            return list(finder._probe_steam())

    def test_other_games_are_still_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_game(tmp, "steamapps", "common", "Baldur's Gate II Enhanced Edition")
            make_game(tmp, "steamapps", "common", "Icewind Dale Enhanced Edition")
            self.assertEqual(sorted(self.probe(tmp)), ["BG2EE", "IWDEE"])

    def test_a_folder_without_chitin_key_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "steamapps" / "common" / "Project P").mkdir(parents=True)
            self.assertEqual(self.probe(tmp), {})


class GogTests(unittest.TestCase):
    def probe(self, registry):
        """Runs the GOG probe against ``registry``: {key path: install path}."""
        def fake_value(_hive, key_path, value_name):
            return registry.get(key_path) if value_name == "path" else None

        with mock.patch.object(finder, "winreg", mock.Mock()), \
                mock.patch.object(finder, "_registry_value", side_effect=fake_value):
            return {inst.game_id: inst for inst in finder._probe_gog()}

    def test_verified_ids_find_their_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {game: make_game(tmp, game) for game in ("BG2EE", "IWDEE", "PSTEE", "PST")}
            registry = {finder._GOG_KEY % ids[0]: paths[game]
                        for game, ids in finder._GOG_PRODUCT_IDS.items() if game in paths}
            found = self.probe(registry)
            self.assertEqual({game: inst.install_path for game, inst in found.items()}, paths)

    def test_documented_product_ids(self):
        ids = finder._GOG_PRODUCT_IDS
        self.assertEqual((ids["BG2EE"], ids["IWDEE"], ids["PSTEE"], ids["PST"]),
                         (("1207666373",), ("1207666683",), ("1132393016",), ("1207658887",)))

    def test_no_two_games_share_a_product_id(self):
        all_ids = [i for ids in finder._GOG_PRODUCT_IDS.values() for i in ids]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_wow6432node_hive_is_tried(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = make_game(tmp, "PSTEE")
            native = finder._GOG_KEY % "1132393016"
            registry = {native.replace("SOFTWARE\\", "SOFTWARE\\Wow6432Node\\", 1): game}
            self.assertEqual(self.probe(registry)["PSTEE"].install_path, game)

    def test_missing_registry_entries_find_nothing(self):
        self.assertEqual(self.probe({}), {})


if __name__ == "__main__":
    unittest.main()
