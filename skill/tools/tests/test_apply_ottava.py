import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
import apply_ottava  # noqa: E402
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
            res = subprocess.run(
                [sys.executable, os.path.join(TOOLS_DIR, 'verify_musescore.py'), score_path],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == '__main__':
    unittest.main()
