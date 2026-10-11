#!/usr/bin/env python3
"""Check what MuseScore actually makes of a score: displayed pitches, instrument changes, 8va.

    python3 tools/verify_musescore.py <score.musicxml> [--mscore mscore]

Converts the score with MuseScore (headless) to .mscx and compares, staff by staff and measure
by measure, the pitches MuseScore stores (= displayed pitches: an 8va line is already taken
off) with the XML pitches minus the octave-shift lines of that staff (a drum note's pitch is
its instrument's midi-unpitched - 1, the GM key MuseScore stores). Also counts
InstrumentChange, Ottava and invisible notes per staff. Exit code 1 on any mismatch.

A mismatch right after an octave-shift usually means the parts have unequal measure lengths
(MuseScore times octave-shifts with per-part cumulative time); see the skill.
"""
import argparse
import env
import collections
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

STEP = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def midi(n):
    p = n.find('pitch')
    return (12 * (int(p.findtext('octave')) + 1) + STEP[p.findtext('step')]
            + int(float(p.findtext('alter') or 0)))


def xml_staves(path):
    """[(label, [sorted display pitches per measure])] in MuseScore staff order."""
    root = ET.parse(path).getroot()
    drum = {i.get('id'): int(i.findtext('midi-unpitched')) - 1
            for i in root.iter('midi-instrument') if i.findtext('midi-unpitched')}
    out = []
    for part in root.findall('part'):
        nst = max([int(e.text) for e in part.iter('staves')] or [1])
        per = {str(s): [] for s in range(1, nst + 1)}
        shift = {s: 0 for s in per}
        for m in part.findall('measure'):
            cur = {s: [] for s in per}
            for el in m:
                if el.tag == 'direction':
                    o = el.find('direction-type/octave-shift')
                    if o is not None:
                        s = el.findtext('staff') or '1'
                        size = 2 if o.get('size') == '15' else 1
                        shift[s] = 0 if o.get('type') == 'stop' else \
                            size * (1 if o.get('type') == 'down' else -1)
                elif el.tag == 'note' and el.find('pitch') is not None:
                    s = el.findtext('staff') or '1'
                    cur[s].append(midi(el) - 12 * shift[s])
                elif el.tag == 'note' and el.find('unpitched') is not None:
                    i = el.find('instrument')
                    if i is not None and i.get('id') in drum:
                        cur[el.findtext('staff') or '1'].append(drum[i.get('id')])
            for s in per:
                per[s].append((m.get('number'), sorted(cur[s])))
        for s in per:
            out.append((f"{part.get('id')} staff {s}", per[s]))
    return out


def mscx_staves(path):
    s = open(path, encoding='utf-8').read()
    body = s[s.index('<Staff id="1">', s.index('</Part>', s.rindex('<Part>'))):]
    out = []
    for m in re.finditer(r'<Staff id="(\d+)">(.*?)(?=<Staff id="|\Z)', body, re.S):
        text = m.group(2)
        measures = [sorted(int(x) for x in re.findall(r'<pitch>(\d+)</pitch>', ms))
                    for ms in text.split('<Measure')[1:]]
        out.append(dict(measures=measures,
                        changes=len(re.findall(r'<InstrumentChange>', text)),
                        ottava=len(re.findall(r'<Ottava>', text)),
                        invisible=len(re.findall(r'<Note>\s*<visible>0', text))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('score')
    ap.add_argument('--mscore', help='default: MUSESCORE_BIN in environment.txt')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        mscx = os.path.join(tmp, 'score.mscx')
        subprocess.run([a.mscore or env.load(('MUSESCORE_BIN',))['MUSESCORE_BIN'], '-o', mscx, a.score], capture_output=True)
        if not os.path.exists(mscx):
            sys.exit('MuseScore conversion failed')
        ms = mscx_staves(mscx)
    xs = xml_staves(a.score)
    bad = 0
    if len(ms) != len(xs):
        print(f'staff count differs: XML {len(xs)}, MuseScore {len(ms)}')
        bad += 1
    # a note moved between the staves of one part (cross-staff) is not a pitch error:
    # compare such measures on the part as a whole
    part_x = collections.defaultdict(collections.Counter)
    part_m = collections.defaultdict(collections.Counter)
    for (label, xm), st in zip(xs, ms):
        pid = label.split()[0]
        for (num, p), q in zip(xm, st['measures']):
            part_x[(pid, num)] += collections.Counter(p)
            part_m[(pid, num)] += collections.Counter(q)
    for (label, xm), st in zip(xs, ms):
        pid = label.split()[0]
        diffs, cross = [], []
        for (num, p), q in zip(xm, st['measures']):
            if p != q:
                (cross if part_x[(pid, num)] == part_m[(pid, num)] else diffs).append((num, p, q))
        if cross:
            print(f"{label}: cross-staff (same notes, other staff) in "
                  f"{', '.join('m' + c[0] for c in cross)}")
        note = ''
        if len(xm) != len(st['measures']):
            note = f"  measure count XML {len(xm)} / MuseScore {len(st['measures'])}"
            bad += 1
        print(f"{label}: {len(diffs)} measures differ, {st['changes']} instrument changes, "
              f"{st['ottava']} ottava, {st['invisible']} invisible notes{note}")
        for num, p, q in diffs[:5]:
            print(f'    m{num}: XML {p}  MuseScore {q}')
        bad += len(diffs)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
