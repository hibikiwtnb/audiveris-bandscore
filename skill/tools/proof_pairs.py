#!/usr/bin/env python3
"""Make "spot the difference" proof units: one printed system (about 4 measures) of the original page
on top, the same measures of the merged MusicXML rendered by MuseScore below, plus a text listing of
the MusicXML notes of those measures.  An agent proofreading the OMR only compares the two halves.

Usage (from skill/, with Pillow):
  python tools/proof_pairs.py <song dir> <merged.musicxml> <out dir> [--group piano|others|all]
                              [--pages 5,6] [--min-stack 300]

Geometry comes from the Audiveris projects <song dir>/raw/<id>_pNN.omr: each system's measure stacks
(left/right x) and staff lines (y), drawn on the project's BINARY.png.  Stacks narrower than
--min-stack pixels are courtesy key/clef space read as a measure (the "phantom measures" a hook
removes) and are skipped.  The remaining stacks are numbered in order and must add up to the merged
score's measure count; otherwise the run stops.

Groups: piano = the first part (grand staff), others = every part below it, all = the whole system.
The original crop takes the staves of the group; a system where the original prints fewer staves
(empty parts hidden) is cropped as printed.

Out dir gets, per unit, pNN_sK_<group>.png (original on top, MusicXML below) and .txt (MusicXML notes:
written pitch, i.e. 8va/15ma lines taken off; hidden coll'8va doubles marked), and index.txt.
"""
import argparse
import copy
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402

STEPS = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)
NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
WIDTH = 2000          # output width of both halves
DPI = 150             # MuseScore PNG resolution
MPOS_DPI = 4320       # .mpos coordinates per inch (360 dpi x 12)


def read_systems(omr, min_stack):
    with zipfile.ZipFile(omr) as z:
        sheet = ET.fromstring(z.read('sheet#1/sheet#1.xml'))
        image = Image.open(z.open('sheet#1/BINARY.png')).convert('L')
    interline = int(sheet.find('scale/interline').get('main'))
    systems = []
    for s in sheet.iter('system'):
        stacks = [(int(k.get('left')), int(k.get('right'))) for k in s.findall('stack')]
        stacks = [st for st in stacks if st[1] - st[0] >= min_stack]
        parts = []
        for p in s.findall('part'):
            staves = []
            for st in p.findall('staff'):
                ys = [float(pt.get('y')) for ln in st.find('lines') for pt in ln.findall('point')]
                staves.append((min(ys), max(ys)))
            parts.append(staves)
        systems.append(dict(stacks=stacks, parts=parts))
    return image, interline, systems


def crop_original(image, interline, system, group):
    parts = system['parts']
    chosen = parts[:1] if group == 'piano' else parts[1:] if group == 'others' else parts
    if not chosen:
        return None
    top = min(y for st in chosen for y, _ in st) - (9 if group != 'others' else 3) * interline
    bottom = max(y for st in chosen for _, y in st) + 4 * interline
    left = system['stacks'][0][0] - 4 * interline
    right = system['stacks'][-1][1] + interline
    box = (max(0, int(left)), max(0, int(top)), min(image.width, int(right)), min(image.height, int(bottom)))
    stacks = system['stacks']
    bounds = [stacks[0][0]] + [st[0] for st in stacks[1:]] + [stacks[-1][1]]
    return image.crop(box), [b - box[0] for b in bounds]


def attr_state(measures, upto):
    state = {}
    for m in measures[:upto]:
        a = m.find('attributes')
        if a is None:
            continue
        for tag in ('divisions', 'key', 'time', 'staves'):
            if a.find(tag) is not None:
                state[tag] = copy.deepcopy(a.find(tag))
        for c in a.findall('clef'):
            state['clef' + c.get('number', '1')] = copy.deepcopy(c)
    return state


def staff_content(measure, staff):
    """What one staff plays in a measure, for comparing with the measure before it."""
    out, cur, last = [], 0, 0
    for e in measure:
        if e.tag == 'backup':
            cur -= int(e.findtext('duration'))
        elif e.tag == 'forward':
            cur += int(e.findtext('duration'))
        elif e.tag == 'note':
            dur = int(e.findtext('duration', '0'))
            chord = e.find('chord') is not None
            on = last if chord else cur
            if e.findtext('staff', '1') == staff:
                pitch = e.find('pitch')
                out.append((on, dur, None if pitch is None else (pitch.findtext('step'), pitch.findtext('alter'),
                                                                   pitch.findtext('octave'))))
            if not chord and e.find('grace') is None:
                last = cur
                cur += dur
    return sorted(out, key=str)


