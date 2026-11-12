#!/usr/bin/env python3
"""Make "spot the difference" proof units: at most two staves over one printed system (about 4 measures).
Each unit is an image with that part of the original page on top and the same measures of the merged
MusicXML, rendered by MuseScore, below, plus a text listing of the MusicXML notes of those measures.
An agent proofreading the OMR only compares the two halves.  Consecutive parts share a unit up to
--max-staves staves (default 2: a grand staff alone, or two one-staff parts); a part is never split.

Usage (from skill/, with Pillow):
  python tools/proof_pairs.py <song dir> <merged.musicxml> <out dir> [--parts P1,P3] [--pages 5,6]
                              [--min-stack 300] [--max-staves 2]

Geometry comes from the Audiveris projects <song dir>/raw/<id>_pNN.omr: each system's measure stacks
(left/right x) and staff lines (y), drawn on the project's BINARY.png; book.xml says which part each
printed staff belongs to.  Stacks narrower than --min-stack pixels are courtesy key/clef space read as
a measure (the "phantom measures" a hook removes) and are skipped.  The remaining stacks are numbered
in order and must add up to the merged score's measure count; otherwise the run stops.

The MusicXML half: each part alone, the whole score rendered once with the printed system breaks, then
cut by system and each measure stretched to its printed width, so bar lines line up and measure repeats,
line-start clefs and keys come out as printed.

Out dir gets, per unit, pNN_sK_<part ids>.png and .txt (MusicXML notes: written pitch, i.e. 8va/15ma
lines taken off; hidden coll'8va doubles marked), and index.txt.  A part not printed in a system (empty
staves hidden) gets no image; index.txt lists it, flagged when the MusicXML has notes there.
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
        book = ET.fromstring(z.read('book.xml'))
        image = Image.open(z.open('sheet#1/BINARY.png')).convert('L')
    interline = int(sheet.find('scale/interline').get('main'))
    logical = [[int(p.get('logical-id')) for p in s.findall('part')] for s in book.iter('system')]
    systems = []
    for k, s in enumerate(sheet.iter('system')):
        stacks = [(int(st.get('left')), int(st.get('right'))) for st in s.findall('stack')]
        stacks = [st for st in stacks if st[1] - st[0] >= min_stack]
        parts = {}
        for j, p in enumerate(s.findall('part')):
            staves = []
            for st in p.findall('staff'):
                ys = [float(pt.get('y')) for ln in st.find('lines') for pt in ln.findall('point')]
                staves.append((min(ys), max(ys)))
            parts[logical[k][j]] = staves
        systems.append(dict(stacks=stacks, parts=parts))
    return image, interline, systems


def crop_original(image, interline, system, logical_id):
    """The part's staves on the original, from halfway to the staff above to halfway to the one below."""
    if logical_id not in system['parts']:
        return None
    mine = system['parts'][logical_id]
    others = [st for lid, staves in system['parts'].items() if lid != logical_id for st in staves]
    top = min(y for y, _ in mine)
    bottom = max(y for _, y in mine)
    above = [b for _, b in others if b < top]
    below = [t for t, _ in others if t > bottom]
    top = (top + max(above)) / 2 if above else top - 8 * interline
    bottom = (bottom + min(below)) / 2 if below else bottom + 5 * interline
    left = system['stacks'][0][0] - 4 * interline
    right = system['stacks'][-1][1] + interline
    box = (max(0, int(left)), max(0, int(top)), min(image.width, int(right)), min(image.height, int(bottom)))
    stacks = system['stacks']
    bounds = [stacks[0][0]] + [st[0] for st in stacks[1:]] + [stacks[-1][1]]
    return image.crop(box), [b - box[0] for b in bounds]


def stack(images):
    """Images of the same width one above the other (crops of adjacent staves tile)."""
    out = Image.new('L', (images[0].width, sum(im.height for im in images)), 255)
    y = 0
    for im in images:
        out.paste(im, (0, y))
        y += im.height
    return out


