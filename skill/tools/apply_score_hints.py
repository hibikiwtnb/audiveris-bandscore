#!/usr/bin/env python3
"""Apply opening tempo, tempo changes, time signature and rehearsal marks from a song's
context/song_metadata.md.  Idempotent.

The md carries these lines (anywhere in the file, everything else is free text):
    - time: 4/4
    - tempo: 182 ca.                  (first measure: printed metronome + playable tempo)
    - tempo_changes: 194=120 195=80   (measure=bpm, playable only, nothing printed)
    - rehearsals: 2=A1 11=B1 19=C1    (measure=mark, boxed, on the first part)
Without any of these lines nothing is changed.

Usage: python tools/apply_score_hints.py <score.musicxml> <song_metadata.md>
"""
import re
import sys
import xml.etree.ElementTree as ET

ATTR_ORDER = ["footnote", "level", "divisions", "key", "time", "staves", "part-symbol",
              "instruments", "clef", "staff-details", "transpose", "directive", "measure-style"]
DIRECTION_ORDER = ["direction-type", "offset", "footnote", "level", "voice", "staff", "sound",
                   "listening"]


def reorder(el, order):
    ch = sorted(list(el), key=lambda e: order.index(e.tag) if e.tag in order else len(order))
    for e in ch:
        el.remove(e)
    for e in ch:
        el.append(e)


def read_hints(md_path):
    hints = {}
    for line in open(md_path, encoding='utf-8'):
        m = re.match(r'\s*[-*]\s*(time|tempo_changes|tempo|rehearsals)\s*[:：]\s*(.+?)\s*$', line)
        if m:
            hints[m.group(1)] = m.group(2)
    return hints


def pairs(text):
    return {int(k): v for k, v in (p.split('=', 1) for p in text.split())}


def insert_after_header(measure, el):
    idx = 0
    for i, ch in enumerate(list(measure)):
        if ch.tag in ('print', 'attributes'):
            idx = i + 1
        else:
            break
    measure.insert(idx, el)


def main(score_path, md_path):
    hints = read_hints(md_path)
    if not hints:
        return
    tree = ET.parse(score_path)
    root = tree.getroot()
    parts = root.findall('part')
    measures = {int(m.get('number')): m for m in parts[0].findall('measure')}
    done = []

    if 'time' in hints:
        beats, beat_type = hints['time'].split('/')
        for part in parts:
            m1 = part.find('measure')
            attr = m1.find('attributes')
            if attr is None:
                attr = ET.Element('attributes')
                m1.insert(0, attr)
            if attr.find('time') is None:
                t = ET.SubElement(attr, 'time')
                ET.SubElement(t, 'beats').text = beats
                ET.SubElement(t, 'beat-type').text = beat_type
                reorder(attr, ATTR_ORDER)
        done.append(f"time {hints['time']}")

    if 'rehearsals' in hints:
        for part in parts:          # drop OCR-made rehearsal marks everywhere first
            for m in part.findall('measure'):
                for d in m.findall('direction'):
                    if d.find('direction-type/rehearsal') is not None:
                        m.remove(d)
        marks = pairs(hints['rehearsals'])
        for n, text in sorted(marks.items()):
            if n not in measures:
                continue
            d = ET.Element('direction', placement='above')
            reh = ET.SubElement(ET.SubElement(d, 'direction-type'), 'rehearsal',
                                {'enclosure': 'square', 'font-weight': 'bold'})
            reh.text = text
            ET.SubElement(d, 'staff').text = '1'
            reorder(d, DIRECTION_ORDER)
            insert_after_header(measures[n], d)
        done.append(f'{len(marks)} rehearsal marks')

    if 'tempo' in hints:
        bpm, *ca = hints['tempo'].split()
        # OCR fragments of the printed tempo ("=168", "168 ca") left as text
        for part in parts:
            for m in part.findall('measure'):
                for d in m.findall('direction'):
                    if any(w.text and (f'={bpm}' in w.text or f'{bpm} ca' in w.text)
                           for w in d.findall('.//words')):
                        m.remove(d)
        m1 = measures[1]
        for d in m1.findall('direction'):
            if d.find('.//metronome') is not None:
                m1.remove(d)
        d = ET.Element('direction', placement='above')
        mm = ET.SubElement(ET.SubElement(d, 'direction-type'), 'metronome',
                           {'default-y': '48', 'relative-x': '-22'})
        ET.SubElement(mm, 'beat-unit').text = 'quarter'
        ET.SubElement(mm, 'per-minute').text = f'{bpm} ca.' if ca else bpm
        ET.SubElement(d, 'staff').text = '1'
        ET.SubElement(d, 'sound', {'tempo': bpm})
        reorder(d, DIRECTION_ORDER)
        insert_after_header(m1, d)
        done.append(f'tempo {bpm}')

    if 'tempo_changes' in hints:
        for n, bpm in sorted(pairs(hints['tempo_changes']).items()):
            m = measures.get(n)
            if m is None or any(d.find('sound') is not None for d in m.findall('direction')):
                continue
            d = ET.Element('direction', placement='above')
            ET.SubElement(ET.SubElement(d, 'direction-type'), 'words')  # DTD needs one; empty prints nothing
            ET.SubElement(d, 'staff').text = '1'
            ET.SubElement(d, 'sound', {'tempo': bpm})
            reorder(d, DIRECTION_ORDER)
            m.append(d)
        done.append('tempo changes')

    tree.write(score_path, encoding='UTF-8', xml_declaration=True)
    print('apply_score_hints:', ', '.join(done))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
