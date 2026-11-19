import sys
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bandscore_postprocess as bp


def _make_page(measures_spec):
    """Build a minimal score-partwise root from [(width, non_rest, fifths_or_none), ...]."""
    root = ET.Element('score-partwise')
    part = ET.SubElement(root, 'part', {'id': 'P1'})
    for idx, (width, non_rest, fifths) in enumerate(measures_spec, 1):
        m = ET.SubElement(part, 'measure', {'number': str(idx), 'width': str(width)})
        if fifths is not None:
            attrs = ET.SubElement(m, 'attributes')
            ET.SubElement(attrs, 'divisions').text = '1'
            key = ET.SubElement(attrs, 'key')
            ET.SubElement(key, 'fifths').text = str(fifths)
        for _ in range(non_rest):
            n = ET.SubElement(m, 'note')
            p = ET.SubElement(n, 'pitch')
            ET.SubElement(p, 'step').text = 'E'
            ET.SubElement(p, 'octave').text = '4'
            ET.SubElement(n, 'duration').text = '2'
        if non_rest == 0:
            n = ET.SubElement(m, 'note')
            ET.SubElement(n, 'rest', {'measure': 'yes'})
            ET.SubElement(n, 'duration').text = '4'
    return root


def _count(root):
    return len(root.findall('part/measure'))


class TestPrunePageEdgeMeasures(unittest.TestCase):
    def test_keeps_297_p12_shape_without_list(self):
        # 297_p12: last measure w=76 vs median 376, one E half note, next page opens with a key
        p1 = _make_page([(445, 8, None), (376, 8, None), (376, 8, None), (76, 1, None)])
        p2 = _make_page([(450, 4, 3), (400, 4, None)])
        rep = {}
        bp.prune_page_edge_measures([('297_p12', p1), ('297_p13', p2)], rep)
        self.assertEqual(_count(p1), 4)
        self.assertEqual(rep['page_edge_candidates'], ['297_p12: m4 (w=76, med=376, notes=1)'])
        self.assertNotIn('page_edge_pruned', rep)

    def test_keeps_228_p06a_shape_without_list(self):
        # 228_p06a: last measure w=75 vs median 432.5, one non-rest note, no key on either side
        p1 = _make_page([(534, 8, None), (427, 8, None), (428, 8, None), (437, 8, None),
                         (75, 1, None)])
        p2 = _make_page([(450, 4, None)])
        bp.prune_page_edge_measures([('228_p06a', p1), ('228_p06b', p2)], {})
        self.assertEqual(_count(p1), 5)

    def test_removes_listed_measure_and_moves_key(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (85, 1, 5)])
        p2 = _make_page([(450, 4, None), (400, 4, None)])
        rep = {}
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], rep,
                                    {('p1', '3'): 'crop p1 right edge: courtesy key only'})
        self.assertEqual(_count(p1), 2)
        self.assertEqual(p2.find('part/measure').findtext('attributes/key/fifths'), '5')
        self.assertEqual(rep['page_edge_pruned'], ['p1: m3 (crop p1 right edge: courtesy key only)'])

    def test_refuses_listed_measure_without_evidence(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (80, 1, None)])
        p2 = _make_page([(450, 4, 3)])
        rep = {}
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], rep, {('p1', '3'): ''})
        self.assertEqual(_count(p1), 3)
        self.assertEqual(rep['page_edge_rejected'], ['p1: m3 (no evidence)'])

    def test_list_entry_for_other_measure_keeps_last(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (80, 1, None)])
        p2 = _make_page([(450, 4, 3)])
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], {}, {('p1', '2'): 'crop'})
        self.assertEqual(_count(p1), 3)

    def test_read_page_edge_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'page_edge_prune.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('# page measure evidence\n'
                        'p10b 5 crop p10b right edge: courtesy key signature only\n'
                        'p16a 5\n')
            self.assertEqual(bp.read_page_edge_list(path), {
                ('p10b', '5'): 'crop p10b right edge: courtesy key signature only',
                ('p16a', '5'): ''})
            self.assertEqual(bp.read_page_edge_list(os.path.join(d, 'missing.txt')), {})


if __name__ == '__main__':
    unittest.main()
