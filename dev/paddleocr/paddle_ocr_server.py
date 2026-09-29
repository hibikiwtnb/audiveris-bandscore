#!/usr/bin/env python3
"""Local PP-OCRv5 server for Audiveris (engine selected by OcrUtil.ocrEngine=paddle).

    python paddle_ocr_server.py [--port 8868] [--rec en_PP-OCRv5_mobile_rec]

GET  /health  -> "ok <det> <rec>"
POST /ocr     body = PNG/TIFF image bytes
              -> text/tab-separated-values, one record per line, top-left pixel coordinates:
                 L  score  x  y  w  h  text      (a text line)
                 W  x  y  w  h  text             (a word of the preceding line)
                 C  x  y  w  h  char             (a char of the preceding word)
"""
import argparse
import io
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

import numpy as np
from PIL import Image
import paddle.inference

# Workaround: PaddlePaddle 3.x on Windows CPU fails in oneDNN instruction when handling
# pir::ArrayAttribute<pir::DoubleAttribute>. Disabling mkldnn ensures stable native CPU inference.
_orig_create_predictor = paddle.inference.create_predictor
def _safe_create_predictor(config):
    if hasattr(config, 'disable_mkldnn'):
        config.disable_mkldnn()
    return _orig_create_predictor(config)
paddle.inference.create_predictor = _safe_create_predictor

from paddleocr import PaddleOCR


def rect(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x, y = int(min(xs)), int(min(ys))
    return x, y, max(1, int(max(xs)) - x), max(1, int(max(ys)) - y)


def words_of(segments, regions):
    """Split PaddleOCR word segments into words of chars, each char with its own box.

    A segment may hold several chars (and spaces): its box is split evenly among its chars.
    """
    words, current = [], []
    for seg, region in zip(segments, regions):
        x, y, w, h = rect(region)
        n = max(1, len(seg))
        for i, ch in enumerate(seg):
            if ch.isspace():
                if current:
                    words.append(current)
                    current = []
                continue
            cx = x + int(i * w / n)
            cw = max(1, int((i + 1) * w / n) - int(i * w / n))
            current.append((ch, cx, y, cw, h))
    if current:
        words.append(current)
    return words


def refine_chars(gray, word):
    """Snap the char boxes of a word to the actual ink, when column segmentation fits.

    The word box is split into runs of inked columns; if there are exactly as many runs as
    chars, each char gets the bounds of the ink in its run. Otherwise the word is left as is.
    """
    if len(word) < 2:
        return word  # e.g. a rehearsal letter within its frame: keep detected box
    x0 = min(c[1] for c in word)
    y0 = min(c[2] for c in word)
    x1 = max(c[1] + c[3] for c in word)
    y1 = max(c[2] + c[4] for c in word)
    h, w = gray.shape
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
    if x1 <= x0 or y1 <= y0:
        return word
    ink = gray[y0:y1, x0:x1] < 128
    cols = ink.any(axis=0)
    runs, start = [], None
    for i, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if len(runs) != len(word):
        return word
    out = []
    for (ch, *_), (a, b) in zip(word, runs):
        rows = ink[:, a:b].any(axis=1).nonzero()[0]
        out.append((ch, x0 + a, y0 + int(rows[0]), b - a, int(rows[-1]) - int(rows[0]) + 1))
    return out


class Engine:
    def __init__(self, det, rec):
        self.name = f'{det} {rec}'
        self.lock = threading.Lock()
        self.ocr = PaddleOCR(text_detection_model_name=det, text_recognition_model_name=rec,
                             use_doc_orientation_classify=False, use_doc_unwarping=False,
                             use_textline_orientation=False, return_word_box=True)

    def run(self, data):
        pil = Image.open(io.BytesIO(data))
        img = np.array(pil.convert('RGB'))
        gray = np.array(pil.convert('L'))
        with self.lock:
            res = self.ocr.predict(img)[0]
        out = []
        for i, text in enumerate(res['rec_texts']):
            if not text.strip():
                continue
            x1, y1, x2, y2 = (int(v) for v in res['rec_boxes'][i])
            out.append(f'L\t{float(res["rec_scores"][i]):.4f}\t{x1}\t{y1}\t{x2 - x1}\t{y2 - y1}\t{clean(text)}')
            for word in words_of(res['text_word'][i], res['text_word_region'][i]):
                word = refine_chars(gray, word)
                wx = min(c[1] for c in word)
                wy = min(c[2] for c in word)
                wr = max(c[1] + c[3] for c in word)
                wb = max(c[2] + c[4] for c in word)
                out.append(f'W\t{wx}\t{wy}\t{wr - wx}\t{wb - wy}\t{clean("".join(c[0] for c in word))}')
                for ch, cx, cy, cw, chh in word:
                    out.append(f'C\t{cx}\t{cy}\t{cw}\t{chh}\t{clean(ch)}')
        return '\n'.join(out) + '\n'


def clean(text):
    return text.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8868)
    ap.add_argument('--det', default='PP-OCRv5_mobile_det')
    ap.add_argument('--rec', default='en_PP-OCRv5_mobile_rec')
    args = ap.parse_args()
    engine = Engine(args.det, args.rec)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                self._send(200, f'ok {engine.name}\n')
            else:
                self._send(404, 'not found\n')

        def do_POST(self):
            if self.path != '/ocr':
                return self._send(404, 'not found\n')
            try:
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self._send(200, engine.run(data))
            except Exception as ex:  # report to client, keep serving
                self._send(500, f'error {ex}\n')

        def log_message(self, fmt, *args):
            pass

    print(f'PaddleOCR server ({engine.name}) on http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
