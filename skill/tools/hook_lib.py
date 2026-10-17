#!/usr/bin/env python3
"""Shared helpers for song hooks (songs/<id>/context/fix_<id>.py): rewrite measures as printed.

Import from a song hook:

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'tools'))
    from hook_lib import *  # noqa: E402,F403

What is here:
  load / save            read a merged score, write it back keeping the DOCTYPE
  part_named, meas       find a part by its name, a measure by its number
  divisions              divisions in force at each measure (merged pages keep their own)
  write_measures         replace whole measures with notes written as tokens ("C#5~", "r", "x", "Gn4")
  write_drums            the same for a drum part, strokes as letters (DRUM_SOUNDS)
  beam_marks             beams of eighths and 16ths, as printed (written by the two writers above)
  copy_measures          repeat signs the OMR left as rests: copy earlier measures
  apply_ottava_range     raise staff-1 pitches one octave and add the 8va line
  add_tie, drop_tie, tie_into, set_lyrics

All writers are 4/4 and must stay repeatable: a hook runs again on its own output, so check the
current state first or write the target state whole (write_measures does the latter).
"""

import re
import xml.etree.ElementTree as ET
from fractions import Fraction

NOTE_TYPES = {4: ('whole', 0), 3: ('half', 1), 2: ('half', 0), 1.5: ('quarter', 1), 1: ('quarter', 0),
              .75: ('eighth', 1), .5: ('eighth', 0), .25: ('16th', 0)}
PITCH = re.compile(r'^([A-G])([#bn]?)(\d)(~?)$')

# K bass drum, S snare, C crash (x), O crash (circled cross), H / Ho closed / open hi-hat, M tom:
# (display-step, display-octave, score-instrument name, notehead)
DRUM_SOUNDS = {'K': ('F', '4', 'Bass_Drum_1', None), 'S': ('C', '5', 'Acoustic_Snare', None),
               'C': ('B', '5', 'Crash_Cymbal_2', 'x'), 'O': ('B', '5', 'Crash_Cymbal_1', 'circle-x'),
               'Ho': ('G', '5', 'Open_Hi_Hat', 'x'), 'H': ('G', '5', 'Closed_Hi_Hat', 'x'),
               'M': ('D', '5', 'Low_Mid_Tom', None)}


# ---------------------------------------------------------------- reading and writing

def load(path):
    """(root, text) of a score; pass both to save()."""
    text = open(path, encoding='utf-8').read()
    return ET.fromstring(text.encode('utf-8')), text


def save(root, text, path):
    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    doctype = re.search(r'<!DOCTYPE[^>]*>', text)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + (doctype.group(0) + '\n' if doctype else '') + body + '\n')


# ---------------------------------------------------------------- finding things

def part(root, pid):
    return next(p for p in root.findall('part') if p.get('id') == pid)


def part_named(root, name):
    pid = next(sp.get('id') for sp in root.iter('score-part') if sp.findtext('part-name') == name)
    return part(root, pid)


def meas(p, num):
    return next(m for m in p.findall('measure') if m.get('number') == str(num))


def music_index(m):
    """Index of the first note / backup / forward (or the right barline) of a measure."""
    for k, e in enumerate(m):
        if e.tag in ('note', 'backup', 'forward') or (e.tag == 'barline' and e.get('location', 'right') == 'right'):
            return k
    return len(m)


def end_index(m):
    rb = [k for k, e in enumerate(m) if e.tag == 'barline' and e.get('location', 'right') == 'right']
    return rb[0] if rb else len(m)


def divisions(p):
    """{measure number: divisions in force}: the pages of a merged score keep their own divisions."""
    out, div = {}, 1
    for m in p.findall('measure'):
        div = int(m.findtext('attributes/divisions') or div)
        out[m.get('number')] = div
    return out


# ---------------------------------------------------------------- ties and lyrics

def drop_tie(note, typ):
    for t in list(note.findall('tie')):
        if t.get('type') == typ:
            note.remove(t)
    for nt in list(note.findall('notations')):
        for t in list(nt.findall('tied')):
            if t.get('type') == typ:
                nt.remove(t)
        if len(nt) == 0:
            note.remove(nt)