def has_notes(root, part_id, first, last):
    part = next(p for p in root.findall('part') if p.get('id') == part_id)
    return any(n.find('pitch') is not None for m in part.findall('measure')
               if first <= int(m.get('number')) <= last for n in m.findall('note'))


def group_score(root, part_ids):
    """The merged score with only part_ids, its system and page breaks kept (they are the printed
    ones), no part names, and pages large enough that nothing else breaks a line."""
    root = copy.deepcopy(root)
    for tag in ('credit', 'work', 'movement-title', 'identification'):
        for e in root.findall(tag):
            root.remove(e)
    pl = root.find('part-list')
    for sp in list(pl):
        if sp.tag == 'part-group' or (sp.tag == 'score-part' and sp.get('id') not in part_ids):
            pl.remove(sp)
    for sp in pl.findall('score-part'):
        for tag in ('part-name', 'part-abbreviation'):
            e = sp.find(tag)
            if e is not None:
                e.text = ''
                e.set('print-object', 'no')
    for p in root.findall('part'):
        if p.get('id') not in part_ids:
            root.remove(p)
    defaults = root.find('defaults')
    if defaults is not None and defaults.find('page-layout') is not None:
        pg = defaults.find('page-layout')
        pg.find('page-width').text = '2000'
        pg.find('page-height').text = '20000'
    for t in root.iter('time'):
        t.set('print-object', 'no')
    return root


def render_systems(xml_root, work):
    """Render the whole score once; return per printed system (in order) its image and bar lines."""
    src = os.path.join(work, 'x.musicxml')
    ET.ElementTree(xml_root).write(src, encoding='UTF-8', xml_declaration=True)
    mscore = env.load(('MUSESCORE_BIN',))['MUSESCORE_BIN']
    for f in os.listdir(work):
        if f.startswith('x-') and f.endswith('.png'):
            os.remove(os.path.join(work, f))
    subprocess.run([mscore, '-r', str(DPI), '-o', os.path.join(work, 'x.png'), src], check=True, capture_output=True)
    subprocess.run([mscore, '-o', os.path.join(work, 'x.mpos'), src], check=True, capture_output=True)
    pages = {}
    for f in os.listdir(work):
        if f.startswith('x-') and f.endswith('.png'):
            img = Image.open(os.path.join(work, f)).convert('RGBA')
            bg = Image.new('RGBA', img.size, 'white')
            pages[int(f[2:-4]) - 1] = Image.alpha_composite(bg, img).convert('L')
    scale = DPI / MPOS_DPI
    text = open(os.path.join(work, 'x.mpos'), encoding='utf-8').read()
    found = re.findall(r'<element id="\d+" x="([\d.]+)" y="([\d.]+)" sx="([\d.]+)" sy="([\d.]+)" page="(\d+)"', text)
    systems = []
    for x, y, w, h, page in found:
        x, y, w, h, page = float(x) * scale, float(y) * scale, float(w) * scale, float(h) * scale, int(page)
        if not systems or systems[-1]['page'] != page or abs(systems[-1]['y'] - y) > 1:
            systems.append(dict(page=page, y=y, h=h, bars=[]))
        systems[-1]['bars'].append((x, x + w))
    out = []
    for s in systems:
        img = pages[s['page']]
        left, right = s['bars'][0][0], s['bars'][-1][1]
        top, bottom = s['y'] - 0.5 * DPI, s['y'] + s['h'] + 0.3 * DPI
        box = (int(max(0, left - 0.4 * DPI)), int(max(0, top)), int(min(img.width, right + 10)), int(min(img.height, bottom)))
        crop = img.crop(box)
        inv = ImageOps.invert(crop).getbbox()
        if inv:  # trim blank rows only
            crop = crop.crop((0, max(0, inv[1] - 20), crop.width, min(crop.height, inv[3] + 20)))
        bounds = [b0 - box[0] for b0, _ in s['bars']] + [s['bars'][-1][1] - box[0]]
        out.append((crop, bounds))
    return out


