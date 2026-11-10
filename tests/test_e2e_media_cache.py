"""The E2E scripts' generated-media cache (tests/e2e/helpers.py).

Clips are cached in a private per-user directory, not a fixed shared
/tmp path where anyone could plant files or symlinks first (and which
is wiped on reboot), and a clip is keyed on how it was made, so one
from an older generator is never silently reused.
"""

import os
import stat

import pytest

from tests.e2e import helpers


@pytest.fixture
def cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def test_cache_dir_is_private_and_under_the_user_cache(cache_home):
    path = helpers.media_cache_dir("avsync")
    assert path == str(cache_home / "lisp-e2e" / "avsync")
    mode = os.stat(path).st_mode
    assert stat.S_ISDIR(mode)
    assert mode & 0o077 == 0
    assert os.stat(os.path.dirname(path)).st_mode & 0o077 == 0


def test_cache_dir_defaults_to_home_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = helpers.media_cache_dir("x")
    assert path == str(tmp_path / ".cache" / "lisp-e2e" / "x")


def test_existing_dir_is_tightened(cache_home):
    loose = cache_home / "lisp-e2e" / "avsync"
    loose.mkdir(parents=True)
    os.chmod(loose, 0o777)
    helpers.media_cache_dir("avsync")
    assert os.stat(loose).st_mode & 0o077 == 0


def test_symlinked_cache_dir_is_refused(cache_home, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("planted")
    (cache_home / "lisp-e2e").mkdir()
    os.symlink(elsewhere, cache_home / "lisp-e2e" / "avsync")
    with pytest.raises(RuntimeError):
        helpers.media_cache_dir("avsync")


def test_media_path_is_keyed_on_the_recipe(cache_home):
    directory = helpers.media_cache_dir("avsync")
    a = helpers.media_path(directory, "clip.mp4", ["ffmpeg", "-r", "30"])
    same = helpers.media_path(directory, "clip.mp4", ["ffmpeg", "-r", "30"])
    other = helpers.media_path(directory, "clip.mp4", ["ffmpeg", "-r", "60"])
    assert a == same
    assert a != other
    assert os.path.dirname(a) == directory
    assert a.endswith(".mp4")
    assert os.path.basename(a).startswith("clip-")


def test_make_media_renames_a_finished_clip_into_place(tmp_path):
    target = str(tmp_path / "clip-abc.mp4")
    seen = []

    def generate(out):
        seen.append(out)
        assert out.endswith(".mp4")  # encoders infer the container
        with open(out, "wb") as f:
            f.write(b"data")

    helpers.make_media(target, generate)
    assert seen[0] != target
    assert open(target, "rb").read() == b"data"
    assert os.listdir(tmp_path) == ["clip-abc.mp4"]


def test_interrupted_generator_leaves_no_clip(tmp_path):
    target = str(tmp_path / "clip-abc.mp4")

    def generate(out):
        with open(out, "wb") as f:
            f.write(b"trunc")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        helpers.make_media(target, generate)
    assert os.listdir(tmp_path) == []


def test_existing_clip_is_reused(tmp_path):
    target = tmp_path / "clip-abc.mp4"
    target.write_bytes(b"cached")

    def generate(out):
        raise AssertionError("regenerated a cached clip")

    helpers.make_media(str(target), generate)
