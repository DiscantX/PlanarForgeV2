"""Headless PVRZ scan: checks every PVRZ page in a game against the documented layout.

The documented layout is: a 4-byte little-endian uncompressed size, then one
zlib stream holding a PVR v3 file (52-byte header, optional metadata, texture
data). Desktop Enhanced Edition pages are DXT1 or DXT5 (IESDP "PVRZ file
format"; PVR File Format Specification 3.0.0). This tool reports, per page and
in summary, where the real files agree or disagree, so the decoder can be
narrowed to what actually occurs (issue #39).

Only numbers and resrefs are reported; no pixel data is decoded or written.
Keep --out and --csv files outside the repo (docs/Game-Asset-Policy.md).

Usage (from the repo root):
    python tools/pvrz_scan.py --game BG2EE --out ../pvrz_scan.txt --csv ../pvrz_scan.csv

The analysis functions are pure (they take bytes) so they can be tested without
game files; only main() touches an installation.
"""
import argparse
import collections
import contextlib
import csv
import io
import struct
import sys
import zlib
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

PVR3_MAGIC = 0x03525650
PVR2_TAG = 0x21525650
HEADER_SIZE = 52
# PVR 3.0.0 pixel format value -> (name, bytes per 4x4 block).
BLOCK_FORMATS = {7: ("DXT1", 8), 9: ("DXT3", 16), 11: ("DXT5", 16)}
CSV_COLUMNS = ["resref", "bytes", "layout", "size_field", "decompressed", "trailing", "nested_zlib",
               "magic", "pixel_format", "format", "width", "height", "mips", "metadata", "texture_bytes",
               "top_level_bytes", "full_chain_bytes", "data_vs_expected", "old_inference", "inference_agrees"]


def _try_layouts(raw):
    """Finds the first way ``raw`` decompresses, documented layout first.

    Args:
        raw: The PVRZ file bytes.

    Returns:
        A ``(layout, data, trailing)`` tuple. ``layout`` is one of
        ``"size+zlib"`` (documented), ``"zlib"``, ``"size+deflate"``,
        ``"deflate"``, ``"PVRZ+zlib"``, ``"uncompressed"`` or
        ``"unrecognised"``; ``data`` is the decompressed bytes (or None);
        ``trailing`` is the number of bytes left after the stream (or None).
    """
    attempts = [("size+zlib", 4, zlib.MAX_WBITS), ("zlib", 0, zlib.MAX_WBITS),
                ("size+deflate", 4, -15), ("deflate", 0, -15)]
    if raw[:4] == b"PVRZ":
        attempts.insert(2, ("PVRZ+zlib", 4, zlib.MAX_WBITS))
    for layout, start, wbits in attempts:
        stream = zlib.decompressobj(wbits)
        try:
            data = stream.decompress(raw[start:])
        except zlib.error:
            continue
        if stream.eof:
            return layout, data, len(stream.unused_data)
    if raw[:4] in (b"PVR\x03", b"DDS "):
        return "uncompressed", raw, 0
    return "unrecognised", None, None


