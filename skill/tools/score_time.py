#!/usr/bin/env python3
"""Exact MusicXML time: divisions, backup / forward, chord, grace, direction offset.

Shared by apply_ottava.py (placing hints) and verify_musescore.py (expected display
pitches).  Time is counted in quarter notes as Fraction, so a measure never depends on
XML document order or on float rounding.  A staff defaults to 1, as in MusicXML.
"""
from collections import namedtuple
from fractions import Fraction as F
import xml.etree.ElementTree as ET

DEFAULT_BEATS, DEFAULT_BEAT_TYPE = 4, 4

# tag is 'note' or 'direction'; tick is the absolute (whole-score) onset in quarters
Event = namedtuple('Event', 'tag tick duration staff el')
# start / end (exclusive) are absolute ticks; end None = still open at the end
Interval = namedtuple('Interval', 'staff start end shift number')
OctaveSpan = namedtuple(
    'OctaveSpan',
    'staff start end shift number start_measure end_measure start_el stop_el continues complete',
)
OctaveAnalysis = namedtuple(
    'OctaveAnalysis',
    'intervals duplicate_starts orphan_stops unclosed_starts overlaps continues',
)


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


def _ranges_overlap(a_start, a_end, b_start, b_end):
    return (a_end is None or b_start < a_end) and (b_end is None or a_start < b_end)


def analyze_octave_shifts(part):
    """Parse native/tool octave-shifts by (staff, number) in exact chronological order.

    Returns OctaveAnalysis(intervals, duplicate_starts, orphan_stops, unclosed_starts,
    overlaps, continues).
    """
    divs = measure_divs(part)
    starts = measure_starts(part)
    events = []
    doc_idx = 0
    for m, div, st in zip(part.findall('measure'), divs, starts):
        m_num = m.get('number') or '?'
        for e in walk(m, div, st):
            if e.tag != 'direction':
                continue
            for o in e.el.iter('octave-shift'):
                events.append((e.tick, doc_idx, m_num, e.staff, o))
                doc_idx += 1
    events.sort(key=lambda item: (item[0], item[1]))

    opened = {}
    intervals = []
    duplicate_starts = []
    orphan_stops = []
    unclosed_starts = []
    continues = []

    for tick, _, m_num, staff, o in events:
        num = o.get('number') or '1'
        size = 2 if o.get('size') == '15' else 1
        typ = o.get('type')
        key = (staff, num)
        if typ in ('up', 'down'):
            shift = size * (1 if typ == 'down' else -1)
            had_dup = False
            if key in opened:
                prev = opened.pop(key)
                had_dup = True
                duplicate_starts.append({
                    'staff': staff, 'number': num, 'measure': m_num, 'tick': tick,
                    'prev_measure': prev['measure'], 'prev_tick': prev['start'], 'el': o,
                })
                intervals.append(OctaveSpan(
                    staff, prev['start'], None, prev['shift'], num,
                    prev['measure'], None, prev['el'], None, prev['continues'], False,
                ))
            opened[key] = {
                'start': tick, 'shift': shift, 'measure': m_num,
                'el': o, 'continues': [], 'dup': had_dup,
            }
        elif typ == 'stop':
            if key in opened:
                st_info = opened.pop(key)
                intervals.append(OctaveSpan(
                    staff, st_info['start'], tick, st_info['shift'], num,
                    st_info['measure'], m_num, st_info['el'], o,
                    st_info['continues'], not st_info['dup'],
                ))
            else:
                orphan_stops.append({
                    'staff': staff, 'number': num, 'measure': m_num, 'tick': tick, 'el': o,
                })
        elif typ == 'continue':
            active = key in opened
            continues.append({
                'staff': staff, 'number': num, 'measure': m_num, 'tick': tick,
                'active': active, 'el': o,
            })
            if active:
                opened[key]['continues'].append((tick, m_num, o))

    for (staff, num), st_info in opened.items():
        unclosed_starts.append({
            'staff': staff, 'number': num, 'measure': st_info['measure'],
            'tick': st_info['start'], 'el': st_info['el'],
        })
        intervals.append(OctaveSpan(
            staff, st_info['start'], None, st_info['shift'], num,
            st_info['measure'], None, st_info['el'], None, st_info['continues'], False,
        ))

    overlaps = []
    for i, a in enumerate(intervals):
        for b in intervals[i + 1:]:
            if a.staff == b.staff and _ranges_overlap(a.start, a.end, b.start, b.end):
                overlaps.append((a, b))

    return OctaveAnalysis(
        intervals=intervals,
        duplicate_starts=duplicate_starts,
        orphan_stops=orphan_stops,
        unclosed_starts=unclosed_starts,
        overlaps=overlaps,
        continues=continues,
    )


def _remove_octave_shift_el(part, o):
    for m in part.findall('measure'):
        for d in list(m.findall('direction')):
            for dt in list(d.findall('direction-type')):
                if o in list(dt):
                    dt.remove(o)
                    if len(dt) == 0:
                        d.remove(dt)
                    if not d.findall('direction-type'):
                        m.remove(d)
                    return


