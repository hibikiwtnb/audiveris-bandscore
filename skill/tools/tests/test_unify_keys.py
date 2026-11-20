import contextlib
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unify_keys


def _add_key(measure, fifths, number=None):
    attrs = measure.find('attributes')
    if attrs is None:
        attrs = ET.SubElement(measure, 'attributes')
    attrib = {'number': str(number)} if number is not None else {}
    key = ET.SubElement(attrs, 'key', attrib)
    ET.SubElement(key, 'fifths').text = str(fifths)
    return key


def _build_score(parts_spec):
    """Build a minimal score-partwise tree from {part_id: {'measures': [...], ...}}."""
    root = ET.Element('score-partwise')
    for pid, spec in parts_spec.items():
        part = ET.SubElement(root, 'part', {'id': pid})
        for idx, m_keys in enumerate(spec['measures'], start=1):
            m = ET.SubElement(part, 'measure', {'number': str(idx)})
            if idx == 1:
                attrs = ET.SubElement(m, 'attributes')
                if spec.get('staves'):
                    ET.SubElement(attrs, 'staves').text = str(spec['staves'])
                if spec.get('percussion'):
                    clef = ET.SubElement(attrs, 'clef')
                    ET.SubElement(clef, 'sign').text = 'percussion'
                if spec.get('transpose') is not None:
                    tr = ET.SubElement(attrs, 'transpose')
                    ET.SubElement(tr, 'diatonic').text = '0'
                    ET.SubElement(tr, 'chromatic').text = str(spec['transpose'])
            for number, fifths in m_keys:
                _add_key(m, fifths, number=number)
    return root


def _run_unify(root):
    with tempfile.NamedTemporaryFile('wb', suffix='.musicxml', delete=False) as tf:
        path = tf.name
    try:
        ET.ElementTree(root).write(path, encoding='UTF-8', xml_declaration=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            unify_keys.main(path)
        out_root = ET.parse(path).getroot()
        return out_root, buf.getvalue()
    finally:
        if os.path.exists(path):
            os.remove(path)


def _measure_keys(root, pid, measure_idx):
    part = next(p for p in root.findall('part') if p.get('id') == pid)
    m = part.findall('measure')[measure_idx]
    return [(k.get('number'), k.findtext('fifths')) for k in m.findall('attributes/key')]


class TestUnifyKeys(unittest.TestCase):
    def test_half_staff_key_change_when_other_parts_change(self):
        root = _build_score({
            'P1': {'staves': 2, 'measures': [[(None, '0')], [(2, '-2')]]},
            'P2': {'measures': [[(None, '0')], [(None, '-2')]]},
            'P3': {'measures': [[(None, '0')], [(None, '-2')]]},
        })
        out, _ = _run_unify(root)
        self.assertEqual(_measure_keys(out, 'P1', 0), [(None, '0')])
        self.assertEqual(_measure_keys(out, 'P1', 1), [(None, '-2')])
        self.assertIsNone(out.find('.//part[@id="P1"]//attributes/key[@number]'))

    def test_redundant_numbered_key_is_normalized(self):
        root = _build_score({
            'P1': {'staves': 2, 'measures': [[(None, '0')], [(None, '-4')], [(1, '-4')]]},
            'P2': {'measures': [[(None, '0')], [(None, '-4')], []]},
        })
        out, _ = _run_unify(root)
        self.assertEqual(_measure_keys(out, 'P1', 1), [(None, '-4')])
        self.assertEqual(_measure_keys(out, 'P1', 2), [])
        self.assertIsNone(out.find('.//part[@id="P1"]//attributes/key[@number]'))

    def test_lone_half_staff_key_change_does_not_create_score_wide_key(self):
        root = _build_score({
            'P1': {'staves': 2, 'measures': [[(None, '0')], [(2, '-2')], []]},
            'P2': {'measures': [[(None, '0')], [], []]},
            'P3': {'measures': [[(None, '0')], [], []]},
        })
        out, _ = _run_unify(root)
        self.assertEqual(_measure_keys(out, 'P1', 0), [(None, '0')])
        self.assertEqual(_measure_keys(out, 'P1', 1), [])
        self.assertEqual(_measure_keys(out, 'P2', 1), [])
        self.assertEqual(_measure_keys(out, 'P3', 1), [])
        self.assertIsNone(out.find('.//part[@id="P1"]//attributes/key[@number]'))

    def test_conflicting_staff_keys_uses_other_parts_timeline_and_logs(self):
        root = _build_score({
            'P1': {'staves': 2, 'measures': [[(None, '0')], [(1, '0'), (2, '-2')]]},
            'P2': {'measures': [[(None, '0')], [(None, '-2')]]},
            'P3': {'measures': [[(None, '0')], [(None, '-2')]]},
        })
        out, stdout = _run_unify(root)
        self.assertIn('conflicting', stdout.lower())
        self.assertEqual(_measure_keys(out, 'P1', 1), [(None, '-2')])
        self.assertIsNone(out.find('.//part[@id="P1"]//attributes/key[@number]'))

    def test_skips_transposing_and_percussion_parts(self):
        root = _build_score({
            'P1': {'staves': 2, 'measures': [[(None, '0')], [(2, '-2')]]},
            'P2': {'measures': [[(None, '0')], [(None, '-2')]]},
            'P3': {'transpose': -2, 'measures': [[(None, '2')], [(1, '0')]]},
            'P4': {'percussion': True, 'measures': [[(None, '0')], [(1, '0')]]},
        })
        out, _ = _run_unify(root)
        self.assertEqual(_measure_keys(out, 'P1', 1), [(None, '-2')])
        self.assertEqual(_measure_keys(out, 'P3', 1), [('1', '0')])
        self.assertEqual(_measure_keys(out, 'P4', 1), [('1', '0')])


if __name__ == '__main__':
    unittest.main()
