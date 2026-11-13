"""Headless TIS / WED diagnostic.

Prints text-only facts about one or more TIS resources and the WED that maps
them, so a rendering problem can be narrowed to a layer (TIS records, PVRZ
pages, WED parsing, WED-to-TIS mapping) and compared against Near Infinity.

Nothing is rendered and no game data is written to disk (except the optional
--out report, which holds only numbers and resrefs; keep it outside the repo,
see docs/Game-Asset-Policy.md).

Usage (from the repo root):
    python tools/tis_diagnostic.py AR0072 AR0016 --game BG2EE
    python tools/tis_diagnostic.py AR0072 --overlay 0 --cells 20 --out ../ar0072.txt

The analysis functions are pure (they take plain data) so they can be tested
without game files; only main() touches an installation.
"""
import argparse
import struct
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

NO_PAGE = 0xFFFFFFFF
TILE_SIZE = 64
PALETTE_TILE_DATA_SIZE = 5120
PVRZ_TILE_DATA_SIZE = 12
TILEMAP_ENTRY_BYTES = 10
LOOKUP_ENTRY_BYTES = 2


# --------------------------------------------------------------------------
# WED: independent raw read (does not use the schema parser)
# --------------------------------------------------------------------------

def parse_wed_raw(raw):
    """Read the WED header, overlays and the tilemap/lookup arrays straight from
    the bytes, using the field layout in wed_v1_3.yaml. Returns a dict, or a dict
    with an "error" key if the data is too short to be a WED."""
    if raw is None or len(raw) < 32:
        return {"error": "WED data shorter than the 32-byte header"}

    u32 = lambda off: struct.unpack_from("<I", raw, off)[0]
    header = {
        "signature": bytes(raw[0:4]).decode("latin-1"),
        "version": bytes(raw[4:8]).decode("latin-1"),
        "count_of_overlays": u32(0x08),
        "count_of_doors": u32(0x0C),
        "offset_to_overlays": u32(0x10),
        "offset_to_secondary_header": u32(0x14),
        "offset_to_doors": u32(0x18),
        "offset_to_door_tile_cell_indices": u32(0x1C),
    }

    overlays = []
    base = header["offset_to_overlays"]
    for i in range(min(header["count_of_overlays"], 16)):
        off = base + i * 24
        if off + 24 > len(raw):
            break
        width, height = struct.unpack_from("<HH", raw, off)
        name = bytes(raw[off + 4:off + 12]).split(b"\x00", 1)[0].decode("latin-1")
        unique, movement = struct.unpack_from("<HH", raw, off + 12)
        tm_off, lk_off = struct.unpack_from("<II", raw, off + 16)
        overlays.append({
            "width": width, "height": height, "tileset_name": name.upper(),
            "unique_tile_count": unique, "movement_type": movement,
            "offset_to_tilemap": tm_off, "offset_to_tile_index_lookup": lk_off,
        })

    sec = {}
    sec_off = header["offset_to_secondary_header"]
    if 0 < sec_off and sec_off + 20 <= len(raw):
        sec = {
            "offset_to_polygons": u32(sec_off + 4),
            "offset_to_vertices": u32(sec_off + 8),
            "offset_to_wall_groups": u32(sec_off + 12),
            "offset_to_polygon_index_lookup": u32(sec_off + 16),
        }

    result = {"header": header, "overlays": overlays, "secondary": sec,
              "file_size": len(raw), "tilemap_room": None, "lookup_room": None,
              "tilemaps": [], "lookup": [], "boundaries": []}
    if not overlays:
        return result

    tm_off = overlays[0]["offset_to_tilemap"]
    lk_off = overlays[0]["offset_to_tile_index_lookup"]

    # Physical room: bytes between a section's start and the next known offset
    # in the file. Informational; the boundaries used are listed in the report.
    named = {"file_end": len(raw)}
    for k in ("offset_to_doors", "offset_to_door_tile_cell_indices", "offset_to_secondary_header"):
        named[k] = header[k]
    named.update(sec)
    result["boundaries"] = sorted((v, k) for k, v in named.items() if v > 0)

    def room(start, entry_bytes):
        later = [v for v, _ in result["boundaries"] if v > start]
        if not later:
            return None
        return (min(later) - start) // entry_bytes

    if tm_off > 0:
        result["tilemap_room"] = room(tm_off, TILEMAP_ENTRY_BYTES)
        n = result["tilemap_room"] or 0
        n = min(n, (len(raw) - tm_off) // TILEMAP_ENTRY_BYTES)
        for i in range(n):
            p, c, s, flags, speed, unk = struct.unpack_from("<HHHBBH", raw, tm_off + i * TILEMAP_ENTRY_BYTES)
            result["tilemaps"].append({
                "primary_tile_index": p, "primary_tile_count": c,
                "secondary_tile_index": s, "draw_overlays": flags,
                "animation_speed": speed, "unknown": unk,
            })
    if lk_off > 0:
        result["lookup_room"] = room(lk_off, LOOKUP_ENTRY_BYTES)
        n = result["lookup_room"] or 0
        n = min(n, (len(raw) - lk_off) // LOOKUP_ENTRY_BYTES)
        result["lookup"] = list(struct.unpack_from("<%dH" % n, raw, lk_off)) if n > 0 else []
    return result


def check_overlay_layout(overlays):
    """Compare each overlay's declared offsets with the offsets implied by
    packing the overlays one after another. Returns a list of (overlay_index,
    message) for anything that does not line up."""
    notes = []
    if not overlays:
        return notes
    tm0 = overlays[0]["offset_to_tilemap"]
    lk0 = overlays[0]["offset_to_tile_index_lookup"]
    cum_cells = 0
    for i, ov in enumerate(overlays):
        cells = ov["width"] * ov["height"]
        tm_delta = ov["offset_to_tilemap"] - tm0
        lk_delta = ov["offset_to_tile_index_lookup"] - lk0
        if tm_delta < 0 or tm_delta % TILEMAP_ENTRY_BYTES:
            notes.append((i, "tilemap offset is not a whole number of 10-byte entries after overlay 0's"))
        elif tm_delta // TILEMAP_ENTRY_BYTES != cum_cells:
            notes.append((i, "tilemap starts at entry %d, but the overlays before it hold %d cells"
                          % (tm_delta // TILEMAP_ENTRY_BYTES, cum_cells)))
        if lk_delta < 0 or lk_delta % LOOKUP_ENTRY_BYTES:
            notes.append((i, "lookup offset is not a whole number of 2-byte entries after overlay 0's"))
        cum_cells += cells
    return notes


# --------------------------------------------------------------------------
# WED -> TIS mapping, spec-literal
# --------------------------------------------------------------------------

def analyze_mapping(overlays, tilemaps, lookup, tis_count, overlay_idx, detail_cells=8):
    """Resolve every cell of one overlay in the most literal way:

        cell -> tilemaps[tilemap_start + cell]
             -> lookup[entry.primary_tile_index]       (absolute index)
             -> TIS tile index

    Assumption (check against IESDP / Near Infinity): primary_tile_index is an
    index into the single lookup array that starts at overlay 0's
    offset_to_tile_index_lookup, and the overlay's tilemap starts at
    (its offset_to_tilemap - overlay 0's) / 10 entries.

    `tilemaps` are dicts with primary_tile_index / primary_tile_count; `lookup`
    is a list of ints (or dicts with tis_index).
    """
    ov = overlays[overlay_idx]
    width, height = ov["width"], ov["height"]
    cells = width * height
    tm0 = overlays[0]["offset_to_tilemap"]
    tm_delta = ov["offset_to_tilemap"] - tm0
    tm_start = tm_delta // TILEMAP_ENTRY_BYTES if tm_delta >= 0 else 0

    lk = [(e.get("tis_index") if isinstance(e, dict) else e) for e in lookup]

    reasons = {"ok": 0, "no_tilemap_entry": 0, "lookup_out_of_range": 0, "tis_out_of_range": 0}
    tis_indices = []
    first_unresolved = None
    max_tis, min_tis = -1, None
    identity = 0
    animated_cells = 0
    required_lookup = 0
    detail = []

    for cell in range(cells):
        tm_idx = tm_start + cell
        reason, lookup_idx, tis = "ok", -1, -1
        prim, count = None, None
        if tm_idx < 0 or tm_idx >= len(tilemaps):
            reason = "no_tilemap_entry"
        else:
            tm = tilemaps[tm_idx]
            prim = int(tm.get("primary_tile_index", 0) or 0)
            count = int(tm.get("primary_tile_count", 0) or 0)
            required_lookup = max(required_lookup, prim + max(count, 1))
            if count > 1:
                animated_cells += 1
            lookup_idx = prim
            if lookup_idx < 0 or lookup_idx >= len(lk):
                reason = "lookup_out_of_range"
            else:
                tis = int(lk[lookup_idx])
                if tis < 0 or (tis_count and tis >= tis_count):
                    reason = "tis_out_of_range"
        reasons[reason] += 1
        if reason == "ok":
            max_tis = max(max_tis, tis)
            min_tis = tis if min_tis is None else min(min_tis, tis)
            if tis == cell:
                identity += 1
        elif first_unresolved is None:
            first_unresolved = {"cell": cell, "row": cell // width if width else 0,
                                "col": cell % width if width else 0, "reason": reason}
        # Keep the raw lookup value when the TIS has no such tile, so it compares like for like
        # with the viewer (which also keeps it); only truly unresolvable cells become -1.
        tis_indices.append(tis if reason in ("ok", "tis_out_of_range") else -1)
        if len(detail) < detail_cells:
            detail.append({"cell": cell, "tm_idx": tm_idx, "primary": prim, "count": count,
                           "lookup_idx": lookup_idx, "tis_index": tis, "status": reason})

    return {
        "overlay": overlay_idx, "width": width, "height": height, "cells": cells,
        "tilemap_start": tm_start, "reasons": reasons, "first_unresolved": first_unresolved,
        "max_tis_index": max_tis, "min_tis_index": min_tis,
        "identity_cells": identity, "animated_cells": animated_cells,
        "required_lookup_entries": required_lookup,
        "tis_indices": tis_indices, "detail": detail,
    }


def compare_mappings(literal_indices, viewer_indices):
    """Compare two per-cell index lists. Returns (differing_count, first_diff_cell)."""
    diff, first = 0, None
    for i, (a, b) in enumerate(zip(literal_indices, viewer_indices)):
        if int(a) != int(b):
            diff += 1
            if first is None:
                first = i
    diff += abs(len(literal_indices) - len(viewer_indices))
    return diff, first


# --------------------------------------------------------------------------
# TIS tile records
# --------------------------------------------------------------------------

def parse_pvrz_records(raw, offset, count):
    """Read `count` 12-byte (page, x, y) records at `offset` from raw bytes."""
    if raw is None or offset is None or offset < 0 or count <= 0:
        return []
    available = max(0, (len(raw) - offset) // PVRZ_TILE_DATA_SIZE)
    n = min(count, available)
    return [struct.unpack_from("<III", raw, offset + i * PVRZ_TILE_DATA_SIZE) for i in range(n)]


def analyze_pvrz_records(records, page_dims=None):
    """Summarise tile records. `page_dims` maps page number -> (width, height) for
    pages that could be decoded; pages missing from it count as not decoded."""
    page_dims = page_dims or {}
    pages = {}
    none_count = 0
    unaligned = 0
    max_x = max_y = 0
    out_of_bounds = 0
    for page, x, y in records:
        if page == NO_PAGE:
            none_count += 1
            continue
        pages[page] = pages.get(page, 0) + 1
        max_x, max_y = max(max_x, x), max(max_y, y)
        if x % TILE_SIZE or y % TILE_SIZE:
            unaligned += 1
        dims = page_dims.get(page)
        if dims and (x + TILE_SIZE > dims[1] or y + TILE_SIZE > dims[0]):
            out_of_bounds += 1
    return {"records": len(records), "no_page": none_count, "pages": dict(sorted(pages.items())),
            "unaligned": unaligned, "max_x": max_x, "max_y": max_y, "out_of_bounds": out_of_bounds}


def pvrz_page_candidates(tis_name, page_index):
    """Candidate PVRZ resrefs for a TIS page. Copied from the viewer's
    _get_tis_pvrz_page_provider; keep the two in sync."""
    tis_name = tis_name.upper()
    prefix = tis_name[0] + tis_name[2:6]
    if len(tis_name) > 6 and tis_name[6] == "N":
        prefix += "N"
    out = []

    def add(r):
        if r and r not in out:
            out.append(r)

    add(f"{prefix}{page_index:02d}")
    if len(tis_name) >= 6:
        add(f"{tis_name[:6]}{page_index:02d}")
    if page_index >= 10:
        add(f"{prefix}{page_index:02X}")
        if len(tis_name) >= 6:
            add(f"{tis_name[:6]}{page_index:02X}")
    add(f"MOS{page_index:04d}")
    return out


# --------------------------------------------------------------------------
# BIF tileset table
# --------------------------------------------------------------------------

def analyze_bif_table(file_size, file_entries_offset, file_entries, tileset_entries_offset, tileset_entries):
    """Describe each tileset entry of a BIF and how much room its data has.

    file_entries: list of dicts with offset/size.  tileset_entries: list of dicts
    with offset/tile_count/tile_size.  For every tileset entry this reports where
    its data ends, where the next known structure starts, the slack between the
    two (negative means the data overlaps something) and how many tiles would
    fit up to the next structure."""
    starts = {file_size, file_entries_offset, tileset_entries_offset}
    starts.update(e["offset"] for e in file_entries if e["offset"] > 0)
    starts.update(e["offset"] for e in tileset_entries if e["offset"] > 0)
    out = []
    for i, e in enumerate(tileset_entries):
        data_end = e["offset"] + e["tile_count"] * e["tile_size"]
        later = [v for v in starts if v > e["offset"]]
        next_start = min(later) if later else file_size
        fit = (next_start - e["offset"]) // e["tile_size"] if e["tile_size"] else 0
        out.append({"index": i, "offset": e["offset"], "tile_count": e["tile_count"], "tile_size": e["tile_size"],
                    "data_end": data_end, "next_start": next_start, "slack_bytes": next_start - data_end,
                    "tiles_that_fit": fit})
    return out


def read_bif_table(path):
    """Read the BIF V1 header, file entries and tileset entries from a file."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(0)
        head = fh.read(20)
        if len(head) < 20 or head[:4] != b"BIFF":
            return {"error": "not a BIFF file"}
        file_count, tileset_count, fe_off = struct.unpack_from("<III", head, 8)
        fh.seek(fe_off)
        fblob = fh.read(file_count * 16)
        files = []
        for i in range(len(fblob) // 16):
            _loc, off, sz = struct.unpack_from("<III", fblob, i * 16)
            files.append({"offset": off, "size": sz})
        ts_off = fe_off + file_count * 16
        tblob = fh.read(tileset_count * 20)
        tilesets = []
        for i in range(len(tblob) // 20):
            _loc, off, cnt, tsz = struct.unpack_from("<IIII", tblob, i * 20)
            tilesets.append({"offset": off, "tile_count": cnt, "tile_size": tsz})
    return {"file_size": size, "file_count": file_count, "tileset_count": tileset_count,
            "file_entries_offset": fe_off, "tileset_entries_offset": ts_off,
            "files": files, "tilesets": tilesets}


def report_bif_table(rep, loader, game, entry, declared_count):
    """Dump the BIF tileset table around this TIS, plus the KEY entries that point into it."""
    try:
        path = loader._find_bif_file(entry, game)
    except Exception as exc:
        rep.add("  BIF lookup failed: %r" % (exc,))
        return
    if not path:
        rep.add("  BIF file not found")
        return
    info = read_bif_table(path)
    if "error" in info:
        rep.flag("BIF table: " + info["error"])
        return
    rep.section("BIF tileset table (%s)" % Path(str(path)).name)
    rep.add("  file size=%d, file entries=%d, tileset entries=%d" % (
        info["file_size"], info["file_count"], info["tileset_count"]))
    rows = analyze_bif_table(info["file_size"], info["file_entries_offset"], info["files"],
                             info["tileset_entries_offset"], info["tilesets"])
    mine = (entry.get("resource_locator") or {}).get("tileset_index")
    for r in rows:
        mark = "  <== this TIS" if r["index"] == mine else ""
        rep.add("  tileset %d: offset=0x%X tiles=%d x %d bytes, data ends 0x%X, next structure 0x%X, "
                "slack=%d bytes, tiles that would fit=%d%s" % (
                    r["index"], r["offset"], r["tile_count"], r["tile_size"], r["data_end"],
                    r["next_start"], r["slack_bytes"], r["tiles_that_fit"], mark))
        if r["slack_bytes"] < 0:
            rep.flag("BIF tileset %d data overlaps the next structure by %d bytes" % (r["index"], -r["slack_bytes"]))
        if r["index"] == mine and r["tiles_that_fit"] > r["tile_count"]:
            rep.flag("BIF tileset %d declares %d tiles but %d would fit before the next structure"
                     % (r["index"], r["tile_count"], r["tiles_that_fit"]))
    # KEY entries that point into this BIF's tilesets
    try:
        locator = entry.get("resource_locator") or {}
        bif_index = locator.get("bif_index")
        chitin = loader.chitins.get(game)
        tis_code = 1003
        found = []
        for e in chitin.sections.get("resource_entries", []):
            if int(e.get("resource_type", -1)) != tis_code:
                continue
            loc = e.get("resource_locator") or {}
            if loc.get("bif_index") == bif_index:
                found.append((loc.get("tileset_index"), loc.get("resource_index"), str(e.get("resource_name"))))
        found.sort(key=lambda t: (t[0] is None, t[0], t[1] is None, t[1]))
        rep.add("  KEY entries (TIS) in this BIF: " + ", ".join(
            "%s(ts=%s,res=%s)" % (n, ts, ri) for ts, ri, n in found))
    except Exception as exc:
        rep.add("  KEY entries lookup failed: %r" % (exc,))


# --------------------------------------------------------------------------
# Report helpers
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.lines = []
        self.flags = []

    def add(self, text=""):
        self.lines.append(text)

    def section(self, title):
        self.lines.append("")
        self.lines.append("== " + title)

    def flag(self, text):
        self.flags.append(text)
        self.lines.append("  !! " + text)

    def render(self):
        out = list(self.lines)
        out.append("")
        out.append("== SUMMARY OF FLAGS (%d)" % len(self.flags))
        out.extend("  - " + f for f in self.flags) if self.flags else out.append("  (none)")
        return "\n".join(out)


def report_wed_raw(rep, wed_raw, parsed_counts):
    if "error" in wed_raw:
        rep.flag("WED raw read failed: " + wed_raw["error"])
        return
    h = wed_raw["header"]
    rep.add("  header: %s %s, overlays=%d doors=%d, file size=%d bytes" % (
        h["signature"], h["version"], h["count_of_overlays"], h["count_of_doors"], wed_raw["file_size"]))
    rep.add("  section offsets: " + ", ".join("%s=0x%X" % (k, v) for v, k in wed_raw["boundaries"]))
    cells_total = 0
    for i, ov in enumerate(wed_raw["overlays"]):
        cells_total += ov["width"] * ov["height"]
        rep.add("  overlay %d: %s %dx%d (%d cells) unique=%d move=%d tilemap@0x%X lookup@0x%X" % (
            i, ov["tileset_name"] or "(unnamed)", ov["width"], ov["height"], ov["width"] * ov["height"],
            ov["unique_tile_count"], ov["movement_type"], ov["offset_to_tilemap"],
            ov["offset_to_tile_index_lookup"]))
    for i, msg in check_overlay_layout(wed_raw["overlays"]):
        rep.flag("overlay %d layout: %s" % (i, msg))

    rep.add("  sum of overlay cells: %d" % cells_total)
    rep.add("  tilemap entries: parsed by schema=%s, physical room in file=%s, read raw=%d" % (
        parsed_counts.get("tilemaps"), wed_raw["tilemap_room"], len(wed_raw["tilemaps"])))
    rep.add("  lookup entries:  parsed by schema=%s, physical room in file=%s, read raw=%d" % (
        parsed_counts.get("lookup"), wed_raw["lookup_room"], len(wed_raw["lookup"])))
    if parsed_counts.get("tilemaps") is not None and parsed_counts["tilemaps"] < cells_total:
        rep.flag("schema parsed %d tilemap entries but the overlays declare %d cells"
                 % (parsed_counts["tilemaps"], cells_total))
    pl = parsed_counts.get("lookup")
    if pl is not None and wed_raw["lookup_room"] is not None and pl < wed_raw["lookup_room"]:
        rep.add("  note: file has room for more lookup entries than the schema parsed "
                "(room is bounded by the next known section offset, so it can overcount).")


def run_one(loader, game, resref, args):
    """Produce the full report for one TIS resref."""
    rep = Report()
    resref = resref.upper()
    rep.add("#" * 72)
    rep.add("TIS %s  (game %s)" % (resref, game))

    install = None
    try:
        install = loader._get_install_path(game)
    except Exception:
        pass

    def override_exists(name, ext):
        return bool(install and (Path(install) / "override" / f"{name}.{ext.lower()}").exists())

    # ---- TIS resource -----------------------------------------------------
    rep.section("TIS resource")
    tis = loader.load(resref=resref, restype="TIS", game=game)
    if tis is None:
        rep.flag("could not load TIS %s" % resref)
        return rep
    raw = getattr(tis, "_original_bytes", None)
    schema_name = getattr(getattr(tis, "schema", None), "name", None)
    count = int(tis.get("count_of_tiles") or 0)
    block = tis.get("tile_data_block_size")
    offset = tis.get("offset_to_tiles")
    dim = tis.get("tile_dimension")
    rep.add("  schema=%s  count_of_tiles=%s  tile_data_block_size=%s  offset_to_tiles=%s  tile_dimension=%s"
            % (schema_name, count, block, offset, dim))
    rep.add("  source=%s  bytes=%s  override file present=%s" % (
        getattr(tis, "source", "?"), len(raw) if raw is not None else None, override_exists(resref, "tis")))
    if dim not in (None, TILE_SIZE):
        rep.flag("tile_dimension is %s; the decoder assumes %d" % (dim, TILE_SIZE))

    bif_entry = None
    try:
        entry = loader._find_exact_resource_location(resref, "TIS", game)
        if entry:
            loc = entry.get("resource_locator") or {}
            rep.add("  key locator: bif_index=%s tileset_index=%s resource_index=%s" % (
                loc.get("bif_index"), loc.get("tileset_index"), loc.get("resource_index")))
            est = loader._estimate_tis_tile_count(entry, game)
            rep.add("  tile count estimated from the BIFF pool (distance to next TIS): %s" % est)
            bif_entry = entry
            if est is not None and est != count:
                rep.flag("header count_of_tiles=%d but the pool estimate is %d" % (count, est))
        else:
            rep.add("  no CHITIN.KEY entry (probably an override file)")
    except Exception as exc:
        rep.add("  key locator lookup failed: %r" % (exc,))

    page_dims = {}
    if block == PVRZ_TILE_DATA_SIZE:
        records = parse_pvrz_records(raw, offset, count)
        tiles_section = tis.get_section("tiles") or []
        rep.add("  PVRZ records: raw read=%d, schema parsed=%d (expected %d)" % (len(records), len(tiles_section), count))
        if len(records) < count:
            rep.flag("only %d of %d tile records fit in the TIS bytes" % (len(records), count))
        if tiles_section and len(tiles_section) != len(records):
            rep.flag("schema parsed %d tile records but raw read gives %d" % (len(tiles_section), len(records)))
        if not args.no_pages:
            page_dims = decode_pages(rep, loader, game, resref, sorted({r[0] for r in records if r[0] != NO_PAGE}),
                                     override_exists)
        stats = analyze_pvrz_records(records, page_dims)
        rep.add("  records: %d, solid-black (0xFFFFFFFF) %d, distinct pages %d, max x=%d max y=%d, x/y not multiple of 64: %d"
                % (stats["records"], stats["no_page"], len(stats["pages"]), stats["max_x"], stats["max_y"], stats["unaligned"]))
        rep.add("  tiles per page: " + ", ".join("%d:%d" % kv for kv in stats["pages"].items()))
        if stats["unaligned"]:
            rep.add("  note: %d records have x or y that is not a multiple of 64 (seen in areas that render correctly, "
                    "so informational only)" % stats["unaligned"])
        if stats["out_of_bounds"]:
            rep.flag("%d tile records point outside their decoded page" % stats["out_of_bounds"])
        rep.add("  first records (page,x,y): " + ", ".join("(%d,%d,%d)" % r for r in records[:6]))
    elif block == PALETTE_TILE_DATA_SIZE:
        need = (offset or 0) + count * PALETTE_TILE_DATA_SIZE
        rep.add("  palette tiles: need %d bytes, have %s" % (need, len(raw) if raw is not None else None))
        if raw is not None and len(raw) < need:
            rep.flag("TIS bytes (%d) are shorter than %d tiles of 5,120 bytes need (%d)" % (len(raw), count, need))
    else:
        rep.flag("tile_data_block_size %s is neither 5120 (palette) nor 12 (PVRZ); the decoder returns nothing" % (block,))

    if bif_entry and not getattr(args, "no_bif", False):
        report_bif_table(rep, loader, game, bif_entry, count)

    # ---- WED ---------------------------------------------------------------
    rep.section("WED %s" % resref)
    wed = loader.load(resref=resref, restype="WED", game=game)
    if wed is None:
        rep.add("  no WED with this name (the viewer would fall back to a plain grid)")
        return rep
    wed_raw_bytes = getattr(wed, "_original_bytes", None)
    wed_raw = parse_wed_raw(wed_raw_bytes)
    overlays_parsed = wed.get_section("overlays") or []
    tilemaps_parsed = wed.get_section("tilemaps") or []
    lookup_parsed = wed.get_section("tile_index_lookup") or []
    rep.add("  override file present=%s" % override_exists(resref, "wed"))
    report_wed_raw(rep, wed_raw, {"tilemaps": len(tilemaps_parsed), "lookup": len(lookup_parsed)})
    if "error" in wed_raw or not wed_raw["overlays"]:
        return rep

    # ---- mapping -----------------------------------------------------------
    viewer_choice, viewer_note = viewer_overlay_choice(loader, game, tis, overlays_parsed, args)
    overlay_idx = args.overlay if args.overlay is not None else (viewer_choice if viewer_choice is not None else 0)
    if overlay_idx >= len(wed_raw["overlays"]):
        rep.flag("overlay %d does not exist" % overlay_idx)
        return rep
    rep.section("Mapping for overlay %d (viewer would choose %s)" % (overlay_idx, viewer_choice))
    if viewer_note:
        rep.add("  " + viewer_note)

    # Use the schema-parsed sections for the literal mapping (what the viewer
    # sees), and the raw read as a second opinion on how much data exists.
    ov_for_map = wed_raw["overlays"]
    lit = analyze_mapping(ov_for_map, tilemaps_parsed, lookup_parsed, count, overlay_idx, args.cells)
    describe_mapping(rep, lit, "spec-literal on schema-parsed sections")
    lit_raw = analyze_mapping(ov_for_map, wed_raw["tilemaps"], wed_raw["lookup"], count, overlay_idx, 0)
    describe_mapping(rep, lit_raw, "spec-literal on raw-read sections", brief=True)
    if lit["required_lookup_entries"] > len(lookup_parsed):
        rep.flag("tilemap entries reference up to lookup entry %d but the schema parsed only %d lookup entries"
                 % (lit["required_lookup_entries"], len(lookup_parsed)))
    if lit["required_lookup_entries"] > lit["cells"]:
        rep.add("  note: lookup needs %d entries for %d cells (animated or multi-frame cells use consecutive entries), "
                "so the lookup length is not width*height" % (lit["required_lookup_entries"], lit["cells"]))

    if not args.no_viewer:
        vinfo, vnote = viewer_mapping(loader, game, tis, overlay_idx)
        if vinfo is None:
            rep.add("  viewer mapping not available: %s" % vnote)
        else:
            diff, first = compare_mappings(lit["tis_indices"], vinfo["tile_indices"])
            unresolved = int((vinfo["tile_indices"] < 0).sum())
            rep.add("  viewer mapping: mode=%s resolved=%s/%s non-black=%s max-idx=%s unresolved cells=%d"
                    % (vinfo.get("mapping_mode"), vinfo.get("resolved_count"), vinfo.get("cell_count"),
                       vinfo.get("non_black_count"), vinfo.get("max_tis_index"), unresolved))
            rep.add("  viewer vs spec-literal: %d of %d cells differ%s" % (
                diff, lit["cells"], "" if first is None else " (first at cell %d, row %d col %d)" % (
                    first, first // lit["width"], first % lit["width"])))
            if diff:
                rep.flag("viewer mapping differs from the spec-literal mapping in %d cells" % diff)
    return rep


def describe_mapping(rep, m, label, brief=False):
    r = m["reasons"]
    rep.add("  [%s] overlay %d: %dx%d = %d cells, tilemap start entry %d" % (
        label, m["overlay"], m["width"], m["height"], m["cells"], m["tilemap_start"]))
    rep.add("    resolved ok=%d, no tilemap entry=%d, lookup index out of range=%d, TIS index out of range=%d" % (
        r["ok"], r["no_tilemap_entry"], r["lookup_out_of_range"], r["tis_out_of_range"]))
    fu = m["first_unresolved"]
    if fu:
        rep.add("    first unresolved cell: %d (row %d, col %d) because: %s" % (
            fu["cell"], fu["row"], fu["col"], fu["reason"].replace("_", " ")))
        if not brief:
            rep.flag("%d of %d cells unresolved; first at cell %d (%s)" % (
                m["cells"] - r["ok"], m["cells"], fu["cell"], fu["reason"].replace("_", " ")))
    rep.add("    TIS index range used: %s..%s; cells where TIS index == cell number: %d; multi-frame cells: %d; "
            "lookup entries needed: %d" % (m["min_tis_index"], m["max_tis_index"], m["identity_cells"],
                                            m["animated_cells"], m["required_lookup_entries"]))
    if not brief and m["detail"]:
        rep.add("    first cells (cell: tilemap idx -> primary/count -> lookup idx -> TIS idx):")
        for d in m["detail"]:
            rep.add("      %d: tm %s -> %s/%s -> lk %s -> tis %s  [%s]" % (
                d["cell"], d["tm_idx"], d["primary"], d["count"], d["lookup_idx"], d["tis_index"], d["status"]))


def decode_pages(rep, loader, game, tis_name, pages, override_exists):
    """Load and decode each referenced PVRZ page once. Returns {page: (h, w)}."""
    from drivers.InfinityEngine.graphics.pvrz_decoder import PvrzDecoder
    available = {resref for resref, restype, _ in loader.iter_resources(game=game) if restype == "PVRZ"}
    dims = {}
    missing = []
    rep.add("  PVRZ pages referenced: %d (naming copied from the viewer's provider)" % len(pages))
    for page in pages:
        found = None
        for cand in pvrz_page_candidates(tis_name, page):
            if cand in available:
                found = cand
                break
        if found is None:
            missing.append(page)
            continue
        try:
            res = loader.load(resref=found, restype="PVRZ", game=game)
            img = PvrzDecoder.decode_pvrz_bytes(res._original_bytes)
            dims[page] = tuple(img.shape[:2])
            rep.add("    page %d -> %s: decoded %dx%d%s" % (
                page, found, img.shape[1], img.shape[0], "  (override file)" if override_exists(found, "pvrz") else ""))
        except Exception as exc:
            rep.flag("page %d (%s) failed to decode: %r" % (page, found, exc))
    if missing:
        rep.flag("PVRZ pages with no matching resource: %s" % ", ".join(map(str, missing)))
    return dims


def _viewer_app(loader):
    """Build a bare ImageViewerApp (no window) so its mapping code can be called."""
    vdir = project_root / "tools" / "image_viewer"
    if str(vdir) not in sys.path:
        sys.path.insert(0, str(vdir))   # app.py does a bare 'from canvas import ...' (issue #40)
    from tools.image_viewer.app import ImageViewerApp
    app = ImageViewerApp.__new__(ImageViewerApp)
    app.loader = loader
    app._tis_wed_map_cache = {}
    app._tis_wed_metadata_cache = {}
    return app


def viewer_overlay_choice(loader, game, tis, overlays, args):
    if args.no_viewer:
        return None, None
    try:
        app = _viewer_app(loader)
        choice = app._choose_overlay_for_tis(tis.name, overlays)
        how = "by tileset name"
        if choice is None:
            choice = app._choose_best_overlay_for_tis(game, tis, overlays)
            how = "by best-resolving score"
        return choice, "viewer overlay choice made %s" % how
    except Exception as exc:
        return None, "viewer overlay choice unavailable: %r" % (exc,)


def viewer_mapping(loader, game, tis, overlay_idx):
    try:
        app = _viewer_app(loader)
        info = app._get_tis_wed_map_info(game, tis, overlay_idx)
        if info is None:
            return None, "viewer returned no mapping"
        return info, None
    except Exception as exc:
        return None, "%r (needs dearpygui installed; the window is not opened)" % (exc,)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Text-only TIS/WED diagnostic (see module docstring).")
    ap.add_argument("resrefs", nargs="+", help="TIS resrefs, e.g. AR0072 AR0016")
    ap.add_argument("--game", default=None, help="game key as used by the viewer (default: loader default)")
    ap.add_argument("--overlay", type=int, default=None, help="overlay to map (default: the viewer's choice)")
    ap.add_argument("--cells", type=int, default=8, help="how many leading cells to list in detail")
    ap.add_argument("--no-pages", action="store_true", help="skip loading/decoding PVRZ pages")
    ap.add_argument("--no-bif", action="store_true", help="skip the BIF tileset table dump")
    ap.add_argument("--no-viewer", action="store_true", help="skip the comparison with the viewer's mapping")
    ap.add_argument("--out", default=None, help="also write the report to this file (keep it outside the repo)")
    args = ap.parse_args(argv)

    from drivers.InfinityEngine.resource_loader import ResourceLoader
    loader = ResourceLoader()
    game = args.game or loader.default_game

    texts = []
    for resref in args.resrefs:
        try:
            texts.append(run_one(loader, game, resref, args).render())
        except Exception as exc:
            import traceback
            texts.append("#" * 72 + "\nTIS %s: diagnostic crashed: %r\n%s" % (resref, exc, traceback.format_exc()))
    output = "\n\n".join(texts)
    print(output)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
