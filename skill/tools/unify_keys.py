#!/usr/bin/env python3
"""Make key signature changes score-wide in a merged MusicXML score (in place).

    python3 tools/unify_keys.py <score.musicxml>

A band changes key all together, so a part whose key differs from the others is an OMR mistake:
Audiveris reads each staff's key signature on its own and mid-system changes are often missed by
some staves (or a courtesy cancellation is read as a key). Parts with <transpose> (their written
key legitimately differs) and percussion are left alone: run this after anything that adds
<transpose>.

Rule, per measure where some part shows a key change to value v:
  * accept it when at least half of the compared parts change to v there, or when every other
    part's own next change is to v as well (they just missed it here, e.g. a mid-system change);
  * drop it otherwise (a lone change nobody else follows, e.g. a stray cancellation to 0).
The accepted changes form one timeline that is written into every compared part.
"""
import collections
import sys
import xml.etree.ElementTree as ET

ATTR_ORDER = ['footnote', 'level', 'divisions', 'key', 'time', 'staves', 'part-symbol',
              'instruments', 'clef', 'staff-details', 'transpose', 'directive', 'measure-style']


def key_events(part):
    """[(measure index, fifths)] where the key differs from the previous one."""
    events, prev = [], None
    for i, m in enumerate(part.findall('measure')):
        k = m.find('attributes/key/fifths')
        if k is not None and k.text != prev:
            events.append((i, k.text))
            prev = k.text
    return events


def unified_timeline(events, part_count):
    """Accepted changes [(measure index, fifths)] and a log of what was decided."""
    timeline, log, current = [], [], None
    for i in sorted({i for ev in events.values() for i, _ in ev}):
        candidates = collections.defaultdict(list)
        for p, ev in events.items():
            for j, v in ev:
                if j == i:
                    candidates[v].append(p)
        for v, ps in sorted(candidates.items(), key=lambda kv: -len(kv[1])):
            if v == current:
                continue
            majority = len(ps) * 2 >= part_count
            adopted = all(p in ps or next((x for j, x in events[p] if j > i), None) == v
                          for p in events)
            if majority or adopted:
                timeline.append((i, v))
                current = v
                log.append((i, v, ps, 'accepted' if majority else 'accepted (the others adopt it later)'))
                break
            log.append((i, v, ps, 'dropped (lone change, nobody follows)'))
    return timeline, log


def set_key(measure, fifths):
    """Put <key> in the attributes at the start of the measure, in DTD order."""
    attrs = None
    for el in measure:
        if el.tag == 'attributes':
            attrs = el
            break
        if el.tag in ('note', 'backup', 'forward'):
            break
    if attrs is None:
        attrs = ET.Element('attributes')
        pos = next((i for i, el in enumerate(measure) if el.tag not in ('print', 'barline')), len(measure))
        measure.insert(pos, attrs)
    key = ET.Element('key')
    ET.SubElement(key, 'fifths').text = fifths
    rank = ATTR_ORDER.index('key')
    pos = next((i for i, el in enumerate(attrs)
                if el.tag in ATTR_ORDER and ATTR_ORDER.index(el.tag) > rank), len(attrs))
    attrs.insert(pos, key)


def rewrite_part(part, timeline):
    """Replace all key elements of the part by the timeline."""
    measures = part.findall('measure')
    for m in measures:
        for attrs in m.findall('attributes'):
            for key in attrs.findall('key'):
                attrs.remove(key)
            if len(attrs) == 0:
                m.remove(attrs)
    for i, fifths in timeline:
        set_key(measures[i], fifths)


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    parts = root.findall('part')
    if len({len(p.findall('measure')) for p in parts}) > 1:
        print('unify_keys: parts have different measure counts, nothing done')
        return
    skipped = [p.get('id') for p in parts if p.find('.//transpose') is not None
               or p.find('.//clef/sign[.="percussion"]') is not None or p.find('.//unpitched') is not None]
    compared = [p for p in parts if p.get('id') not in skipped and key_events(p)]
    if len(compared) < 2:
        print('unify_keys: fewer than two parts with keys, nothing done')
        return
    events = {p.get('id'): key_events(p) for p in compared}
    timeline, log = unified_timeline(events, len(compared))
    numbers = [m.get('number') for m in parts[0].findall('measure')]
    changed = [p.get('id') for p in compared if events[p.get('id')] != timeline]
    for p in compared:
        if events[p.get('id')] != timeline:
            rewrite_part(p, timeline)
    print('unify_keys: compared ' + ' '.join(p.get('id') for p in compared)
          + (' (left alone: ' + ' '.join(skipped) + ')' if skipped else ''))
    print('  key timeline: ' + ' '.join(f'm{numbers[i]}:{v}' for i, v in timeline))
    for i, v, ps, what in log:
        if what != 'accepted':
            print(f'  m{numbers[i]} key {v} from {" ".join(ps)}: {what}')
    for (i, v), (j, _) in zip(timeline, timeline[1:]):
        if j == i + 1:
            print(f'  check: key {v} at m{numbers[i]} lasts a single measure')
    print('  parts changed: ' + (' '.join(changed) or 'none'))
    if changed:
        tree.write(path, encoding='UTF-8', xml_declaration=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python3 tools/unify_keys.py <score.musicxml>')
    main(sys.argv[1])
