#!/usr/bin/env python3
"""Print facts about a MusicXML score for an agent to read. No verdicts, always exit 0.

    python3 tools/score_quality.py <score.musicxml>

Output: a title line, then `key=value` lines of basic facts, then an `[issues]` section:
musical inconsistencies found in the XML (count, then positions). m17 = measure 17;
keys are the <fifths> values of the XML (3 = three sharps, -4 = four flats);
length_mismatch = a voice ends earlier or later than the time signature says;
length_mismatch_voices counts the voice-measures (each voice of each part in each measure) that
do, out of all of them: finer than the measure count, use it on the raw Audiveris pages
(raw/*.mxl, unzipped) to compare OMR settings, since the merged score is padded to length.
The last issues are lists to check against the printed score, not errors:
staff_lines_change = a staff changes its number of lines inside the score (a 5-line staff read
as a one-line staff); transposing_key_mismatch = a part with <transpose> whose key is not the
concert key moved by its transposition; out_of_range = notes outside the usual range of the
part's General MIDI program (approximate ranges, MuseScore marks such notes);
harmony_root_without_key_accidental = chord roots written natural on a letter that the key
signature alters (a flat or sharp the OCR may have dropped).
"""
import collections
import datetime
import os
import re
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction as F

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clean_score_noise as tie_rules  # same tie judgement as the cleanup step

# plain / dotted / double-dotted note values in quarters
STANDARD = {F(4, 2 ** k) * (2 - F(1, 2 ** d)) for k in range(0, 7) for d in range(3)}


STEP_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
# diatonic steps of an interval of N semitones (used when <transpose> has no <diatonic>)
STEPS_OF_SEMITONES = [0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6]
# Usual sounding range (MIDI numbers) of General MIDI programs, approximate. Programs that
# are not listed (synth leads and pads, effects...) have no range.
GM_RANGES = [
    (range(1, 9), 21, 108),      # pianos
    (range(9, 10), 60, 108),     # celesta
    (range(10, 11), 79, 108),    # glockenspiel
    (range(11, 12), 60, 84),     # music box
    (range(12, 13), 53, 89),     # vibraphone
    (range(13, 14), 45, 96),     # marimba
    (range(14, 15), 65, 108),    # xylophone
    (range(15, 16), 60, 77),     # tubular bells
    (range(17, 22), 36, 96),     # organs
    (range(25, 33), 40, 88),     # guitars
    (range(33, 41), 28, 67),     # basses
    (range(41, 42), 55, 103),    # violin
    (range(42, 43), 48, 91),     # viola
    (range(43, 44), 36, 76),     # cello
    (range(44, 45), 28, 67),     # contrabass
    (range(47, 48), 24, 103),    # harp
    (range(48, 49), 38, 57),     # timpani
    (range(49, 53), 28, 103),    # string ensembles
    (range(53, 56), 36, 84),     # choir, voice
    (range(57, 58), 54, 86),     # trumpet
    (range(58, 59), 40, 77),     # trombone
    (range(59, 60), 28, 58),     # tuba
    (range(61, 62), 34, 77),     # horn
    (range(62, 64), 36, 86),     # brass sections
    (range(65, 69), 44, 92),     # saxophones
    (range(69, 70), 58, 91),     # oboe
    (range(70, 71), 52, 81),     # english horn
    (range(71, 72), 34, 75),     # bassoon
    (range(72, 73), 50, 94),     # clarinet
    (range(73, 74), 74, 108),    # piccolo
    (range(74, 75), 59, 98),     # flute
]


def gm_range(program):
    for programs, low, high in GM_RANGES:
        if program in programs:
            return low, high
    return None


def midi_name(n):
    return f'{NOTE_NAMES[n % 12]}{n // 12 - 1}'


def altered_letters(fifths):
    """Letters that the key signature alters: -4 -> B E A D."""
    if not fifths:
        return set()
    return set('FCGDAEB'[:fifths]) if fifths > 0 else set('BEADGCF'[:-fifths])


