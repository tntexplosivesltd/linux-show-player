# This file is part of Linux Show Player
#
# Copyright 2025 Thomas Sherlock
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

"""The E2E scripts' generated-media cache.

Standard library only and free of import-time side effects, so unit
tests can import it without pulling in helpers.py (which puts the test
harness directory on sys.path). helpers.py re-exports everything here.

The cache is per user and shared by every worktree, and several
worktrees may run E2E scripts at once (see CLAUDE.md), so every write
is safe against a concurrent writer of the same clip.
"""

import hashlib
import os
import tempfile


def media_cache_dir(name):
    """A private, persistent directory for one script's generated
    media: $XDG_CACHE_HOME/lisp-e2e/<name> (~/.cache by default).

    Not a fixed /tmp path, where another user could plant files or
    symlinks before us (and which is wiped on reboot). Each level is
    created owner-only, an existing one is tightened, and one that is
    a symlink or someone else's is refused, so whatever the directory
    holds was put there by this user. The base directory itself is
    trusted (it is the user's own cache); `name` must be a single path
    component, so it cannot escape it.
    """
    if (
        not name
        or name in (".", "..")
        or os.path.basename(name) != name
        or os.sep in name
        or (os.altsep and os.altsep in name)
    ):
        raise ValueError(f"media cache name {name!r} is not a plain name")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    path = base
    for part in ("lisp-e2e", name):
        path = os.path.join(path, part)
        os.makedirs(path, mode=0o700, exist_ok=True)
        info = os.lstat(path)
        if not os.path.isdir(path) or os.path.islink(path):
            raise RuntimeError(f"media cache {path} is not a directory")
        if info.st_uid != os.getuid():
            raise RuntimeError(f"media cache {path} is not ours")
        if info.st_mode & 0o077:
            os.chmod(path, 0o700)
    return path


def media_path(directory, filename, recipe):
    """Path for a generated clip in `directory`, keyed on `recipe`
    (e.g. the generator's command line minus its output path): change
    how a clip is made and it gets a new name, so a stale one from an
    older generator is never reused."""
    stem, ext = os.path.splitext(filename)
    key = hashlib.sha256(repr(recipe).encode()).hexdigest()[:12]
    return os.path.join(directory, f"{stem}-{key}{ext}")


def make_media(path, generate):
    """Create the clip at `path` with generate(tmp_path) unless it is
    already there.

    The generator writes a temporary file of its own (unique per call,
    same extension so encoders still infer the container), which is
    renamed into place only once it succeeds. An interrupted run leaves
    no truncated clip for later runs to reuse, and two runs generating
    the same clip at once never write the same file: each renames its
    own complete clip over the path (atomic), so whichever finishes
    last wins with a whole file.
    """
    if os.path.exists(path):
        return
    directory, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix=f"{stem}.", suffix=f".part{ext}")
    os.close(fd)
    try:
        generate(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
