"""Fonts for the image labels: a Chinese-capable font for the Chinese words, a plain sans for
the Latin and figures next to them.

One candidate list per platform (macOS, Linux, Windows), then fontconfig on Linux, then the
usual system font folders.  A Chinese font that cannot draw a Chinese character is skipped:
fontconfig's "sans-serif:lang=zh" may name a Latin-only fallback, and drawing with it gives
empty boxes instead of the label.  The common Linux CJK fallback (Droid Sans Fallback) has no
Latin or digits at all, so a label is drawn run by run, each run in a font that can draw it.
When no Chinese font is found a warning goes to stderr, so a Chinese label never silently
becomes a row of boxes again.
"""
import glob
import itertools
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

CJK_FILES = (
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
    '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/truetype/arphic/uming.ttc',
    '/usr/local/share/fonts/NotoSansCJK-Regular.ttc',
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/simsun.ttc',
)

CJK_PATTERNS = (':lang=zh', 'sans-serif:lang=zh', 'serif:lang=zh')

SANS_FILES = (
    ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
     '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
)

SAMPLE = '\u4e2d'        # 中
UNASSIGNED = '\u0378'    # no font has a glyph here; the mask is the .notdef shape
_warned = set()


def _load(path, size):
    if not path or not os.path.exists(path):
        return None
    try:
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def _fc_match(pattern):
    exe = shutil.which('fc-match')
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '-f', '%{file}', pattern],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip()
    return path if out.returncode == 0 and path and os.path.exists(path) else None


def _draws(font, text):
    """False when text comes out as the same blank or .notdef shape as an unassigned codepoint."""
    size = getattr(font, 'size', 20) or 20

    def ink(t):
        img = Image.new('L', (size * 2, size * 2), 0)
        ImageDraw.Draw(img).text((2, 2), t, fill=255, font=font)
        return img.tobytes()
    try:
        return ink(text) != ink(UNASSIGNED)
    except Exception:
        return True   # cannot judge: trust the chosen file instead of warning wrongly


def _draws_chinese(font):
    return _draws(font, SAMPLE)


def _warn(kind, why):
    if kind in _warned:
        return
    _warned.add(kind)
    sys.stderr.write('warning: no %s font found (%s); install one, e.g. a Noto CJK font, '
                     'or the labels will be unreadable\n' % (kind, why))


def cjk(size):
    """A font that can draw Chinese at the given pixel size."""
    for path in CJK_FILES:
        font = _load(path, size)
        if font is not None and _draws_chinese(font):
            return font
    for pattern in CJK_PATTERNS:
        path = _fc_match(pattern)
        if path in CJK_FILES:
            continue
        font = _load(path, size)
        if font is not None and _draws_chinese(font):
            return font
    for pattern in ('*CJK*.tt[cf]', '*Droid*Fallback*.ttf', '*wqy*.tt[cf]', '*hei*.tt[cf]'):
        for path in sorted(glob.glob('/usr/share/fonts/**/' + pattern, recursive=True)):
            font = _load(path, size)
            if font is not None and _draws_chinese(font):
                return font
    _warn('Chinese-capable', 'the macOS/Linux/Windows font paths all failed, so did fontconfig '
          'and the usual font folders')
    return ImageFont.load_default()


def sans(size, bold=False):
    """A plain Latin/sans font at the given pixel size."""
    for regular, heavy in SANS_FILES:
        font = _load(heavy if bold else regular, size)
        if font is not None:
            return font
    for suffix in (':bold', '') if bold else ('',):
        font = _load(_fc_match('sans-serif' + suffix), size)
        if font is not None:
            return font
    _warn('sans', 'tried Arial, DejaVu Sans, Liberation Sans and fontconfig')
    return ImageFont.load_default()


def _east_asian(ch):
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F
            or 0xFF00 <= o <= 0xFFEF or 0x20000 <= o <= 0x2FA1F)


def draw_text(draw, xy, text, size, fill=0):
    """Draw at xy, taking the Chinese runs from the Chinese font and the rest from the sans font."""
    latin, chinese = sans(size), cjk(size)
    if getattr(latin, 'path', None) == getattr(chinese, 'path', None) or all(
            _draws(chinese, ch) for ch in 'A5p'):
        draw.text(xy, text, fill=fill, font=chinese)
        return
    x, y = xy
    for east, run in itertools.groupby(text, _east_asian):
        run = ''.join(run)
        font = chinese if east else latin
        draw.text((x, y), run, fill=fill, font=font)
        x += font.getlength(run)