def transposition_fifths(tr):
    """How many fifths the concert key is above the written key of a part with <transpose>."""
    chromatic = int(float(tr.findtext('chromatic', '0')))
    if tr.findtext('diatonic') is not None:
        diatonic = int(tr.findtext('diatonic'))
    else:
        sign = -1 if chromatic < 0 else 1
        diatonic = sign * (7 * (abs(chromatic) // 12) + STEPS_OF_SEMITONES[abs(chromatic) % 12])
    return 7 * chromatic - 12 * diatonic


def key_text(fifths):
    """The <fifths> value as written in the XML (3 = three sharps, -4 = four flats)."""
    return 'none' if fifths is None else fifths


def measures_text(numbers):
    """['3','4','5','8'] -> 'm3-m5 m8' (consecutive numbers become a range)."""
    runs = []
    for n in numbers:
        if runs and n.isdigit() and runs[-1][1].isdigit() and int(n) == int(runs[-1][1]) + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ' '.join(f'm{a}' if a == b else f'm{a}-m{b}' for a, b in runs)


def read_measures(part):
    """One dict of facts per measure of a part."""
    div, bar, key, out = 1, F(4), None, []
    for m in part.findall('measure'):
        a = m.find('attributes')
        time = None
        if a is not None:
            if a.findtext('divisions'):
                div = int(a.findtext('divisions'))
            t = a.find('time')
            if t is not None and t.findtext('beats'):
                bar = F(int(t.findtext('beats')) * 4, int(t.findtext('beat-type')))
                time = f'{t.findtext("beats")}/{t.findtext("beat-type")}'
            if a.find('key/fifths') is not None:
                key = a.findtext('key/fifths')
        d = dict(number=m.get('number'), key=key, time=time, notes=0, rests=0, whole_rest=False,
                 has_note=False, len_bad=False, value_bad=False,
                 new_page=m.find('print') is not None and m.find('print').get('new-page') == 'yes',
                 marks=[], endings=[], shifts=[], tempos=[],
                 segno=False, coda=False, dc=False, ds=False)
        cur, ends = F(0), {}
        for el in m:
            if el.tag == 'backup':
                cur -= F(int(el.findtext('duration')), div)
            elif el.tag == 'forward':
                cur += F(int(el.findtext('duration')), div)
            elif el.tag == 'barline':
                order = 0 if el.get('location') == 'left' else 1
                for r in el.findall('repeat'):
                    d['marks'].append((order, r.get('direction')))
                for e in el.findall('ending'):
                    d['endings'].append((e.get('number'), e.get('type')))
            elif el.tag == 'direction':
                st = el.findtext('staff', '1')
                for o in el.iter('octave-shift'):
                    d['shifts'].append((st, o.get('number', '1'), o.get('type')))
                d['segno'] |= el.find('.//segno') is not None
                d['coda'] |= el.find('.//coda') is not None
                for w in el.iter('words'):
                    d['ds'] |= (w.text or '').strip().upper() == 'D.S.'
                for s in el.iter('sound'):
                    d['dc'] |= s.get('dacapo') == 'yes'
                    d['ds'] |= s.get('dalsegno') is not None
                    if s.get('tempo'):
                        d['tempos'].append(s.get('tempo'))
            elif el.tag == 'note' and el.find('grace') is None:
                d['has_note'] = True
                rest = el.find('rest')
                chord = el.find('chord') is not None
                v = el.findtext('voice', '1')
                dur = F(int(el.findtext('duration') or 0), div)
                if rest is not None:
                    d['rests'] += 1
                    d['whole_rest'] |= rest.get('measure') == 'yes'
                else:
                    d['notes'] += 1
                if not chord:
                    measure_rest = rest is not None and rest.get('measure') == 'yes'
                    if not measure_rest and (el.find('type') is None or (
                            el.find('time-modification') is None and dur not in STANDARD)):
                        d['value_bad'] = True
                    cur += dur
                    ends[v] = max(ends.get(v, F(0)), cur)
        d['len_bad'] = m.get('implicit') != 'yes' and any(e != bar for e in ends.values())
        d['voices'] = len(ends)
        d['bad_voices'] = 0 if m.get('implicit') == 'yes' else sum(e != bar for e in ends.values())
        out.append(d)
    return out


def unpaired_octave_shifts(pm):
    n = 0
    for ms in pm.values():
        open_ = {}
        for d in ms:
            for st, num, typ in d['shifts']:
                if typ == 'stop':
                    n += 0 if open_.pop((st, num), False) else 1
                elif typ in ('up', 'down'):
                    n += 1 if open_.get((st, num)) else 0
                    open_[(st, num)] = True
        n += len(open_)
    return n


def unpaired_ties(root):
    """Ties with no partner, judged like the cleanup step: dangling in both the same-voice
    view and the same-staff view."""
    n = 0
    for part in root.findall('part'):
        by_voice = {(id(x), t) for x, t in tie_rules._dangling_ties(tie_rules._voice_chords(part), False)}
        by_staff = {(id(x), t) for x, t in tie_rules._dangling_ties(tie_rules._staff_chords(part), True)}
        n += len(by_voice & by_staff)
    return n


def endings_of(pm):
    """Endings as (number, first measure index, last measure index or None), all parts merged."""
    seen = set()
    for ms in pm.values():
        open_ = {}
        for i, d in enumerate(ms):
            for num, typ in d['endings']:
                if typ == 'start':
                    open_[num] = i
                elif num in open_:
                    seen.add((num, open_.pop(num), i))
        seen.update((num, i, None) for num, i in open_.items())
    return sorted(seen, key=lambda e: (e[1], e[0]))


def staff_line_changes(parts):
    """(part id, staff, measure number, lines before, lines after) where a staff changes its
    number of lines. A staff without <staff-lines> has 5 lines."""
    out = []
    for part in parts:
        lines = {}
        for m in part.findall('measure'):
            for sd in m.iter('staff-details'):
                if sd.findtext('staff-lines'):
                    st, n = sd.get('number', '1'), int(sd.findtext('staff-lines'))
                    first = st not in lines and m is part.find('measure')
                    before = lines.get(st, n if first else 5)
                    if n != before:
                        out.append((part.get('id'), st, m.get('number'), before, n))
                    lines[st] = n
    return out


def notes_out_of_range(root, parts):
    """Per (part, program): pitched notes outside the usual range of the program.
    A note uses its own <instrument> when the part has several, else the first of the part."""
    programs = {}
    for sp in root.iter('score-part'):
        for mi in sp.iter('midi-instrument'):
            if mi.findtext('midi-program'):
                programs[mi.get('id')] = int(mi.findtext('midi-program'))
    first = {sp.get('id'): next((programs[mi.get('id')] for mi in sp.iter('midi-instrument')
                                 if mi.get('id') in programs), None) for sp in root.iter('score-part')}
    stat = collections.OrderedDict()
    for part in parts:
        pid = part.get('id')
        for note in part.iter('note'):
            pitch = note.find('pitch')
            if pitch is None:
                continue
            inst = note.find('instrument')
            program = programs.get(inst.get('id')) if inst is not None else first.get(pid)
            if program is None or gm_range(program) is None:
                continue
            n = 12 * (int(pitch.findtext('octave')) + 1) + STEP_PC[pitch.findtext('step')] \
                + int(float(pitch.findtext('alter', '0')))
            low, high = gm_range(program)
            d = stat.setdefault((pid, program), dict(total=0, out=0, lo=n, hi=n))
            d['total'] += 1
            d['out'] += not low <= n <= high
            d['lo'], d['hi'] = min(d['lo'], n), max(d['hi'], n)
    return [(pid, program, d) for (pid, program), d in stat.items() if d['out']]


def roots_without_key_accidental(parts):
    """(measure number, root letter) of chord symbols whose root is natural on a letter that
    the key signature of the part alters."""
    out = []
    for part in parts:
        fifths = 0
        for m in part.findall('measure'):
            for el in m:
                if el.tag == 'attributes' and el.find('key/fifths') is not None:
                    fifths = int(el.findtext('key/fifths'))
                elif el.tag == 'harmony':
                    for root in el.findall('root'):
                        step = root.findtext('root-step')
                        if step in altered_letters(fifths) and not int(float(root.findtext('root-alter', '0'))):
                            out.append((m.get('number'), step))
    return out


def main(path):
    root = ET.parse(path).getroot()
    parts = root.findall('part')
    names = {sp.get('id'): sp.findtext('part-name') for sp in root.iter('score-part')}
    pids = [p.get('id') for p in parts]
    pm = {p.get('id'): read_measures(p) for p in parts}
    transposing = {p.get('id'): p.find('.//transpose') for p in parts}
    counts = {p: len(pm[p]) for p in pids}
    longest = max(pm.values(), key=len)
    numbers = [d['number'] for d in longest]
    N = len(longest)
    for p in pids:      # a shorter part is padded with blank measures that carry its last key
        while len(pm[p]) < N:
            last = pm[p][-1]['key'] if pm[p] else None
            pm[p].append(dict(number=None, key=last, time=None, notes=0, rests=0, whole_rest=False,
                              has_note=True, len_bad=False, value_bad=False, new_page=False,
                              marks=[], endings=[], shifts=[], tempos=[],
                              segno=False, coda=False, dc=False, ds=False))
    first = pm[pids[0]]
    out = []
    line = out.append

    def flagged(flag):
        """Measure numbers where any part has the flag set."""
        return [numbers[i] for i in range(N) if any(pm[p][i][flag] for p in pids)]

    st = os.stat(path)
    line('# MusicXML Quality Report')
    line('# m17 = measure 17 counted from the start of the whole score')
    line(f'file={os.path.basename(path)}')
    line(f'file_size_bytes={st.st_size}')
    line('modified=' + datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'))
    line(f'pages={1 + sum(d["new_page"] for d in first[1:])}')
    line(f'measures={N}')
    starts = [0] + [i for i, d in enumerate(first) if d['new_page'] and i] + [N]
    line('measures_per_page=' + ' '.join(str(b - a) for a, b in zip(starts, starts[1:])))
    line(f'parts={len(parts)}')
    times = [(d['number'], d['time']) for d in first if d['time']]
    line(f'time_signature={times[0][1] if times else "none"}')
    changes = [f'm{n}:{t}' for (n, t), prev in zip(times[1:], times) if t != prev[1]]
    if changes:
        line('time_signature_changes=' + ' '.join(changes))
    tempos = [f'm{d["number"]}:{t}' for d in first for t in d['tempos']]
    for t in tempos or ['none']:
        line(f'tempo={t}')
    line(f'notes={sum(d["notes"] for p in pids for d in pm[p])}')
    line(f'rests={sum(d["rests"] for p in pids for d in pm[p])}')
    line(f'empty_measures={sum(1 for p in pids for d in pm[p] if not d["has_note"])}')
    line('rehearsal_marks=' + (' '.join((r.text or '').strip() for r in parts[0].iter('rehearsal')) or 'none'))

    # repeat signs, endings, D.S. / D.C. / coda / segno
    signs = sorted({(i, order, direction) for p in pids for i, d in enumerate(pm[p])
                    for order, direction in d['marks']})
    line('repeat_signs=' + (' '.join(f'{direction}@m{numbers[i]}' for i, _, direction in signs) or 'none'))
    endings = endings_of(pm)
    line('endings=' + (' '.join(
        f'{num}@m{numbers[a]}' + ('-?' if b is None else f'-m{numbers[b]}' if b != a else '')
        for num, a, b in endings) or 'none'))
    for label, flag in (('segno', 'segno'), ('coda', 'coda'), ('D.S.', 'ds'), ('D.C.', 'dc')):
        pos = flagged(flag)
        line(f'{label}={len(pos)}' + (f' at={measures_text(pos)}' if pos else ''))

    # parts
    key_of = {p: [d['key'] for d in pm[p]] for p in pids}
    for p in pids:
        ms, fifths = pm[p], key_of[p]
        chg = [f'm{ms[i]["number"]}:{key_text(fifths[i])}' for i in range(1, N) if fifths[i] != fifths[i - 1]]
        tr = transposing[p]
        trans = 'no' if tr is None else \
            f'chromatic:{tr.findtext("chromatic", "0")},octave:{tr.findtext("octave-change", "0")}'
        line(f'part={p} name="{names.get(p) or ""}" notes={sum(d["notes"] for d in ms)} '
             f'whole_rest_measures={sum(d["whole_rest"] and d["notes"] == 0 for d in ms)} '
             f'key_at_start={key_text(fifths[0])} key_changes={" ".join(chg) or "none"} transposing={trans}')

    # issues
    line('[issues]')

    def issue(name, nums):
        line(f'{name} count={len(nums)}' + (f' at={measures_text(nums)}' if nums else ''))

    if len(set(counts.values())) > 1:
        line(f'measure_count_differs_between_parts count={len(set(counts.values()))} ' +
             ' '.join(f'{p}={counts[p]}' for p in pids))
    issue('length_mismatch_measures', [numbers[i] for i in range(N) if any(pm[p][i]['len_bad'] for p in pids)])
    line(f'length_mismatch_voices count={sum(d.get("bad_voices", 0) for p in pids for d in pm[p])}'
         f' of={sum(d.get("voices", 0) for p in pids for d in pm[p])}')
    issue('nonstandard_duration_measures', [numbers[i] for i in range(N) if any(pm[p][i]['value_bad'] for p in pids)])
    line(f'unpaired_ties count={unpaired_ties(root)}')
    line(f'unpaired_octave_shifts count={unpaired_octave_shifts(pm)}')

    percussion = {p.get('id') for p in parts
                  if p.find('.//clef/sign[.="percussion"]') is not None or p.find('.//unpitched') is not None}
    compared = [p for p in pids if transposing[p] is None and p not in percussion
                and any(k is not None for k in key_of[p])]
    excluded = [p for p in pids if p not in compared]
    bad = [i for i in range(N) if len({key_of[p][i] for p in compared}) > 1]
    line(f'key_mismatch_between_parts count={len(bad)} measures '
         f'(compared: {" ".join(compared)}' + (f'; excluded: {" ".join(excluded)}' if excluded else '') + ')')
    runs = []
    for i in bad:
        if runs and i == runs[-1][1] + 1 and all(key_of[p][i] == key_of[p][i - 1] for p in compared):
            runs[-1][1] = i
        else:
            runs.append([i, i])
    for a, b in runs:
        rng = f'm{numbers[a]}' if a == b else f'm{numbers[a]}-m{numbers[b]}'
        line(f'  at={rng} ' + ' '.join(f'{p}={key_text(key_of[p][a])}' for p in compared))

    def mark_set(p, i):
        d = pm[p][i]
        return '+'.join(sorted([direction for _, direction in d['marks']]
                               + [f'ending{n}_{t}' for n, t in d['endings']])) or 'none'
    differ = [i for i in range(N) if len({mark_set(p, i) for p in pids}) > 1]
    line(f'repeat_mismatch_between_parts count={len(differ)}' + (' measures' if differ else ''))
    for i in differ:
        groups = collections.defaultdict(list)
        for p in pids:
            groups[mark_set(p, i)].append(p)
        line(f'  at=m{numbers[i]} ' + ' '.join(f'{",".join(ps)}={ms}' for ms, ps in groups.items()))

    # a first backward repeat without forward means "repeat from the start": not reported
    unclosed, no_start, seen_backward, opened = [], [], False, None
    for i, _, direction in signs:
        if direction == 'forward':
            if opened is not None:
                unclosed.append(numbers[opened])
            opened = i
        elif opened is not None:
            opened, seen_backward = None, True
        else:
            if seen_backward:
                no_start.append(numbers[i])
            seen_backward = True
    if opened is not None:
        unclosed.append(numbers[opened])
    issue('repeat_forward_without_backward', unclosed)
    issue('repeat_backward_without_forward', no_start)
    issue('ending_not_closed', [numbers[a] for _, a, b in endings if b is None])

    backward_at = {i for i, _, direction in signs if direction == 'backward'}
    groups, cur = [], []            # endings that follow each other form one group
    for e in endings:
        if cur and e[1] > (cur[-1][2] if cur[-1][2] is not None else cur[-1][1]) + 1:
            groups.append(cur)
            cur = []
        cur.append(e)
    if cur:
        groups.append(cur)
    incomplete, first_open = [], []
    for g in groups:
        nums = {int(x) for e in g for x in re.findall(r'\d+', e[0])}
        if (1 in nums) != (2 in nums):
            incomplete.append(numbers[g[0][1]])
        for num, a, b in g:
            if '1' in re.findall(r'\d+', num) and b is not None and b not in backward_at:
                first_open.append(numbers[a])
    issue('ending_numbers_incomplete', incomplete)
    issue('first_ending_without_backward_repeat', first_open)

    # lists to check against the printed score
    changes = staff_line_changes(parts)
    line(f'staff_lines_change count={len(changes)}' + ''.join(
        f' {pid}/staff{st}@m{num}:{before}->{after}' for pid, st, num, before, after in changes))

    def concert_key(i):
        keys = [key_of[p][i] for p in compared if key_of[p][i] is not None]
        return int(collections.Counter(keys).most_common(1)[0][0]) if keys else None
    pitched = {p.get('id') for p in parts if p.find('.//pitch') is not None}
    wrong = []
    for p in pids:
        if transposing[p] is None or p not in pitched:
            continue
        shift = transposition_fifths(transposing[p])
        bad_at = [i for i in range(N) if key_of[p][i] is not None and concert_key(i) is not None
                  and int(key_of[p][i]) != concert_key(i) - shift]
        if bad_at:
            a = bad_at[0]
            wrong.append(f'  {p} "{names.get(p) or ""}" measures={len(bad_at)} first=m{numbers[a]} '
                         f'key={key_of[p][a]} expected={concert_key(a) - shift} '
                         f'(concert key {concert_key(a)})')
    line(f'transposing_key_mismatch count={len(wrong)}')
    out.extend(wrong)

    ranges = notes_out_of_range(root, parts)
    line(f'out_of_range count={sum(d["out"] for _, _, d in ranges)}')
    for pid, program, d in ranges:
        low, high = gm_range(program)
        line(f'  {pid} "{names.get(pid) or ""}" program={program} range={midi_name(low)}-{midi_name(high)} '
             f'outside={d["out"]}/{d["total"]} lowest={midi_name(d["lo"])} highest={midi_name(d["hi"])}')

    roots = roots_without_key_accidental(parts)
    line(f'harmony_root_without_key_accidental count={len(roots)}' +
         (' at=' + ' '.join(f'm{num}:{step}' for num, step in roots) if roots else ''))
    print('\n'.join(out))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python3 tools/score_quality.py <score.musicxml>')
    main(sys.argv[1])
