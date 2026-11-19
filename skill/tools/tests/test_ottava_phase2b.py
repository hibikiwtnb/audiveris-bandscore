import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
import apply_instrument_changes  # noqa: E402
import apply_ottava  # noqa: E402
import ottava_from_labels  # noqa: E402
import verify_musescore  # noqa: E402


def row(page, system, staff, measure, beat, text, x=300.0, part='Str. I'):
    return dict(page=page, system=system, part=part, staff=staff, measure=measure,
                beat=beat, x=x, text=text)


class TestOttavaLabelPlanning(unittest.TestCase):
    def test_reminder_never_starts_a_region(self):
        hints, checks = ottava_from_labels.plan([row('1', '1', '1', '126', '1', '(8va).')])
        self.assertEqual(hints, [])
        self.assertTrue(any('reminder' in c for c in checks))

    def test_different_kinds_are_not_paired(self):
        hints, checks = ottava_from_labels.plan([
            row('1', '1', '1', '10', '1', '┌ 8va'),
            row('1', '1', '1', '12', '3', '15ma ┘'),
        ])
        self.assertEqual(hints, [])
        self.assertTrue(any('different kind' in c for c in checks))

    def test_continuation_does_not_close_or_restart(self):
        hints, checks = ottava_from_labels.plan([
            row('1', '1', '1', '4', '1', '8va ┌'),
            row('2', '1', '1', '5', '1', '← 8va'),
            row('2', '1', '1', '6', '3', '8va ┘'),
        ])
        self.assertEqual(hints, [('Str. I', '1', '8va', '4', '1', '6', '3')])
        self.assertTrue(any('continuation' in c for c in checks))

    def test_single_bracketed_label_is_a_local_span(self):
        hints, checks = ottava_from_labels.plan([row('1', '1', '1', '2', '3', '(8va)')])
        self.assertEqual(hints, [('Str. I', '1', '8va', '2', '3', '2', 'end')])
        self.assertTrue(any('single bracketed' in c for c in checks))

    def test_bare_mark_is_only_a_check(self):
        hints, checks = ottava_from_labels.plan([row('1', '2', '1', '7', '1', '8va')])
        self.assertEqual(hints, [])
        self.assertTrue(any('cannot tell' in c for c in checks))

    def test_open_mark_before_stop_is_not_paired(self):
        hints, checks = ottava_from_labels.plan([
            row('1', '1', '1', '10', '1', '8va ┌'),
            row('1', '1', '1', '11', '1', '15ma ┌'),
            row('1', '1', '1', '12', '1', '8va ┘'),
        ])
        self.assertEqual(hints, [])
        self.assertTrue(checks)

    def test_exact_duplicate_rows_are_dropped_once(self):
        r = row('1', '1', '1', '3', '1', '8va ┌')
        kept, checks = ottava_from_labels.dedupe([r, dict(r), row('1', '1', '1', '5', '1',
                                                                 '8va ┘')])
        self.assertEqual(len(kept), 2)
        self.assertTrue(any('duplicate' in c for c in checks))

    def test_no_arrow_and_long_gap_are_reported(self):
        hints, checks = ottava_from_labels.plan([
            row('1', '1', '1', '1', '1', '8va ('),
            row('1', '1', '1', '120', '1', '8va )'),
        ])
        self.assertEqual(len(hints), 1)
        self.assertTrue(any('very long region' in c for c in checks))


