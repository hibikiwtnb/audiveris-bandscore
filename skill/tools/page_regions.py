#!/usr/bin/env python3
"""OCR the margins around the score block of a page: what Step 1 needs to write the hints.

SKILL.md Step 1.  Checked on two scanned pages (title page, 2-system page).

    <OCR_PYTHON> tools/page_regions.py "<song dir>" [page ...]      (default: page 1)

Reads the full pages (<song dir>/input/extracted/e-NNN.png, title still there) and writes
<song dir>/context/page_regions.txt:
    A  above the score block   title, lyricist, composer (Japanese + English model)
    B  left of each staff      part names, abbreviations (English model)
    C  below the score block   footer, page number (English model)
    (D, right of the block, is usually empty and not read.)
    S  per system: each B name with its number of staves (staff lines grouped into staves)
with the coordinates of the regions, staves and words (deskewed page pixels, angle given),
then a partsHint draft (first system's names | the first other names with the same staves)
and the doubts.  Whether and where to look at the image is left to the reader.

Score block (after BandScoreSplit, github.com/hibikiwtnb/BandScoreSplit): the page is
deskewed, then rows whose longest ink run spans 30% of the width are long lines (gray < 200,
small breaks bridged: scanned staff lines are faint); staff lines are the thin ones that come
in groups or sit on a system's start barline (a title rule is thick or alone); the first and
last give the top and bottom.  The leftmost long vertical line through a staff line (start
barline or bracket) is its left edge, as in BandScoreSplit's vertical line map.
B is cut per staff line row (an indented first system keeps its long part names), A and C
stop at the first blank band outside the block (chord names, stems, beams stay out).
"""
import glob
import os
import re
import sys

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

import numpy as np
from PIL import Image

BLANK_BAND = 0.02   # A/C end at a blank band this high (fraction of page height)


def deskew(im):
    """Rotate the page so that staff lines are horizontal (search -1..+1 degree); and the angle."""
    small = im.resize((im.size[0] // 4, im.size[1] // 4))
    best = max(np.arange(-1, 1.01, 0.05), key=lambda a: np.square(
        (np.array(small.rotate(a, fillcolor=255)) < 128).sum(axis=1).astype(float)).sum())
    return im.rotate(best, resample=Image.BICUBIC, fillcolor=255), best


def longest_runs(ink):
    """Per row: length and left end of the longest horizontal ink run (scan border excluded)."""
    h, w = ink.shape
    pad = np.zeros((h, 1), bool)
    d = np.diff(np.hstack([pad, ink, pad]).astype(np.int8), axis=1)
    rs, xs = np.nonzero(d == 1)
    _, xe = np.nonzero(d == -1)
    keep = (xs > 0) & (xe < w)
    rs, xs, ln = rs[keep], xs[keep], (xe - xs)[keep]
    order = np.lexsort((-ln, rs))                  # per row, longest run first
    rs, xs, ln = rs[order], xs[order], ln[order]
    first = np.r_[True, rs[1:] != rs[:-1]]
    length, left = np.zeros(h, int), np.full(h, w)
    length[rs[first]], left[rs[first]] = ln[first], xs[first]
    return length, left


def close_gaps(ink, k=3):
    """Bridge horizontal breaks of up to 2k pixels (faint, broken staff lines in scans)."""
    p = np.pad(ink, ((0, 0), (k, k)))
    grown = np.zeros_like(p)
    for s in range(-k, k + 1):
        grown |= np.roll(p, s, axis=1)
    shrunk = np.ones_like(p)
    for s in range(-k, k + 1):
        shrunk &= np.roll(grown, s, axis=1)
    return shrunk[:, k:-k]


def long_verticals(ink, min_len):
    """Vertical ink runs at least min_len long as (x, y0, y1); the scan border is left out."""
    h, w = ink.shape
    pad = np.zeros((1, w), bool)
    d = np.diff(np.vstack([pad, ink, pad]).astype(np.int8), axis=0)
    ys, xs = np.nonzero(d.T == 1)[1], np.nonzero(d.T == 1)[0]
    ye = np.nonzero(d.T == -1)[1]
    keep = (ye - ys >= min_len) & (xs > 0.01 * w) & (xs < 0.99 * w)
    return list(zip(xs[keep], ys[keep], ye[keep] - 1))


def score_block(ink):
    """Top and bottom staff line rows, and per row the left end of the nearest staff."""
    h, w = ink.shape
    length, left = longest_runs(ink)
    rows = np.nonzero(length >= 0.3 * w)[0]        # long lines; text strokes are short
    rows = rows[(rows > 0.01 * h) & (rows < 0.99 * h)]   # scan border out
    objs = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)   # one physical line each
    thick = np.median([len(o) for o in objs])
    mids = np.array([o.mean() for o in objs])
    # Left edge (BandScoreSplit's vertical line map): the leftmost long vertical line through
    # a staff line row is the system's start barline or bracket; part names are left of it
    lv = [v for v in long_verticals(close_gaps(ink.T).T, 0.02 * w) if v[0] < w / 2]

    def start_line(y):
        return min([x for x, y0, y1 in lv if y0 <= y <= y1], default=w)

    # Staff lines are thin, and come in groups or sit on the system's start barline (a 1-line
    # percussion staff); a title rule is thick or alone, a scan shadow is thick
    lines = np.concatenate([o for o, m in zip(objs, mids) if len(o) <= 2 * thick
                            and ((np.abs(mids - m) < 0.01 * h).sum() > 1 or start_line(m) < w)])
    top, bottom = lines[0], lines[-1]
    staff_left = np.array([start_line(y) for y in lines])
    nearest = np.abs(np.arange(h)[:, None] - lines[None, :]).argmin(axis=1)
    return top, bottom, staff_left[nearest], lv


def staves(ink, top, bottom, x0, lv):
    """Staves as (y0, y1, lines, system) between top and bottom, right of x0.

    Staff lines by row projection (> 60% ink; dilated 1 px, as a scanned line is not quite
    straight and dense notes break the longest run), grouped where they are close together.
    A system is the longest vertical line through the staff (the start barline spans it all).
    """
    h, w = ink.shape
    d = ink.copy()
    d[1:] |= ink[:-1]
    d[:-1] |= ink[1:]
    rows = np.nonzero(d[:, x0:int(0.95 * w)].mean(axis=1) > 0.6)[0]
    rows = rows[(rows >= top - 5) & (rows <= bottom + 5)]
    mids = np.array([o.mean() for o in np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)])
    gap = np.median(np.diff(mids))                  # staff line spacing: most gaps are inside a staff
    out = []
    for g in np.split(mids, np.nonzero(np.diff(mids) > 2.5 * gap)[0] + 1):
        y = g.mean()
        through = [v for v in lv if v[1] <= y <= v[2]]
        sysline = max(through, key=lambda v: v[2] - v[1], default=None)
        out.append((int(g[0]), int(g[-1]), len(g), sysline and (sysline[1], sysline[2])))
    keys = list(dict.fromkeys(s[3] for s in out))
    return [(y0, y1, n, keys.index(k) + 1) for y0, y1, n, k in out]


