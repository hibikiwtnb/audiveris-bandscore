#!/usr/bin/env python3
"""Report dropped accompaniment staves and bad voice lengths in a merged score.

Usage:
    python3 tools/audit_merged_staves.py songs/<name>.musicxml

A part with <staves>2</staves> (piano, organ, harp, ...) needs real notes on
every staff in every measure.  When OMR drops a whole staff, a RUN of measures
is left with rests only.  DTD validation and per-voice measure length still
pass, but MuseScore plays a silent accompaniment.  Single silent measures are
normal (pickup bars, rests), so only runs of two or more are reported.

It also checks the rhythm rule in DEVELOPMENT.md: every (staff, voice) of a
measure must add up to exactly the time signature, in divisions.

Prints one line per finding, then "issues: N".  Exits 1 when there is any.
A finding is a list of places to compare with the printed score, not a verdict:
a genuinely incomplete measure is reported as BAD_VOICE, and a silent run may be
exactly what the composer wrote.  <forward> is counted so a notated rest at the
start of a bar does not produce a false BAD_VOICE.
"""
import sys
import xml.etree.ElementTree as ET


def consecutive(seqs):
    out = []
    for s in seqs:
        if out and s == out[-1][-1] + 1:
            out[-1].append(s)
        else:
            out.append([s])
    return out


def findings(root):
    for part in root.findall('part'):
        pid = part.get('id', '?')
        divisions, beats, beat_type, staves = 1, 4, 4, 1
        silent = []
        for seq, m in enumerate(part.findall('measure'), 1):
            a = m.find('attributes')
            if a is not None:
                if a.find('divisions') is not None:
                    divisions = int(a.find('divisions').text)
                t = a.find('time')
                if t is not None and t.find('beats') is not None:
                    beats = int(t.findtext('beats'))
                    beat_type = int(t.findtext('beat-type'))
                if a.find('staves') is not None:
                    staves = int(a.find('staves').text)
            expected = divisions * beats * 4 // beat_type

            voice_len, pitched = {}, set()
            # Notes and <forward> both advance the cursor within a voice.
            for n in [c for c in m if c.tag in ('note', 'forward')]:
                staff = int(n.findtext('staff', '1'))
                voice = int(n.findtext('voice', '1'))
                if n.tag == 'note' and (n.find('chord') is not None
                                        or n.find('grace') is not None):
                    continue
                if n.find('duration') is None:
                    continue
                voice_len[(staff, voice)] = (
                    voice_len.get((staff, voice), 0)
                    + int(n.findtext('duration')))
                if n.tag == 'note' and n.find('pitch') is not None:
                    pitched.add(staff)

            for key, total in sorted(voice_len.items()):
                if total != expected:
                    yield (f'part={pid} measure={seq} staff={key[0]} '
                           f'voice={key[1]} BAD_VOICE {total} != {expected}')
            if staves > 1 and pitched:
                for st in range(1, staves + 1):
                    if st not in pitched:
                        silent.append((seq, st))

        for st in range(1, staves + 1):
            for run in consecutive([s for s, x in silent if x == st]):
                if len(run) >= 2:
                    yield (f'part={pid} staff={st} EMPTY_STAFF_RUN '
                           f'measures={run[0]}-{run[-1]} ({len(run)} bars, '
                           f'rests only)')


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    count = 0
    for line in findings(ET.parse(argv[0]).getroot()):
        print(line)
        count += 1
    print(f'issues: {count}')
    return 1 if count else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
