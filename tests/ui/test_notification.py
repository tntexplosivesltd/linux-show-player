from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

from lisp.ui.widgets.notification import (
    NotificationLevel,
    NotificationToast,
)


class TestNotificationToast:
    def test_initially_hidden(self, qtbot):
        parent = QWidget()
        qtbot.addWidget(parent)
        toast = NotificationToast(parent)
        assert not toast.isVisible()

    def test_show_makes_visible(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Hello", NotificationLevel.Info)
        assert toast.isVisible()

    def test_dedup_increments_count(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Same msg", NotificationLevel.Info)
        toast.show_notification("Same msg", NotificationLevel.Info)
        toast.show_notification("Same msg", NotificationLevel.Info)

        assert toast._current_count == 3
        assert "(x3)" in toast._message_label.text()

    def test_different_message_replaces(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("First", NotificationLevel.Info)
        toast.show_notification("Second", NotificationLevel.Warning)

        assert toast._current_count == 1
        assert "Second" in toast._message_label.text()
        assert toast._current_message == "Second"

    def test_dedup_resets_timer(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Msg", NotificationLevel.Info)

        # Simulate some time passing
        initial_remaining = toast._remaining_ms
        toast._tick()
        toast._tick()
        after_ticks = toast._remaining_ms
        assert after_ticks < initial_remaining

        # Dedup should reset the timer
        toast.show_notification("Msg", NotificationLevel.Info)
        assert toast._remaining_ms == toast._duration_ms

    def test_click_dismisses(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Click me", NotificationLevel.Info)
        assert toast.isVisible()

        # Simulate the dismiss (can't easily click during animation)
        toast.dismiss()
        # After animation finishes the toast hides
        qtbot.waitUntil(lambda: not toast.isVisible(), timeout=1000)

    def test_level_property_set(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Info", NotificationLevel.Info)
        assert toast.property("level") == "info"

        toast.show_notification("Warn", NotificationLevel.Warning)
        assert toast.property("level") == "warning"

    def test_centered_on_parent(self, qtbot):
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        qtbot.addWidget(parent)

        toast = NotificationToast(parent)
        toast.show_notification("Center", NotificationLevel.Info)

        # Wait for animation to finish
        qtbot.waitUntil(
            lambda: not toast._anim.state(), timeout=1000
        )

        # Trigger a reposition to sync with final widget size
        toast._reposition()

        expected_x = (parent.width() - toast.width()) // 2
        assert abs(toast.x() - expected_x) <= 1
