#!/usr/bin/env python3
"""Light post-processing of patched-Audiveris output (raw/) into a preview score.

    python3 tools/bandscore_postprocess.py "<song dir>"

Reads <song dir>/raw/*.mxl (+ .omr), writes
<song dir>/pages/*.musicxml and <song dir>/<id>_<title>[_Keyboard].musicxml (for review).

Page-level fixes (a measure never gets longer than its time signature, except a pickup):

  * rehearsal marks exported as page credits (text read through the frame, the frame then
    being unavailable for the rehearsal detection) are moved back as boxed <rehearsal>
    directions, at the first measure of their system;
  * empty measures get a measure rest (an empty measure freezes MuseScore playback);
  * dots that make a voice over-full are dropped: first all its dots, then they are given back
    from left to right as long as the voice does not get over-full again (a short voice is
    padded below);
  * over-full voices are trimmed at the barline (one misread voice must not lengthen the
    measure of all parts): a bogus leading gap (<forward>, no printed rest) or a bogus rest
    before a tie continuation is removed, otherwise the element crossing the barline is
    shortened and everything starting beyond it (notes too) is dropped;
  * under-full voices are padded with rests up to the measure length of the time signature,
    also when the whole measure is short (a short measure would shift all following
    downbeats; otherwise the barline of that staff is drawn inside the measure); a last note
    tied over the barline is extended instead, so that its tie stays valid; the padding rests
    are hidden where another voice of the staff sounds (one line split into two voices: a
    printed rest there is not in the score);
  * lyrics of instrumental parts (misread staff text; open syllables draw hyphen dashes
    across systems) become below-staff words, OCR fragments (va, **, b) are dropped;
  * source paths (which may contain the user name) are reduced to file names;
  * narrow page-final measures (a trailing courtesy key signature read as a measure) are
    reported as candidates; only those listed with printed-page evidence in
    <song dir>/context/page_edge_prune.txt are removed.

Score-level fixes after merge: tools/fill_measure_repeats.py (measure repeats at the top of a
page get the notes of the last measure of the previous page), a 1st ending split over a page
break is joined back into one span (start on the first page, stop at the backward repeat),
tools/fill_slash_chords.py (each
slash gets the pitches of the chord before it), tools/clean_score_noise.py (drops slurs, completes chord ties,
prunes invalid ties, ...), then tools/apply_instrument_changes.py when
<song dir>/context/instrument_changes.txt exists (printed timbre changes -> real instrument changes),
and tools/apply_ottava.py when <song dir>/context/ottava.txt exists (8va / 15ma / coll'8va);
tools/apply_capo.py writes <transpose> on the parts flagged ":capoN" in audiveris_hints.txt;
tools/unify_keys.py makes key changes score-wide (a part whose key differs from the others is an
OMR mistake); finally tools/apply_tab_octave.py adds the octave that guitar and bass-guitar
notation sounds below its written pitch.
"""
import copy
import glob
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F

import measure_map

HERE = os.path.dirname(os.path.abspath(__file__))

REHEARSAL_RE = re.compile(r"^[A-H][0-9]?'?$")

# Note values in quarters -> (type, dots), longest first
VALUES = [(F(4), 'whole', 0), (F(7, 2), 'half', 2), (F(3), 'half', 1), (F(2), 'half', 0),
          (F(7, 4), 'quarter', 2), (F(3, 2), 'quarter', 1), (F(1), 'quarter', 0),
          (F(3, 4), 'eighth', 1), (F(1, 2), 'eighth', 0), (F(3, 8), '16th', 1),
          (F(1, 4), '16th', 0), (F(3, 16), '32nd', 1), (F(1, 8), '32nd', 0),
          (F(3, 32), '64th', 1), (F(1, 16), '64th', 0)]

# MusicXML <note> children order (subset relevant here)
NOTE_ORDER = ['grace', 'cue', 'chord', 'pitch', 'unpitched', 'rest', 'duration', 'tie',
              'instrument', 'voice', 'type', 'dot', 'accidental', 'time-modification', 'stem',
              'notehead', 'notehead-text', 'staff', 'beam', 'notations', 'lyric', 'play']


# --------------------------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------------------------- #
def read_mxl(path):
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.endswith('.xml') and not n.startswith('META')][0]
    return ET.fromstring(z.read(name))


def sgn(x):
    """Format a Fraction with an explicit sign (the :+ spec needs Python 3.12)."""
    return f'+{x}' if x >= 0 else str(x)


def decompose(q):
    """Split a duration in quarters into standard note values (longest first)."""
    out = []
    for v, t, d in VALUES:
        while q >= v:
            out.append((v, t, d))
            q -= v
    return out if q == 0 else None


def insert_ordered(note, el):
    """Insert child el into note, respecting MusicXML child order."""
    rank = NOTE_ORDER.index(el.tag) if el.tag in NOTE_ORDER else len(NOTE_ORDER)
    for i, c in enumerate(list(note)):
        if c.tag in NOTE_ORDER and NOTE_ORDER.index(c.tag) > rank:
            note.insert(i, el)
            return
    note.append(el)


def set_value(note, q, div):
    """Set duration / type / dots of a note for q quarters (q must be a single value)."""
    note.find('duration').text = str(int(q * div))
    for tag in ('type', 'dot'):
        for e in note.findall(tag):
            note.remove(e)
    match = [(t, d) for v, t, d in VALUES if v == q]
    if match:
        t, d = match[0]
        te = ET.Element('type')
        te.text = t
        insert_ordered(note, te)
        for _ in range(d):
            insert_ordered(note, ET.Element('dot'))


def make_rest(q, div, voice, staff):
    n = ET.Element('note')
    ET.SubElement(n, 'rest')
    ET.SubElement(n, 'duration').text = str(int(q * div))
    ET.SubElement(n, 'voice').text = voice
    match = [(t, d) for v, t, d in VALUES if v == q]
    if match:
        ET.SubElement(n, 'type').text = match[0][0]
        for _ in range(match[0][1]):
            ET.SubElement(n, 'dot')
    if staff:
        ET.SubElement(n, 'staff').text = staff
    return n


def rests_for(q, div, voice, staff):
    parts = decompose(q)
    if parts is None:  # odd value: single rest with exact duration, no type
        return [make_rest(q, div, voice, staff)]
    return [make_rest(v, div, voice, staff) for v, _, _ in parts]