def _level_bytes(width, height, block_bytes):
    """Returns the byte size of one mip level of a block-compressed texture."""
    return ((width + 3) // 4) * ((height + 3) // 4) * block_bytes


def _full_chain_bytes(width, height, block_bytes):
    """Returns the byte size of every mip level down to 1x1, largest first."""
    total = 0
    while True:
        total += _level_bytes(width, height, block_bytes)
        if width == 1 and height == 1:
            return total
        width, height = max(1, width // 2), max(1, height // 2)


def analyze_pvrz(raw, infer_compression=None):
    """Describes how one PVRZ file compares with the documented layout.

    Args:
        raw: The PVRZ file bytes.
        infer_compression: Optional ``f(width, height, data_size)`` returning
            ``"DXT1"``, ``"DXT5"`` or None; pass the decoder's current
            data-size inference to see where it disagrees with the header's
            pixel format.

    Returns:
        A dict of facts (see ``CSV_COLUMNS``). Keys that do not apply are
        absent. Contains no pixel data.
    """
    row = {"bytes": len(raw)}
    if len(raw) < 5:
        row["layout"] = "too small"
        return row

    row["size_field"] = struct.unpack_from("<I", raw, 0)[0]
    layout, data, trailing = _try_layouts(raw)
    row["layout"], row["trailing"] = layout, trailing
    if data is None:
        return row
    row["decompressed"] = len(data)
    try:
        zlib.decompress(data)
        row["nested_zlib"] = True
    except zlib.error:
        row["nested_zlib"] = False

    if len(data) < HEADER_SIZE:
        row["magic"] = "too small"
        return row
    magic = struct.unpack_from("<I", data, 0)[0]
    row["magic"] = "PVR3" if magic == PVR3_MAGIC else (
        "PVR2" if struct.unpack_from("<I", data, 44)[0] == PVR2_TAG else
        "DDS" if data[:4] == b"DDS " else "0x%08X" % magic)
    if magic != PVR3_MAGIC:
        return row

    (_, _, pixel_format, _, _, height, width, _, _, _, mips, metadata) = struct.unpack_from("<IIQ9I", data, 0)
    texture_bytes = len(data) - HEADER_SIZE - metadata
    row.update(pixel_format=pixel_format, width=width, height=height, mips=mips, metadata=metadata,
               texture_bytes=texture_bytes)
    name, block_bytes = BLOCK_FORMATS.get(pixel_format, (None, None))
    row["format"] = name or "other"
    if block_bytes:
        top, chain = _level_bytes(width, height, block_bytes), _full_chain_bytes(width, height, block_bytes)
        row.update(top_level_bytes=top, full_chain_bytes=chain,
                   data_vs_expected="top level" if texture_bytes == top else
                   "full chain" if texture_bytes == chain else "other")
    if infer_compression:
        row["old_inference"] = infer_compression(width, height, texture_bytes)
        row["inference_agrees"] = row["old_inference"] == name
    return row


def summarize(rows):
    """Aggregates per-page facts into counts and example lists.

    Args:
        rows: A list of ``(resref, facts)`` pairs from ``analyze_pvrz``.

    Returns:
        A dict with ``total``, ``counts`` (a dict of Counter objects keyed by
        category) and ``examples`` (category -> list of resrefs).
    """
    counts = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    for resref, facts in rows:
        layout = facts.get("layout")
        counts["layout"][layout] += 1
        if layout != "size+zlib":
            examples["layout other than the documented size+zlib"].append(resref)
        else:
            equal = facts["size_field"] == facts["decompressed"]
            counts["size field equals decompressed length"][equal] += 1
            if not equal:
                examples["size field differs from decompressed length"].append(resref)
            if facts["trailing"]:
                examples["bytes after the zlib stream"].append(resref)
            counts["data is itself zlib-compressed"][facts["nested_zlib"]] += 1
        if "magic" not in facts:
            continue
        counts["header"][facts["magic"]] += 1
        if facts["magic"] != "PVR3":
            examples["not a PVR v3 header"].append(resref)
            continue
        counts["pixel format"][facts["format"] + " (%d)" % facts["pixel_format"]] += 1
        counts["mip levels"][facts["mips"]] += 1
        counts["metadata bytes"][facts["metadata"]] += 1
        counts["size"]["%dx%d" % (facts["width"], facts["height"])] += 1
        counts["texture data vs expected"][facts.get("data_vs_expected", "n/a")] += 1
        if facts["format"] == "other":
            examples["pixel format other than DXT1/DXT3/DXT5"].append(resref)
        if facts.get("inference_agrees") is False:
            examples["old size-based inference disagrees with pixel format"].append(resref)
    return {"total": len(rows), "counts": counts, "examples": examples}


def render(summary, game, limit=25):
    """Formats a ``summarize`` result as text."""
    out = ["#" * 72, "PVRZ SCAN  (game %s)" % game, "", "  PVRZ pages scanned: %d" % summary["total"]]
    for title, counter in summary["counts"].items():
        out.append("")
        out.append("  %s:" % title)
        out.extend("    %s: %d" % (key, n) for key, n in counter.most_common())
    for title, names in summary["examples"].items():
        out.append("")
        out.append("  %s: %d" % (title, len(names)))
        out.extend("    " + n for n in names[:limit])
        if len(names) > limit:
            out.append("    ... and %d more" % (len(names) - limit))
    if not summary["examples"]:
        out.append("")
        out.append("  No deviations from the documented layout found.")
    return "\n".join(out)


def write_csv(path, rows):
    """Writes one row of facts per page to ``path``."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for resref, facts in rows:
            writer.writerow(dict(facts, resref=resref))


def scan_game(loader, game, infer_compression=None):
    """Analyses every PVRZ resource listed in the game's KEY file.

    Args:
        loader: A ``ResourceLoader``.
        game: Game key, e.g. ``"BG2EE"``.
        infer_compression: Passed through to ``analyze_pvrz``.

    Returns:
        A list of ``(resref, facts)`` pairs. Pages whose bytes cannot be read
        get ``{"layout": "unreadable"}``.
    """
    names = sorted({resref for resref, restype, _ in loader.iter_resources(game=game) if restype == "PVRZ"})
    rows = []
    for n, resref in enumerate(names):
        if n and n % 500 == 0:
            print("  PVRZ page %d/%d ..." % (n, len(names)), file=sys.stderr)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                raw, _source, _code = loader.get_raw_bytes(resref, restype="PVRZ", game=game)
        except Exception:
            raw = None
        rows.append((resref, analyze_pvrz(raw, infer_compression) if raw else {"layout": "unreadable"}))
    return rows


def main(argv=None):
    """Runs the scan against an installed game and prints the report."""
    parser = argparse.ArgumentParser(description="Text-only PVRZ scan (see module docstring).")
    parser.add_argument("--game", default=None, help="game key as used by the viewer (default: loader default)")
    parser.add_argument("--csv", default=None, help="write one row per page to this file")
    parser.add_argument("--limit", type=int, default=25, help="examples to list per category")
    parser.add_argument("--out", default=None, help="also write the report to this file (outside the repo)")
    args = parser.parse_args(argv)

    from drivers.InfinityEngine.graphics.pvrz_decoder import PvrzDecoder
    from drivers.InfinityEngine.resource_loader import ResourceLoader
    loader = ResourceLoader()
    game = args.game or loader.default_game

    rows = scan_game(loader, game, PvrzDecoder._infer_compression)
    if args.csv:
        write_csv(args.csv, rows)
    output = render(summarize(rows), game, args.limit)
    print(output)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
