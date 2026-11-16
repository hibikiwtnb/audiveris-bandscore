#!/usr/bin/env python3
"""Conservative contextual correction of OCR-corrupted rehearsal marks.

Idempotent, in-place on MusicXML.

Only rewrites a <rehearsal> element when the surrounding uppercase letter
sequence uniquely determines the intended letter:
  - "0" -> "O" when adjacent to N/P or spanning O in an increasing letter sequence
  - "1" -> "I" when adjacent to H/J or spanning I in an increasing letter sequence
  - duplicate single letter (e.g. I I K) or obvious garbled text sandwiched
    between single uppercase letters `prev` and `next` with
    `ord(next) - ord(prev) == 2` -> `chr(ord(prev) + 1)`.

Ambiguous cases (e.g. a multi-letter gap such as H, "poond", K) are left
unchanged so score_quality.py can surface them for manual review.

Usage:
    fix_rehearsal_marks.py FILE [FILE ...]
"""
import re
import sys
import xml.etree.ElementTree as ET

VALID_REHEARSAL_RE = re.compile(
    r"^(?:[A-Z][0-9]*['\"]*|[0-9]+[A-Z]['\"]*"
    r"|(?i:Intro|Inter|Ending|Outro|Solo|Bridge|Verse|Chorus|Coda)"
    r"(?:[.\s]*(?:[0-9]+|[IVX]+))?)$"
)


def is_single_upper(text):
    return text is not None and len(text) == 1 and "A" <= text <= "Z"


def is_valid_rehearsal(text):
    return bool(text and VALID_REHEARSAL_RE.match(text))


def _infer_digit_letter(text, prev_t, next_t, target, lo_neighbor, hi_neighbor):
    if prev_t == lo_neighbor or next_t == hi_neighbor:
        return target
    if is_single_upper(prev_t) and ord(prev_t) < ord(target):
        if next_t is None or (is_single_upper(next_t) and ord(next_t) > ord(target)):
            return target
    if prev_t is None and is_single_upper(next_t) and ord(next_t) > ord(target):
        return target
    return None


def fix_part_rehearsals(part):
    """Fix contextually certain OCR rehearsal-mark errors in one <part>."""
    items = [
        (m.get("number") or "?", r, (r.text or "").strip())
        for m in part.findall("measure")
        for r in m.iter("rehearsal")
    ]
    changes = []
    for i, (mnum, elem, t) in enumerate(items):
        prev_t = items[i - 1][2] if i > 0 else None
        next_t = items[i + 1][2] if i + 1 < len(items) else None
        new_t = None

        if (
            is_single_upper(prev_t)
            and is_single_upper(next_t)
            and ord(next_t) - ord(prev_t) == 2
        ):
            expected = chr(ord(prev_t) + 1)
            if (
                (t == "0" and expected == "O")
                or (t == "1" and expected == "I")
                or t in (prev_t, next_t)
                or (
                    t not in ("0", "1")
                    and not is_single_upper(t)
                    and not is_valid_rehearsal(t)
                )
            ):
                if t != expected:
                    new_t = expected

        if new_t is None and t == "0":
            new_t = _infer_digit_letter(t, prev_t, next_t, "O", "N", "P")
        elif new_t is None and t == "1":
            new_t = _infer_digit_letter(t, prev_t, next_t, "I", "H", "J")

        if new_t is not None and new_t != t:
            elem.text = new_t
            items[i] = (mnum, elem, new_t)
            changes.append((mnum, t, new_t))
    return changes


def fix_rehearsal_marks(root):
    """Apply conservative rehearsal-mark fixes across all parts of a MusicXML root."""
    changes = []
    for part in root.findall("part"):
        changes.extend(fix_part_rehearsals(part))
    return changes


def rehearsal_suspects(part):
    """Return [(measure_num, text, reason), ...] for remaining suspect rehearsal marks."""
    items = [
        (m.get("number") or "?", (r.text or "").strip())
        for m in part.findall("measure")
        for r in m.iter("rehearsal")
    ]
    suspects = []
    for i, (mnum, t) in enumerate(items):
        prev_t = items[i - 1][1] if i > 0 else None
        if t in ("0", "1"):
            suspects.append((mnum, t, "digit"))
        elif not is_valid_rehearsal(t):
            suspects.append((mnum, t, "garbled"))
        elif is_single_upper(t) and t == prev_t:
            suspects.append((mnum, t, "duplicate"))
    return suspects


def main(argv):
    for path in argv[1:]:
        tree = ET.parse(path)
        root = tree.getroot()
        changes = fix_rehearsal_marks(root)
        if changes:
            tree.write(path, encoding="utf-8", xml_declaration=True)
            summary = ", ".join(f"m{m}:{old}->{new}" for m, old, new in changes)
            print(f"fix_rehearsal_marks: {len(changes)} fixed ({summary})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv)
