"""Program launch controller for Mouser.

The mouse hook invokes actions from a non-toolkit thread.  This module exposes
a controller whose public request method *only* emits a queued signal: the
actual process start then happens on the GUI thread, so the hook thread never
blocks while an application boots.

Unlike the screenshot controllers this one has no per-platform variants -- the
platform differences all live inside :func:`core.program_launcher.build_launch_argv`.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal, Slot

from core.program_launcher import launch_target, launch_target_id


class ProgramLaunchController(QObject):
    """Turns a hook-thread launch request into a GUI-thread process start."""

    # Private, camelCase signal -- same convention as the screenshot controller.
    _requestAction = Signal(str)

    def __init__(
        self,
        status_callback: Optional[Callable[[str], None]] = None,
        target_provider: Optional[Callable[[str], Optional[dict]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._status_callback = status_callback
        self._target_provider = target_provider
        # Queued delivery is load-bearing: with the default (direct) connection
        # the launch would run on the mouse-hook thread and stall the pointer.
        self._requestAction.connect(
            self._handle_request, Qt.ConnectionType.QueuedConnection)

    def request_action(self, action_id: str) -> None:
        """Hook-thread entry point -- emits only, never starts anything inline."""
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        """Runs on the GUI thread: resolve the target and start it."""
        target_id = launch_target_id(action_id)
        if not target_id:
            return

        if self._target_provider is None:
            self._emit_status("Launch target unavailable")
            return

        target = self._target_provider(target_id)
        if not target:
            self._emit_status("Launch target is missing; reassign this button")
            return

        ok, message = launch_target(target)
        if ok:
            self._emit_status(f"Launched {message}" if message else "Launched")
        else:
            self._emit_status(f"Launch failed: {message}")

    def _emit_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)
