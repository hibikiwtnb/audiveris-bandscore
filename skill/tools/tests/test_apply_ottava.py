import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction as F

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
import apply_ottava  # noqa: E402
import mscore_env  # noqa: E402
import score_time  # noqa: E402
import verify_musescore  # noqa: E402


def _make_two_voice_score(path):
    """Build a minimal 4/4 score with two voices in measure 1 ending on beat 4."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1">
      <part-name>Strings I</part-name>
      <part-abbreviation>Str. I</part-abbreviation>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration>
        <voice>1</voice>
        <type>whole</type>
        <staff>1</staff>
      </note>
      <backup><duration>4</duration></backup>
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>4</duration>
        <voice>2</voice>
        <type>whole</type>
        <staff>1</staff>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(xml)


class TestApplyOttava(unittest.TestCase):
    def test_stop_placed_after_last_document_group_on_time_tie(self):
        with tempfile.TemporaryDirectory() as d:
            score_path = os.path.join(d, 'score.musicxml')
            hints_path = os.path.join(d, 'ottava.txt')
            _make_two_voice_score(score_path)
            with open(hints_path, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t1\tend\n')

            apply_ottava.main(score_path, hints_path)

            # Document order: stop must come after voice 2's note so verify_musescore sees it
            root = ET.parse(score_path).getroot()
            m1 = root.find('part/measure')
            tags = [el.tag for el in m1]
            last_note_idx = len(tags) - 1 - tags[::-1].index('note')
            stop_idx = next(
                i for i, el in enumerate(m1)
                if el.tag == 'direction'
                and el.find("direction-type/octave-shift[@type='stop']") is not None
            )
            self.assertGreater(stop_idx, last_note_idx)

            # verify_musescore.xml_staves must recover both original displayed pitches (G4=67, C5=72)
            staves = verify_musescore.xml_staves(score_path)
            self.assertEqual(staves, [('P1 staff 1', [('1', [67, 72])])])

            # MuseScore conversion + verify_musescore.py must report 0 differences
            if not mscore_env.musescore_bin():
                self.skipTest('MuseScore not installed')
            res = subprocess.run(
                [sys.executable, os.path.join(TOOLS_DIR, 'verify_musescore.py'), score_path],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == '__main__':
    unittest.main()


def _make_voice_score(path, measures=1):
    """4/4 score; measure 1 has a whole C5 (voice 1) and a quarter G4 (voice 2)."""
    m = ['<measure number="1"><attributes>'
         '<divisions>1</divisions><key><fifths>0</fifths></key>'
         '<time><beats>4</beats><beat-type>4</beat-type></time>'
         '<clef><sign>G</sign><line>2</line></clef></attributes>']
    m.append('<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration>'
             '<voice>1</voice><type>whole</type><staff>1</staff></note>')
    m.append('<backup><duration>4</duration></backup>')
    m.append('<note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration>'
             '<voice>2</voice><type>quarter</type><staff>1</staff></note>')
    m.append('<note><rest/><duration>3</duration><voice>2</voice>'
             '<type>half</type><dot/><staff>1</staff></note>')
    m.append('</measure>')
    for i in range(2, measures + 1):
        m.append(f'<measure number="{i}"><note><pitch><step>E</step><octave>4</octave>'
                 f'</pitch><duration>4</duration><voice>1</voice><type>whole</type>'
                 f'<staff>1</staff></note></measure>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<score-partwise version="3.1"><part-list><score-part id="P1">'
           '<part-name>Strings I</part-name><part-abbreviation>Str. I</part-abbreviation>'
           '</score-part></part-list><part id="P1">' + ''.join(m) + '</part></score-partwise>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(xml)


def _map_file(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('page_unit\tsystem\traw_measure\tfinal_measure\tstatus\n')
        for page, system, raw, final, status in rows:
            f.write(f'{page}\t{system}\t{raw}\t{final}\t{status}\n')


class TestOttavaTimeAndMap(unittest.TestCase):
    def test_stop_uses_end_exclusive_tick_not_document_last_group(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            _make_voice_score(score)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t1\t1\t1\tend\n')
            apply_ottava.main(score, hints)
            part = ET.parse(score).getroot().find('part')
            # the range ends with voice 1's whole note at tick 4, not with the document-last
            # quarter note (tick 1); the stop is end-exclusive there
            intervals = score_time.octave_intervals(part)
            self.assertEqual(intervals[0].end, F(4))
            self.assertEqual(score_time.shift_at(intervals, '1', F(3)), 1)
            self.assertEqual(score_time.shift_at(intervals, '1', F(4)), 0)
            self.assertEqual(verify_musescore.xml_staves(score),
                             [('P1 staff 1', [('1', [67, 72])])])

    def test_measure_map_rejects_deleted_measure(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            mpath = os.path.join(d, 'measure_map.tsv')
            _make_voice_score(score, measures=3)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t3\t1\t3\tend\n')
            _map_file(mpath, [('p01', '1', '1', '1', 'kept'),
                              ('p01', '1', '2', '2', 'kept'),
                              ('p01', '1', '3', '-', 'deleted')])
            with self.assertRaises(SystemExit) as e:
                apply_ottava.main(score, hints, mpath)
            self.assertIn('deleted', str(e.exception))
            self.assertIsNone(ET.parse(score).getroot().find('.//octave-shift'))

    def test_measure_map_rejects_ambiguous_raw_coordinate(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            mpath = os.path.join(d, 'measure_map.tsv')
            _make_voice_score(score, measures=2)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t2\t1\t2\tend\n')
            _map_file(mpath, [('p01', '1', '2', '1', 'kept'),
                              ('p02', '1', '2', '2', 'kept')])
            with self.assertRaises(SystemExit) as e:
                apply_ottava.main(score, hints, mpath, True)
            self.assertIn('ambiguous', str(e.exception))

    def test_measure_map_converts_raw_coordinate(self):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            hints = os.path.join(d, 'ottava.txt')
            mpath = os.path.join(d, 'measure_map.tsv')
            _make_voice_score(score, measures=3)
            with open(hints, 'w', encoding='utf-8') as f:
                f.write('Str. I\t1\t8va\t3\t1\t3\tend\n')
            _map_file(mpath, [('p01', '1', '1', '1', 'kept'),
                              ('p01', '1', '2', '2', 'kept'),
                              ('p02', '1', '1', '2', 'kept'),
                              ('p02', '1', '3', '3', 'kept')])
            apply_ottava.main(score, hints, mpath, True)
            root = ET.parse(score).getroot()
            m3 = root.findall('part/measure')[2]
            self.assertIsNotNone(m3.find("direction/direction-type/octave-shift[@type='down']"))