def repeat_marks(measure):
    """[(type, staff or None)] of the measure-repeat marks of a measure."""
    out = []
    for ms in measure.iter('measure-style'):
        for r in ms.findall('measure-repeat'):
            out.append((r.get('type'), ms.get('number')))
    return out


def carry_repeats(ms, idx, staves):
    """A one-measure repeat (%) running into the excerpt lost its start mark, and MuseScore cannot
    draw % on the excerpt's first measure (nothing before it).  Give the excerpt's second measure a
    start mark on each staff where a repeat is running and the measure equals the one before."""
    if len(idx) < 2:
        return
    first, second = ms[idx[0]], ms[idx[1]]
    for staff in staves:
        active = False
        for m in ms[:idx[1] + 1]:
            for kind, num in repeat_marks(m):
                if num in (None, staff):
                    active = kind == 'start'
        if not active or staff_content(second, staff) != staff_content(first, staff):
            continue
        if any(k == 'start' and n in (None, staff) for k, n in repeat_marks(second)):
            continue
        a = second.find('attributes')
        if a is None:
            a = ET.Element('attributes')
            second.insert(0, a)
        style = ET.SubElement(a, 'measure-style', number=staff)
        ET.SubElement(style, 'measure-repeat', type='start', slashes='1').text = '1'


def excerpt(root, part_ids, first, last):
    """MusicXML with only part_ids and measures first..last, laid out as one line."""
    root = copy.deepcopy(root)
    for tag in ('credit', 'work', 'movement-title', 'identification'):
        for e in root.findall(tag):
            root.remove(e)
    pl = root.find('part-list')
    for sp in list(pl):
        if sp.tag == 'score-part' and sp.get('id') not in part_ids:
            pl.remove(sp)
        elif sp.tag == 'part-group':
            pl.remove(sp)
    defaults = root.find('defaults')
    if defaults is not None:
        pg = defaults.find('page-layout')
        if pg is not None:
            pg.find('page-width').text = str(1500 * (last - first + 1))
            pg.find('page-height').text = '6000'
    for sp in pl.findall('score-part'):
        for tag in ('part-name', 'part-abbreviation'):
            e = sp.find(tag)
            if e is not None:
                e.text = ''
                e.set('print-object', 'no')
    for p in root.findall('part'):
        if p.get('id') not in part_ids:
            root.remove(p)
            continue
        ms = p.findall('measure')
        idx = [i for i, m in enumerate(ms) if first <= int(m.get('number')) <= last]
        state = attr_state(ms, idx[0])
        nstaves = int(state['staves'].text) if 'staves' in state else 1
        carry_repeats(ms, idx, [str(i) for i in range(1, nstaves + 1)])
        for i, m in enumerate(ms):
            if i not in idx:
                p.remove(m)
        firstm = ms[idx[0]]
        a = firstm.find('attributes')
        if a is None:
            a = ET.Element('attributes')
            firstm.insert(0, a)
        order = ['divisions', 'key', 'time', 'staves']
        for tag in order:
            if a.find(tag) is None and tag in state:
                a.insert(order.index(tag), state[tag])
        for k, c in state.items():
            if k.startswith('clef') and not any(x.get('number', '1') == c.get('number', '1') for x in a.findall('clef')):
                a.append(c)
        if a.find('time') is not None:
            a.find('time').set('print-object', 'no')
        for m in p.findall('measure'):
            for pr in m.findall('print'):
                m.remove(pr)
    return root


