#!/usr/bin/env python3
"""Check what MuseScore actually makes of a score: displayed pitches, measure lengths,
instrument changes, 8va.

    python3 tools/verify_musescore.py <score.musicxml> [--mscore mscore]

Converts the score with MuseScore (headless) to .mscx and compares, staff by staff and measure
by measure, the pitches MuseScore stores (= displayed pitches: an 8va line is already taken
off) with the XML pitches minus the octave-shift that covers each note's exact onset (a drum
note's pitch is its instrument's midi-unpitched - 1, the GM key MuseScore stores).  The onset
and the octave-shift intervals come from tools/score_time.py, so backup / forward, voices,
direction offsets and document order do not change the expectation; a stop is end-exclusive.
All differing measures are listed, split into octave/pitch differences and
note-set/measure-repeat differences (cross-staff notes are reported separately).

Also reads the measure length MuseScore computed for every staff. The MusicXML <duration>
values can add up to a full measure while MuseScore still builds an irregular measure (e.g. a
tuplet split into stray <time-modification> runs): MuseScore then stores a <Measure len="...">
and the score shows that measure with a "?" instead of its number. Each such measure is listed
with MuseScore's length and the time-signature length; these count as failures too.

Also counts InstrumentChange, Ottava and invisible notes per staff. Exit code 1 on any
mismatch. MuseScore measure-repeat symbols represent the notes of the referenced earlier
measures.

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
from fractions import Fraction as F

import score_time

STEP = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def midi(n):
    p = n.find('pitch')
    return (12 * (int(p.findtext('octave')) + 1) + STEP[p.findtext('step')]
            + int(float(p.findtext('alter') or 0)))


def transpose_offset(part):
    """Semitones MuseScore moves the written pitch to sounding pitch (part <transpose>)."""
    tr = part.find('.//transpose')
    if tr is None:
        return 0
    return int(tr.findtext('chromatic') or 0) + 12 * int(tr.findtext('octave-change') or 0)


def xml_staves(path):
    """[(label, [sorted display pitches per measure])] in MuseScore staff order.

    The expected display pitch is taken from the note's exact onset (tools/score_time.py)
    and the octave-shift interval containing it, so backup / forward, voices and document
    order cannot move a note into or out of a shift.
    """
    root = ET.parse(path).getroot()
    drum = {i.get('id'): int(i.findtext('midi-unpitched')) - 1
            for i in root.iter('midi-instrument') if i.findtext('midi-unpitched')}
    out = []
    for part in root.findall('part'):
        nst = max([int(e.text) for e in part.iter('staves')] or [1])
        transpose = transpose_offset(part)
        per = {str(s): [] for s in range(1, nst + 1)}
        divs = score_time.measure_divs(part)
        starts = score_time.measure_starts(part)
        intervals = score_time.octave_intervals(part)
        for m, div, st in zip(part.findall('measure'), divs, starts):
            cur = {s: [] for s in per}
            for e in score_time.walk(m, div, st):
                if e.tag != 'note':
                    continue
                cur.setdefault(e.staff, [])
                if e.el.find('pitch') is not None:
                    shift = score_time.shift_at(intervals, e.staff, e.tick)
                    cur[e.staff].append(midi(e.el) - 12 * shift + transpose)
                elif e.el.find('unpitched') is not None:
                    i = e.el.find('instrument')
                    if i is not None and i.get('id') in drum:
                        cur[e.staff].append(drum[i.get('id')])
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
        measures = []
        for ms in text.split('<Measure')[1:]:
            pitches = sorted(int(x) for x in re.findall(r'<pitch>(\d+)</pitch>', ms))
            repeat = re.search(r'<RepeatMeasure>(.*?)</RepeatMeasure>', ms, re.S)
            if repeat:
                count = re.search(r'<numMeasures>(\d+)</numMeasures>', repeat.group(1))
                distance = int(count.group(1)) if count else 1
                if len(measures) >= distance:
                    pitches = measures[-distance].copy()
            measures.append(pitches)
        out.append(dict(measures=measures,
                        changes=len(re.findall(r'<InstrumentChange>', text)),
                        ottava=len(re.findall(r'<Ottava>', text)),
                        invisible=len(re.findall(r'<Note>\s*<visible>0', text))))
    return out


def mscx_measure_lens(path):
    """[per staff: [length or None per measure]] from MuseScore's <Measure len="...">.

    MuseScore writes len only when the measure it built is not the time-signature length,
    i.e. exactly the measures it displays with "?" (except implicit pickup measures, which
    the caller skips using the XML implicit flag).
    """
    s = open(path, encoding='utf-8').read()
    body = s[s.index('<Staff id="1">', s.index('</Part>', s.rindex('<Part>'))):]
    out = []
    for m in re.finditer(r'<Staff id="(\d+)">(.*?)(?=<Staff id="|\Z)', body, re.S):
        lens = []
        for ms in m.group(2).split('<Measure')[1:]:
            match = re.match(r'[^>]*\blen="([^"]+)"', ms)
            lens.append(F(match.group(1)) if match else None)
        out.append(lens)
    return out


def xml_measure_meta(path):
    """[(number, nominal length in whole notes, implicit, signature)] from the first part."""
    root = ET.parse(path).getroot()
    part = root.find('part')
    if part is None:
        return []
    bar, sig, out = F(1), '4/4', []
    for m in part.findall('measure'):
        t = m.find('attributes/time')
        if t is not None and t.findtext('beats'):
            beats, beat_type = int(t.findtext('beats')), int(t.findtext('beat-type'))
            bar = F(beats, beat_type)
            sig = f'{beats}/{beat_type}'
        out.append((m.get('number'), bar, m.get('implicit') == 'yes', sig))
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
        lens = mscx_measure_lens(mscx)
    xs = xml_staves(a.score)
    meta = xml_measure_meta(a.score)
    bad = 0
    if len(ms) != len(xs):
        print(f'staff count differs: XML {len(xs)}, MuseScore {len(ms)}')
        bad += 1
    if len(lens) != len(ms):
        print(f'measure-length staff count differs: MuseScore staves {len(ms)}, lengths {len(lens)}')
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
    for (label, xm), st, st_lens in zip(xs, ms, lens):
        pid = label.split()[0]
        diffs, cross = [], []
        for (num, p), q in zip(xm, st['measures']):
            if p != q:
                (cross if part_x[(pid, num)] == part_m[(pid, num)] else diffs).append((num, p, q))
        if cross:
            print(f"{label}: cross-staff (same notes, other staff) in "
                  f"{', '.join('m' + c[0] for c in cross)}")
        irregular = []
        for idx, length in enumerate(st_lens if len(xm) == len(st['measures']) else []):
            if length is None or idx >= len(meta):
                continue
            num, nominal, implicit, sig = meta[idx]
            if not implicit and length != nominal:
                irregular.append((num, length, sig))
        if irregular:
            print(f"{label}: irregular measure length "
                  + ', '.join(f'm{num} MuseScore {length} (time signature {sig})'
                              for num, length, sig in irregular))
            bad += len(irregular)
        note = ''
        if len(xm) != len(st['measures']):
            note = f"  measure count XML {len(xm)} / MuseScore {len(st['measures'])}"
            bad += 1
        pitch = [d for d in diffs
                 if len(d[1]) == len(d[2]) and all((a - b) % 12 == 0
                                                   for a, b in zip(d[1], d[2]))]
        notes = [d for d in diffs if d not in pitch]
        print(f"{label}: {len(diffs)} measures differ ({len(pitch)} octave/pitch, "
              f"{len(notes)} note-set/measure-repeat), {st['changes']} instrument changes, "
              f"{st['ottava']} ottava, {st['invisible']} invisible notes{note}")
        for num, p, q in pitch:
            print(f'    m{num} [pitch]: XML {p}  MuseScore {q}')
        for num, p, q in notes:
            print(f'    m{num} [notes]: XML {p}  MuseScore {q}')
        bad += len(diffs)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
