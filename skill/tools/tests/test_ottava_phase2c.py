import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from fractions import Fraction as F

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
import apply_instrument_changes  # noqa: E402
import apply_ottava  # noqa: E402
import clean_score_noise  # noqa: E402
import score_quality  # noqa: E402
import score_time  # noqa: E402
import verify_musescore  # noqa: E402


def _oct(typ, number='1', size='8', staff=None):
    st = f'<staff>{staff}</staff>' if staff else ''
    return (f'<direction placement="above"><direction-type>'
            f'<octave-shift type="{typ}" size="{size}" number="{number}"/>'
            f'</direction-type>{st}</direction>')


def _note(step, octave, dur=4, staff='1', voice='1', typ='whole'):
    return (f'<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>'
            f'<duration>{dur}</duration><voice>{voice}</voice><type>{typ}</type>'
            f'<staff>{staff}</staff></note>')


def _build_score(measures_xml, part_id='P1', abbr='Str. I'):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<score-partwise version="3.1"><part-list><score-part id="{part_id}">'
        f'<part-name>{abbr}</part-name><part-abbreviation>{abbr}</part-abbreviation>'
        '</score-part></part-list>'
        f'<part id="{part_id}">{"".join(measures_xml)}</part></score-partwise>'
    )


def _m(num, body, attrs=True):
    a = ('<attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
         '<time><beats>4</beats><beat-type>4</beat-type></time>'
         '<clef><sign>G</sign><line>2</line></clef></attributes>') if attrs else ''
    return f'<measure number="{num}">{a}{body}</measure>'


class TestCleanupQualityConsistency(unittest.TestCase):
    def test_same_staff_different_numbers_match_score_quality(self):
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6) + _oct('stop', '2', staff='1')),
        ])
        root = ET.fromstring(xml)
        pm = {'P1': score_quality.read_measures(root.find('part'))}
        self.assertEqual(score_quality.unpaired_octave_shifts(pm), 2)

        warnings = []
        removed = clean_score_noise.strip_dangling_octave_shifts(root, warnings=warnings)
        self.assertEqual(removed, 2)
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all('未自動改音高，待確認' in w for w in warnings))
        self.assertTrue(any('number 1' in w for w in warnings))
        self.assertTrue(any('number 2' in w for w in warnings))
        # pitch must remain untouched
        self.assertEqual(root.findtext('.//note/pitch/octave'), '6')
        pm_after = {'P1': score_quality.read_measures(root.find('part'))}
        self.assertEqual(score_quality.unpaired_octave_shifts(pm_after), 0)

    def test_duplicate_start_and_orphan_stop_consistent_without_pitch_change(self):
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6)),
            _m('2', _oct('down', '1', staff='1') + _note('D', 6) + _oct('stop', '1', staff='1'), attrs=False),
            _m('3', _oct('stop', '2', staff='1') + _note('E', 5), attrs=False),
        ])
        root = ET.fromstring(xml)
        pm = {'P1': score_quality.read_measures(root.find('part'))}
        self.assertEqual(score_quality.unpaired_octave_shifts(pm), 2)

        warnings = []
        removed = clean_score_noise.strip_dangling_octave_shifts(root, warnings=warnings)
        self.assertEqual(removed, 2)
        self.assertTrue(any('m1' in w and 'duplicate start' in w and '未自動改音高，待確認' in w for w in warnings))
        self.assertTrue(any('m3' in w and 'orphan stop' in w and '未自動改音高，待確認' in w for w in warnings))
        self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6', '6', '5'])


class TestScoreTimeAnalysis(unittest.TestCase):
    def test_analyze_lists_all_anomalies_and_continues(self):
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6)
               + '<backup><duration>4</duration></backup>'
               + _oct('down', '2', staff='1') + _note('G', 5, voice='2')),
            _m('2', _oct('continue', '1', staff='1') + _oct('down', '1', staff='1')
               + _note('D', 6) + _oct('stop', '1', staff='1'), attrs=False),
            _m('3', _oct('stop', '3', staff='1') + _note('E', 5), attrs=False),
        ])
        part = ET.fromstring(xml).find('part')
        analysis = score_time.analyze_octave_shifts(part)
        self.assertEqual(len(analysis.duplicate_starts), 1)
        self.assertEqual(analysis.duplicate_starts[0]['measure'], '2')
        self.assertEqual(len(analysis.orphan_stops), 1)
        self.assertEqual(analysis.orphan_stops[0]['number'], '3')
        self.assertEqual(len(analysis.unclosed_starts), 1)
        self.assertEqual(analysis.unclosed_starts[0]['number'], '2')
        self.assertEqual(len(analysis.continues), 1)
        self.assertTrue(analysis.continues[0]['active'])
        self.assertTrue(len(analysis.overlaps) >= 1)


