#!/usr/bin/env python3
"""Crop one part of every system from the OMR binary image, annotated with measure numbers
and beat positions, to read positions of printed markings (8va lines, labels...) by eye.

    python3 tools/omr_beat_grid.py "<song dir>" <page> [<page> ...] [--part N] [--out DIR]

A page argument (2 or 02) takes both halves of a split page (split_pages=true); 2a takes one.
Uses raw/*_pNN.omr (binary image, staff lines, stacks and their time slots) and
pages/*.musicxml (bandscore_postprocess.py) for global measure numbers. Green: measure start + global
number; red: time slots with their beat (1-based). --part is the 1-based part of each system
(default 1). One PNG per page, all systems stacked, 2000 px wide.
"""
import argparse
import glob
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F

from PIL import Image, ImageDraw, ImageFont


def font(size, bold=False):
    for name in (('Arial Bold.ttf' if bold else 'Arial.ttf'),):
        for d in ('/System/Library/Fonts/Supplemental', '/usr/share/fonts/truetype/dejavu'):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def measure_rows(song_dir):
    """{(unit, system): [global measure numbers]} for the page units (raw/*.omr order, 1-based),
    from pages/<unit>.musicxml (bandscore_postprocess.py): the merged score numbers their
    measures 1..N in this order, and a lower half page no longer starts a merged page."""
    rows, first = {}, 0
    for unit, path in enumerate(sorted(glob.glob(os.path.join(song_dir, 'pages', '*.musicxml'))), 1):
        root = ET.parse(path).getroot()
        sy = 1
        for i, m in enumerate(root.find('part').findall('measure')):
            pr = m.find('print')
            if i > 0 and pr is not None and pr.get('new-system') == 'yes':
                sy += 1
            rows.setdefault((unit, sy), []).append(str(first + i + 1))
        first += i + 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song_dir')
    ap.add_argument('pages', nargs='+')
    ap.add_argument('--part', type=int, default=1)
    ap.add_argument('--out', default='.')
    a = ap.parse_args()
    rows = measure_rows(a.song_dir)
    small, big = font(22), font(30, True)
    omrs = sorted(glob.glob(os.path.join(a.song_dir, 'raw', '*_p??.omr'))
                  + glob.glob(os.path.join(a.song_dir, 'raw', '*_p??[ab].omr')))
    units = [os.path.basename(o)[:-4].rsplit('_p', 1)[1] for o in omrs]   # 02 / 02a
    # one pages/ unit per .omr, in this order (bandscore_postprocess.py)
    wanted = [(page, omr, unit) for page, (omr, unit) in enumerate(zip(omrs, units), 1)
              if any(p.lstrip('0') == unit.lstrip('0') or (p.isdigit() and int(p) == int(unit[:2]))
                     for p in a.pages)]
    for page, omr, unit in wanted:
        z = zipfile.ZipFile(omr)
        sheet = z.read('sheet#1/sheet#1.xml').decode()
        img = Image.open(io.BytesIO(z.read('sheet#1/BINARY.png'))).convert('RGB')
        d = ImageDraw.Draw(img)
        strips = []
        for si, sysm in enumerate(re.finditer(r'<system id="\d+">(.*?)</system>', sheet, re.S), 1):
            body = sysm.group(1)
            parts = re.findall(r'<part id="\d+"[^>]*>(.*?)</part>', body, re.S)
            ys = [float(y) for y in re.findall(r'<point x="[\d.]+" y="([\d.]+)"',
                                                parts[a.part - 1])]
            top, bot = int(min(ys)) - 170, int(max(ys)) + 90
            meas = rows.get((page, si), [])
            for k, st in enumerate(re.finditer(
                    r'<stack id="\d+" left="(\d+)" right="(\d+)"(?![^>]*special=)[^>]*(?<!/)>(.*?)</stack>',
                    body, re.S)):   # skip special (CAUTIONARY) stacks
                left = int(st.group(1))
                d.line([(left, top), (left, bot)], fill=(0, 160, 0), width=2)
                d.text((left + 6, top + 2), f'm{meas[k]}' if k < len(meas) else '?',
                       fill=(0, 140, 0), font=big)
                for sl in re.finditer(r'<slot id="\d+" x-offset="(\d+)" time-offset="([\d/]+)"',
                                      st.group(3)):
                    x = left + int(sl.group(1))
                    d.line([(x, bot - 30), (x, bot)], fill=(220, 0, 0), width=2)
                    d.text((x - 8, bot - 58), f'{float(F(sl.group(2)) * 4 + 1):g}',
                           fill=(220, 0, 0), font=small)
            strips.append(img.crop((150, top, img.size[0] - 20, bot)))
        w = max(s.size[0] for s in strips)
        out = Image.new('RGB', (w, sum(s.size[1] + 20 for s in strips)), 'white')
        y = 0
        for s in strips:
            out.paste(s, (0, y))
            y += s.size[1] + 20
        out = out.resize((2000, out.size[1] * 2000 // w))
        path = os.path.join(a.out, f'p{unit}_part{a.part}.png')
        out.save(path)
        print(path)


if __name__ == '__main__':
    main()