def _score(path, measures=2, voices=False):
    body = []
    for n in range(1, measures + 1):
        body.append(f'<measure number="{n}"><attributes>'
                    '<divisions>1</divisions><key><fifths>0</fifths></key>'
                    '<time><beats>4</beats><beat-type>4</beat-type></time>'
                    '<clef><sign>G</sign><line>2</line></clef></attributes>')
        if voices and n == 1:
            body.append('<note><pitch><step>C</step><octave>5</octave></pitch>'
                        '<duration>4</duration><tie type="start"/>'
                        '<voice>1</voice><type>whole</type><staff>1</staff>'
                        '<notations><tied type="start"/>'
                        '<slur type="start" number="1"/></notations></note>')
            body.append('<backup><duration>4</duration></backup>')
            body.append('<note><pitch><step>G</step><octave>4</octave></pitch>'
                        '<duration>4</duration><tie type="start"/>'
                        '<voice>2</voice><type>whole</type><staff>1</staff>'
                        '<notations><tied type="start"/></notations></note>')
        else:
            body.append('<note><pitch><step>C</step><octave>5</octave></pitch>'
                        '<duration>4</duration>'
                        + ('<tie type="stop"/>' if voices and n == 2 else '')
                        + '<voice>1</voice><type>whole</type><staff>1</staff>'
                        + ('<notations><tied type="stop"/>'
                           '<slur type="stop" number="1"/></notations>' if voices and n == 2
                           else '') + '</note>')
        body.append('</measure>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<score-partwise version="3.1"><part-list><score-part id="P1">'
           '<part-name>Strings I</part-name><part-abbreviation>Str. I</part-abbreviation>'
           '<score-instrument id="P1-I1"><instrument-name>Strings</instrument-name>'
           '</score-instrument></score-part></part-list>'
           '<part id="P1">' + ''.join(body) + '</part></score-partwise>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(xml)


class TestTextOnlyAndColl8va(unittest.TestCase):
    def test_text_only_raises_pitch_and_hides_line(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            _score(score, measures=2)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t1\tend\ttext-only\n')
            apply_ottava.main(score, hints)
            root = ET.parse(score).getroot()
            note = root.find('part/measure/note')
            self.assertEqual(note.findtext('pitch/octave'), '6')
            shifts = list(root.iter('octave-shift'))
            self.assertEqual({s.get('print-object') for s in shifts}, {'no'})
            self.assertEqual([w.text for w in root.iter('words')], ['8va'])
            self.assertEqual(verify_musescore.xml_staves(score),
                             [('P1 staff 1', [('1', [72]), ('2', [72])])])

    def test_text_only_musescore_import_keeps_written_pitch_and_hides_line(self):
        mscore = os.environ.get('MUSESCORE_BIN') or '/usr/local/bin/mscore'
        if not os.path.exists(mscore):
            self.skipTest('MuseScore not installed')
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            mscx = os.path.join(d, 'score.mscx')
            _score(score, measures=1)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t1\tend\ttext-only\n')
            apply_ottava.main(score, hints)
            subprocess.run([mscore, '-o', mscx, score], capture_output=True)
            text = open(mscx, encoding='utf-8').read()
            ottava = text[text.index('<Ottava>'):text.index('</Ottava>')]
            self.assertIn('<visible>0</visible>', ottava)
            self.assertIn('<pitch>72</pitch>', text)
            self.assertIn('<text>8va</text>', text)

    def test_coll8va_copy_has_no_visible_tied_or_slur(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            _score(score, measures=2, voices=True)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\tcoll8va\t1\t1\t2\tend\n')
            apply_ottava.main(score, hints)
            root = ET.parse(score).getroot()
            copies = [n for n in root.iter('note') if n.get('print-object') == 'no']
            self.assertTrue(copies)
            for c in copies:
                self.assertIsNone(c.find('notations/tied'))
                self.assertIsNone(c.find('notations/slur'))
                self.assertIsNone(c.find('notations'))
            voice1 = [c for c in copies if c.findtext('voice') == '1']
            voice2 = [c for c in copies if c.findtext('voice') == '2']
            self.assertTrue(voice1 and voice2)
            self.assertIsNotNone(voice1[0].find("tie[@type='start']"))
            self.assertIsNone(voice2[0].find("tie[@type='start']"))


class TestInstrumentLocalOctave(unittest.TestCase):
    def _grand(self, path):
        m = ['<measure number="1"><attributes><divisions>1</divisions>'
             '<key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>'
             '<staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef>'
             '<clef number="2"><sign>F</sign><line>4</line></clef></attributes>']
        for staff, step in (('1', 'C'), ('2', 'E')):
            for i in range(4):
                m.append(f'<note><pitch><step>{step}</step><octave>4</octave></pitch>'
                         f'<duration>1</duration><voice>1</voice><type>quarter</type>'
                         f'<staff>{staff}</staff></note>'
                         + (f'<backup><duration>1</duration></backup>' if False else ''))
            if staff == '1':
                m.append('<backup><duration>4</duration></backup>')
        m.append('</measure>')
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<score-partwise version="3.1"><part-list><score-part id="P1">'
               '<part-name>Key</part-name><part-abbreviation>Key.</part-abbreviation>'
               '<score-instrument id="P1-I1"><instrument-name>Piano</instrument-name>'
               '</score-instrument></score-part></part-list>'
               '<part id="P1">' + ''.join(m) + '</part></score-partwise>')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(xml)

    def test_local_octave_moves_only_the_marked_beat_range(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'instrument_changes.txt')
            self._grand(score)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('[defaults]\nKey.\tPan Flute\t2\n')
                f.write('[changes]\n1\tKey.\t2\t— Pan Flute (8va)—\tPan Flute\t1\t3\tend\tline\n')
            apply_instrument_changes.main(score, hints)
            root = ET.parse(score).getroot()
            staff2 = [n for n in root.iter('note')
                      if (n.findtext('staff') or '1') == '2' and n.find('pitch') is not None]
            self.assertEqual([n.findtext('pitch/octave') for n in staff2], ['4', '4', '5', '5'])
            staff1 = [n for n in root.iter('note')
                      if (n.findtext('staff') or '1') == '1' and n.find('pitch') is not None]
            self.assertEqual({n.findtext('pitch/octave') for n in staff1}, {'4'})
            intervals = __import__('score_time').octave_intervals(root.find('part'))
            local = [iv for iv in intervals if iv.number == '6']
            self.assertEqual(len(local), 1)
            self.assertEqual((local[0].start, local[0].end), (2, 4))

    def test_standalone_ottava_skips_instrument_octave_region(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'instrument_changes.txt')
            ottava = os.path.join(d, 'ottava.txt')
            self._grand(score)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('[defaults]\nKey.\tPan Flute\t2\n')
                f.write('[changes]\n1\tKey.\t2\t— Pan Flute (8va)—\tPan Flute\t1\t3\tend\tline\n')
            apply_instrument_changes.main(score, hints)
            with open(ottava, 'w', encoding='utf-8') as f:
                f.write('Key.\t2\t8va\t1\t3\t1\tend\n')
            apply_ottava.main(score, ottava)
            root = ET.parse(score).getroot()
            staff2 = [n for n in root.iter('note')
                      if (n.findtext('staff') or '1') == '2' and n.find('pitch') is not None]
            self.assertEqual([n.findtext('pitch/octave') for n in staff2], ['4', '4', '5', '5'])


if __name__ == '__main__':
    unittest.main()