def align(xml, xml_bounds, width, orig_bounds, height):
    """Stretch each measure of the rendering to the width it has on the original page, and the
    whole rendering to the height of the original crop."""
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
    ap.add_argument('--parts', help='part ids, e.g. P1,P3 (default: all)')
    ap.add_argument('--pages')
    ap.add_argument('--min-stack', type=int, default=300)
    ap.add_argument('--max-staves', type=int, default=2, help='staves per unit (default 2, a grand staff)')
    args = ap.parse_args()
    raw = os.path.join(args.song_dir, 'raw')
    omrs = sorted(f for f in os.listdir(raw) if f.endswith('.omr'))
    root = ET.parse(args.merged).getroot()
    names = {sp.get('id'): sp.findtext('part-name') for sp in root.find('part-list').findall('score-part')}
    ids = [p.get('id') for p in root.findall('part')]
    chosen = args.parts.split(',') if args.parts else ids
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
    groups = []  # consecutive parts, at most --max-staves staves per unit (a part never split)
    for part_id in chosen:
        part = next(p for p in root.findall('part') if p.get('id') == part_id)
        staves = int(next((m.findtext('attributes/staves') for m in part.findall('measure')
                           if m.findtext('attributes/staves')), '1'))
        if groups and groups[-1][1] + staves <= args.max_staves:
            groups[-1][0].append(part_id)
            groups[-1][1] += staves
        else:
            groups.append([[part_id], staves])
    with tempfile.TemporaryDirectory() as work:
        rendered = {}
        for part_id in chosen:
            rendered[part_id] = render_systems(group_score(root, [part_id]), work)
            if len(rendered[part_id]) != len(plan):
                sys.exit('%s: MuseScore laid out %d systems, the original has %d'
                         % (part_id, len(rendered[part_id]), len(plan)))
        for i, (page, k, first, last, image, interline, s) in enumerate(plan):
            if wanted and page not in wanted:
                continue
            for members, _ in groups:
                name = 'p%02d_s%d_%s' % (page, k, '-'.join(members))
                tops, bottoms, shown = [], [], []
                for part_id in members:
                    cropped = crop_original(image, interline, s, ids.index(part_id) + 1)
                    if cropped is None:
                        flag = '  OMR 有音符，原譜沒印這個聲部' if has_notes(root, part_id, first, last) else ''
                        index.append('%s\tm%d-%d\t%s\t原譜沒印%s' % (name, first, last, names[part_id], flag))
                        continue
                    orig, orig_bounds = cropped
                    xml, xml_bounds = rendered[part_id][i]
                    if len(xml_bounds) != len(orig_bounds):
                        sys.exit('%s %s: %d bars rendered, %d on the original'
                                 % (name, part_id, len(xml_bounds) - 1, len(orig_bounds) - 1))
                    tops.append(orig.convert('L'))
                    bottoms.append(align(xml, xml_bounds, orig.width, orig_bounds, orig.height))
                    shown.append(part_id)
                if not shown:
                    continue
                what = ' / '.join(names[p] for p in shown)
                top = label(stack(tops), '原譜 p%02d 第 %d 行  m%d–%d  %s' % (page, k, first, last, what))
                bottom = label(stack(bottoms), 'OMR  m%d–%d  %s' % (first, last, what))
                out = Image.new('L', (WIDTH, top.height + bottom.height + 12), 128)
                out.paste(top, (0, 0))
                out.paste(bottom, (0, top.height + 12))
                out.save(os.path.join(args.out_dir, name + '.png'), optimize=True)
                with open(os.path.join(args.out_dir, name + '.txt'), 'w', encoding='utf-8') as fh:
                    fh.write('# %s  m%d–%d  %s（音高為譜面書寫音高；beat 從 1 起算；×後面是時值，單位四分音符）\n'
                             % (name, first, last, what))
                    fh.write(listing(root, shown, names, first, last) + '\n')
                index.append('%s\tm%d-%d\t%s' % (name, first, last, what))
                print(name, 'm%d-%d' % (first, last))
    with open(os.path.join(args.out_dir, 'index.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(index) + '\n')


if __name__ == '__main__':
    main()
