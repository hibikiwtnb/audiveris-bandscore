#!/usr/bin/env python3
"""Read-only repeat/ending audit for merged band scores. No edits, always exit 0.

    python3 tools/audit_repeats.py <score.musicxml> [...]
    python3 tools/audit_repeats.py --table <score.musicxml> [...]
    python3 tools/audit_repeats.py --all            # songs/*/*/*.musicxml, merged only

Prints, per song, the repeat and ending timeline with page numbers (from the merged
score's own page breaks), the same flags score_quality.py reports, and the facts to
judge them against the printed score: the right barline style at each first ending,
printed text in and after that measure, and the nearest segno / coda / D.S. / D.C.
With --table only one TSV line per file is printed.

The flags are lists to check, not verdicts:
  first_ending_without_backward_repeat = a 1st ending whose last measure has no backward
    repeat. Printed scores using a D.S. jump (segno right after the 1st ending) are
    correct as they are; a missing printed repeat sign needs a repeat in every part.
  ending_numbers_incomplete = a group of adjacent endings without both 1 and 2
    (often a misread printed number).
  repeat_forward_without_backward = a forward repeat with no later backward repeat.
  repeat_backward_without_forward = a backward repeat with no earlier forward repeat
    after the previous backward (the first one means "repeat from the start").
  ending_not_closed = an ending with a start but no stop.
"""
import argparse
import bisect
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_quality  # noqa: E402


def page_map(first):
    """(measure index -> page number, measures per page). Page 1 starts at measure 0."""
    starts = [0] + [i for i, d in enumerate(first) if d['new_page'] and i]
    per = [b - a for a, b in zip(starts, starts[1:] + [len(first)])]
    return lambda i: bisect.bisect_right(starts, i), per


def bar_styles(root):
    """{part id: {measure index: (left style, right style)}}."""
    out = {}
    for part in root.findall('part'):
        per = {}
        for i, m in enumerate(part.findall('measure')):
            styles = {}
            for b in m.findall('barline'):
                loc = b.get('location', 'right')
                st = b.findtext('bar-style')
                if st:
                    styles[loc] = st
            per[i] = (styles.get('left'), styles.get('right'))
        out[part.get('id')] = per
    return out


def measure_words(root, index):
    """Printed words in the first part's measure at index, joined by '|'."""
    part = root.find('part')
    ms = part.findall('measure')
    if index >= len(ms):
        return ''
    words = [(w.text or '').strip() for w in ms[index].iter('words')]
    return '|'.join(w for w in words if w)


def nearest_marks(pm, pids, index, span=4):
    """Segno / coda / D.S. / D.C. facts near a measure (any part), as readable text."""
    lo, hi = max(0, index - span), index + span
    found = []
    for p in pids:
        for j in range(lo, min(hi + 1, len(pm[p]))):
            d = pm[p][j]
            for flag, label in (('segno', 'segno'), ('coda', 'coda'), ('ds', 'D.S.'), ('dc', 'D.C.')):
                if d[flag]:
                    found.append((j, label))
    return sorted(set(found))