class TestSafeRestorationAndOverlaps(unittest.TestCase):
    def test_partial_intersection_when_native_starts_before_hint(self):
        # Native 8va covers m1-m2 (notes already +1 octave: C6, D6).
        # Hint covers m2 only -> m1 must stay C6 with native 8va [0, 4),
        # m2 must be restored to D5 then shifted once to D6 with hint 8va [4, 8).
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6)),
            _m('2', _oct('continue', '1', staff='1') + _note('D', 6) + _oct('stop', '1', staff='1'), attrs=False),
        ])
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t2\t1\t2\tend\n')

            apply_ottava.main(score, hints)

            root = ET.parse(score).getroot()
            octaves = [o.text for o in root.findall('.//note/pitch/octave')]
            self.assertEqual(octaves, ['6', '6'])
            ivs = score_time.octave_intervals(root.find('part'))
            native_ivs = [iv for iv in ivs if iv.number == '1']
            hint_ivs = [iv for iv in ivs if iv.number == '3']
            self.assertEqual(len(native_ivs), 1)
            self.assertEqual((native_ivs[0].start, native_ivs[0].end), (F(0), F(4)))
            self.assertEqual(len(hint_ivs), 1)
            self.assertEqual((hint_ivs[0].start, hint_ivs[0].end), (F(4), F(8)))
            self.assertEqual(verify_musescore.xml_staves(score), [('P1 staff 1', [('1', [72]), ('2', [74])])])

    def test_incomplete_native_interval_stops_hint(self):
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6)),
            _m('2', _note('D', 6), attrs=False),
        ])
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t2\tend\n')

            buf = io.StringIO()
            with redirect_stdout(buf):
                apply_ottava.main(score, hints)

            self.assertIn('stopped', buf.getvalue())
            root = ET.parse(score).getroot()
            self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6', '6'])
            self.assertFalse(any(o.get('number') == '3' for o in root.iter('octave-shift')))

    def test_216_p1_m15_overlapping_native_shifts_stop_hint_without_double_shift(self):
        xml = _build_score([
            _m('15', _oct('down', '1', staff='1') + _oct('down', '2', staff='1')
               + _note('C', 6) + _oct('stop', '1', staff='1') + _oct('stop', '2', staff='1')),
        ])
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t15\t1\t15\tend\n')

            buf = io.StringIO()
            with redirect_stdout(buf):
                apply_ottava.main(score, hints)

            self.assertIn('overlapping native octave-shifts', buf.getvalue())
            root = ET.parse(score).getroot()
            self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6'])
            self.assertFalse(any(o.get('number') == '3' for o in root.iter('octave-shift')))

    def test_overlapping_standalone_hints_apply_only_once(self):
        xml = _build_score([
            _m('1', _note('C', 5)),
            _m('2', _note('D', 5), attrs=False),
        ])
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t2\tend\n'
                        'Str. I\t1\tcoll8va\t1\t1\t2\tend\n')

            buf = io.StringIO()
            with redirect_stdout(buf):
                apply_ottava.main(score, hints)

            self.assertIn('skipped', buf.getvalue())
            root = ET.parse(score).getroot()
            self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6', '6'])

    def test_instrument_changes_partial_intersection_and_incomplete_stop(self):
        xml = _build_score([
            _m('1', _oct('down', '1', staff='1') + _note('C', 6)),
            _m('2', _note('D', 6) + _oct('stop', '1', staff='1'), attrs=False),
            _m('3', _oct('down', '1', staff='1') + _note('E', 6), attrs=False),
        ], abbr='Key.')
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'instrument_changes.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write(
                    '[changes]\n'
                    '1\tKey.\t1\t-\tPiano\t0\n'
                    '2\tKey.\t1\tGlocken\tGlocken\t1\n'
                    '3\tKey.\t1\tPiano\tPiano\t0\n'
                )
            apply_instrument_changes.main(score, hints)
            root = ET.parse(score).getroot()
            self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6', '6', '6'])
            ivs = score_time.octave_intervals(root.find('part'))
            self.assertTrue(any(iv.number == '1' and iv.start == F(0) and iv.end == F(4) for iv in ivs))
            self.assertTrue(any(iv.number == '5' and iv.start == F(4) and iv.end == F(8) for iv in ivs))

        # Now test m3 unclosed native start stops instrument-change octave line
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'instrument_changes.txt')
            with open(score, 'w', encoding='utf-8') as f:
                f.write(xml)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write(
                    '[changes]\n'
                    '1\tKey.\t1\t-\tPiano\t0\n'
                    '3\tKey.\t1\tGlocken\tGlocken\t1\n'
                )
            buf = io.StringIO()
            with redirect_stdout(buf):
                apply_instrument_changes.main(score, hints)
            self.assertIn('stopped octave line', buf.getvalue())
            root = ET.parse(score).getroot()
            self.assertEqual([o.text for o in root.findall('.//note/pitch/octave')], ['6', '6', '6'])
            self.assertFalse(any(o.get('number') == '5' for o in root.iter('octave-shift')))


if __name__ == '__main__':
    unittest.main()