def has_tie(note, kind):
    return any(t.get('type') == kind for t in note.findall('tie'))


# --------------------------------------------------------------------------------------------- #
# Measure analysis
# --------------------------------------------------------------------------------------------- #
class Event:
    def __init__(self, el, start, dur, members):
        self.el, self.start, self.dur, self.members = el, start, dur, members

    @property
    def end(self):
        return self.start + self.dur

    @property
    def is_rest(self):
        return self.el.find('rest') is not None


def voices_of(measure, div):
    """Map voice -> list of Events (chord members grouped), in document order."""
    t = F(0)
    voices = {}
    last = None
    for el in list(measure):
        if el.tag == 'note':
            if el.find('grace') is not None:
                continue
            dur = F(int(el.findtext('duration') or 0), div)
            if el.find('chord') is not None and last is not None:
                last.members.append(el)
                continue
            ev = Event(el, t, dur, [el])
            voices.setdefault(el.findtext('voice', '1'), []).append(ev)
            last = ev
            t += dur
        elif el.tag == 'backup':
            t -= F(int(el.findtext('duration')), div)
        elif el.tag == 'forward':
            t += F(int(el.findtext('duration')), div)
    return voices


def fix_backups(measure, old_cursor_targets):
    """Recompute <backup> durations so that each one rewinds to its original target."""
    div = old_cursor_targets['div']
    t = F(0)
    k = 0
    for el in list(measure):
        if el.tag == 'note' and el.find('grace') is None and el.find('chord') is None:
            t += F(int(el.findtext('duration') or 0), div)
        elif el.tag == 'forward':
            t += F(int(el.findtext('duration')), div)
        elif el.tag == 'backup' and el.get('new'):
            # inserted by keep_cursor: not one of the original backups
            t -= F(int(el.findtext('duration')), div)
            del el.attrib['new']
        elif el.tag == 'backup':
            target = old_cursor_targets['targets'][k]
            k += 1
            amount = t - target
            if amount <= 0:
                measure.remove(el)
            else:
                el.find('duration').text = str(int(amount * div))
            t = target


def backup_targets(measure, div):
    t = F(0)
    targets = []
    for el in list(measure):
        if el.tag == 'note' and el.find('grace') is None and el.find('chord') is None:
            t += F(int(el.findtext('duration') or 0), div)
        elif el.tag == 'forward':
            t += F(int(el.findtext('duration')), div)
        elif el.tag == 'backup':
            t -= F(int(el.findtext('duration')), div)
            targets.append(t)
    return {'div': div, 'targets': targets}


# --------------------------------------------------------------------------------------------- #
# Page fixes
# --------------------------------------------------------------------------------------------- #
def repair_zero_divisions(root, report):
    """Audiveris writes <divisions>0</divisions> on a page with no pitched note (only whole
    measure rests), which is invalid and leaves the rest durations meaningless. Fall back to
    divisions 1 and give each measure rest the measure length."""
    fixed = 0
    for part in root.findall('part'):
        div, bar = 1, F(4)
        for m in part.findall('measure'):
            a = m.find('attributes')
            if a is not None:
                d = a.find('divisions')
                if d is not None and int(d.text or 0) <= 0:
                    d.text = '1'
                    fixed += 1
                if d is not None:
                    div = int(d.text)
                tm = a.find('time')
                if tm is not None and tm.find('beats') is not None:
                    bar = F(int(tm.findtext('beats')) * 4, int(tm.findtext('beat-type')))
            if div <= 0:
                continue
            for n in m.findall('note'):
                r = n.find('rest')
                if r is not None and r.get('measure') == 'yes':
                    n.find('duration').text = str(int(bar * div))
    report['zero_divisions'] = report.get('zero_divisions', 0) + fixed
    return fixed


def fill_empty_measures(root, report):
    for part in root.findall('part'):
        div, staves, bar = 1, 1, F(4)
        tab_staves = set()
        for m in part.findall('measure'):
            a = m.find('attributes')
            if a is not None:
                if a.find('divisions') is not None:
                    div = int(a.findtext('divisions'))
                if a.find('staves') is not None:
                    staves = int(a.findtext('staves'))
                tm = a.find('time')
                if tm is not None and tm.find('beats') is not None:
                    bar = F(int(tm.findtext('beats')) * 4, int(tm.findtext('beat-type')))
                for c in a.findall('clef'):
                    sn = c.get('number') or '1'
                    if c.findtext('sign') == 'TAB':
                        tab_staves.add(sn)
                    else:
                        tab_staves.discard(sn)
                for sd in a.findall('staff-details'):
                    if sd.findtext('staff-type') == 'tablature':
                        tab_staves.add(sd.get('number') or '1')
            present = {n.findtext('staff') or '1' for n in m.findall('note')}
            missing = [st for st in range(1, staves + 1)
                       if str(st) not in present and str(st) not in tab_staves]
            if not missing:
                continue
            kids = list(m)
            idx = next((i for i, k in enumerate(kids)
                        if k.tag == 'barline' and k.get('location') == 'right'), len(kids))
            cursor = 0
            for k in kids[:idx]:
                if k.tag == 'note' and k.find('grace') is None and k.find('chord') is None:
                    cursor += int(k.findtext('duration') or 0)
                elif k.tag == 'forward':
                    cursor += int(k.findtext('duration') or 0)
                elif k.tag == 'backup':
                    cursor -= int(k.findtext('duration') or 0)
            new = []
            for st in missing:
                if cursor > 0:
                    b = ET.Element('backup')
                    ET.SubElement(b, 'duration').text = str(cursor)
                    new.append(b)
                n = make_rest(bar, div, str(1 + 4 * (st - 1)), str(st) if staves > 1 else None)
                n.find('rest').set('measure', 'yes')
                new.append(n)
                cursor = int(bar * div)
            for k, e in enumerate(new):
                m.insert(idx + k, e)
            report['empty_filled'] += 1


def part_measures(root):
    """Yield (part, measure, div, bar) for all measures, tracking divisions and time."""
    for part in root.findall('part'):
        div, beats = 1, F(4)
        for m in part.findall('measure'):
            a = m.find('attributes')
            if a is not None:
                if a.find('divisions') is not None:
                    div = int(a.findtext('divisions'))
                tm = a.find('time')
                if tm is not None and tm.find('beats') is not None:
                    beats = F(int(tm.findtext('beats')) * 4, int(tm.findtext('beat-type')))
            yield part, m, div, beats


