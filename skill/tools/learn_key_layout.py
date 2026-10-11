#!/usr/bin/env python3
"""Measure where a book prints the items of its key signatures, for templates/<book>/key_layout.txt.

    learn_key_layout.py SONG:FIFTHS [SONG:FIFTHS ...]

SONG is a song folder under songs/ already run through Audiveris (raw/*.omr), FIFTHS the key
printed at the start of most of its staves (3 = three sharps, -4 = four flats; the written key
of each staff, e.g. 3 for a guitar tuned down a semitone in a 4-flat song is not counted: give
the key of most staves).  Give songs of the same book, at least one with sharps and one with
flats.

Only the key signatures read right (as many items as FIFTHS says) are measured, in interlines
of their own staff (spacing of its own lines, not the sheet interline):
    gap      clef right side to the center of the first item (treble and bass clef apart)
    spacing  center of one item to the center of the next
    dy       center of an item from its pitch line or space (negative: above; a flat is)
The medians are printed as the lines of key_layout.txt, with the spread to check by eye:
a book prints them the same way in all its songs.  Audiveris (KeyTemplates) looks for the
key items at these places only.
"""
import glob
import os
import re
import statistics as st
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SONGS = os.path.join(os.path.dirname(HERE), 'songs')


def lines_of(staff_xml):
    return [[(float(a), float(b)) for a, b in re.findall(r'x="([\d.]+)" y="([\d.]+)"', line)]
            for line in re.findall(r'<line [^>]*>(.*?)</line>', staff_xml, re.S)]


def y_at(points, x):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return points[0][1] if x < points[0][0] else points[-1][1]


def measure(song, fifths):
    """Rows (kind, clef, gap, spacings, dys) of the keys read right in the song."""
    rows = []
    for omr in sorted(glob.glob(os.path.join(SONGS, song, 'raw', '*.omr'))):
        x = zipfile.ZipFile(omr).read('sheet#1/sheet#1.xml').decode('utf-8', 'ignore')
        staves = {m.group(1): lines_of(m.group(2))
                  for m in re.finditer(r'<staff id="(\d+)"[^>]*>(.*?)</staff>', x, re.S)}
        clefs = {}
        for m in re.finditer(r'<clef [^>]*shape="([A-Z_0-9]+)"[^>]*staff="(\d+)"[^>]*>\s*'
                             r'<bounds x="(\d+)" y="(\d+)" w="(\d+)" h="(\d+)"', x):
            clefs.setdefault(m.group(2), []).append((int(m.group(3)) + int(m.group(5)), m.group(1)))
        items = {}
        for m in re.finditer(r'<key-alter pitch="(-?[\d.]+)" shape="([A-Z]+)"[^>]*staff="(\d+)"'
                             r'[^>]*>\s*<bounds x="(\d+)" y="(\d+)" w="(\d+)" h="(\d+)"', x):
            p, shape, s, bx, by, bw, bh = m.groups()
            items.setdefault(s, []).append(
                (int(bx) + int(bw) / 2, int(by) + int(bh) / 2, round(float(p)), shape))
        for s, its in items.items():
            if len(staves.get(s, [])) != 5 or s not in clefs:
                continue
            its.sort()
            keys = [[its[0]]]
            for it in its[1:]:
                if it[0] - keys[-1][-1][0] < 40 and it[3] == keys[-1][-1][3]:
                    keys[-1].append(it)
                else:
                    keys.append([it])
            for key in keys:
                kind = 'sharp' if key[0][3] == 'SHARP' else 'flat'
                if len(key) != abs(fifths) or (kind == 'sharp') != (fifths > 0):
                    continue
                left = [c for c in clefs[s] if c[0] < key[0][0] < c[0] + 6 * 20]
                if not left:
                    continue
                clef_right, clef = max(left)
                ys = [y_at(line, key[0][0]) for line in staves[s]]
                il = (ys[4] - ys[0]) / 4
                rows.append((kind, 'bass' if clef.startswith('F_CLEF') else 'treble',
                             (key[0][0] - clef_right) / il,
                             [(b[0] - a[0]) / il for a, b in zip(key, key[1:])],
                             [(it[1] - (ys[2] + it[2] * il / 2)) / il for it in key]))
    return rows


def spread(values):
    return f'(median of {len(values)}, {min(values):.2f} .. {max(values):.2f})'


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rows = []
    for arg in sys.argv[1:]:
        song, fifths = arg.rsplit(':', 1)
        found = measure(song, int(fifths))
        print(f'# {song}: {len(found)} key signatures read right')
        rows += found
    for kind in ('sharp', 'flat'):
        kr = [r for r in rows if r[0] == kind]
        if not kr:
            print(f'# no {kind} key read right')
            continue
        for clef in ('treble', 'bass'):
            gaps = [r[2] for r in kr if r[1] == clef]
            if gaps:
                print(f'{kind}.gap.{clef} = {st.median(gaps):.2f}   # {spread(gaps)}')
        sp = [d for r in kr for d in r[3]]
        if sp:
            print(f'{kind}.spacing = {st.median(sp):.2f}   # {spread(sp)}')
        dy = [d for r in kr for d in r[4]]
        print(f'{kind}.dy = {st.median(dy):.2f}   # {spread(dy)}')


if __name__ == '__main__':
    main()
