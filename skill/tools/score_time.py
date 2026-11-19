#!/usr/bin/env python3
"""Exact MusicXML time: divisions, backup / forward, chord, grace, direction offset.

Shared by apply_ottava.py (placing hints) and verify_musescore.py (expected display
pitches).  Time is counted in quarter notes as Fraction, so a measure never depends on
XML document order or on float rounding.  A staff defaults to 1, as in MusicXML.
"""
from collections import namedtuple
from fractions import Fraction as F

DEFAULT_BEATS, DEFAULT_BEAT_TYPE = 4, 4

# tag is 'note' or 'direction'; tick is the absolute (whole-score) onset in quarters
Event = namedtuple('Event', 'tag tick duration staff el')
# start / end (exclusive) are absolute ticks; end None = still open at the end
Interval = namedtuple('Interval', 'staff start end shift number')


def measure_divs(part):
    """Divisions per measure, inherited from the previous measure."""
    out, div = [], 1
    for m in part.findall('measure'):
        d = m.findtext('attributes/divisions')
        if d:
            div = int(d)
        out.append(div)
    return out


def bar_length(beats, beat_type):
    return F(beats * 4, beat_type)


def measure_starts(part):
    """Absolute start (quarters, Fraction) of every measure of a part.

    Lengths come from the time signature in force; a missing one keeps the previous
    (4/4 before the first).  A composite '<beats>3+2</beats>' is added up.
    """
    out, start = [], F(0)
    beats, beat_type = DEFAULT_BEATS, DEFAULT_BEAT_TYPE
    for m in part.findall('measure'):
        a = m.find('attributes')
        if a is not None:
            t = a.find('time')
            if t is not None and t.find('beats') is not None:
                beats = sum(int(x) for x in t.findtext('beats').split('+'))
                beat_type = int(t.findtext('beat-type'))
        out.append(start)
        start += bar_length(beats, beat_type)
    return out


def walk(measure, div, start=F(0)):
    """Yield the timed events of one measure, in document order.

    * backup / forward move the cursor (both are in divisions);
    * a chord member takes the onset of the preceding note and does not advance;
    * a grace note has duration 0 and does not advance;
    * a direction sounds at the cursor plus its <offset> (in divisions);
    * the staff defaults to 1.
    """
    cur = start
    last_note = None
    for el in measure:
        if el.tag == 'note':
            dur = F(int(el.findtext('duration') or 0), div)
            grace = el.find('grace') is not None
            chord = el.find('chord') is not None
            if chord and last_note is not None:
                tick = last_note
            else:
                tick = cur
            yield Event('note', tick, F(0) if grace else dur, el.findtext('staff') or '1', el)
            if not chord:
                last_note = tick
                if not grace:
                    cur += dur
        elif el.tag == 'backup':
            cur -= F(int(el.findtext('duration') or 0), div)
            last_note = None
        elif el.tag == 'forward':
            cur += F(int(el.findtext('duration') or 0), div)
            last_note = None
        elif el.tag == 'direction':
            off = el.findtext('offset')
            tick = cur + (F(off) / div if off else 0)
            yield Event('direction', tick, F(0), el.findtext('staff') or '1', el)


def local_cursor(measure, until, div):
    """Cursor position (quarters from the measure start) after processing `until`."""
    cur, last_note = F(0), None
    for el in measure:
        if el.tag == 'note':
            dur = F(int(el.findtext('duration') or 0), div)
            grace = el.find('grace') is not None
            chord = el.find('chord') is not None
            if not chord:
                last_note = cur
                if not grace:
                    cur += dur
            if el is until:
                return cur
        elif el.tag == 'backup':
            cur -= F(int(el.findtext('duration') or 0), div)
            last_note = None
        elif el.tag == 'forward':
            cur += F(int(el.findtext('duration') or 0), div)
            last_note = None
        elif el is until:
            return cur
    return cur


def octave_intervals(part):
    """[(staff, start, end, shift, number)] of the octave shifts of a part.

    shift is in octaves with the sign of the sounding change (type 'down' = +1), the
    same value apply_ottava.py writes; a stop closes the newest still-open interval of
    its (staff, number) at its own tick, so the stop tick is end-exclusive.  A
    'continue' does not change the state.  Unclosed intervals run to the part end.
    """
    divs = measure_divs(part)
    starts = measure_starts(part)
    opened, out = {}, []
    for m, div, st in zip(part.findall('measure'), divs, starts):
        for e in walk(m, div, st):
            if e.tag != 'direction':
                continue
            o = e.el.find('direction-type/octave-shift')
            if o is None:
                continue
            num = o.get('number') or '1'
            size = 2 if o.get('size') == '15' else 1
            typ = o.get('type')
            if typ == 'stop':
                stack = opened.get((e.staff, num))
                if stack:
                    start, shift = stack.pop()
                    out.append(Interval(e.staff, start, e.tick, shift, num))
            elif typ in ('up', 'down'):
                shift = size * (1 if typ == 'down' else -1)
                opened.setdefault((e.staff, num), []).append((e.tick, shift))
    for (staff, num), stack in opened.items():
        for start, shift in stack:
            out.append(Interval(staff, start, None, shift, num))
    return out


def shift_at(intervals, staff, tick):
    """Octave shift that applies to a note onset: newest interval containing it."""
    best = None
    for iv in intervals:
        if iv.staff != staff or tick < iv.start:
            continue
        if iv.end is not None and tick >= iv.end:
            continue
        if best is None or iv.start >= best.start:
            best = iv
    return best.shift if best is not None else 0