def render(xml_root, work):
    """PNG of the excerpt cropped to its content, and the x of its bar lines in that crop."""
    src = os.path.join(work, 'x.musicxml')
    ET.ElementTree(xml_root).write(src, encoding='UTF-8', xml_declaration=True)
    mscore = env.load(('MUSESCORE_BIN',))['MUSESCORE_BIN']
    subprocess.run([mscore, '-r', str(DPI), '-o', os.path.join(work, 'x.png'), src], check=True, capture_output=True)
    subprocess.run([mscore, '-o', os.path.join(work, 'x.mpos'), src], check=True, capture_output=True)
    pages = sorted(f for f in os.listdir(work) if f.startswith('x-') and f.endswith('.png'))
    img = Image.open(os.path.join(work, pages[0])).convert('RGBA')
    bg = Image.new('RGBA', img.size, 'white')
    img = Image.alpha_composite(bg, img).convert('L')
    for f in pages:
        os.remove(os.path.join(work, f))
    text = open(os.path.join(work, 'x.mpos'), encoding='utf-8').read()
    ms = [(float(x), float(w)) for x, w in re.findall(r'<element id="\d+" x="([\d.]+)" y="[\d.]+" sx="([\d.]+)"', text)]
    scale = DPI / MPOS_DPI
    bounds = [x * scale for x, _ in ms] + [(ms[-1][0] + ms[-1][1]) * scale]
    box = ImageOps.invert(img).getbbox()
    box = (max(0, box[0] - 20), max(0, box[1] - 20), box[2] + 20, box[3] + 20)
    return img.crop(box), [b - box[0] for b in bounds]


def align(xml, xml_bounds, width, orig_bounds):
    """Stretch each measure of the rendering to the width it has on the original page."""
    k = (orig_bounds[-1] - orig_bounds[0]) / (xml_bounds[-1] - xml_bounds[0])
    height = max(1, round(xml.height * k))
    src = [0] + xml_bounds + [xml.width]
    dst = [0] + orig_bounds + [width]
    out = Image.new('L', (width, height), 255)
    for i in range(len(src) - 1):
        a, b, c, d = (round(v) for v in (src[i], src[i + 1], dst[i], dst[i + 1]))
        a, b = max(0, a), min(xml.width, b)
        c, d = max(0, c), min(width, d)
        if b - a < 1 or d - c < 1:
            continue
        out.paste(xml.crop((a, 0, b, xml.height)).resize((d - c, height)), (c, 0))
    return out


def label(img, text):
    img = img.resize((WIDTH, max(1, round(img.height * WIDTH / img.width))))
    bar = Image.new('L', (WIDTH, 44), 255)
    d = ImageDraw.Draw(bar)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 30)
    except OSError:
        font = ImageFont.load_default()
    d.text((10, 6), text, fill=0, font=font)
    out = Image.new('L', (WIDTH, img.height + 44), 255)
    out.paste(bar, (0, 0))
    out.paste(img, (0, 44))
    return out


