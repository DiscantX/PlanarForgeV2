"""
core/installation.py

Locate Infinity Engine game installations and their CHITIN.KEY files.

Supports every major distribution channel:
    - Steam          (any library folder, not just the default)
    - GOG Galaxy
    - Beamdog client (standalone EE launcher)
    - CD/classic retail installs (registry keys left by the original installers)

Supported games:
    Original:  BG1, BG2, IWD, IWD2, PST
    Enhanced:  BGEE, BG2EE, IWDEE, PSTEE

On non-Windows platforms all registry probes are skipped and only
manually-supplied paths can be used.

Usage::

    from core.installation import InstallationFinder, GameInstallation

    finder = InstallationFinder()

    # All installed games:
    for inst in finder.find_all():
        print(inst)

    # One specific game:
    inst = finder.find("BG2EE")         # GameInstallation or None

    # Just the CHITIN.KEY path:
    chitin = finder.find_chitin("IWDEE")  # Path or None

    # Re-scan after installing a new game:
    finder.rescan()

    # Or probe a known path directly, bypassing the scan:
    inst = GameInstallation.from_path("BG2EE", "/path/to/bg2ee")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

# winreg is Windows-only; import it behind a guard so the module loads on
# Linux/macOS too (useful for development and cross-platform tooling).
if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Game identity catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GameInfo:
    """Static metadata about one IE game title."""
    game_id:      str   # Short identifier used throughout the codebase
    display_name: str   # Human-readable title
    is_ee:        bool  # True for Enhanced Edition titles


#: Every game the editor understands, keyed by game_id.
KNOWN_GAMES: dict[str, GameInfo] = {
    "BG1":   GameInfo("BG1",   "Baldur's Gate",                          is_ee=False),
    "BG2":   GameInfo("BG2",   "Baldur's Gate II: Shadows of Amn",       is_ee=False),
    "IWD":   GameInfo("IWD",   "Icewind Dale",                           is_ee=False),
    "IWD2":  GameInfo("IWD2",  "Icewind Dale II",                        is_ee=False),
    "PST":   GameInfo("PST",   "Planescape: Torment",                    is_ee=False),
    "BGEE":  GameInfo("BGEE",  "Baldur's Gate: Enhanced Edition",        is_ee=True),
    "BG2EE": GameInfo("BG2EE", "Baldur's Gate II: Enhanced Edition",     is_ee=True),
    "IWDEE": GameInfo("IWDEE", "Icewind Dale: Enhanced Edition",         is_ee=True),
    "PSTEE": GameInfo("PSTEE", "Planescape: Torment Enhanced Edition",   is_ee=True),
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GameInstallation:
    """
    A located game installation with a readable CHITIN.KEY.

    Attributes
    ----------
    game_id:      Short identifier, e.g. ``"BG2EE"``.
    display_name: Human-readable title.
    install_path: Root directory of the game (contains CHITIN.KEY).
    chitin_key:   Absolute path to the CHITIN.KEY file.
    source:       How the install was found: ``"steam"``, ``"gog"``,
                  ``"beamdog"``, ``"registry"``, or ``"manual"``.
    """
    game_id:      str
    display_name: str
    install_path: Path
    chitin_key:   Path
    source:       str

    @classmethod
    def from_path(
        cls,
        game_id: str,
        path:    str | Path,
        source:  str = "manual",
    ) -> Optional["GameInstallation"]:
        """
        Build a GameInstallation from a known directory path.

        Returns ``None`` if the directory does not contain a CHITIN.KEY.
        Useful for adding a game manually that the finder did not detect.
        """
        install_path = Path(path)
        chitin = _find_chitin(install_path)
        if chitin is None:
            return None
        info = KNOWN_GAMES.get(game_id)
        display = info.display_name if info else game_id
        return cls(
            game_id=game_id,
            display_name=display,
            install_path=install_path,
            chitin_key=chitin,
            source=source,
        )

    def __str__(self) -> str:
        return f"[{self.source}] {self.display_name} — {self.install_path}"


# ---------------------------------------------------------------------------
# Finder
# ---------------------------------------------------------------------------

class InstallationFinder:
    """
    Scans all known installation sources and provides lookup by game ID.

    The scan is performed lazily on the first call to any lookup method
    and the result is cached for subsequent calls.  Call :meth:`rescan`
    to discard the cache and probe the system again (e.g. after the user
    installs a new game or points the editor at a custom path).

    Sources are probed in priority order: Steam → GOG → Beamdog →
    classic registry.  If the same game is found by more than one source,
    the first discovery wins.

    Example::

        finder = InstallationFinder()

        for inst in finder.find_all():
            print(inst)

        inst   = finder.find("BG2EE")         # GameInstallation or None
        chitin = finder.find_chitin("IWDEE")  # Path or None
    """

    def __init__(self) -> None:
        self._cache: Optional[dict[str, GameInstallation]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_all(self) -> List[GameInstallation]:
        """Return every located installation, in discovery order."""
        return list(self._get_cache().values())

    def find(self, game_id: str) -> Optional[GameInstallation]:
        """Return the installation for *game_id*, or ``None`` if not found."""
        return self._get_cache().get(game_id)

    def find_chitin(self, game_id: str) -> Optional[Path]:
        """Return the CHITIN.KEY path for *game_id*, or ``None`` if not found."""
        inst = self.find(game_id)
        return inst.chitin_key if inst is not None else None

    def rescan(self) -> None:
        """Discard the cached results and force a fresh scan on next access."""
        self._cache = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_cache(self) -> dict[str, GameInstallation]:
        if self._cache is None:
            self._cache = self._scan()
        return self._cache

    def _scan(self) -> dict[str, GameInstallation]:
        """
        Probe all sources and return a game_id → GameInstallation mapping.

        Deduplication: the first source to find a given game_id wins,
        matching the priority order Steam → GOG → Beamdog → registry.
        """
        result: dict[str, GameInstallation] = {}

        def _add(inst: Optional[GameInstallation]) -> None:
            if inst is not None and inst.game_id not in result:
                result[inst.game_id] = inst

        for inst in _probe_steam():
            _add(inst)
        for inst in _probe_gog():
            _add(inst)
        for inst in _probe_beamdog():
            _add(inst)
        for inst in _probe_classic_registry():
            _add(inst)

        return result


# ---------------------------------------------------------------------------
# Steam discovery
# ---------------------------------------------------------------------------

#: Folder name inside the Steam library's steamapps/common/ directory.
_STEAM_FOLDER_NAMES: dict[str, str] = {
    "BGEE":  "Baldur's Gate Enhanced Edition",
    "BG2EE": "Baldur's Gate II Enhanced Edition",
    "IWDEE": "Icewind Dale Enhanced Edition",
    "PSTEE": "Project P",
    "IWD2":  "Icewind Dale 2",
}

def _probe_steam() -> Iterator[GameInstallation]:
    """Yield installations found in any Steam library folder."""
    if winreg is None:
        return

    for library_root in _steam_library_roots():
        common = library_root / "steamapps" / "common"
        if not common.is_dir():
            continue
        for game_id, folder_name in _STEAM_FOLDER_NAMES.items():
            inst = GameInstallation.from_path(
                game_id, common / folder_name, source="steam"
            )
            if inst is not None:
                yield inst


def _steam_library_roots() -> List[Path]:
    """
    Return all Steam library root paths configured on this machine.

    Steam stores its library folders in
    ``<SteamPath>/steamapps/libraryfolders.vdf``.  Each entry has a ``path``
    key that points to an additional library root.  We parse this file
    rather than relying on the default path so that games installed on
    secondary drives or custom locations are found.
    """
    roots: List[Path] = []

    steam_path = _registry_value(
        winreg.HKEY_CURRENT_USER,
        r"Software\Valve\Steam",
        "SteamPath",
    )
    if not steam_path:
        return roots

    steam_root = Path(steam_path)
    roots.append(steam_root)  # The Steam install dir is always a library root

    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        roots.extend(_parse_libraryfolders_vdf(vdf))

    return roots


def _parse_libraryfolders_vdf(vdf_path: Path) -> List[Path]:
    """
    Extract additional library paths from Steam's libraryfolders.vdf.

    The file uses Valve's KeyValues text format.  We do a minimal line-by-line
    parse rather than a full KV parser: we look for lines that contain a
    ``"path"`` key and extract the value.  This handles both the legacy
    (numeric-indexed) and the modern (object-with-path-key) formats.
    """
    paths: List[Path] = []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return paths

    for line in text.splitlines():
        stripped = line.strip()
        # Match:  "path"   "C:\\Games\\SteamLibrary"
        if stripped.startswith('"path"'):
            parts = stripped.split('"')
            # parts = ['', 'path', '\t\t', '<value>', '']
            if len(parts) >= 4:
                candidate = Path(parts[3])
                if candidate.is_dir() and candidate not in paths:
                    paths.append(candidate)

    return paths


# ---------------------------------------------------------------------------
# GOG discovery
# ---------------------------------------------------------------------------

#: Registry keys written by the GOG Galaxy installer, with the install-path
#: value name.  GOG uses HKLM so installations are system-wide.
_GOG_REGISTRY: dict[str, tuple[str, str]] = {
    "BGEE":  (r"SOFTWARE\GOG.com\Games\1207666353", "path"),
    "BG2EE": (r"SOFTWARE\GOG.com\Games\1207666443", "path"),
    "IWDEE": (r"SOFTWARE\GOG.com\Games\1207658930", "path"),
    "PSTEE": (r"SOFTWARE\GOG.com\Games\1441974336", "path"),
    "BG1":   (r"SOFTWARE\GOG.com\Games\1207658886", "path"),
    "BG2":   (r"SOFTWARE\GOG.com\Games\1207658920", "path"),
    "IWD":   (r"SOFTWARE\GOG.com\Games\1207658888", "path"),
    "IWD2":  (r"SOFTWARE\GOG.com\Games\1207658891", "path"),
    "PST":   (r"SOFTWARE\GOG.com\Games\1207658930", "path"),
}


def _probe_gog() -> Iterator[GameInstallation]:
    """Yield installations found via GOG Galaxy registry entries."""
    if winreg is None:
        return

    for game_id, (key_path, value_name) in _GOG_REGISTRY.items():
        # GOG writes to both the native and Wow6432Node hives on 64-bit Windows.
        path = _registry_value(winreg.HKEY_LOCAL_MACHINE, key_path, value_name)
        if not path:
            path = _registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path.replace("SOFTWARE\\", "SOFTWARE\\Wow6432Node\\", 1),
                value_name,
            )
        if path:
            inst = GameInstallation.from_path(game_id, path, source="gog")
            if inst is not None:
                yield inst


# ---------------------------------------------------------------------------
# Beamdog client discovery
# ---------------------------------------------------------------------------

#: Registry keys written by the Beamdog standalone client.
_BEAMDOG_REGISTRY: dict[str, tuple[str, str]] = {
    "BGEE":  (r"SOFTWARE\Beamdog\Games\00806", "AppPath"),
    "BG2EE": (r"SOFTWARE\Beamdog\Games\00783", "AppPath"),
    "IWDEE": (r"SOFTWARE\Beamdog\Games\00795", "AppPath"),
    "PSTEE": (r"SOFTWARE\Beamdog\Games\01521", "AppPath"),
}


def _probe_beamdog() -> Iterator[GameInstallation]:
    """Yield installations found via the Beamdog client registry entries."""
    if winreg is None:
        return

    for game_id, (key_path, value_name) in _BEAMDOG_REGISTRY.items():
        path = _registry_value(winreg.HKEY_LOCAL_MACHINE, key_path, value_name)
        if not path:
            path = _registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path.replace("SOFTWARE\\", "SOFTWARE\\Wow6432Node\\", 1),
                value_name,
            )
        if path:
            inst = GameInstallation.from_path(game_id, path, source="beamdog")
            if inst is not None:
                yield inst


# ---------------------------------------------------------------------------
# Classic / retail registry discovery
# ---------------------------------------------------------------------------

#: Registry keys left by original retail / CD-ROM installers.
_CLASSIC_REGISTRY: dict[str, tuple[str, str]] = {
    "BG1":           (r"SOFTWARE\BioWare\Baldur's Gate",                     "AppPath"),
    "BG1_interplay": (r"SOFTWARE\Interplay\Baldur's Gate",                   "AppPath"),
    "BG2":           (r"SOFTWARE\BioWare\Baldur's Gate II - Shadows of Amn", "AppPath"),
    "IWD":           (r"SOFTWARE\Black Isle\Icewind Dale",                   "AppPath"),
    "IWD2":          (r"SOFTWARE\Black Isle\Icewind Dale II",                "AppPath"),
    "PST":           (r"SOFTWARE\Black Isle\Planescape: Torment",            "AppPath"),
}


def _probe_classic_registry() -> Iterator[GameInstallation]:
    """
    Yield installations found via original retail installer registry keys.

    On 64-bit Windows the classic 32-bit installers wrote to the
    Wow6432Node hive, so we probe both locations.
    """
    if winreg is None:
        return

    for game_id, (key_path, value_name) in _CLASSIC_REGISTRY.items():
        # Normalise alternate keys (e.g. BG1_interplay → BG1)
        normalised_id = game_id.split("_")[0]

        path = _registry_value(winreg.HKEY_LOCAL_MACHINE, key_path, value_name)
        if not path:
            path = _registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path.replace("SOFTWARE\\", "SOFTWARE\\Wow6432Node\\", 1),
                value_name,
            )
        if path:
            inst = GameInstallation.from_path(normalised_id, path, source="registry")
            if inst is not None:
                yield inst


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

def _registry_value(hive: object, key_path: str, value_name: str) -> Optional[str]:
    """
    Read a single string value from the Windows registry.

    Returns ``None`` if the key or value does not exist, or if running on
    a non-Windows platform.
    """
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(hive, key_path) as key:  # type: ignore[call-overload]
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Filesystem helper
# ---------------------------------------------------------------------------

def _find_chitin(install_path: Path) -> Optional[Path]:
    """
    Return the path to CHITIN.KEY inside *install_path*, or ``None``.

    The filename is matched case-insensitively so that the function works
    on case-sensitive filesystems (Linux) where the file might be named
    ``chitin.key`` or ``Chitin.Key``.
    """
    if not install_path.is_dir():
        return None
    for child in install_path.iterdir():
        if child.name.lower() == "chitin.key" and child.is_file():
            return child
    return None


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

def main() -> None:
    finder = InstallationFinder()
    installations = finder.find_all()
    if not installations:
        print("No installations found.")
        return
    for inst in installations:
        print(inst)


if __name__ == "__main__":
    main()