def leading_forward(m, first_note):
    """Report the <forward> right before the first note of a voice (after measure start or a
    backup), if any."""
    kids = list(m)
    i = kids.index(first_note) - 1
    while i >= 0 and kids[i].tag not in ('note', 'backup', 'forward'):
        i -= 1
    return kids[i] if i >= 0 and kids[i].tag == 'forward' else None


def drop_dots(evs, excess, div):
    """Undot notes of an over-full voice: first all of them, then dots are given back from left
    to right as long as the voice does not get over-full again (it stops at the last one that
    fits). Return the undotted events."""
    dotted = [e for e in evs if not e.is_rest and len(e.el.findall('dot')) == 1]
    extra = [e.dur / 3 for e in dotted]  # a dot adds a third of the dotted length
    over = excess - sum(extra)  # with no dot at all
    keep = 0
    while keep < len(dotted) and over + extra[keep] <= 0:
        over += extra[keep]
        keep += 1
    drop = dotted[keep:]
    for e in drop:
        for el in e.members:
            el.remove(el.find('dot'))
            el.find('duration').text = str(int(e.dur * 2 / 3 * div))
    return drop


def trim_measure(part, m, div, bar, report, page):
    """Trim over-full voices at the barline. Return True if modified."""
    targets = backup_targets(m, div)
    changed = False
    for v, evs in voices_of(m, div).items():
        end = max(e.end for e in evs)
        if end <= bar:
            continue
        dropped = drop_dots(evs, end - bar, div)
        if dropped:
            changed = True
            evs = voices_of(m, div)[v]
            new_end = max(e.end for e in evs)
            report['drop_dot'].append(f'{page} m{m.get("number")} {part.get("id")} v{v} '
                                      f'{len(dropped)} dot(s) {sgn(end - bar)} -> {sgn(new_end - bar)}')
            end = new_end
            if end <= bar:
                continue
        excess = end - bar
        lead_fwd = leading_forward(m, evs[0].el)
        if lead_fwd is not None and F(int(lead_fwd.findtext('duration')), div) == excess:
            # Voice pushed late by a bogus gap (no printed rest): shift it back
            m.remove(lead_fwd)
            report['trim_gap'].append(f'{page} m{m.get("number")} {part.get("id")} v{v} -{excess}')
            changed = True
            continue
        sounding = [e for e in evs if not e.is_rest]
        lead = [e for e in evs if e.is_rest and sounding and e.end <= sounding[0].start]
        if (sounding and has_tie(sounding[0].el, 'stop') and lead
                and sum(e.dur for e in lead) == excess):
            # Bogus rest(s) before a tie continuation, which must start the measure
            for e in lead:
                for el in e.members:
                    m.remove(el)
            report['trim_rest'].append(f'{page} m{m.get("number")} {part.get("id")} v{v}')
        else:
            cut = [e for e in evs if (not e.is_rest) and e.start >= bar]
            if cut:
                report['overflow_cut'].append(
                    f'{page} m{m.get("number")} {part.get("id")} v{v} {len(cut)} note(s) {sgn(excess)}')
            for e in evs:
                if e.start >= bar:
                    for el in e.members:
                        m.remove(el)
                elif e.end > bar:
                    q = bar - e.start
                    for el in e.members:
                        set_value(el, q, div)
                    report['trim_note'].append(
                        f'{page} m{m.get("number")} {part.get("id")} v{v} {e.dur}->{q}')
        changed = True
    if changed:
        fix_backups(m, targets)
    return changed


def keep_cursor(m, after, added, div):
    """After lengthening a voice by `added` just before `after`'s next sibling: if other content
    follows without a <backup> (Audiveris does this), step back so it keeps its position."""
    kids = list(m)
    i = kids.index(after) + 1
    if i < len(kids) and kids[i].tag in ('note', 'forward'):
        b = ET.Element('backup', new='1')
        ET.SubElement(b, 'duration').text = str(int(added * div))
        m.insert(i, b)


def pad_measure(part, m, div, bar, report, page):
    """Pad under-full voices with rests up to the measure length of the time signature."""
    target = bar
    targets = backup_targets(m, div)
    changed = False
    voices = voices_of(m, div)
    for v, evs in voices.items():
        end = max(e.end for e in evs)
        if end >= target:
            continue
        last = max(evs, key=lambda e: e.end)
        q = last.dur + target - end
        if last.is_rest and last.el.find('rest').get('measure') == 'yes':
            # A short measure rest is stretched rather than followed by another rest
            last.el.find('duration').text = str(int(q * div))
            keep_cursor(m, last.members[-1], target - end, div)
            report['padded'].append(
                f'{page} m{m.get("number")} {part.get("id")} v{v} measure rest {last.dur}->{q}')
        elif target == bar and (not last.is_rest) and has_tie(last.el, 'start') and any(v2 == q for v2, _, _ in VALUES):
            # A note tied over the barline must reach it: extend the note (keeps the tie)
            for el in last.members:
                set_value(el, q, div)
            keep_cursor(m, last.members[-1], target - end, div)
            report['extended'].append(
                f'{page} m{m.get("number")} {part.get("id")} v{v} {last.dur}->{q}')
        else:
            staff = last.el.findtext('staff')
            idx = list(m).index(last.members[-1]) + 1
            rests = rests_for(target - end, div, v, staff)
            if any((not e.is_rest) and e.start < target and e.end > end
                   for v2, evs2 in voices.items() if v2 != v
                   for e in evs2 if e.el.findtext('staff') == staff):
                for r in rests:
                    r.set('print-object', 'no')
            for k, r in enumerate(rests):
                m.insert(idx + k, r)
            keep_cursor(m, rests[-1], target - end, div)
            report['padded'].append(
                f'{page} m{m.get("number")} {part.get("id")} v{v} +{target - end}')
        changed = True
    if changed:
        fix_backups(m, targets)


def trim_and_pad(root, report, page):
    # Pass 1: trim over-full voices in every part
    for part, m, div, bar in part_measures(root):
        if m.get('implicit') != 'yes':
            trim_measure(part, m, div, bar, report, page)
    # Pass 2: pad under-full voices
    for part, m, div, bar in part_measures(root):
        if m.get('implicit') != 'yes' and voices_of(m, div):
            pad_measure(part, m, div, bar, report, page)


