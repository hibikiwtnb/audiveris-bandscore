#!/usr/bin/env python3
"""Batch rerun Audiveris and postprocess on specified songs.

Usage:
    python tools/batch_rerun.py <song_dir_or_name> ...
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run_song(song, resume=False, extra_av_args=None):
    if extra_av_args is None:
        extra_av_args = []
    if not os.path.isabs(song):
        if os.path.isdir(os.path.join(ROOT, "songs", song)):
            song_dir = os.path.join(ROOT, "songs", song)
        elif os.path.isdir(os.path.join(ROOT, song)):
            song_dir = os.path.join(ROOT, song)
        else:
            song_dir = os.path.abspath(song)
    else:
        song_dir = song

    if not os.path.isdir(song_dir):
        sys.exit(f"Error: song directory not found: {song_dir}")

    s_t0 = time.time()
    print(f"\n========================================", flush=True)
    print(f"Starting {os.path.basename(song_dir)}", flush=True)
    print(f"========================================", flush=True)

    raw_dir = os.path.join(song_dir, "raw")
    if not resume:
        for f in glob.glob(os.path.join(raw_dir, "*.mxl")) + glob.glob(os.path.join(raw_dir, "*.omr")):
            try:
                os.remove(f)
            except OSError as e:
                print(f"Warning: failed to remove {f}: {e}", flush=True)
        print(f"Cleaned raw/*.mxl and raw/*.omr in {song_dir}", flush=True)
    else:
        print(f"Resuming {song_dir} (preserving completed pages in raw/)", flush=True)

    imgs = sorted(glob.glob(os.path.join(song_dir, "input", "omr_in", "*.png")))
    if not imgs:
        sys.exit(f"Error: no input images found in {song_dir}/input/omr_in/*.png")

    print(f"Running Audiveris on {len(imgs)} pages...", flush=True)
    cmd_av = [sys.executable, os.path.join(HERE, "run_audiveris.py")] + extra_av_args + [song_dir] + imgs
    res_av = subprocess.run(cmd_av)
    if res_av.returncode != 0:
        print(f"Audiveris failed for {song_dir}", flush=True)
        return False

    print(f"Running bandscore_postprocess.py...", flush=True)
    cmd_pp = [sys.executable, os.path.join(HERE, "bandscore_postprocess.py"), song_dir]
    res_pp = subprocess.run(cmd_pp)
    if res_pp.returncode != 0:
        print(f"Postprocess failed for {song_dir}", flush=True)
        return False

    elapsed = time.time() - s_t0
    print(f"Done {os.path.basename(song_dir)} in {elapsed:.1f}s ({elapsed/60:.1f}m)", flush=True)
    return True


def main():
    resume = False
    extra_av_args = []
    songs = []
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--resume":
            resume = True
        elif a in ("--no-mask-header", "--mask-header"):
            extra_av_args.append(a)
        elif a in ("--mask-start-page", "--mask-max-ratio", "--mask-ink-thresh", "--mask-fixed-ratio"):
            extra_av_args.extend([a, sys.argv[i + 1]])
            i += 1
        elif a.startswith("--"):
            extra_av_args.append(a)
        else:
            songs.append(a)
        i += 1

    if not songs:
        sys.exit("Usage: python tools/batch_rerun.py [--resume] [--no-mask-header] <song> ...")

    t0 = time.time()
    failed = []
    for arg in songs:
        ok = run_song(arg, resume=resume, extra_av_args=extra_av_args)
        if not ok:
            failed.append(arg)
            break

    total = time.time() - t0
    print(f"\n========================================", flush=True)
    if failed:
        print(f"Batch rerun FAILED on {failed} after {total:.1f}s ({total/60:.1f}m)", flush=True)
        sys.exit(1)
    else:
        print(f"Batch rerun SUCCEEDED in {total:.1f}s ({total/60:.1f}m)", flush=True)


if __name__ == "__main__":
    main()
