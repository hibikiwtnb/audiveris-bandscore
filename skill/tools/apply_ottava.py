#!/usr/bin/env python3
"""Apply printed 8va / 15ma / coll'8va markings (read by hand) to a merged score.

    python3 tools/apply_ottava.py <score.musicxml> <song dir>/context/ottava.txt \\
        [<song dir>/context/measure_map.tsv] [--raw]

Run on a freshly merged score (tools/bandscore_postprocess.py does); it refuses to run twice.
Each hint line gives part, staff, kind and a start / end position (measure + beat, "#k" = k-th
onset of that staff in the measure, or "end").  Measures are final merged numbers; with
`--raw` the hint numbers are source (Audiveris) numbers and are converted through the map.
A map names deleted / missing / ambiguous measures explicitly instead of guessing.

The notes of that staff in the range get:

  * 8va / 15ma: pitch raised by 1 / 2 octaves and an <octave-shift type="down"> line around
    them. MusicXML <pitch> is the sounding pitch and the line displays it lower, so the page
    still shows the printed notes while playback is an octave higher;
  * coll8va: an invisible (print-object="no") copy one octave higher on every note (chord
    member), i.e. the octave doubling is heard but the page is unchanged, plus a "coll'8va" word.

The stop sits at the end-exclusive tick of the last covered note (its onset + duration),
measured with tools/score_time.py, so its position no longer depends on which voice's note
happens to be last in document order; an <offset> corrects the direction when needed.

OCR copies of these markings left as <words> in the listed parts ("8va", "18va", "coll'8va"...)
are removed. The score's measure lengths should be equal across parts (bandscore_postprocess
pads them): MuseScore times octave-shifts with per-part cumulative time.
"""
import copy
import re
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction as F

import measure_map
import score_time

NUMBER = {'1': '3', '2': '4'}   # octave-shift number per staff (2 is used by instrument changes)
WORDS_RE = re.compile(r"8va|15ma|coll", re.I)
NOTE_ORDER = ['grace', 'cue', 'chord', 'pitch', 'unpitched', 'rest', 'duration', 'tie',
              'instrument', 'voice', 'type', 'dot', 'accidental', 'time-modification', 'stem',
              'notehead', 'notehead-text', 'staff', 'beam', 'notations', 'lyric', 'play']
DIRECTION_ORDER = ['direction-type', 'offset', 'footnote', 'level', 'voice', 'staff', 'sound']


def insert_ordered(note, el):
    rank = NOTE_ORDER.index(el.tag)
    for i, c in enumerate(list(note)):
        if c.tag in NOTE_ORDER and NOTE_ORDER.index(c.tag) > rank:
            note.insert(i, el)
            return
    note.append(el)


def read_hints(path):
    out = []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        f = line.split('\t')
        out.append(dict(part=f[0], staff=f[1], kind=f[2], m1=f[3], p1=f[4], m2=f[5], p2=f[6]))
    return out


def groups(m, div):
    """Chord groups of a measure: (onset in quarters, [note elements], staff), document order."""
    out = []
    for e in score_time.walk(m, div):
        if e.tag != 'note':
            continue
        if e.el.find('chord') is not None and out:
            out[-1][1].append(e.el)
        else:
            out.append((e.tick, [e.el], e.staff))
    return out


def pitched(g):
    return [n for n in g[1] if n.find('pitch') is not None]


def describe(h):
    return f"{h['part']} staff {h['staff']} {h['kind']} m{h['m1']} {h['p1']}-m{h['m2']} {h['p2']}"


def resolve(pos, gs, staff):
    """Onset bound (quarters) for a position in one measure."""
    if pos == 'end':
        return None
    onsets = sorted({t for t, ns, st in gs if st == staff and any(n.find('pitch') is not None
                                                                  for n in ns)})
    if pos.startswith('#'):
        k = int(pos[1:])
        if not 1 <= k <= len(onsets):
            raise ValueError(f'position #{k} out of range: staff {staff} has {len(onsets)} onset(s)')
        return onsets[k - 1]
    return F(pos) - 1


def shift(n, octaves):
    o = n.find('pitch/octave')
    o.text = str(int(o.text) + octaves)


def insert_direction(measure, index, staff, child, offset=None):
    """Insert a <direction> at `index`, with an optional <offset> in divisions."""
    d = ET.Element('direction', placement='above')
    dt = ET.SubElement(d, 'direction-type')
    dt.append(child)
    if offset:
        ET.SubElement(d, 'offset').text = str(int(offset))
    ET.SubElement(d, 'staff').text = staff
    measure.insert(index, d)