def blank_edge(ink, start, step):
    """From row start, walk by step past the ink next to the block to the first blank band."""
    h, w = ink.shape
    blank = ink[:, int(0.03 * w):int(0.97 * w)].sum(axis=1) < 0.002 * w   # side borders out
    band, y = int(BLANK_BAND * h), start
    while 0 <= y < h:
        if blank[y:y + band].all() if step > 0 else blank[max(0, y - band + 1):y + 1].all():
            return y
        y += step
    return min(max(y, 0), h)


def read(ocr, img, dx, dy):
    """OCR an image, words in page coordinates as (y centre, x, text, score, box)."""
    if img.size[0] < 8 or img.size[1] < 8:
        return []
    res = ocr.predict(np.array(img.convert('RGB')))[0]
    out = []
    for text, score, poly in zip(res['rec_texts'], res['rec_scores'], res['rec_polys']):
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        box = (int(min(xs)) + dx, int(min(ys)) + dy, int(max(xs)) + dx, int(max(ys)) + dy)
        out.append(((box[1] + box[3]) // 2, box[0], text, float(score), box))
    return sorted(out)


def roman(name):
    """Roman numerals as OCR reads them (E.Guitar ⅡI, E.G. 1) back to I / II."""
    name = name.replace('ⅡI', 'II').replace('Ⅱ', 'II').replace('Ⅰ', 'I')
    return re.sub(r'(?<= )2$', 'II', re.sub(r'(?<= )1$', 'I', name))


def parts(stv, words, gap):
    """Per system, [name, staves, score] top to bottom: each staff goes to the nearest B word.

    Words on one row are joined first; a staff far from any word, or a word with no staff,
    goes to the doubts."""
    joined, doubts = [], []
    for y, x, text, score, _ in sorted(words):
        if joined and abs(y - joined[-1][0]) < gap:
            joined[-1][2] += ' ' + text
            joined[-1][3] = min(joined[-1][3], score)
        else:
            joined.append([y, x, text, score])
    systems, used = {}, set()
    for y0, y1, n, sysno in stv:
        y = (y0 + y1) / 2
        i = min(range(len(joined)), key=lambda j: abs(joined[j][0] - y), default=None)
        if i is None or abs(joined[i][0] - y) > 4 * (y1 - y0 + gap):
            doubts.append(f'staff y={y0}..{y1} has no name next to it')
            continue
        used.add(i)
        ps = systems.setdefault(sysno, [])
        if ps and ps[-1][3] == i:
            ps[-1][1] += 1
        else:
            ps.append([joined[i][2], 1, joined[i][3], i])
    doubts += [f'"{t}" (y={y}) is next to no staff' for j, (y, x, t, s) in enumerate(joined)
               if j not in used]
    return [[p[:3] for p in ps] for ps in systems.values()], doubts


def hint(systems, doubts):
    """partsHint draft: names of the first system | the first other names with the same staves."""
    full = systems[0]
    counts = [n for _, n, _ in full]
    abbr = next((ps for ps in systems[1:] if [p[0] for p in ps] != [p[0] for p in full]), None)
    for k, ps in enumerate(systems[1:], 2):
        if [n for _, n, _ in ps] != counts:
            doubts.append(f'system {k} has other staves per part than system 1 '
                          '(a part left out, or a staff missed)')
    if len(systems) == 1:
        doubts.append('only one system read: no abbreviations (read page 2 too)')
    if abbr is not None and [n for _, n, _ in abbr] != counts:
        abbr = None
    # a low score is fine when another system reads the same name in the same place
    same = [ps for ps in systems if [n for _, n, _ in ps] == counts]
    doubts += [f'low OCR score {s:.2f}: "{t}"' for ps in systems for i, (t, _, s) in enumerate(ps)
               if s < 0.9 and not (ps in same and sum(roman(o[i][0]) == roman(t) for o in same) > 1)]
    out = []
    for i, (name, n, _) in enumerate(full):
        names = [roman(name)] + ([roman(abbr[i][0])] if abbr else [])
        out.append('|'.join(dict.fromkeys(names)) + f':{n}')
    return '; '.join(out)


def main(song_dir, pages):
    from paddleocr import PaddleOCR

    def engine(rec):
        return PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',
                         text_recognition_model_name=rec, use_doc_orientation_classify=False,
                         use_doc_unwarping=False, use_textline_orientation=False,
                         enable_mkldnn=False)   # paddle 3.3 oneDNN fails on these models

    ja, en = engine('PP-OCRv5_server_rec'), engine('en_PP-OCRv5_mobile_rec')
    imgs = sorted(glob.glob(os.path.join(song_dir, 'input', 'extracted', 'e-*.png')))
    lines = ['# tools/page_regions.py: facts from the page margins (raw OCR) with coordinates.',
             '# Coordinates are pixels of the page after deskew: Image.rotate(deg, BICUBIC) of the '
             'input PNG (counter-clockwise, about the centre); box = x0,y0,x1,y1.']
    systems, doubts = [], []
    for page in pages:
        im, angle = deskew(Image.open(imgs[page - 1]).convert('L'))
        gray = np.array(im)
        ink = gray < 128
        h, w = ink.shape
        faint = close_gaps(gray < 200)                  # staff lines are faint
        top, bottom, left, lv = score_block(faint)
        a_end = blank_edge(ink, top, -1)
        # a page number can sit close under the last staff: C starts just below it at the latest
        c_start = min(blank_edge(ink, bottom, +1), bottom + int(0.01 * h))
        b_right = int(left[top:bottom + 1].max())
        stv = staves(faint, top, bottom, int(np.median(left[top:bottom + 1])), lv)
        lines += [f'\n## p{page:02d}  {os.path.basename(imgs[page - 1])}  {w}x{h}  deg={angle:.2f}',
                  f'[p{page:02d} region] score block (staff lines) y={top}..{bottom}',
                  f'[p{page:02d} region] A box=0,0,{w},{a_end}',
                  f'[p{page:02d} region] B box=0,{a_end},{b_right},{c_start}  '
                  "(per row only left of the staff's start line, see staves)",
                  f'[p{page:02d} region] C box=0,{c_start},{w},{h}']
        lines += [f'[p{page:02d} staff] system={k} y={y0}..{y1} lines={n} '
                  f'start_x={left[(y0 + y1) // 2]}' for y0, y1, n, k in stv]
        for y, x, text, score, box in read(ja, im.crop((0, 0, w, a_end)), 0, 0):
            lines.append(f'[p{page:02d} A] box={",".join(map(str, box))} {text}  ({score:.2f})')
        # B: per row, keep only what is left of that row's staff line start
        b = np.array(im.crop((0, a_end, b_right, c_start)))
        cols = np.arange(b.shape[1])[None, :]
        b[cols >= (left[a_end:c_start] - int(0.005 * w))[:, None]] = 255
        words = read(en, Image.fromarray(b), 0, a_end)
        for y, x, text, score, box in words:
            lines.append(f'[p{page:02d} B] box={",".join(map(str, box))} {text}  ({score:.2f})')
        for y, x, text, score, box in read(en, im.crop((0, c_start, w, h)), 0, c_start):
            lines.append(f'[p{page:02d} C] box={",".join(map(str, box))} {text}  ({score:.2f})')
        gap = np.median([(y1 - y0) / (n - 1) for y0, y1, n, _ in stv if n > 1])
        ps, ds = parts(stv, words, gap)
        systems += ps
        doubts += [f'p{page:02d}: {d}' for d in ds]
        for k, p in enumerate(ps, 1):
            lines.append(f'[p{page:02d} S{k}] ' + '; '.join(f'{t}:{n}' for t, n, _ in p))
    if systems:
        lines.append('\n## partsHint draft (staves per part from the staff lines; '
                     'add :lyrics / :drums yourself)\n' + hint(systems, doubts))
    lines.append('\n## doubts (what the tool could not settle from the text)')
    lines += [f'- {d}' for d in doubts] or ['none']
    out = os.path.join(song_dir, 'context', 'page_regions.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(out)


if __name__ == '__main__':
    main(sys.argv[1], [int(p) for p in sys.argv[2:]] or [1])
