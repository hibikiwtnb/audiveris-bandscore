import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import verify_musescore  # noqa: E402

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<score-partwise version="3.1"><part-list><score-part id="P1">'
        '<part-name>Strings I</part-name><part-abbreviation>Str. I</part-abbreviation>'
        '</score-part></part-list><part id="P1">')
ATTR = ('<attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '<clef><sign>G</sign><line>2</line></clef></attributes>')


def note(step, octave, dur, voice='1', chord=False, grace=False):
    s = '<note>'
    if grace:
        s += '<grace/>'
    if chord:
        s += '<chord/>'
    s += f'<pitch><step>{step}</step><octave>{octave}</octave></pitch>'
    return s + f'<duration>{dur}</duration><voice>{voice}</voice><staff>1</staff></note>'


def shift(typ):
    return (f'<direction><direction-type><octave-shift type="{typ}" size="8" number="3"/>'
            '</direction-type><staff>1</staff></direction>')


def write(score, measures):
    with open(score, 'w', encoding='utf-8') as f:
        f.write(HEAD + ''.join(measures) + '</part></score-partwise>')


class TestVerifyTime(unittest.TestCase):
    def _staves(self, measures):
        with tempfile.TemporaryDirectory() as d:
            score = os.path.join(d, 'score.musicxml')
            write(score, measures)
            return verify_musescore.xml_staves(score)

    def test_document_order_and_backup_do_not_change_expected_pitches(self):
        a = [f'<measure number="1">{ATTR}{shift("down")}{note("C", 5, 4)}'
             f'<backup><duration>4</duration></backup>{note("G", 4, 4, voice="2")}</measure>']
        b = [f'<measure number="1">{ATTR}{shift("down")}{note("G", 4, 4, voice="2")}'
             f'<backup><duration>4</duration></backup>{note("C", 5, 4)}</measure>']
        self.assertEqual(self._staves(a), [('P1 staff 1', [('1', [55, 60])])])
        self.assertEqual(self._staves(a), self._staves(b))

    def test_stop_tick_is_end_exclusive(self):
        measures = [f'<measure number="1">{ATTR}{shift("down")}{note("C", 5, 2)}'
                    f'{shift("stop")}{note("D", 5, 2)}</measure>']
        # C5 sounds an octave up (display C5=72), D5 starts at the stop tick and stays
        self.assertEqual(self._staves(measures), [('P1 staff 1', [('1', [60, 74])])])

    def test_grace_note_does_not_move_the_cursor(self):
        measures = [f'<measure number="1">{ATTR}{note("C", 5, 1)}'
                    f'{note("D", 5, 1, grace=True)}{note("E", 5, 3)}</measure>']
        self.assertEqual(self._staves(measures), [('P1 staff 1', [('1', [72, 74, 76])])])

    def test_divisions_change_mid_score(self):
        measures = [
            f'<measure number="1">{ATTR}{note("C", 4, 4)}</measure>',
            '<measure number="2"><attributes><divisions>2</divisions></attributes>'
            f'{note("D", 4, 8)}</measure>',
        ]
        self.assertEqual(self._staves(measures),
                         [('P1 staff 1', [('1', [60]), ('2', [62])])])


if __name__ == '__main__':
    unittest.main()
