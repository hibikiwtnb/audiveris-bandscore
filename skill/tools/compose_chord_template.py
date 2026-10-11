#!/usr/bin/env python3
"""Compose a chord template (root letter + flat) for a root the book never prints with a flat.

    compose_chord_template.py templates/<book> --root G
        --letter PAGE RX,RY,RW,RH [RX,RY,RW,RH ...] [--letter ...]
        --flat PAGE RX,RY,RW,RH,FX,FW [...] [--flat ...]

--letter: examples of the plain root letter (e.g. the G of Gm, GM7): the letter box on the page
(RX,RY top left, RW,RH width and height of the letter ink).
--flat: examples of other roots with their flat (e.g. D♭, E♭): the letter box, then the left
abscissa FX and width FW of the flat bowl (its darker part).
PAGE is a page as Audiveris reads it (input/omr_in/*.png).

Each example is cut at a letter height of 20 pixels (the darkness of learn_template.py), aligned
on the right edge and top of its letter; the letters are averaged, the flats (right of their
letter) are averaged, the flat is put right of the letter as far as in the examples, and the
square is centered on letter + flat, as learn_template.py --box 1.4 does on real examples.
Writes chord_<ROOT>b.png and check_chord_<ROOT>b.png into templates/<book>/.
"""
import argparse
import os

import numpy as np
from PIL import Image

from learn_template import darkness

X0, X1, Y0, Y1 = -20, 15, -8, 24  # patch, scaled pixels around (letter right edge, cap top)
HALF = 14                          # square of 29 pixels: --box 1.4 at 20 pixels


def patch(page, rx, ry, rw, rh):
    a, s = darkness(page, float(rh))  # letter height -> 20 pixels
    ox, oy = int(round((rx + rw) * s)), int(round(ry * s))
    return a[oy + Y0:oy + Y1, ox + X0:ox + X1], s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('book')
    ap.add_argument('--root', required=True)
    ap.add_argument('--letter', nargs='+', action='append', required=True)
    ap.add_argument('--flat', nargs='+', action='append', required=True)
    args = ap.parse_args()

    letters, lefts = [], []
    for page, *boxes in args.letter:
        for box in boxes:
            rx, ry, rw, rh = map(int, box.split(','))
            p, s = patch(page, rx, ry, rw, rh)
            q = p.copy()
            q[:, -X0 + 1:] = 0  # the letter only
            letters.append(q)
            lefts.append(-rw * s)
    flats, rights = [], []
    for page, *boxes in args.flat:
        for box in boxes:
            rx, ry, rw, rh, fx, fw = map(int, box.split(','))
            p, s = patch(page, rx, ry, rw, rh)
            q = p.copy()
            q[:, :-X0 + 1] = 0  # right of the letter only
            flats.append(q)
            rights.append((fx + fw - rx - rw) * s)

    comp = np.mean(letters, axis=0) + np.mean(flats, axis=0)
    cx = int(round((np.mean(lefts) + np.mean(rights)) / 2 - X0))
    cy = int(round((-4 + 20) / 2 - Y0))  # flat top above the cap top .. letter bottom
    t = comp[cy - HALF:cy + HALF + 1, cx - HALF:cx + HALF + 1]

    img = lambda d: Image.fromarray(np.uint8(np.round(255 * (1 - np.clip(d, 0, 1)))))
    name = f'chord_{args.root}b'
    img(t).save(os.path.join(args.book, name + '.png'))
    z, n = 12, t.shape[0]
    img(t).resize((z * n, z * n), Image.NEAREST).save(
        os.path.join(args.book, f'check_{name}.png'), optimize=True)
    print(f'{args.book}/{name}.png: {n}x{n} from {len(letters)} letters and {len(flats)} flats')


if __name__ == '__main__':
    main()
