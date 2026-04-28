# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
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

import time

from lisp import layout as layout_module
from lisp.command.cue import UpdateCueCommand
from lisp.command.model import (
    ModelAddItemsCommand,
    ModelMoveItemsCommand,
    ModelRemoveItemsCommand,
)
from lisp.cues.cue import CueAction
from lisp.plugins.test_harness.dispatcher import AppError
from lisp.plugins.test_harness.qt_invoke import invoke_on_main_thread
from lisp.plugins.test_harness.serializers import (
    serialize_cue,
    serialize_cue_brief,
    state_name,
)


def register_all(dispatcher, app, signal_manager):
    """Register all JSON-RPC method handlers."""

    def _require_session():
        if app.session is None:
            raise AppError("No active session")

    def _get_cue(cue_id):
        cue = app.cue_model.get(cue_id)
        if cue is None:
            raise AppError(f"Cue not found: {cue_id}")
        return cue

    # --- Utility ---

    def handle_ping(params):
        return {"pong": True, "timestamp": time.time()}

    def handle_cue_types(params):
        return app.cue_factory.registered_types()

    # --- Session ---

    def handle_session_info(params):
        if app.session is None:
            return {"has_session": False}
        return {
            "has_session": True,
            "session_file": getattr(app.session, "session_file", None),
            "layout_type": app.layout.__class__.__name__,
        }

    def handle_session_new(params):
        layout_type = params.get("layout_type")
        if not layout_type:
            raise AppError("layout_type is required")

        try:
            layout_class = layout_module.get_layout(layout_type)
        except KeyError:
            raise AppError(f"Unknown layout type: {layout_type}")

        def do_new():
            app._Application__new_session(layout_class)

        invoke_on_main_thread(do_new)
        return {"ok": True}

    def handle_session_save(params):
        _require_session()
        path = params.get("path")
        if not path:
            raise AppError("path is required")
        if not path.endswith(".lsp"):
            raise AppError("path must end with .lsp")

        def do_save():
            app._Application__save_to_file(path)

        invoke_on_main_thread(do_save)
        return {"ok": True}

    def handle_session_load(params):
        path = params.get("path")
        if not path:
            raise AppError("path is required")
        if not path.endswith(".lsp"):
            raise AppError("path must end with .lsp")

        def do_load():
            app._Application__load_from_file(path)

        invoke_on_main_thread(do_load)
        return {"ok": True}

    # --- CueModel queries ---

    def handle_cue_list(params):
        type_filter = params.get("type_filter")
        result = []
        for cue in app.cue_model:
            if type_filter and cue._type_ != type_filter:
                continue
            result.append(serialize_cue_brief(cue))
        result.sort(key=lambda c: c["index"])
        return result

    def handle_cue_get(params):
        cue = _get_cue(params.get("id"))
        return serialize_cue(cue)

    def handle_cue_get_property(params):
        cue = _get_cue(params.get("id"))
        prop = params.get("property")
        if not prop:
            raise AppError("property is required")
        if prop not in cue.properties_names():
            raise AppError(f"Unknown property: {prop}")
        return {"value": getattr(cue, prop)}

    def handle_cue_count(params):
        return {"count": len(app.cue_model)}

    def handle_cue_state(params):
        cue = _get_cue(params.get("id"))
        return {
            "state": cue.state,
            "state_name": state_name(cue.state),
            "current_time": cue.current_time(),
            "prewait_time": cue.prewait_time(),
            "postwait_time": cue.postwait_time(),
            "is_fading": cue.is_fading(),
        }

    # --- Cue mutations ---

    def handle_cue_add(params):
        _require_session()
        cue_type = params.get("type")
        if not cue_type:
            raise AppError("type is required")

        properties = params.get("properties", {})

        def do_add():
            cue = app.cue_factory.create_cue(cue_type)
            if properties:
                cue.update_properties(properties)
            app.commands_stack.do(
                ModelAddItemsCommand(app.cue_model, cue)
            )
            return cue.id

        cue_id = invoke_on_main_thread(do_add)
        return {"id": cue_id}

    def handle_cue_remove(params):
        _require_session()
        cue = _get_cue(params.get("id"))

        def do_remove():
            app.commands_stack.do(
                ModelRemoveItemsCommand(app.cue_model, cue)
            )

        invoke_on_main_thread(do_remove)
        return {"ok": True}

    def handle_cue_update(params):
        cue = _get_cue(params.get("id"))
        properties = params.get("properties")
        if not properties:
            raise AppError("properties is required")

        def do_update():
            app.commands_stack.do(UpdateCueCommand(properties, cue))

        invoke_on_main_thread(do_update)
        return {"ok": True}

    def handle_cue_set_property(params):
        cue = _get_cue(params.get("id"))
        prop = params.get("property")
        value = params.get("value")
        if not prop:
            raise AppError("property is required")

        def do_set():
            app.commands_stack.do(
                UpdateCueCommand({prop: value}, cue)
            )

        invoke_on_main_thread(do_set)
        return {"ok": True}

    # --- Cue control ---

    def handle_cue_execute(params):
        cue = _get_cue(params.get("id"))
        action_str = params.get("action", "Default")
        try:
            action = CueAction(action_str)
        except ValueError:
            raise AppError(
                f"Unknown action: {action_str}. "
                f"Available: {[a.value for a in CueAction]}"
            )
        invoke_on_main_thread(lambda: cue.execute(action))
        return {"ok": True}

    def handle_cue_start(params):
        cue = _get_cue(params.get("id"))
        fade = params.get("fade", False)
        invoke_on_main_thread(lambda: cue.start(fade=fade))
        return {"ok": True}

    def handle_cue_stop(params):
        cue = _get_cue(params.get("id"))
        fade = params.get("fade", False)
        invoke_on_main_thread(lambda: cue.stop(fade=fade))
        return {"ok": True}

    def handle_cue_pause(params):
        cue = _get_cue(params.get("id"))
        fade = params.get("fade", False)
        invoke_on_main_thread(lambda: cue.pause(fade=fade))
        return {"ok": True}

    def handle_cue_resume(params):
        cue = _get_cue(params.get("id"))
        fade = params.get("fade", False)
        invoke_on_main_thread(lambda: cue.resume(fade=fade))
        return {"ok": True}

    def handle_cue_interrupt(params):
        cue = _get_cue(params.get("id"))
        fade = params.get("fade", False)
        invoke_on_main_thread(lambda: cue.interrupt(fade=fade))
        return {"ok": True}

    # --- Cue seek ---

    def handle_cue_seek(params):
        """Seek a media cue to a position in milliseconds."""
        cue = _get_cue(params.get("id"))
        position = params.get("position")
        if position is None:
            raise AppError("position is required (milliseconds)")

        if not hasattr(cue, "media"):
            raise AppError(
                f"Cue {cue.id} is not a media cue"
            )

        def do_seek():
            cue.media.seek(int(position))

        invoke_on_main_thread(do_seek)
        return {"ok": True}

    # --- Cue add from URI ---

    def handle_cue_add_from_uri(params):
        """Add media cue(s) from file paths using the backend."""
        _require_session()
        files = params.get("files")
        if not files:
            uri = params.get("uri")
            if uri:
                files = [uri]
            else:
                raise AppError("files or uri is required")

        from lisp.backend import get_backend

        def do_add():
            backend = get_backend()
            if backend is None:
                raise AppError("No backend available")
            backend.add_cue_from_files(files)

        invoke_on_main_thread(do_add)
        return {"ok": True}

    def handle_cue_add_video_from_uri(params):
        """Add video cue(s) from file paths using the backend."""
        _require_session()
        files = params.get("files")
        if not files:
            uri = params.get("uri")
            if uri:
                files = [uri]
            else:
                raise AppError("files or uri is required")

        from lisp.backend import get_backend

        def do_add():
            backend = get_backend()
            if backend is None:
                raise AppError("No backend available")
            if not hasattr(backend, "add_video_cue_from_files"):
                raise AppError(
                    "Backend does not support video cues"
                )
            backend.add_video_cue_from_files(files)

        invoke_on_main_thread(do_add)
        return {"ok": True}

    def handle_cue_add_image_from_uri(params):
        """Add image cue(s) from file paths using the backend."""
        _require_session()
        files = params.get("files")
        if not files:
            uri = params.get("uri")
            if uri:
                files = [uri]
            else:
                raise AppError("files or uri is required")

        duration = params.get("duration", 5000)

        from lisp.backend import get_backend

        def do_add():
            backend = get_backend()
            if backend is None:
                raise AppError("No backend available")
            if not hasattr(backend, "add_image_cue_from_files"):
                raise AppError(
                    "Backend does not support image cues"
                )
            backend.add_image_cue_from_files(
                files, duration=duration
            )

        invoke_on_main_thread(do_add)
        return {"ok": True}

    # --- Layout ---

    def handle_layout_go(params):
        _require_session()
        action_str = params.get("action", "Default")
        advance = params.get("advance", 1)
        try:
            action = CueAction(action_str)
        except ValueError:
            raise AppError(f"Unknown action: {action_str}")

        def do_go():
            app.layout.go(action=action, advance=advance)

        invoke_on_main_thread(do_go)
        return {"ok": True}

    def handle_layout_cues(params):
        _require_session()
        return [serialize_cue_brief(cue) for cue in app.layout.cues()]

    def handle_layout_running_widget_info(params):
        """Return per-running-widget introspection for E2E tests.

        Response shape:
            [{
                "cue_id": str,
                "volume_indicator_visible": bool,
                "volume_indicator_text": str,
            }, ...]

        The list is ordered as the running panel's QListWidget
        iterates. Non-MediaCue running widgets report
        ``volume_indicator_visible=False`` and empty text — they do
        not have the indicator at all.
        """
        _require_session()
        run_view = app.layout.view.runView

        results = []

        def collect():
            for n in range(run_view.count()):
                item = run_view.item(n)
                widget = run_view.itemWidget(item)
                if widget is None:
                    continue
                cue = getattr(widget, "cue", None)
                cue_id = cue.id if cue is not None else ""
                indicator = getattr(widget, "volumeIndicator", None)
                if indicator is None:
                    results.append({
                        "cue_id": cue_id,
                        "volume_indicator_visible": False,
                        "volume_indicator_text": "",
                    })
                else:
                    results.append({
                        "cue_id": cue_id,
                        "volume_indicator_visible": (
                            indicator.isVisible()
                        ),
                        "volume_indicator_text": indicator.text(),
                    })

        invoke_on_main_thread(collect)
        return results

    def handle_layout_set_property(params):
        """Set a named ProxyProperty on the current layout.

        Used by E2E tests to flip visibility toggles declaratively.
        """
        _require_session()
        name = params.get("name")
        if not name:
            raise AppError("name is required")
        value = params.get("value")

        def do_set():
            setattr(app.layout, name, value)

        invoke_on_main_thread(do_set)
        return {"ok": True}

    def handle_cue_get_element_property(params):
        """Read a media-element property (e.g. Volume.live_volume).

        Params:
            id (str): cue id
            element (str): element name (e.g. "Volume")
            property (str): element property (e.g. "live_volume")
        """
        _require_session()
        cue_id = params.get("id")
        element_name = params.get("element")
        prop = params.get("property")
        if not (cue_id and element_name and prop):
            raise AppError(
                "id, element, property are all required"
            )

        cue = app.cue_model.get(cue_id)
        if cue is None:
            raise AppError(f"No cue with id {cue_id}")
        media = getattr(cue, "media", None)
        if media is None:
            raise AppError(f"Cue {cue_id} has no media")
        element = media.element(element_name)
        if element is None:
            raise AppError(
                f"Cue {cue_id} has no {element_name} element"
            )
        return {"value": getattr(element, prop)}

    def handle_layout_cue_at(params):
        _require_session()
        index = params.get("index")
        if index is None:
            raise AppError("index is required")
        try:
            cue = app.layout.cue_at(index)
        except IndexError:
            raise AppError(f"No cue at index {index}")
        return serialize_cue_brief(cue)

    def handle_layout_standby(params):
        _require_session()
        cue = app.layout.standby_cue()
        if cue is None:
            return None
        return {
            **serialize_cue_brief(cue),
            "standby_index": app.layout.standby_index(),
        }

    def handle_layout_set_standby_index(params):
        _require_session()
        index = params.get("index")
        if index is None:
            raise AppError("index is required")

        def do_set():
            app.layout.set_standby_index(index)

        invoke_on_main_thread(do_set)
        return {"ok": True}

    def handle_layout_selected_cues(params):
        _require_session()
        return [serialize_cue_brief(cue) for cue in app.layout.selected_cues()]

    def _require_list_layout():
        from lisp.plugins.list_layout.layout import ListLayout
        if not isinstance(app.layout, ListLayout):
            raise AppError(
                "This operation requires ListLayout"
            )

    def handle_layout_selection_mode(params):
        """Get or set selection mode."""
        _require_session()
        _require_list_layout()
        enable = params.get("enable")
        if enable is not None:
            invoke_on_main_thread(
                lambda: app.layout._set_selection_mode(enable)
            )
        return {"selection_mode": app.layout.selection_mode}

    def handle_layout_select_cues(params):
        """Select cues by index list. Enables selection mode first."""
        _require_session()
        _require_list_layout()
        indices = params.get("indices", [])

        def do_select():
            app.layout._set_selection_mode(True)
            app.layout.deselect_all()
            view = app.layout._view.listView
            for idx in indices:
                if 0 <= idx < view.topLevelItemCount():
                    view.topLevelItem(idx).setSelected(True)

        invoke_on_main_thread(do_select)
        return {"ok": True}

    def handle_layout_move_cue(params):
        """Move a cue from one index to another."""
        _require_session()
        from_index = params.get("from_index")
        to_index = params.get("to_index")
        if from_index is None or to_index is None:
            raise AppError("from_index and to_index are required")

        def do_move():
            app.commands_stack.do(
                ModelMoveItemsCommand(
                    app.layout.model, [from_index], to_index
                )
            )

        invoke_on_main_thread(do_move)
        return {"ok": True}

    def handle_layout_context_action(params):
        """Trigger a context menu action by name on cues.

        Simulates right-click > action on the given cues.
        Requires selection mode to select multiple cues.
        """
        _require_session()
        action_name = params.get("action")
        cue_ids = params.get("cue_ids", [])
        if not action_name:
            raise AppError("action is required")
        if not cue_ids:
            raise AppError("cue_ids is required")

        cues = [_get_cue(cid) for cid in cue_ids]

        def do_action():
            # Search context menu actions for matching name
            from lisp.core.util import greatest_common_superclass

            ref_class = greatest_common_superclass(cues)
            for action in app.layout.CuesMenu.filter(ref_class):
                from lisp.layout.cue_menu import MenuActionsGroup

                if isinstance(action, MenuActionsGroup):
                    for sub in action.actions:
                        text = sub.text(cues)
                        if text and text == action_name:
                            sub.action(cues)
                            return
                else:
                    text = action.text(cues)
                    if text and text == action_name:
                        action.action(cues)
                        return

            raise AppError(
                f"Context action not found: {action_name}"
            )

        invoke_on_main_thread(do_action)
        return {"ok": True}

    def handle_layout_stop_all(params):
        _require_session()
        invoke_on_main_thread(app.layout.stop_all)
        return {"ok": True}

    def handle_layout_pause_all(params):
        _require_session()
        invoke_on_main_thread(app.layout.pause_all)
        return {"ok": True}

    def handle_layout_resume_all(params):
        _require_session()
        invoke_on_main_thread(app.layout.resume_all)
        return {"ok": True}

    def handle_layout_interrupt_all(params):
        _require_session()
        invoke_on_main_thread(app.layout.interrupt_all)
        return {"ok": True}

    def handle_layout_execute_all(params):
        _require_session()
        action_str = params.get("action")
        if not action_str:
            raise AppError("action is required")
        try:
            action = CueAction(action_str)
        except ValueError:
            raise AppError(f"Unknown action: {action_str}")
        invoke_on_main_thread(
            lambda: app.layout.execute_all(action)
        )
        return {"ok": True}

    def _require_cart_layout():
        from lisp.plugins.cart_layout.layout import CartLayout
        if not isinstance(app.layout, CartLayout):
            raise AppError(
                "This operation requires CartLayout"
            )

    def handle_cart_click_cue(params):
        """Synthesize a click on a cart cell with optional modifiers.

        Drives the same code path the Qt mouse-release handler does
        (`QClickLabel.clicked` → `CueWidget._clicked`), so this
        exercises the modifier-dispatch logic end-to-end without
        needing the window to be visible to the windowing system.

        The synthetic event uses position ``(0, 0)`` — the cell's
        top-left, which is always outside the seek slider's
        geometry. That deliberately bypasses `_clicked`'s seek-slider
        early-out so the modifier branches always run; this handler
        is not the right tool for testing seek-slider gestures.

        Params:
          ``cue_id`` (str, optional): cell identified by the cue it holds.
          ``index`` (int, optional): cell identified by its model index.
            Either ``cue_id`` or ``index`` is required.
          ``modifier`` (str, optional): one of ``"none"``, ``"shift"``,
            ``"ctrl"``. Default ``"none"``.
        """
        _require_session()
        _require_cart_layout()

        cue_id = params.get("cue_id")
        index = params.get("index")
        if cue_id is None and index is None:
            raise AppError("cue_id or index is required")

        modifier_name = (params.get("modifier") or "none").lower()

        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QMouseEvent

        modifier_map = {
            "none": Qt.NoModifier,
            "shift": Qt.ShiftModifier,
            "ctrl": Qt.ControlModifier,
            "control": Qt.ControlModifier,
        }
        if modifier_name not in modifier_map:
            raise AppError(
                f"Unknown modifier: {modifier_name}"
            )
        modifier = modifier_map[modifier_name]

        def do_click():
            if cue_id is not None:
                target_cue = _get_cue(cue_id)
            else:
                target_cue = app.layout.cue_at(index)
                if target_cue is None:
                    raise AppError(f"No cue at index {index}")

            target_widget = None
            for page in app.layout.view.pages():
                for widget in page.widgets():
                    if widget.cue is target_cue:
                        target_widget = widget
                        break
                if target_widget is not None:
                    break
            if target_widget is None:
                raise AppError(
                    "No cart widget hosts the requested cue"
                )

            event = QMouseEvent(
                QEvent.MouseButtonRelease,
                QPoint(0, 0),
                Qt.LeftButton,
                Qt.LeftButton,
                modifier,
            )
            target_widget.nameButton.clicked.emit(event)

        invoke_on_main_thread(do_click)
        return {"ok": True}

    # --- Commands ---

    def handle_commands_undo(params):
        def do_undo():
            app.commands_stack.undo_last()

        invoke_on_main_thread(do_undo)
        return {"ok": True}

    def handle_commands_redo(params):
        def do_redo():
            app.commands_stack.redo_last()

        invoke_on_main_thread(do_redo)
        return {"ok": True}

    def handle_commands_is_saved(params):
        return {"saved": app.commands_stack.is_saved()}

    def handle_commands_clear(params):
        def do_clear():
            app.commands_stack.clear()

        invoke_on_main_thread(do_clear)
        return {"ok": True}

    # --- Signals ---

    def handle_signals_subscribe(params):
        signal_path = params.get("signal")
        if not signal_path:
            raise AppError("signal is required")
        cue_id = params.get("cue_id")

        try:
            sub_id = signal_manager.subscribe(signal_path, cue_id=cue_id)
        except ValueError as e:
            raise AppError(str(e))

        return {"subscription_id": sub_id}

    def handle_signals_unsubscribe(params):
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AppError("subscription_id is required")

        try:
            signal_manager.unsubscribe(sub_id)
        except ValueError as e:
            raise AppError(str(e))

        return {"ok": True}

    def handle_signals_unsubscribe_all(params):
        signal_manager.unsubscribe_all()
        return {"ok": True}

    def handle_signals_poll(params):
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AppError("subscription_id is required")
        clear = params.get("clear", True)

        try:
            events = signal_manager.poll(sub_id, clear=clear)
        except ValueError as e:
            raise AppError(str(e))

        return {"events": events}

    def handle_signals_wait_for(params):
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AppError("subscription_id is required")
        timeout = params.get("timeout", 10.0)
        match = params.get("match")

        try:
            event = signal_manager.wait_for(
                sub_id, timeout=timeout, match=match
            )
        except ValueError as e:
            raise AppError(str(e))
        # TimeoutError is caught by the dispatcher

        return {"event": event}

    def handle_signals_list(params):
        return signal_manager.list_signals()

    # --- Plugins ---

    def handle_plugin_list(params):
        from lisp.plugins import get_plugins

        result = []
        for name, plugin in get_plugins():
            result.append({
                "name": name,
                "loaded": plugin.is_loaded(),
                "enabled": plugin.is_enabled(),
            })
        return result

    def handle_plugin_is_loaded(params):
        name = params.get("name")
        if not name:
            raise AppError("name is required")

        from lisp.plugins import is_loaded

        return {"loaded": is_loaded(name)}

    # --- Video window ---

    def handle_video_window_state(params):
        """Query the video output window state."""
        from lisp.plugins.gst_backend.gst_backend import GstBackend

        window = GstBackend.video_window()
        if window is None:
            return {"exists": False}

        return {
            "exists": True,
            "visible": window.isVisible(),
            "fullscreen": window.isFullScreen(),
            "handle": window.window_handle(),
            "render_visible": window._render_widget.isVisible()
            if window._render_widget is not None
            else False,
        }

    # --- Playback monitor ---

    def handle_playback_monitor_state(params):
        """Query the playback monitor window state."""
        from lisp.plugins import get_plugin

        try:
            plugin = get_plugin("PlaybackMonitor")
        except Exception:
            return {"loaded": False}

        window = plugin._window
        if window is None:
            return {
                "loaded": True,
                "visible": False,
            }

        cue = window._tracked_cue
        return {
            "loaded": True,
            "visible": window.isVisible(),
            "cue_name": window._name_label.text(),
            "elapsed": window.elapsed_text,
            "remaining": window.remaining_text,
            "tracked_cue_id": cue.id if cue else None,
        }

    def handle_playback_monitor_toggle(params):
        """Toggle the playback monitor window."""
        from lisp.plugins import get_plugin

        try:
            plugin = get_plugin("PlaybackMonitor")
        except Exception:
            return {"error": "PlaybackMonitor not loaded"}
        plugin._toggle_window()
        window = plugin._window
        return {
            "visible": (
                window.isVisible() if window else False
            ),
        }

    # --- Inspector ---
    #
    # Driving the inspector through Qt requires marshaling onto the
    # main thread for any read that touches widget state, because the
    # populate-and-bind path runs through QTimer.singleShot — even
    # "look up the current page name" can race against an in-flight
    # rebuild kicked off by a selection change.

    def _inspector():
        return app.window.inspectorPanel

    def _mixed_indicator_active(widget):
        """True when ``widget`` is currently displaying the "—" dash.

        Mirrors the conventions in lisp.ui.inspector.mixed_values:
        each widget class has its own "no single value" rendering.
        """
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import (
            QAbstractSpinBox,
            QCheckBox,
            QComboBox,
            QLineEdit,
        )
        from lisp.ui.inspector.mixed_values import MIXED_PLACEHOLDER

        if isinstance(widget, QLineEdit):
            return widget.placeholderText() == MIXED_PLACEHOLDER
        if isinstance(widget, QCheckBox):
            return widget.checkState() == Qt.PartiallyChecked
        if isinstance(widget, QAbstractSpinBox):
            return widget.specialValueText() == MIXED_PLACEHOLDER
        if isinstance(widget, QComboBox):
            return widget.currentIndex() == -1
        return False

    def handle_inspector_state(params):
        """Snapshot of the inspector pane: visibility, bound cues, tabs."""
        def _read():
            panel = _inspector()
            tabs = panel._tabs
            current_idx = tabs.currentIndex()
            current_name = (
                tabs.tabText(current_idx) if current_idx >= 0 else None
            )
            return {
                "visible": panel.isVisible(),
                "cue_ids": panel.active_cue_ids(),
                "page_names": panel.page_names(),
                "current_page": current_name,
                "tab_count": tabs.count(),
            }

        return invoke_on_main_thread(_read)

    def handle_inspector_toggle(params):
        """Show or hide the inspector pane via the View action."""
        action = app.window.showInspectorAction

        def _do():
            target = params.get("visible")
            if target is None:
                action.trigger()
            else:
                # setChecked alone doesn't fire the toggled handler
                # when the state already matches — use trigger to
                # mirror what the menu item does.
                if bool(target) != action.isChecked():
                    action.trigger()
            return _inspector().isVisible()

        visible = invoke_on_main_thread(_do)
        return {"visible": visible}

    def handle_inspector_bind(params):
        """Force the inspector to a specific cue selection."""
        cue_ids = params.get("cue_ids")
        if cue_ids is None:
            raise AppError("cue_ids is required")

        cues = [_get_cue(cid) for cid in cue_ids]

        def _do():
            _inspector().bind(cues)
            return _inspector().active_cue_ids()

        return {"cue_ids": invoke_on_main_thread(_do)}

    def handle_inspector_flush(params):
        """Commit any pending inspector edits."""
        invoke_on_main_thread(_inspector().flush)
        return {"ok": True}

    def handle_inspector_set_active_page(params):
        """Switch the visible inspector tab by translated name."""
        page_name = params.get("page_name")
        if not page_name:
            raise AppError("page_name is required")

        def _do():
            panel = _inspector()
            tabs = panel._tabs
            for i in range(tabs.count()):
                if tabs.tabText(i) == page_name:
                    tabs.setCurrentIndex(i)
                    return True
            return False

        ok = invoke_on_main_thread(_do)
        if not ok:
            raise AppError(f"Inspector page not found: {page_name}")
        return {"ok": True}

    def handle_inspector_set_field(params):
        """Drive a widget on a specific inspector page.

        The widget's normal change/focus pathway is responsible for
        flushing — but harness callers usually want their edit
        committed immediately, so we follow up with an explicit
        flush before returning.
        """
        page_name = params.get("page_name")
        object_name = params.get("object_name")
        if not page_name or not object_name:
            raise AppError(
                "page_name and object_name are required"
            )
        if "value" not in params:
            raise AppError("value is required")
        value = params["value"]

        def _do():
            panel = _inspector()
            ok = panel.set_field_value(page_name, object_name, value)
            if ok:
                panel.flush()
            return ok

        ok = invoke_on_main_thread(_do)
        if not ok:
            raise AppError(
                f"Field not found: {page_name}/{object_name}"
            )
        return {"ok": True}

    def handle_inspector_set_group_enabled(params):
        """Toggle a multi-edit group's "apply to all" checkbox.

        No-op for single-cue selections (groups aren't checkable then).
        """
        page_name = params.get("page_name")
        group_name = params.get("group_name")
        if not page_name or not group_name:
            raise AppError(
                "page_name and group_name are required"
            )
        if "enabled" not in params:
            raise AppError("enabled is required")
        enabled = bool(params["enabled"])

        def _do():
            return _inspector().set_group_enabled(
                page_name, group_name, enabled
            )

        ok = invoke_on_main_thread(_do)
        if not ok:
            raise AppError(
                f"Group not found or not checkable: "
                f"{page_name}/{group_name}"
            )
        return {"ok": True}

    def handle_inspector_get_field(params):
        """Read a widget's current displayed value + mixed-state flag."""
        from lisp.ui.inspector.panel import _widget_value

        page_name = params.get("page_name")
        object_name = params.get("object_name")
        if not page_name or not object_name:
            raise AppError(
                "page_name and object_name are required"
            )

        def _do():
            widget = _inspector().find_field(page_name, object_name)
            if widget is None:
                return None
            return {
                "value": _widget_value(widget),
                "mixed": _mixed_indicator_active(widget),
                "class": type(widget).__name__,
            }

        result = invoke_on_main_thread(_do)
        if result is None:
            raise AppError(
                f"Field not found: {page_name}/{object_name}"
            )
        return result

    # --- Settings ---

    def handle_settings_list_cue_pages(params):
        """List cue-settings pages registered for a cue type, in the
        canonical dialog order (SortOrder, translated Name).

        Pure read from CueSettingsRegistry — registry mutations happen
        only during plugin init, so the GIL is sufficient; no need to
        marshal to the Qt main thread.
        """
        from lisp.ui.settings.cue_settings import (
            CueSettingsRegistry,
            cue_page_sort_key,
        )
        from lisp.ui.ui_utils import translate

        cue_type = params.get("cue_type")
        if not cue_type:
            raise AppError("cue_type is required")

        registry = CueSettingsRegistry()
        # Resolve via the CueFactory: it stores every cue class keyed
        # by type-name (the class itself is the factory callable in
        # practice), so this is O(1) and doesn't require instantiating
        # anything off the main thread.
        factory_registry = app.cue_factory._CueFactory__registry
        cue_class = factory_registry.get(cue_type)
        if cue_class is None:
            # Fall back to ref_classes for base types (e.g. "Cue",
            # "MediaCue") that are not leaf factory entries.
            for ref_class in registry.ref_classes():
                if ref_class.__name__ == cue_type:
                    cue_class = ref_class
                    break
        if cue_class is None:
            raise AppError(f"Unknown cue type: {cue_type}")

        pages = sorted(registry.filter(cue_class), key=cue_page_sort_key)
        return [
            {
                "class": page.__name__,
                "name": translate("SettingsPageName", page.Name),
                "raw_name": page.Name,
                "sort_order": getattr(page, "SortOrder", 1000),
            }
            for page in pages
        ]

    # --- Register all methods ---

    methods = {
        "ping": handle_ping,
        "app.cue_types": handle_cue_types,
        # Session
        "session.info": handle_session_info,
        "session.new": handle_session_new,
        "session.save": handle_session_save,
        "session.load": handle_session_load,
        # Cue queries
        "cue.list": handle_cue_list,
        "cue.get": handle_cue_get,
        "cue.get_property": handle_cue_get_property,
        "cue.count": handle_cue_count,
        "cue.state": handle_cue_state,
        # Cue mutations
        "cue.add": handle_cue_add,
        "cue.remove": handle_cue_remove,
        "cue.update": handle_cue_update,
        "cue.set_property": handle_cue_set_property,
        # Cue control
        "cue.execute": handle_cue_execute,
        "cue.start": handle_cue_start,
        "cue.stop": handle_cue_stop,
        "cue.pause": handle_cue_pause,
        "cue.resume": handle_cue_resume,
        "cue.interrupt": handle_cue_interrupt,
        "cue.seek": handle_cue_seek,
        "cue.add_from_uri": handle_cue_add_from_uri,
        "cue.add_video_from_uri": handle_cue_add_video_from_uri,
        "cue.add_image_from_uri": handle_cue_add_image_from_uri,
        "cue.get_element_property": handle_cue_get_element_property,
        # Layout
        "layout.go": handle_layout_go,
        "layout.cues": handle_layout_cues,
        "layout.running_widget_info": handle_layout_running_widget_info,
        "layout.set_property": handle_layout_set_property,
        "layout.cue_at": handle_layout_cue_at,
        "layout.standby": handle_layout_standby,
        "layout.set_standby_index": handle_layout_set_standby_index,
        "layout.selected_cues": handle_layout_selected_cues,
        "layout.selection_mode": handle_layout_selection_mode,
        "layout.select_cues": handle_layout_select_cues,
        "layout.move_cue": handle_layout_move_cue,
        "layout.context_action": handle_layout_context_action,
        "layout.stop_all": handle_layout_stop_all,
        "layout.pause_all": handle_layout_pause_all,
        "layout.resume_all": handle_layout_resume_all,
        "layout.interrupt_all": handle_layout_interrupt_all,
        "layout.execute_all": handle_layout_execute_all,
        # Cart layout
        "cart.click_cue": handle_cart_click_cue,
        # Commands
        "commands.undo": handle_commands_undo,
        "commands.redo": handle_commands_redo,
        "commands.is_saved": handle_commands_is_saved,
        "commands.clear": handle_commands_clear,
        # Signals
        "signals.subscribe": handle_signals_subscribe,
        "signals.unsubscribe": handle_signals_unsubscribe,
        "signals.unsubscribe_all": handle_signals_unsubscribe_all,
        "signals.poll": handle_signals_poll,
        "signals.wait_for": handle_signals_wait_for,
        "signals.list": handle_signals_list,
        # Plugins
        "plugin.list": handle_plugin_list,
        "plugin.is_loaded": handle_plugin_is_loaded,
        # Video window
        "video_window.state": handle_video_window_state,
        # Playback monitor
        "playback_monitor.state": handle_playback_monitor_state,
        "playback_monitor.toggle": handle_playback_monitor_toggle,
        # Settings
        "settings.list_cue_pages": handle_settings_list_cue_pages,
        # Inspector
        "inspector.state": handle_inspector_state,
        "inspector.toggle": handle_inspector_toggle,
        "inspector.bind": handle_inspector_bind,
        "inspector.flush": handle_inspector_flush,
        "inspector.set_active_page": handle_inspector_set_active_page,
        "inspector.set_field": handle_inspector_set_field,
        "inspector.set_group_enabled": handle_inspector_set_group_enabled,
        "inspector.get_field": handle_inspector_get_field,
    }

    for method_name, handler in methods.items():
        dispatcher.register(method_name, handler)
