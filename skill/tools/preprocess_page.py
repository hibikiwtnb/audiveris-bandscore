#!/usr/bin/env python3
"""Deterministic page preprocessing: crop the page down to the music area and
upscale so the staff interline reaches a scale Audiveris likes.

Follows the SKILL production chain:
    native raster -> remove low-info title/header band -> remove outer margins
                  -> proportional upscale (default 2x, capped to < 20 MP)

The top crop uses the "large white gap" method (no fixed pixel values): find the
first near-white horizontal band in the upper part of the page whose height is
at least --gap-frac of the page, and crop 1% of the page height above its lower
edge (still inside the band, so the music keeps some white above it).  This
removes the title while keeping tempo, rehearsal marks and chord symbols that
sit just above the first system.  This is for the first page of a song, whose title block takes
about half the page.  On the other pages (--no-title) the band is looked for in the top 10% only
(a running header), and nothing is cropped when there is none there: searched lower, the first
large band could be the one between two systems, and the whole first system was cut off (mu's
book, 004 p09).  A running header close to the music is kept:
its distance to the music differs between books (054: farther than a rehearsal
box, 132: closer), so no rule tells it from the music.

With --split the cropped page is cut in two at the widest white band in its middle
(30-70% of the height, between two systems: inside a system the system bracket and
barline keep every row inked), and each half is upscaled on its own (default 2.0x,
also < 20 MP; on 054 p02-p06, 2.0x gave 76 measures of wrong length, ~2.5x 94, and runs ~40% faster): OUT_a.png / OUT_b.png, and M_a.json / M_b.json, named <stem>a / <stem>b.
A page with no such band (a single system, a landscape page) is written whole.

Usage:
    preprocess_page.py IN.png OUT.png --meta M.json [--scale 2.0] [--no-title] [--split [--split-scale 2.0]]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

MAX_PIXELS = 19_800_000          # stay just under Audiveris' 20 MP hard limit


def row_ink(gray, thresh=200):
    """Fraction of dark pixels per row (central 96% of width)."""
    h, w = gray.shape
    c0, c1 = int(w * 0.02), int(w * 0.98)
    dark = gray[:, c0:c1] < thresh
    return dark.sum(axis=1) / float(c1 - c0)


def col_ink(gray, thresh=200):
    h, w = gray.shape
    r0, r1 = int(h * 0.02), int(h * 0.98)
    dark = gray[r0:r1, :] < thresh
    return dark.sum(axis=0) / float(r1 - r0)


def top_crop(ink, gap_frac=0.05, ink_thresh=0.004, search_frac=0.55):
    """Return crop_top from the first large white band in the upper page."""
    h = len(ink)
    limit = int(h * search_frac)
    min_gap = int(h * gap_frac)
    run_start = None
    for y in range(limit):
        if ink[y] <= ink_thresh:
            if run_start is None:
                run_start = y
        else:
            if run_start is not None and y - run_start >= min_gap:
                # white band [run_start, y); crop a little above its lower edge
                return y - int(h * 0.01)
            run_start = None
    if run_start is not None and limit - run_start >= min_gap:
        return limit - int(h * 0.01)
    return 0


def content_box(gray, thresh=200, pad_frac=0.005):
    h, w = gray.shape
    rows = row_ink(gray, thresh)
    cols = col_ink(gray, thresh)
    ys = np.nonzero(rows > 0.0015)[0]
    xs = np.nonzero(cols > 0.0015)[0]
    if len(ys) == 0 or len(xs) == 0:
        return 0, 0, w, h
    py = int(h * pad_frac)
    px = int(w * pad_frac)
    left = max(0, int(xs[0]) - px)
    right = min(w, int(xs[-1]) + px)
    top = max(0, int(ys[0]) - py)
    bottom = min(h, int(ys[-1]) + py)
    return left, top, right, bottom


def split_row(ink, ink_thresh=0.001, lo=0.3, hi=0.7, min_frac=0.005):
    """Middle row of the widest near-white band in lo..hi of the height, or None."""
    h = len(ink)
    best, best_len, start = None, 0, None
    for y in range(int(h * lo), int(h * hi)):
        if ink[y] <= ink_thresh:
            start = y if start is None else start
            if y + 1 - start > best_len:
                best, best_len = (start + y) // 2, y + 1 - start
        else:
            start = None
    return best if best_len >= h * min_frac else None


def upscale(im, scale):
    """Resize by scale, lowered to stay under MAX_PIXELS; return (image, scale)."""
    w, h = im.size
    if w * h * scale * scale > MAX_PIXELS:
        scale = round((MAX_PIXELS / float(w * h)) ** 0.5, 3)
    if scale != 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return im, scale


def write(im, dst, meta, meta_path):
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    im.save(dst)
    meta["output_size"] = list(im.size)
    meta["output_pixels"] = im.size[0] * im.size[1]
    print(json.dumps(meta))
    if meta_path:
        os.makedirs(os.path.dirname(meta_path) or ".", exist_ok=True)
        with open(meta_path, "w") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--meta", default=None)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--gap-frac", type=float, default=0.05)
    ap.add_argument("--no-title", action="store_true",
                    help="not a title page: the band is looked for in the top 10%% only")
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--split-scale", type=float, default=2.0)
    args = ap.parse_args()

    im = Image.open(args.src).convert("L")
    gray = np.asarray(im)
    h, w = gray.shape

    crop_top = top_crop(row_ink(gray), gap_frac=args.gap_frac,
                        search_frac=0.10 if args.no_title else 0.55)
    left, top, right, bottom = content_box(gray)
    top = max(top, crop_top)                     # never cut below the title gap
    left = max(0, left - 6)
    right = min(w, right + 6)
    if right <= left or bottom <= top:
        left, top, right, bottom = 0, 0, w, h

    method = "white-gap" if crop_top else "content-box"

    def meta(box, scale, **extra):
        return dict({"source": os.path.basename(args.src), "source_size": [w, h], "crop": list(box),
                     "crop_top_method": method}, **extra, scale=scale)

    crop = im.crop((left, top, right, bottom))
    if args.split:
        mid = split_row(row_ink(np.asarray(crop)))
        if mid is not None:
            stem, ext = os.path.splitext(args.dst)
            mstem = os.path.splitext(args.meta)[0] if args.meta else None
            for half, (y0, y1) in (("a", (top, top + mid)), ("b", (top + mid, bottom))):
                out, scale = upscale(im.crop((left, y0, right, y1)), args.split_scale)
                write(out, stem + half + ext,
                      meta((left, y0, right, y1), scale, split=half, page_crop=[left, top, right, bottom]),
                      mstem + half + ".json" if mstem else None)
            return
    out, scale = upscale(crop, args.scale)
    write(out, args.dst, meta((left, top, right, bottom), scale), args.meta)

if __name__ == "__main__":
    main()