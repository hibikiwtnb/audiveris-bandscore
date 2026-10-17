#!/usr/bin/env python3
"""Keep chord names and directions inside their measure.

    python3 tools/clamp_offsets.py <score.musicxml>

A <harmony> or <direction> stands at the time of the music before it plus its <offset>.  When a
note before it is shortened or rewritten after the OMR (a dot dropped to fix the measure length,
a song hook that rewrites a measure), the offset can point before the measure start: MuseScore then
draws the chord name left of the clef and the system layout breaks.  Such an offset is cut back to
the measure start; one past the measure end is cut back to the last division of the measure.
Run last, after every step that changes notes.  Prints what it moved.
"""
import sys
import xml.etree.ElementTree as ET

# where <offset> goes among the children (MusicXML order)
AFTER = {'harmony': ('root', 'function', 'kind', 'inversion', 'bass', 'degree', 'frame'),
         'direction': ('direction-type',)}


def measure_length(m):
    t = end = 0
    for e in m:
        d = e.findtext('duration')
        if e.tag == 'note' and e.find('chord') is None and e.find('grace') is None and d:
            t += int(d)
        elif e.tag == 'backup' and d:
            t -= int(d)
        elif e.tag == 'forward' and d:
            t += int(d)
        end = max(end, t)
    return end


def set_offset(e, value):
    o = e.find('offset')
    if value == 0:
        if o is not None:
            e.remove(o)
        return
    if o is None:
        o = ET.Element('offset')
        k = max([i for i, c in enumerate(e) if c.tag in AFTER[e.tag]] or [-1]) + 1
        e.insert(k, o)
    o.text = str(value)


def clamp(root):
    moved = []
    for p in root.findall('part'):
        for m in p.findall('measure'):
            length = measure_length(m)
            t = 0
            for e in m:
                d = e.findtext('duration')
                if e.tag == 'note' and e.find('chord') is None and e.find('grace') is None and d:
                    t += int(d)
                elif e.tag == 'backup' and d:
                    t -= int(d)
                elif e.tag == 'forward' and d:
                    t += int(d)
                elif e.tag in AFTER and e.findtext('offset'):
                    off = int(float(e.findtext('offset')))
                    at = t + off
                    if at < 0 or (length and at >= length):
                        new = min(max(at, 0), max(length - 1, 0)) - t
                        set_offset(e, new)
                        moved.append(f'{p.get("id")} m{m.get("number")} {e.tag}: offset {off} -> {new}')
    return moved


def main(path):
    tree = ET.parse(path)
    moved = clamp(tree.getroot())
    if moved:
        tree.write(path, encoding='UTF-8', xml_declaration=True)
    print(f'clamp_offsets: {len(moved)} moved back into their measure')
    for line in moved:
        print('   ', line)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
