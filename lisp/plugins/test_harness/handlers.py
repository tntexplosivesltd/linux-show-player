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
        return list(app.cue_factory._CueFactory__registry.keys())

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

        def do_save():
            app._Application__save_to_file(path)

        invoke_on_main_thread(do_save)
        return {"ok": True}

    def handle_session_load(params):
        path = params.get("path")
        if not path:
            raise AppError("path is required")

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

    def handle_layout_selection_mode(params):
        """Get or set selection mode."""
        _require_session()
        enable = params.get("enable")
        if enable is not None:
            invoke_on_main_thread(
                lambda: app.layout._set_selection_mode(enable)
            )
        return {"selection_mode": app.layout.selection_mode}

    def handle_layout_select_cues(params):
        """Select cues by index list. Enables selection mode first."""
        _require_session()
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
        # Layout
        "layout.go": handle_layout_go,
        "layout.cues": handle_layout_cues,
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
    }

    for method_name, handler in methods.items():
        dispatcher.register(method_name, handler)