def main(score, hints, map_path=None, raw_map=False):
    tree = ET.parse(score)
    root = tree.getroot()
    if any(o.get('number') in NUMBER.values() for o in root.iter('octave-shift')):
        sys.exit('ottava lines already applied')
    abbr = {sp.findtext('part-abbreviation'): sp.get('id') for sp in root.iter('score-part')}
    parts = {p.get('id'): p for p in root.findall('part')}
    hs = read_hints(hints)
    rows = measure_map.read_map(map_path) if map_path else None

    # resolve every hint coordinate before touching the score, so a deleted / missing /
    # ambiguous measure stops the run instead of silently skipping the hint
    for h in hs:
        if rows is None:
            continue
        try:
            h['m1'] = measure_map.resolve_measure(h['m1'], rows, raw_map)
            h['m2'] = measure_map.resolve_measure(h['m2'], rows, raw_map)
        except ValueError as e:
            sys.exit(f'ottava hint {describe(h)}: {e}')

    # divisions per measure, per part
    divs = {}
    for pid, part in parts.items():
        div = 1
        for m in part.findall('measure'):
            if m.findtext('attributes/divisions'):
                div = int(m.findtext('attributes/divisions'))
            divs[(pid, m.get('number'))] = div

    removed = 0
    for pid in {abbr[h['part']] for h in hs}:
        for m in parts[pid].findall('measure'):
            for d in m.findall('direction'):
                ws = [w.text or '' for w in d.iter('words')]
                if ws and all(WORDS_RE.search(w) for w in ws):
                    m.remove(d)
                    removed += 1

    for h in hs:
        pid = abbr[h['part']]
        measures = parts[pid].findall('measure')
        nums = [m.get('number') for m in measures]
        if h['m1'] not in nums or h['m2'] not in nums:
            print(f"   skipped out-of-range hint ({describe(h)}): measure not found")
            continue
        i1, i2 = nums.index(h['m1']), nums.index(h['m2'])
        starts = score_time.measure_starts(parts[pid])
        covered = []    # (measure index, group)
        try:
            for i in range(i1, i2 + 1):
                m = measures[i]
                gs = groups(m, divs[(pid, m.get('number'))])
                lo = resolve(h['p1'], gs, h['staff']) if i == i1 else None
                hi = resolve(h['p2'], gs, h['staff']) if i == i2 else None
                for g in gs:
                    if g[2] != h['staff'] or not pitched(g):
                        continue
                    if (lo is not None and g[0] < lo) or (hi is not None and g[0] > hi):
                        continue
                    covered.append((i, g))
        except ValueError as e:
            print(f"   skipped out-of-range hint ({describe(h)}): {e}")
            continue
        if not covered:
            print(f'   {h}: no notes')
            continue
        first_i, first_g = covered[0]
        first_m = measures[first_i]
        n_notes = sum(len(pitched(g)) for _, g in covered)
        if h['kind'] in ('8va', '15ma'):
            octv, size = (1, '8') if h['kind'] == '8va' else (2, '15')
            for _, g in covered:
                for n in pitched(g):
                    shift(n, octv)
            num = NUMBER[h['staff']]
            insert_direction(first_m, list(first_m).index(first_g[1][0]), h['staff'],
                             ET.Element('octave-shift', type='down', size=size, number=num))
            # end-exclusive tick of the last covered note (onset + its own duration), measured
            # per staff, not by whichever voice's group is last in the XML
            end_idx, end_tick = max(
                ((k, starts[i] + g[0] + max(F(int(n.findtext('duration') or 0),
                                               divs[(pid, measures[i].get('number'))])
                                             for n in g[1]))
                 for k, (i, g) in enumerate(covered)),
                key=lambda item: (item[1], item[0]))
            last_i, last_g = covered[end_idx]
            last_m = measures[last_i]
            div = divs[(pid, last_m.get('number'))]
            offset = (end_tick - starts[last_i]) - score_time.local_cursor(last_m, last_g[1][-1], div)
            insert_direction(last_m, list(last_m).index(last_g[1][-1]) + 1, h['staff'],
                             ET.Element('octave-shift', type='stop', size=size, number=num),
                             offset=offset * div)
        elif h['kind'] == 'coll8va':
            w = ET.Element('words')
            w.text = "coll'8va"
            insert_direction(first_m, list(first_m).index(first_g[1][0]), h['staff'], w)
            for k, (m, g) in enumerate(covered):
                have = {(n.findtext('pitch/step'), n.findtext('pitch/alter'),
                         n.findtext('pitch/octave')) for n in pitched(g)}
                idx = list(m).index(g[1][-1]) + 1
                for n in pitched(g):
                    c = copy.deepcopy(n)
                    shift(c, 1)
                    key = (c.findtext('pitch/step'), c.findtext('pitch/alter'),
                           c.findtext('pitch/octave'))
                    if key in have:
                        continue
                    have.add(key)
                    for tag in ('beam', 'lyric', 'accidental', 'stem', 'notations'):
                        for e in c.findall(tag):
                            c.remove(e)
                    # ties only inside the range (playback only: invisible doubling notes must not draw visible <tied> arcs)
                    for e in c.findall('tie'):
                        if (e.get('type') == 'stop' and k == 0) or \
                                (e.get('type') == 'start' and k == len(covered) - 1):
                            c.remove(e)
                    if c.find('chord') is None:
                        insert_ordered(c, ET.Element('chord'))
                    for a in ('default-x', 'default-y'):
                        c.attrib.pop(a, None)
                    c.set('print-object', 'no')
                    m.insert(idx, c)
                    idx += 1
        print(f"   {h['part']} staff {h['staff']} {h['kind']} m{h['m1']}-m{h['m2']}: {n_notes} notes")

    tree.write(score, encoding='UTF-8', xml_declaration=True)
    print(f'ottava: {len(hs)} hints, {removed} OCR words removed')


if __name__ == '__main__':
    argv = sys.argv[1:]
    args = [a for a in argv if a != '--raw']
    main(args[0], args[1], args[2] if len(args) > 2 else None, '--raw' in argv)
