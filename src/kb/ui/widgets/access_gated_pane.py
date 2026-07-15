"""Shared access-state handling for CalendarPane/RemindersPane.

Both panes need identical handling of the three non-GRANTED AccessStates:

- NOT_DETERMINED: permission has never been asked for. The pane must actively
  call request_access() to give the user a path to grant it — collapsing this
  into the same "not granted" message as DENIED, with no call to
  request_access() anywhere, leaves a never-asked user stuck forever.
- DENIED/RESTRICTED: permission was actively refused (or is restricted by e.g.
  parental controls). macOS will not re-prompt once denied, so calling
  request_access() again is pointless — the only remedy is System Settings,
  so the message says so.
- GRANTED: fetch and render the real content.

All three access_state()/request_access() calls, plus the eventual data fetch,
run in a @work(thread=True) worker rather than synchronously in compose():
request_access() blocks on a threading.Event waiting for the user to respond
to a system permission dialog (see eventkit_services.py), and doing that on
the main thread would freeze the whole Textual UI while the dialog is up.

compose() itself only ever renders whatever `_render_state` currently says —
it never touches the service. Widgets update via the `recompose=True` reactive
once the worker writes the result back through `call_from_thread`, since
thread workers cannot touch the UI/reactive state directly — see
https://textual.textualize.io/guide/workers/#thread-workers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label

from kb.platform.models import AccessState


class _AccessControlledService(Protocol):
    def access_state(self) -> AccessState: ...

    def request_access(self) -> AccessState: ...


@dataclass(frozen=True)
class _RenderState:
    """What compose() should show right now.

    `kind` is one of "checking", "requesting", "denied", "granted". `content`
    is only meaningful for "granted" — it's whatever `_fetch_content()`
    returned, opaque to this base class.
    """

    kind: str
    content: object = None


_CHECKING = _RenderState(kind="checking")


class AccessGatedPane(VerticalScroll):
    """Base for panes backed by a service gated behind an AccessState.

    Subclasses set `resource_name` (e.g. "Calendar", "Reminders" — used in
    both the transient and denied messages) and implement `_fetch_content()`
    (called only once access is confirmed GRANTED, in the worker thread) and
    `_render_content()` (turns that content into widgets, called from
    compose() on the main thread).
    """

    # j/k mirror the up/down arrow keys VerticalScroll already binds to
    # scroll_up/scroll_down — see ActionItemsPane for the ActionItemsPane's copy
    # of this same pair. A shared DOMNode-based mixin was tried and reverted:
    # DOMNode._css_bases() walks only the first DOMNode base at each MRO level,
    # so putting a mixin ahead of VerticalScroll in the base list silently drops
    # VerticalScroll's DEFAULT_CSS (including overflow-y: auto), breaking
    # scrolling entirely. Two duplicated lines are cheaper than that landmine.
    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
    ]

    resource_name = ""

    _render_state: _RenderState = reactive(_CHECKING, recompose=True)

    def __init__(self, service: _AccessControlledService, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._service = service

    def on_mount(self) -> None:
        self._resolve_access()

    @work(thread=True)
    def _resolve_access(self) -> None:
        state = self._service.access_state()

        if state is AccessState.NOT_DETERMINED:
            self.app.call_from_thread(
                self._set_render_state, _RenderState(kind="requesting")
            )
            state = self._service.request_access()

        if state is AccessState.GRANTED:
            render_state = _RenderState(kind="granted", content=self._fetch_content())
        else:
            render_state = _RenderState(kind="denied")

        self.app.call_from_thread(self._set_render_state, render_state)

    def _set_render_state(self, render_state: _RenderState) -> None:
        self._render_state = render_state

    def compose(self) -> ComposeResult:
        state = self._render_state

        if state.kind == "checking":
            yield Label(
                f"Checking {self.resource_name} access…",
                classes="access-checking",
                markup=False,
            )
            return

        if state.kind == "requesting":
            yield Label(
                f"Requesting {self.resource_name} access…",
                classes="access-requesting",
                markup=False,
            )
            return

        if state.kind == "denied":
            yield Label(
                f"{self.resource_name} access denied — grant it in "
                f"System Settings > Privacy & Security > {self.resource_name}.",
                classes="access-denied",
                markup=False,
            )
            return

        yield from self._render_granted_content(state.content)

    def _fetch_content(self) -> object:
        """Called in the worker thread once access_state() is GRANTED."""
        raise NotImplementedError

    def _render_granted_content(self, content: object) -> ComposeResult:
        """Called from compose() on the main thread with _fetch_content()'s result.

        Named _render_granted_content rather than _render_content: Widget
        already defines a private `_render_content()` for its own internal
        render-cache bookkeeping, and overriding it by accident breaks
        rendering with a confusing "missing argument" TypeError deep inside
        Textual's compositor.
        """
        raise NotImplementedError
