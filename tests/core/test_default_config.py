# This file is part of Linux Show Player
#
# Copyright 2016 Francesco Ceruti <ceppofrancy@gmail.com>
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

import json
from pathlib import Path


def test_default_config_has_pre_arm_block():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "lisp" / "default.json"
    config = json.loads(path.read_text())
    assert "preArm" in config
    assert config["preArm"]["enabled"] is True
    assert config["preArm"]["lookahead"] == 1
    assert config["preArm"]["maxArmed"] == 16
    assert config["preArm"]["failOnCapHit"] is False
