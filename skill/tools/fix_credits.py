#!/usr/bin/env python3
"""Normalize the first-page title frame (credits) of a merged score.  Idempotent.

    python3 tools/fix_credits.py <score.musicxml> [<context/song_metadata.md>]

Audiveris exports every line of the first-page author block (Lyrics by ...,
Composed ... by ..., Orchestrated by ...) as its own <credit>, so MuseScore
stacks them at the same position and they overlap.  The title is usually not
exported at all, and an author line drawn above the first system is sometimes
read as staff text instead of a credit.  Page numbers and OCR fragments from
later pages are exported as credits too.

An author line is a page-1 credit (or an above-staff <words> direction in the
first system of the first part) whose text starts with a credit role and
contains "by".  When any author line is found:

  * the lines are joined top to bottom into one composer creator;
  * the title from `- Title:` in song_metadata.md is written as work-title;
  * all page credits and the misplaced author directions are removed, so that
    MuseScore builds its standard title frame (centered title, right-aligned
    composer block) instead of importing the overlapping words.

Credits on pages after the first are page numbers or OCR fragments and are
always removed; they never belong in the merged score.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

ROLE_RE = re.compile(
    r'^(?:Lyrics?|Words?|Music|Composed|Composer|Arranged|Arranger|'
    r'Orchestrated|Orchestration|Transcribed|Transcription|Edited|Editor|'
    r'Published|Publisher|Written|Produced)\b.*\bby\b',
    re.I)
TITLE_PAREN_RE = re.compile(r'\s*[（(][^（()）]*[)）]\s*$')


def norm_text(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def is_author_line(text):
    return bool(ROLE_RE.match(norm_text(text)))


def title_from_metadata(path):
    if not path or not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s*[-*]\s*Title\s*[:：]\s*(.+?)\s*$', line)
            if m:
                return TITLE_PAREN_RE.sub('', m.group(1)).strip()
    return ''


def credit_text(credit):
    return norm_text(''.join(''.join(cw.itertext())
                             for cw in credit.findall('credit-words')))


def first_system_measures(measures):
    """Measures of the first system: up to the first new-system break after m1."""
    for i, m in enumerate(measures):
        pr = m.find('print')
        if i > 0 and pr is not None and pr.get('new-system') == 'yes':
            return measures[:i]
    return measures


def author_words(part):
    """Above-staff words in the first system that are really author lines."""
    found = []
    measures = first_system_measures(part.findall('measure'))
    for m in measures:
        for d in list(m.findall('direction')):
            if d.get('placement') != 'above':
                continue
            for w in d.findall('direction-type/words'):
                text = norm_text(''.join(w.itertext()))
                if is_author_line(text):
                    found.append(text)
                    m.remove(d)
                    break
    return found


def fix(root, metadata_path=None, report=None):
    report = report if report is not None else []
    credits = root.findall('credit')

    def page_of(c):
        try:
            return int(c.get('page', '1'))
        except ValueError:
            return 1

    author_credits = []
    for c in credits:
        if page_of(c) != 1:
            continue
        text = credit_text(c)
        if is_author_line(text):
            def ypos(cr):
                cw = cr.find('credit-words')
                try:
                    return float(cw.get('default-y'))
                except (AttributeError, TypeError, ValueError):
                    return float('-inf')
            author_credits.append((c, text, ypos(c)))
    author_credits.sort(key=lambda item: item[2], reverse=True)
    lines = [text for _, text, _ in author_credits]

    for part in root.findall('part')[:1]:
        lines.extend(author_words(part))

    title = title_from_metadata(metadata_path) if lines else ''

    # page numbers and OCR fragments after page 1 never belong in the merged score
    for c in credits:
        if page_of(c) != 1:
            root.remove(c)
            report.append(f'dropped page-{page_of(c)} credit: '
                          f'{credit_text(c)[:30]}')

    if not lines:
        return report

    for c, text, _ in author_credits:
        root.remove(c)
    report.append(f'merged {len(lines)} author line(s)')

    ident = root.find('identification')
    if ident is None:
        ident = ET.Element('identification')
        root.insert(1 if root.find('work') is not None else 0, ident)
    for cr in list(ident.findall('creator')):
        ident.remove(cr)
    creator = ET.Element('creator', {'type': 'composer'})
    creator.text = '\n'.join(lines)
    creator.tail = ident.text or ''
    ident.insert(0, creator)

    if title:
        work = root.find('work')
        if work is None:
            work = ET.Element('work')
            work.tail = root.text or ''
            work.text = '\n    '
            root.insert(0, work)
        wt = work.find('work-title')
        if wt is None:
            wt = ET.Element('work-title')
            wt.tail = '\n  '
            work.insert(0, wt)
        wt.text = title
        report.append(f'title: {title}')
    return report


def main(score_path, metadata_path=None):
    tree = ET.parse(score_path)
    report = fix(tree.getroot(), metadata_path)
    if report:
        tree.write(score_path, encoding='UTF-8', xml_declaration=True)
    for line in report:
        print(line)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: fix_credits.py <score.musicxml> [song_metadata.md]')
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