def audit(path):
    root = ET.parse(path).getroot()
    parts = root.findall('part')
    pids = [p.get('id') for p in parts]
    pm = {p.get('id'): score_quality.read_measures(p) for p in parts}
    first = pm[pids[0]]
    numbers = [d['number'] for d in first]
    n = len(first)
    for p in pids:
        while len(pm[p]) < n:
            pm[p].append(dict(key=None, time=None, notes=0, rests=0, whole_rest=False,
                              has_note=True, len_bad=False, value_bad=False, new_page=False,
                              marks=[], endings=[], shifts=[], tempos=[],
                              segno=False, coda=False, dc=False, ds=False))
    page_of, per_page = page_map(first)
    styles = bar_styles(root)
    name = os.path.basename(path)
    out = [f'song={os.path.basename(os.path.dirname(path))}', f'file={name}',
           f'measures={n}', f'pages={len(per_page)}',
           'measures_per_page=' + ' '.join(str(x) for x in per_page)]

    signs = sorted({(i, order, direction) for p in pids for i, d in enumerate(pm[p])
                    for order, direction in d['marks']})
    out.append('repeat_signs=' + (' '.join(
        f'{direction}@m{numbers[i]}(p{page_of(i)})' for i, _, direction in signs) or 'none'))
    endings = score_quality.endings_of(pm)
    out.append('endings=' + (' '.join(
        f'{num}@m{numbers[a]}(p{page_of(a)})' + ('-?' if b is None else
                                                 f'-m{numbers[b]}' if b != a else '')
        for num, a, b in endings) or 'none'))

    unclosed, no_start, opened, seen_backward = [], [], None, False
    for i, _, direction in signs:
        if direction == 'forward':
            if opened is not None:
                unclosed.append(opened)
            opened = i
        elif opened is not None:
            opened, seen_backward = None, True
        else:
            no_start.append(i)
            seen_backward = True
    if opened is not None:
        unclosed.append(opened)

    backward_at = {i for i, _, direction in signs if direction == 'backward'}
    groups, cur = [], []
    for e in endings:
        if cur and e[1] > (cur[-1][2] if cur[-1][2] is not None else cur[-1][1]) + 1:
            groups.append(cur)
            cur = []
        cur.append(e)
    if cur:
        groups.append(cur)
    incomplete = []
    for g in groups:
        nums = {int(x) for e in g for x in re.findall(r'\d+', e[0])}
        if (1 in nums) != (2 in nums):
            incomplete.append(g[0][1])
    first_open = [a for num, a, b in endings
                  if 1 in [int(x) for x in re.findall(r'\d+', num)]
                  and b is not None and b not in backward_at]
    open_end = [a for num, a, b in endings if b is None]

    out.append('[flags]')
    for label, idx in (('first_ending_without_backward_repeat', first_open),
                       ('ending_numbers_incomplete', incomplete),
                       ('repeat_forward_without_backward', unclosed),
                       ('repeat_backward_without_forward', no_start),
                       ('ending_not_closed', open_end)):
        out.append(f'{label} count={len(idx)}' + ('' if not idx else
                   ' at=' + ' '.join(f'm{numbers[i]}(p{page_of(i)})' for i in idx)))
    focus = sorted(set(first_open + incomplete + unclosed + no_start + open_end))
    if focus:
        out.append('[evidence]')
    for i in focus:
        found = nearest_marks(pm, pids, i)
        marks = ' '.join(f'{lab}@m{numbers[j]}' for j, lab in found) or 'none'
        right = [styles[p][i][1] if i < len(styles[p]) else None for p in pids]
        right_style = collections_count(right)
        out.append(f'm{numbers[i]}(p{page_of(i)}) right_barline={right_style} '
                   f'words="{measure_words(root, i)}" near_marks={marks}')
    return out


def collections_count(values):
    seen = {}
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    return ','.join(f'{k or "none"}x{v}' for k, v in sorted(seen.items(), key=lambda x: str(x[0])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--all', action='store_true', help='merged songs/*/*/*.musicxml')
    ap.add_argument('--table', action='store_true', help='one TSV line per file')
    a = ap.parse_args()
    paths = list(a.paths)
    if a.all:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'songs')
        paths += sorted(p for p in glob.glob(os.path.join(base, '**', '*.musicxml'),
                                             recursive=True)
                        if os.sep + 'pages' + os.sep not in p)
    if not paths:
        ap.error('give a .musicxml path or --all')
    for path in paths:
        lines = audit(path)
        if a.table:
            facts = dict(x.split('=', 1) for x in lines if '=' in x)
            print('\t'.join(facts.get(k, '') for k in
                            ('song', 'file', 'measures', 'pages', 'repeat_signs', 'endings'))
                  + '\t' + '\t'.join(x for x in lines if x.startswith(
                      ('first_ending_without_backward_repeat', 'ending_numbers_incomplete',
                       'repeat_forward_without_backward', 'repeat_backward_without_forward',
                       'ending_not_closed'))))
        else:
            print('\n'.join(lines))
            print()


if __name__ == '__main__':
    main()
