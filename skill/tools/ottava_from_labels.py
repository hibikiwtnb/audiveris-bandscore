#!/usr/bin/env python3
"""Draft context/ottava.txt for standalone printed 8va / 15ma / coll'8va lines.

    python3 tools/ottava_from_labels.py "<song dir>" [--part "A.pf"] > /tmp/ottava.txt

Runs tools/locate_labels.py and keeps every printed octave mark of each part/staff with its
page, system, staff, measure, beat and original text. A mark is only paired when its role is
explicit:

    * start      opening bracket / box corner, or a right arrow ("┌ 8va", "8va →");
    * stop       closing bracket / box corner, or an explicit end / stop / 止 word;
    * continue   left arrow, "cont" / 續, or a bare mark between a start and its stop;
    * single     one label that carries both an opening and a closing bracket, i.e. a local
                 span; its end is taken as the measure end and flagged for review;
    * reminder   a label ending with "." / "。" (e.g. 038 m126 "(8va)."); never starts a line.

A continuation never changes the octave state. A start is not paired with a mark of a
different kind. Anything ambiguous (bare hooks, reminders used as ends, nested starts, long
gaps) becomes a ``# check:`` line and produces no executable hint. Exact duplicate OCR rows
(same page, system, staff, measure, beat and text) are reported and dropped once. Labels
that carry an instrument name (e.g. "Glocken(8va)") belong in context/instrument_changes.txt
and are skipped here. The result is a DRAFT to review against the score; this tool never
writes into the song directory.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from apply_instrument_changes import DEFAULT_TIMBRES  # noqa: E402

MARK = re.compile(r"(15\s*ma|8\s*va|coll\s*'?\s*8va)", re.I)
CLEAN = re.compile(r"[\s\-—–~∼¬→←┌┐└┘↓|()（）\[\]［］<>'\"·.,:;=]+")
DIRS = {k.upper().replace('.', '').replace(' ', '') for k in DEFAULT_TIMBRES}
OPEN = set('(（[［┌└{｛')
CLOSE = set(')）]］┐┘}｝')
LONG_MEASURES = 40


def kind_of(text):
    if re.search(r'coll', text, re.I):
        return 'coll8va'
    return '15ma' if re.search(r'15\s*ma', text, re.I) else '8va'


def labelled(text):
    body = CLEAN.sub('', text).upper().replace('.', '').replace(' ', '')
    return any(d in body for d in DIRS)


MARK_BODY = re.compile(r"^(?:COLL)?(?:8VA|15MA)(?:8VA|15MA)?$")
SINGLE_TEXT = re.compile(r"[\[(（［]\s*(?:coll\s*'?\s*)?(?:8\s*va|15\s*ma)\s*[)\]）］][.。]?")


def mark_only(text):
    """The label is nothing but an octave mark (plus artwork removed by CLEAN)."""
    return bool(MARK_BODY.fullmatch(CLEAN.sub('', text).upper()))


def role_of(text):
    """Explicit role of one printed label, or 'unknown' when the hook / bracket is unclear."""
    if re.search(r'[.。]\s*$', text):
        return 'reminder'
    op = any(c in text for c in OPEN)
    cl = any(c in text for c in CLOSE)
    if op and cl:
        if SINGLE_TEXT.fullmatch(text.strip()):
            return 'single'
        return 'unknown'
    if not mark_only(text):
        return 'unknown'
    if op or '→' in text:
        return 'start'
    if cl or re.search(r'\bend\b|\bstop\b|止', text, re.I):
        return 'stop'
    if '←' in text or re.search(r'\bcont(inue)?\b|續', text, re.I):
        return 'continue'
    return 'unknown'


def rows(song_dir, part):
    cmd = [sys.executable, os.path.join(HERE, 'locate_labels.py'), song_dir, r"8va|15ma|coll"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True,
                         env=dict(os.environ, PYTHONIOENCODING='utf-8')).stdout
    for line in out.splitlines()[1:]:
        f = line.split('\t')
        if len(f) < 8 or (part and f[2] != part):
            continue
        if float(f[6]) < 250 or not MARK.search(f[7]) or labelled(f[7]):
            continue
        yield dict(page=f[0], system=f[1], part=f[2], staff=f[3], measure=f[4],
                   beat=f[5], x=float(f[6]), text=f[7])


def _where(r):
    return (f"p{r['page']} sys {r['system']} {r['part']} staff {r['staff']} "
            f"m{r['measure']} {r['text']!r}")


def _position(r):
    return 'end' if r['beat'] in ('', '?', 'end') else r['beat']


def _sort_key(r):
    try:
        page, system, measure = int(r['page']), int(r['system']), int(r['measure'])
    except (TypeError, ValueError):
        page, system, measure = 0, 0, 0
    beat = 99 if r['beat'] in ('end', '?', '') else float(r['beat'])
    return page, system, measure, beat, r['x']


def dedupe(rs):
    """Drop exact repeated OCR rows (same place and text); return (kept, checks)."""
    seen, kept, checks = set(), [], []
    for r in rs:
        key = (r['page'], r['system'], r['part'], r['staff'], r['measure'], r['beat'],
               r['text'])
        if key in seen:
            checks.append(f"{_where(r)}: duplicate OCR row dropped")
            continue
        seen.add(key)
        kept.append(r)
    return kept, checks


def plan(rs):
    """Pair one part/staff reading order. Returns (hints, checks).

    A hint is (part, staff, kind, measure1, position1, measure2, position2). Ambiguous
    marks only produce a check line, never an executable interval.
    """
    hints, checks = [], []
    i = 0
    while i < len(rs):
        a = rs[i]
        role = role_of(a['text'])
        if role == 'reminder':
            checks.append(f"{_where(a)}: reminder / hook, not a line start")
            i += 1
            continue
        if role == 'continue':
            checks.append(f"{_where(a)}: continuation without a known start, ignored")
            i += 1
            continue
        if role == 'unknown':
            checks.append(f"{_where(a)}: cannot tell start / stop / reminder, no hint")
            i += 1
            continue
        if role == 'stop':
            checks.append(f"{_where(a)}: stop without a known start, no hint")
            i += 1
            continue
        if role == 'single':
            kind = kind_of(a['text'])
            hints.append((a['part'], a['staff'], kind, a['measure'], _position(a),
                          a['measure'], 'end'))
            checks.append(f"{_where(a)}: single bracketed label, assumed local span to the "
                          f"measure end")
            i += 1
            continue
        # role == 'start'
        kind = kind_of(a['text'])
        j, paired, gap = i + 1, None, 0
        while j < len(rs):
            b = rs[j]
            brole = role_of(b['text'])
            if brole in ('reminder', 'continue'):
                if brole == 'continue':
                    checks.append(f"{_where(b)}: read as a continuation of {_where(a)}")
                else:
                    checks.append(f"{_where(b)}: reminder inside the span, state unchanged")
                j += 1
                continue
            if brole == 'single':
                checks.append(f"{_where(b)}: independent local span inside the open region")
                j += 1
                continue
            if brole == 'stop':
                if kind_of(b['text']) != kind:
                    checks.append(f"{_where(a)} -> {_where(b)}: stop of a different kind, "
                                  f"not paired")
                else:
                    paired = b
                break
            # another start / unknown: only an explicit stop can close the region
            checks.append(f"{_where(b)}: open or unclear mark before any stop, region "
                          f"from {_where(a)} not paired")
            break
        if paired is None:
            if j >= len(rs):
                checks.append(f"{_where(a)}: no explicit stop, no hint")
        else:
            try:
                gap = int(paired['measure']) - int(a['measure'])
            except (TypeError, ValueError):
                gap = 0
            if gap > LONG_MEASURES:
                checks.append(f"{_where(a)} -> {_where(paired)}: very long region "
                              f"({gap} measures), check the pairing")
            hints.append((a['part'], a['staff'], kind, a['measure'], _position(a),
                          paired['measure'], _position(paired)))
            i = j
        i += 1
    return hints, checks


def main(song_dir, part):
    groups, checks = {}, []
    for r in rows(song_dir, part):
        if r['measure'] == '?':
            checks.append(f"{_where(r)}: no measure")
            continue
        groups.setdefault((r['part'], r['staff']), []).append(r)
    print('# DRAFT generated by tools/ottava_from_labels.py; check every line against the score.')
    for (p, s), rs in groups.items():
        kept, dups = dedupe(sorted(rs, key=_sort_key))
        checks.extend(dups)
        hints, more = plan(kept)
        checks.extend(more)
        for h in hints:
            print('\t'.join(h))
    for c in checks:
        print(f'# check: {c}')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    part = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--part=')), '')
    if not args:
        sys.exit('Usage: tools/ottava_from_labels.py "<song dir>" [--part=ABBR]')
    main(args[0], part)
