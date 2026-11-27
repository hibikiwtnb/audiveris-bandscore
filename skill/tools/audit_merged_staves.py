#!/usr/bin/env python3
"""Report accompaniment staves that OMR dropped from a merged score.

Usage:
    python3 tools/audit_merged_staves.py songs/<name>.musicxml

A part with <staves>2</staves> (piano, organ, harp, ...) needs real notes on
every staff in every measure.  When OMR drops a whole staff, a RUN of measures
is left with rests only.  DTD validation and per-voice measure length still
pass, but MuseScore plays a silent accompaniment.  Single silent measures are
normal (pickup bars, rests), so only runs of two or more are reported.

Staves that are legitimately silent are not reported:

* a TAB staff of a guitar/bass part (its tablature may simply not be exported);
* a staff that has no pitched note at all for the whole part, which is how a
  deliberately dropped staff looks (same rule as fill_empty_measures).

Measure length is NOT checked here: score_quality.py already reports
length_mismatch, and a (staff, voice) check would also flag cross-staff voices
(one voice spread over the two staves of a grand staff) that are perfectly legal.

Prints one line per finding, then "issues: N".  Exits 1 when there is any.
A finding is a list of places to compare with the printed score, not a verdict.
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
        staves, tab, pitched_ever = 1, set(), set()
        silent = []
        for seq, m in enumerate(part.findall('measure'), 1):
            a = m.find('attributes')
            if a is not None:
                if a.find('staves') is not None:
                    staves = int(a.find('staves').text)
                for clef in a.findall('clef'):
                    if clef.findtext('sign') == 'TAB':
                        tab.add(int(clef.get('number', '1')))
            pitched = set()
            for n in m.findall('note'):
                if n.find('rest') is not None or n.find('chord') is not None:
                    continue
                if n.find('grace') is not None or n.find('pitch') is None:
                    continue
                staff = int(n.findtext('staff', '1'))
                pitched.add(staff)
                pitched_ever.add(staff)
            if staves > 1 and pitched:
                for st in range(1, staves + 1):
                    if st not in pitched:
                        silent.append((seq, st))

        for st in range(1, staves + 1):
            if st in tab or st not in pitched_ever:
                continue
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
