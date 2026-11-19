#!/usr/bin/env python3
"""Map every source measure stack (page unit, system, raw number) to the final measure.

    python3 tools/measure_map.py "<song dir>" [merged.musicxml] [--deleted=page:raw,...]

The merge renumbers the measures 1..N and later steps (virtual-measure pruning, verified
page-edge removal, a song hook) drop some of them.  bandscore_postprocess.py writes
`<song dir>/context/measure_map.tsv` with one row per source measure:

    page_unit  system  raw_measure  final_measure  status

A removed stack keeps its row with status `deleted` and no final measure.  Hints are
written in final measures; old raw-number hints can still be converted when the mapping
is unique.  A deleted, missing or ambiguous number is an error, never a guess.
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET

HEADER = 'page_unit\tsystem\traw_measure\tfinal_measure\tstatus\n'


def page_rows(pages):
    """[(page unit, root)] -> rows in merged order (final numbers still empty)."""
    rows = []
    for page, root in pages:
        part = root.find('part')
        if part is None:
            continue
        sy = 1
        for i, m in enumerate(part.findall('measure')):
            pr = m.find('print')
            if i and pr is not None and pr.get('new-system') == 'yes':
                sy += 1
            rows.append(dict(page=page, system=str(sy), raw=str(m.get('number')),
                             final=None, status='kept'))
    return rows


def build_map(pages, deleted=()):
    """Rows with final numbers; `deleted` = [(page unit, raw measure)] removed by later steps."""
    rows = page_rows(pages)
    for page, raw in deleted:
        idx = next((i for i, r in enumerate(rows) if r['page'] == page and r['raw'] == raw),
                   None)
        if idx is not None:
            rows[idx]['status'] = 'deleted'
            rows[idx]['final'] = None
            continue
        last = max((i for i, r in enumerate(rows) if r['page'] == page), default=None)
        rows.insert(len(rows) if last is None else last + 1,
                    dict(page=page, system=rows[last]['system'] if last is not None else '1',
                         raw=raw, final=None, status='deleted'))
    n = 0
    for r in rows:
        if r['status'] == 'kept':
            n += 1
            r['final'] = str(n)
    return rows


def write_map(path, rows):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(HEADER)
        for r in rows:
            f.write(f"{r['page']}\t{r['system']}\t{r['raw']}\t"
                    f"{r['final'] or '-'}\t{r['status']}\n")


def read_map(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#') or line.startswith('page_unit'):
                continue
            field = line.split('\t')
            if len(field) < 5:
                raise ValueError(f'{path}: malformed measure map row: {line!r}')
            rows.append(dict(page=field[0], system=field[1], raw=field[2],
                             final=None if field[3] in ('', '-') else field[3],
                             status=field[4]))
    return rows


def resolve_measure(num, rows, raw=False):
    """Final measure number for a hint coordinate.  Raises on deleted / missing / ambiguous.

    raw=False: a new hint, already in final measures.
    raw=True: an old hint in source (raw) measure numbers, converted through the map.
    """
    num = str(num)
    if raw:
        cand = [r for r in rows if r['raw'] == num]
        kept = [r for r in cand if r['status'] == 'kept' and r['final']]
        if len(kept) == 1:
            return kept[0]['final']
        if len(kept) > 1:
            raise ValueError(f'raw measure {num} is ambiguous ({len(kept)} rows)')
        if cand:
            r = cand[0]
            raise ValueError(f'raw measure {num} was deleted '
                             f'(page {r["page"]} system {r["system"]})')
        raise ValueError(f'raw measure {num} is not in the measure map')
    kept = [r for r in rows if r['status'] == 'kept' and r['final'] == num]
    if len(kept) == 1:
        return num
    deleted = [r for r in rows if r['status'] == 'deleted' and r['raw'] == num]
    if deleted:
        r = deleted[0]
        raise ValueError(f'measure {num} was deleted (page {r["page"]} system {r["system"]}); '
                         'hints must use final measures')
    raise ValueError(f'measure {num} is not in the measure map')


def parse_deleted(value):
    """`page:raw,page:raw` -> [(page, raw)]."""
    out = []
    for item in value.split(','):
        page, _, raw = item.partition(':')
        if page and raw:
            out.append((page, raw))
    return out


def main(song_dir, merged=None, deleted=()):
    pages = []
    for path in sorted(glob.glob(os.path.join(song_dir, 'pages', '*.musicxml'))):
        pages.append((os.path.basename(path)[:-8], ET.parse(path).getroot()))
    rows = build_map(pages, deleted)
    kept = sum(1 for r in rows if r['status'] == 'kept')
    if merged:
        merged_count = len(ET.parse(merged).getroot().find('part').findall('measure'))
        print(f'source measures: {len(rows)}  kept: {kept}  merged measures: {merged_count}',
              file=sys.stderr)
        if merged_count != kept:
            sys.exit('measure count differs; list the deleted stacks (--deleted page:raw,...)')
    sys.stdout.write(HEADER)
    for r in rows:
        sys.stdout.write(f"{r['page']}\t{r['system']}\t{r['raw']}\t"
                         f"{r['final'] or '-'}\t{r['status']}\n")


if __name__ == '__main__':
    deleted = []
    for a in sys.argv[1:]:
        if a.startswith('--deleted='):
            deleted = parse_deleted(a.split('=', 1)[1])
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    main(args[0], args[1] if len(args) > 1 else None, deleted)
