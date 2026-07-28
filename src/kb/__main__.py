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


@cli.group()
def journal() -> None:
    """Manage journal entries in the vault."""


@journal.command("append")
@click.option(
    "--date",
    "date_str",
    help="The date of the journal entry (YYYY-MM-DD). Defaults to today."
)
@click.option("--section", help="The section heading to append to (e.g., 'Git Activity').")
@click.option("--content", help="The content to append. Reads from stdin if not provided or '-'.")
@click.pass_context
def journal_append(
    ctx: click.Context,
    date_str: str | None,
    section: str | None,
    content: str | None
) -> None:
    """Append content to a daily journal entry, optionally under a specific section."""
    import re
    from datetime import date as datetime_date

    from kb.contract import CONTRACT_VERSION

    if date_str is None:
        date_str = datetime_date.today().strftime("%Y-%m-%d")
    else:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            err_resp = {
                "contract_version": CONTRACT_VERSION,
                "ok": False,
                "error": {
                    "code": "validation.invalid_date",
                    "message": f"Invalid date format: {date_str}. Must be YYYY-MM-DD.",
                    "path": "/date",
                    "retryable": False
                },
                "warnings": []
            }
            click.echo(json.dumps(err_resp, indent=2), err=True)
            ctx.exit(1)

    if content is None or content == "-":
        import sys
        content = sys.stdin.read()

    kb_root = resolve_kb_root(None, validate=True)
    journal_dir = kb_root / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_file = journal_dir / f"{date_str}.md"

    # Read existing content or start fresh
    if journal_file.is_file():
        file_text = journal_file.read_text(encoding="utf-8")
    else:
        file_text = f"# {date_str}\n"

    from kb.core.markdown import Section, split_sections

    sections = split_sections(file_text)

    # Ensure we have the initial H1 section if it's a new file or doesn't have it
    has_h1 = any(s.level == 1 for s in sections)
    if not has_h1:
        insert_at = 1 if sections and sections[0].heading is None else 0
        sections.insert(insert_at, Section(heading=date_str, level=1, lines=[]))

    content_lines = [line for line in content.split("\n")]
    if content_lines and content_lines[-1] == "":
        content_lines.pop()

    if section:
        target_section = None
        for s in sections:
            if s.level == 2 and s.heading and s.heading.strip().lower() == section.strip().lower():
                target_section = s
                break

        if target_section is not None:
            new_lines = list(target_section.lines)
            if new_lines and new_lines[-1] != "":
                new_lines.append("")
            new_lines.extend(content_lines)
            idx = sections.index(target_section)
            sections[idx] = Section(
                heading=target_section.heading,
                level=target_section.level,
                lines=new_lines
            )
        else:
            sections.append(Section(heading=section, level=2, lines=content_lines))
    else:
        if sections:
            last_section = sections[-1]
            new_lines = list(last_section.lines)
            if new_lines:
                if new_lines[-1] != "":
                    new_lines.append("")
            else:
                if last_section.level == 1:
                    new_lines.append("")
            new_lines.extend(content_lines)
            sections[-1] = Section(
                heading=last_section.heading,
                level=last_section.level,
                lines=new_lines
            )
        else:
            sections.append(Section(heading=None, level=0, lines=content_lines))

    # Serialize sections back to markdown
    parts = []
    for s in sections:
        part = []
        if s.heading is not None:
            part.append(f"{'#' * s.level} {s.heading}")
        part.extend(s.lines)
        parts.append("\n".join(part))

    new_text = "\n\n".join(parts)
    if not new_text.endswith("\n"):
        new_text += "\n"

    # Write back to disk
    journal_file.write_text(new_text, encoding="utf-8")

    # Success Response Envelope
    success_resp = {
        "contract_version": CONTRACT_VERSION,
        "ok": True,
        "data": {
            "file": f"journal/{date_str}.md",
            "date": date_str,
            "section": section,
            "bytes_written": len(new_text.encode("utf-8"))
        },
        "warnings": []
    }
    click.echo(json.dumps(success_resp, indent=2))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
