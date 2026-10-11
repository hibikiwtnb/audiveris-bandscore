#!/usr/bin/env python3
"""Merge per-page normalized MusicXML files into a single paginated score.

The merged score keeps the original pagination strictly:

  * merged pages 2..N start with `<print new-page="yes">` on their first
    measure (page 1 unchanged);
  * each source page's own `<page-layout>` is carried into the `<print>` of
    that page's first measure, so every page keeps its original paper size;
  * mid-page `<print new-system="yes">` markers stay glued to their measure;
  * measures are re-numbered globally 1..N; part ids / part-list are kept;
  * page credits are remapped to their merged page number.

Half pages (split_pages=true): --continues=3,5,... lists the input pages (1-based) that are
the lower half of the page before; such a page starts with `<print new-system="yes">` on the
same merged page, its height is added to that page's height and the upper half's credits
move up by it.  Without it every half got a page of its own, and MuseScore 3 (one page size
for the whole score) put a blank page after each half whose system nearly filled it.

Hardcoded for the current single song. To add another song, change BASE /
PAGES (or pass the song base name and page count as CLI arguments).
"""

import copy
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = "145_想いよひとつになれ_Keyboard"
PAGES = range(1, 12)

HERE = os.path.dirname(os.path.abspath(__file__))
SONG_DIR = os.path.normpath(os.path.join(HERE, "..", BASE))
OUT_PATH = os.path.join(SONG_DIR, "%s_merged.musicxml" % BASE)


def input_path(base, page):
    name = "%s_p%02d_normalized.musicxml" % (base, page)
    p0 = os.path.join(SONG_DIR, name)
    if os.path.exists(p0):
        return p0
    return os.path.join(SONG_DIR, "normalized", name)


def get_or_create_print(measure):
    pr = measure.find("print")
    if pr is None:
        pr = ET.Element("print")
        measure.insert(0, pr)
    return pr


