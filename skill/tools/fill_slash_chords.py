#!/usr/bin/env python3
"""Give the slashes of a merged score the pitches of the chord they repeat.

    python3 tools/fill_slash_chords.py <merged.musicxml>

A slash (<notehead>slash</notehead>, found by the book's slash template) means: the previous
chord again, with the slash rhythm.  Audiveris exports it with a placeholder pitch.  Here each
slash gets the pitches of the last chord before it (not a rest, not a slash) on the same staff
and voice, else on the same staff, across pages: one slash-headed note per chord pitch, with the
slash duration, ties and beams.  A slash with no chord before it is left as it is and listed.
"""
import copy
import sys
import xml.etree.ElementTree as ET


def is_slash(note):
    return note.findtext('notehead') == 'slash'


def groups(measure):
    """Chords of a measure, in order: lists of <note> (first one without <chord/>)."""
    out = []
    for el in measure.findall('note'):
        if el.find('chord') is not None and out:
            out[-1].append(el)
        else:
            out.append([el])
    return out


def fill(measure, slash, pitches):
    """Replace the slash notes (one chord) with one slash note per pitch."""
    first = slash[0]
    at = list(measure).index(first)
    for n in slash:
        measure.remove(n)
    for k, pitch in enumerate(pitches):
        n = copy.deepcopy(first)
        old = n.find('pitch')
        i = list(n).index(old)
        n.remove(old)
        n.insert(i, copy.deepcopy(pitch))
        for acc in n.findall('accidental'):
            n.remove(acc)
        if k > 0:
            n.insert(0, ET.Element('chord'))
            for b in n.findall('beam'):
                n.remove(b)
        measure.insert(at + k, n)


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    names = {sp.get('id'): sp.findtext('part-name') for sp in root.iter('score-part')}
    filled, missing = 0, []
    for part in root.findall('part'):
        last = {}  # (staff, voice) or staff -> pitches of the last chord
        for m in part.findall('measure'):
            for g in groups(m):
                first = g[0]
                if first.find('rest') is not None or first.find('pitch') is None:
                    continue
                staff = first.findtext('staff', '1')
                voice = first.findtext('voice', '1')
                if all(is_slash(n) for n in g):
                    pitches = last.get((staff, voice)) or last.get(staff)
                    if pitches is None:
                        missing.append(f"{names.get(part.get('id'))} m{m.get('number')}")
                        continue
                    fill(m, g, pitches)
                    filled += 1
                else:
                    pitches = [n.find('pitch') for n in g if not is_slash(n)]
                    last[(staff, voice)] = last[staff] = pitches
    tree.write(path, encoding='UTF-8', xml_declaration=True)
    print(f'slash chords filled: {filled}'
          + (f'; no chord before: {", ".join(missing)}' if missing else ''))


if __name__ == '__main__':
    main(sys.argv[1])
