import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bandscore_postprocess as bp  # noqa: E402
import score_quality  # noqa: E402

ATTR = ('<attributes><divisions>4</divisions><key><fifths>0</fifths></key>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '<clef><sign>G</sign><line>2</line></clef></attributes>')


def note(dur=16, voice='1', step='C', octave=5, rest=False, chord=False):
    s = '<note>'
    if chord:
        s += '<chord/>'
    if rest:
        s += '<rest/>'
    else:
        s += f'<pitch><step>{step}</step><octave>{octave}</octave></pitch>'
    return s + f'<duration>{dur}</duration><voice>{voice}</voice></note>'


def forward(dur, voice='2'):
    return f'<forward><duration>{dur}</duration><voice>{voice}</voice></forward>'


def measure(body, number='1', implicit=False, attrs=True):
    imp = ' implicit="yes"' if implicit else ''
    a = ATTR if attrs else ''
    return f'<measure number="{number}"{imp}>{a}{body}</measure>'


def part_root(measures):
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<score-partwise version="3.1"><part-list><score-part id="P1">'
           '<part-name>Piano</part-name></score-part></part-list>'
           '<part id="P1">' + ''.join(measures) + '</part></score-partwise>')
    return ET.fromstring(xml)


class TestTrailingForwardRemoval(unittest.TestCase):
    def _run(self, root):
        rep = {'trailing_forward': []}
        bp.drop_trailing_forwards(root, rep, 'p01')
        return rep

    def test_removes_trailing_forward(self):
        root = part_root([measure(note(16) + '<backup><duration>16</duration></backup>'
                                  + forward(18))])
        rep = self._run(root)
        self.assertEqual(rep['trailing_forward'], ['p01 m1 P1 -9/2'])
        self.assertIsNone(root.find('.//forward'))
        self.assertEqual(len(root.findall('.//note')), 1)

    def test_removes_consecutive_trailing_forwards(self):
        root = part_root([measure(note(8) + forward(4) + forward(4))])
        rep = self._run(root)
        self.assertEqual(len(rep['trailing_forward']), 2)
        self.assertIsNone(root.find('.//forward'))

    def test_keeps_forward_before_a_direction(self):
        body = note(8) + forward(8) + (
            '<direction><direction-type><words>cresc.</words></direction-type></direction>')
        root = part_root([measure(body)])
        self.assertEqual(self._run(root)['trailing_forward'], [])
        self.assertIsNotNone(root.find('.//forward'))

    def test_keeps_forward_before_a_note(self):
        root = part_root([measure(note(8) + forward(8) + note(8, voice='2'))])
        self.assertEqual(self._run(root)['trailing_forward'], [])
        self.assertIsNotNone(root.find('.//forward'))

    def test_keeps_forward_in_a_measure_without_notes(self):
        root = part_root([measure(forward(16))])
        self.assertEqual(self._run(root)['trailing_forward'], [])
        self.assertIsNotNone(root.find('.//forward'))

    def test_keeps_implicit_measure(self):
        root = part_root([measure(note(4) + forward(4), implicit=True)])
        self.assertEqual(self._run(root)['trailing_forward'], [])

    def test_removes_empty_forward_backup_placeholder_voice(self):
        root = part_root([measure(note(16) + '<backup><duration>16</duration></backup>'
                                  + forward(20) + '<backup><duration>20</duration></backup>')])
        rep = self._run(root)
        self.assertEqual(rep['trailing_forward'], ['p01 m1 P1 -5 (empty voice)'])
        self.assertIsNone(root.find('.//forward'))
        self.assertEqual(len(root.findall('.//backup')), 1)

    def test_removes_trailing_forward_then_placeholder_pair(self):
        # 076 m152: a cut voice leaves forward 24 after a forward/backup placeholder
        root = part_root([measure(note(16) + '<backup><duration>16</duration></backup>'
                                  + forward(20) + '<backup><duration>20</duration></backup>'
                                  + forward(24))])
        rep = self._run(root)
        self.assertEqual(len(rep['trailing_forward']), 2)
        self.assertIsNone(root.find('.//forward'))
        self.assertEqual(len(root.findall('.//backup')), 1)

    def test_keeps_unequal_forward_backup_pair(self):
        root = part_root([measure(note(16) + '<backup><duration>16</duration></backup>'
                                  + forward(16) + '<backup><duration>8</duration></backup>')])
        self.assertEqual(self._run(root)['trailing_forward'], [])
        self.assertIsNotNone(root.find('.//forward'))

    def test_ignores_barline_after_the_forward(self):
        root = part_root([measure(note(16) + forward(2)
                                  + '<barline location="right"><bar-style>light-heavy</bar-style>'
                                    '</barline>')])
        self.assertEqual(len(self._run(root)['trailing_forward']), 1)


def score_root(parts):
    """parts: list of measure-body lists, one per part."""
    ids = [f'P{k + 1}' for k in range(len(parts))]
    plist = ''.join(f'<score-part id="{i}"><part-name>{i}</part-name></score-part>' for i in ids)
    body = ''.join(f'<part id="{i}">' + ''.join(measure(b, str(n + 1), attrs=n == 0)
                                                for n, b in enumerate(ms)) + '</part>'
                   for i, ms in zip(ids, parts))
    return ET.fromstring('<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
                         f'<part-list>{plist}</part-list>{body}</score-partwise>')


class TestCrossPartLength(unittest.TestCase):
    def _quality(self, parts):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'score.musicxml')
            ET.ElementTree(score_root(parts)).write(path, encoding='UTF-8', xml_declaration=True)
            buf = io.StringIO()
            with redirect_stdout(buf):
                score_quality.main(path)
        return buf.getvalue()

    def test_flags_part_with_trailing_forward(self):
        # 297 m198: P1 has a trailing forward 18 (div 4) behind its last voice
        p1 = (note(16) + '<backup><duration>16</duration></backup>' + forward(18, voice='6'))
        out = self._quality([[p1], [note(16)], [note(16)]])
        self.assertIn('cross_part_length_mismatch count=1 at=m1', out)
        self.assertIn('at=m1 most=4 P1=9/2', out)

    def test_clean_parts_are_not_flagged(self):
        p1 = (note(16) + note(16, chord=True)
              + '<backup><duration>16</duration></backup>' + note(16, voice='2', rest=True))
        out = self._quality([[p1, note(16)], [note(16), note(16)]])
        self.assertIn('cross_part_length_mismatch count=0', out)

    def test_flags_only_the_odd_measure(self):
        out = self._quality([[note(16), note(16) + forward(2)], [note(16), note(16)]])
        self.assertIn('cross_part_length_mismatch count=1 at=m2', out)


if __name__ == '__main__':
    unittest.main()
