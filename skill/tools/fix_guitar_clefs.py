#!/usr/bin/env python3
"""Revert a guitar staff that Audiveris read with a low clef back to treble (in place).

    python3 tools/fix_guitar_clefs.py <score.musicxml> [more.musicxml ...]

Guitar notation is always written in treble clef on the first staff (the TAB staff, when the
score prints one, is the second).  Audiveris sometimes reads one system or page of a guitar part
with a bass clef (F4, occasionally F3 or another low clef) although the printed clef does not
change.  Every note of that span then comes out a compound sixth too low (F2 / G2 instead of the
printed D4 / E4), which is where the out-of-range warnings come from.

For a guitar part whose first staff has a treble clef anywhere, each later clef on that staff
that is not treble is removed (the previous clef stays in force) and the notes it covers are
moved back by the same diatonic interval that the wrong clef took away: bass clef F4 is a
compound sixth (12 degrees, one octave plus a sixth), a baritone F3, alto C3 and so on are
computed from the clef's own line.  Accidentals are kept on the printed letter: an explicit
<accidental> keeps its alteration and applies to the same letter and octave for the rest of the
measure, every other note takes the alteration of the current key signature for its corrected
letter.  Notes on the TAB staff are not touched.

A guitar part with no treble clef at all (a separate TAB-only part) is left alone; such a part
is reported by score_quality.py as guitar_clef_misread.

Idempotent: after the fix no non-treble clef remains on the first staff.
"""
import sys
import xml.etree.ElementTree as ET

STEP_INDEX = {s: i for i, s in enumerate('CDEFGAB')}
STEPS = 'CDEFGAB'
# <fifths> sharp and flat letter orders
SHARP_ORDER = 'FCGDAEB'
FLAT_ORDER = 'BEADGCF'
# diatonic number (7 * octave + step index) of the reference pitch of each clef sign
CLEF_REFERENCE = {'G': 7 * 4 + STEP_INDEX['G'],   # G4
                  'F': 7 * 3 + STEP_INDEX['F'],   # F3
                  'C': 7 * 4 + STEP_INDEX['C']}   # C4
TREBLE_LINE_ONE = 7 * 4 + STEP_INDEX['E']         # E4 on the first line of a G2 staff


def is_guitar(name, abbreviation):
    """True for guitar part names, never for basses (E.Bass, Synth Bass, Bass Trombone)."""
    text = f'{name} {abbreviation}'.replace('.', ' ').lower()
    return 'guitar' in text and 'bass' not in text


def part_names(root):
    return {sp.get('id'): ((sp.findtext('part-name') or '').strip(),
                           (sp.findtext('part-abbreviation') or '').strip())
            for sp in root.iter('score-part')}


def key_alter(fifths, step):
    """Alteration the key signature gives a letter."""
    if not fifths:
        return 0
    if fifths > 0:
        return 1 if step in SHARP_ORDER[:fifths] else 0
    return -1 if step in FLAT_ORDER[:-fifths] else 0


def clef_offset(sign, line, octave_change=0):
    """Diatonic degrees to add to a note read with this clef to get the treble reading.

    The clef puts its reference pitch on <line>; a staff line step is a third (two degrees).
    A <clef-octave-change> moves the whole staff by that many octaves."""
    reference = CLEF_REFERENCE[sign] + 12 * octave_change
    line_one = reference - 2 * (line - 1)
    return TREBLE_LINE_ONE - line_one


def note_diatonic(pitch):
    return 7 * int(pitch.findtext('octave')) + STEP_INDEX[pitch.findtext('step')]


def set_pitch(pitch, diatonic, alter):
    step, octave = STEPS[diatonic % 7], diatonic // 7
    if octave < 0:
        return False
    pitch.find('step').text = step
    octave_el = pitch.find('octave')
    if octave_el is None:
        octave_el = ET.SubElement(pitch, 'octave')
    octave_el.text = str(octave)
    alter_el = pitch.find('alter')
    if alter:
        if alter_el is None:
            alter_el = ET.Element('alter')
            steps = list(pitch)
            pitch.insert(steps.index(pitch.find('step')) + 1, alter_el)
        alter_el.text = str(alter)
    elif alter_el is not None:
        pitch.remove(alter_el)
    return True


