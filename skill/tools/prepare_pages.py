#!/usr/bin/env python3
"""Turn a song's score PDF into OMR input pages.

Usage: python tools/prepare_pages.py "<song dir>"

Page images come from <song dir>/input/extracted/e-NNN.png.  When that folder has none, they are
taken out of <song dir>/input/score.pdf with pdfimages (embedded images, not re-rasterised); the PDF
is the file named by '- pdf:' in context/song_metadata.md, copied from PDF_DIR of environment.txt
when set (a folder holding your score PDFs).  A score you have as page images skips the PDF:
save its pages as e-001.png, e-002.png ... in page order.  Writes (skipping pages already done):
    <song dir>/input/omr_in/<id>_pNN.png     cropped, ~2x, < 20 MP: what Audiveris reads
    <song dir>/crop_meta/<id>_pNN.json       how each page was cropped (goes into git)

Switch: `split_pages=true` in context/audiveris_hints.txt cuts each page in two between its
systems (<id>_pNNa / <id>_pNNb, each upscaled 2x, see preprocess_page.py --split): more
pixels per symbol, Audiveris reads more notes right.  A page that has no white band between two
systems in its middle (single system, landscape page) stays whole.  When the switch changes, the
pages made the other way are made again, and their old raw/ and pages/ results are deleted
(a whole page that cannot be cut keeps its image and results).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import env

HERE = os.path.dirname(os.path.abspath(__file__))
song_dir = os.path.abspath(sys.argv[1])
song_id = os.path.basename(song_dir).split('_')[0]
inp = os.path.join(song_dir, 'input')
pdf = os.path.join(inp, 'score.pdf')
ext = os.path.join(inp, 'extracted')
os.makedirs(inp, exist_ok=True)

if not glob.glob(os.path.join(ext, 'e-*.png')) and not os.path.exists(pdf):
    md = open(os.path.join(song_dir, 'context', 'song_metadata.md'), encoding='utf-8').read()
    m = re.search(r'^\s*[-*]\s*pdf\s*:\s*(.+?)\s*$', md, re.M)
    name = m.group(1) if m else '(no "- pdf:" line in song_metadata.md)'
    src = os.path.join(env.load().get('PDF_DIR', ''), name)
    if not os.path.isfile(src):
        sys.exit(f'{pdf} not found: save the score PDF "{name}" there (or set PDF_DIR in environment.txt to its folder)')
    shutil.copy(src, pdf)

if not glob.glob(os.path.join(ext, 'e-*.png')):
    os.makedirs(ext, exist_ok=True)
    subprocess.run(['pdfimages', '-png', pdf, os.path.join(ext, 'e')], check=True)



def split_on():
    hints = os.path.join(song_dir, 'context', 'audiveris_hints.txt')
    if os.path.exists(hints):
        for line in open(hints, encoding='utf-8'):
            k, _, v = line.strip().partition('=')
            if k.strip() == 'split_pages':
                return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return False


def remove(unit):
    """Delete the input and the results of one page or half page."""
    for f in [os.path.join(out, unit + '.png'), os.path.join(meta, unit + '.json'),
              os.path.join(song_dir, 'raw', unit + '.mxl'), os.path.join(song_dir, 'raw', unit + '.omr'),
              os.path.join(song_dir, 'pages', unit + '.musicxml')] + \
            glob.glob(os.path.join(song_dir, 'raw', unit + '-*.log')):
        if os.path.exists(f):
            os.remove(f)
            print('removed', f)


out = os.path.join(inp, 'omr_in')
meta = os.path.join(song_dir, 'crop_meta')
split = split_on()
for i, img in enumerate(sorted(glob.glob(os.path.join(ext, 'e-*.png'))), 1):
    unit = f'{song_id}_p{i:02d}'
    dst = os.path.join(out, unit + '.png')
    args = [sys.executable, os.path.join(HERE, 'preprocess_page.py'), img] + (['--no-title'] if i > 1 else [])
    if os.path.exists(os.path.join(out, unit + 'a.png')):
        if split:
            continue
        remove(unit + 'a')
        remove(unit + 'b')
    elif os.path.exists(dst):
        if not split:
            continue
        # whole page made earlier: replaced only if it can be cut
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(args + [os.path.join(tmp, unit + '.png'), '--meta',
                                   os.path.join(tmp, unit + '.json'), '--split'],
                           check=True, stdout=subprocess.DEVNULL)
            if not os.path.exists(os.path.join(tmp, unit + 'a.png')):
                continue
            remove(unit)
            for half in 'ab':
                shutil.move(os.path.join(tmp, unit + half + '.png'), out)
                shutil.move(os.path.join(tmp, unit + half + '.json'), meta)
        print(*sorted(glob.glob(os.path.join(out, unit + '?.png'))))
        continue
    subprocess.run(args + [dst, '--meta', os.path.join(meta, unit + '.json')] + (['--split'] if split else []),
                   check=True, stdout=subprocess.DEVNULL)
    print(*sorted(glob.glob(os.path.join(out, unit + '*.png'))))
