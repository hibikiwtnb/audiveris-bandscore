"""Read environment.txt (KEY=value lines, '#' comments) from the repo root.

environment.txt is machine-local and not in git.  If it is missing, stop and say how to make it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(required=()):
    path = os.path.join(ROOT, 'environment.txt')
    if not os.path.exists(path):
        sys.exit('environment.txt not found: copy the template at the end of requirements.txt '
                 'to environment.txt (repo root) and fill it in')
    env = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
    for k in required:
        if not env.get(k):
            sys.exit(f'environment.txt: {k} is empty')
    return env
