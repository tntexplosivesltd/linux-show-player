"""Prevent pytest from collecting E2E tests.

These tests require a running LiSP instance and are run
via their own __main__ entry point, not via pytest.
"""

collect_ignore = [
    "helpers.py",
    "test_groups_e2e.py",
    "test_media_playback_e2e.py",
    "test_notifications_e2e.py",
    "test_session_e2e.py",
    "test_video_e2e.py",
]
