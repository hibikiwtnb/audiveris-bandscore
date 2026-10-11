#!/usr/bin/env python3
"""Run patched Audiveris on OMR input pages (Windows / macOS / Linux).

Usage:
    python tools/run_audiveris.py [options] "<song dir>" <song dir>/input/omr_in/*.png

Options:
    --mask-header            Mask running header with white on pages >= start_page (default: True)
    --no-mask-header         Disable running header masking
    --mask-start-page <N>    Page number to start masking from (default: 2)
    --mask-max-ratio <F>     Max height fraction to search for header (default: 0.08)
    --mask-ink-thresh <N>    Dark pixel threshold per row for ink detection (default: 25)
    --mask-fixed-ratio <F>   Override auto-gap detection with a fixed cut ratio (e.g. 0.03)

Configuration can also be set in <song dir>/context/audiveris_hints.txt:
    header_mask=false
    header_mask_start_page=2
    header_mask_max_ratio=0.08
    header_mask_fixed_ratio=0.03

Half pages (<id>_pNNa / <id>_pNNb, split_pages=true, see prepare_pages.py): only the upper half
has the running header (the search height and the fixed ratio are scaled to the half, from
crop_meta/), and Audiveris gets ScaleBuilder.minDerivativeRatio=0.008: at ~2.5x (staff
interline ~22 px, tablature ~28 px) the default 0.025 missed the second interline and the
tablature staves were lost (kept at the 2.0x default).

Paths come from environment.txt (JAVA_HOME, AUDIVERIS_BIN, WORK_DIR).  Reads
<song dir>/context/audiveris_hints.txt, writes <song dir>/raw/.
A relative templateDir in the hints (templates/<book>) is taken from the repo root.
Backslashes in the hints are passed as literal characters (Windows paths).
PaddleOCR is the OCR engine of Audiveris (ocrEngine=tesseract in the hints to use Tesseract):
its server must already be running at PADDLE_OCR_URL (environment.txt, this machine or another one
on the LAN); this script passes that URL to Audiveris, does not start or stop the server, and stops
with an error when the server does not answer. Audiveris goes on without the texts when an OCR request
fails: a try whose log shows such a failure is failed.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image


def get_page_number(filename):
    """Extract page number from filename (e.g. 054_p02.png -> 2)."""
    m = re.search(r'[_\b]p(\d+)', filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\.png$', filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 1


def detect_header_cut(img_path, max_ratio=0.08, ink_thresh=25, min_gap=3):
    """Detect running header ink cluster and return cut line in the subsequent white gap."""
    im = Image.open(img_path).convert('L')
    arr = np.asarray(im)
    h, w = arr.shape
    max_y = int(h * max_ratio)
    c0, c1 = int(w * 0.05), int(w * 0.95)
    row_dark = (arr[:max_y, c0:c1] < 200).sum(axis=1)

    # 3-tap moving average filter to avoid 1-pixel noise flickering
    smoothed = np.convolve(row_dark, np.ones(3)/3.0, mode='same')

    # 1. Skip scanner edge noise at the very top (first 15 rows)
    scan_start = 0
    if smoothed[0] > ink_thresh:
        for y in range(min(15, max_y)):
            if smoothed[y] <= ink_thresh:
                scan_start = y
                break

    # 2. Find ink runs and gaps in scan_start..max_y
    runs = []
    in_ink = False
    start = scan_start
    for y in range(scan_start, max_y):
        is_ink = (smoothed[y] > ink_thresh)
        if is_ink and not in_ink:
            if y > start:
                runs.append(('gap', start, y))
            start = y
            in_ink = True
        elif not is_ink and in_ink:
            runs.append(('ink', start, y))
            start = y
            in_ink = False
    if in_ink:
        runs.append(('ink', start, max_y))
    else:
        runs.append(('gap', start, max_y))

    # Merge very small gaps inside an ink cluster (< 3 px)
    merged = []
    for rtype, y0, y1 in runs:
        if merged and rtype == 'gap' and (y1 - y0) < 3 and merged[-1][0] == 'ink':
            prev_type, py0, py1 = merged.pop()
            merged.append(('ink', py0, y1))
        elif merged and rtype == 'ink' and merged[-1][0] == 'ink':
            prev_type, py0, py1 = merged.pop()
            merged.append(('ink', py0, y1))
        else:
            merged.append((rtype, y0, y1))

    # 3. Locate the header ink run (height between 15 and 150 px, substantial peak)
    header_run = None
    header_idx = -1
    for idx, (rtype, y0, y1) in enumerate(merged):
        if rtype == 'ink' and (15 <= (y1 - y0) <= 150):
            if smoothed[y0:y1].max() > 150:
                header_run = (y0, y1)
                header_idx = idx
                break

    if not header_run:
        return None, "no header ink cluster found"

    # 4. Next run should be a gap before chords/staves
    if header_idx + 1 < len(merged) and merged[header_idx + 1][0] == 'gap':
        gap_y0, gap_y1 = merged[header_idx + 1][1], merged[header_idx + 1][2]
        if (gap_y1 - gap_y0) >= min_gap:
            # Safe cut is in the upper part of the gap
            cut_y = gap_y0 + min(15, (gap_y1 - gap_y0) // 2)
            return cut_y, f"header [{header_run[0]}..{header_run[1]}], gap [{gap_y0}..{gap_y1}], cut at y={cut_y}"

    return None, "no valid gap after header"


parser = argparse.ArgumentParser(description="Run patched Audiveris on OMR input pages.")
parser.add_argument("song_dir", help="Path to song directory")
parser.add_argument("images", nargs="+", help="Page image files")
parser.add_argument("--mask-header", dest="mask_header", action="store_true", default=None,
                    help="Mask running header with white on pages >= start_page (default: True)")
parser.add_argument("--no-mask-header", dest="mask_header", action="store_false",
                    help="Disable running header masking")
parser.add_argument("--mask-start-page", type=int, default=None,
                    help="Page number to start header masking (default: 2)")
parser.add_argument("--mask-max-ratio", type=float, default=None,
                    help="Max height ratio to search for running header (default: 0.08)")
parser.add_argument("--mask-ink-thresh", type=int, default=None,
                    help="Dark pixel threshold per row for ink detection (default: 25)")
parser.add_argument("--mask-fixed-ratio", type=float, default=None,
                    help="Override auto-gap detection with fixed cut ratio (e.g. 0.03)")

cli_args = parser.parse_args()
song_dir = os.path.abspath(cli_args.song_dir)

# Expand any wildcard paths if present
images = []
for p in cli_args.images:
    if '*' in p or '?' in p:
        matched = glob.glob(p)
        if matched:
            images.extend(sorted(os.path.abspath(m) for m in matched))
        else:
            images.append(os.path.abspath(p))
    else:
        images.append(os.path.abspath(p))

if not images:
    sys.exit(f"Error: no images found for {song_dir}")

# 1. Environment & Binaries (all from environment.txt, nothing is guessed)
import env
cfg = env.load(('JAVA_HOME', 'AUDIVERIS_BIN', 'WORK_DIR'))
java_home = cfg['JAVA_HOME']
audiveris_bin = cfg['AUDIVERIS_BIN']
work_dir = cfg['WORK_DIR']            # keep the user name out of the path: Audiveris writes it into .mxl / .omr
if not os.path.exists(audiveris_bin):
    sys.exit(f"Error: Audiveris binary not found at {audiveris_bin} (AUDIVERIS_BIN in environment.txt).")

env_vars = os.environ.copy()
env_vars["JAVA_HOME"] = java_home
env_vars["PATH"] = os.path.join(java_home, "bin") + os.pathsep + env_vars.get("PATH", "")

# 2. Hints & Configuration Defaults
# Hierarchy: CLI flag > audiveris_hints.txt > Default
mask_header = True
mask_start_page = 2
mask_max_ratio = 0.08
mask_ink_thresh = 25
mask_fixed_ratio = None

hints_file = os.path.join(song_dir, "context", "audiveris_hints.txt")
args_av = []
use_paddle = True
if os.path.exists(hints_file):
    with open(hints_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Parse custom header masking configurations from hints (commented or uncommented)
            check_line = line.lstrip('#').strip()
            if check_line.startswith(('header_mask', 'mask_header')):
                k, _, v = check_line.partition('=')
                k = k.strip().lower()
                v = v.strip().lower()
                if k in ('header_mask', 'mask_header'):
                    mask_header = (v in ('1', 'true', 'yes', 'on'))
                elif k in ('header_mask_start_page', 'mask_start_page'):
                    mask_start_page = int(v)
                elif k in ('header_mask_max_ratio', 'mask_max_ratio'):
                    mask_max_ratio = float(v)
                elif k in ('header_mask_fixed_ratio', 'mask_fixed_ratio'):
                    mask_fixed_ratio = float(v)
                elif k in ('header_mask_ink_thresh', 'mask_ink_thresh'):
                    mask_ink_thresh = int(v)
                continue  # Intercepted: do NOT pass to Audiveris -constant!

            if not line.startswith("#"):
                key, _, value = line.partition("=")
                if key.endswith(".templateDir") and value and not os.path.isabs(value):
                    value = os.path.join(env.ROOT, value)
                    if not os.path.isdir(value):
                        sys.exit(f"Error: templateDir {value} not found (audiveris_hints.txt).")
                    line = f"{key}={value}"
                # Audiveris reads each -constant like a .properties line: a backslash is an escape,
                # so a Windows path would lose its separators
                args_av.extend(["-constant", line.replace("\\", "\\\\")])
                if "ocrEngine=tesseract" in line:
                    use_paddle = False

# CLI explicit arguments override hints
if cli_args.mask_header is not None:
    mask_header = cli_args.mask_header
if cli_args.mask_start_page is not None:
    mask_start_page = cli_args.mask_start_page
if cli_args.mask_max_ratio is not None:
    mask_max_ratio = cli_args.mask_max_ratio
if cli_args.mask_ink_thresh is not None:
    mask_ink_thresh = cli_args.mask_ink_thresh
if cli_args.mask_fixed_ratio is not None:
    mask_fixed_ratio = cli_args.mask_fixed_ratio

if use_paddle:
    paddle_url = env.load(('PADDLE_OCR_URL',))['PADDLE_OCR_URL'].rstrip('/')
    args_av.extend(["-constant", f"org.audiveris.omr.text.paddle.PaddleOCR.serverUrl={paddle_url}"])


# OCR failures logged by Audiveris, which then goes on without the texts
OCR_FAILURE = re.compile(r"PaddleOCR (server error|recognition failed|lyrics|server not reachable)")


def check_paddle():
    for _ in range(5):
        try:
            with urllib.request.urlopen(paddle_url + "/health", timeout=30) as resp:
                if resp.status == 200 and b"ok" in resp.read():
                    return
        except Exception:
            time.sleep(2)
    sys.exit(f"Error: PaddleOCR server not answering at {paddle_url} (PADDLE_OCR_URL in environment.txt). "
             "Start it first: <OCR_PYTHON> <PADDLE_OCR_SERVER>.")


# 3. Directories (Keep username out of .mxl / .omr metadata)
in_dir = os.path.join(work_dir, "in")
out_dir = os.path.join(work_dir, "out")
logs_dir = os.path.join(work_dir, "logs")
raw_out = os.path.join(song_dir, "raw")

for d in (in_dir, out_dir, logs_dir, raw_out):
    os.makedirs(d, exist_ok=True)

# Half pages: lower threshold of the interline histogram, or the tablature staves are lost
HALF_ARGS = ["-constant", "org.audiveris.omr.sheet.ScaleBuilder.minDerivativeRatio=0.008"]


def half_of(base):
    """'a' / 'b' for a half page (<id>_pNNa / <id>_pNNb), None for a whole page."""
    m = re.search(r'_p\d+([ab])$', base)
    return m.group(1) if m else None


def half_factor(base):
    """Page crop height over this half's crop height (crop_meta/<base>.json)."""
    with open(os.path.join(song_dir, "crop_meta", base + ".json")) as f:
        meta = json.load(f)
    return (meta["page_crop"][3] - meta["page_crop"][1]) / float(meta["crop"][3] - meta["crop"][1])


