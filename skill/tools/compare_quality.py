#!/usr/bin/env python3
"""Compare two quality reports of the same song (before / after a rerun) and list what changed
in the structure of the score: pages, measures (per page), parts, staff lines, keys of each
part, transposition, rehearsal marks, repeats, endings.  Issue counts are listed when they
change.  Note counts are not compared (they move a little at every rerun).

    python3 tools/compare_quality.py <old_quality.txt> <new_quality.txt>
    python3 tools/compare_quality.py HEAD:songs/<song>/<id>_quality.txt songs/<song>/<id>_quality.txt

An argument written REV:path is read from git (git show).  Exit 1 when something of the
structure changed (to be checked against the printed score: a change is not always an
error), 0 otherwise.  A fact missing from the old report (written by an older
score_quality.py) is listed as "(new)" and does not count.
"""
import re
import subprocess
import sys

STRUCTURE = ['pages', 'measures', 'measures_per_page', 'parts', 'time_signature',
             'time_signature_changes', 'rehearsal_marks', 'repeat_signs', 'endings',
             'segno', 'coda', 'D.S.', 'D.C.']
STRUCTURE_ISSUES = ['staff_lines_change', 'transposing_key_mismatch',
                    'measure_count_differs_between_parts']
PART_FACTS = ['name', 'key_at_start', 'key_changes', 'transposing']


def read(arg):
    if re.match(r'^[^/\\]+:.+', arg) and not re.match(r'^[A-Za-z]:[/\\]', arg):
        text = subprocess.run(['git', 'show', arg], check=True, capture_output=True).stdout.decode('utf-8')
    else:
        text = open(arg, encoding='utf-8').read()
    facts, parts, issues, in_issues = {}, {}, {}, False
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        if line.strip() == '[issues]':
            in_issues = True
        elif in_issues:
            if line.startswith(' '):
                continue
            name, _, rest = line.partition(' ')
            issues[name] = rest.strip()
        elif line.startswith('part='):
            pid = line.split()[0][5:]
            d = {}
            for key in PART_FACTS:
                m = re.search(rf'\b{key}=("[^"]*"|.*?)(?= [a-z_]+=|$)', line)
                d[key] = m.group(1) if m else None
            parts[pid] = d
        elif '=' in line:
            key, _, value = line.partition('=')
            facts.setdefault(key, value)
    return facts, parts, issues


def count_of(text):
    m = re.search(r'count=(\d+)', text or '')
    return int(m.group(1)) if m else None


def main(old_arg, new_arg):
    of, op, oi = read(old_arg)
    nf, np_, ni = read(new_arg)
    changed, notes = [], []
    for key in STRUCTURE:
        if key not in of and key in nf:
            notes.append(f'{key}: (new) {nf[key]}')
        elif of.get(key) != nf.get(key):
            changed.append(f'{key}: {of.get(key)} -> {nf.get(key)}')
    same = {}                       # the same change on several parts is listed once
    for pid in sorted(set(op) | set(np_), key=lambda p: int(p[1:]) if p[1:].isdigit() else 0):
        if pid not in op or pid not in np_:
            changed.append(f'part {pid}: {"added" if pid in np_ else "removed"}')
            continue
        for key in PART_FACTS:
            if op[pid][key] != np_[pid][key]:
                same.setdefault((key, op[pid][key], np_[pid][key]), []).append(pid)
    for (key, old, new), pids in same.items():
        changed.append(f'part {",".join(pids)} {key}: {old} -> {new}')
    for name in sorted(set(oi) | set(ni)):
        if name not in oi:
            (changed if name in STRUCTURE_ISSUES and count_of(ni[name]) else notes).append(
                f'{name}: (new) {ni[name]}')
        elif oi.get(name) != ni.get(name):
            (changed if name in STRUCTURE_ISSUES else notes).append(
                f'{name}: {oi.get(name)} -> {ni.get(name)}')
    print(f'# {old_arg} -> {new_arg}')
    print(f'[structure] changed={len(changed)}')
    for line in changed:
        print('  ' + line)
    print(f'[other] changed={len(notes)}')
    for line in notes:
        print('  ' + line)
    sys.exit(1 if changed else 0)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
