#!/usr/bin/env python3
# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

"""E2E: an image cue is fitted to the projection window, whole.

A four-quadrant test image (red / green / blue / yellow inside a white
frame) plays as an image cue (silent) while the window manager
repeatedly fullscreens and restores the projection window. After each
change the fit is judged from SCREEN pixels (a root-window grab cropped
to the window): the window's own buffer can be correct while the
screen shows the bug — the GL sink drawing at a stale, mid-resize
window size, so the picture is squeezed into part of the window, or
magnified and cropped.

The judge (judge()) samples the middle of the white frame along every
edge, so a magnification above ~1.07x (the frame pushed off screen) or
a squeeze (black where the frame should be) fails, the quadrant
centres, and the letterbox bars, which must be black.

Requires an X display, ffmpeg (x11grab), xwininfo, libX11 and a window
manager that honours _NET_WM_STATE fullscreen; SKIPs otherwise (exit
77: under bare Xvfb in CI/Docker it checks nothing). It grabs real screen pixels:
keep other windows off the projection window while it runs.

Run:
    poetry run python tests/e2e/test_video_image_fit_e2e.py
"""

import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e.helpers import call, run_suite  # noqa: E402

IMG_W, IMG_H = 1600, 900  # 16:9
# White frame around the quadrants, as a fraction of each side. Its
# middle (EDGE) is sampled: any magnification above 1 / (1 - 2 * EDGE)
# ~ 1.07x moves image content there.
BORDER = 0.06
EDGE = BORDER / 2
GRAB_W = 160
SETTLE_S = 0.6
RECHECK_S = 2.0
# First paint after cue.start, polled: a cold start can take seconds.
INITIAL_TIMEOUT_S = 10.0
CYCLES = int(os.environ.get("FIT_CYCLES", "30"))

COLOURS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
}


def have_tools():
    return bool(os.environ.get("DISPLAY") and shutil.which("ffmpeg")
                and shutil.which("xwininfo")
                and ctypes.util.find_library("X11"))


def make_image(path):
    """Quadrants TL red, TR green, BL blue, BR yellow, in a white
    frame BORDER wide on each side."""
    bx, by = round(IMG_W * BORDER), round(IMG_H * BORDER)
    half_w, half_h = (IMG_W - 2 * bx) // 2, (IMG_H - 2 * by) // 2
    src = (
        f"color=red:s={half_w}x{half_h}[a];"
        f"color=lime:s={half_w}x{half_h}[b];"
        f"color=blue:s={half_w}x{half_h}[c];"
        f"color=yellow:s={half_w}x{half_h}[d];"
        "[a][b]hstack[top];[c][d]hstack[bot];[top][bot]vstack,"
        f"pad={IMG_W}:{IMG_H}:{bx}:{by}:white"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src,
         "-frames:v", "1", path],
        check=True,
    )


def grab_screen(geom):
    """(width, height, pixels): the screen area under the window,
    downscaled. Root-window grab = what is actually displayed."""
    x, y, w, h = geom
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "x11grab",
         "-video_size", f"{w}x{h}", "-i", f"{os.environ['DISPLAY']}+{x},{y}",
         "-frames:v", "1", "-vf", f"scale={GRAB_W}:-2",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True,
    ).stdout
    n = len(raw) // 3
    h = n // GRAB_W
    px = [tuple(raw[i * 3:i * 3 + 3]) for i in range(n)]
    return GRAB_W, h, px


def window_geometry(handle):
    """(x, y, width, height) of the window, in root coordinates."""
    out = subprocess.run(["xwininfo", "-id", str(handle)],
                         capture_output=True, text=True).stdout

    def get(key):
        m = re.search(key + r": +(-?\d+)", out)
        return int(m.group(1)) if m else None

    vals = [get(k) for k in ("Absolute upper-left X",
                             "Absolute upper-left Y", "Width", "Height")]
    return None if None in vals else tuple(vals)


def find_window(name):
    out = subprocess.run(["xwininfo", "-root", "-tree"],
                         capture_output=True, text=True).stdout
    m = re.search(r"(0x[0-9a-f]+) \"" + re.escape(name) + r"\"", out)
    return int(m.group(1), 16) if m else None


class _XClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int), ("data", ctypes.c_long * 5),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("xclient", _XClientMessage), ("pad", ctypes.c_long * 24)]


def _x11():
    x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_int]
    x11.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                  ctypes.c_uint, ctypes.c_uint]
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                               ctypes.c_int, ctypes.c_long,
                               ctypes.POINTER(_XEvent)]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x11


