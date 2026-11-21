import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as F
import xml.etree.ElementTree as ET

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
import apply_ottava  # noqa: E402
import mscore_env  # noqa: E402
import score_time  # noqa: E402
import verify_musescore  # noqa: E402


def _wrap_score(parts_xml):
    part_list = ''.join(
        f'<score-part id="{pid}"><part-name>{name}</part-name>'
        f'<part-abbreviation>{abbr}</part-abbreviation></score-part>'
        for pid, name, abbr, _ in parts_xml
    )
    parts = ''.join(
        f'<part id="{pid}">{body}</part>'
        for pid, _, _, body in parts_xml
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
        f'<score-partwise version="3.1"><part-list>{part_list}</part-list>{parts}</score-partwise>'
    )


def _note(step, octave, dur, typ=None, voice='1', staff='1', alter=None,
          chord=False, grace=False):
    parts = ['<note>']
    if grace:
        parts.append('<grace/>')
    if chord:
        parts.append('<chord/>')
    parts.append(f'<pitch><step>{step}</step>')
    if alter is not None:
        parts.append(f'<alter>{alter}</alter>')
    parts.append(f'<octave>{octave}</octave></pitch>')
    if not grace:
        parts.append(f'<duration>{dur}</duration>')
    parts.append(f'<voice>{voice}</voice>')
    if typ:
        parts.append(f'<type>{typ}</type>')
    if staff is not None:
        parts.append(f'<staff>{staff}</staff>')
    parts.append('</note>')
    return ''.join(parts)


def _require_mscore(testcase):
    if not mscore_env.musescore_bin():
        testcase.skipTest('MuseScore not installed')


