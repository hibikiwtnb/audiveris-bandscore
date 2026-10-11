#!/usr/bin/env python3
"""Write <transpose> on the parts that the partsHint flags ":capoN" (a guitar with a capo on
fret N, written N semitones below what it sounds) or ":downN" (a guitar or bass tuned down N
semitones, written N semitones above what it sounds).  Idempotent.

Audiveris keeps the written key of such a part (it votes as a transposing instrument); this
step adds the <transpose> that makes it sound at concert pitch.  It must run before
unify_keys.py, which leaves the parts with <transpose> alone.

Usage: python tools/apply_capo.py <score.musicxml> <audiveris_hints.txt>
"""
import re
import sys
import xml.etree.ElementTree as ET

ATTR_ORDER = ["footnote", "level", "divisions", "key", "time", "staves", "part-symbol",
              "instruments", "clef", "staff-details", "transpose", "directive", "measure-style"]
# diatonic steps of N semitones up: minor 2nd, major 2nd, minor 3rd, major 3rd, 4th, ...
CAPO_STEPS = [0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6]
# diatonic steps of N semitones down, from the written note: augmented unison (A for A flat), ...
DOWN_STEPS = [0, 0, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6]


def read_capos(hints_path):
    """{main part name: capo fret, or minus the semitones tuned down} from the partsHint line."""
    capos = {}
    for line in open(hints_path, encoding='utf-8'):
        line = line.strip()
        if line.startswith('#') or 'partsHint=' not in line:
            continue
        for token in line.split('partsHint=', 1)[1].split(';'):
            fields = [f.strip() for f in token.split(':')]
            fret = next((int(f[4:]) for f in fields[1:] if re.fullmatch(r'(?i)capo\d+', f)), None)
            down = next((int(f[4:]) for f in fields[1:] if re.fullmatch(r'(?i)down\d+', f)), None)
            name = fields[0].split('|')[0].strip()
            if (fret is not None or down is not None) and name:
                if not 1 <= (fret or down) <= 11:
                    sys.exit(f'apply_capo: capo / down must be 1..11: {token.strip()}')
                capos[name] = fret if fret is not None else -down
    return capos


def main(score_path, hints_path):
    capos = read_capos(hints_path)
    if not capos:
        return
    tree = ET.parse(score_path)
    root = tree.getroot()
    names = {sp.get('id'): (sp.findtext('part-name') or '').strip() for sp in root.iter('score-part')}
    done, found = [], set()
    for part in root.findall('part'):
        name = names.get(part.get('id'))
        if name not in capos:
            continue
        found.add(name)
        fret = capos[name]
        first = part.find('measure')
        if first is None:
            continue
        for at in part.iter('attributes'):          # one <transpose>, in the first measure
            for old in at.findall('transpose'):
                at.remove(old)
        at = first.find('attributes')
        if at is None:
            at = ET.Element('attributes')
            idx = 1 if len(first) and first[0].tag == 'print' else 0
            first.insert(idx, at)
        tr = ET.SubElement(at, 'transpose')
        steps = CAPO_STEPS[fret] if fret > 0 else -DOWN_STEPS[-fret]
        ET.SubElement(tr, 'diatonic').text = str(steps)
        ET.SubElement(tr, 'chromatic').text = str(fret)
        ET.SubElement(tr, 'octave-change').text = '0'
        ch = sorted(list(at), key=lambda e: ATTR_ORDER.index(e.tag) if e.tag in ATTR_ORDER else len(ATTR_ORDER))
        for e in ch:
            at.remove(e)
        for e in ch:
            at.append(e)
        done.append(f'{part.get("id")} {name} ' + (f'capo {fret}' if fret > 0 else f'down {-fret}'))
    for name in capos:
        if name not in found:
            print(f'apply_capo: WARNING no part named "{name}" in the score')
    if done:
        tree.write(score_path, encoding='UTF-8', xml_declaration=True)
    print('apply_capo: ' + ('; '.join(done) or 'nothing changed'))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Usage: python tools/apply_capo.py <score.musicxml> <audiveris_hints.txt>')
    main(sys.argv[1], sys.argv[2])
