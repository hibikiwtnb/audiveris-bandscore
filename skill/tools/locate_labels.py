#!/usr/bin/env python3
"""List staff labels (timbre changes, 8va / 15ma / coll'8va) with part, measure and beat.

    python3 tools/locate_labels.py "<song dir>" [regex]

Reads <song dir>/page_ocr/pNN.json (tools/page_ocr.py), raw/*_pNN.omr (pNNa / pNNb for half
pages, split_pages=true: the page column then shows 2a / 2b) and pages/*.musicxml
(global measure numbers), and prints one tab-separated line per OCR text matching the regex (default:
common timbre words and octave marks):

    page  system  part  staff  measure  beat  x  text

part/staff = the staff right below the text (the top line is interpolated at the text's x,
staves can be skewed); measure = global measure number; beat = the .omr time slot at the
text's left edge (the same timing Audiveris exported, 1-based). Writing the hint files
(context/instrument_changes.txt, context/ottava.txt) from this list only needs the page to be
looked at where the list is ambiguous (start / end / reminder of a label, see the skill).
"""
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction as F

DEFAULT_RE = (r"8\s*va|15\s*ma|coll|pizz|arco|pluck|bell|glock|harp|woodwind|flute|lead|pad|"
              r"string|synth|piano|organ|brass|choir|seq|arpegg")


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
    abbr = [sp.findtext('part-abbreviation') for sp in root.iter('score-part')] if rows else []
    return rows, abbr


def systems_of(omr):
    sheet = zipfile.ZipFile(omr).read('sheet#1/sheet#1.xml').decode()
    systems = []
    for sysm in re.finditer(r'<system id="\d+">(.*?)</system>', sheet, re.S):
        body = sysm.group(1)
        staves = []
        # part id = logical part (partsHint order); an absent part leaves a gap in the ids
        for pid, part in re.findall(r'<part id="(\d+)"[^>]*>(.*?)</part>', body, re.S):
            pi = int(pid) - 1
            for si, st in enumerate(re.findall(r'<staff id="\d+"[^>]*>\s*<lines>(.*?)</lines>',
                                               part, re.S)):
                first = re.search(r'<line\b.*?</line>', st, re.S).group(0)
                pts = [(float(a), float(b)) for a, b in
                       re.findall(r'<point x="([\d.]+)" y="([\d.]+)"', first)]
                staves.append((pi, si + 1, pts))
        # real measures only: skip special stacks (CAUTIONARY key/time at a system end, which
        # are self-closing and have no slots)
        stacks = [(int(l), int(r), [(int(l) + int(x), F(t)) for x, t in re.findall(
            r'<slot id="\d+" x-offset="(\d+)" time-offset="([\d/]+)"', body_s)])
            for l, r, body_s in re.findall(
                r'<stack id="\d+" left="(\d+)" right="(\d+)"(?![^>]*special=)[^>]*(?<!/)>(.*?)</stack>',
                body, re.S)]
        systems.append((staves, stacks))
    return systems


def top_at(pts, x):
    """y of a staff's top line at abscissa x (linear between the line's points)."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (max(x, x0) - x0) / max(1e-6, x1 - x0)
    return pts[-1][1]


def main(song_dir, pattern):
    rows, abbr = measure_rows(song_dir)
    want = re.compile(pattern, re.I)
    print('page\tsystem\tpart\tstaff\tmeasure\tbeat\tx\ttext')
    omrs = sorted(glob.glob(os.path.join(song_dir, 'raw', '*_p??.omr'))
                  + glob.glob(os.path.join(song_dir, 'raw', '*_p??[ab].omr')))
    # one pages/ unit per .omr, in this order (bandscore_postprocess.py)
    for page, omr in enumerate(omrs, 1):
        unit = os.path.basename(omr)[:-4].rsplit('_p', 1)[1]
        path = os.path.join(song_dir, 'page_ocr', f'p{unit}.json')
        if not os.path.exists(path):
            continue
        systems = systems_of(omr)
        for w in json.load(open(path)):
            if not want.search(w['text']):
                continue
            x, yref = w['x'], w['y'] + 0.25 * w['h']     # text may touch the staff below
            below = [(top_at(pts, x + w['w'] / 2) - yref, k, pi, si)
                     for k, (staves, _) in enumerate(systems) for pi, si, pts in staves
                     if top_at(pts, x + w['w'] / 2) > yref]
            if not below:
                continue
            _, k, pi, si = min(below)
            stacks = systems[k][1]
            idx = next((i for i, (l, r, _) in enumerate(stacks) if l <= x < r),
                       0 if x < stacks[0][0] else len(stacks) - 1)
            after = [t for sx, t in stacks[idx][2] if sx >= x - 12]
            beat = f'{float(after[0]) * 4 + 1:g}' if after else 'end'
            meas = rows.get((page, k + 1), [])
            m = meas[idx] if idx < len(meas) else '?'
            part = abbr[pi] if pi < len(abbr) else f'#{pi + 1}'
            print(f"{int(unit[:2])}{unit[2:]}\t{k + 1}\t{part}\t{si}\t{m}\t{beat}\t{x}\t{w['text'].strip()}")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_RE)