def add_tie(note, typ):
    """<tie> after <duration>, <tied> in <notations>, which goes before lyric / play / listen."""
    if not any(t.get('type') == typ for t in note.findall('tie')):
        note.insert(list(note).index(note.find('duration')) + 1, ET.Element('tie', type=typ))
    nt = note.find('notations')
    if nt is None:
        nt = ET.Element('notations')
        after = [i for i, c in enumerate(note) if c.tag in ('lyric', 'play', 'listen')]
        note.insert(after[0] if after else len(note), nt)
    if not any(t.get('type') == typ for t in nt.findall('tied')):
        ET.SubElement(nt, 'tied', type=typ)


def tie_into(p, num, staff='1'):
    """Tie the last note of the measure before num to the first note of num when they are the same
    pitch (held notes the OMR read as rests). Both ends are ensured, so it can run again."""
    prev, cur = meas(p, num - 1), meas(p, num)
    a = [n for n in prev.findall('note') if n.find('pitch') is not None and (n.findtext('staff') or '1') == staff]
    b = [n for n in cur.findall('note') if n.find('pitch') is not None and (n.findtext('staff') or '1') == staff]
    if not a or not b:
        return
    a, b = a[-1], b[0]
    if all(a.findtext(f'pitch/{t}') == b.findtext(f'pitch/{t}') for t in ('step', 'alter', 'octave')):
        add_tie(a, 'start')
        add_tie(b, 'stop')


def set_lyrics(note, texts):
    """Lyric k = texts[k-1] (verses 1, 2, ...); a missing lyric is created as 'single'."""
    for k, text in enumerate(texts, 1):
        ly = note.find(f"lyric[@number='{k}']")
        if ly is None:
            ly = ET.SubElement(note, 'lyric', number=str(k))
            ET.SubElement(ly, 'syllabic').text = 'single'
            ET.SubElement(ly, 'text')
        ly.find('text').text = text


# ---------------------------------------------------------------- writing measures

