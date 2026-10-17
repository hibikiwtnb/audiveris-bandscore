#!/usr/bin/env python3
"""Deterministic lyric correction for the Vocal part of a merged MusicXML.

OMR reads the Vocal lyrics with many character errors, stray dashes and extra
lyric lines of symbol noise; the printed words can be restored from a reference
lyric sheet (a plain text file) without looking at the page image.  This tool
keeps that correction reviewable and repeatable, in the same spirit as the other
post-processing steps:

  * `show`  prints the vocal lyrics as one string per lyric number and measure,
            which is read straight against the reference sheet.
  * `dump`  writes a tab-separated cue sheet of every lyric slot in the vocal
            part -- measure, ordinal of the <note> in the measure, lyric number,
            the words currently there -- so a human (or an AI) fills in the last
            column by comparing with the reference.  `--include-empty` also lists
            pitched notes that carry no lyric, to fill clearly missing words.
  * `apply` reads the cue sheet back and writes the last column into the score.
            An empty value removes the lyric; a value on a slot that had none
            creates one.

The slot key is (measure number, ordinal of the <note> inside the measure,
lyric number), so a cue sheet can be re-applied after unrelated edits or after
clean_score_noise.py, as long as the notes of the vocal part stay where they are.

  * `blocks` segments the vocal melody into phrases (runs of pitched notes whose
            measures are at most `--gap` apart) and prints every slot -- pitch,
            whether it is the second half of a tie, and its current lyric or
            `(empty)` -- so the holes are visible before matching the reference.
  * `plan`  turns a lyric plan into a cue sheet.  Each plan line names a lyric
            number, a measure range and one token per slot in that range
            (text = set, `-`/`.` = remove, `=`/`*` = leave).  A line with the
            wrong token count is reported with its slot list instead of guessed.

Usage:
  fix_lyrics.py show   SCORE.musicxml [--part NAME]
  fix_lyrics.py blocks SCORE.musicxml [--part NAME] [-n 1,2] [--gap 1] [--from M --to M]
  fix_lyrics.py plan   SCORE.musicxml PLAN.txt [-o CUE.tsv] [--part NAME]
  fix_lyrics.py dump   SCORE.musicxml [-o CUE.tsv] [--part NAME] [-n N] [--include-empty]
  fix_lyrics.py apply  SCORE.musicxml CUE.tsv [-o OUT.musicxml]

Cue sheet column layout (tab separated, header line starts with "#"):

  measure  note  lyric  current  corrected

`measure` is the printed measure number, `note` the 0-based ordinal of the note
inside that measure, `lyric` the lyric number (1, 2, ...).  `current` is what the
score has now (for reference), `corrected` is written back by `apply`.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

VOCAL_RE = re.compile(r'^(vocal|vo\.?|voice|chorus|cho\.?|歌)\b', re.I)
LYRIC_AFTER = ('play', 'listen')


def find_part(root, name=None):
    parts = root.findall('part')
    if name:
        for p in parts:
            sp = next(s for s in root.iter('score-part') if s.get('id') == p.get('id'))
            if (sp.findtext('part-name') or '') == name:
                return p
        sys.exit(f'fix_lyrics: no part named {name!r}')
    for p in parts:
        sp = next(s for s in root.iter('score-part') if s.get('id') == p.get('id'))
        if VOCAL_RE.match((sp.findtext('part-name') or '').strip()):
            return p
    sys.exit('fix_lyrics: no vocal part; pass --part NAME')


def notes_of(measure):
    return measure.findall('note')


def lyric_slots(part, include_empty=False):
    """Yield (measure, note ordinal, lyric number, current text) in document order."""
    for measure in part.findall('measure'):
        for i, note in enumerate(notes_of(measure)):
            lyrics = note.findall('lyric')
            if lyrics:
                for ly in lyrics:
                    yield measure.get('number'), i, ly.get('number') or '1', ly.findtext('text') or ''
            elif include_empty and note.find('rest') is None:
                yield measure.get('number'), i, '1', ''


def dump(part, out, include_empty):
    lines = ['# measure\tnote\tlyric\tcurrent\tcorrected']
    for num, i, ln, text in lyric_slots(part, include_empty):
        lines.append(f'{num}\t{i}\t{ln}\t{text}\t{text}')
    out.write('\n'.join(lines) + '\n')


def show(part, out):
    for measure in part.findall('measure'):
        cells = {}
        for note in notes_of(measure):
            for ly in note.findall('lyric'):
                cells.setdefault(ly.get('number') or '1', []).append(ly.findtext('text') or '')
        if cells:
            row = ' | '.join(f'L{n}:{"".join(v)}' for n, v in sorted(cells.items()))
            out.write(f'm{measure.get("number")}\t{row}\n')


def pitch_name(note):
    p = note.find('pitch')
    if p is None:
        return 'rest'
    return (p.findtext('step') or '?') + (p.findtext('alter') or '') + (p.findtext('octave') or '')


def melody_slots(part, lyric_number, m_from=None, m_to=None):
    """Ordered pitched notes of one lyric number in [m_from, m_to].

    Every pitched note is a slot, even when it carries no lyric of that number,
    so the caller can see the holes.  Slots are ordered by their onset inside
    the measure (not by document order), so a measure notated in two voices
    reads left to right the way it is drawn: a lower voice's note that starts
    before the upper voice's is returned first.  Ties are folded into the
    reading order too ('stop' marks the second half of a held note).
    """
    slots = []
    for measure in part.findall('measure'):
        num = int(measure.get('number'))
        if m_from is not None and num < m_from:
            continue
        if m_to is not None and num > m_to:
            continue
        pos = 0
        note_index = -1
        local = []
        for ch in measure:
            if ch.tag == 'backup':
                pos -= int(ch.findtext('duration') or 0)
            elif ch.tag == 'forward':
                pos += int(ch.findtext('duration') or 0)
            elif ch.tag == 'note':
                note_index += 1
                dur = int(ch.findtext('duration') or 0)
                if ch.find('chord') is None and ch.find('rest') is None:
                    # a chord member shares the onset and the lyric of the note it
                    # is stacked on; only the first note of the chord is a slot
                    tie = ch.find('tie')
                    cur = ''
                    for ly in ch.findall('lyric'):
                        if (ly.get('number') or '1') == str(lyric_number):
                            cur = ly.findtext('text') or ''
                    local.append({'m': measure.get('number'), 'i': note_index, 'onset': pos,
                                  'tie': tie.get('type') if tie is not None else '',
                                  'pitch': pitch_name(ch), 'cur': cur})
                if ch.find('chord') is None:
                    pos += dur
        local.sort(key=lambda s: s['onset'])
        slots.extend(local)
    return slots


def slot_groups(slots, gap=1):
    """Split ordered slots into runs whose measures are at most `gap` apart."""
    groups, run, last = [], [], None
    for s in slots:
        num = int(s['m'])
        if last is not None and num > last + gap:
            groups.append(run)
            run = []
        run.append(s)
        last = num
    if run:
        groups.append(run)
    return groups


def fmt_slot(s):
    hold = '~' if s['tie'] else ''
    cur = s['cur'] if s['cur'] else ('(hold)' if s['tie'] else '(empty)')
    return f"m{s['m']}#{s['i']} {s['pitch']}{hold} {cur}"


def blocks(part, lyric_number, out, gap=1):
    for run in slot_groups(melody_slots(part, lyric_number), gap):
        holes = sum(1 for s in run if not s['cur'])
        out.write(f"== L{lyric_number} m{run[0]['m']}-{run[-1]['m']}  "
                  f"slots={len(run)} holes={holes}\n")
        out.write('   ' + '  '.join(fmt_slot(s) for s in run) + '\n')


def plan(part, plan_path, out):
    """Read a plan file and emit cue lines.

    Each line:  <lyric_number> <m_from> <m_to>\t token token token ...
    One token per pitched-notes slot in that range, in order:
      text  set the lyric,  -  or  .  remove it,  =  or  *  leave unchanged.
    A line whose token count does not match the slot count is reported and
    skipped, with the slot list printed so it can be fixed.
    """
    n = 0
    for raw in open(plan_path, encoding='utf-8'):
        if raw.startswith('#') or not raw.strip():
            continue
        head, _, tokpart = raw.rstrip('\n').partition('\t')
        try:
            lyric_number, m_from, m_to = head.split()
        except ValueError:
            out.write(f'!! bad plan line: {raw.rstrip()}\n')
            continue
        tokens = tokpart.split()
        slots = melody_slots(part, lyric_number, int(m_from), int(m_to))
        if len(tokens) != len(slots):
            out.write(f"!! L{lyric_number} m{m_from}-{m_to}: {len(tokens)} tokens "
                      f"for {len(slots)} slots\n   "
                      + '  '.join(fmt_slot(s) for s in slots) + '\n')
            continue
        for s, tok in zip(slots, tokens):
            if tok in ('=', '*'):
                continue
            tgt = '' if tok in ('.', '-') else tok
            if tgt == s['cur']:
                continue
            out.write(f"{s['m']}\t{s['i']}\t{lyric_number}\t{s['cur']}\t{tgt}\n")
            n += 1
    return n


def align_slots(mora, slots):
    """Align a reference mora sequence to melody slots by dynamic programming.

    Every slot is either left as it is (a tie hold `ー` or an empty/harmony
    note) or takes the next reference mora.  Assigning to a slot that already
    holds the same text is free, correcting a different text costs a little,
    filling an empty hole costs more, so the existing (roughly placed) words
    act as anchors.  When the melody has fewer notes than the reference (the
    OMR lost notes) the extra mora are dropped, and dropping is dearer than any
    placement, so it only happens when no slot is left.  Returns
    (cost, {slot index: text}, [dropped mora]).
    """
    N, L = len(slots), len(mora)
    INF = float('inf')
    DROP = 1000.0
    dp = [[INF] * (L + 1) for _ in range(N + 1)]
    back = [[None] * (L + 1) for _ in range(N + 1)]
    dp[0][0] = 0
    for i in range(N):
        ci = slots[i]['cur']
        skip = 0.0 if ci in ('', 'ー') else 1.0
        for j in range(L + 1):
            base = dp[i][j]
            if base == INF:
                continue
            if base + skip < dp[i + 1][j]:
                dp[i + 1][j] = base + skip
                back[i + 1][j] = ('skip', i)
            if j < L:
                cc = 0.0 if ci == mora[j] else (1.0 if ci == '' else 0.5)
                if base + cc < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = base + cc
                    back[i + 1][j + 1] = ('set', i, j)
                if base + DROP < dp[i][j + 1]:
                    dp[i][j + 1] = base + DROP
                    back[i][j + 1] = ('drop', j)
    best = L
    assigns, dropped = {}, []
    i, j = N, best
    while back[i][j] is not None:
        act = back[i][j]
        if act[0] == 'set':
            _, pi, pj = act
            assigns[pi] = mora[pj]
            i, j = pi, pj
        elif act[0] == 'drop':
            dropped.append(mora[act[1]])
            j = act[1]
        else:
            i = act[1]
    return dp[N][best], assigns, dropped


def align(part, plan_path, out):
    """Read a plan of reference mora and emit a cue sheet.

    Each line:  <lyric_number> <m_from> <m_to>\t mora mora mora ...
    The mora tokens are aligned to the melody slots of that range.
    """
    n = 0
    for raw in open(plan_path, encoding='utf-8'):
        if raw.startswith('#') or not raw.strip():
            continue
        head, _, tokpart = raw.rstrip('\n').partition('\t')
        lyric_number, m_from, m_to = head.split()
        mora = tokpart.split()
        slots = melody_slots(part, lyric_number, int(m_from), int(m_to))
        cost, assigns, dropped = align_slots(mora, slots)
        for i, s in enumerate(slots):
            cur = s['cur']
            if i in assigns:
                tgt = assigns[i]
            elif cur not in ('', 'ー'):
                tgt = ''            # leftover wrong text: clear the junk
            else:
                continue            # keep the tie hold / empty harmony note
            if tgt == cur:
                continue
            out.write(f"{s['m']}\t{s['i']}\t{lyric_number}\t{cur}\t{tgt}\n")
            n += 1
        if dropped:
            out.write(f'# L{lyric_number} m{m_from}-{m_to}: dropped {len(dropped)} mora '
                      f'({"".join(dropped)}) -- melody has fewer notes\n')
        if cost:
            out.write(f'# L{lyric_number} m{m_from}-{m_to}: cost {cost:g}, '
                      f'{len(mora)} mora on {len(slots)} slots\n')
    return n


def dump_json(part, out, numbers=None):
    """Machine-readable dump: every pitched note with pitch, tie, voice, duration
    and its lyrics, plus the resolved slots per lyric number."""
    import json
    numbers = numbers or ['1', '2', '3']
    meas_out = []
    for measure in part.findall('measure'):
        notes = []
        for i, note in enumerate(notes_of(measure)):
            entry = {'note': i, 'pitch': pitch_name(note),
                     'duration': note.findtext('duration'),
                     'voice': note.findtext('voice'),
                     'rest': note.find('rest') is not None}
            tie = note.find('tie')
            if tie is not None:
                entry['tie'] = tie.get('type')
            lyrics = {ly.get('number') or '1': ly.findtext('text') or ''
                      for ly in note.findall('lyric')}
            if lyrics:
                entry['lyric'] = lyrics
            notes.append(entry)
        meas_out.append({'measure': measure.get('number'), 'notes': notes})
    doc = {'measures': meas_out,
           'slots': {n: melody_slots(part, n) for n in numbers}}
    json.dump(doc, out, ensure_ascii=False, indent=1)
    out.write('\n')


def read_cue(path):
    """Return {(measure, note, lyric): corrected text} and the ordered key list."""
    edits = {}
    order = []
    with open(path, encoding='utf-8') as f:
        for raw in f:
            if raw.startswith('#') or not raw.strip():
                continue
            fields = raw.rstrip('\n').split('\t')
            if len(fields) < 5:
                continue
            measure, note, lyric, _current, corrected = fields[:5]
            key = (measure, note, lyric)
            edits[key] = corrected
            order.append(key)
    return edits, order


def insert_index(note):
    for i, ch in enumerate(note):
        if ch.tag in LYRIC_AFTER:
            return i
    return len(note)


def set_lyric(note, number, text):
    lyric = next((l for l in note.findall('lyric') if (l.get('number') or '1') == number), None)
    if text == '':
        if lyric is not None:
            note.remove(lyric)
        return 'removed' if lyric is not None else 'absent'
    if lyric is None:
        lyric = ET.Element('lyric', number=number, placement='below')
        ET.SubElement(lyric, 'syllabic').text = 'single'
        ET.SubElement(lyric, 'text')
        note.insert(insert_index(note), lyric)
        lyric.find('text').text = text
        return 'added'
    t = lyric.find('text')
    if t is None:
        t = ET.SubElement(lyric, 'text')
    old = t.text or ''
    t.text = text
    return 'changed' if old != text else 'same'


def apply(part, edits, order):
    seen = set()
    for num, i, ln, _text in lyric_slots(part, include_empty=True):
        key = (num, i, ln)
        if key in edits and key not in seen:
            seen.add(key)
    by_key = {}
    for measure in part.findall('measure'):
        notes = notes_of(measure)
        for i, note in enumerate(notes):
            by_key[(measure.get('number'), str(i))] = note
    counts = {'changed': 0, 'added': 0, 'removed': 0, 'same': 0, 'absent': 0, 'missing': 0}
    for key in order:
        measure, i, ln = key
        note = by_key.get((measure, i))
        if note is None:
            counts['missing'] += 1
            continue
        counts[set_lyric(note, ln, edits[key])] += 1
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_show = sub.add_parser('show', help='print vocal lyrics joined per number and measure')
    p_show.add_argument('score')
    p_show.add_argument('--part')

    p_dump = sub.add_parser('dump', help='write the cue sheet')
    p_dump.add_argument('score')
    p_dump.add_argument('-o', '--output')
    p_dump.add_argument('--part')
    p_dump.add_argument('-n', '--number', help='limit to one measure number')
    p_dump.add_argument('--include-empty', action='store_true', help='also list lyric-less pitched notes')
    p_dump.add_argument('--json', action='store_true', help='machine readable JSON of every note/slot')

    p_apply = sub.add_parser('apply', help='write the corrected column back')
    p_apply.add_argument('score')
    p_apply.add_argument('cue')
    p_apply.add_argument('-o', '--output')

    p_blocks = sub.add_parser('blocks', help='segment the vocal melody into phrases and show the holes')
    p_blocks.add_argument('score')
    p_blocks.add_argument('--part')
    p_blocks.add_argument('-n', '--lyric', default='1', help='lyric number (default 1)')
    p_blocks.add_argument('--gap', type=int, default=1, help='measures of rest that split a phrase')
    p_blocks.add_argument('--from', dest='m_from', type=int)
    p_blocks.add_argument('--to', dest='m_to', type=int)

    p_plan = sub.add_parser('plan', help='turn a lyric plan file into a cue sheet')
    p_plan.add_argument('score')
    p_plan.add_argument('plan')
    p_plan.add_argument('-o', '--output')
    p_plan.add_argument('--part')

    p_align = sub.add_parser('align', help='align reference mora to melody slots (DP) and emit a cue sheet')
    p_align.add_argument('score')
    p_align.add_argument('plan', help='lines of: "<lyric#> <m_from> <m_to><TAB>mora mora ..."')
    p_align.add_argument('-o', '--output')
    p_align.add_argument('--part')

    args = ap.parse_args()
    text = open(args.score, encoding='utf-8').read()
    doctype = re.search(r'<!DOCTYPE[^>]*>', text)
    root = ET.fromstring(text)

    if args.cmd == 'show':
        show(find_part(root, args.part), sys.stdout)
        return

    if args.cmd == 'blocks':
        part = find_part(root, args.part)
        for number in str(args.lyric).split(','):
            if args.m_from or args.m_to:
                for run in slot_groups(melody_slots(part, number, args.m_from, args.m_to), args.gap):
                    holes = sum(1 for s in run if not s['cur'])
                    print(f"== L{number} m{run[0]['m']}-{run[-1]['m']}  slots={len(run)} holes={holes}")
                    print('   ' + '  '.join(fmt_slot(s) for s in run))
            else:
                blocks(part, number, sys.stdout, args.gap)
        return

    if args.cmd == 'plan':
        part = find_part(root, args.part)
        out = open(args.output, 'w', encoding='utf-8') if args.output else sys.stdout
        n = plan(part, args.plan, out)
        if args.output:
            out.close()
            print(f'fix_lyrics: {n} edits written to {args.output}')
        return

    if args.cmd == 'align':
        part = find_part(root, args.part)
        out = open(args.output, 'w', encoding='utf-8') if args.output else sys.stdout
        n = align(part, args.plan, out)
        if args.output:
            out.close()
            print(f'fix_lyrics: {n} edits written to {args.output}')
        return

    if args.cmd == 'dump':
        part = find_part(root, args.part)
        if args.json:
            out = open(args.output, 'w', encoding='utf-8') if args.output else sys.stdout
            dump_json(part, out)
            if args.output:
                out.close()
                print(f'fix_lyrics: wrote {args.output}')
            return
        if args.number:
            part = ET.fromstring(ET.tostring(part))
            for m in list(part.findall('measure')):
                if m.get('number') != str(args.number):
                    part.remove(m)
        out = open(args.output, 'w', encoding='utf-8') if args.output else sys.stdout
        dump(part, out, args.include_empty)
        if args.output:
            out.close()
            print(f'fix_lyrics: wrote {args.output}')
        return

    part = find_part(root)
    edits, order = read_cue(args.cue)
    counts = apply(part, edits, order)
    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    dst = args.output or args.score
    with open(dst, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                + (doctype.group(0) + '\n' if doctype else '') + body + '\n')
    print('fix_lyrics: %s -- changed %d, added %d, removed %d, same %d, missing %d'
          % (dst, counts['changed'], counts['added'], counts['removed'], counts['same'], counts['missing']))


if __name__ == '__main__':
    main()
