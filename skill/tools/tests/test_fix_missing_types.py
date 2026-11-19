import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bandscore_postprocess as bp


def _note(measure, dur, typ=None, tm=None, beams=0, rest=False, voice='1'):
    n = ET.SubElement(measure, 'note')
    if rest:
        ET.SubElement(n, 'rest')
    else:
        p = ET.SubElement(n, 'pitch')
        ET.SubElement(p, 'step').text = 'C'
        ET.SubElement(p, 'octave').text = '4'
    ET.SubElement(n, 'duration').text = str(dur)
    ET.SubElement(n, 'voice').text = voice
    if typ:
        ET.SubElement(n, 'type').text = typ
    if tm:
        e = ET.SubElement(n, 'time-modification')
        ET.SubElement(e, 'actual-notes').text = str(tm[0])
        ET.SubElement(e, 'normal-notes').text = str(tm[1])
    for i in range(beams):
        b = ET.SubElement(n, 'beam')
        b.set('number', str(i + 1))
        b.text = 'continue'
    return n


def _score(div, notes):
    root = ET.Element('score-partwise')
    part = ET.SubElement(root, 'part', {'id': 'P1'})
    m = ET.SubElement(part, 'measure', {'number': '1'})
    a = ET.SubElement(m, 'attributes')
    ET.SubElement(a, 'divisions').text = str(div)
    t = ET.SubElement(a, 'time')
    ET.SubElement(t, 'beats').text = '4'
    ET.SubElement(t, 'beat-type').text = '4'
    for spec in notes:
        _note(m, **spec)
    return root, m


def _fix(root):
    report = {'type_fixed': [], 'type_skipped': []}
    stats = bp.fix_missing_values(root, report)
    return stats, report


def _written(m):
    return [(n.findtext('type'), int(n.findtext('duration')))
            for n in m.findall('note')]


class TestFixMissingTypes(unittest.TestCase):
    def test_a1_adds_type_from_time_modification(self):
        root, m = _score(12, [dict(dur=46, typ='half'), dict(dur=2, tm=(3, 2))])
        stats, _ = _fix(root)
        self.assertEqual(stats, {'A1': 1})
        self.assertEqual(_written(m)[-1], ('16th', 2))
        self.assertEqual(m.findall('note')[-1].findtext('time-modification/actual-notes'), '3')

    def test_b_infers_type_and_tuplet_from_beam(self):
        root, m = _score(12, [dict(dur=44, typ='half'), dict(dur=4, beams=1)])
        stats, _ = _fix(root)
        self.assertEqual(stats, {'B': 1})
        last = m.findall('note')[-1]
        self.assertEqual(last.findtext('type'), 'eighth')
        self.assertEqual(last.findtext('time-modification/actual-notes'), '3')
        self.assertEqual(last.findtext('time-modification/normal-notes'), '2')

    def test_c_splits_long_note_into_tied_chain(self):
        root, m = _score(8, [dict(dur=22, typ='half'), dict(dur=10)])
        stats, _ = _fix(root)
        self.assertEqual(stats, {'C': 1})
        notes = m.findall('note')
        self.assertEqual(len(notes), 3)
        self.assertEqual([n.findtext('type') for n in notes[1:]], ['quarter', '16th'])
        self.assertEqual(sum(int(n.findtext('duration')) for n in notes[1:]), 10)
        self.assertEqual([t.get('type') for t in notes[1].findall('tie')], ['start'])
        self.assertEqual([t.get('type') for t in notes[2].findall('tie')], ['stop'])

    def test_d_splits_rest_preserving_total(self):
        root, m = _score(16, [dict(dur=44, typ='half'), dict(dur=20, rest=True)])
        stats, _ = _fix(root)
        self.assertEqual(stats, {'D': 1})
        rests = [n for n in m.findall('note') if n.find('rest') is not None]
        self.assertEqual([n.findtext('type') for n in rests], ['quarter', '16th'])
        self.assertEqual(sum(int(n.findtext('duration')) for n in rests), 20)

    def test_legal_tuplet_is_unchanged(self):
        root, m = _score(12, [dict(dur=46, typ='half'), dict(dur=2, typ='eighth', tm=(3, 2))])
        stats, report = _fix(root)
        self.assertEqual(stats, {})
        self.assertFalse(report['type_fixed'])
        self.assertEqual(_written(m)[-1], ('eighth', 2))

    def test_short_measure_is_not_touched(self):
        root, m = _score(12, [dict(dur=2, tm=(3, 2))])
        stats, _ = _fix(root)
        self.assertEqual(stats, {})
        self.assertIsNone(m.findall('note')[-1].findtext('type'))

    def test_non_tail_note_is_not_touched(self):
        root, m = _score(12, [dict(dur=2, tm=(3, 2)), dict(dur=46, typ='half')])
        stats, _ = _fix(root)
        self.assertEqual(stats, {})
        self.assertIsNone(m.findall('note')[0].findtext('type'))

    def test_incomplete_six_tuplet_is_left_for_rebuild(self):
        root, m = _score(12, [dict(dur=44, typ='half'),
                              dict(dur=2, typ='16th', tm=(6, 4)),
                              dict(dur=2, tm=(6, 4))])
        stats, report = _fix(root)
        self.assertEqual(stats, {})
        self.assertTrue(any('A2 incomplete 6-tuplet' in x for x in report['type_skipped']))
        self.assertIsNone(m.findall('note')[-1].findtext('type'))


if __name__ == '__main__':
    unittest.main()
