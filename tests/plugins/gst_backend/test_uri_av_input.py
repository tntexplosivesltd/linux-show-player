"""Tests for UriAvInput element."""

from unittest.mock import MagicMock

from lisp.backend.media_element import ElementType, MediaType
from lisp.plugins.gst_backend.gi_repository import Gst
from lisp.plugins.gst_backend.elements.uri_av_input import UriAvInput


class TestUriAvInputProperties:
    def test_media_type(self):
        assert UriAvInput.MediaType == MediaType.AudioAndVideo

    def test_element_type(self):
        assert UriAvInput.ElementType == ElementType.Input

    def test_name(self):
        assert UriAvInput.Name == "URI A/V Input"


class TestUriAvInputConstruction:
    def test_creates_pipeline_elements(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.decoder is not None
        assert element.audio_queue is not None
        assert element.audio_convert is not None
        assert element.video_queue is not None
        assert element.video_convert is not None
        assert element.video_scale is not None

    def test_src_returns_audioconvert(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.src() is element.audio_convert

    def test_video_src_returns_videoscale(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element.video_src() is element.video_scale

    def test_dispose_disconnects_handlers(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        # Should not raise
        element.dispose()

    def test_initial_link_state(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        assert element._audio_linked is False
        assert element._video_linked is False


class TestOnPadAdded:
    """Test the __on_pad_added callback logic."""

    def _make_element(self):
        pipeline = Gst.Pipeline()
        return UriAvInput(pipeline)

    def _make_pad(self, media_type):
        """Create a mock pad with caps of the given media type."""
        mock_pad = MagicMock()
        mock_caps = MagicMock()
        mock_struct = MagicMock()
        mock_struct.get_name.return_value = media_type
        mock_caps.get_structure.return_value = mock_struct
        mock_pad.get_current_caps.return_value = mock_caps
        return mock_pad

    def test_audio_pad_links_to_audio_queue(self):
        element = self._make_element()
        pad = self._make_pad("audio/x-raw")

        audio_sink = element.audio_queue.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        # Call the private method directly (name-mangled)
        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(audio_sink)
        assert element._audio_linked is True

    def test_video_pad_links_to_video_queue(self):
        element = self._make_element()
        pad = self._make_pad("video/x-raw")

        video_sink = element.video_queue.get_static_pad("sink")
        pad.link.return_value = Gst.PadLinkReturn.OK

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_called_once_with(video_sink)
        assert element._video_linked is True

    def test_null_caps_ignored(self):
        element = self._make_element()
        pad = MagicMock()
        pad.get_current_caps.return_value = None

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()
        assert element._audio_linked is False
        assert element._video_linked is False

    def test_unknown_media_type_ignored(self):
        element = self._make_element()
        pad = self._make_pad("application/x-id3")

        element._UriAvInput__on_pad_added(element.decoder, pad)

        pad.link.assert_not_called()

    def test_duplicate_audio_pad_ignored(self):
        element = self._make_element()

        # First link succeeds
        first_pad = self._make_pad("audio/x-raw")
        first_pad.link.return_value = Gst.PadLinkReturn.OK
        element._UriAvInput__on_pad_added(
            element.decoder, first_pad
        )
        assert element._audio_linked is True

        # Second audio pad — _audio_linked flag prevents linking
        second_pad = self._make_pad("audio/x-raw")
        element._UriAvInput__on_pad_added(
            element.decoder, second_pad
        )
        second_pad.link.assert_not_called()

    def test_link_failure_logged(self):
        element = self._make_element()
        pad = self._make_pad("audio/x-raw")
        pad.link.return_value = Gst.PadLinkReturn.WRONG_HIERARCHY

        element._UriAvInput__on_pad_added(element.decoder, pad)

        assert element._audio_linked is False


def _make_fake_decoder(*, audio=False, video=False):
    """Build a ``Gst.Bin`` that mimics uridecodebin's
    no-more-pads state for splice-decision tests.

    ``audio`` / ``video`` toggle whether a corresponding src pad
    is attached.  Pads are created from templates so they carry
    only template caps; ``UriAvInput.__streams_present`` falls
    back to ``query_caps`` for that case.  Real uridecodebin
    pads carry negotiated current caps at no-more-pads time.
    """
    bin_ = Gst.Bin.new(None)
    index = 0
    if audio:
        caps = Gst.Caps.from_string("audio/x-raw")
        tmpl = Gst.PadTemplate.new(
            f"src_{index}",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            caps,
        )
        bin_.add_pad(Gst.Pad.new_from_template(tmpl, f"src_{index}"))
        index += 1
    if video:
        caps = Gst.Caps.from_string("video/x-raw")
        tmpl = Gst.PadTemplate.new(
            f"src_{index}",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            caps,
        )
        bin_.add_pad(Gst.Pad.new_from_template(tmpl, f"src_{index}"))
    return bin_


class TestNoMorePads:
    """Test the __on_no_more_pads callback.

    When uridecodebin reports no audio or no video stream, the
    handler splices a num-buffers=0 testsrc upstream of the
    orphaned branch so its downstream sink prerolls on EOS. The
    branches themselves stay in the pipeline — see the docstring
    on __on_no_more_pads for why removing them caused qtdemux
    not-linked aborts.

    The splice decision is driven by which source pads exist on
    decodebin at no-more-pads time.  Tests therefore construct a
    fake decoder via ``_make_fake_decoder`` rather than relying
    on the ``_audio_linked`` / ``_video_linked`` flags, which
    only guard duplicate-link in ``__on_pad_added`` after the
    race fix in ``__on_no_more_pads`` (see
    ``TestNoMorePadsRaceFix``).
    """

    def _pipeline_has(self, pipeline, element):
        """Check if a GStreamer element is in the pipeline."""
        name = element.get_name()
        return pipeline.get_by_name(name) is not None

    def test_inserts_video_filler_when_no_video(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(audio=True)

        element._UriAvInput__on_no_more_pads(decoder)

        assert self._pipeline_has(pipeline, element.audio_queue)
        assert self._pipeline_has(pipeline, element.video_queue)
        assert element._silence_src is None
        assert element._video_filler_src is not None
        assert self._pipeline_has(
            pipeline, element._video_filler_src
        )

    def test_inserts_silence_src_when_no_audio(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(video=True)

        element._UriAvInput__on_no_more_pads(decoder)

        assert self._pipeline_has(pipeline, element.audio_queue)
        assert self._pipeline_has(pipeline, element.video_queue)
        assert element._silence_src is not None
        assert self._pipeline_has(pipeline, element._silence_src)
        assert element._video_filler_src is None

    def test_keeps_both_when_both_linked(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(audio=True, video=True)

        element._UriAvInput__on_no_more_pads(decoder)

        assert self._pipeline_has(pipeline, element.audio_queue)
        assert self._pipeline_has(pipeline, element.video_queue)
        assert element._silence_src is None
        assert element._video_filler_src is None

    def test_stop_tears_down_filler_sources(self):
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder()  # no streams

        element._UriAvInput__on_no_more_pads(decoder)
        silence = element._silence_src
        video_filler = element._video_filler_src
        assert silence is not None and video_filler is not None
        assert self._pipeline_has(pipeline, silence)
        assert self._pipeline_has(pipeline, video_filler)

        element.stop()

        assert element._silence_src is None
        assert element._video_filler_src is None
        assert not self._pipeline_has(pipeline, silence)
        assert not self._pipeline_has(pipeline, video_filler)


class TestNoMorePadsRaceFix:
    """Regression: silent-EOS splice mis-fires when uridecodebin's
    `pad-added` and `no-more-pads` Python callbacks race.

    Both signals are emitted from streaming threads and contend for
    the GIL.  Under load the interpreter can schedule
    `__on_no_more_pads` first, see `_audio_linked == False`, and
    splice an `audiotestsrc num-buffers=0` upstream of an audio
    queue that DOES have a real audio pad about to be linked by
    the still-pending `__on_pad_added` callback.  The result is
    a cue that stalls at 00:00.00 with two
    `gst_segment_to_running_time` GStreamer-CRITICAL warnings.

    Fix: ignore the `_audio_linked` / `_video_linked` flags for
    the splice decision.  Inspect the decodebin's source pads
    directly — by the GStreamer contract, when `no-more-pads`
    fires, all pads are physically attached at the C level
    (only their Python notifications may be queued).

    See docs/bugs/2026-05-03-uri-av-input-silent-eos-false-positive.md
    """

    def test_audio_pad_present_no_splice_despite_flag_false(self):
        """The race state: audio pad attached at C level, but
        `_audio_linked` is still False because `__on_pad_added`'s
        Python callback hasn't run.  The handler must inspect the
        decodebin and see the audio pad — no silence splice.
        """
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(audio=True)
        element._audio_linked = False
        element._video_linked = False

        element._UriAvInput__on_no_more_pads(decoder)

        assert element._silence_src is None, (
            "Silent-EOS splice mis-fired: the file has an audio "
            "pad on decodebin; the flag is only stale because "
            "pad-added's Python callback hadn't run yet."
        )
        # Video filler is correct here — decoder has no video pad.
        assert element._video_filler_src is not None

    def test_video_pad_present_no_splice_despite_flag_false(self):
        """Mirror of the audio race: video pad present, flag
        still False because `__on_pad_added` hadn't run.  No
        video filler should be spliced.
        """
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(video=True)
        element._audio_linked = False
        element._video_linked = False

        element._UriAvInput__on_no_more_pads(decoder)

        assert element._video_filler_src is None, (
            "Video filler splice mis-fired: the file has a "
            "video pad on decodebin; the flag is only stale "
            "because pad-added's Python callback hadn't run yet."
        )
        assert element._silence_src is not None

    def test_both_pads_present_no_splices(self):
        """Healthy file with both streams: no splices regardless
        of flag state.
        """
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder(audio=True, video=True)
        # Worst-case race: NEITHER pad-added callback has run.
        element._audio_linked = False
        element._video_linked = False

        element._UriAvInput__on_no_more_pads(decoder)

        assert element._silence_src is None
        assert element._video_filler_src is None

    def test_no_pads_both_splices(self):
        """Genuinely-empty decodebin: both fillers spliced.  This
        is the case `91519a16` originally introduced the splice
        for.
        """
        pipeline = Gst.Pipeline()
        element = UriAvInput(pipeline)
        decoder = _make_fake_decoder()  # no pads
        # Flags True here — proves splice decision ignores them.
        element._audio_linked = True
        element._video_linked = True

        element._UriAvInput__on_no_more_pads(decoder)

        assert element._silence_src is not None
        assert element._video_filler_src is not None