def _insert_octave_shift_at(part, staff, tick, typ, size, number):
    measures = part.findall('measure')
    if not measures:
        return
    divs = measure_divs(part)
    starts = measure_starts(part)
    target_i = len(measures) - 1
    for i in range(len(measures) - 1):
        if starts[i] <= tick < starts[i + 1]:
            target_i = i
            break
    m = measures[target_i]
    div = divs[target_i]
    rel = tick - starts[target_i]

    cur = F(0)
    idx = len(m)
    cur_at_idx = None
    for pos, el in enumerate(list(m)):
        if el.tag in ('print', 'attributes', 'barline') and rel == 0:
            continue
        if cur_at_idx is None:
            if rel == 0:
                idx, cur_at_idx = pos, cur
                break
            if el.tag == 'note' and cur >= rel:
                idx, cur_at_idx = pos, cur
                break
        if el.tag == 'note':
            dur = F(int(el.findtext('duration') or 0), div)
            grace = el.find('grace') is not None
            chord = el.find('chord') is not None
            if not chord and not grace:
                cur += dur
        elif el.tag == 'backup':
            cur -= F(int(el.findtext('duration') or 0), div)
        elif el.tag == 'forward':
            cur += F(int(el.findtext('duration') or 0), div)
        if cur_at_idx is None and cur >= rel and typ == 'stop':
            idx, cur_at_idx = pos + 1, cur
            break
    if cur_at_idx is None:
        cur_at_idx = cur

    d = ET.Element('direction', placement='above')
    dt = ET.SubElement(d, 'direction-type')
    ET.SubElement(dt, 'octave-shift', type=typ, size=str(size), number=str(number))
    offset = (rel - cur_at_idx) * div
    if offset:
        ET.SubElement(d, 'offset').text = str(int(offset))
    ET.SubElement(d, 'staff').text = str(staff)
    m.insert(idx, d)


def restore_native_octave_shifts(part, staff, hint_start, hint_end, exclude_numbers=(), check_only=False):
    """Safely undo confirmed complete native octave-shifts inside [hint_start, hint_end).

    Returns (ok, stop_reason, messages). If any incomplete, orphan, or overlapping
    native octave-shift intersects [hint_start, hint_end) on `staff`, returns
    (False, reason, []) without modifying pitches or XML.
    """
    exclude = set(exclude_numbers)
    analysis = analyze_octave_shifts(part)
    native_ivs = [iv for iv in analysis.intervals if iv.staff == staff and iv.number not in exclude]

    for iv in native_ivs:
        if not iv.complete and _ranges_overlap(iv.start, iv.end, hint_start, hint_end):
            return (
                False,
                f"incomplete native octave-shift #{iv.number} on staff {staff} (m{iv.start_measure})",
                [],
            )
    for ev in analysis.orphan_stops:
        if ev['staff'] == staff and ev['number'] not in exclude and ev['tick'] > hint_start:
            return (
                False,
                f"orphan stop octave-shift #{ev['number']} on staff {staff} at m{ev['measure']}",
                [],
            )
    for ev in analysis.continues:
        if (ev['staff'] == staff and ev['number'] not in exclude
                and not ev['active'] and ev['tick'] > hint_start):
            return (
                False,
                f"orphan continue octave-shift #{ev['number']} on staff {staff} at m{ev['measure']}",
                [],
            )
    for a, b in analysis.overlaps:
        if (a.staff == staff and a.number not in exclude and b.number not in exclude
                and _ranges_overlap(a.start, a.end, hint_start, hint_end)
                and _ranges_overlap(b.start, b.end, hint_start, hint_end)):
            return (
                False,
                f"overlapping native octave-shifts #{a.number} and #{b.number} on staff {staff}",
                [],
            )

    overlapping = [iv for iv in native_ivs if _ranges_overlap(iv.start, iv.end, hint_start, hint_end)]
    if not overlapping or check_only:
        return True, None, []

    divs = measure_divs(part)
    starts = measure_starts(part)
    measures = part.findall('measure')
    messages = []

    for iv in overlapping:
        inter_start = max(iv.start, hint_start)
        inter_end = min(iv.end, hint_end)
        restored_notes = 0
        for m, div, st in zip(measures, divs, starts):
            for e in walk(m, div, st):
                if e.tag != 'note' or e.staff != staff or e.el.find('pitch') is None:
                    continue
                if inter_start <= e.tick < inter_end:
                    o = e.el.find('pitch/octave')
                    if o is not None:
                        o.text = str(int(o.text) - iv.shift)
                        restored_notes += 1

        _remove_octave_shift_el(part, iv.start_el)
        if iv.stop_el is not None:
            _remove_octave_shift_el(part, iv.stop_el)
        for _, _, c_el in iv.continues:
            _remove_octave_shift_el(part, c_el)

        typ = 'down' if iv.shift > 0 else 'up'
        size = 15 if abs(iv.shift) == 2 else 8
        if iv.start < inter_start:
            _insert_octave_shift_at(part, staff, iv.start, typ, size, iv.number)
            _insert_octave_shift_at(part, staff, inter_start, 'stop', size, iv.number)
        if inter_end < iv.end:
            _insert_octave_shift_at(part, staff, inter_end, typ, size, iv.number)
            _insert_octave_shift_at(part, staff, iv.end, 'stop', size, iv.number)

        messages.append(
            f"staff {staff} native #{iv.number} ({size}va) restored {restored_notes} notes "
            f"in [{inter_start}, {inter_end})"
        )

    return True, None, messages
