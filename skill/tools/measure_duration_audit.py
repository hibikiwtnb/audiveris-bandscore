#!/usr/bin/env python3
"""Audit measure durations in Audiveris raw OMR output (.mxl), per (staff, voice).

Usage:
    python3 measure_duration_audit.py <song_dir> [<song_dir> ...]
    python3 measure_duration_audit.py --files a.mxl b.mxl ...

<song_dir> is a folder containing raw_omr/*.mxl.  Expected measure length is taken
from the last <time> seen in the part, 4/4 when none was ever seen.

Reports, for before/after comparison of an Audiveris change:
  - measures / voices whose summed duration != expected
  - how many of those are measure-rests (rest measure="yes") with a wrong duration
    (the "contamination" symptom: whole-measure rests inherit the longest voice
     of the stack when Audiveris does not know the time signature)
  - a rough cause classification for the remaining (real note) errors
"""
import collections
import glob
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F


def load(path):
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.endswith('.xml') and not n.startswith('META')][0]
    return ET.fromstring(z.read(name))


def audit(files):
    st = collections.Counter()
    cause = collections.Counter()
    tsigs = collections.Counter()
    for p in files:
        r = load(p)
        page_has_ts = False
        for part in r.findall('part'):
            div, exp = 1, F(4)
            for m in part.findall('measure'):
                a = m.find('attributes')
                if a is not None:
                    if a.find('divisions') is not None:
                        div = int(a.find('divisions').text)
                    t = a.find('time')
                    if t is not None and t.find('beats') is not None:
                        b, bt = t.findtext('beats'), t.findtext('beat-type')
                        tsigs[f'{b}/{bt}'] += 1
                        page_has_ts = True
                        exp = F(int(b)) * 4 / int(bt)
                vs = collections.defaultdict(list)
                for n in m.findall('note'):
                    if n.find('chord') is not None or n.find('grace') is not None:
                        continue
                    if n.find('duration') is None:
                        continue
                    vs[(n.findtext('staff', '1'), n.findtext('voice', '1'))].append(n)
                st['measures'] += 1
                mbad = False
                for ns in vs.values():
                    st['voices'] += 1
                    durs = [F(int(n.findtext('duration')), div) for n in ns]
                    dlt = sum(durs) - exp
                    if dlt == 0:
                        continue
                    mbad = True
                    st['bad_voices'] += 1
                    rest = ns[0].find('rest')
                    if len(ns) == 1 and rest is not None and rest.get('measure') == 'yes':
                        st['bad_measure_rests'] += 1
                        continue
                    dotted = [F(int(n.findtext('duration')), div) for n in ns if n.find('dot') is not None]
                    if dlt > 0 and any(x / 3 == dlt for x in dotted):
                        cause['extra dot (remove one dot fixes)'] += 1
                    elif dlt < 0 and any(x / 2 == -dlt for x in durs):
                        cause['missing dot (add one dot fixes)'] += 1
                    elif dlt > 0 and any(x / 2 == dlt for x in durs):
                        cause['one note too long x2 (missed flag/beam)'] += 1
                    elif dlt < 0 and any(x == -dlt for x in durs):
                        cause['one note too short /2 (extra flag/beam)'] += 1
                    elif any(n.find('time-modification') is not None for n in ns):
                        cause['tuplet involved'] += 1
                    else:
                        cause['other'] += 1
                st['bad_measures'] += mbad
        st['pages'] += 1
        st['pages_with_time_sig'] += page_has_ts
    return st, cause, tsigs


def main(argv):
    if argv and argv[0] == '--files':
        groups = [('files', argv[1:])]
    else:
        groups = [(d, sorted(glob.glob(os.path.join(d, 'raw_omr', '*.mxl')))) for d in argv]
    for label, files in groups:
        st, cause, tsigs = audit(files)
        bv = st['bad_voices'] or 1
        print(f'== {label}')
        print(f"  pages {st['pages']} (with time sig: {st['pages_with_time_sig']}), time sigs seen {dict(tsigs)}")
        print(f"  measures {st['measures']}, bad measures {st['bad_measures']}"
              f" ({100 * st['bad_measures'] // max(st['measures'], 1)}%)")
        print(f"  voices {st['voices']}, bad voices {st['bad_voices']}")
        print(f"    bad measure-rests (contamination) {st['bad_measure_rests']}"
              f" ({100 * st['bad_measure_rests'] // bv}%)")
        for k, c in cause.most_common():
            print(f'    {c:5d}  {k}')


if __name__ == '__main__':
    main(sys.argv[1:])