def beam_marks(events):
    """Beam value (begin / continue / end, or None) of each event of a 4/4 voice, as printed:
    eighths beamed by half measure, a group with 16ths by beat; rests and quarters break them."""
    t, keys = 0, []
    for pitches, beats in events:
        short = beats < 1 and pitches not in ('r', 'x')
        keys.append((int(t // 2), int(t)) if short else None)
        t += beats
    runs, cur = [], []
    for i, key in enumerate(keys):
        if cur and (key is None or key[0] != keys[cur[-1]][0]):
            runs.append(cur)
            cur = []
        if key is not None:
            cur.append(i)
    runs.append(cur)
    marks = [None] * len(events)
    for run in runs:
        if any(events[i][1] < .5 for i in run):     # 16ths: by beat
            groups = {}
            for i in run:
                groups.setdefault(keys[i][1], []).append(i)
            run_groups = list(groups.values())
        else:
            run_groups = [run]
        for g in run_groups:
            if len(g) > 1:
                for i in g:
                    marks[i] = 'continue'
                marks[g[0]], marks[g[-1]] = 'begin', 'end'
    return marks


def write_measures(p, table, octave_up=()):
    """Replace the notes of the measures of table ({measure: [(staff, voice, events[, pass])]})
    with the events, (pitches, beats): pitches are tokens separated by spaces (a chord), "C#5~"
    ties to the next same note, "Gn4" has a natural, "r" is a rest, "x" a hidden rest; beats in
    quarters (4 = whole, .5 = eighth). The optional pass is written as time-only. Measures in
    octave_up sound one octave above the tokens (under an 8va line already applied). The
    <instrument> of the old notes is kept. Returns the number of notes written."""
    divs_at = divisions(p)
    pending = set()  # (staff, step, alter, octave) of the ties started
    n = 0
    for num, voices in table.items():
        divs = divs_at[str(num)]
        m = meas(p, num)
        old = [e for e in m if e.tag in ('note', 'backup', 'forward')]
        instrument = next((e.find('instrument') for e in old if e.find('instrument') is not None), None)
        k = music_index(m)
        for e in old:
            m.remove(e)
        new = []
        for i, (staff, voice, events, *only) in enumerate(voices):
            if i:
                b = ET.Element('backup')
                ET.SubElement(b, 'duration').text = str(4 * divs)
                new.append(b)
            beams = beam_marks(events)
            for e_idx, (pitches, beats) in enumerate(events):
                kind, dots = NOTE_TYPES[beats]
                for j, token in enumerate(pitches.split()):
                    note = ET.Element('note')
                    if only:
                        note.set('time-only', only[0])
                    if j:
                        ET.SubElement(note, 'chord')
                    tie_stop = tie_start = False
                    if token in ('r', 'x'):
                        ET.SubElement(note, 'rest')
                        if token == 'x':
                            note.set('print-object', 'no')
                    else:
                        step, acc, octave, tie = PITCH.match(token).groups()
                        alter = {'#': '1', 'b': '-1'}.get(acc)
                        pitch = ET.SubElement(note, 'pitch')
                        ET.SubElement(pitch, 'step').text = step
                        if alter:
                            ET.SubElement(pitch, 'alter').text = alter
                        ET.SubElement(pitch, 'octave').text = str(int(octave) + (num in octave_up))
                        key = (staff, step, alter, octave)
                        tie_stop = key in pending
                        pending.discard(key)
                        tie_start = tie == '~'
                        if tie_start:
                            pending.add(key)
                    ET.SubElement(note, 'duration').text = str(int(beats * divs))
                    for kind_ in ('stop', 'start'):
                        if (tie_stop, tie_start)[kind_ == 'start']:
                            ET.SubElement(note, 'tie', type=kind_)
                    if instrument is not None:
                        note.append(ET.fromstring(ET.tostring(instrument)))
                    ET.SubElement(note, 'voice').text = str(voice)
                    ET.SubElement(note, 'type').text = kind
                    for _ in range(dots):
                        ET.SubElement(note, 'dot')
                    ET.SubElement(note, 'staff').text = str(staff)
                    if not j and beams[e_idx]:
                        ET.SubElement(note, 'beam', number='1').text = beams[e_idx]
                    if tie_stop or tie_start:
                        nots = ET.SubElement(note, 'notations')
                        for kind_ in ('stop', 'start'):
                            if (tie_stop, tie_start)[kind_ == 'start']:
                                ET.SubElement(nots, 'tied', type=kind_)
                    new.append(note)
                    n += token not in ('r', 'x')
            assert sum(b for _, b in events) == 4, (num, staff, voice)
        for j, e in enumerate(new):
            m.insert(k + j, e)
    assert not pending, pending
    return n


def write_drums(root, p, table, sounds=DRUM_SOUNDS):
    """Replace the notes of the drum measures of table ({measure: [(voice, events)]}), events
    (strokes, beats): strokes are letters of sounds separated by spaces, "r" a rest; suffix "/" a
    roll, "~" a tie to the next stroke, prefix "-" the end of a tie (not struck again). Voice 1
    stems up, the others down. Returns the number of strokes written."""
    sp = next(s for s in root.iter('score-part') if s.get('id') == p.get('id'))
    ids = {s.findtext('instrument-name'): s.get('id') for s in sp.findall('score-instrument')}
    divs_at = divisions(p)
    n = 0
    for num, voices in table.items():
        divs = divs_at[str(num)]
        m = meas(p, num)
        for e in [e for e in m if e.tag in ('note', 'backup', 'forward')]:
            m.remove(e)
        k = music_index(m)
        new = []
        for i, (voice, events) in enumerate(voices):
            if i:
                b = ET.Element('backup')
                ET.SubElement(b, 'duration').text = str(4 * divs)
                new.append(b)
            beams = beam_marks(events)
            for e_idx, (strokes, beats) in enumerate(events):
                kind, dots = NOTE_TYPES[beats]
                for j, token in enumerate(strokes.split()):
                    note = ET.Element('note')
                    if j:
                        ET.SubElement(note, 'chord')
                    roll = token.endswith('/')
                    tie_start, tie_stop = token.endswith('~'), token.startswith('-')
                    token = token.strip('/~-')
                    if token == 'r':
                        ET.SubElement(note, 'rest')
                    else:
                        step, octave, inst, head = sounds[token]
                        u = ET.SubElement(note, 'unpitched')
                        ET.SubElement(u, 'display-step').text = step
                        ET.SubElement(u, 'display-octave').text = octave
                    ET.SubElement(note, 'duration').text = str(int(beats * divs))
                    for t, on in (('stop', tie_stop), ('start', tie_start)):
                        if on:
                            ET.SubElement(note, 'tie', type=t)
                    if token != 'r':
                        ET.SubElement(note, 'instrument', id=ids[inst])
                    ET.SubElement(note, 'voice').text = str(voice)
                    ET.SubElement(note, 'type').text = kind
                    for _ in range(dots):
                        ET.SubElement(note, 'dot')
                    if token != 'r':
                        ET.SubElement(note, 'stem').text = 'up' if voice == 1 else 'down'
                        if head:
                            ET.SubElement(note, 'notehead').text = head
                        if not j and beams[e_idx]:
                            ET.SubElement(note, 'beam', number='1').text = beams[e_idx]
                        nots = None
                        for t, on in (('stop', tie_stop), ('start', tie_start)):
                            if on:
                                nots = nots if nots is not None else ET.SubElement(note, 'notations')
                                ET.SubElement(nots, 'tied', type=t)
                        if roll:
                            nots = nots if nots is not None else ET.SubElement(note, 'notations')
                            ET.SubElement(ET.SubElement(nots, 'ornaments'), 'tremolo', type='single').text = '3'
                        n += 1
                    new.append(note)
            assert sum(b for _, b in events) == 4, (num, voice)
        for j, e in enumerate(new):
            m.insert(k + j, e)
    return n


def copy_measures(p, src, dst, drop_tie_stops=False):
    """Copy the notes of measures src (numbers) into dst, durations scaled to the divisions there
    (repeat signs the OMR left as rests). Does nothing when a dst measure already has a pitch or
    an unpitched note, so it can run again. drop_tie_stops: a tie into the first copied measure
    does not repeat. Returns True when copied."""
    divs_at = divisions(p)
    if any(n.find('pitch') is not None or n.find('unpitched') is not None
           for d in dst for n in meas(p, d).findall('note')):
        return False
    for s, d in zip(src, dst):
        sm, dm = meas(p, s), meas(p, d)
        f = Fraction(divs_at[str(d)], divs_at[str(s)])
        k = music_index(dm)
        for e in [e for e in dm if e.tag in ('note', 'backup', 'forward')]:
            dm.remove(e)
        for j, e in enumerate([e for e in sm if e.tag in ('note', 'backup', 'forward')]):
            c = ET.fromstring(ET.tostring(e))
            c.find('duration').text = str(int(int(c.findtext('duration')) * f))
            if e.tag == 'note' and drop_tie_stops:
                drop_tie(c, 'stop')
            dm.insert(k + j, c)
    return True


# ---------------------------------------------------------------- 8va

def octave_shift(kind, staff='1', number='3'):
    d = ET.Element('direction', placement='above')
    ET.SubElement(ET.SubElement(d, 'direction-type'), 'octave-shift', type=kind, size='8', number=number)
    ET.SubElement(d, 'staff').text = staff
    return d


def apply_ottava_range(p, a, b, staff='1'):
    """8va over measures a..b of a staff the OMR missed: raise its pitches one octave and add the
    line. Does nothing when measure a already starts one (returns False)."""
    first = meas(p, a)
    if any(o.get('type') == 'down' for o in first.iter('octave-shift')):
        return False
    for num in range(a, b + 1):
        for n in meas(p, num).findall('note'):
            if n.find('pitch') is not None and (n.findtext('staff') or '1') == staff:
                o = n.find('pitch/octave')
                o.text = str(int(o.text) + 1)
    first.insert(music_index(first), octave_shift('down', staff))
    last = meas(p, b)
    last.insert(end_index(last), octave_shift('stop', staff))
    return True


def ottava_measures(p, ranges):
    """Measures of p inside 8va ranges [(a, b)] already applied, for write_measures(octave_up=...)."""
    return {num for a, b in ranges if any(o.get('type') == 'down' for o in meas(p, a).iter('octave-shift'))
            for num in range(a, b + 1)}
