#!/usr/bin/env python3
"""Local PP-OCRv5 server for Audiveris (engine selected by OcrUtil.ocrEngine=paddle).

    python paddle_ocr_server.py [--port 8868] [--rec en_PP-OCRv5_mobile_rec]
                                [--lyrics-rec PP-OCRv5_server_rec] [--device gpu:0]

GET  /health  -> "ok <det> <rec> lyrics=<lyrics-rec>"
POST /ocr     body = PNG/TIFF image bytes
              read with <det> and <rec>
POST /ocr?model=lyrics&scripts=hiragana,katakana,punct
              body = image of the lyrics below a staff, read by LyricsReader with <lyrics-rec>,
              keeping only the chars of the given scripts (SCRIPTS); one line per text line,
              one word per syllable, each word with its own score (W ... text score)
              -> text/tab-separated-values, one record per line, top-left pixel coordinates:
                 L  score  x  y  w  h  text      (a text line)
                 W  x  y  w  h  text             (a word of the preceding line)
                 C  x  y  w  h  char             (a char of the preceding word)
"""
import argparse
import io
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
# On GPU (--device gpu:N), full fp32: with TF32 (Ampere default) and free cuDNN algorithms the
# texts differ from the CPU (e.g. chord Eb read E\); without, the same texts, boxes and scores
os.environ.setdefault('NVIDIA_TF32_OVERRIDE', '0')
os.environ.setdefault('FLAGS_cudnn_deterministic', '1')

import cv2
import numpy as np
from PIL import Image
import paddle.inference

# Workaround: PaddlePaddle 3.x CPU fails in oneDNN instruction when handling
# pir::ArrayAttribute<pir::DoubleAttribute>, an op of the text detection model (seen on Windows
# and Linux with paddlepaddle 3.3.1): mkldnn is disabled for the detection model only, on Windows
# for all models. The recognition models keep it, reading twice as fast with the same texts.
_orig_create_predictor = paddle.inference.create_predictor
def _safe_create_predictor(config):
    if hasattr(config, 'disable_mkldnn') and (os.name == 'nt' or '_det' in config.prog_file()):
        config.disable_mkldnn()
    return _orig_create_predictor(config)
paddle.inference.create_predictor = _safe_create_predictor

from paddleocr import PaddleOCR
from paddlex import create_model
from paddlex.inference.models.text_recognition.processors import CTCLabelDecode
from urllib.parse import parse_qs, urlparse


def _chars(*ranges):
    return {chr(c) for a, b in ranges for c in range(a, b + 1)}


# Chars of each script a lyrics request may allow (ー is the long vowel mark of both kana)
SCRIPTS = {
    'hiragana': _chars((0x3041, 0x3096), (0x309D, 0x309F)) | {'ー'},
    'katakana': _chars((0x30A1, 0x30FA), (0x30FC, 0x30FF), (0x31F0, 0x31FF)),
    'kanji': _chars((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF)) | set('々〆〇'),
    'latin': _chars((0x41, 0x5A), (0x61, 0x7A)) | {"'"},
    'digits': _chars((0x30, 0x39)),
    'punct': set('!?,.()~"' + '！？、。（）「」『』～・…‥'),
    'hyphen': {'-'},
}

# Kana that have a small form, told apart by size (LyricsReader.SMALL_SIZE)
SMALL = dict(zip('つやゆよあいうえおわツヤユヨアイウエオワ', 'っゃゅょぁぃぅぇぉゎッャュョァィゥェォヮ'))
LARGE = {small: large for large, small in SMALL.items()}


def allowed_chars(names):
    allowed = set()
    for name in names:
        if name not in SCRIPTS:
            raise ValueError(f'unknown script "{name}", known: {", ".join(SCRIPTS)}')
        allowed |= SCRIPTS[name]
    return allowed


_ctc_call = CTCLabelDecode.__call__