def set_wm_fullscreen(win, enabled):
    """Ask the window manager to (un)fullscreen `win` — an
    external, WM-driven size change, as when a tiling WM re-arranges
    the window, not one requested from inside LiSP."""
    x11 = _x11()
    dpy = x11.XOpenDisplay(None)
    try:
        ev = _XEvent()
        ev.xclient.type = 33  # ClientMessage
        ev.xclient.send_event = 1
        ev.xclient.display = dpy
        ev.xclient.window = win
        ev.xclient.message_type = x11.XInternAtom(
            dpy, b"_NET_WM_STATE", 0)
        ev.xclient.format = 32
        ev.xclient.data[0] = 1 if enabled else 0  # _NET_WM_STATE_ADD/REMOVE
        ev.xclient.data[1] = x11.XInternAtom(
            dpy, b"_NET_WM_STATE_FULLSCREEN", 0)
        ev.xclient.data[3] = 1  # source: normal application
        mask = (1 << 20) | (1 << 19)  # SubstructureRedirect|Notify
        x11.XSendEvent(dpy, x11.XDefaultRootWindow(dpy), 0, mask,
                       ctypes.byref(ev))
        x11.XFlush(dpy)
    finally:
        x11.XCloseDisplay(dpy)


def screen_locked():
    """True if a screen locker is up: its window covers everything, so
    every screen grab would be judged a wrong fit."""
    return subprocess.run(
        ["pgrep", "-x", "i3lock|xsecurelock|slock|xscreensaver-gfx"],
        capture_output=True,
    ).returncode == 0


def nearest(rgb):
    def d(c):
        return sum((a - b) ** 2 for a, b in zip(rgb, c))
    name, col = min(COLOURS.items(), key=lambda kv: d(kv[1]))
    return name if d(col) < 120 ** 2 else "other"


def expected_rect(win_w, win_h):
    """Aspect-preserving, centred fit of the image into the window."""
    scale = min(win_w / IMG_W, win_h / IMG_H)
    w, h = IMG_W * scale, IMG_H * scale
    return (win_w - w) / 2, (win_h - h) / 2, w, h


# Where judge() samples, as fractions of the expected image rect.
FRAME_POINTS = {
    "frame TL": (EDGE, EDGE), "frame T": (0.5, EDGE),
    "frame TR": (1 - EDGE, EDGE), "frame R": (1 - EDGE, 0.5),
    "frame BR": (1 - EDGE, 1 - EDGE), "frame B": (0.5, 1 - EDGE),
    "frame BL": (EDGE, 1 - EDGE), "frame L": (EDGE, 0.5),
}
QUADRANT_POINTS = {
    "red": (0.28, 0.28), "green": (0.72, 0.28),
    "blue": (0.28, 0.72), "yellow": (0.72, 0.72),
}
# A bar narrower than this many grab pixels is not sampled (scaling
# blur would read the image's edge).
MIN_BAR_PX = 3


def judge(gw, gh, px, win_w, win_h):
    """{sample: (wanted, seen)} for a grab (gw x gh rgb24 pixels) of a
    win_w x win_h window that should show the image fitted, whole."""
    x0, y0, w, h = expected_rect(win_w, win_h)
    sx, sy = gw / win_w, gh / win_h

    def seen_at(x, y):  # window coordinates
        gx = max(0, min(gw - 1, int(x * sx)))
        gy = max(0, min(gh - 1, int(y * sy)))
        return nearest(px[gy * gw + gx])

    out = {}
    for name, (fx, fy) in FRAME_POINTS.items():
        out[name] = ("white", seen_at(x0 + w * fx, y0 + h * fy))
    for name, (fx, fy) in QUADRANT_POINTS.items():
        out[name] = (name, seen_at(x0 + w * fx, y0 + h * fy))
    # Letterbox bars: black, or the picture spills past its rect.
    if x0 * sx >= MIN_BAR_PX:
        out["bar L"] = ("black", seen_at(x0 / 2, win_h / 2))
        out["bar R"] = ("black", seen_at(win_w - x0 / 2, win_h / 2))
    if y0 * sy >= MIN_BAR_PX:
        out["bar T"] = ("black", seen_at(win_w / 2, y0 / 2))
        out["bar B"] = ("black", seen_at(win_w / 2, win_h - y0 / 2))
    return out


def fit_ok(handle, label, report=True):
    """True if the screen shows the whole image fitted to the window."""
    geom = window_geometry(handle)
    if not geom or geom[0] < 0 or geom[1] < 0:
        if report:
            print(f"  {label}: window not on screen ({geom})")
        return False
    gw, gh, px = grab_screen(geom)
    if not gh:
        if report:
            print(f"  {label}: screen grab failed")
        return False
    _, _, win_w, win_h = geom
    samples = judge(gw, gh, px, win_w, win_h)
    wrong = {k: v for k, v in samples.items() if v[0] != v[1]}
    if report:
        print(f"  {label}: window {win_w}x{win_h} -> "
              f"{'fit ok' if not wrong else 'WRONG ' + str(wrong)}")
    return not wrong