def staff_of(note):
    return note.findtext('staff') or '1'


def treble_parts(root):
    """Part ids of guitar parts whose first staff uses a treble clef somewhere, with names."""
    names = part_names(root)
    out = {}
    for part in root.findall('part'):
        name, abbr = names.get(part.get('id'), ('', ''))
        if not is_guitar(name, abbr):
            continue
        treble = any(c.findtext('sign') == 'G' and c.findtext('line') == '2'
                     and not int(c.findtext('clef-octave-change', '0') or 0)
                     for c in part.iter('clef') if (c.get('number') or '1') == '1')
        if treble:
            out[part.get('id')] = name
    return out


def fix_part(part, name):
    """Remove low clefs from the first staff and move their notes back; returns log lines."""
    log = []
    fifths = 0
    offset = 0                     # 0 = the first staff is read as treble here
    span_start, span_clef, span_notes = None, None, 0
    last_number = None

    def close_span():
        if span_start is not None and span_notes:
            log.append(f'{part.get("id")} {name} m{span_start}-{last_number} '
                       f'{span_clef} -> G2, {span_notes} notes')

    for m in part.findall('measure'):
        number = m.get('number')
        for at in m.findall('attributes'):
            key = at.find('key/fifths')
            if key is not None and key.text is not None:
                fifths = int(key.text)
            for clef in at.findall('clef'):
                if (clef.get('number') or '1') != '1':
                    continue
                sign, line = clef.findtext('sign'), clef.findtext('line')
                octave_change = int(clef.findtext('clef-octave-change', '0') or 0)
                if sign == 'G' and line == '2' and not octave_change:
                    if offset:
                        close_span()
                        span_start, span_notes = None, 0
                    offset = 0
                elif sign in CLEF_REFERENCE and line:
                    if not offset:
                        span_start, span_notes = number, 0
                    offset = clef_offset(sign, int(line), octave_change)
                    span_clef = f'{sign}{line}'
                    at.remove(clef)
                    log.append(f'{part.get("id")} {name} m{number}: {sign}{line} clef removed')
        if not offset:
            continue
        accidentals = {}               # notes of one measure re-use an explicit accidental
        for note in m.iter('note'):
            if staff_of(note) != '1':
                continue
            pitch = note.find('pitch')
            if pitch is None:
                continue
            old_diatonic = note_diatonic(pitch)
            new_diatonic = old_diatonic + offset
            old_step = pitch.findtext('step')
            old_octave = pitch.findtext('octave')
            old_alter = int(float(pitch.findtext('alter', '0') or 0))
            accidental = note.find('accidental')
            if accidental is not None:
                # a printed accidental stays on its new letter, and applies to the rest of the
                # measure (the same letter and octave, as MuseScore reads it)
                accidentals[(old_step, old_octave)] = old_alter
                new_alter = old_alter
            elif (old_step, old_octave) in accidentals:
                new_alter = accidentals[(old_step, old_octave)]
            else:
                new_alter = key_alter(fifths, STEPS[new_diatonic % 7])
            if not set_pitch(pitch, new_diatonic, new_alter):
                log.append(f'{part.get("id")} {name} m{number}: pitch below octave 0, left alone')
                continue
            span_notes += 1
        last_number = number
    close_span()
    return log


def fix(score_path):
    tree = ET.parse(score_path)
    root = tree.getroot()
    names = part_names(root)
    guitar = treble_parts(root)
    log = []
    for part in root.findall('part'):
        if part.get('id') in guitar:
            log.extend(fix_part(part, names.get(part.get('id'), ('', ''))[0]))
    if log:
        tree.write(score_path, encoding='UTF-8', xml_declaration=True)
    print('fix_guitar_clefs: ' + ('; '.join(log) if log else 'nothing changed'))


def main(paths):
    for path in paths:
        fix(path)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('Usage: python tools/fix_guitar_clefs.py <score.musicxml> [more.musicxml ...]')
    main(sys.argv[1:])