def merge_double_dot_splits(root, report, page):
    """Merge a double-dotted half + eighth split across two voices on the same staff."""
    for part, m, div, bar in part_measures(root):
        if m.get('implicit') == 'yes' or bar != F(4):
            continue
        by_staff = {}
        for v, evs in voices_of(m, div).items():
            staves = {e.el.findtext('staff') or '1' for e in evs}
            if len(staves) == 1:
                by_staff.setdefault(next(iter(staves)), []).append((v, evs))
        for st, vs in by_staff.items():
            if len(vs) < 2:
                continue
            merged = False
            for v1, ev1 in vs:
                if len(ev1) != 2:
                    continue
                e0, e1 = ev1
                if e0.is_rest or e0.start != 0 or e0.el.findtext('type') != 'half' or not e1.is_rest:
                    continue
                d0 = len(e0.el.findall('dot'))
                for v2, ev2 in vs:
                    if v2 == v1 or len(ev2) != 1 or ev2[0].is_rest:
                        continue
                    e2 = ev2[0]
                    case_a = (d0 == 1 and e0.dur == F(3) and e1.start == F(3) and e1.dur == F(1)
                              and e2.start == F(7, 2) and e2.dur == F(1, 2))
                    case_b = (d0 == 2 and e0.dur == F(7, 2) and e1.start == F(7, 2) and e1.dur == F(1, 2)
                              and e2.start == F(3) and e2.dur == F(1))
                    if not (case_a or case_b):
                        continue
                    targets = backup_targets(m, div)
                    if case_a:
                        for el in e0.members:
                            set_value(el, F(7, 2), div)
                    else:
                        for el in e2.members:
                            set_value(el, F(1, 2), div)
                    for el in e1.members:
                        m.remove(el)
                    fwd = leading_forward(m, e2.el)
                    if fwd is not None:
                        m.remove(fwd)
                    for el in e2.members:
                        vel = el.find('voice')
                        if vel is not None:
                            vel.text = v1
                        m.remove(el)
                    anchor = list(m).index(e0.members[-1]) + 1
                    for k, el in enumerate(e2.members):
                        m.insert(anchor + k, el)
                    fix_backups(m, targets)
                    kids = list(m)
                    for i, el in enumerate(kids):
                        if el.tag == 'backup':
                            nxt = next((k for k in kids[i + 1:] if k.tag != 'barline'), None)
                            if nxt is None or nxt.tag == 'backup':
                                m.remove(el)
                    report['double_dot_merged'].append(
                        f'{page} m{m.get("number")} {part.get("id")} st{st} v{v2}->v{v1}')
                    merged = True
                    break
                if merged:
                    break


# Note type reached by each beam count in a beamed group (written value, quarters).
BEAM_VALUE = {1: F(1, 2), 2: F(1, 4), 3: F(1, 8), 4: F(1, 16)}


def value_type(q):
    """Return (type, dots) for a standard note value in quarters, else None."""
    for v, t, d in VALUES:
        if v == q:
            return t, d
    return None


def set_type_only(note, q):
    """Set <type>/<dot> for q without touching the duration."""
    match = value_type(q)
    if match is None:
        return False
    for tag in ('type', 'dot'):
        for e in note.findall(tag):
            note.remove(e)
    te = ET.Element('type')
    te.text = match[0]
    insert_ordered(note, te)
    for _ in range(match[1]):
        insert_ordered(note, ET.Element('dot'))
    return True


def set_time_modification(note, actual, normal):
    for e in note.findall('time-modification'):
        note.remove(e)
    tm = ET.Element('time-modification')
    ET.SubElement(tm, 'actual-notes').text = str(actual)
    ET.SubElement(tm, 'normal-notes').text = str(normal)
    insert_ordered(note, tm)


def add_tie(note, kind):
    """Mark a note with a MusicXML tie, creating a notation tied element."""
    tie = ET.Element('tie')
    tie.set('type', kind)
    insert_ordered(note, tie)
    nots = note.find('notations')
    if nots is None:
        nots = ET.Element('notations')
        insert_ordered(note, nots)
    tied = ET.SubElement(nots, 'tied')
    tied.set('type', kind)


def tuplet_for(q, max_actual=8):
    """Represent q as a standard written value under a small time-modification."""
    for actual in range(2, max_actual + 1):
        for normal in range(actual - 1, 0, -1):
            w = q * actual / normal
            if value_type(w) is not None:
                return w, actual, normal
    return None


def split_standard(q):
    """Split q into standard values only (no tuplets), or None."""
    out = []
    while q > 0:
        v = next((v for v, _, _ in VALUES if v <= q), None)
        if v is None:
            return None
        out.append((v, None))
        q -= v
    return out


def split_value(q):
    """Split q into standard values plus, if needed, one small-tuplet segment."""
    out = []
    while q > 0:
        if value_type(q) is not None:
            out.append((q, None))
            break
        tup = tuplet_for(q, 4)
        if tup is not None:
            out.append((q, (tup[1], tup[2])))
            break
        v = next((v for v, _, _ in VALUES if v < q), None)
        if v is None:
            return None
        out.append((v, None))
        q -= v
    return out


def _clone_note(note):
    new = copy.deepcopy(note)
    for tag in ('duration', 'type', 'dot', 'tie', 'time-modification'):
        for e in new.findall(tag):
            new.remove(e)
    nots = new.find('notations')
    if nots is not None:
        for e in nots.findall('tied'):
            nots.remove(e)
    return new


def split_event(m, event, div, segments, tie_chain=False):
    """Replace a note/rest (with its chord members) by segments [(quarters, tm or None)]."""
    members = event.members
    anchor = list(m).index(members[0])
    for el in members:
        m.remove(el)
    pos = anchor
    for i, (q, tup) in enumerate(segments):
        for orig in members:
            n = _clone_note(orig)
            if i:
                for e in n.findall('notations'):
                    n.remove(e)
            dur = ET.Element('duration')
            dur.text = str(int(q * div))
            insert_ordered(n, dur)
            if tup is None:
                set_type_only(n, q)
            else:
                set_type_only(n, q * F(tup[0], tup[1]))
                set_time_modification(n, tup[0], tup[1])
            if tie_chain:
                if i == 0:
                    add_tie(n, 'start')
                elif i == len(segments) - 1:
                    add_tie(n, 'stop')
                else:
                    add_tie(n, 'start')
                    add_tie(n, 'stop')
            m.insert(pos, n)
            pos += 1


