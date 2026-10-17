#!/usr/bin/env python3
"""Turn printed timbre changes (text only in the OMR output) into real instrument changes.

    python3 tools/apply_instrument_changes.py <score.musicxml> <song dir>/context/instrument_changes.txt
    python3 tools/apply_instrument_changes.py --link-labels <score.musicxml> <hints>   (scores made before
        the labels carried their instrument: only add sound/midi-instrument to the labels)

Features a built-in General MIDI 1-128 instrument table, making the [timbres] section in hints optional.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

# Built-in General MIDI instrument catalog (1-128)
DEFAULT_TIMBRES = {
    # Pianos & Keyboards
    "Piano": (1, "Acoustic Grand Piano"),
    "Acoustic Piano": (1, "Acoustic Grand Piano"),
    "Grand Piano": (1, "Acoustic Grand Piano"),
    "A.Piano": (1, "Acoustic Grand Piano"),
    "Pf": (1, "Acoustic Grand Piano"),
    "Bright Piano": (2, "Bright Acoustic Piano"),
    "Electric Grand": (3, "Electric Grand Piano"),
    "Honky-tonk": (4, "Honky-tonk Piano"),
    "Electric Piano": (5, "Electric Piano 1"),
    "E.Piano": (5, "Electric Piano 1"),
    "EP": (5, "Electric Piano 1"),
    "Harpsichord": (7, "Harpsichord"),
    "Clavi": (8, "Clavinet"),
    "Celesta": (9, "Celesta"),
    "Bell": (9, "Celesta"),
    "Glocken": (10, "Glockenspiel"),
    "Glockenspiel": (10, "Glockenspiel"),
    "Music Box": (11, "Music Box"),
    "Vibes": (12, "Vibraphone"),
    "Vibraphone": (12, "Vibraphone"),
    "Marimba": (13, "Marimba"),
    "Xylophone": (14, "Xylophone"),
    "Tubular Bells": (15, "Tubular Bells"),

    # Organs & Accordions
    "Organ": (17, "Drawbar Organ"),
    "Drawbar Organ": (17, "Drawbar Organ"),
    "Percussive Organ": (18, "Percussive Organ"),
    "Rock Organ": (19, "Rock Organ"),
    "Church Organ": (20, "Church Organ"),
    "Reed Organ": (21, "Reed Organ"),
    "Accordion": (22, "Accordion"),
    "Harmonica": (23, "Harmonica"),

    # Guitars & Basses
    "Acoustic Guitar": (25, "Acoustic Guitar (nylon)"),
    "A.Guitar": (25, "Acoustic Guitar (steel)"),
    "Guitar": (26, "Acoustic Guitar (steel)"),
    "Electric Guitar": (28, "Electric Guitar (clean)"),
    "E.Guitar": (28, "Electric Guitar (clean)"),
    "Jazz Guitar": (27, "Electric Guitar (jazz)"),
    "Muted Guitar": (29, "Electric Guitar (muted)"),
    "Overdrive Guitar": (30, "Overdriven Guitar"),
    "Distortion Guitar": (31, "Distortion Guitar"),
    "Acoustic Bass": (33, "Acoustic Bass"),
    "Electric Bass": (34, "Electric Bass (finger)"),
    "E.Bass": (34, "Electric Bass (finger)"),
    "Pick Bass": (35, "Electric Bass (pick)"),
    "Fretless Bass": (36, "Fretless Bass"),
    "Slap Bass": (37, "Slap Bass 1"),
    "Synth Bass": (39, "Synth Bass 1"),
    "Syn.Bass": (39, "Synth Bass 1"),

    # Strings & Orchestral
    "Violin": (41, "Violin"),
    "Viola": (42, "Viola"),
    "Cello": (43, "Cello"),
    "Contrabass": (44, "Contrabass"),
    "Tremolo Strings": (45, "Tremolo Strings"),
    "Pizz": (46, "Pizzicato Strings"),
    "Pizzicato": (46, "Pizzicato Strings"),
    "Harp": (47, "Orchestral Harp"),
    "Orchestral Harp": (47, "Orchestral Harp"),
    "Timpani": (48, "Timpani"),
    "Strings": (49, "String Ensemble 1"),
    "String Ensemble": (49, "String Ensemble 1"),
    "Arco": (49, "String Ensemble 1"),
    "Slow Strings": (50, "String Ensemble 2"),
    "Synth Strings": (51, "Synth Strings 1"),
    "Syn.Strings": (51, "Synth Strings 1"),
    "Choir": (53, "Choir Aahs"),
    "Voice": (54, "Voice Oohs"),
    "Synth Choir": (55, "Synth Choir"),
    "Orchestra Hit": (56, "Orchestra Hit"),
    "Hit": (56, "Orchestra Hit"),

    # Brass & Winds
    "Trumpet": (57, "Trumpet"),
    "Trombone": (58, "Trombone"),
    "Tuba": (59, "Tuba"),
    "Muted Trumpet": (60, "Muted Trumpet"),
    "Horn": (61, "French Horn"),
    "French Horn": (61, "French Horn"),
    "Brass": (62, "Brass Section"),
    "Brass Section": (62, "Brass Section"),
    "Synth Brass": (63, "Synth Brass 1"),
    "Syn.Brass": (63, "Synth Brass 1"),
    "Soprano Sax": (65, "Soprano Sax"),
    "Alto Sax": (66, "Alto Sax"),
    "Tenor Sax": (67, "Tenor Sax"),
    "Baritone Sax": (68, "Baritone Sax"),
    "Oboe": (69, "Oboe"),
    "English Horn": (70, "English Horn"),
    "Bassoon": (71, "Bassoon"),
    "Clarinet": (72, "Clarinet"),
    "Piccolo": (73, "Piccolo"),
    "Flute": (74, "Flute"),
    "Woodwind": (74, "Flute"),
    "Recorder": (75, "Recorder"),
    "Pan Flute": (76, "Pan Flute"),
    "Whistle": (79, "Whistle"),
    "Synth Whistle": (79, "Whistle"),

    # Synths & FX
    "Synth": (81, "Lead 1 (square)"),
    "Square Lead": (81, "Lead 1 (square)"),
    "Lead": (82, "Lead 2 (sawtooth)"),
    "Synth Lead": (82, "Lead 2 (sawtooth)"),
    "Syn.Lead": (82, "Lead 2 (sawtooth)"),
    "Sawtooth": (82, "Lead 2 (sawtooth)"),
    "Analog Synth": (82, "Lead 2 (sawtooth)"),
    "Pluck": (88, "Lead 8 (bass+lead)"),
    "Synth Pluck": (88, "Lead 8 (bass+lead)"),
    "Syn.Pluck": (88, "Lead 8 (bass+lead)"),
    "Pad": (89, "Pad 1 (new age)"),
    "Synth Pad": (89, "Pad 1 (new age)"),
    "Syn.Pad": (89, "Pad 1 (new age)"),
    "Warm Pad": (90, "Pad 2 (warm)"),
    "Polysynth": (91, "Pad 3 (polysynth)"),
    "Sweep": (96, "Pad 8 (sweep)"),
    "Synth Sweep": (96, "Pad 8 (sweep)"),
    "Synth Bell": (99, "FX 3 (crystal)"),
    "Syn.Bell": (99, "FX 3 (crystal)"),
    "Crystal": (99, "FX 3 (crystal)"),

    # Percussion, FX & World
    "FX": (97, "FX 1 (rain)"),
    "Atmosphere": (100, "FX 4 (atmosphere)"),
    "Noise Sweep": (101, "FX 4 (atmosphere)"),
    "Sitar": (105, "Sitar"),
    "Banjo": (106, "Banjo"),
    "Koto": (108, "Koto"),
    "Steel Drums": (115, "Steel Drums"),
    "Suspended Cymbal": (120, "Reverse Cymbal"),
    "Reverse Cymbal": (120, "Reverse Cymbal"),
    "Noise Scratch": (121, "Guitar Fret Noise"),
}

LABEL_RE = re.compile(
    r"\b(pizz|arco|bell|15ma|8va|woodwind|flute|oboe|clarinet|bassoon|horn|trumpet|trombone|brass|"
    r"synth|strings|piano|organ|harp|pluck|glocken|celesta|pad|lead|hit|cymbal|choir|voice|marimba|"
    r"vibes|seq|arpegg|scratch|sweep|whistle)\b",
    re.I
)

NOTE_ORDER = ['grace', 'cue', 'chord', 'pitch', 'unpitched', 'rest', 'duration', 'tie',
              'instrument', 'voice', 'type', 'dot', 'accidental', 'time-modification', 'stem',
              'notehead', 'notehead-text', 'staff', 'beam', 'notations', 'lyric', 'play']
SHIFT_NUMBER = '2'
PART_LIST_ORDER = ['identification', 'part-link', 'part-name', 'part-name-display',
                   'part-abbreviation', 'part-abbreviation-display', 'group', 'score-instrument',
                   'player', 'midi-device', 'midi-instrument']


def read_hints(path):
    timbres = dict(DEFAULT_TIMBRES)
    defaults, changes, sec = {}, [], None
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith('['):
            sec = line.strip('[]').lower()
            continue
        f = [c.strip() for c in line.split('\t')]
        if sec == 'timbres':
            timbres[f[0]] = (int(f[1]), f[2] if len(f) > 2 else f[0])
        elif sec == 'defaults':
            defaults[f[0]] = f[1]
        elif sec == 'changes':
            if len(f) >= 7:  # coordinate mode: page, system, idx, part, label, timbre, octave
                changes.append(dict(page=int(f[0]), system=int(f[1]), idx=int(f[2]), part=f[3],
                                    label=f[4], timbre=f[5], octave=int(f[6])))
            elif len(f) >= 5:  # measure mode: measure, part, label, timbre, octave
                changes.append(dict(measure=f[0], part=f[1], label=f[2], timbre=f[3],
                                    octave=int(f[4])))
    return timbres, defaults, changes


def insert_ordered(parent, el, order):
    rank = order.index(el.tag) if el.tag in order else len(order)
    for i, c in enumerate(list(parent)):
        if c.tag in order and order.index(c.tag) > rank:
            parent.insert(i, el)
            return
    parent.append(el)


def systems(root):
    rows, pg, sy = {}, 1, 1
    for i, m in enumerate(root.find('part').findall('measure')):
        pr = m.find('print')
        if pr is not None and i > 0:
            if pr.get('new-page') == 'yes':
                pg, sy = pg + 1, 1
            elif pr.get('new-system') == 'yes':
                sy += 1
        rows.setdefault((pg, sy), []).append(m.get('number'))
    return rows


def pitched(m):
    return [n for n in m.iter('note') if n.find('pitch') is not None]


def shift_pitch(n, octaves):
    o = n.find('pitch/octave')
    if o is not None:
        o.text = str(int(o.text) + octaves)


def shift_dir(kind, size):
    d = ET.Element('direction', placement='above')
    ET.SubElement(ET.SubElement(d, 'direction-type'), 'octave-shift',
                  type=kind, size=str(size), number=SHIFT_NUMBER)
    return d


def restore_omr_shifts(ab, measures, octaves):
    out, active = [], None
    for m, octv in zip(measures, octaves):
        for el in list(m):
            osh = el.find('direction-type/octave-shift') if el.tag == 'direction' else None
            if osh is not None:
                if osh.get('type') in ('up', 'down') and octv > 0:
                    size = 2 if osh.get('size') == '15' else 1
                    active = size if osh.get('type') == 'down' else -size
                    m.remove(el)
                    out.append(f'{ab} m{m.get("number")}: removed OMR {osh.get("size")}va line '
                               f'inside labelled octave region')
                elif osh.get('type') == 'stop' and active is not None:
                    m.remove(el)
                    active = None
            elif el.tag == 'note' and active is not None and el.find('pitch') is not None:
                shift_pitch(el, -active)
    return out


def octave_lines(ab, measures, octaves):
    out, runs, cur = [], [], None
    for m, octv in zip(measures, octaves):
        if octv > 0 and pitched(m):
            if cur and cur[0] == octv:
                cur[1].append(m)
            else:
                cur = (octv, [m])
                runs.append(cur)
        else:
            cur = None
    for octv, ms in runs:
        for m in ms:
            for n in pitched(m):
                shift_pitch(n, octv)
        size = 8 if octv == 1 else 15
        first, last = ms[0], ms[-1]
        first.insert(list(first).index(pitched(first)[0]), shift_dir('down', size))
        nxt = measures.index(last) + 1
        if nxt < len(measures):
            m2 = measures[nxt]
            kids = list(m2)
            m2.insert(next((i for i, x in enumerate(kids) if x.tag not in ('print', 'attributes')),
                           len(kids)), shift_dir('stop', size))
        else:
            last.insert(list(last).index(pitched(last)[-1]) + 1, shift_dir('stop', size))
        out.append(f'{ab} m{first.get("number")}-m{last.get("number")}: {"8va" if size == 8 else "15ma"} line')
    return out


def resolve_part(name, part_map):
    if name in part_map:
        return part_map[name]
    for sp in part_map.values():
        if sp.findtext('part-abbreviation') == name or sp.findtext('part-name') == name:
            return sp
    return None


def main(score, hints):
    timbres, defaults, changes = read_hints(hints)
    tree = ET.parse(score)
    root = tree.getroot()
    if any(o.get('number') == SHIFT_NUMBER and o.get('type') == 'down' and o.get('default-y') is None
           for o in root.iter('octave-shift')):
        sys.exit('instrument changes already applied (octave lines present)')

    rows = systems(root)
    parts = {p.get('id'): p for p in root.findall('part')}
    part_map = {sp.get('id'): sp for sp in root.iter('score-part')}
    order = {m.get('number'): i for i, m in enumerate(root.find('part').findall('measure'))}

    # Resolve changes to measure numbers
    per_part = {}
    for c in changes:
        if 'measure' not in c:
            row = rows.get((c['page'], c['system']))
            if not row or c['idx'] > len(row):
                sys.exit(f'no measure for {c}')
            c['measure'] = row[c['idx'] - 1]
        per_part.setdefault(c['part'], []).append(c)

    # Drop misplaced OCR copies of the labels
    dropped = 0
    for part in parts.values():
        for m in part.findall('measure'):
            for d in list(m.findall('direction')):
                ws = [w.text or '' for w in d.iter('words')]
                if ws and all(LABEL_RE.search(w.strip()) for w in ws):
                    m.remove(d)
                    dropped += 1

    report = []
    warnings = []
    for key in sorted(set(per_part) | set(defaults)):
        sp = resolve_part(key, part_map)
        if sp is None:
            warnings.append(f'part {key!r} not found in score: its hint lines are ignored')
            continue
        pid = sp.get('id')
        part = parts[pid]
        cs = sorted(per_part.get(key, []), key=lambda c: order.get(c['measure'], 0))
        swaps = [c for c in cs if c['timbre'] != '-']
        first = defaults.get(key) or (swaps[0]['timbre'] if swaps else None)
        if first is None:
            continue
        used = list(dict.fromkeys([first] + [c['timbre'] for c in swaps]))

        # Update part-list instruments
        old_vol = sp.findtext('midi-instrument/volume') or '78'
        for e in sp.findall('score-instrument') + sp.findall('midi-instrument'):
            sp.remove(e)
        ids = {}
        for k, t in enumerate(used, 1):
            iid = f'{pid}-I{k}'
            ids[t] = iid
            if t not in timbres:
                warnings.append(f'{key}: unknown timbre {t!r} (not in built-in table or [timbres]): '
                                f'falls back to GM program 1')
            t_info = timbres.get(t, (1, t))
            si = ET.Element('score-instrument', id=iid)
            ET.SubElement(si, 'instrument-name').text = t_info[1].split('（')[0]
            insert_ordered(sp, si, PART_LIST_ORDER)
            mi = ET.Element('midi-instrument', id=iid)
            ET.SubElement(mi, 'midi-program').text = str(t_info[0])
            ET.SubElement(mi, 'volume').text = old_vol
            insert_ordered(sp, mi, PART_LIST_ORDER)

        # Timeline: instrument, labels, octave per measure
        timbre, octave, k = first, 0, 0
        measures = part.findall('measure')
        octaves = []
        for m in measures:
            while k < len(cs) and order.get(cs[k]['measure'], 0) <= order.get(m.get('number'), 0):
                c = cs[k]
                k += 1
                if c['label'] != '-':
                    d = ET.Element('direction', placement='above')
                    ET.SubElement(ET.SubElement(d, 'direction-type'), 'words').text = c['label']
                    if c['timbre'] != '-':
                        # The label is the printed mark of the change: our MuseScore import shows
                        # the instrument change with this text instead of an invisible name over it
                        ET.SubElement(ET.SubElement(d, 'sound'), 'midi-instrument', id=ids[c['timbre']])
                    kids = list(m)
                    idx = next((i for i, x in enumerate(kids)
                                if x.tag not in ('print', 'attributes', 'barline')), len(kids))
                    m.insert(idx, d)
                if c['timbre'] != '-':
                    if c['timbre'] != timbre:
                        report.append(f'{key} m{m.get("number")}: {timbre} -> {c["timbre"]}')
                    timbre, octave = c['timbre'], c['octave']
            octaves.append(octave)
            active_iid = ids.get(timbre, ids[first])
            for n in m.iter('note'):
                for e in n.findall('instrument'):
                    n.remove(e)
                insert_ordered(n, ET.Element('instrument', id=active_iid), NOTE_ORDER)

        report.extend(restore_omr_shifts(key, measures, octaves))
        report.extend(octave_lines(key, measures, octaves))
        report.append(f'{key}: {len(used)} timbres {used}')

    tree.write(score, encoding='UTF-8', xml_declaration=True)
    print(f'instrument changes: {len(changes)} hints, {dropped} misplaced label words dropped')
    for line in report:
        print('   ', line)
    for w in warnings:
        print('WARNING:', w)


def link_labels(score, hints):
    """Link the timbre labels of a score where the changes are already applied (made before the
    labels carried their instrument): add sound/midi-instrument to each label, nothing else."""
    timbres, _, changes = read_hints(hints)
    tree = ET.parse(score)
    root = tree.getroot()
    rows = systems(root)
    parts = {p.get('id'): p for p in root.findall('part')}
    part_map = {sp.get('id'): sp for sp in root.iter('score-part')}
    linked, missing = 0, []
    for c in changes:
        if c['label'] == '-' or c['timbre'] == '-':
            continue
        if 'measure' not in c:
            row = rows.get((c['page'], c['system']))
            if not row or c['idx'] > len(row):
                missing.append(f'{c}: no measure')
                continue
            c['measure'] = row[c['idx'] - 1]
        sp = resolve_part(c['part'], part_map)
        if sp is None:
            missing.append(f"{c['part']}: part not found")
            continue
        name = timbres.get(c['timbre'], (1, c['timbre']))[1].split('（')[0]
        iid = next((si.get('id') for si in sp.findall('score-instrument')
                    if si.findtext('instrument-name') == name), None)
        m = next((m for m in parts[sp.get('id')].findall('measure')
                  if m.get('number') == c['measure']), None)
        d = None if m is None else next(
            (d for d in m.findall('direction')
             if [w.text for w in d.iter('words')] == [c['label']]), None)
        if iid is None or d is None:
            missing.append(f"m{c['measure']} {c['part']} {c['label']!r}: "
                           + ('no instrument' if iid is None else 'no label'))
            continue
        if d.find('sound/midi-instrument') is None:
            snd = d.find('sound')
            if snd is None:
                snd = ET.SubElement(d, 'sound')
            ET.SubElement(snd, 'midi-instrument', id=iid)
            linked += 1
    tree.write(score, encoding='UTF-8', xml_declaration=True)
    print(f'instrument labels linked: {linked}')
    for line in missing:
        print('WARNING:', line)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--link-labels']
    if len(args) < 2:
        sys.exit('Usage: python tools/apply_instrument_changes.py [--link-labels] <score.musicxml> <hints.txt>')
    (link_labels if '--link-labels' in sys.argv else main)(args[0], args[1])
