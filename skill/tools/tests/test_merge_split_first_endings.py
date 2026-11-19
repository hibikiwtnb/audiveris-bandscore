import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bandscore_postprocess as bp


def _score(parts):
    """Build a minimal score-partwise root.

    parts: {part_id: [measure_spec, ...]}; a measure_spec is a list of
    ('ending', number, type) and ('repeat', direction) tuples in barline order.
    """
    root = ET.Element('score-partwise')
    for pid, specs in parts.items():
        part = ET.SubElement(root, 'part', {'id': pid})
        for idx, spec in enumerate(specs, 1):
            m = ET.SubElement(part, 'measure', {'number': str(idx)})
            if not spec:
                continue
            bar = ET.SubElement(m, 'barline', {'location': 'right'})
            for item in spec:
                if item[0] == 'ending':
                    ET.SubElement(bar, 'ending', {'number': item[1], 'type': item[2]})
                else:
                    ET.SubElement(bar, 'repeat', {'direction': item[1]})
    return root


def _marks(root, pid='P1'):
    out = []
    for m in root.findall(f"part[@id='{pid}']/measure"):
        out.append(([(e.get('number'), e.get('type')) for e in m.findall('barline/ending')],
                    [r.get('direction') for r in m.findall('barline/repeat')]))
    return out


A = ('ending', '1', 'start'), ('ending', '1', 'discontinue')


class TestMergeSplitFirstEndings(unittest.TestCase):
    def test_merges_long_split_first_ending(self):
        # 244 m43..m71 / 004 m61..m108 shape
        root = _score({'P1': [list(A), [], [], [], [('ending', '1', 'start'),
                                                    ('ending', '1', 'stop'),
                                                    ('repeat', 'backward')],
                             [('ending', '2', 'start'), ('ending', '2', 'discontinue')]]})
        rep = {}
        bp.merge_split_first_endings(root, rep)
        marks = _marks(root)
        self.assertEqual(marks[0], ([('1', 'start')], []))
        self.assertEqual(marks[4], ([('1', 'stop')], ['backward']))
        self.assertEqual(marks[5], ([('2', 'start'), ('2', 'discontinue')], []))
        self.assertEqual(rep['split_endings_merged'], ['P1 m1-m5'])

    def test_discontinue_at_backward_becomes_stop(self):
        # 038 m61..m77 shape: the closing fragment says start+discontinue, not stop
        root = _score({'P1': [list(A), [],
                             [('ending', '1', 'start'), ('ending', '1', 'discontinue'),
                              ('repeat', 'backward')]]})
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root)[2], ([('1', 'stop')], ['backward']))
        self.assertEqual(rep['split_endings_merged'], ['P1 m1-m3'])

    def test_leaves_stray_discontinue_alone(self):
        # 071 m131 shape: a start+discontinue with no later closing ending
        root = _score({'P1': [[('ending', '1', 'start'), ('ending', '1', 'stop'),
                              ('repeat', 'backward')], list(A)]})
        before = _marks(root)
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), before)
        self.assertNotIn('split_endings_merged', rep)

    def test_does_not_cross_another_ending(self):
        root = _score({'P1': [list(A), [('ending', '1', 'start'), ('ending', '1', 'stop')],
                             [('ending', '1', 'start'), ('ending', '1', 'stop'),
                              ('repeat', 'backward')]]})
        before = _marks(root)
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), before)
        self.assertNotIn('split_endings_merged', rep)

    def test_does_not_cross_forward_repeat(self):
        root = _score({'P1': [list(A), [('repeat', 'forward')],
                             [('ending', '1', 'start'), ('ending', '1', 'stop'),
                              ('repeat', 'backward')]]})
        before = _marks(root)
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), before)
        self.assertNotIn('split_endings_merged', rep)

    def test_does_not_cross_other_number(self):
        root = _score({'P1': [list(A), [('ending', '2', 'start'), ('ending', '2', 'stop'),
                                       ('repeat', 'backward')]]})
        before = _marks(root)
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), before)
        self.assertNotIn('split_endings_merged', rep)

    def test_requires_backward_repeat_at_the_closing_ending(self):
        root = _score({'P1': [list(A), [('ending', '1', 'start'),
                                       ('ending', '1', 'stop')]]})
        before = _marks(root)
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), before)
        self.assertNotIn('split_endings_merged', rep)

    def test_is_idempotent(self):
        root = _score({'P1': [list(A), [],
                             [('ending', '1', 'start'), ('ending', '1', 'stop'),
                              ('repeat', 'backward')]]})
        rep = {}
        bp.merge_split_first_endings(root, rep)
        once = _marks(root)
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root), once)
        self.assertEqual(rep['split_endings_merged'], ['P1 m1-m3'])

    def test_parts_are_handled_independently(self):
        p1 = [list(A), [], [('ending', '1', 'start'), ('ending', '1', 'stop'),
                            ('repeat', 'backward')]]
        p2 = [list(A), []]
        root = _score({'P1': p1, 'P2': p2})
        rep = {}
        bp.merge_split_first_endings(root, rep)
        self.assertEqual(_marks(root, 'P1')[2], ([('1', 'stop')], ['backward']))
        self.assertEqual(_marks(root, 'P2')[0], ([('1', 'start'), ('1', 'discontinue')], []))
        self.assertEqual(rep['split_endings_merged'], ['P1 m1-m3'])

    def test_does_not_rewrite_other_content(self):
        root = _score({'P1': [list(A), [],
                             [('ending', '1', 'start'), ('ending', '1', 'stop'),
                              ('repeat', 'backward')]]})
        note = ET.SubElement(root.find('part/measure'), 'note')
        ET.SubElement(note, 'duration').text = '1'
        bp.merge_split_first_endings(root, {})
        self.assertEqual(root.findtext('part/measure/note/duration'), '1')


if __name__ == '__main__':
    unittest.main()
