#!/usr/bin/env python3
"""Pick the PaddleOCR server of the next Audiveris batch and write it to PADDLE_OCR_URL.

Usage (before a batch, any machine):
    python3 tools/ocr_pick.py && python3 tools/batch_rerun.py <song>

Candidates, in order of preference: PADDLE_OCR_CANDIDATES in environment.txt (comma separated),
by default only this machine (127.0.0.1:8868).  The first one whose /health answers is
written as PADDLE_OCR_URL in environment.txt (a busy or far server answers slowly: 5s for each
candidate but the last, which gets 30s).  Exit 1 when none answers.

Picked once per batch: if the server drops mid-batch, run_audiveris.py fails the pages on the OCR
errors in the log; run this again and rerun the batch, the done pages are skipped.
"""
import os
import re
import sys
import urllib.request

import env

DEFAULT = 'http://127.0.0.1:8868'  # this machine


def answers(url, timeout):
    try:
        with urllib.request.urlopen(url + '/health', timeout=timeout) as resp:
            return resp.status == 200 and resp.read().startswith(b'ok')
    except Exception:
        return False


def main():
    cfg = env.load()
    urls = [u.strip().rstrip('/') for u in cfg.get('PADDLE_OCR_CANDIDATES', DEFAULT).split(',') if u.strip()]
    for i, url in enumerate(urls):
        if answers(url, 5 if i < len(urls) - 1 else 30):
            break
        print(f'{url} not answering', flush=True)
    else:
        sys.exit('no PaddleOCR server answering: start one, <OCR_PYTHON> <PADDLE_OCR_SERVER> '
                 '(--device gpu:0 with paddlepaddle-gpu)')

    path = os.path.join(env.ROOT, 'environment.txt')
    text = open(path, encoding='utf-8').read()
    line = f'PADDLE_OCR_URL={url}'
    if re.search(r'^PADDLE_OCR_URL=.*$', text, re.M):
        text = re.sub(r'^PADDLE_OCR_URL=.*$', line, text, count=1, flags=re.M)
    else:
        text = text.rstrip('\n') + '\n' + line + '\n'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print(line)


if __name__ == '__main__':
    main()
