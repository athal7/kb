"""Command registry for the `:` command bar.

Each Command's handler receives the live Dashboard app instance and whatever
whitespace-split tokens followed the command name/alias — argument validation
(e.g. `:goto` requiring exactly one name) is the handler's job, not resolve()'s,
since what counts as valid arguments is command-specific.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kb.core.models import EntityKind, ResolutionStatus

if TYPE_CHECKING:
    from kb.ui.app import Dashboard


@dataclass(frozen=True)
class Command:
    name: str
    handler: Callable[[Dashboard, list[str]], None]
    aliases: tuple[str, ...] = ()


def _quit(dashboard: Dashboard, args: list[str]) -> None:
    # action_quit is inherited from App and is a coroutine function — calling
    # it directly would create an unawaited coroutine and silently no-op.
    # call_later schedules it through Textual's callback machinery, which
    # awaits coroutine callbacks properly.
    dashboard.call_later(dashboard.action_quit)


def _refresh(dashboard: Dashboard, args: list[str]) -> None:
    dashboard.action_refresh()


def _help(dashboard: Dashboard, args: list[str]) -> None:
    dashboard.action_help()


_GOTO_KINDS = (EntityKind.PERSON, EntityKind.PROJECT, EntityKind.PRODUCT)
_SUGGESTION_LIMIT = 5


def _display_of(entity) -> str:
    return sorted(entity.titles)[0] if entity.titles else entity.canonical


def _goto(dashboard: Dashboard, args: list[str]) -> None:
    if len(args) != 1:
        dashboard.notify("Usage: :goto <name>", severity="warning")
        return

    name = args[0]
    for kind in _GOTO_KINDS:
        resolution = dashboard.index.resolve_wikilink(name, kind)
        if resolution.status is ResolutionStatus.RESOLVED and resolution.entity is not None:
            dashboard.notify(f"Found: {_display_of(resolution.entity)}", severity="information")
            return

    # Exact/alias resolution missed — fall back to typo/partial-tolerant search.
    matches = dashboard.index.fuzzy_matches(name, _GOTO_KINDS)
    if not matches:
        dashboard.notify(
            f"No such person, project, or product: {name}", severity="warning"
        )
        return
    if len(matches) == 1:
        dashboard.notify(f"Found: {_display_of(matches[0])}", severity="information")
        return

    names = ", ".join(_display_of(m) for m in matches[:_SUGGESTION_LIMIT])
    dashboard.notify(f"Did you mean: {names}", severity="information")


COMMANDS: list[Command] = [
    Command(name="quit", handler=_quit, aliases=("q",)),
    Command(name="refresh", handler=_refresh, aliases=("r",)),
    Command(name="help", handler=_help, aliases=("h",)),
    Command(name="goto", handler=_goto),
]


def resolve(text: str) -> tuple[Command | None, list[str]]:
    """Split `text` on whitespace and match the first token against COMMANDS.

    Returns (matched_command_or_None, remaining_args). The caller is
    responsible for reporting an unknown command — resolve() only reports
    what it found.
    """
    tokens = text.split()
    if not tokens:
        return None, []

    token, *args = tokens
    for command in COMMANDS:
        if token == command.name or token in command.aliases:
            return command, args
    return None, args
