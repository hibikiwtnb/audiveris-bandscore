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


def _omr(path, staves, extra_sheets=()):
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
             '<stack id="1" left="10" right="100"/>%s'
             '<lyric-line role="Lyrics" staff="1"><bounds x="20" y="75" w="70" h="15"/></lyric-line>'
             '</system></page></sheet>' % parts)
    buf = io.BytesIO()
    Image.new('L', (120, 500), 255).save(buf, format='PNG')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('book.xml', book)
        z.writestr('sheet#1/sheet#1.xml', sheet)
        z.writestr('sheet#1/BINARY.png', buf.getvalue())
        for num, xml in extra_sheets:
            z.writestr('sheet#%d/sheet#%d.xml' % (num, num), xml)


class TestReadSystems(unittest.TestCase):
    def test_repeated_logical_id_keeps_every_printed_staff(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.omr')
            _omr(path, [(1, 20, 60), (2, 100, 140), (2, 180, 220)])
            _, interline, systems = read_systems(path, 1)
        self.assertEqual(interline, 10)
        self.assertEqual(systems[0]['parts'][1], [(20.0, 60.0)])
        self.assertEqual(systems[0]['parts'][2], [(100.0, 140.0), (180.0, 220.0)])

    def test_read_texts_reads_all_sheets_and_lyric_lines(self):
        sheet2 = ('<?xml version="1.0"?><sheet><page id="2"><system>'
                  '<part><staff id="1"/></part>'
                  '<lyric-line role="Lyrics" staff="1"><bounds x="15" y="80" w="60" h="12"/></lyric-line>'
                  '</system></page></sheet>')
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.omr')
            _omr(path, [(1, 20, 60), (2, 120, 160)], extra_sheets=[(2, sheet2)])
            boxes = extract_parts.read_texts(path)
        lyrics = [b for b in boxes if b['tag'] == 'lyric-line']
        self.assertEqual(len(lyrics), 2)
        self.assertEqual(lyrics[0]['lid'], 1)
        self.assertEqual((lyrics[0]['y'], lyrics[0]['h']), (75, 15))
        self.assertEqual((lyrics[1]['y'], lyrics[1]['h']), (80, 12))


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

    def test_connected_component_attribution_removes_neighbor_stem(self):
        arr = np.full((300, 300), 255, np.uint8)
        for y in range(40, 81, 10):
            arr[y:y + 2, 20:280] = 0   # upper 5-line staff (lid 1)
        arr[60:145, 120:124] = 0       # upper part stem extending down to y=145
        arr[135:175, 200:204] = 0      # lower part stem extending up to y=135 (overlap in y=135..145!)
        for y in range(175, 216, 10):
            arr[y:y + 2, 20:280] = 0   # lower 5-line staff (lid 2)
        image = Image.fromarray(arr)
        system = dict(stacks=[(20, 280)], parts={1: [(40.0, 80.0)], 2: [(175.0, 215.0)]})
        boxes = [
            dict(tag='stem', role='stem', staff=1, lid=1, system=0, x=120, y=60, w=4, h=85),
            dict(tag='stem', role='stem', staff=2, lid=2, system=0, x=200, y=135, w=4, h=60),
        ]
        gaps = []
        c2 = extract_parts.part_crop(arr, image, 10, system, 2, 10, 290, gaps, boxes=boxes)
        c2_arr = np.asarray(c2)
        # In part 2's crop, the neighbor stem at x=120..124 (crop x=110..114) above staff 2
        # must be erased to white (255), while part 2's own stem at x=200..204 (crop x=190..194)
        # above staff 2 remains black (0).
        self.assertEqual((c2_arr[:30, 110:114] < 128).sum(), 0)
        self.assertGreater((c2_arr[:30, 190:194] < 128).sum(), 0)


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

    def test_vocal_bottom_cuts_below_lyrics_not_staff_middle(self):
        arr = np.full((300, 300), 255, np.uint8)
        arr[40:80, 20:280] = 0    # vocal staff
        arr[110:128, 30:250] = 0  # vocal lyrics below staff
        arr[170:210, 20:280] = 0  # guitar staff below
        image = Image.fromarray(arr)
        system = dict(stacks=[(20, 280)], parts={1: [(40.0, 80.0)], 2: [(170.0, 210.0)]})
        boxes = [dict(tag='lyric-line', role='Lyrics', staff=1, lid=1, system=0,
                      x=30, y=110, w=220, h=18)]
        gaps = []
        v_crop = extract_parts.part_crop(arr, image, 10, system, 1, 10, 290, gaps,
                                         vocal=True, boxes=boxes)
        g_crop = extract_parts.part_crop(arr, image, 10, system, 2, 10, 290, gaps,
                                         vocal=False, boxes=boxes)
        self.assertEqual(gaps, [])
        # Vocal crop must include the lyric band at y=110..128 (top=28, so height >= 102)
        self.assertGreaterEqual(v_crop.height, 102)
        # Guitar crop must start below y=128 (bottom=240, so height <= 112)
        self.assertLessEqual(g_crop.height, 112)


if __name__ == '__main__':
    unittest.main()