def fix_missing_values(root, report, page=''):
    """Give missing <type> values to page tails, preserving every total duration.

    A1: a time-modification fixes the written value; only the type is added.
    B:  a beamed, short note without time-modification; the beam count gives the written
        value and the missing tuplet ratio.
    C:  a long unbewed note at the end of a complete voice; the total is split into a
        tied chain of standard values.
    D:  a rest with a non-standard duration; the total is split into standard rests
        (one small tuplet segment when the remainder has no standard value).
    A2: an incomplete six-tuplet is left alone and listed for rebuilding.
    """
    stats = {}
    for part, m, div, bar in part_measures(root):
        num = m.get('number')
        if m.get('implicit') == 'yes':
            continue
        for v, evs in voices_of(m, div).items():
            if not evs or max(e.end for e in evs) != bar:
                continue
            e = evs[-1]
            el = e.el
            if el.findtext('type') is not None:
                continue
            tm = el.find('time-modification')
            beams = len(el.findall('beam'))
            is_rest = e.is_rest
            d = e.dur
            tag = f'{page} m{num} {part.get("id")} v{v}'
            if is_rest and el.find('rest').get('measure') == 'yes':
                continue
            if tm is not None:
                actual = int(tm.findtext('actual-notes', '0') or 0)
                normal = int(tm.findtext('normal-notes', '0') or 0)
                if actual <= 0 or normal <= 0:
                    report['type_skipped'].append(f'{tag} bad time-modification')
                    continue
                same = sum(1 for x in evs if x.el.find('time-modification') is not None
                           and x.el.findtext('time-modification/actual-notes') == str(actual)
                           and x.el.findtext('time-modification/normal-notes') == str(normal))
                if actual >= 6 and same < actual:
                    report['type_skipped'].append(
                        f'{tag} A2 incomplete {actual}-tuplet ({same} notes)')
                    continue
                written = d * F(actual, normal)
                if value_type(written) is not None:
                    for member in e.members:
                        set_type_only(member, written)
                    report['type_fixed'].append(f'{tag} A1 {d} tm{actual}:{normal} -> {value_type(written)[0]}')
                    stats['A1'] = stats.get('A1', 0) + 1
                else:
                    report['type_skipped'].append(f'{tag} A1 written {written} not standard')
                continue
            if is_rest:
                segments = [(d, None)] if value_type(d) is not None else split_value(d)
                if segments is None:
                    report['type_skipped'].append(f'{tag} D rest {d} has no standard split')
                    continue
                if len(segments) == 1 and segments[0][1] is None:
                    set_type_only(el, d)
                else:
                    split_event(m, e, div, segments)
                report['type_fixed'].append(f'{tag} D rest {d} -> {len(segments)} value(s)')
                stats['D'] = stats.get('D', 0) + 1
                continue
            if beams and d <= 1 and len(e.members) == 1:
                written = BEAM_VALUE.get(beams)
                if written is None or written <= d:
                    report['type_skipped'].append(f'{tag} B beam {beams} does not fit {d}')
                    continue
                ratio = written / d
                if ratio.numerator > 8 or ratio.denominator >= ratio.numerator:
                    report['type_skipped'].append(f'{tag} B ratio {ratio} not a small tuplet')
                    continue
                set_type_only(el, written)
                set_time_modification(el, ratio.numerator, ratio.denominator)
                report['type_fixed'].append(
                    f'{tag} B {d} beam{beams} -> {value_type(written)[0]} tm{ratio.numerator}:{ratio.denominator}')
                stats['B'] = stats.get('B', 0) + 1
                continue
            if not beams and d > 1 and not any(
                    el.findall('tie')):
                segments = split_standard(d)
                if segments is None:
                    report['type_skipped'].append(f'{tag} C note {d} has no standard tie chain')
                    continue
                split_event(m, e, div, segments, tie_chain=True)
                report['type_fixed'].append(f'{tag} C note {d} -> {len(segments)} tied value(s)')
                stats['C'] = stats.get('C', 0) + 1
                continue
            report['type_skipped'].append(f'{tag} not a supported tail case (d={d})')
    return stats


