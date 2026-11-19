import os
import sys
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import score_time  # noqa: E402


def _measure(number, body, divisions=None, time=None):
    xml = f'<measure number="{number}">'
    if divisions is not None or time is not None:
        xml += '<attributes>'
        if divisions is not None:
            xml += f'<divisions>{divisions}</divisions>'
        if time is not None:
            xml += f'<time><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time>'
        xml += '</attributes>'
    return ET.fromstring(xml + body + '</measure>')


def _note(step, octave, dur, staff=None, chord=False, grace=False, voice='1'):
    xml = '<note>'
    if grace:
        xml += '<grace/>'
    if chord:
        xml += '<chord/>'
    xml += f'<pitch><step>{step}</step><octave>{octave}</octave></pitch>'
    xml += f'<duration>{dur}</duration><voice>{voice}</voice>'
    if staff is not None:
        xml += f'<staff>{staff}</staff>'
    return xml + '</note>'


def _part(measures, staves=1):
    part = ET.Element('part', {'id': 'P1'})
    for m in measures:
        part.append(m)
    return part


def _events(measure, div):
    return [e for e in score_time.walk(measure, div)]


class TestScoreTime(unittest.TestCase):
    def test_divisions_change_and_measure_starts(self):
        part = _part([
            _measure('1', _note('C', 4, 8) + '<backup><duration>8</duration></backup>'
                     + _note('E', 4, 8), divisions=2, time=(4, 4)),
            _measure('2', _note('D', 4, 16), divisions=4),
            _measure('3', _note('F', 4, 12), time=(3, 4)),
        ])
        self.assertEqual(score_time.measure_divs(part), [2, 4, 4])
        self.assertEqual(score_time.measure_starts(part), [F(0), F(4), F(8)])
        notes = [e for e in score_time.walk(part.findall('measure')[1], 4, F(4))]
        self.assertEqual(notes[0].tick, F(4))
        self.assertEqual(notes[0].duration, F(4))

    def test_backup_forward_and_chord(self):
        m = _measure('1', _note('C', 5, 2) + '<forward><duration>1</duration></forward>'
                     + _note('D', 5, 1) + _note('E', 5, 1, chord=True)
                     + '<backup><duration>4</duration></backup>' + _note('G', 4, 1), divisions=1)
        ev = _events(m, 1)
        self.assertEqual([(e.tick, e.duration) for e in ev],
                         [(F(0), F(2)), (F(3), F(1)), (F(3), F(1)), (F(0), F(1))])

    def test_grace_note_has_no_time(self):
        m = _measure('1', _note('C', 5, 1) + _note('D', 5, 1, grace=True)
                     + _note('E', 5, 1), divisions=1)
        ev = _events(m, 1)
        self.assertEqual([(e.tick, e.duration) for e in ev],
                         [(F(0), F(1)), (F(1), F(0)), (F(1), F(1))])

    def test_direction_offset_and_default_staff(self):
        m = _measure('1', '<direction><direction-type><words>x</words></direction-type>'
                     '<offset>2</offset></direction>' + _note('C', 5, 4), divisions=2)
        ev = _events(m, 2)
        self.assertEqual(ev[0].staff, '1')
        self.assertEqual(ev[0].tick, F(1))

    def test_local_cursor(self):
        m = _measure('1', _note('C', 5, 2) + '<backup><duration>2</duration></backup>'
                     + _note('G', 4, 1), divisions=2)
        self.assertEqual(score_time.local_cursor(m, m.findall('note')[1], 2), F(1, 2))
        self.assertEqual(score_time.local_cursor(m, m.findall('note')[0], 2), F(1))

    def test_octave_intervals_are_end_exclusive(self):
        def oct_shift(kind, typ, number='3', size='8'):
            return (f'<direction><direction-type><octave-shift type="{typ}" size="{size}" '
                    f'number="{number}"/></direction-type></direction>')
        part = _part([
            _measure('1', oct_shift('8va', 'down') + _note('C', 5, 4), divisions=1,
                     time=(4, 4)),
            _measure('2', _note('D', 5, 2) + oct_shift('8va', 'stop') + _note('E', 5, 2)),
            _measure('3', _note('F', 5, 4)),
        ])
        iv = score_time.octave_intervals(part)
        self.assertEqual(iv, [score_time.Interval('1', F(0), F(6), 1, '3')])
        self.assertEqual(score_time.shift_at(iv, '1', F(0)), 1)
        self.assertEqual(score_time.shift_at(iv, '1', F(5)), 1)
        self.assertEqual(score_time.shift_at(iv, '1', F(6)), 0)
        self.assertEqual(score_time.shift_at(iv, '2', F(0)), 0)

    def test_continue_keeps_shift_open_across_measures(self):
        def oct_shift(typ):
            return (f'<direction><direction-type><octave-shift type="{typ}" size="8" '
                    f'number="3"/></direction-type></direction>')
        part = _part([
            _measure('1', oct_shift('down') + _note('C', 5, 4), divisions=1, time=(4, 4)),
            _measure('2', oct_shift('continue') + _note('D', 5, 4)),
            _measure('3', oct_shift('stop') + _note('E', 5, 4)),
        ])
        iv = score_time.octave_intervals(part)
        self.assertEqual(iv, [score_time.Interval('1', F(0), F(8), 1, '3')])
        self.assertEqual(score_time.shift_at(iv, '1', F(7)), 1)

    def test_same_staff_different_numbers_are_separate(self):
        def oct_shift(typ, number):
            return (f'<direction><direction-type><octave-shift type="{typ}" size="8" '
                    f'number="{number}"/></direction-type></direction>')
        part = _part([
            _measure('1', oct_shift('down', '3') + oct_shift('down', '1')
                     + _note('C', 5, 4), divisions=1, time=(4, 4)),
        ])
        iv = score_time.octave_intervals(part)
        self.assertEqual(len(iv), 2)
        self.assertEqual(score_time.shift_at(iv, '1', F(0)), 1)


if __name__ == '__main__':
    unittest.main()
