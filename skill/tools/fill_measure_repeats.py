#!/usr/bin/env python3
"""Fill the measure repeats (%) left empty at the top of a page, in a merged score.

    python3 tools/fill_measure_repeats.py <merged.musicxml>

Audiveris writes a measure repeat as <measure-repeat type="start"> (the stop goes on the first
measure after the repeats) and copies the notes of the measure before it.  Pages are read one
by one, so the repeats at the top of a page have nothing before them on their page: they are
left with a measure rest.  Here such a measure gets the notes of the measure before it in the
merged score (the last one of the previous page), for every part.

A repeat run ends at its stop, or at the next page.  Only a measure with no sounding note is
filled; ties and lyrics are not copied.  Durations are converted to the divisions of the
filled measure (pages may differ); when one does not convert to a whole number (triplets copied
into a measure of fewer divisions), the filled measure gets the least common multiple of both
divisions (its offsets scaled) and the next measure goes back to its own.
"""
import copy
import math
import sys
import xml.etree.ElementTree as ET

MUSIC = ('note', 'backup', 'forward')


def sounding(measure):
    return any(n.find('rest') is None for n in measure.findall('note'))


def repeat_types(measure):
    return [r.get('type') for r in measure.iter('measure-repeat')]


def new_page(measure):
    return any(p.get('new-page') == 'yes' for p in measure.findall('print'))


def set_divisions(measure, div):
    """Give the measure its own <divisions> (first attributes, after any <print>)."""
    attrs = measure.find('attributes')
    if attrs is None:
        attrs = ET.Element('attributes')
        measure.insert(len([e for e in measure if e.tag == 'print']), attrs)
    d = attrs.find('divisions')
    if d is None:
        d = ET.Element('divisions')
        attrs.insert(0, d)
    d.text = str(div)


def fill(measure, next_measure, source, src_div, div):
    """Copy the music of source into measure; return the divisions now in force in measure."""
    for el in [e for e in measure if e.tag in MUSIC]:
        measure.remove(el)
    durations = [int(d.text) for el in source if el.tag in MUSIC for d in el.findall('duration')]
    if any(q * div % src_div for q in durations):
        new = div * src_div // math.gcd(div, src_div)
        for off in measure.iter('offset'):
            off.text = str(int(off.text) * new // div)
        set_divisions(measure, new)
        if next_measure is not None and next_measure.find('attributes/divisions') is None:
            set_divisions(next_measure, div)
        div = new
    copies = []
    for el in source:
        if el.tag not in MUSIC:
            continue
        c = copy.deepcopy(el)
        for parent in [c] + c.findall('notations'):
            for t in parent.findall('tie') + parent.findall('tied') + parent.findall('slur'):
                parent.remove(t)
        for ly in c.findall('lyric'):
            c.remove(ly)
        d = c.find('duration')
        if d is not None:
            d.text = str(int(d.text) * div // src_div)
        copies.append(c)
    # Before the right barline, if any
    at = len(measure)
    for i, el in enumerate(measure):
        if el.tag == 'barline' and el.get('location', 'right') == 'right':
            at = i
            break
    for k, c in enumerate(copies):
        measure.insert(at + k, c)
    return div


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    names = {sp.get('id'): sp.findtext('part-name') for sp in root.iter('score-part')}
    filled = []
    for part in root.findall('part'):
        measures = part.findall('measure')
        divs = []  # divisions in force in each measure
        for m in measures:
            d = m.find('attributes/divisions')
            divs.append(int(d.text) if d is not None else divs[-1] if divs else 1)
        in_run = False
        for i, m in enumerate(measures):
            types = repeat_types(m)
            if new_page(m) and 'start' not in types:
                in_run = False
            if 'start' in types:
                in_run = True
            if 'stop' in types:
                in_run = False
            if in_run and i > 0 and not sounding(m) and sounding(measures[i - 1]):
                divs[i] = fill(m, measures[i + 1] if i + 1 < len(measures) else None,
                               measures[i - 1], divs[i - 1], divs[i])
                filled.append(f"{names.get(part.get('id'))} m{m.get('number')}")
    tree.write(path, encoding='UTF-8', xml_declaration=True)
    print(f'measure repeats filled: {len(filled)}' + (f' ({", ".join(filled)})' if filled else ''))


if __name__ == '__main__':
    main(sys.argv[1])
