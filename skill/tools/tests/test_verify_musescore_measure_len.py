import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as F

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mscore_env  # noqa: E402
import verify_musescore  # noqa: E402

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<score-partwise version="3.1"><part-list><score-part id="P1">'
        '<part-name>Violin I</part-name><part-abbreviation>Vln. I</part-abbreviation>'
        '</score-part></part-list><part id="P1">')
ATTR = ('<attributes><divisions>24</divisions><key><fifths>2</fifths></key>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '<clef><sign>G</sign><line>2</line></clef></attributes>')


def note(step, octave, dur, typ, tm=None, tuplet=None):
    s = (f'<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>'
         f'<duration>{dur}</duration><voice>1</voice><type>{typ}</type>')
    if tm:
        s += (f'<time-modification><actual-notes>{tm[0]}</actual-notes>'
              f'<normal-notes>{tm[1]}</normal-notes></time-modification>')
    if tuplet:
        s += f'<notations><tuplet type="{tuplet}" number="1"/></notations>'
    return s + '</note>'


def plain_run(n):
    # 16ths at divisions=24: 12 plain 16ths fill 3 beats
    return ''.join(note(step, 5, 6, '16th') for step in ['B'] * n)


BROKEN = (HEAD + '<measure number="1">' + ATTR
          + plain_run(14)
          + note('F', 5, 4, '16th', tm=(6, 4), tuplet='start')
          + note('A', 5, 4, '16th', tm=(6, 4), tuplet='stop')
          + note('B', 5, 4, '16th', tm=(3, 2))
          + '</measure></part></score-partwise>')

FIXED = (HEAD + '<measure number="1">' + ATTR
         + plain_run(12)
         + note('B', 4, 4, '16th', tm=(6, 4), tuplet='start')
         + note('D', 5, 4, '16th', tm=(6, 4))
         + note('F', 5, 4, '16th', tm=(6, 4))
         + note('A', 5, 4, '16th', tm=(6, 4))
         + note('B', 5, 4, '16th', tm=(6, 4))
         + note('D', 6, 4, '16th', tm=(6, 4), tuplet='stop')
         + '</measure></part></score-partwise>')


def verify(xml_str):
    with tempfile.TemporaryDirectory() as td:
        score = os.path.join(td, 'score.musicxml')
        with open(score, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        return subprocess.run(
            [sys.executable, os.path.join(TOOLS_DIR, 'verify_musescore.py'), score],
            capture_output=True, text=True)


class TestMeasureLength(unittest.TestCase):
    def test_mscx_measure_lens_reads_len_and_none(self):
        mscx = ('<Staff id="1"><Measure><voice/></Measure>'
                '<Measure len="133/128"><voice/></Measure></Staff>')
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 's.mscx')
            with open(path, 'w', encoding='utf-8') as f:
                # duplicate the Staff after a Part so the parser finds its body
                f.write('<Part></Part>' + mscx)
            self.assertEqual(verify_musescore.mscx_measure_lens(path),
                             [[None, F(133, 128)]])

    def test_stray_tuplet_length_is_reported(self):
        if not mscore_env.musescore_bin():
            self.skipTest('MuseScore not installed')
        res = verify(BROKEN)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn('irregular measure length m1', res.stdout)

    def test_complete_sextuplet_is_accepted(self):
        if not mscore_env.musescore_bin():
            self.skipTest('MuseScore not installed')
        res = verify(FIXED)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn('irregular measure length', res.stdout)


if __name__ == '__main__':
    unittest.main()