def rehearsals_from_credits(root, omr_path, report, page):
    """Move rehearsal-like page credits back into boxed rehearsal directions."""
    credits = []
    for cr in root.findall('credit'):
        cw = cr.find('credit-words')
        if cw is not None and REHEARSAL_RE.match((cw.text or '').strip()):
            credits.append((cr, cw.text.strip()))
    if not credits:
        return
    sheet = zipfile.ZipFile(omr_path).read('sheet#1/sheet#1.xml').decode()
    # system vertical ranges (from staff line points), top down
    systems = []
    for s in re.findall(r'<system\b.*?</system>', sheet, re.S):
        ys = [float(y) for y in re.findall(r'<point x="[\d.]+" y="([\d.]+)"', s)]
        systems.append((min(ys), max(ys)))
    systems.sort()
    # word inters with the same values
    words = {}
    for w in re.finditer(r'<word value="([^"]*)"[^>]*>(.*?)</word>', sheet, re.S):
        b = re.search(r'<bounds x="(\d+)" y="(\d+)" w="(\d+)" h="(\d+)"', w.group(2))
        if b and REHEARSAL_RE.match(w.group(1)):
            words.setdefault(w.group(1), []).append(int(b.group(2)) + int(b.group(4)) // 2)
    part = root.find('part')
    measures = part.findall('measure')
    starts = [0] + [i for i, m in enumerate(measures)
                    if i > 0 and m.find('print') is not None
                    and m.find('print').get('new-system') == 'yes']
    for cr, text in credits:
        ys = words.get(text)
        if not ys:
            continue
        y = ys.pop(0)
        # system just below the mark
        k = next((i for i, (top, bot) in enumerate(systems) if y < bot), None)
        if k is None or k >= len(starts):
            continue
        m = measures[starts[k]]
        d = ET.Element('direction', placement='above')
        dt = ET.SubElement(d, 'direction-type')
        r = ET.SubElement(dt, 'rehearsal', enclosure='square')
        r.text = text
        kids = list(m)
        idx = next((i for i, c in enumerate(kids) if c.tag not in ('print', 'attributes', 'barline')),
                   len(kids))
        m.insert(idx, d)
        root.remove(cr)
        report['rehearsal'].append(f'{page} {text} -> m{m.get("number")}')


VOCAL_RE = re.compile(r'vocal|voice|chorus|choir|^vo\.?$|^cho\.?$|歌', re.I)


def lyrics_to_words(root, report, page):
    """Instrumental parts: every <lyric> is misread staff text (pizz., Bell (15ma), 8va
    fragments...). A begin/middle syllable left open makes MuseScore draw hyphens up to the
    next syllable, possibly many systems later. Turn them into below-staff words, drop noise.
    Vocal parts (name or abbreviation like Vocal / Vo. / Chorus) keep their lyrics."""
    names = {sp.get('id'): ' '.join(filter(None, (sp.findtext('part-name'),
                                                  sp.findtext('part-abbreviation'))))
             for sp in root.iter('score-part')}
    for part in root.findall('part'):
        if any(VOCAL_RE.search(w) for w in names.get(part.get('id'), '').split()):
            continue
        for m in part.findall('measure'):
            kids = list(m)
            for note in [c for c in kids if c.tag == 'note']:
                lyrics = note.findall('lyric')
                if not lyrics:
                    continue
                texts = [(l.findtext('text') or '').strip() for l in lyrics]
                for l in lyrics:
                    note.remove(l)
                text = ' '.join(t for t in texts if t)
                if sum(c.isalpha() for c in text) < 2 or re.fullmatch(r'\(?F?(8|15)?(va|ma)\)?', text, re.I):
                    report['lyric_dropped'].append(f'{page} m{m.get("number")} {text!r}')
                    continue
                # before the chord head, never between chord members
                idx = list(m).index(note)
                while idx > 0 and m[idx].find('chord') is not None:
                    idx -= 1
                d = ET.Element('direction', placement='below')
                ET.SubElement(ET.SubElement(d, 'direction-type'), 'words').text = text
                if note.find('staff') is not None:
                    ET.SubElement(d, 'staff').text = note.findtext('staff')
                m.insert(idx, d)
                report['lyric_words'].append(f'{page} m{m.get("number")} {text!r}')


def file_name(path):
    """Last component of a Windows or POSIX path (os.path.basename knows only the host's)."""
    return re.split(r'[\\/]', path)[-1]


def scrub_paths(root):
    for e in root.iter('source'):
        if e.text:
            e.text = file_name(e.text)
    for e in root.iter('miscellaneous-field'):
        if e.get('name') == 'source-file' and e.text:
            e.text = file_name(e.text)


def prune_virtual_measures(root, report=None, page=''):
    """Remove spurious virtual measures (like '12+1') generated by Audiveris measure-repeat expansion
    when they are not present across all parts, and orphan extra measures that follow a negative-width
    measure in a subset of parts.  Each removal is recorded for the measure map."""
    parts = root.findall('part')
    if not parts:
        return
    measure_sets = [set(m.get('number') for m in p.findall('measure')) for p in parts]
    common_numbers = set.intersection(*measure_sets)
    for p in parts:
        prev = None
        for m in list(p.findall('measure')):
            num = m.get('number', '')
            if '+' in num and num not in common_numbers:
                p.remove(m)
                if report is not None:
                    report.setdefault('measure_map_deleted', []).append((page, num))
                continue
            if num not in common_numbers and prev is not None:
                try:
                    prev_w = float(prev.get('width', ''))
                except ValueError:
                    prev_w = None
                if prev_w is not None and prev_w < 0:
                    prev.attrib.pop('width', None)
                    p.remove(m)
                    if report is not None:
                        report.setdefault('measure_map_deleted', []).append((page, num))
                    continue
            prev = m


def _float_pos(val):
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _non_rest_count(measure):
    return sum(1 for n in measure.findall('note') if n.find('rest') is None)


def _insert_key_in_attributes(measure, key_el):
    """Insert a <key> element into measure's <attributes> in MusicXML DTD order."""
    attrs = measure.find('attributes')
    if attrs is None:
        attrs = ET.Element('attributes')
        idx = 1 if len(measure) and measure[0].tag == 'print' else 0
        measure.insert(idx, attrs)
    after_tags = {'footnote', 'level', 'divisions'}
    pos = 0
    for i, child in enumerate(attrs):
        if child.tag in after_tags:
            pos = i + 1
        elif child.tag == 'key':
            pos = i + 1
    attrs.insert(pos, key_el)


def read_page_edge_list(path):
    """Read <song dir>/context/page_edge_prune.txt: {(page, measure number): evidence}.

    One line per verified page-edge measure: `<page> <measure number> <evidence>`, where the
    evidence names what the printed page shows there (e.g. `crop p12 right edge: courtesy key
    signature only`).  '#' starts a comment.  An entry without evidence maps to ''.
    """
    entries = {}
    if not os.path.isfile(path):
        return entries
    with open(path, encoding='utf-8') as f:
        for line in f:
            fields = line.split('#', 1)[0].split(None, 2)
            if len(fields) >= 2:
                entries[(fields[0], fields[1])] = fields[2].strip() if len(fields) == 3 else ''
    return entries


def prune_page_edge_measures(pages, report=None, verified=None):
    """Report narrow page-edge measures; remove only those verified against the printed page.

    A candidate is a page's final measure that is much narrower than the other measures of the
    page (< 35% of their median width) and has <= 3 non-rest notes in every part: the shape a
    trailing courtesy key signature takes, but also of a short real measure, which the MusicXML
    cannot tell apart.  Candidates are only reported.  A page's final measure is removed only
    when `verified` (read_page_edge_list) lists its page and measure number with evidence; its
    key signature then moves to the next page's opening measure where that one has none.
    """
    verified = verified or {}
    rep = report if report is not None else {}
    for idx, (page_name, root) in enumerate(pages):
        parts = root.findall('part')
        if not parts or any(len(p.findall('measure')) < 2 for p in parts):
            continue
        last_ms = [p.findall('measure')[-1] for p in parts]
        num = last_ms[0].get('number')
        other_widths = [w for m in parts[0].findall('measure')[:-1]
                        if (w := _float_pos(m.get('width'))) is not None]
        last_w = _float_pos(last_ms[0].get('width'))
        notes = max(_non_rest_count(m) for m in last_ms)
        if other_widths and last_w is not None:
            med_w = statistics.median(other_widths)
            if last_w < 0.35 * med_w and notes <= 3:
                rep.setdefault('page_edge_candidates', []).append(
                    f'{page_name}: m{num} (w={last_w:g}, med={med_w:g}, notes={notes})')
        evidence = verified.get((page_name, num))
        if evidence is None:
            continue
        if not evidence:
            rep.setdefault('page_edge_rejected', []).append(f'{page_name}: m{num} (no evidence)')
            continue
        if idx + 1 < len(pages):
            next_parts = pages[idx + 1][1].findall('part')
            if len(next_parts) == len(parts):
                for m, np_ in zip(last_ms, next_parts):
                    nm = np_.find('measure')
                    src_key = m.find('.//key')
                    if nm is not None and nm.find('.//key') is None and src_key is not None:
                        _insert_key_in_attributes(nm, copy.deepcopy(src_key))
        for p, m in zip(parts, last_ms):
            p.remove(m)
        rep.setdefault('page_edge_pruned', []).append(f'{page_name}: m{num} ({evidence})')
        rep.setdefault('measure_map_deleted', []).append((page_name, num))


def merge_split_first_endings(root, report=None):
    """Join a 1st ending that a page break split into two <ending> elements.

    Audiveris closes the ending on the page where the bracket starts (start+discontinue)
    and opens a second one at the page holding the closing barline (start+stop/discontinue
    with the backward repeat).  Playback then leaves the 1st ending early and the second
    fragment has no backward repeat of its own.  When no other ending or repeat lies
    between the two, keep the first <start> and close it where the backward repeat is.
    A start+discontinue without a later closing ending and backward repeat (a stray
    ending) is left alone.
    """
    rep = report if report is not None else {}
    for part in root.findall('part'):
        measures = part.findall('measure')
        for i, m in enumerate(measures):
            if m.find('.//repeat') is not None:
                continue
            a_ends = [(b, e) for b in m.findall('barline') for e in b.findall('ending')]
            if len(a_ends) != 2 or any(e.get('number') != '1' for _, e in a_ends):
                continue
            if sorted(e.get('type') for _, e in a_ends) != ['discontinue', 'start']:
                continue
            for j in range(i + 1, len(measures)):
                nb = measures[j].findall('barline')
                b_ends = [(b, e) for b in nb for e in b.findall('ending')]
                b_reps = [r for b in nb for r in b.findall('repeat')]
                if b_ends or b_reps:
                    break
            else:
                continue
            if (len(b_ends) != 2 or any(e.get('number') != '1' for _, e in b_ends)
                    or sorted(e.get('type') for _, e in b_ends)
                    not in (['start', 'stop'], ['discontinue', 'start'])
                    or [(r.get('direction'), r.get('times')) for r in b_reps]
                    != [('backward', None)]):
                continue
            for b, e in a_ends:
                if e.get('type') == 'discontinue':
                    b.remove(e)
                    break
            for b, e in b_ends:
                if e.get('type') == 'start':
                    b.remove(e)
                elif e.get('type') == 'discontinue':
                    e.set('type', 'stop')
            rep.setdefault('split_endings_merged', []).append(
                f'{part.get("id")} m{m.get("number")}-m{measures[j].get("number")}')


# --------------------------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------------------------- #
def main(song_dir):
    song_dir = os.path.abspath(song_dir)
    base = os.path.basename(song_dir)
    song_id = base.split('_')[0]
    raw = os.path.join(song_dir, 'raw')
    out_pages = os.path.join(song_dir, 'pages')
    os.makedirs(out_pages, exist_ok=True)
    report = {k: [] for k in ('drop_dot', 'overflow_cut', 'trim_gap', 'trim_rest', 'trim_note', 'padded',
                              'extended', 'double_dot_merged', 'page_edge_candidates',
                              'page_edge_pruned', 'page_edge_rejected',
                              'split_endings_merged', 'measure_map_deleted',
                              'type_fixed', 'type_skipped',
                              'rehearsal', 'lyric_words', 'lyric_dropped')}
    report['empty_filled'] = 0
    report['zero_divisions'] = 0
    mxls = sorted(glob.glob(os.path.join(raw, '*.mxl')))
    tmp = tempfile.mkdtemp()
    norm = os.path.join(tmp, base, 'normalized')
    os.makedirs(norm)
    os.makedirs(os.path.join(tmp, 'Tools'))
    shutil.copy(os.path.join(HERE, 'merge_pages.py'), os.path.join(tmp, 'Tools'))
    canonical_pids = None
    if mxls:
        first_root = read_mxl(mxls[0])
        canonical_pids = [p.get('id') for p in first_root.findall('part')]

    pages = []
    for i, mxl in enumerate(mxls, 1):
        page = os.path.basename(mxl)[:-4]
        root = read_mxl(mxl)
        if canonical_pids:
            part_list = root.find('part-list')
            if part_list is not None:
                for sp in list(part_list.findall('score-part')):
                    if sp.get('id') not in canonical_pids:
                        part_list.remove(sp)
            for p in list(root.findall('part')):
                if p.get('id') not in canonical_pids:
                    root.remove(p)
        prune_virtual_measures(root, report, page)
        rehearsals_from_credits(root, mxl[:-4] + '.omr', report, page)
        repair_zero_divisions(root, report)
        fill_empty_measures(root, report)
        trim_and_pad(root, report, page)
        merge_double_dot_splits(root, report, page)
        fix_missing_values(root, report, page)
        lyrics_to_words(root, report, page)
        scrub_paths(root)
        pages.append((page, root))

    prune_page_edge_measures(pages, report, read_page_edge_list(
        os.path.join(song_dir, 'context', 'page_edge_prune.txt')))
    for i, (page, root) in enumerate(pages, 1):
        tree = ET.ElementTree(root)
        tree.write(os.path.join(out_pages, page + '.musicxml'), encoding='UTF-8',
                   xml_declaration=True)
        tree.write(os.path.join(norm, f'{base}_p{i:02d}_normalized.musicxml'), encoding='UTF-8',
                   xml_declaration=True)
    # the lower half of a split page (<id>_pNNb) continues the page of its upper half
    stems = [os.path.basename(m)[:-4] for m in mxls]
    continues = [str(i) for i, s in enumerate(stems, 1)
                 if s.endswith('b') and i > 1 and stems[i - 2] == s[:-1] + 'a']
    subprocess.run([sys.executable, os.path.join(tmp, 'Tools', 'merge_pages.py'), base,
                    str(len(mxls))] + (['--continues=' + ','.join(continues)] if continues else []),
                   check=True, cwd=tmp, stdout=subprocess.DEVNULL)
    # review file lives inside <song_dir>/ and is named <id>_<title>[_Keyboard].musicxml
    # from the '- Title:' line of song_metadata.md (falling back to '- pdf:' or song_dir basename)
    name = base
    meta_path = os.path.join(song_dir, 'context', 'song_metadata.md')
    if os.path.exists(meta_path):
        with open(meta_path, encoding='utf-8') as f:
            meta = f.read()
        t = re.search(r'^- Title:\s*(.+?)\s*(?:[（(].*)?$', meta, re.M)
        m = re.search(r'^- pdf:\s*(.+?)\s*$', meta, re.M)
        if t:
            title = t.group(1)
            if base.endswith('_keyboard') and 'keyboard' not in title.lower():
                title = re.sub(r'[/?:]', '_', title).rstrip('_') + '_Keyboard'
            name = base.split('_')[0] + '_' + title
        elif m:
            name = os.path.splitext(m.group(1))[0]
    merged = os.path.join(os.path.abspath(song_dir), re.sub(r'[/?:]', '_', name) + '.musicxml')
    shutil.move(os.path.join(tmp, base, f'{base}_merged.musicxml'), merged)
    shutil.rmtree(tmp)
    merged_tree = ET.parse(merged)
    merge_split_first_endings(merged_tree.getroot(), report)
    merged_tree.write(merged, encoding='UTF-8', xml_declaration=True)
    # trace every source measure stack (page unit, system, raw number) to its final measure;
    # verified page-edge / virtual removals keep a `deleted` row.  A count mismatch means an
    # unrecorded deletion (e.g. a song hook): the map is not written rather than guessed.
    rows = measure_map.build_map(pages, report['measure_map_deleted'])
    merged_count = len(merged_tree.getroot().find('part').findall('measure'))
    kept = sum(1 for r in rows if r['status'] == 'kept')
    if kept == merged_count:
        map_path = os.path.join(song_dir, 'context', 'measure_map.tsv')
        measure_map.write_map(map_path, rows)
        print(f'measure map: {map_path} ({kept} kept, '
              f'{len(rows) - kept} deleted)')
    else:
        print(f'measure map not written: {kept} source measures, merged score has '
              f'{merged_count}; record the deleted measures')
    subprocess.run([sys.executable, os.path.join(HERE, 'fill_measure_repeats.py'), merged],
                   check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'fill_slash_chords.py'), merged],
                   check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'clean_score_noise.py'), merged],
                   check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'fix_rehearsal_marks.py'), merged],
                   check=True)
    hints = os.path.join(song_dir, 'context', 'instrument_changes.txt')
    if os.path.exists(hints):
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_instrument_changes.py'),
                        merged, hints], check=True)
    ottava = os.path.join(song_dir, 'context', 'ottava.txt')
    if os.path.exists(ottava):
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_ottava.py'), merged, ottava],
                       check=True)
        # an octave shift changes the pitch at its ends, so ties crossing them are no longer pairs
        subprocess.run([sys.executable, os.path.join(HERE, 'clean_score_noise.py'), merged],
                       check=True)
    meta = os.path.join(song_dir, 'context', 'song_metadata.md')
    if os.path.exists(meta):
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_score_hints.py'), merged, meta],
                       check=True)
    av_hints = os.path.join(song_dir, 'context', 'audiveris_hints.txt')
    if os.path.exists(av_hints):     # partsHint ":capoN" -> <transpose>, before unify_keys
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_capo.py'), merged, av_hints],
                       check=True)
    song_fix = os.path.join(song_dir, 'context', 'hook.py')
    if os.path.exists(song_fix):
        # tools/ on PYTHONPATH: a hook (and the fix scripts it runs) can import hook_lib wherever
        # songs/ is kept (Python resolves a songs/ symlink, so ../../../tools may not be tools/)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(
            filter(None, [HERE, os.environ.get('PYTHONPATH')])))
        subprocess.run([sys.executable, song_fix, merged], check=True, env=env)
    # guitar staves Audiveris read with a bass clef go back to treble before keys are unified
    subprocess.run([sys.executable, os.path.join(HERE, 'fix_guitar_clefs.py'), merged],
                   check=True)
    # last, so that parts a song hook marked with <transpose> are left alone
    subprocess.run([sys.executable, os.path.join(HERE, 'unify_keys.py'), merged], check=True)
    # guitar / bass-guitar notation is written an octave above sounding: add the octave after
    # key unification, so these parts still take part in it (an octave does not change the key)
    subprocess.run([sys.executable, os.path.join(HERE, 'apply_tab_octave.py'), merged],
                   check=True)
    # very last: chord names / directions whose notes were shortened or rewritten above
    subprocess.run([sys.executable, os.path.join(HERE, 'clamp_offsets.py'), merged], check=True)
    # Report
    print(f'pages: {len(mxls)}  empty measures filled: {report["empty_filled"]}  zero divisions fixed: {report["zero_divisions"]}')
    for k in ('rehearsal', 'lyric_words', 'lyric_dropped', 'drop_dot', 'trim_gap', 'trim_rest', 'trim_note', 'padded', 'extended',
              'double_dot_merged', 'page_edge_candidates', 'page_edge_pruned', 'page_edge_rejected',
              'split_endings_merged', 'overflow_cut'):
        print(f'{k}: {len(report[k])}')
        for line in report[k]:
            print('   ', line)
    print('merged:', merged)
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    q = subprocess.run([sys.executable, os.path.join(HERE, 'score_quality.py'), merged],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, check=True).stdout
    q = ''.join(l for l in q.splitlines(True) if not l.startswith('modified='))  # keeps reruns diff-clean
    qpath = os.path.join(song_dir, f'{song_id}_quality.txt')
    with open(qpath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(q)
    print(q)
    print('quality report:', qpath)


if __name__ == '__main__':
    main(sys.argv[1])
