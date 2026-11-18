import sys
import os
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
            ET.SubElement(p, 'step').text = 'C'
            ET.SubElement(p, 'octave').text = '4'
            ET.SubElement(n, 'duration').text = '1'
        if non_rest == 0:
            n = ET.SubElement(m, 'note')
            ET.SubElement(n, 'rest', {'measure': 'yes'})
            ET.SubElement(n, 'duration').text = '4'
    return root


class TestPrunePageEdgeMeasures(unittest.TestCase):
    def test_prunes_spurious_measure_when_next_page_has_key(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (80, 2, None)])
        p2 = _make_page([(450, 4, 3), (400, 4, None)])
        rep = {}
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], rep)
        self.assertEqual(len(p1.findall('part/measure')), 2)
        self.assertEqual(len(rep.get('page_edge_pruned', [])), 1)

    def test_moves_key_when_only_trailing_measure_has_key(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (85, 1, 5)])
        p2 = _make_page([(450, 4, None), (400, 4, None)])
        rep = {}
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], rep)
        self.assertEqual(len(p1.findall('part/measure')), 2)
        first_p2 = p2.find('part/measure')
        self.assertEqual(first_p2.findtext('attributes/key/fifths'), '5')

    def test_keeps_normal_width_or_real_notes(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (250, 2, None)])
        p2 = _make_page([(450, 4, 3)])
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], {})
        self.assertEqual(len(p1.findall('part/measure')), 3)

        p3 = _make_page([(400, 4, None), (400, 4, None), (80, 4, None)])
        bp.prune_page_edge_measures([('p3', p3), ('p2', p2)], {})
        self.assertEqual(len(p3.findall('part/measure')), 3)

    def test_keeps_when_no_key_on_either_side(self):
        p1 = _make_page([(400, 4, None), (400, 4, None), (80, 1, None)])
        p2 = _make_page([(450, 4, None)])
        bp.prune_page_edge_measures([('p1', p1), ('p2', p2)], {})
        self.assertEqual(len(p1.findall('part/measure')), 3)


if __name__ == '__main__':
    unittest.main()
