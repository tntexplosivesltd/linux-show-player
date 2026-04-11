"""Prevent pytest from collecting E2E tests.

These tests require a running LiSP instance and are run
via their own __main__ entry point, not via pytest.
"""

collect_ignore = [
    "helpers.py",
    "test_collection_cue_e2e.py",
    "test_command_cue_e2e.py",
    "test_go_standby_e2e.py",
    "test_groups_e2e.py",
    "test_image_e2e.py",
    "test_media_playback_e2e.py",
    "test_notifications_e2e.py",
    "test_session_e2e.py",
    "test_undo_redo_e2e.py",
    "test_video_e2e.py",
    "test_video_window_e2e.py",
    "test_wait_chaining_e2e.py",
    "test_seek_cue_e2e.py",
    "test_index_action_cue_e2e.py",
    "test_volume_control_e2e.py",
    "test_cart_layout_e2e.py",
]
