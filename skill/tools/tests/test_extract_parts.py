import io
import os
import sys
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extract_parts  # noqa: E402
from proof_pairs import read_systems  # noqa: E402


def _omr(path, staves):
    """A minimal .omr: shelf system with one stack and the given printed staves."""
    parts = ''.join(
        '<part logical-id="%d"><staff id="%d"><lines><line><point x="10" y="%d"/>'
        '<point x="100" y="%d"/></line></lines></staff></part>'
        % (lid, i, top, bottom) for i, (lid, top, bottom) in enumerate(staves, 1))
    book = ('<?xml version="1.0"?><book><score>'
            '<logical-part id="1" name="Vocal"/><logical-part id="2" name="Guitar"/>'
            '</score><sheet number="1"><page id="1"><system>%s</system></page></sheet></book>'
            % parts)
    sheet = ('<?xml version="1.0"?><sheet><picture width="120" height="500"/>'
             '<scale><interline main="10"/></scale><page id="1"><system>'
             '<stack id="1" left="10" right="100"/>%s</system></page></sheet>' % parts)
    buf = io.BytesIO()
    Image.new('L', (120, 500), 255).save(buf, format='PNG')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('book.xml', book)
        z.writestr('sheet#1/sheet#1.xml', sheet)
        z.writestr('sheet#1/BINARY.png', buf.getvalue())


class TestReadSystems(unittest.TestCase):
    def test_repeated_logical_id_keeps_every_printed_staff(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.omr')
            _omr(path, [(1, 20, 60), (2, 100, 140), (2, 180, 220)])
            _, interline, systems = read_systems(path, 1)
        self.assertEqual(interline, 10)
        self.assertEqual(systems[0]['parts'][1], [(20.0, 60.0)])
        self.assertEqual(systems[0]['parts'][2], [(100.0, 140.0), (180.0, 220.0)])


class TestFindSplit(unittest.TestCase):
    def setUp(self):
        self.arr = np.full((200, 300), 255, np.uint8)
        self.arr[30:40, :] = 0
        self.arr[150:160, :] = 0

    def test_picks_blank_band_near_prefer(self):
        y, clean = extract_parts.find_split(self.arr, 10, 10, 290, 40, 150, 95)
        self.assertTrue(clean)
        self.assertLessEqual(60, y)
        self.assertLessEqual(y, 100)

    def test_falls_back_when_no_clean_band(self):
        band = np.full((200, 300), 255, np.uint8)
        band[40:160, 10:20] = 0
        y, clean = extract_parts.find_split(band, 10, 10, 290, 40, 160, 100)
        self.assertFalse(clean)
        self.assertEqual(y, 100)


class TestPartCrop(unittest.TestCase):
    def test_absent_part_returns_none_and_gaps_are_cut(self):
        image = Image.new('L', (300, 500), 255)
        arr = np.asarray(image)
        system = dict(stacks=[(20, 280)], parts={1: [(50.0, 90.0)], 2: [(200.0, 250.0)],
                                                3: [(350.0, 400.0)]})
        gaps = []
        cropped = extract_parts.part_crop(arr, image, 10, system, 2, 10, 290, gaps)
        self.assertIsNotNone(cropped)
        self.assertGreater(cropped.height, 50)
        self.assertEqual(extract_parts.part_crop(arr, image, 10, system, 9, 10, 290, gaps), None)
        self.assertEqual(gaps, [])

    def test_part_names_are_not_in_filename(self):
        self.assertEqual(extract_parts.safe_name('E.Guitar I'), 'E.Guitar_I')
        self.assertEqual(extract_parts.safe_name(''), 'part')


if __name__ == '__main__':
    unittest.main()
