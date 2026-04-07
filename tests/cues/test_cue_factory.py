import pytest
from unittest.mock import MagicMock

from lisp.cues.cue_factory import CueFactory


class TestCueFactory:
    def test_register_and_create(self):
        app = MagicMock()
        factory = CueFactory(app)

        def cue_builder(**kwargs):
            cue = MagicMock()
            cue.type = "TestCue"
            return cue

        factory.register_factory("TestCue", cue_builder)
        cue = factory.create_cue("TestCue")
        assert cue is not None

    def test_has_factory(self):
        factory = CueFactory(MagicMock())
        factory.register_factory("X", MagicMock())
        assert factory.has_factory("X")
        assert not factory.has_factory("Y")

    def test_remove_factory(self):
        factory = CueFactory(MagicMock())
        factory.register_factory("X", MagicMock())
        factory.remove_factory("X")
        assert not factory.has_factory("X")

    def test_create_unregistered_raises(self):
        factory = CueFactory(MagicMock())
        with pytest.raises(Exception, match="not available"):
            factory.create_cue("NonExistent")

    def test_create_passes_app_and_id(self):
        app = MagicMock()
        factory = CueFactory(app)
        calls = []

        def builder(**kwargs):
            calls.append(kwargs)
            return MagicMock()

        factory.register_factory("T", builder)
        factory.create_cue("T", cue_id="my-id")
        assert calls[0]["app"] is app
        assert calls[0]["id"] == "my-id"

    def test_clone_cue(self):
        app = MagicMock()
        factory = CueFactory(app)

        original = MagicMock()
        original.__class__.__name__ = "TestCue"
        original.properties.return_value = {
            "id": "orig-id",
            "name": "My Cue",
            "x": 42,
        }

        created = MagicMock()
        factory.register_factory("TestCue", lambda **kw: created)

        clone = factory.clone_cue(original)
        # The clone should have update_properties called without 'id'
        created.update_properties.assert_called_once()
        props = created.update_properties.call_args[0][0]
        assert "id" not in props
        assert props["name"] == "My Cue"