def _ctc_call_masked(self, pred, *args, **kwargs):
    """CTC decoding restricted to self.allowed (a mask over the chars, or None for all chars).

    Where the best char of a time step is not allowed, the best allowed char is taken instead,
    so a char seen by the model is replaced, not dropped: blank decisions stay as they are.
    """
    allowed = getattr(self, 'allowed', None)
    if allowed is not None:
        p = np.array(pred[0])
        swap = ~allowed[p.argmax(axis=-1)]
        q = p[swap]
        q[:, ~allowed] = 0
        q[:, 0] = 0
        p[swap] = q
        pred = [p]
        self.last_pred = p
    return _ctc_call(self, pred, *args, **kwargs)


CTCLabelDecode.__call__ = _ctc_call_masked


def runs(flags, max_gap):
    """[start, stop) of the runs of True, runs closer than max_gap merged."""
    out = []
    for i in np.flatnonzero(flags):
        if out and i - out[-1][1] <= max_gap:
            out[-1][1] = i + 1
        else:
            out.append([int(i), int(i) + 1])
    return out


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
    def __init__(self, det, rec, device):
        self.name = f'{det} {rec}'
        self.lock = threading.Lock()
        self.ocr = PaddleOCR(text_detection_model_name=det, text_recognition_model_name=rec, device=device,
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


class LyricsReader:
    """Read the lyrics below a staff: lines of syllables set apart by blank columns.

    No text detection, it misses lone short syllables and dashes:
    - ties and slurs left in the image are erased: pieces of ink at least 2.5 times as wide as
      high and less than half filled (a dash is filled);
    - a text line is a band of inked rows (bands lower than half the highest one are dropped);
    - a syllable is a group of inked columns, groups closer than GAP line heights merged;
    - the syllables are recognized side by side, half a line height apart, as one line (in
      chunks up to MAX_RATIO line heights wide), keeping only the chars of the scripts; each
      char goes to the syllable under its decoded position, a char decoded in the blank between
      syllables is dropped;
    - a syllable as flat as a dash is a dash: "-" after a latin syllable, "ー" otherwise (as
      far as the scripts allow); a line of dashes only is no lyrics;
    - a kana with a small form is small when its ink is less high than SMALL_SIZE of the median
      char (non ASCII) of the line, large when higher than LARGE_SIZE, as read in between; its
      score is the sum for both forms.
    """
    GAP = 0.6
    MAX_RATIO = 40
    SMALL_SIZE = 0.76
    LARGE_SIZE = 0.9

    def __init__(self, rec, device):
        self.lock = threading.Lock()
        self.model = create_model(model_name=rec, device=device)
        self.decoder = self.model._predictor.post_op
        index = {ch: i for i, ch in enumerate(self.decoder.character)}
        self.other_form = {index[a]: index[b] for a, b in list(SMALL.items()) + list(LARGE.items())
                           if a in index and b in index}
        resize = self.model._predictor.pre_tfs['ReisizeNorm']
        _, self.rec_h, self.rec_w = resize.rec_image_shape
        self.rec_max_w = resize.max_imgW

    def run(self, data, scripts):
        allowed = allowed_chars(scripts)
        mask = np.array([i == 0 or ch in allowed for i, ch in enumerate(self.decoder.character)])
        gray = np.array(Image.open(io.BytesIO(data)).convert('L'))
        ink = gray < 128
        n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
        for i in range(1, n):
            _, _, w, h, area = stats[i]
            if w >= 2.5 * h and area < 0.5 * w * h:
                ink[labels == i] = False
                gray[labels == i] = 255
        bands = runs(ink.any(axis=1), 2)
        if not bands:
            return ''
        top = max(b - a for a, b in bands)
        out = []
        for y0, y1 in bands:
            if (y1 - y0) * 2 >= top:
                out += self.read_line(gray, ink[y0:y1], y0, allowed, mask)
        return '\n'.join(out) + '\n'

    def read_line(self, gray, ink, y0, allowed, mask):
        h = ink.shape[0]
        # an extender line (flat, on the baseline, often broken in pieces) would widen the
        # syllable before it; a hyphen or a long vowel mark is flat too, but at mid height
        ink = ink.copy()
        n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
        for i in range(1, n):
            _, cy, w, ch, _ = stats[i]
            if ch * 4 <= h and w >= 3 * ch and (cy + ch / 2) * 4 >= 3 * h:
                ink[labels == i] = False
        syllables = []
        for x0, x1 in runs(ink.any(axis=0), int(self.GAP * h)):
            rows = np.flatnonzero(ink[:, x0:x1].any(axis=1))
            sy0, sy1 = y0 + int(rows[0]), y0 + int(rows[-1]) + 1
            dash = (sy1 - sy0) * 4 <= h and (x1 - x0) >= 2 * (sy1 - sy0)
            syllables.append({'x0': x0, 'x1': x1, 'y0': sy0, 'y1': sy1, 'dash': dash,
                              'text': '', 'probs': []})
        chunk, width = [], 0
        for syl in syllables:
            w = syl["x1"] - syl["x0"] + h
            if chunk and width + w > self.MAX_RATIO * h:
                self.recognize(gray[y0:y0 + h], chunk, mask)
                chunk, width = [], 0
            chunk.append(syl)
            width += w
        if chunk:
            self.recognize(gray[y0:y0 + h], chunk, mask)
        if not any(s['text'] for s in syllables if not s['dash']):
            return []
        self.set_dashes(syllables, allowed)
        syllables = [s for s in syllables if s['text']]
        chars = [self.chars_of(gray, s) for s in syllables]
        sizes = [c[4] for cs in chars for c in cs if not c[0].isascii()]
        size = float(np.median(sizes)) if sizes else 0
        chars = [[self.sized(c, size) for c in cs] for cs in chars]
        scores = [float(np.mean(s['probs'])) if s['probs'] else 1.0 for s in syllables]
        lx0, lx1 = syllables[0]['x0'], syllables[-1]['x1']
        ly0, ly1 = min(s['y0'] for s in syllables), max(s['y1'] for s in syllables)
        text = ' '.join(''.join(c[0] for c in cs) for cs in chars)
        out = [f'L\t{np.mean(scores):.4f}\t{lx0}\t{ly0}\t{lx1 - lx0}\t{ly1 - ly0}\t{clean(text)}']
        for syl, cs, score in zip(syllables, chars, scores):
            x0, x1, sy0, sy1 = syl['x0'], syl['x1'], syl['y0'], syl['y1']
            word = ''.join(c[0] for c in cs)
            out.append(f'W\t{x0}\t{sy0}\t{x1 - x0}\t{sy1 - sy0}\t{clean(word)}\t{score:.4f}')
            out += [f'C\t{cx}\t{cy}\t{cw}\t{ch}\t{clean(c)}' for c, cx, cy, cw, ch in cs]
        return out

    def recognize(self, band, chunk, mask):
        """Recognize the syllables of a chunk side by side, a line height apart, and give each
        decoded char to the syllable under its position (a quarter line height around it)."""
        h = band.shape[0]
        gap = np.full((h, h), 255, np.uint8)
        parts, spans, x = [gap], [], gap.shape[1]
        for syl in chunk:
            img = band[:, syl['x0']:syl['x1']]
            spans.append((x, x + img.shape[1]))
            parts += [img, gap]
            x += img.shape[1] + gap.shape[1]
        line = np.pad(np.hstack(parts), ((h // 4, h // 4), (0, 0)), constant_values=255)
        with self.lock:
            self.decoder.allowed = mask
            try:
                list(self.model.predict([np.stack([line] * 3, -1)]))
                pred = self.decoder.last_pred[0]
            finally:
                self.decoder.allowed = None
        # Same resizing as the model input: rec_h high, padded to rec_w at least
        lh, lw = line.shape
        full = min(max(self.rec_w, int(self.rec_h * lw / lh)), self.rec_max_w)
        resized = min(full, math.ceil(self.rec_h * lw / lh))
        prev = 0
        for t, idx in enumerate(pred.argmax(axis=-1)):
            if idx != 0 and idx != prev:
                ch = self.decoder.character[idx]
                if not ch.isspace():
                    x = (t + 0.5) * full / len(pred) * lw / resized
                    for syl, (a, b) in zip(chunk, spans):
                        if a - h / 4 <= x <= b + h / 4:
                            syl['text'] += ch
                            other = self.other_form.get(idx)
                            prob = pred[t, idx] + (pred[t, other] if other is not None else 0)
                            syl['probs'].append(float(prob))
                            break
            prev = idx

    @staticmethod
    def set_dashes(syllables, allowed):
        """Text of the dash syllables: "-" after latin, "ー" otherwise."""
        kana = 'ー' in allowed
        hyphen = '-' in allowed
        prev = ''
        for syl in syllables:
            if syl['dash']:
                latin = prev[-1:].isascii() and prev[-1:].isalpha()
                syl['text'] = '-' if hyphen and (latin or not kana) else ('ー' if kana else '')
                syl['probs'] = []
            elif syl['text']:
                prev = syl['text']

    @staticmethod
    def chars_of(gray, syl):
        """Char boxes: the syllable split evenly in columns, each part snapped to its ink."""
        x0, x1, y0, y1, word = syl['x0'], syl['x1'], syl['y0'], syl['y1'], syl['text']
        n = len(word)
        out = []
        for i, ch in enumerate(word):
            a = x0 + (x1 - x0) * i // n
            b = x0 + (x1 - x0) * (i + 1) // n
            part = gray[y0:y1, a:b] < 128
            cy0, cy1 = y0, y1
            if part.any():
                cols = np.flatnonzero(part.any(axis=0))
                rows = np.flatnonzero(part.any(axis=1))
                a, b = a + int(cols[0]), a + int(cols[-1]) + 1
                cy0, cy1 = y0 + int(rows[0]), y0 + int(rows[-1]) + 1
            out.append((ch, a, cy0, max(1, b - a), max(1, cy1 - cy0)))
        return out

    def sized(self, char, size):
        """The small or large form of a kana, by its height against the median char height."""
        ch, x, y, w, h = char
        if h < self.SMALL_SIZE * size and ch in SMALL:
            ch = SMALL[ch]
        elif h > self.LARGE_SIZE * size and ch in LARGE:
            ch = LARGE[ch]
        return ch, x, y, w, h


def clean(text):
    return text.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8868)
    ap.add_argument('--det', default='PP-OCRv5_mobile_det')
    ap.add_argument('--rec', default='en_PP-OCRv5_mobile_rec')
    ap.add_argument('--lyrics-rec', default='PP-OCRv5_server_rec')
    ap.add_argument('--device', default='cpu', help='cpu, or gpu:N with paddlepaddle-gpu')
    args = ap.parse_args()
    engine = Engine(args.det, args.rec, args.device)
    lyrics = LyricsReader(args.lyrics_rec, args.device)

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
                self._send(200, f'ok {engine.name} lyrics={args.lyrics_rec}\n')
            else:
                self._send(404, 'not found\n')

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != '/ocr':
                return self._send(404, 'not found\n')
            query = parse_qs(url.query)
            try:
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if query.get('model') == ['lyrics']:
                    scripts = [n for v in query.get('scripts', []) for n in v.split(',') if n]
                    if not scripts:
                        return self._send(400, 'error model=lyrics needs scripts=...\n')
                    self._send(200, lyrics.run(data, scripts))
                elif query:
                    self._send(400, f'error unknown query {url.query}\n')
                else:
                    self._send(200, engine.run(data))
            except ValueError as ex:
                self._send(400, f'error {ex}\n')
            except Exception as ex:  # report to client, keep serving
                self._send(500, f'error {ex}\n')

        def log_message(self, fmt, *args):
            pass

    print(f'PaddleOCR server ({engine.name}, lyrics {args.lyrics_rec}) on http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
