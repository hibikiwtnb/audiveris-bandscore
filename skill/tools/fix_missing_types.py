#!/usr/bin/env python3
"""Add missing <type> values to a merged MusicXML score.

    python3 tools/fix_missing_types.py <score.musicxml>            # report only
    python3 tools/fix_missing_types.py <score.musicxml> --write    # update the file

The rules are bandscore_postprocess.fix_missing_values: A1 (time-modification fixes the
written value), B (beam count fixes a short note and its tuplet), C (a long tail note is
split into a tied chain) and D (a rest is split into standard rests). Total durations do
not change. An incomplete six-tuplet (A2) is left for a rebuild and only listed.
"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bandscore_postprocess as bp  # noqa: E402


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    write = '--write' in argv
    paths = [a for a in argv if a != '--write']
    total = {'A1': 0, 'B': 0, 'C': 0, 'D': 0}
    for path in paths:
        root = ET.parse(path).getroot()
        report = {'type_fixed': [], 'type_skipped': []}
        stats = bp.fix_missing_values(root, report)
        for k in total:
            total[k] += stats.get(k, 0)
        print(f'== {os.path.basename(path)}')
        for line in report['type_fixed']:
            print(f'  fixed {line}')
        for line in report['type_skipped']:
            print(f'  skip  {line}')
        if write and report['type_fixed']:
            ET.ElementTree(root).write(path, encoding='UTF-8', xml_declaration=True)
            print(f'  written {path}')
    print('total ' + ' '.join(f'{k}={v}' for k, v in total.items()))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