def float_safe(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def merged_part_list(roots):
    """Part-list of page 1 with the score/midi instruments the later pages add.

    A part only declares the instruments it actually uses on a page (unpitched percussion
    declares one per drum sound).  Keeping page 1's part-list alone leaves later pages'
    notes referring to undeclared instrument ids (071: the drums' first page is all rests).
    """
    pl = copy.deepcopy(roots[0].find("part-list"))
    sp_by_id = {sp.get("id"): sp for sp in pl.findall("score-part")}
    seen_si = {si.get("id") for si in pl.iter("score-instrument")}
    seen_mi = {mi.get("id") for mi in pl.iter("midi-instrument")}
    new_si = {pid: [] for pid in sp_by_id}
    new_mi = {pid: [] for pid in sp_by_id}
    for r in roots[1:]:
        rpl = r.find("part-list")
        if rpl is None:
            continue
        for sp in rpl.findall("score-part"):
            pid = sp.get("id")
            if pid not in sp_by_id:
                continue
            for si in sp.findall("score-instrument"):
                if si.get("id") not in seen_si:
                    seen_si.add(si.get("id"))
                    new_si[pid].append(si)
            for mi in sp.findall("midi-instrument"):
                if mi.get("id") not in seen_mi:
                    seen_mi.add(mi.get("id"))
                    new_mi[pid].append(mi)
    for pid, sp in sp_by_id.items():
        kids = list(sp)
        idx = next((i for i, k in enumerate(kids)
                    if k.tag in ("midi-device", "midi-instrument")), len(kids))
        for j, si in enumerate(new_si[pid]):
            sp.insert(idx + j, copy.deepcopy(si))
        for mi in new_mi[pid]:
            sp.append(copy.deepcopy(mi))
    return pl


def expand_empty_measures(xml_text):
    """Render empty measures as explicit <measure ...></measure> pairs.

    ElementTree serializes child-less measures as self-closing
    (<measure ... />).  A self-closing empty measure makes plain-text / regex
    inspection attribute the NEXT measure's content (e.g. its <barline>) to it,
    which looks like a barline mismatch.  Expanding is semantically identical
    and keeps text-level review unambiguous.
    """
    return re.sub(r'<measure number="(\d+)"([^>]*?)\s*/>',
                  lambda m: '<measure number="%s"%s></measure>'
                  % (m.group(1), m.group(2)), xml_text)


def main():
    global SONG_DIR
    continues = set()
    for a in [a for a in sys.argv[1:] if a.startswith("--continues=")]:
        sys.argv.remove(a)
        continues = {int(x) - 1 for x in a.split("=", 1)[1].split(",") if x}
    base = sys.argv[1] if len(sys.argv) > 1 else BASE
    SONG_DIR = os.path.normpath(os.path.join(HERE, "..", base))
    prefix = sys.argv[3] if len(sys.argv) > 3 else base
    try:
        pages = range(1, int(sys.argv[2]) + 1) if len(sys.argv) > 2 else PAGES
    except ValueError:
        sys.exit("page count must be an integer")
    out = os.path.join(SONG_DIR, "%s_merged.musicxml" % base)

    roots = []
    for p in pages:
        ip = input_path(prefix, p)
        if not os.path.exists(ip):
            sys.exit("missing input: %s" % ip)
        roots.append(ET.parse(ip).getroot())

    # ---- consistency checks ------------------------------------------------ #
    part_ids = [pr.get("id") for pr in roots[0].findall("part")]
    for r in roots[1:]:
        ids = [pr.get("id") for pr in r.findall("part")]
        if ids != part_ids:
            sys.exit("part ids differ across pages: %s" % ids)

    counts = {pid: [] for pid in part_ids}
    for r in roots:
        for pr in r.findall("part"):
            counts[pr.get("id")].append(len(pr.findall("measure")))
    ref = counts[part_ids[0]]
    for pid, lst in counts.items():
        if lst != ref:
            sys.exit("per-page measure counts differ for part %s: %s"
                     % (pid, lst))

    # ---- merged pages: a lower half continues the page of its upper half -- #
    groups = []
    for pi in range(len(roots)):
        if pi in continues and groups:
            groups[-1].append(pi)
        else:
            groups.append([pi])
    page_of = {pi: gi for gi, g in enumerate(groups) for pi in g}
    heights = [float_safe(r.findtext("defaults/page-layout/page-height")) or 0
               for r in roots]
    lift = {pi: sum(heights[q] for q in g[g.index(pi) + 1:]) for g in groups for pi in g}

    # ---- defaults: from page 1, page-layout = union of all pages ---------- #
    defaults = copy.deepcopy(roots[0].find("defaults"))
    max_h = max_w = None
    page_layouts = {}
    for g in groups:
        pl = copy.deepcopy(roots[g[0]].find("defaults/page-layout"))
        h = sum(heights[pi] for pi in g)
        w = max(float_safe(roots[pi].findtext("defaults/page-layout/page-width")) or 0
                for pi in g)
        pl.find("page-height").text = str(int(h))
        pl.find("page-width").text = str(int(w))
        page_layouts[g[0]] = pl
        max_h = max((h, max_h or 0))
        max_w = max((w, max_w or 0))
    # MuseScore 3 lays every page out at this one size; a page shorter than portrait A4 can
    # leave no room for the second system of a merged half-page pair (054: 3185 x 2511 gave 14
    # blank pages, x 1.414 none)
    max_h = max(max_h, round(max_w * 1.414))
    dpl = defaults.find("page-layout")
    if dpl is not None:
        dpl.find("page-height").text = str(int(max_h))
        dpl.find("page-width").text = str(int(max_w))

    # ---- merge parts -------------------------------------------------------- #
    parts = []
    for pid in part_ids:
        new_part = ET.Element("part", {"id": pid})
        num = 0
        for pi, root in enumerate(roots):
            src_part = next(pr for pr in root.findall("part")
                            if pr.get("id") == pid)
            for mi, m in enumerate(src_part.findall("measure")):
                num += 1
                cp = copy.deepcopy(m)
                cp.set("number", str(num))
                if pi in continues and mi == 0 and pi != groups[page_of[pi]][0]:
                    pr = get_or_create_print(cp)
                    pr.attrib.pop("new-page", None)
                    pr.set("new-system", "yes")
                    sl = pr.find("system-layout")
                    tsd = sl.find("top-system-distance") if sl is not None else None
                    if tsd is not None:
                        sl.remove(tsd)
                elif pi > 0 and mi == 0:
                    pr = get_or_create_print(cp)
                    pr.set("new-page", "yes")
                    if pid == part_ids[0]:
                        pl = copy.deepcopy(page_layouts[pi])
                        pl.tag = "page-layout"
                        pr.insert(0, pl)
                new_part.append(cp)
        parts.append(new_part)

    # ---- credits remapped to merged page numbers ---------------------------- #
    credits = []
    for pi, root in enumerate(roots):
        for c in root.findall("credit"):
            cc = copy.deepcopy(c)
            cc.set("page", str(page_of[pi] + 1))
            if lift[pi]:
                for cw in cc.iter():
                    y = float_safe(cw.get("default-y"))
                    if y is not None:
                        cw.set("default-y", "%g" % (y + lift[pi]))
            credits.append(cc)

    # ---- assemble root ------------------------------------------------------ #
    src = roots[0]
    out_root = ET.Element("score-partwise", src.attrib)
    for tag in ("work", "movement-number", "movement-title", "identification"):
        el = src.find(tag)
        if el is not None:
            out_root.append(copy.deepcopy(el))
    out_root.append(defaults)
    for c in credits:
        out_root.append(c)
    out_root.append(merged_part_list(roots))
    for p in parts:
        out_root.append(p)

    # ---- serialize ---------------------------------------------------------- #
    with open(input_path(prefix, 1), "rb") as fh:
        mt = re.search(rb"<!DOCTYPE[^>]*>", fh.read())
    doctype = mt.group(0).decode("utf-8") if mt else None

    ET.indent(out_root, space="  ")
    body = expand_empty_measures(ET.tostring(out_root, encoding="unicode"))
    header = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if doctype:
        header += doctype + "\n"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(header + body + "\n")

    # ---- self-audit (pagination invariants) ---------------------------------- #
    audit(base, out, part_ids, [sum(ref[pi] for pi in g) for g in groups])


def audit(base, out, part_ids, per_page_counts):
    print("written: %s" % out)
    tree = ET.parse(out)
    root = tree.getroot()
    problems = []

    parts = {pr.get("id"): pr for pr in root.findall("part")}
    ref_part = parts[part_ids[0]]
    measures = ref_part.findall("measure")
    total = len(measures)
    print("merged measures: %d x %d parts" % (total, len(parts)))

    bounds = []
    off = 0
    for k, n in enumerate(per_page_counts, start=1):
        bounds.append((k, off + 1, off + n))
        off += n
    if off != total:
        problems.append("measure count %d != expected %d" % (total, off))

    by_number = {}
    for pr in parts.values():
        for m in pr.findall("measure"):
            by_number.setdefault(m.get("number"), []).append(pr.get("id"))

    for (page, start, end) in bounds:
        pr = None
        for m in measures:
            if int(m.get("number")) == start:
                pr = m
                break
        new_page = pr is not None and pr.find("print") is not None \
            and pr.find("print").get("new-page") == "yes"
        present_in = by_number.get(str(start), [])
        if page == 1:
            status = "first page (no break)"
            from_measures = pr.find("print") is None or \
                pr.find("print").get("new-page") is None
            if not from_measures:
                problems.append(
                    "page 1 start m%s must not carry new-page" % start)
        else:
            status = "new-page=%s" % (new_page,)
            if not new_page:
                problems.append("page %d start m%s is missing new-page"
                                % (page, start))
        if present_in != part_ids:
            problems.append("page %d start m%s not present in every part: %s"
                            % (page, start, present_in))

        # new-system markers must live inside their own page range
        markers = []
        for m in measures:
            n = int(m.get("number"))
            if start <= n <= end:
                pr = m.find("print")
                if pr is not None and pr.get("new-system") == "yes":
                    markers.append(n)
        print("page %2d  measures %s  %s  new-system@%s"
              % (page, "%4d-%4d" % (start, end), status.ljust(23), markers))

    # global check: every measure present in every part
    for m in ref_part.findall("measure"):
        if len(by_number.get(m.get("number"), [])) != len(part_ids):
            problems.append("measure %s missing in some part" % m.get("number"))

    if problems:
        print("AUDIT PROBLEMS:")
        for w in problems:
            print("  - %s" % w)
        sys.exit(1)
    print("audit ok: %d pages, page starts pinned, systems kept in page"
          % len(per_page_counts))


if __name__ == "__main__":
    main()