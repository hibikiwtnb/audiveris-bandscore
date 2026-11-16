#!/usr/bin/env python3
"""Make guitar and bass-guitar parts sound an octave below their written pitch.  Idempotent.

Guitar and bass-guitar notation is written an octave above the sounding pitch (the printed
TAB and the standard staff agree: low E is written E3 for guitar and E2 for bass, but sounds
E2 / E1).  MusicXML carries that octave with <transpose><octave-change>-1</transpose>, which
MuseScore applies to playback while keeping the written staff as printed.  This step adds the
missing octave to every guitar / bass-guitar part that has no octave transposition yet and
keeps an existing chromatic transposition (capo ":capoN", tuned down ":downN") untouched.

Synth basses, bassoons, trombones, tubas and the contrabass are not octave-transposed here:
their printed parts either sound as written or already carry their own <transpose>.

Usage: python tools/apply_tab_octave.py <score.musicxml> [more.musicxml ...]
"""
import re
import sys
import xml.etree.ElementTree as ET

ATTR_ORDER = ["footnote", "level", "divisions", "key", "time", "staves", "part-symbol",
              "instruments", "clef", "staff-details", "transpose", "directive", "measure-style"]


def is_octave_part(name):
    """True for guitar and bass-guitar part names (not synth bass or orchestral bass)."""
    n = re.sub(r'\s+', ' ', name.replace('.', ' ')).strip().lower()
    if n in ('guitar', 'electric guitar', 'acoustic guitar'):
        return True
    if n.startswith('e guitar') or n.startswith('a guitar'):
        return True
    return n in ('e bass', 'electric bass', 'bass guitar')


def part_names(root):
    """{part id: (part name, part abbreviation)}; a separate TAB part carries the guitar only
    in its abbreviation (e.g. "A.Guitar TAB")."""
    return {sp.get('id'): ((sp.findtext('part-name') or '').strip(),
                           (sp.findtext('part-abbreviation') or '').strip())
            for sp in root.iter('score-part')}


def first_attributes(part):
    first = part.find('measure')
    if first is None:
        return None
    at = first.find('attributes')
    if at is None:
        at = ET.Element('attributes')
        idx = 1 if len(first) and first[0].tag == 'print' else 0
        first.insert(idx, at)
    return at


def sort_attributes(at):
    ch = sorted(list(at), key=lambda e: ATTR_ORDER.index(e.tag) if e.tag in ATTR_ORDER
                else len(ATTR_ORDER))
    for e in ch:
        at.remove(e)
    for e in ch:
        at.append(e)


def add_octave(score_path):
    tree = ET.parse(score_path)
    root = tree.getroot()
    names = part_names(root)
    done = []
    for part in root.findall('part'):
        name, abbr = names.get(part.get('id'), ('', ''))
        if not (is_octave_part(name) or is_octave_part(abbr)):
            continue
        holder, tr = None, None
        for at in part.iter('attributes'):
            t = at.find('transpose')
            if t is not None:
                holder, tr = at, t
                break
        if tr is not None and int(tr.findtext('octave-change', '0') or 0) != 0:
            continue                        # already octave-transposed (guitar/bass or other)
        if tr is None:
            holder = first_attributes(part)
            if holder is None:
                continue
            tr = ET.SubElement(holder, 'transpose')
            ET.SubElement(tr, 'diatonic').text = '0'
            ET.SubElement(tr, 'chromatic').text = '0'
            ET.SubElement(tr, 'octave-change').text = '-1'
        else:
            oc = tr.find('octave-change')
            if oc is None:
                oc = ET.SubElement(tr, 'octave-change')
            oc.text = '-1'
        sort_attributes(holder)
        done.append(f'{part.get("id")} {name}')
    if done:
        tree.write(score_path, encoding='UTF-8', xml_declaration=True)
    print('apply_tab_octave: ' + ('; '.join(done) if done else 'nothing changed'))


def main(paths):
    for path in paths:
        add_octave(path)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('Usage: python tools/apply_tab_octave.py <score.musicxml> [more.musicxml ...]')
    main(sys.argv[1:])
