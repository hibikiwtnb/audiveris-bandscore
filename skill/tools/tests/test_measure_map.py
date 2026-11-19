import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import measure_map  # noqa: E402


def _page(name, numbers, systems):
    """Root with one part; systems = first measure index (0-based) of each new system."""
    root = ET.Element('score-partwise')
    part = ET.SubElement(root, 'part', {'id': 'P1'})
    for i, num in enumerate(numbers):
        m = ET.SubElement(part, 'measure', {'number': str(num)})
        if i in systems:
            ET.SubElement(m, 'print', {'new-system': 'yes'})
    return name, root


class TestMeasureMap(unittest.TestCase):
    def test_final_numbering_and_deleted_rows(self):
        pages = [_page('p01', [1, 2, 3], {0, 1}),
                 _page('p02', [2, 3], {0})]
        rows = measure_map.build_map(pages, [('p01', '3')])
        self.assertEqual([(r['page'], r['system'], r['raw'], r['final'], r['status'])
                          for r in rows],
                         [('p01', '1', '1', '1', 'kept'),
                          ('p01', '2', '2', '2', 'kept'),
                          ('p01', '2', '3', None, 'deleted'),
                          ('p02', '1', '2', '3', 'kept'),
                          ('p02', '1', '3', '4', 'kept')])

    def test_deleted_measure_missing_from_survivors_is_appended(self):
        rows = measure_map.build_map([_page('p01', [1, 2], {0})], [('p01', '3')])
        self.assertEqual(rows[-1], dict(page='p01', system='1', raw='3',
                                        final=None, status='deleted'))

    def test_resolve_final_raw_deleted_and_ambiguous(self):
        rows = measure_map.build_map(
            [_page('p01', [1, 2, 3], {0}), _page('p02', [1, 4], {0})],
            [('p01', '3')])
        self.assertEqual(measure_map.resolve_measure('2', rows), '2')
        self.assertEqual(measure_map.resolve_measure('2', rows, raw=True), '2')
        with self.assertRaises(ValueError) as e:
            measure_map.resolve_measure('3', rows, raw=True)
        self.assertIn('deleted', str(e.exception))
        with self.assertRaises(ValueError):
            measure_map.resolve_measure('9', rows)
        rows.append(dict(page='p03', system='1', raw='2', final='5', status='kept'))
        with self.assertRaises(ValueError) as e:
            measure_map.resolve_measure('2', rows, raw=True)
        self.assertIn('ambiguous', str(e.exception))

    def test_write_read_roundtrip(self):
        rows = measure_map.build_map([_page('p01', [1, 2], {0})], [('p01', '2')])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'measure_map.tsv')
            measure_map.write_map(path, rows)
            self.assertEqual(measure_map.read_map(path), rows)


if __name__ == '__main__':
    unittest.main()