def wait_fit(handle, label, timeout):
    """Poll fit_ok until it holds or `timeout` s pass; report once."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fit_ok(handle, label, report=False):
            break
        time.sleep(0.3)
    return fit_ok(handle, label)


def run_tests(t):
    if not have_tools():
        t.skip("need X display + ffmpeg + xwininfo + libX11")
        return
    tmp = tempfile.mkdtemp(prefix="lisp-fit-")
    made = {}  # what _run got to: "cue_id", "top"
    try:
        _run(t, tmp, made)
    finally:
        # Every early return (or exception) lands here: leave no cue
        # playing, no fullscreen window and no temp dir behind.
        if made.get("cue_id"):
            try:
                call("cue.stop", {"id": made["cue_id"]})
            except Exception as e:  # LiSP may already be gone
                print(f"  cleanup: cue.stop failed: {e}")
        if made.get("top"):
            set_wm_fullscreen(made["top"], False)
        shutil.rmtree(tmp, ignore_errors=True)


def wm_honours_fullscreen(top, handle):
    """True if a window manager acts on _NET_WM_STATE requests. Bare
    Xvfb (CI, Docker) has none: every "resize" would be a no-op and
    the run a vacuous pass."""
    before = window_geometry(handle)
    set_wm_fullscreen(top, True)
    deadline = time.time() + 3.0
    changed = False
    while time.time() < deadline and not changed:
        time.sleep(0.1)
        changed = window_geometry(handle) != before
    set_wm_fullscreen(top, False)
    time.sleep(SETTLE_S)
    return changed


def _run(t, img_dir, made):
    """The test body. Records the cue id and the top-level window in
    `made` as soon as they exist, for run_tests' cleanup."""
    img = os.path.join(img_dir, "quadrants.png")
    make_image(img)

    before = {c["id"] for c in call("cue.list")}
    call("cue.add_image_from_uri", {"uri": img, "duration": 60000})
    new = [c["id"] for c in call("cue.list") if c["id"] not in before]
    t.check("image cue added", len(new) == 1)
    if not new:
        return
    cue_id = made["cue_id"] = new[0]

    handle = call("video_window.state").get("handle", 0)
    t.check("projection handle valid", handle != 0)
    if not handle:
        return

    # Adding the cue shows the window; probe the WM before playing, so
    # a run with none is a SKIP whatever the first paint does.
    deadline = time.time() + 5.0
    while (not call("video_window.state").get("visible")
           and time.time() < deadline):
        time.sleep(0.1)
    top = made["top"] = find_window("LiSP Video Output")
    t.check("found the output top-level window", bool(top))
    if not top:
        return
    if not wm_honours_fullscreen(top, handle):
        t.skip("no window manager acted on _NET_WM_STATE fullscreen "
               "(bare Xvfb?): the resize cycles would test nothing")
        return

    call("cue.start", {"id": cue_id})
    initial = wait_fit(handle, "initial", INITIAL_TIMEOUT_S)
    t.check("initial fit (run INVALID if not: nothing to compare)", initial)
    if not initial:
        return

    # A wrong fit SETTLE_S after a resize is re-checked RECHECK_S later:
    # still wrong = stuck (the bug: it stays until the next resize);
    # right by then = slow (the new-size frame just hadn't landed yet).
    stuck = slow = 0
    for i in range(CYCLES):
        if screen_locked():
            t.check(f"screen not locked (INVALID run: locked at cycle "
                    f"{i + 1})", False)
            return
        for on in (True, False):
            label = f"cycle {i + 1} fullscreen={on}"
            set_wm_fullscreen(top, on)
            time.sleep(SETTLE_S)
            if fit_ok(handle, label):
                continue
            time.sleep(RECHECK_S)
            if fit_ok(handle, label + " recheck"):
                slow += 1
            else:
                stuck += 1
    print(f"  {2 * CYCLES} WM resizes: {stuck} stuck, {slow} slow "
          f"(> {SETTLE_S}s but fixed by {SETTLE_S + RECHECK_S}s)")
    # Either is visible to the audience: slow = a squeezed/magnified
    # flash on every resize, stuck = it stays.
    t.check(f"fit right within {SETTLE_S}s of all {2 * CYCLES} WM "
            f"resizes ({stuck} stuck, {slow} slow)", stuck + slow == 0)


if __name__ == "__main__":
    run_suite("Image fit to projection window", run_tests)
