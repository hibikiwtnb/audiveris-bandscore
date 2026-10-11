#!/usr/bin/env python3
"""Learn a book's symbol template from examples picked by eye.

    learn_template.py templates/<book> --name NAME --box B [--height H] --from PAGE IL X,Y X,Y ... [--from ...]

PAGE is a page as Audiveris reads it (input/omr_in/*.png).  Look at the pages, pick 3 or more
clear examples of the symbol (from one page or several, one --from per page) and give the
interline of the staff they are on (IL, page pixels, measured there: drum staves can be smaller
than the others) and their centers (X,Y, page pixels).  B is the side of a square that just
holds the symbol, in interlines; with H, the box is B wide and H high (a key signature sharp or
flat: narrow, so that the next one of the key signature stays out).  For a chord template (chord_<root>b: root letter and flat),
IL is the height of the root letter instead.

Each example is cut out of its page's gray darkness (3x3 median, staff and ledger lines erased
where white above and below, as Audiveris does before matching), aligned on the first example
(within 2 pixels) and averaged.  Writes into templates/<book>/:
    NAME.png        the template: average gray, ink dark, scaled to an interline of 20 pixels;
                    every pixel of the square is matched
    check_NAME.png  the examples as cut and aligned, then the template, enlarged: look at it
Audiveris reads NAME.png from the folder given as templateDir (templates/README.md).
"""
import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image

INTERLINE = 20  # template scale, in pixels


def darkness(path, il):
    """Gray darkness (0 white .. 1 black) of the page at INTERLINE, horizontal line pixels erased
    (made white) where white above and below; and the scale factor."""
    g = np.asarray(Image.open(path).convert('L'))
    s = INTERLINE / il
    g = cv2.medianBlur(cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC), 3)
    ink = g < 160
    line = cv2.morphologyEx((g < 200).astype(np.uint8), cv2.MORPH_OPEN,  # pale lines too
                            np.ones((1, int(1.2 * INTERLINE)), np.uint8)) > 0
    d = INTERLINE // 5
    above = np.zeros_like(ink)
    above[d:] = ink[:-d]
    below = np.zeros_like(ink)
    below[:-d] = ink[d:]
    a = 1 - g.astype(np.float32) / 255
    erase = (line & ~above & ~below).astype(np.uint8)
    a[cv2.dilate(erase, np.ones((3, 1), np.uint8)) > 0] = 0  # anti-aliased edges too
    return a, s


def cut(a, x, y, h, w=None):
    w = h if w is None else w
    return a[y - h:y + h + 1, x - w:x + w + 1]


def ncc(p, q):
    p = p - p.mean()
    q = q - q.mean()
    return float((p * q).sum() / (np.sqrt((p * p).sum() * (q * q).sum()) + 1e-9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('book')
    ap.add_argument('--name', required=True, help='template name: cross, cross_line, slash ...')
    ap.add_argument('--box', type=float, required=True, help='side of the square, in interlines')
    ap.add_argument('--height', type=float, help='height of the box (then --box is its width)')
    ap.add_argument('--from', dest='pages', nargs='+', action='append', required=True,
                    metavar='PAGE IL X,Y', help='a page, its staff interline, example centers')
    args = ap.parse_args()

    w = int(round(args.box * INTERLINE / 2))
    h = w if args.height is None else int(round(args.height * INTERLINE / 2))
    cells = []
    for page, il, *xys in args.pages:
        a, s = darkness(page, float(il))
        for xy in xys:
            x, y = (int(round(float(v) * s)) for v in xy.split(','))
            if not cells:
                cells.append(cut(a, x, y, h, w))
                continue
            best = max(((ncc(cells[0], cut(a, x + dx, y + dy, h, w)), dx, dy)
                        for dy in range(-2, 3) for dx in range(-2, 3)))
            cells.append(cut(a, x + best[1], y + best[2], h, w))
            print(f'{os.path.basename(page)} {xy}: shifted {best[1]:+d},{best[2]:+d}, '
                  f'match with the first {best[0]:.2f}')
    if len(cells) < 3:
        sys.exit('3 examples or more are needed')
    t = np.mean(cells, axis=0)

    os.makedirs(args.book, exist_ok=True)
    img = lambda d: Image.fromarray(np.uint8(np.round(255 * (1 - np.clip(d, 0, 1)))))
    img(t).save(os.path.join(args.book, args.name + '.png'))
    z = 12
    n, m = 2 * h + 1, 2 * w + 1
    out = Image.new('L', ((len(cells) + 1) * (z * m + z), z * n), 255)
    for i, c in enumerate(cells + [t]):
        out.paste(img(c).resize((z * m, z * n), Image.NEAREST), (i * (z * m + z), 0))
    out.save(os.path.join(args.book, f'check_{args.name}.png'), optimize=True)
    print(f'{args.book}/{args.name}.png: {m}x{n} from {len(cells)} examples')


if __name__ == '__main__':
    main()
