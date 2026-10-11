#!/usr/bin/env python3
"""Light post-processing of patched-Audiveris output (raw/) into a preview score.

    python3 tools/bandscore_postprocess.py "<song dir>"

Reads <song dir>/raw/*.mxl (+ .omr), writes
<song dir>/pages/*.musicxml and <songs dir>/<input pdf name>.musicxml (next to the song dir, for review).

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
    tied over the barline is extended instead, so that its tie stays valid;
  * lyrics of instrumental parts (misread staff text; open syllables draw hyphen dashes
    across systems) become below-staff words, OCR fragments (va, **, b) are dropped;
  * source paths (which may contain the user name) are reduced to file names.

Score-level fixes after merge: tools/fill_measure_repeats.py (measure repeats at the top of a
page get the notes of the last measure of the previous page), tools/fill_slash_chords.py (each
slash gets the pitches of the chord before it), tools/clean_score_noise.py (drops slurs, completes chord ties,
prunes invalid ties, ...), then tools/apply_instrument_changes.py when
<song dir>/context/instrument_changes.txt exists (printed timbre changes -> real instrument changes),
and tools/apply_ottava.py when <song dir>/context/ottava.txt exists (8va / 15ma / coll'8va);
tools/apply_capo.py writes <transpose> on the parts flagged ":capoN" in audiveris_hints.txt;
finally tools/unify_keys.py makes key changes score-wide (a part whose key differs from the
others is an OMR mistake).
"""
import copy
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))

REHEARSAL_RE = re.compile(r"^[A-H][0-9]?'?$")

# Note values in quarters -> (type, dots), longest first
VALUES = [(F(4), 'whole', 0), (F(7, 2), 'half', 2), (F(3), 'half', 1), (F(2), 'half', 0),
          (F(7, 4), 'quarter', 2), (F(3, 2), 'quarter', 1), (F(1), 'quarter', 0),
          (F(3, 4), 'eighth', 1), (F(1, 2), 'eighth', 0), (F(3, 8), '16th', 1),
          (F(1, 4), '16th', 0), (F(3, 16), '32nd', 1), (F(1, 8), '32nd', 0)]

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
            if m.find('note') is not None:
                continue
            new = []
            for st in range(1, staves + 1):
                if st > 1:
                    b = ET.Element('backup')
                    ET.SubElement(b, 'duration').text = str(int(bar * div))
                    new.append(b)
                n = make_rest(bar, div, str(1 + 4 * (st - 1)), str(st) if staves > 1 else None)
                n.find('rest').set('measure', 'yes')
                new.append(n)
            kids = list(m)
            idx = next((i for i, k in enumerate(kids)
                        if k.tag == 'barline' and k.get('location') == 'right'), len(kids))
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
    for v, evs in voices_of(m, div).items():
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


def prune_virtual_measures(root, report=None):
    """Remove spurious virtual measures (like '12+1') generated by Audiveris measure-repeat expansion
    when they are not present across all parts."""
    parts = root.findall('part')
    if not parts:
        return
    measure_sets = [set(m.get('number') for m in p.findall('measure')) for p in parts]
    common_numbers = set.intersection(*measure_sets)
    for p in parts:
        for m in list(p.findall('measure')):
            num = m.get('number', '')
            if '+' in num and num not in common_numbers:
                p.remove(m)


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
                              'extended',
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
        prune_virtual_measures(root, report)
        rehearsals_from_credits(root, mxl[:-4] + '.omr', report, page)
        repair_zero_divisions(root, report)
        fill_empty_measures(root, report)
        trim_and_pad(root, report, page)
        lyrics_to_words(root, report, page)
        scrub_paths(root)
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
    # review file lives in songs/ and is named after the input PDF (the '- pdf:' line of song_metadata.md);
    # a song from page images (no PDF) is named <id>_<title> from the '- Title:' line
    name = base
    meta_path = os.path.join(song_dir, 'context', 'song_metadata.md')
    if os.path.exists(meta_path):
        with open(meta_path, encoding='utf-8') as f:
            meta = f.read()
        m = re.search(r'^- pdf:\s*(.+?)\s*$', meta, re.M)
        t = re.search(r'^- Title:\s*(.+?)\s*(?:[（(].*)?$', meta, re.M)
        if m:
            name = os.path.splitext(m.group(1))[0]
        elif t:
            name = base.split('_')[0] + '_' + t.group(1)
    merged = os.path.join(os.path.dirname(os.path.abspath(song_dir)), re.sub(r'[/?:]', '_', name) + '.musicxml')
    shutil.move(os.path.join(tmp, base, f'{base}_merged.musicxml'), merged)
    shutil.rmtree(tmp)
    subprocess.run([sys.executable, os.path.join(HERE, 'fill_measure_repeats.py'), merged],
                   check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'fill_slash_chords.py'), merged],
                   check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'clean_score_noise.py'), merged],
                   check=True)
    hints = os.path.join(song_dir, 'context', 'instrument_changes.txt')
    if os.path.exists(hints):
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_instrument_changes.py'),
                        merged, hints], check=True)
    ottava = os.path.join(song_dir, 'context', 'ottava.txt')
    if os.path.exists(ottava):
        subprocess.run([sys.executable, os.path.join(HERE, 'apply_ottava.py'), merged, ottava],
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
        subprocess.run([sys.executable, song_fix, merged], check=True)
    # last, so that parts a song hook marked with <transpose> are left alone
    subprocess.run([sys.executable, os.path.join(HERE, 'unify_keys.py'), merged], check=True)
    # Report
    print(f'pages: {len(mxls)}  empty measures filled: {report["empty_filled"]}  zero divisions fixed: {report["zero_divisions"]}')
    for k in ('rehearsal', 'lyric_words', 'lyric_dropped', 'drop_dot', 'trim_gap', 'trim_rest', 'trim_note', 'padded', 'extended',
              'overflow_cut'):
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
