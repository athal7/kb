"""kb-tui entry point.

Wires the pure-Python VaultIndex, the real EventKit-backed services, config,
and plugin discovery into a pane registry, then hands that registry to the
Dashboard app. The app only ever depends on `PaneSpec`s in a registry dict —
never on EventKit, the plugin loader, or config parsing — so this is the one
place that knows which concrete calendar/reminders backend is in play and
which plugins/layout the user has configured. Swapping the real EventKit
services for fakes (e.g. for UI development without a TCC prompt) is a
one-line change here, not a UI rewrite.

Config (`~/.config/kb/config.toml`) is read once, here, at startup — not
re-read on every Dashboard.action_refresh. A refresh re-scans the vault and
rebuilds the pane registry from the *same* enabled plugins/services/layout, so
a config edit takes effect on the next launch, not the next refresh keypress.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from kb.config import resolve_kb_root
from kb.core.actionitems import ActionItem, load_action_items
from kb.core.index import VaultIndex
from kb.core.models import Person
from kb.platform.eventkit_services import EventKitCalendarService, EventKitRemindersService
from kb.plugin_config import default_config_path, load_config
from kb.plugin_loader import build_pane_registry, discover_plugins
from kb.plugins import PaneSpec, PluginContext
from kb.ui.app import Dashboard


def build_app() -> Dashboard:
    """Resolve KB_ROOT, scan the vault, and construct the Dashboard app.

    Split from main() so tests can construct the app without starting
    Textual's event loop.
    """
    kb_root = resolve_kb_root(None, validate=True)
    index = VaultIndex.build(kb_root)
    action_items = load_action_items(kb_root)

    config = load_config(default_config_path())
    discovered = discover_plugins()
    calendar_service = EventKitCalendarService()
    reminders_service = EventKitRemindersService()

    def rebuild_pane_registry(
        index: VaultIndex, action_items: list[ActionItem]
    ) -> dict[str, PaneSpec]:
        context = PluginContext(
            vault_index=index,
            kb_root=kb_root,
            calendar_service=calendar_service,
            reminders_service=reminders_service,
        )
        return build_pane_registry(
            context=context,
            action_items=action_items,
            enabled_plugins=config.enabled_plugins,
            discovered=discovered,
        )

    return Dashboard(
        index=index,
        action_items=action_items,
        pane_registry=rebuild_pane_registry(index, action_items),
        layout_rows=config.layout_rows,
        rebuild_pane_registry=rebuild_pane_registry,
        kb_root=kb_root,
    )


def _build_index() -> VaultIndex:
    """Resolve KB_ROOT and scan the vault.

    The shared seam for every non-interactive subcommand — `people list`,
    `people show`, and any future read-only command group — so each one
    doesn't re-derive KB_ROOT resolution on its own.
    """
    kb_root = resolve_kb_root(None, validate=True)
    return VaultIndex.build(kb_root)


def _person_display_name(person: Person) -> str:
    """The vault's H1-heading-is-the-display-name convention (see index.py's
    _title_of) isn't exposed on Person itself, since VaultIndex only tracks
    it internally keyed by canonical name. Recompute it here from the
    person's own sections, falling back to the file's canonical stem for a
    person file with no H1 heading.
    """
    for section in person.sections:
        if section.level == 1 and section.heading:
            return section.heading
    return Path(person.file).stem


def _person_to_dict(person: Person) -> dict:
    return {
        "name": _person_display_name(person),
        "title": person.title,
        "team": person.team,
        "email": person.email,
        "slack_id": person.slack_id,
        "aliases": person.aliases,
    }


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Browse and manage your personal knowledge-base vault.

    Run with no subcommand to launch the interactive TUI dashboard.
    """
    if ctx.invoked_subcommand is None:
        build_app().run()


@cli.group()
def people() -> None:
    """Query people recorded in the vault."""


@people.command("list")
def people_list() -> None:
    """Print every person in the vault as a JSON array."""
    index = _build_index()
    click.echo(json.dumps([_person_to_dict(p) for p in index.all_people()], indent=2))


@people.command("show")
@click.argument("name")
@click.pass_context
def people_show(ctx: click.Context, name: str) -> None:
    """Print one person's record as JSON, looked up by name or alias."""
    index = _build_index()
    person = index.person(name)
    if person is None:
        # Keep stdout clean JSON-on-success; the error goes to stderr and the
        # exit code is the actual success/failure signal for scripts.
        click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        ctx.exit(1)
    click.echo(json.dumps(_person_to_dict(person), indent=2))


@cli.command("query")
@click.option("-t", "--text", help="Substring/full-text search text")
@click.option("-f", "--filter", "filters", multiple=True, help="Field filters, e.g. status=active")
@click.option(
    "-c",
    "--collection",
    "collections",
    multiple=True,
    help="Collection scope, e.g. people",
)
@click.option("-r", "--related-to", help="Filter by relationship target ref")
@click.option("--relationship", help="Filter by relationship name")
@click.option("-l", "--limit", type=int, help="Limit number of results")
@click.option("--json", "json_str", help="QueryRequest as raw JSON string")
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str | None,
    filters: list[str],
    collections: list[str],
    related_to: str | None,
    relationship: str | None,
    limit: int | None,
    json_str: str | None,
) -> None:
    """Query and search the KB vault."""
    from kb.contract.query import QueryFilter, QueryRequest
    from kb.core.engine import Engine

    try:
        kb_root = resolve_kb_root(None, validate=True)
        engine = Engine(kb_root)
    except Exception as e:
        from kb.contract.envelope import ErrorResponse
        from kb.contract.errors import ContractError
        err = ErrorResponse(
            error=ContractError.io(
                path="",
                message=f"Failed to load KB: {e}"
            )
        )
        click.echo(err.model_dump_json(indent=2 if sys.stdout.isatty() else None))
        ctx.exit(1)

    if json_str is not None:
        try:
            req = QueryRequest.model_validate_json(json_str)
        except Exception as e:
            from kb.contract.envelope import ErrorResponse
            from kb.contract.errors import ContractError
            err = ErrorResponse(
                error=ContractError.validation(
                    path="/",
                    message=f"Invalid QueryRequest JSON: {e}",
                    code="validation.invariant"
                )
            )
            click.echo(err.model_dump_json(indent=2 if sys.stdout.isatty() else None))
            ctx.exit(1)
    else:
        parsed_filters = []
        for flt in filters:
            op = "="
            field = flt
            val = ""
            for possible_op in [">=", "<=", "!=", "=", ">", "<", "contains"]:
                if possible_op in flt:
                    parts = flt.split(possible_op, 1)
                    field = parts[0].strip()
                    op = possible_op
                    val = parts[1].strip()
                    break
            parsed_filters.append(QueryFilter(field=field, op=op, value=val))

        req = QueryRequest(
            text=text,
            filters=parsed_filters,
            collections=list(collections),
            related_to=related_to,
            relationship=relationship,
            limit=limit,
        )

    response = engine.query(req)

    indent = 2 if sys.stdout.isatty() else None
    click.echo(response.model_dump_json(indent=indent))
    if not response.ok:
        ctx.exit(1)


@cli.group()
def contract() -> None:
    """Introspect the KB Contract."""


@contract.command("version")
def contract_version() -> None:
    """Print the contract version."""
    from kb.contract.version import CONTRACT_VERSION
    click.echo(CONTRACT_VERSION)


@contract.command("schema")
def contract_schema_cmd() -> None:
    """Print the contract's JSON Schema."""
    from kb.contract.schema import contract_schema
    click.echo(json.dumps(contract_schema(), indent=2))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