def listing(root, part_ids, names, first, last):
    lines = []
    for p in root.findall('part'):
        if p.get('id') not in part_ids:
            continue
        ms = p.findall('measure')
        div = 1
        shift = {}  # staff -> semitones the 8va/15ma line adds
        lines.append('## ' + names[p.get('id')])
        for m in ms:
            num = int(m.get('number'))
            a = m.find('attributes')
            if a is not None and a.findtext('divisions'):
                div = int(a.findtext('divisions'))
            cur, last_on, events = 0, 0, {}
            for e in m:
                if e.tag == 'direction':
                    os_ = e.find('direction-type/octave-shift')
                    if os_ is not None:
                        st = e.findtext('staff', '1')
                        size = int(os_.get('size', '8'))
                        semis = 12 if size == 8 else 24
                        if os_.get('type') == 'down':
                            shift[st] = semis
                        elif os_.get('type') == 'up':
                            shift[st] = -semis
                        elif os_.get('type') == 'stop':
                            shift[st] = 0
                elif e.tag == 'backup':
                    cur -= int(e.findtext('duration'))
                elif e.tag == 'forward':
                    cur += int(e.findtext('duration'))
                elif e.tag == 'note':
                    dur = int(e.findtext('duration', '0'))
                    chord = e.find('chord') is not None
                    on = last_on if chord else cur
                    st = e.findtext('staff', '1')
                    if e.find('grace') is not None:
                        tok_dur = 'grace'
                    else:
                        tok_dur = '%g' % (dur / div)
                    pitch = e.find('pitch')
                    if pitch is None:
                        tok = 'rest'
                    else:
                        midi = 12 * (int(pitch.findtext('octave')) + 1) + STEPS[pitch.findtext('step')] + int(
                            float(pitch.findtext('alter', '0')))
                        midi -= shift.get(st, 0)
                        tok = NAMES[midi % 12] + str(midi // 12 - 1)
                        if e.get('print-object') == 'no':
                            tok += '(hidden)'
                        if any(t.get('type') == 'stop' for t in e.findall('tie')):
                            tok += '(tied from before)'
                    if e.get('print-object') == 'no' and pitch is None:
                        tok = 'hidden rest'
                    if num >= first and num <= last:
                        key = (st, e.findtext('voice', '1'))
                        events.setdefault(key, []).append('beat %g: %s ×%s' % (on / div + 1, tok, tok_dur))
                    if not chord and e.find('grace') is None:
                        last_on = cur
                        cur += dur
            if first <= num <= last:
                for (st, v), evs in sorted(events.items()):
                    lines.append('m%d staff %s voice %s: %s' % (num, st, v, '; '.join(evs)))
                if not events:
                    lines.append('m%d: (nothing)' % num)
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song_dir')
    ap.add_argument('merged')
    ap.add_argument('out_dir')
    ap.add_argument('--group', default='piano', choices=('piano', 'others', 'all'))
    ap.add_argument('--pages')
    ap.add_argument('--min-stack', type=int, default=300)
    args = ap.parse_args()
    raw = os.path.join(args.song_dir, 'raw')
    omrs = sorted(f for f in os.listdir(raw) if f.endswith('.omr'))
    root = ET.parse(args.merged).getroot()
    names = {sp.get('id'): sp.findtext('part-name') for sp in root.find('part-list').findall('score-part')}
    ids = [p.get('id') for p in root.findall('part')]
    group_ids = ids[:1] if args.group == 'piano' else ids[1:] if args.group == 'others' else ids
    total = len(root.find('part').findall('measure'))
    plan, n = [], 1
    for f in omrs:
        page = int(f.rsplit('_p', 1)[1][:2])
        image, interline, systems = read_systems(os.path.join(raw, f), args.min_stack)
        for k, s in enumerate(systems, 1):
            plan.append((page, k, n, n + len(s['stacks']) - 1, image, interline, s))
            n += len(s['stacks'])
    if n - 1 != total:
        sys.exit('stacks give %d measures, the merged score has %d: check --min-stack' % (n - 1, total))
    wanted = {int(x) for x in args.pages.split(',')} if args.pages else None
    os.makedirs(args.out_dir, exist_ok=True)
    index = []
    with tempfile.TemporaryDirectory() as work:
        for page, k, first, last, image, interline, s in plan:
            if wanted and page not in wanted:
                continue
            name = 'p%02d_s%d_%s' % (page, k, args.group)
            cropped = crop_original(image, interline, s, args.group)
            if cropped is None:
                continue
            orig, orig_bounds = cropped
            xml, xml_bounds = render(excerpt(root, group_ids, first, last), work)
            if len(xml_bounds) == len(orig_bounds):
                xml = align(xml, xml_bounds, orig.width, orig_bounds)
            top = label(orig.convert('L'), '原譜 p%02d 第 %d 行  m%d–%d' % (page, k, first, last))
            bottom = label(xml, 'OMR（MusicXML 經 MuseScore 渲染）  m%d–%d' % (first, last))
            out = Image.new('L', (WIDTH, top.height + bottom.height + 12), 128)
            out.paste(top, (0, 0))
            out.paste(bottom, (0, top.height + 12))
            out.save(os.path.join(args.out_dir, name + '.png'), optimize=True)
            with open(os.path.join(args.out_dir, name + '.txt'), 'w', encoding='utf-8') as fh:
                fh.write('# %s  m%d–%d（音高為譜面書寫音高；beat 從 1 起算；×後面是時值，單位四分音符）\n'
                         % (name, first, last))
                fh.write(listing(root, group_ids, names, first, last) + '\n')
            index.append('%s\tm%d-%d' % (name, first, last))
            print(name, 'm%d-%d' % (first, last))
    with open(os.path.join(args.out_dir, 'index.txt'), 'a', encoding='utf-8') as fh:
        fh.write('\n'.join(index) + '\n')


if __name__ == '__main__':
    main()