# 4. Transcription Loop
for img in images:
    base = os.path.splitext(os.path.basename(img))[0]
    half = half_of(base)
    factor = half_factor(base) if half == 'a' else 1.0

    # Check if already completed in raw_out
    target_mxl = os.path.join(raw_out, f"{base}.mxl")
    target_omr = os.path.join(raw_out, f"{base}.omr")
    if os.path.exists(target_mxl) and os.path.exists(target_omr) and os.path.getsize(target_mxl) > 0:
        print(f"{base}: already completed, skipping.", flush=True)
        continue

    staged_png = os.path.join(in_dir, f"{base}.png")
    page_num = get_page_number(base)

    did_mask = False
    if mask_header and page_num >= mask_start_page and half != 'b':
        if mask_fixed_ratio is not None:
            im = Image.open(img)
            cut_y = int(im.height * min(1.0, mask_fixed_ratio * factor))
            arr = np.asarray(im).copy()
            arr[:cut_y] = 255
            Image.fromarray(arr).save(staged_png)
            print(f"{base}: masked running header with fixed ratio {mask_fixed_ratio} (cut at y={cut_y})", flush=True)
            did_mask = True
        else:
            cut_y, reason = detect_header_cut(img, max_ratio=min(1.0, mask_max_ratio * factor),
                                              ink_thresh=mask_ink_thresh)
            if cut_y is not None:
                im = Image.open(img)
                arr = np.asarray(im).copy()
                arr[:cut_y] = 255
                Image.fromarray(arr).save(staged_png)
                print(f"{base}: masked running header ({reason})", flush=True)
                did_mask = True
            else:
                print(f"{base}: header masking skipped ({reason})", flush=True)

    if not did_mask:
        shutil.copy(img, staged_png)

    ok = False
    for attempt in (1, 2, 3):
        if use_paddle:
            check_paddle()

        for f in glob.glob(os.path.join(out_dir, f"{base}*")):
            os.remove(f)

        cmd = [audiveris_bin, "-batch", "-transcribe", "-export", "-output", out_dir] + args_av \
            + (HALF_ARGS if half else []) + ["--", staged_png]
        log_file = os.path.join(logs_dir, f"{base}.try{attempt}.log")
        with open(log_file, "w", encoding="utf-8") as log_fp:
            subprocess.run(cmd, env=env_vars, stdout=log_fp, stderr=subprocess.STDOUT, text=True)

        has_mxl = os.path.exists(os.path.join(out_dir, f"{base}.mxl")) or len(glob.glob(os.path.join(out_dir, f"{base}.mvt*.mxl"))) > 0
        has_omr = os.path.exists(os.path.join(out_dir, f"{base}.omr"))

        if use_paddle and (has_mxl or has_omr):
            with open(log_file, encoding="utf-8", errors="replace") as log_fp:
                if any(OCR_FAILURE.search(line) for line in log_fp):
                    print(f"{base}: try {attempt} OCR failure, see {log_file}", flush=True)
                    has_mxl = False

        if has_mxl and has_omr:
            ok = True
            for f in glob.glob(os.path.join(out_dir, f"{base}*")):
                shutil.move(f, os.path.join(raw_out, os.path.basename(f)))
            print(f"{base}: ok (try {attempt})", flush=True)
            break
        print(f"{base}: try {attempt} failed", flush=True)

    if not ok:
        print(f"{base}: FAILED, see {logs_dir}/{base}.try*.log", flush=True)
        sys.exit(1)