def _run_mscore_staves(xml_str):
    mscore_bin = mscore_env.musescore_bin()
    with tempfile.TemporaryDirectory() as td:
        in_xml = os.path.join(td, 'score.musicxml')
        out_mscx = os.path.join(td, 'score.mscx')
        with open(in_xml, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        subprocess.run([mscore_bin, '-o', out_mscx, in_xml], check=True, capture_output=True)
        return verify_musescore.mscx_staves(out_mscx), verify_musescore.xml_staves(in_xml)


def _verify_zero_diff(testcase, xml_str, hints_text=None):
    _require_mscore(testcase)
    with tempfile.TemporaryDirectory() as td:
        score = os.path.join(td, 'score.musicxml')
        with open(score, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        if hints_text is not None:
            hints = os.path.join(td, 'ottava.txt')
            with open(hints, 'w', encoding='utf-8') as f:
                f.write(hints_text)
            apply_ottava.main(score, hints)
        res = subprocess.run(
            [sys.executable, os.path.join(TOOLS_DIR, 'verify_musescore.py'), score],
            capture_output=True, text=True,
        )
        testcase.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return ET.parse(score).getroot()


class TestOttavaPhase2D(unittest.TestCase):
    def test_divisions_change_mid_score_ottava_and_verify(self):
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 4, 'half')
            + _note('D', 5, 4, 'half')
            + '</measure>'
        )
        m2 = (
            '<measure number="2">'
            '<attributes><divisions>4</divisions></attributes>'
            + _note('E', 5, 4, 'quarter')
            + _note('F', 5, 4, 'quarter')
            + _note('G', 5, 8, 'half')
            + '</measure>'
        )
        xml_str = _wrap_score([('P1', 'Strings I', 'Str. I', m1 + m2)])
        root = _verify_zero_diff(self, xml_str, 'Str. I\t1\t8va\t1\t3\t2\t2\n')
        iv = score_time.octave_intervals(root.find('part'))
        self.assertEqual([(i.start, i.end, i.shift) for i in iv], [(F(2), F(6), 1)])

    def test_six_eight_time_quarter_unit_positions(self):
        # 6/8 measure = 3 quarter notes; divisions=2 -> 6 eighth notes (dur=1 each)
        # Quarter-unit pos=1 is onset 0, pos=2.5 is onset 1.5 (4th eighth note)
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
            '<time><beats>6</beats><beat-type>8</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 1, 'eighth')
            + _note('D', 5, 1, 'eighth')
            + _note('E', 5, 1, 'eighth')
            + _note('F', 5, 1, 'eighth')
            + _note('G', 5, 1, 'eighth')
            + _note('A', 5, 1, 'eighth')
            + '</measure>'
        )
        xml_str = _wrap_score([('P1', 'Strings I', 'Str. I', m1)])
        root = _verify_zero_diff(self, xml_str, 'Str. I\t1\t8va\t1\t1\t1\t2.5\n')
        iv = score_time.octave_intervals(root.find('part'))
        self.assertEqual([(i.start, i.end, i.shift) for i in iv], [(F(0), F(2), 1)])

    def test_grace_note_with_ottava_boundary(self):
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 1, 'quarter')
            + _note('D', 5, 0, 'eighth', grace=True)
            + _note('E', 5, 1, 'quarter')
            + _note('F', 5, 2, 'half')
            + '</measure>'
        )
        xml_str = _wrap_score([('P1', 'Strings I', 'Str. I', m1)])
        with tempfile.TemporaryDirectory() as td:
            score = os.path.join(td, 'score.musicxml')
            hints = os.path.join(td, 'ottava.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml_str)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t2\t1\t2\n')
            apply_ottava.main(score, hints)
            staves = verify_musescore.xml_staves(score)
            # apply_ottava shifts grace D5 and E5 up an octave; xml_staves recovers [72, 74, 76, 77]
            self.assertEqual(staves, [('P1 staff 1', [('1', [72, 74, 76, 77])])])
            _verify_zero_diff(self, xml_str, 'Str. I\t1\t8va\t1\t2\t1\t2\n')

    def test_chord_notes_under_ottava_and_verify(self):
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 2, 'half')
            + _note('E', 5, 2, 'half', chord=True)
            + _note('G', 5, 2, 'half')
            + '</measure>'
        )
        xml_str = _wrap_score([('P1', 'Strings I', 'Str. I', m1)])
        _verify_zero_diff(self, xml_str, 'Str. I\t1\t8va\t1\t1\t1\t1\n')

    def test_octave_shift_with_direction_offset(self):
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            '<direction><direction-type><octave-shift type="down" size="8" number="3"/>'
            '</direction-type><offset>2</offset><staff>1</staff></direction>'
            + _note('C', 5, 2, 'quarter')
            + _note('D', 5, 2, 'quarter')
            + '<direction><direction-type><octave-shift type="stop" size="8" number="3"/>'
            '</direction-type><offset>2</offset><staff>1</staff></direction>'
            + _note('E', 5, 2, 'quarter')
            + _note('F', 5, 2, 'quarter')
            + '</measure>'
        )
        part = ET.fromstring(f'<part id="P1">{m1}</part>')
        iv = score_time.octave_intervals(part)
        # start at 0 + 2/2 = F(1), stop at cursor(after D5)=2 + 2/2 = F(3)
        self.assertEqual([(i.start, i.end, i.shift) for i in iv], [(F(1), F(3), 1)])
        with tempfile.TemporaryDirectory() as td:
            score = os.path.join(td, 'score.musicxml')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(_wrap_score([('P1', 'Strings I', 'Str. I', m1)]))
            # C5=72 (tick 0, out), D5=74->62 (tick 1, in), E5=76->64 (tick 2, in), F5=77 (tick 3, out)
            self.assertEqual(verify_musescore.xml_staves(score),
                             [('P1 staff 1', [('1', [62, 64, 72, 77])])])

    def test_same_onset_different_duration_document_order(self):
        # Shorter note appears AFTER longer note at same onset in document order
        m1 = (
            '<measure number="1">'
            '<attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 4, 'whole', voice='1')
            + '<backup><duration>4</duration></backup>'
            + _note('G', 4, 1, 'quarter', voice='2')
            + '<note><rest/><duration>3</duration><voice>2</voice><type>half</type><dot/><staff>1</staff></note>'
            + '</measure>'
        )
        xml_str = _wrap_score([('P1', 'Strings I', 'Str. I', m1)])
        root = _verify_zero_diff(self, xml_str, 'Str. I\t1\t8va\t1\t1\t1\tend\n')
        iv = score_time.octave_intervals(root.find('part'))
        self.assertEqual([(i.start, i.end) for i in iv], [(F(0), F(4))])

    def test_297_short_span_p5_m204_m212_single_part_and_unequal_parts(self):
        _require_mscore(self)
        # Single-part 297 P5 m212 shape: 4/4 div=4, half+quarter rest, 4x 16th on beat 4, stop in next measure
        p2_m1 = (
            '<measure number="1">'
            '<attributes><divisions>4</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            '<note><rest measure="yes"/><duration>16</duration><voice>1</voice></note>'
            '</measure>'
        )
        p2_m2 = (
            '<measure number="2">'
            '<note><rest/><duration>8</duration><voice>1</voice><type>half</type></note>'
            '<note><rest/><duration>4</duration><voice>1</voice><type>quarter</type></note>'
            + _note('B', 4, 1, '16th', staff=None)
            + _note('D', 5, 1, '16th', staff=None)
            + _note('G', 5, 1, '16th', alter=1, staff=None)
            + _note('B', 5, 1, '16th', staff=None)
            + '</measure>'
        )
        p2_m3 = (
            '<measure number="3">'
            '<note><rest measure="yes"/><duration>16</duration><voice>1</voice></note>'
            '</measure>'
        )
        single_xml = _wrap_score([('P1', 'Syn. Lead', 'Syn.', p2_m1 + p2_m2 + p2_m3)])
        root = _verify_zero_diff(self, single_xml, 'Syn.\t1\t8va\t2\t4\t2\tend\n')

        # Now embed the exact apply_ottava result into a 2-part score where P1 m1 has 9/8 (+1/8)
        p1_m1 = (
            '<measure number="1">'
            '<attributes><divisions>4</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 16, 'whole', staff=None)
            + _note('C', 5, 2, 'eighth', staff=None)
            + '</measure>'
        )
        p1_rest = '<note><rest measure="yes"/><duration>16</duration><voice>1</voice></note>'
        p2_body = ''.join(ET.tostring(m, encoding='unicode') for m in root.findall('part/measure'))
        two_part_xml = _wrap_score([
            ('P1', 'Vocal', 'Vo.', p1_m1 + f'<measure number="2">{p1_rest}</measure><measure number="3">{p1_rest}</measure>'),
            ('P2', 'Syn. Lead', 'Syn.', p2_body),
        ])
        ms, xs = _run_mscore_staves(two_part_xml)
        # score_time / xml_staves expects [71, 74, 80, 83], while MuseScore Pass1/Pass2 mismatch leaves last two +12
        self.assertEqual(xs[1][1][1][1], [71, 74, 80, 83])
        self.assertEqual(ms[1]['measures'][1], [71, 74, 92, 95])

    def test_297_cross_measure_stop_p4_m228_single_part_and_unequal_parts(self):
        _require_mscore(self)
        # 297 P4 m227-m229 shape: div=2, 8va from m227 beat 3.5 across m228 (ending with eighth C#6), stop at m229
        p2_m1 = (
            '<measure number="1">'
            '<attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            '<note><rest measure="yes"/><duration>8</duration><voice>1</voice></note>'
            '</measure>'
        )
        p2_m2 = (
            '<measure number="2">'
            '<note><rest/><duration>4</duration><voice>1</voice><type>half</type></note>'
            '<note><rest/><duration>1</duration><voice>1</voice><type>eighth</type></note>'
            + _note('D', 5, 2, 'quarter', staff=None)
            + _note('D', 5, 1, 'eighth', staff=None)
            + '</measure>'
        )
        p2_m3 = (
            '<measure number="3">'
            + _note('D', 5, 1, 'eighth', staff=None)
            + _note('A', 4, 2, 'quarter', staff=None)
            + _note('G', 4, 1, 'eighth', staff=None)
            + _note('F', 4, 1, 'eighth', alter=1, staff=None)
            + _note('G', 4, 1, 'eighth', staff=None)
            + _note('A', 4, 1, 'eighth', staff=None)
            + _note('C', 5, 1, 'eighth', alter=1, staff=None)
            + '</measure>'
        )
        p2_m4 = (
            '<measure number="4">'
            '<note><rest measure="yes"/><duration>8</duration><voice>1</voice></note>'
            '</measure>'
        )
        single_xml = _wrap_score([('P1', 'Bell I', 'Bell', p2_m1 + p2_m2 + p2_m3 + p2_m4)])
        root = _verify_zero_diff(self, single_xml, 'Bell\t1\t8va\t2\t3.5\t3\tend\n')

        p1_m1 = (
            '<measure number="1">'
            '<attributes><divisions>2</divisions><key><fifths>0</fifths></key>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            + _note('C', 5, 8, 'whole', staff=None)
            + _note('C', 5, 1, 'eighth', staff=None)
            + '</measure>'
        )
        p1_rest = '<note><rest measure="yes"/><duration>8</duration><voice>1</voice></note>'
        p2_body = ''.join(ET.tostring(m, encoding='unicode') for m in root.findall('part/measure'))
        two_part_xml = _wrap_score([
            ('P1', 'Vocal', 'Vo.', p1_m1 + ''.join(f'<measure number="{i}">{p1_rest}</measure>' for i in (2, 3, 4))),
            ('P2', 'Bell I', 'Bell', p2_body),
        ])
        ms, xs = _run_mscore_staves(two_part_xml)
        self.assertEqual(xs[1][1][2][1], [66, 67, 67, 69, 69, 73, 74])
        self.assertEqual(ms[1]['measures'][2], [66, 67, 67, 69, 69, 74, 85])


if __name__ == '__main__':
    unittest.main()
