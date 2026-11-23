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

import cv2
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
    """Text, lyric, rehearsal and symbol boxes from every sheet#N/sheet#N.xml in the .omr."""
    with zipfile.ZipFile(omr) as z:
        book = ET.fromstring(z.read('book.xml'))
        sheets = sorted((n for n in z.namelist() if re.match(r'^sheet#\d+/sheet#\d+\.xml$', n)),
                        key=lambda n: int(n.split('#', 1)[1].split('/', 1)[0]))
        roots = [ET.fromstring(z.read(sh)) for sh in sheets]
    logical = [[int(p.get('logical-id')) for p in s.findall('part')] for s in book.iter('system')]
    boxes = []
    sys_idx = 0
    for root in roots:
        for sys_el in root.iter('system'):
            smap = {}
            for j, p in enumerate(sys_el.findall('part')):
                if sys_idx < len(logical) and j < len(logical[sys_idx]):
                    lid = logical[sys_idx][j]
                    for st in p.findall('staff'):
                        smap[int(st.get('id'))] = lid
            for e in sys_el.iter():
                if e.tag in ('system', 'part', 'staff', 'lines', 'line', 'stack', 'bar-connector', 'word'):
                    continue
                b = e.find('bounds')
                if b is None:
                    continue
                sid = int(e.get('staff', '0'))
                role = 'ChordName' if e.tag == 'chord-name' else (e.get('role') or e.tag)
                boxes.append(dict(tag=e.tag, role=role, staff=sid, lid=smap.get(sid, 0),
                                  system=sys_idx,
                                  x=int(b.get('x')), y=int(b.get('y')),
                                  w=int(b.get('w')), h=int(b.get('h'))))
            sys_idx += 1
    seen, unique = set(), []
    for b in boxes:
        key = (b['system'], b['tag'], b['role'], b['lid'], b['x'], b['y'], b['w'], b['h'])
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def lyric_bottom(top, bottom, boxes, lid, interline):
    """Bottom of lyric lines belonging to lid (within a reasonable distance below its staff)."""
    ends = [b['y'] + b['h'] for b in boxes
            if b['lid'] == lid and (b['tag'] in ('lyric-line', 'lyric-item') or b['role'] == 'Lyrics')
            and b['w'] >= interline // 2 and bottom <= b['y'] + b['h'] <= bottom + 5.8 * interline]
    return max(ends, default=bottom)


def find_tab_staff(arr, interline, x0, x1, bottom, next_top, is_bass=False):
    """Locate an unexported 4-line (bass) or 6-line (guitar) TAB staff between bottom and next_top."""
    n_lines = 4 if is_bass else 6
    y_a = int(max(0, bottom + 2.5 * interline))
    y_b = int(min(arr.shape[0], next_top - 3.5 * interline))
    if y_b - y_a < int(3.8 * interline):
        if next_top - 4 * interline > bottom + 4 * interline:
            return float(bottom + 4.5 * interline), float(min(next_top - 4 * interline, bottom + 11.5 * interline))
        return None
    x_s, x_e = int(max(0, x0)), int(min(arr.shape[1], x1))
    if x_e <= x_s:
        return None
    profile = (arr[y_a:y_b, x_s:x_e] < 215).mean(axis=1)
    smooth = np.convolve(profile, [0.25, 0.5, 0.25], mode='same')
    best_score, best_span = -1.0, None
    for step_10 in range(max(1, int(11.5 * interline)), int(14.0 * interline) + 1):
        step = step_10 / 10.0
        span = round((n_lines - 1) * step)
        if span >= len(smooth):
            continue
        for y0 in range(0, len(smooth) - span):
            ys = [y0 + round(k * step) for k in range(n_lines)]
            mids = [y0 + round((k + 0.5) * step) for k in range(n_lines - 1)]
            score = sum(smooth[y] for y in ys) / n_lines - 0.5 * sum(smooth[m] for m in mids) / (n_lines - 1)
            if score > best_score:
                best_score = float(score)
                best_span = (float(y_a + y0), float(y_a + ys[-1]))
    if best_span and best_score > 0.08:
        return best_span
    return float(bottom + 5 * interline), float(min(next_top - 4 * interline, bottom + 11.5 * interline))


def extend_missing_staves(systems, book, interline, arr=None):
    """Audiveris sometimes exports only the first staff of a two-staff part (a TAB staff is a
    common miss).  Locate the actual TAB staff lines (or reserve the expected TAB band) so the
    TAB staff stays with its own part without swallowing the gap above the next part."""
    for system in systems:
        order = sorted(system['parts'], key=lambda lid: min(t for t, _ in system['parts'][lid]))
        x0 = system['stacks'][0][0] if system.get('stacks') else 0
        x1 = system['stacks'][-1][1] if system.get('stacks') else (arr.shape[1] if arr is not None else 0)
        for i, lid in enumerate(order):
            staves = system['parts'][lid]
            missing = book.get(lid, {}).get('staves', 1) - len(staves)
            if missing <= 0 or i + 1 >= len(order):
                continue
            next_top = min(t for t, _ in system['parts'][order[i + 1]])
            bottom = max(b for _, b in staves)
            is_bass = 'bass' in book.get(lid, {}).get('name', '').lower()
            if arr is not None and x1 > x0:
                span = find_tab_staff(arr, interline, x0, x1, bottom, next_top, is_bass=is_bass)
            else:
                span = (bottom, min(next_top - 4 * interline, bottom + 11.5 * interline)) if next_top - 4 * interline > bottom else None
            if span is not None and span[1] > bottom:
                staves.append(span)
                system['parts'][lid].sort()


CONTENT_TAGS = frozenset({
    'head', 'head-chord', 'stem', 'beam', 'beam-group', 'flag', 'ledger',
    'rest', 'rest-chord', 'articulation', 'fermata', 'tuplet', 'ornament',
    'augmentation-dot', 'alter', 'pedal',
})


def part_content_spans(system, boxes, interline, arr=None, vocal_lid=None):
    """Actual vertical content span (min_y, max_y) for each logical part in the system,
    combining staff lines, TAB staves, lyrics, stems, beams and noteheads."""
    ext, _, _ = system_spans(system)
    if not ext:
        return {}
    spans = {lid: [t, lyric_bottom(t, b, boxes, lid, interline)] for lid, (t, b) in ext.items()}
    order = sorted(ext, key=lambda l: ext[l][0])
    pos = {l: i for i, l in enumerate(order)}
    x_min = (system['stacks'][0][0] + interline) if system.get('stacks') else 0
    for b in boxes:
        lid = b.get('lid', 0)
        if lid not in spans or b['tag'] not in CONTENT_TAGS:
            continue
        if b['x'] + b['w'] < x_min:
            continue
        idx = pos[lid]
        lim_top = (ext[order[idx - 1]][1] + 0.5 * interline) if idx > 0 else 0
        # Multi-staff parts (guitar/bass with TAB below) have no pitch symbols extending
        # more than 0.6*interline below their bottom TAB line; single-staff parts allow 3.5*interline.
        max_below = 0.6 * interline if len(system['parts'].get(lid, ())) > 1 else 3.5 * interline
        lim_bot = (ext[order[idx + 1]][0] - 0.5 * interline) if idx + 1 < len(order) else 999999
        by0, by1 = b['y'], b['y'] + b['h']
        if b['tag'] in ('rest', 'rest-chord', 'articulation', 'ornament', 'augmentation-dot') and (
                by1 < ext[lid][0] - 0.5 * interline or by0 > ext[lid][1] + 0.5 * interline):
            continue
        if by0 >= max(lim_top, ext[lid][0] - 6.5 * interline) and by1 <= min(lim_bot, ext[lid][1] + max_below):
            spans[lid][0] = min(spans[lid][0], float(by0))
            spans[lid][1] = max(spans[lid][1], float(by1))
    if (arr is not None and vocal_lid in spans and len(order) > 1 and order[0] == vocal_lid
            and spans[vocal_lid][1] < ext[vocal_lid][1] + 2.5 * interline and system.get('stacks')):
        ya = int(max(0, ext[vocal_lid][1] + 2.4 * interline))
        yb = int(min(arr.shape[0], ext[vocal_lid][1] + 5.6 * interline, spans[order[1]][0] - 0.3 * interline))
        xs = int(max(0, system['stacks'][0][0] + 2 * interline))
        xe = int(min(arr.shape[1], system['stacks'][-1][1] - interline))
        if yb > ya and xe > xs:
            sub_ink = (arr[ya:yb, xs:xe] < 185).sum(axis=1)
            lyric_rows = [ya + r for r, v in enumerate(sub_ink) if v > 8]
            if len(lyric_rows) >= max(4, int(0.6 * interline)):
                spans[vocal_lid][1] = max(spans[vocal_lid][1], float(max(lyric_rows)))
    return {lid: (lo, hi) for lid, (lo, hi) in spans.items()}


def attribute_boundary_components(arr, crop_arr, x0, top_y, bot_y, lid, system, c_spans, boxes, interline):
    """When two adjacent parts have overlapping or tight vertical ranges, erase connected ink
    components near the top/bottom boundary that belong to the neighboring part (by Audiveris
    symbol bounds or staff connection)."""
    ext, _, _ = system_spans(system)
    if lid not in ext:
        return
    H, W = arr.shape
    ch, cw = crop_arr.shape
    x_s, x_e = int(max(0, x0)), int(min(W, x0 + cw))
    if x_e <= x_s or ch < 4:
        return
    pad = int(6 * interline)
    wy0 = int(max(0, min([top_y - pad] + [t - pad for t, _ in ext.values()])))
    wy1 = int(min(H, max([bot_y + pad] + [b + pad for _, b in ext.values()])))
    win = (arr[wy0:wy1, x_s:x_e] < 195).astype(np.uint8)
    # Break thin 1-2px vertical bar-connector lines on the left margin
    left_w = min(win.shape[1], int(2.5 * interline))
    if left_w > 0:
        win[:, :left_w] = cv2.morphologyEx(win[:, :left_w], cv2.MORPH_OPEN, np.ones((1, 5), np.uint8))
    my_staff_top, my_staff_bot = ext[lid]
    other_ext = {o: s for o, s in ext.items() if o != lid}
    if not other_ext:
        return
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(win, connectivity=8)
    my_c_top, my_c_bot = c_spans.get(lid, (my_staff_top, my_staff_bot))
    other_boxes = [b for b in boxes if b.get('lid', 0) in other_ext and b['x'] + b['w'] >= x_s + interline]
    my_boxes = [b for b in boxes if b.get('lid', 0) == lid and b['x'] + b['w'] >= x_s + interline]
    # Also prepare a staff-broken window to separate symbols attached to neighbor staff lines
    h_runs = cv2.morphologyEx(win, cv2.MORPH_OPEN, np.ones((1, max(15, int(2.5 * interline))), np.uint8))
    h_thick = cv2.morphologyEx(h_runs, cv2.MORPH_OPEN, np.ones((7, 1), np.uint8))
    thin_lines = (h_runs > 0) & (h_thick == 0)
    ms0 = max(0, int(my_staff_top - 0.5 * interline) - wy0)
    ms1 = min(win.shape[0], int(my_staff_bot + 0.5 * interline) - wy0)
    thin_lines[ms0:ms1, :] = False
    win_sub = win.copy()
    win_sub[thin_lines] = 0
    num_sub, labels_sub, stats_sub, _ = cv2.connectedComponentsWithStats(win_sub, connectivity=8)

    def _box_overlap(gx0, gy0, gx1, gy1, b_list):
        best = 0
        for b in b_list:
            ix0, iy0 = max(gx0, b['x'] - 2), max(gy0, b['y'] - 2)
            ix1, iy1 = min(gx1, b['x'] + b['w'] + 2), min(gy1, b['y'] + b['h'] + 2)
            if ix1 > ix0 and iy1 > iy0:
                best = max(best, (ix1 - ix0) * (iy1 - iy0))
        return best

    erase_mask = np.zeros_like(win)
    # Also erase any pixel inside an Audiveris-attributed neighbor symbol box that does not overlap
    # our own staff band or our own symbol boxes.
    for ob in other_boxes:
        ox0, oy0, ox1, oy1 = ob['x'], ob['y'], ob['x'] + ob['w'], ob['y'] + ob['h']
        if oy1 <= top_y or oy0 >= bot_y:
            continue
        if oy0 <= my_staff_bot + 0.3 * interline and oy1 >= my_staff_top - 0.3 * interline:
            continue
        if _box_overlap(ox0, oy0, ox1, oy1, my_boxes) == 0:
            ry0, ry1 = max(0, oy0 - 1 - wy0), min(win.shape[0], oy1 + 1 - wy0)
            rx0, rx1 = max(0, ox0 - 1 - x_s), min(win.shape[1], ox1 + 1 - x_s)
            if ry1 > ry0 and rx1 > rx0:
                erase_mask[ry0:ry1, rx0:rx1] = 1
    for cur_num, cur_labels, cur_stats in ((num_labels, labels, stats), (num_sub, labels_sub, stats_sub)):
        for lbl in range(1, cur_num):
            cx, cy, bw, bh, _ = cur_stats[lbl]
            gy0, gy1 = wy0 + cy, wy0 + cy + bh
            gx0, gx1 = x_s + cx, x_s + cx + bw
            if gy1 <= top_y or gy0 >= bot_y:
                continue
            if gy0 <= my_staff_bot + 0.3 * interline and gy1 >= my_staff_top - 0.3 * interline:
                continue
            touches_other_staff = any(
                gy0 <= ob + 0.3 * interline and gy1 >= ot - 0.3 * interline
                for ot, ob in other_ext.values()
            )
            ov_my = _box_overlap(gx0, gy0, gx1, gy1, my_boxes)
            ov_other = _box_overlap(gx0, gy0, gx1, gy1, other_boxes)
            erase = False
            if touches_other_staff and ov_my == 0:
                erase = True
            elif ov_other > ov_my and ov_other >= 0.25 * max(1, bw * bh):
                erase = True
            elif ov_my == 0 and (gy0 < top_y or gy1 > bot_y):
                yc = (gy0 + gy1) / 2.0
                d_my = 0.0 if my_staff_top <= yc <= my_staff_bot else min(abs(yc - my_staff_top), abs(yc - my_staff_bot))
                d_other = min(
                    0.0 if ot <= yc <= ob else min(abs(yc - ot), abs(yc - ob))
                    for ot, ob in other_ext.values()
                )
                if d_other + 0.2 * interline < d_my:
                    erase = True
            if erase:
                erase_mask[cur_labels == lbl] = 1
    if erase_mask.any():
        erase_mask = cv2.dilate(erase_mask, np.ones((3, 3), np.uint8), iterations=1)
        cy0 = max(0, top_y - wy0)
        cy1 = min(win.shape[0], cy0 + ch)
        sub_mask = erase_mask[cy0:cy1, :cw]
        crop_arr[:sub_mask.shape[0], :sub_mask.shape[1]][sub_mask > 0] = 255


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
    low_i, high_i = int(max(0, min(low, high))), int(min(arr.shape[0], max(low, high)))
    if high_i - low_i >= 2 and high >= low:
        ink = (arr[low_i:high_i, max(0, int(x0)):int(x1)] < 160).sum(axis=1)
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
                runs.append((low_i + start, low_i + y, (2 * low_i + start + y - 1) / 2))
        near = [r for r in runs if abs(r[2] - prefer) <= 6 * interline]
        if near:
            _, _, center = max(near, key=lambda r: (r[1] - r[0], -abs(r[2] - prefer)))
            return center, True
    # No complete blank band: pick the minimum-ink row inside [min(low, high), max(low, high)]
    s_lo = int(max(0, min(low, high)))
    s_hi = int(min(arr.shape[0], max(low, high)))
    if s_hi - s_lo < 2:
        return prefer, False
    ink = (arr[s_lo:s_hi, max(0, int(x0)):int(x1)] < 160).sum(axis=1)
    best_y = min(range(len(ink)), key=lambda i: (int(ink[i]), abs(s_lo + i - prefer)))
    return float(s_lo + best_y), False


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


def part_crop(arr, image, interline, system, lid, x0, x1, gaps, vocal=False, boxes=(), vocal_lid=None):
    """Crop one logical part (all its staves) using content extents and component attribution."""
    ext, _, _ = system_spans(system)
    if lid not in ext:
        return None
    c_spans = part_content_spans(system, boxes, interline, arr=arr, vocal_lid=vocal_lid or (lid if vocal else None))
    top, bottom = ext[lid]
    my_top, my_low = c_spans.get(lid, (top, bottom))
    above_parts = [(o, c_spans[o][1], ext[o][1]) for o, (_, b) in ext.items() if o != lid and b < top]
    below_parts = [(o, c_spans[o][0], ext[o][0]) for o, (t, _) in ext.items() if o != lid and t > bottom]
    need_cc = False
    if above_parts:
        _, low_a, staff_b_a = max(above_parts, key=lambda item: item[2])
        prefer = (low_a + my_top) / 2 if low_a <= my_top else (staff_b_a + top) / 2
        cut, clean = find_split(arr, interline, x0, x1, low_a, my_top, prefer)
        if not clean:
            gaps.append(('top', lid))
            need_cc = True
        top_cut = min(cut, my_top - 4) if not clean else cut
    else:
        top_cut = min(top - 1.5 * interline, my_top - 4)
    if below_parts:
        _, high_b, staff_t_b = min(below_parts, key=lambda item: item[2])
        prefer = (my_low + 0.6 * interline if (vocal and my_low > bottom)
                  else ((my_low + high_b) / 2 if my_low <= high_b else (bottom + staff_t_b) / 2))
        cut, clean = find_split(arr, interline, x0, x1, my_low, high_b, prefer)
        if not clean:
            gaps.append(('bottom', lid))
            need_cc = True
        bot_cut = max(cut, my_low + 4) if not clean else cut
    else:
        bot_cut = max(my_low + 0.8 * interline, bottom + 3 * interline)
    box = (int(max(0, x0)), int(max(0, top_cut)), int(min(image.width, x1)),
           int(min(image.height, bot_cut)))
    cropped = image.crop(box)
    if need_cc or above_parts or below_parts:
        crop_arr = np.asarray(cropped).copy()
        attribute_boundary_components(arr, crop_arr, box[0], box[1], box[3], lid, system,
                                      c_spans, boxes, interline)
        cropped = Image.fromarray(crop_arr)
    return cropped


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
            extend_missing_staves(systems, book, interline, arr=arr)
            spans = [(system_spans(s)[1], system_spans(s)[2]) for s in systems]
            boxes = read_texts(path)
            for b in boxes:
                if 'system' not in b:
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
                    vc = part_crop(arr, image, interline, system, vocal, x0, x1, [], vocal=True,
                                   boxes=local, vocal_lid=vocal)
                    if vc is not None:
                        strips.append(trim_rows(vc))
                crop, cut = None, []
                if lid in ext:
                    crop = part_crop(arr, image, interline, system, lid, x0, x1, cut,
                                     vocal=(lid == vocal), boxes=local, vocal_lid=vocal)
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
