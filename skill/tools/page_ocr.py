#!/usr/bin/env python3
"""Full-page PaddleOCR of the OMR input images, in OMR pixel coordinates.

    <OCR_PYTHON> tools/page_ocr.py "<song dir>" [page ...]

Reads the pages exactly as given to Audiveris (<song dir>/input/omr_in/*.png, made by
tools/prepare_pages.py), runs PP-OCRv5 (mobile det + English rec) on the whole page and writes
<song dir>/page_ocr/pNN.json: [{text, score, x, y, w, h}, ...] (pNNa.json / pNNb.json for
half pages, split_pages=true).  A page argument (2 or 02) takes both halves; 02a takes one.

Why: Audiveris only OCRs what it classified as text, and misses most small italic staff labels
(297: Pluck, Harp, Glocken, Pad, most 8va). The whole page reads almost all of them; their
positions can then be mapped onto parts and measures with tools/locate_labels.py.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

import numpy as np
from PIL import Image
from paddleocr import PaddleOCR


def main(song_dir, pages):
    imgs = sorted(glob.glob(os.path.join(song_dir, 'input', 'omr_in', '*_p??.png'))
                  + glob.glob(os.path.join(song_dir, 'input', 'omr_in', '*_p??[ab].png')))
    out_dir = os.path.join(song_dir, 'page_ocr')
    os.makedirs(out_dir, exist_ok=True)
    ocr = PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',
                    text_recognition_model_name='en_PP-OCRv5_mobile_rec',
                    use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False)
    for img_path in imgs:
        unit = os.path.basename(img_path)[:-4].rsplit('_p', 1)[1]      # 02 / 02a
        if pages and not any(p == unit or (p.isdigit() and int(p) == int(unit[:2])) for p in pages):
            continue
        im = Image.open(img_path).convert('RGB')
        res = ocr.predict(np.array(im))[0]
        words = []
        for text, score, poly in zip(res['rec_texts'], res['rec_scores'], res['rec_polys']):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            words.append(dict(text=text, score=round(float(score), 3), x=int(min(xs)),
                              y=int(min(ys)), w=int(max(xs) - min(xs)),
                              h=int(max(ys) - min(ys))))
        with open(os.path.join(out_dir, f'p{unit}.json'), 'w') as f:
            json.dump(words, f, ensure_ascii=False, indent=0)
        print(f'p{unit}: {len(words)} lines')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
