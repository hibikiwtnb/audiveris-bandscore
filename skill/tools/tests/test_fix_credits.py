import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fix_credits  # noqa: E402

CREDIT = ('<credit page="1"><credit-type>composer</credit-type>'
          '<credit-words default-y="{}">{}</credit-words></credit>')
NOISE = ('<credit page="{}"><credit-words>{}</credit-words></credit>')
ATTR = ('<attributes><divisions>4</divisions><key><fifths>0</fifths></key>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '<clef><sign>G</sign><line>2</line></clef></attributes>')


def build_score(credits, words='', identification='', words_measure=2):
    bodies = []
    for number in (1, 2, 3):
        print_el = '<print new-system="yes"/>' if number in (1, 3) else ''
        body = f'<measure number="{number}">{print_el}'
        if number == 1:
            body += ATTR
        if number == words_measure:
            body += words
        bodies.append(body + '</measure>')
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<score-partwise version="4.0.3">'
            f'<identification>{identification}</identification>'
            f'{credits}'
            '<part-list><score-part id="P1"><part-name>Piccolo</part-name></score-part>'
            '</part-list>'
            '<part id="P1">'
            + ''.join(bodies)
            + '</part></score-partwise>')


class FixCreditsTest(unittest.TestCase):

    def run_fix(self, xml, meta=None):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'score.musicxml')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(xml)
        meta_path = None
        if meta is not None:
            meta_path = os.path.join(tmp, 'song_metadata.md')
            with open(meta_path, 'w', encoding='utf-8') as f:
                f.write(meta)
        fix_credits.main(path, meta_path)
        with open(path, encoding='utf-8') as f:
            once = f.read()
        fix_credits.main(path, meta_path)
        with open(path, encoding='utf-8') as f:
            twice = f.read()
        self.assertEqual(once, twice)
        return ET.fromstring(once)

    def test_merge_authors_and_title(self):
        credits = (CREDIT.format(3200, 'Lyrics by A. Author')
                   + CREDIT.format(3190, 'Composed, Arranged by B. Writer')
                   + NOISE.format(2, '201'))
        words = ('<direction placement="above"><direction-type>'
                 '<words>Orchestrated by C. Editor</words>'
                 '</direction-type></direction>')
        ident = '<creator type="composer">Lyrics by A. Author</creator>'
        root = self.run_fix(build_score(credits, words, ident),
                            '# x\n- Title: テスト曲（シリーズ）\n')
        self.assertIsNone(root.find('credit'))
        self.assertEqual(root.findtext('work/work-title'), 'テスト曲')
        creators = root.findall('identification/creator')
        self.assertEqual(len(creators), 1)
        self.assertEqual(creators[0].get('type'), 'composer')
        self.assertEqual(creators[0].text,
                         'Lyrics by A. Author\nComposed, Arranged by B. Writer\n'
                         'Orchestrated by C. Editor')
        self.assertIsNone(root.find('part/measure[@number="2"]/direction'))

    def test_page_number_credits_are_not_authors(self):
        credits = (NOISE.format(1, '12') + NOISE.format(2, '13')
                   + NOISE.format(9, '208'))
        root = self.run_fix(build_score(credits))
        left = root.findall('credit')
        self.assertEqual([c.get('page') for c in left], ['1'])
        self.assertEqual(fix_credits.credit_text(left[0]), '12')
        self.assertIsNone(root.find('work/work-title'))

    def test_words_after_first_system_are_left_alone(self):
        words = ('<direction placement="above"><direction-type>'
                 '<words>Composed by Someone</words>'
                 '</direction-type></direction>')
        root = self.run_fix(build_score('', words, words_measure=3))
        self.assertIsNotNone(root.find('part/measure[@number="3"]/direction'))


if __name__ == '__main__':
    unittest.main()
