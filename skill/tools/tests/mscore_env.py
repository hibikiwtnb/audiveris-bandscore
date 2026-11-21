"""Locate MuseScore for tests that need a real conversion (None when unavailable)."""
import os

import env


def musescore_bin():
    value = os.environ.get('MUSESCORE_BIN')
    if not value:
        path = os.path.join(env.ROOT, 'environment.txt')
        if os.path.exists(path):
            for line in open(path, encoding='utf-8'):
                line = line.strip()
                if line.startswith('MUSESCORE_BIN='):
                    value = line.split('=', 1)[1].strip()
                    break
    value = value or '/usr/local/bin/mscore'
    return value if os.path.exists(value) else None
