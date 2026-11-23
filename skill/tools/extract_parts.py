#!/usr/bin/env python3
"""Cut image parts (one PDF per instrument) out of a band-score scan that was already run
through Audiveris.

Only the printed layout is used: raw/*.omr gives every system's staff positions and the logical
part each printed staff belongs to, and input/omr_in/<page>.png is cropped at the original scan
resolution.  No note data is read, so OMR note mistakes do not reach the parts.

Every system is kept, one to one with the full score.  A part hidden on a system (empty staves
omitted in print) becomes a placeholder so the system count stays the same.  A second staff that
Audiveris did not export (usually a TAB staff) stays with its own part, using the staff count in
book.xml, instead of being cut into the part below.  The staff gap is cut
where the widest blank row band sits near the middle between the two staves; when no clean band
exists the middle is used and the place is listed in check_gaps.txt.

System-level marks above the top staff (tempo, rehearsal marks) are attached above every part.
--with-chords adds the printed chord-symbol row, --with-lyrics adds the vocal staff and lyrics as
a reference above each system.  Both are off by default.

Usage (from skill/):
  python tools/extract_parts.py S [--out S/parts] [--with-chords] [--with-lyrics]
                                 [--parts P1,P3] [--dpi 150]
Output: <out>/NN_<instrument>.pdf, <out>/overview.png, <out>/check_gaps.txt, <out>/index.txt.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fonts  # noqa: E402
from proof_pairs import read_systems  # noqa: E402

A4 = {150: (1240, 1754), 200: (1654, 2339), 300: (2480, 3508)}
MARGIN = 42
BOTTOM = 58
SYSTEM_GAP = 16
STRIP_GAP = 3
VOCAL = re.compile(r'vocal|voice|chorus|cho\b|vo\.', re.I)


def read_book(omr):
    """Logical parts of the score in printed order: id -> name/abbreviation."""
    with zipfile.ZipFile(omr) as z:
        book = ET.fromstring(z.read('book.xml'))
    parts = {}
    for lp in book.iter('logical-part'):
        count = int(lp.get('staff-count') or len(lp.findall('staff-configuration')) or 0)
        parts[int(lp.get('id'))] = dict(name=lp.get('name') or '', abbr=lp.get('abbreviation') or '',
                                        staves=max(1, count))
    return parts


def read_texts(omr):
    """Text boxes on the page: sentences (role) and printed chord names."""
    with zipfile.ZipFile(omr) as z:
        root = ET.fromstring(z.read('sheet#1/sheet#1.xml'))
    boxes = []
    for tag, role in (('sentence', None), ('chord-name', 'ChordName')):
        for e in root.iter(tag):
            b = e.find('bounds')
            if b is None:
                continue
            boxes.append(dict(role=role or e.get('role', ''), staff=int(e.get('staff', '0')),
                              x=int(b.get('x')), y=int(b.get('y')),
                              w=int(b.get('w')), h=int(b.get('h'))))
    seen, unique = set(), []
    for b in boxes:
        key = (b['role'], b['x'], b['y'], b['w'], b['h'])
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def extend_missing_staves(systems, book, interline):
    """Audiveris sometimes exports only the first staff of a two-staff part (a TAB staff is a
    common miss).  The whole gap down to the next printed part then stays with that part, so the
    missing staff is not cut into the part below."""
    for system in systems:
        order = sorted(system['parts'], key=lambda lid: min(t for t, _ in system['parts'][lid]))
        for i, lid in enumerate(order):
            staves = system['parts'][lid]
            missing = book.get(lid, {}).get('staves', 1) - len(staves)
            if missing <= 0 or i + 1 >= len(order):
                continue
            next_top = min(t for t, _ in system['parts'][order[i + 1]])
            bottom = max(b for _, b in staves)
            if next_top - 1.5 * interline > bottom:
                staves.append((bottom, next_top - 1.5 * interline))
                system['parts'][lid].sort()


def system_spans(system):
    """Top/bottom staff line for each logical part and for the whole system."""
    ext = {lid: (min(t for t, _ in st), max(b for _, b in st))
           for lid, st in system['parts'].items() if st}
    if not ext:
        return {}, 0, 0
    return ext, min(a for a, _ in ext.values()), max(b for _, b in ext.values())


def assign_system(box, spans, interline):
    """The system a text box belongs to: nearest by vertical distance (headers sit above a top staff)."""
    y = box['y'] + box['h'] / 2
    best = None
    for i, (top, bottom) in enumerate(spans):
        d = 0 if top <= y <= bottom else min(abs(y - top), abs(y - bottom))
        if best is None or d < best[0]:
            best = (d, i)
    return best[1] if best else 0


def find_split(arr, interline, x0, x1, low, high, prefer):
    """A blank row band near prefer, between low and high.  Returns (y, clean)."""
    low, high = int(max(0, low)), int(min(arr.shape[0], high))
    if high - low < 2:
        return prefer, False
    ink = (arr[low:high, max(0, x0):x1] < 160).sum(axis=1)
    blank = ink <= max(2, int((x1 - x0) * 0.005))
    runs, y = [], 0
    while y < len(blank):
        if not blank[y]:
            y += 1
            continue
        start = y
        while y < len(blank) and blank[y]:
            y += 1
        if y - start >= 2:
            runs.append((low + start, low + y, (2 * low + start + y - 1) / 2))
    near = [r for r in runs if abs(r[2] - prefer) <= 6 * interline]
    if not near:
        return prefer, False
    _, _, center = max(near, key=lambda r: (r[1] - r[0], -abs(r[2] - prefer)))
    return center, True


def trim_rows(img):
    inv = ImageOps.invert(img).getbbox()
    if inv is None:
        return None
    return img.crop((0, max(0, inv[1] - 2), img.width, min(img.height, inv[3] + 2)))


def safe_name(name):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_') or 'part'


def page_scan(song, stem):
    path = os.path.join(song, 'input', 'omr_in', stem + '.png')
    if not os.path.exists(path):
        sys.exit('%s not found: the original scan page for %s is required' % (path, stem))
    return Image.open(path).convert('L')


def title_image(song, stem):
    """Title area of the first page, from the uncropped scan in input/extracted."""
    meta = os.path.join(song, 'crop_meta', stem + '.json')
    if not os.path.exists(meta):
        return None
    with open(meta, encoding='utf-8') as fh:
        data = json.load(fh)
    src = os.path.join(song, 'input', 'extracted', data.get('source', ''))
    if not os.path.exists(src):
        return None
    scale = float(data.get('scale', 1))
    y0 = int(data['crop'][1] / scale) + 4
    img = Image.open(src).convert('L')
    img = img.crop((0, 0, img.width, min(img.height, y0)))
    return trim_rows(img)


def part_crop(arr, image, interline, system, lid, x0, x1, gaps, vocal=False):
    """Crop one logical part (all its staves) and note unclean cuts in gaps."""
    ext, _, _ = system_spans(system)
    if lid not in ext:
        return None
    top, bottom = ext[lid]
    above = [b for o, (_, b) in ext.items() if o != lid and b < top]
    below = [t for o, (t, _) in ext.items() if o != lid and t > bottom]
    if above:
        cut, clean = find_split(arr, interline, x0, x1, max(above), top, (max(above) + top) / 2)
        if not clean:
            gaps.append(('top', lid))
        top = cut
    else:
        top = top - 1.2 * interline
    if below and vocal:
        bottom = (bottom + min(below)) / 2
    elif below:
        cut, clean = find_split(arr, interline, x0, x1, bottom, min(below),
                                (bottom + min(below)) / 2)
        if not clean:
            gaps.append(('bottom', lid))
        bottom = cut
    else:
        bottom = bottom + 3 * interline
    box = (int(max(0, x0)), int(max(0, top)), int(min(image.width, x1)),
           int(min(image.height, bottom)))
    return image.crop(box)


def header_crop(image, system, boxes, interline, x0, x1, with_chords):
    """System-level marks above the top staff; chord names are blanked unless --with-chords."""
    _, top, _ = system_spans(system)
    near = [b for b in boxes if b['y'] + b['h'] <= top + interline and b['y'] >= top - 10 * interline
            and x0 - 80 <= b['x'] <= x1]
    htop = min((b['y'] for b in near), default=top - 4 * interline) - 0.8 * interline
    htop = int(max(0, htop))
    hbottom = int(top - 1.2 * interline)
    img = image.crop((int(x0), htop, int(x1), hbottom))
    if not with_chords:
        d = ImageDraw.Draw(img)
        pad = int(0.7 * interline)
        for b in near:
            if b['role'] == 'ChordName':
                d.rectangle([b['x'] - pad - x0, b['y'] - pad - htop,
                             b['x'] + b['w'] + pad - x0, b['y'] + b['h'] + pad - htop],
                            fill=255)
    return trim_rows(img)


def hstack(images):
    out = Image.new('L', (images[0].width, sum(im.height for im in images) + STRIP_GAP * (len(images) - 1)), 255)
    y = 0
    for im in images:
        out.paste(im, (0, y))
        y += im.height + STRIP_GAP
    return out


def placeholder(width, interline, text):
    img = Image.new('L', (int(width), int(4 * interline)), 255)
    fonts.draw_text(ImageDraw.Draw(img), (12, int(1.4 * interline)), text, int(2 * interline))
    return img


def paginate(blocks, dpi):
    """Lay out (label, image) blocks on A4 pages; returns PIL pages."""
    width, height = A4.get(dpi, (int(8.27 * dpi), int(11.69 * dpi)))
    content = width - 2 * MARGIN
    pages, cur, y = [], None, height

    def new_page():
        nonlocal cur, y
        cur = Image.new('L', (width, height), 255)
        pages.append(cur)
        y = MARGIN

    for _, block in blocks:
        if block.width != content:
            block = block.resize((content, max(1, round(block.height * content / block.width))))
        if cur is None or (block.height <= height - MARGIN - BOTTOM
                           and y + block.height > height - BOTTOM):
            new_page()
        while block.height:
            if y >= height - BOTTOM - 20:
                new_page()
            h = min(height - BOTTOM - y, block.height)
            cur.paste(block.crop((0, 0, content, h)), (MARGIN, y))
            y += h
            block = block.crop((0, h, content, block.height))
            if block.height:
                new_page()
        y += SYSTEM_GAP
    for i, page in enumerate(pages, 1):
        fonts.draw_text(ImageDraw.Draw(page), (width // 2 - 8, height - 38), str(i), 20)
    return pages


def overview(parts, out):
    """One image with every cut system for checking."""
    items = [(label, img) for label, img in parts]
    tw = 360
    cols = 5
    rows = (len(items) + cols - 1) // cols
    cells = []
    height = 0
    for label, img in items:
        thumb = img.resize((tw, max(1, round(img.height * tw / img.width))))
        cell = Image.new('L', (tw, thumb.height + 26), 255)
        fonts.draw_text(ImageDraw.Draw(cell), (4, 2), label, 15)
        cell.paste(thumb, (0, 26))
        cells.append(cell)
        height = max(height, cell.height)
    sheet = Image.new('L', (cols * tw + 8 * (cols + 1), rows * (height + 8) + 8), 255)
    for i, cell in enumerate(cells):
        x = 8 + (i % cols) * (tw + 8)
        y = 8 + (i // cols) * (height + 8)
        sheet.paste(cell, (x, y))
    sheet.save(os.path.join(out, 'overview.png'), optimize=True)


def title_block(song, stem, name, dpi):
    """Title crop plus the instrument name, for the first page of a part."""
    width = A4[dpi][0] - 2 * MARGIN
    parts = []
    title = title_image(song, stem)
    if title is not None:
        parts.append(title.resize((width, max(1, round(title.height * width / title.width)))))
    bar = Image.new('L', (width, 64), 255)
    fonts.draw_text(ImageDraw.Draw(bar), (0, 4), name, 42)
    parts.append(bar)
    out = Image.new('L', (width, sum(p.height for p in parts) + 10 * (len(parts) - 1)), 255)
    y = 0
    for part in parts:
        out.paste(part, (0, y))
        y += part.height + 10
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song_dir')
    ap.add_argument('--out')
    ap.add_argument('--with-chords', action='store_true')
    ap.add_argument('--with-lyrics', action='store_true')
    ap.add_argument('--parts', help='logical part ids or names, e.g. P1,Vocal')
    ap.add_argument('--dpi', type=int, default=150, choices=sorted(A4))
    ap.add_argument('--min-stack', type=int, default=300)
    args = ap.parse_args()

    song = args.song_dir.rstrip('/')
    raw = os.path.join(song, 'raw')
    omrs = sorted(f for f in os.listdir(raw) if f.endswith('.omr'))
    if not omrs:
        sys.exit('no .omr pages in %s' % raw)
    out = args.out or os.path.join(song, 'parts')
    os.makedirs(out, exist_ok=True)
    book = read_book(os.path.join(raw, omrs[0]))
    wanted = None
    if args.parts:
        tokens = [t.strip().lower() for t in args.parts.split(',')]
        wanted = {i for i, p in book.items()
                  if str(i).lower() in tokens or p['name'].lower() in tokens}
        if not wanted:
            sys.exit('--parts matched no logical part')
    order = [i for i in sorted(book) if wanted is None or i in wanted]
    vocal = next((i for i in sorted(book) if VOCAL.search(book[i]['name'] + ' ' + book[i]['abbr'])), None)

    total = 0
    for f in omrs:
        total += len(read_systems(os.path.join(raw, f), args.min_stack)[2])
    gaps = []
    made, printed = [], {}
    for n, lid in enumerate(order, 1):
        blocks, seen = [], 0
        for f in omrs:
            stem = f[:-4]
            path = os.path.join(raw, f)
            geometry, interline, systems = read_systems(path, args.min_stack)
            image = page_scan(song, stem)
            if image.size != (geometry.width, geometry.height):
                sys.exit('%s: scan %s and .omr %s have different sizes'
                         % (stem, image.size, geometry.size))
            arr = np.asarray(image)
            extend_missing_staves(systems, book, interline)
            spans = [(system_spans(s)[1], system_spans(s)[2]) for s in systems]
            boxes = read_texts(path)
            for b in boxes:
                b['system'] = assign_system(b, spans, interline)
            page = int(stem.rsplit('_p', 1)[1][:2])
            for k, system in enumerate(systems, 1):
                ext = system_spans(system)[0]
                if not ext:
                    continue
                x0 = system['stacks'][0][0] - interline
                x1 = system['stacks'][-1][1] + interline
                local = [b for b in boxes if b['system'] == k - 1]
                strips = []
                hdr = header_crop(image, system, local, interline, x0, x1, args.with_chords)
                if hdr is not None:
                    strips.append(hdr)
                if args.with_lyrics and vocal and lid != vocal and vocal in ext:
                    vc = part_crop(arr, image, interline, system, vocal, x0, x1, [], vocal=True)
                    if vc is not None:
                        strips.append(trim_rows(vc))
                crop, cut = None, []
                if lid in ext:
                    crop = part_crop(arr, image, interline, system, lid, x0, x1, cut,
                                     vocal=(lid == vocal))
                    gaps.extend((stem, k, book[lid]['name'], side) for side, _ in cut)
                if crop is not None:
                    strips.append(trim_rows(crop))
                    seen += 1
                else:
                    strips.append(placeholder(x1 - x0, interline,
                                              '%s: not printed on this system' % book[lid]['name']))
                block = hstack([s for s in strips if s is not None])
                blocks.append(('p%02d s%d %s' % (page, k, book[lid]['name']), block))
        name = safe_name(book[lid]['name'] or book[lid]['abbr'])
        filename = '%02d_%s.pdf' % (n, name)
        tb = title_block(song, omrs[0][:-4], book[lid]['name'], args.dpi)
        pages_out = paginate([('title', tb)] + blocks, args.dpi)
        first, rest = pages_out[0], pages_out[1:]
        first.save(os.path.join(out, filename), save_all=True, append_images=rest,
                   resolution=args.dpi)
        printed[lid] = filename
        made.extend(blocks)
        print('%s  %s  systems=%d  placeholder=%d' % (filename, book[lid]['name'], seen,
                                                      len(blocks) - seen))
    with open(os.path.join(out, 'index.txt'), 'w', encoding='utf-8') as fh:
        for lid, filename in printed.items():
            fh.write('%s\t%s\t%d systems\n' % (filename, book[lid]['name'], total))
    with open(os.path.join(out, 'check_gaps.txt'), 'w', encoding='utf-8') as fh:
        for stem, k, name, side in gaps:
            fh.write('%s s%d\t%s\t%s cut at the staff middle (no clean blank band)\n'
                     % (stem, k, name, side))
    overview(made, out)
    print('wrote %s (check_gaps: %d, overview.png)' % (out, len(gaps)))


if __name__ == '__main__':
    main()
