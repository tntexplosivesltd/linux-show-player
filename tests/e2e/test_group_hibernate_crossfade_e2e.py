#!/usr/bin/env python3
"""E2E: hibernating a crossfading playlist group, then resuming it.

The show pattern: a background playlist GroupCue (crossfade, loop) is
hibernated by a Fade & Stop (action Hibernate) and brought back by a
Fade & Resume.

A. Hibernate fired mid-crossfade (both children audible).
B. The crossfade point falls inside the hibernate fade (M78): the
   group must not start the next child, which the fade would miss.
C. The current child ends naturally inside the fade (M78): the next
   child is held back, and starts on the resume.

After the hibernate: the group is Pause, no child is still Running,
and the music is silent at the pause. After the resume: exactly one
child plays and no child is left Paused outside the group.

Run:
    poetry run python tests/e2e/test_group_hibernate_crossfade_e2e.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.e2e import helpers as _h  # noqa: E402
from tests.e2e.helpers import (  # noqa: E402
    call,
    parse_args,
    resolve_suite_port,
    start_lisp,
    stop_lisp,
)
from tests.e2e.test_groups_e2e import (  # noqa: E402
    AUDIO_DIR,
    create_test_audio,
)

_pass = 0
_fail = 0
_errors = []


def check(name, condition, detail=""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS: {name}")
    else:
        _fail += 1
        _errors.append(name)
        print(f"  FAIL: {name} {detail}")


def state(cue_id):
    return call("cue.state", {"id": cue_id})["state_name"]


def wait_state(cue_id, pred, timeout=5.0):
    deadline = time.time() + timeout
    s = ""
    while time.time() < deadline:
        s = state(cue_id)
        if pred(s):
            return True
        time.sleep(0.05)
    return False


def live_volume(cue_id):
    return call("cue.get_element_property", {
        "id": cue_id, "element": "Volume", "property": "live_volume",
    })["value"]


def snapshot(label, ids):
    out = {n: state(i) for n, i in ids.items()}
    print(f"    [{label}] " + ", ".join(f"{n}={s}" for n, s in out.items()))
    return out


class VolumeSampler:
    """Record (t, {name: live_volume}) for the given children."""

    def __init__(self, ids):
        self.ids = ids
        self.samples = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            row = {}
            for n, i in self.ids.items():
                try:
                    if "Running" in state(i):
                        row[n] = round(live_volume(i), 3)
                except Exception:
                    pass
            self.samples.append((time.time(), row))
            time.sleep(0.05)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(2)


def setup():
    for cue in call("cue.list"):
        call("cue.remove", {"id": cue["id"]})
    time.sleep(0.3)
    call("cue.add_from_uri", {"files": [
        os.path.join(AUDIO_DIR, f"tone_{n}.wav") for n in "ABC"
    ]})
    time.sleep(1)
    ids = {c["name"]: c["id"] for c in call("cue.list")}
    kids = [ids["tone_A"], ids["tone_B"], ids["tone_C"]]
    call("layout.context_action", {
        "action": "Group selected", "cue_ids": kids,
    })
    time.sleep(0.3)
    group = next(
        c["id"] for c in call("cue.list") if c["_type_"] == "GroupCue"
    )
    for prop, value in (
        ("group_mode", "playlist"), ("crossfade", 2.0), ("loop", True),
    ):
        call("cue.set_property", {
            "id": group, "property": prop, "value": value,
        })
    return group, {"A": kids[0], "B": kids[1], "C": kids[2]}


def add_action_cues(group, hib_ms, resume_ms):
    hib = call("cue.add", {"type": "StopCue", "properties": {
        "name": "Hibernate group", "target_id": group,
        "action": "Hibernate", "duration": hib_ms,
    }})["id"]
    res = call("cue.add", {"type": "ResumeCue", "properties": {
        "name": "Resume group", "target_id": group,
        "duration": resume_ms,
    }})["id"]
    return hib, res


def reset(group, kids, *extra):
    call("layout.stop_all")
    for c in (group, *kids.values()):
        wait_state(c, lambda s: s == "Stop", timeout=5)
    for c in extra:
        call("cue.remove", {"id": c})
    time.sleep(0.3)


def after_hibernate_and_resume(tag, group, kids, res, sampler):
    ok = wait_state(group, lambda s: "Pause" in s, timeout=6)
    check(f"{tag}: group paused by the hibernate", ok, state(group))
    t_pause = time.time()
    snapshot("at pause", {"group": group, **kids})

    # Silence at the pause: each child's last sample while it played
    # (the sampler polls every ~50 ms, so allow a little ramp left).
    series = {}
    for t, row in sampler.samples:
        if t <= t_pause:
            for name, level in row.items():
                series.setdefault(name, []).append(level)
    stopped = {n: state(i) == "Stop" for n, i in kids.items()}
    last = {}
    for name, levels in series.items():
        # Faded out, then read back at its saved level as it stopped:
        # GstMedia.stop() resets the Volume element before the
        # pipeline leaves PLAYING (M79, on master too). Not this
        # test's subject: judge the fade by the level before the
        # reset, however many readings caught it.
        reset = len(levels)
        while reset > 1 and levels[reset - 1] >= 0.99:
            reset -= 1
        if stopped[name] and reset < len(levels) and (
            levels[reset - 1] <= 0.15
        ):
            print(f"    {name}: level reset on stop seen (M79)")
            levels = levels[:reset]
        last[name] = levels[-1]
    loud = {n: v for n, v in last.items() if v > 0.15}
    check(f"{tag}: music silent when the hibernate pauses it",
          not loud, f"last live_volume before the pause: {loud}")
    if loud:
        t0 = sampler.samples[0][0] if sampler.samples else t_pause
        for name in loud:
            timed = [
                (round(t - t0, 2), row[name])
                for t, row in sampler.samples if name in row
            ]
            print(f"    {name} series (s since the fade, level): "
                  f"{timed}; pause seen at {round(t_pause - t0, 2)}")

    time.sleep(1.5)  # let any outgoing stop worker finish
    s = snapshot("1.5 s after pause", {"group": group, **kids})
    running = [n for n in kids if "Running" in s[n]]
    check(f"{tag}: no child still running while hibernated",
          not running, f"running: {running}")

    call("cue.execute", {"id": res, "action": "Start"})
    ok = wait_state(group, lambda s: s == "Running", timeout=5)
    check(f"{tag}: group running after resume", ok, state(group))
    time.sleep(1.0)
    s = snapshot("1 s after resume", {"group": group, **kids})
    running = [n for n in kids if "Running" in s[n]]
    paused = [n for n in kids if "Pause" in s[n]]
    check(f"{tag}: exactly one child playing after resume",
          len(running) == 1, f"running: {running}")
    check(f"{tag}: no child left paused after resume",
          not paused, f"paused: {paused}")
    return running


def test_a_hibernate_mid_crossfade(group, kids):
    print("\n═══ A: hibernate fired mid-crossfade ═══")
    hib, res = add_action_cues(group, hib_ms=500, resume_ms=500)
    try:
        call("cue.execute", {"id": group, "action": "Start"})
        wait_state(kids["A"], lambda s: s == "Running")
        call("cue.seek", {"id": kids["A"], "position": 5500})
        check("A: crossfade started B",
              wait_state(kids["B"], lambda s: "Running" in s, timeout=5))
        time.sleep(0.3)  # both audible, A fading out (2 s)
        snapshot("mid crossfade", {"group": group, **kids})
        with VolumeSampler(kids) as sampler:
            call("cue.execute", {"id": hib, "action": "Start"})
            running = after_hibernate_and_resume(
                "A", group, kids, res, sampler)
        check("A: B is the child that plays on", running == ["B"],
              f"running: {running}")
    finally:
        reset(group, kids, hib, res)


def test_b_crossfade_during_hibernate_fade(group, kids):
    print("\n═══ B: crossfade begins during the hibernate fade ═══")
    hib, res = add_action_cues(group, hib_ms=2000, resume_ms=500)
    try:
        call("cue.execute", {"id": group, "action": "Start"})
        wait_state(kids["A"], lambda s: s == "Running")
        # 8 s tone, 2 s crossfade: the crossfade starts at 6.0 s,
        # 0.8 s into the 2 s hibernate fade.
        call("cue.seek", {"id": kids["A"], "position": 5200})
        time.sleep(0.1)
        with VolumeSampler(kids) as sampler:
            call("cue.execute", {"id": hib, "action": "Start"})
            wait_state(group, lambda s: "Pause" in s, timeout=6)
            check("B: no crossfade into B inside the fade",
                  state(kids["B"]) == "Stop", state(kids["B"]))
            after_hibernate_and_resume("B", group, kids, res, sampler)
    finally:
        reset(group, kids, hib, res)


def test_c_natural_end_during_hibernate_fade(group, kids):
    print("\n═══ C: current child ends inside the hibernate fade ═══")
    call("cue.set_property", {
        "id": group, "property": "crossfade", "value": 0.0,
    })
    hib, res = add_action_cues(group, hib_ms=2000, resume_ms=2000)
    try:
        call("cue.execute", {"id": group, "action": "Start"})
        wait_state(kids["A"], lambda s: s == "Running")
        # 8 s tone: A ends 1 s into the 2 s hibernate fade.
        call("cue.seek", {"id": kids["A"], "position": 7000})
        with VolumeSampler(kids) as sampler:
            call("cue.execute", {"id": hib, "action": "Start"})
            ok = wait_state(kids["A"], lambda s: s == "Stop", timeout=4)
            check("C: A ended inside the fade", ok, state(kids["A"]))
            check("C: B not started inside the fade",
                  "Stop" == state(kids["B"]), state(kids["B"]))
            ok = wait_state(group, lambda s: "Pause" in s, timeout=4)
            check("C: group paused by the hibernate", ok, state(group))
            snapshot("at pause", {"group": group, **kids})
        check("C: nothing played inside the fade after A",
              not any("B" in row or "C" in row
                      for _, row in sampler.samples),
              "B or C sampled while running")

        with VolumeSampler({"B": kids["B"]}) as ramp:
            call("cue.execute", {"id": res, "action": "Start"})
            ok = wait_state(kids["B"], lambda s: s == "Running", timeout=5)
            check("C: resume starts B, the child after A", ok,
                  state(kids["B"]))
            time.sleep(2.5)  # the 2 s Fade & Resume
        levels = [row["B"] for _, row in ramp.samples if "B" in row]
        print(f"    B live_volume after the resume: {levels[:4]} ... "
              f"{levels[-2:]}")
        # Fade & Resume fades the held child in (it wasn't playing,
        # so no fader of its covered it): it starts low and rises.
        check("C: B fades in on the resume, not a hard start",
              bool(levels) and levels[0] < 0.5,
              f"levels {levels[:3]} ... {levels[-2:]}")
        # The ramp runs in stream time, which can start late (M74):
        # poll for the end of it rather than assume the wall clock.
        deadline = time.time() + 5.0
        while time.time() < deadline and live_volume(kids["B"]) < 0.95:
            time.sleep(0.1)
        check("C: B reaches its full level",
              live_volume(kids["B"]) >= 0.95,
              f"live_volume {live_volume(kids['B'])}")
        s = snapshot("1 s after resume", {"group": group, **kids})
        check("C: A not restarted", s["A"] == "Stop", s["A"])
    finally:
        reset(group, kids, hib, res)
        call("cue.set_property", {
            "id": group, "property": "crossfade", "value": 2.0,
        })


def main():
    args = parse_args("E2E: hibernate a crossfading playlist group")
    _h.HOST = args.host
    port = resolve_suite_port(args)
    if port is not None:
        _h.PORT = port
    create_test_audio()
    # E2E_HIB_CASES / E2E_HIB_REPS narrow and repeat the run (for
    # chasing an intermittent failure); default: every case, twice.
    cases = {
        "A": test_a_hibernate_mid_crossfade,
        "B": test_b_crossfade_during_hibernate_fade,
        "C": test_c_natural_end_during_hibernate_fade,
    }
    chosen = (os.environ.get("E2E_HIB_CASES") or "ABC").upper()
    unknown = set(chosen) - set(cases)
    if unknown:
        sys.exit(f"E2E_HIB_CASES: no case {''.join(sorted(unknown))}"
                 f" (cases: {''.join(cases)})")
    if not args.no_launch:
        start_lisp()
    try:
        group, kids = setup()
        for _ in range(int(os.environ.get("E2E_HIB_REPS") or 2)):
            for name in chosen:
                cases[name](group, kids)
    finally:
        call("layout.stop_all")
        if not args.no_launch:
            stop_lisp()

    print(f"\n{'═' * 40}\n  {_pass} passed, {_fail} failed")
    if _errors:
        print(f"  Failures: {', '.join(_errors)}")
    print("═" * 40)
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
