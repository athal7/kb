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
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import click

from kb.config import (
    UnknownConfigKeyError,
    get_config_value,
    resolve_kb_root,
    set_config_value,
)
from kb.core.actionitems import (
    ACTION_ITEMS_FILENAME,
    ActionItem,
    ActionItemsFile,
    load_action_items,
)
from kb.core.index import VaultIndex
from kb.core.models import Person, Product, Project
from kb.core.openspec import AmbiguousChangeError, OpenSpecImportError, OpenSpecStore
from kb.cq.projection import (
    ALL_LOCAL_AGENTS_POLICY,
    CQCli,
    ProjectionLedger,
    ProjectionManifest,
    ProjectionScope,
    apply_manifest,
    build_plan,
    verify,
)
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


def _entity_display_name(entity: Person | Project | Product) -> str:
    """The vault's H1-heading-is-the-display-name convention (see index.py's
    _title_of) isn't exposed on the entity itself, since VaultIndex only tracks
    it internally keyed by canonical name. Recompute it here from the
    entity's own sections, falling back to the file's canonical stem for an
    entity file with no H1 heading.
    """
    for section in entity.sections:
        if section.level == 1 and section.heading:
            return section.heading
    return Path(entity.file).stem


def _person_to_dict(person: Person) -> dict:
    return {
        "name": _entity_display_name(person),
        "title": person.title,
        "team": person.team,
        "email": person.email,
        "slack_id": person.slack_id,
        "github": person.github,
        "aliases": person.aliases,
    }


def _get_format(ctx: click.Context) -> str:
    """Determine the active output format.

    Looks up the `--format` option from the root click context. If it's
    'auto', checks if stdout is connected to an interactive TTY.
    """
    fmt = ctx.find_root().params.get("format", "auto")
    if fmt == "auto":
        is_tty = getattr(sys.stdout, "isatty", lambda: False)()
        return "text" if is_tty else "json"
    return fmt


def _format_person_text(person_dict: dict) -> str:
    """Format a person's details in a human-readable text block."""
    lines = []
    lines.append(f"Name: {person_dict['name']}")
    if person_dict.get("title"):
        lines.append(f"Title: {person_dict['title']}")
    if person_dict.get("team"):
        lines.append(f"Team: {person_dict['team']}")
    if person_dict.get("email"):
        lines.append(f"Email: {person_dict['email']}")
    if person_dict.get("slack_id"):
        lines.append(f"Slack ID: {person_dict['slack_id']}")
    if person_dict.get("aliases"):
        aliases_str = ", ".join(person_dict["aliases"])
        lines.append(f"Aliases: {aliases_str}")
    return "\n".join(lines)


def _project_to_dict(project: Project) -> dict:
    return {
        "name": _entity_display_name(project),
        "status": project.status,
        "product": project.product_link.raw_text if project.product_link else None,
        "github": project.github,
        "linear": project.linear,
        "aliases": project.aliases,
        "people": [link.raw_text for link in project.people_links],
    }


def _format_project_text(project_dict: dict) -> str:
    """Format a project's details in a human-readable text block."""
    lines = [f"Name: {project_dict['name']}"]
    if project_dict.get("status"):
        lines.append(f"Status: {project_dict['status']}")
    if project_dict.get("product"):
        lines.append(f"Product: {project_dict['product']}")
    if project_dict.get("github"):
        lines.append(f"GitHub: {project_dict['github']}")
    if project_dict.get("linear"):
        lines.append(f"Linear: {project_dict['linear']}")
    if project_dict.get("people"):
        lines.append(f"People: {', '.join(project_dict['people'])}")
    if project_dict.get("aliases"):
        lines.append(f"Aliases: {', '.join(project_dict['aliases'])}")
    return "\n".join(lines)


def _product_to_dict(product: Product) -> dict:
    return {
        "name": _entity_display_name(product),
        "status": product.status,
        "repos": product.repos,
        "linear": product.linear_label,
        "aliases": product.aliases,
    }


def _format_product_text(product_dict: dict) -> str:
    """Format a product's details in a human-readable text block."""
    lines = [f"Name: {product_dict['name']}"]
    if product_dict.get("status"):
        lines.append(f"Status: {product_dict['status']}")
    if product_dict.get("repos"):
        lines.append(f"Repos: {', '.join(product_dict['repos'])}")
    if product_dict.get("linear"):
        lines.append(f"Linear: {product_dict['linear']}")
    if product_dict.get("aliases"):
        lines.append(f"Aliases: {', '.join(product_dict['aliases'])}")
    return "\n".join(lines)


def _validate_date_param(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Click callback that validates --from/--to are valid YYYY-MM-DD strings."""
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise click.BadParameter("must be in YYYY-MM-DD format", ctx=ctx, param=param) from exc
    return value


@click.group(invoke_without_command=True)
@click.version_option(package_name="kb")
@click.option(
    "--format",
    type=click.Choice(["json", "text", "auto"]),
    default="auto",
    help="Output format (json, text, or auto).",
)
@click.pass_context
def cli(ctx: click.Context, format: str) -> None:
    """Browse and manage your personal knowledge-base vault.

    Run with no subcommand to launch the interactive TUI dashboard.
    """
    if ctx.invoked_subcommand is None:
        build_app().run()


@cli.group("config")
def config_group() -> None:
    """Get and set kb configuration values (stored in ~/.config/kb/config.toml)."""


@config_group.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Print the value of a configuration KEY (its default if unset)."""
    try:
        value = get_config_value(key)
    except UnknownConfigKeyError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("" if value is None else value)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set configuration KEY to VALUE, persisting it to the config file."""
    try:
        set_config_value(key, value)
    except UnknownConfigKeyError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Set {key} = {value}")


@cli.group()
def people() -> None:
    """Query people recorded in the vault."""


@people.command("list")
@click.pass_context
def people_list(ctx: click.Context) -> None:
    """Print every person in the vault."""
    index = _build_index()
    people_dicts = [_person_to_dict(p) for p in index.all_people()]
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(people_dicts, indent=2))
    else:
        output = "\n\n".join(_format_person_text(p) for p in people_dicts)
        click.echo(output)


@people.command("show")
@click.argument("name")
@click.pass_context
def people_show(ctx: click.Context, name: str) -> None:
    """Print one person's record, looked up by name or alias."""
    index = _build_index()
    person = index.person(name)
    fmt = _get_format(ctx)
    if person is None:
        # Keep stdout clean JSON-on-success; the error goes to stderr and the
        # exit code is the actual success/failure signal for scripts.
        if fmt == "json":
            click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        else:
            click.echo(f"Error: person '{name}' not found", err=True)
        ctx.exit(1)

    person_dict = _person_to_dict(person)
    if fmt == "json":
        click.echo(json.dumps(person_dict, indent=2))
    else:
        click.echo(_format_person_text(person_dict))


@cli.group()
def projects() -> None:
    """Query projects recorded in the vault."""


@projects.command("list")
@click.pass_context
def projects_list(ctx: click.Context) -> None:
    """Print every project in the vault."""
    index = _build_index()
    projects_dicts = [_project_to_dict(p) for p in index.all_projects()]
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(projects_dicts, indent=2))
    else:
        click.echo("\n\n".join(_format_project_text(p) for p in projects_dicts))


@projects.command("show")
@click.argument("name")
@click.pass_context
def projects_show(ctx: click.Context, name: str) -> None:
    """Print one project's record, looked up by name or alias."""
    index = _build_index()
    project = index.project(name)
    fmt = _get_format(ctx)
    if project is None:
        # Keep stdout clean on success; the error goes to stderr and the exit
        # code is the actual success/failure signal for scripts.
        if fmt == "json":
            click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        else:
            click.echo(f"Error: project '{name}' not found", err=True)
        ctx.exit(1)
    project_dict = _project_to_dict(project)
    if fmt == "json":
        click.echo(json.dumps(project_dict, indent=2))
    else:
        click.echo(_format_project_text(project_dict))


@cli.group()
def products() -> None:
    """Query products recorded in the vault."""


@products.command("list")
@click.pass_context
def products_list(ctx: click.Context) -> None:
    """Print every product in the vault."""
    index = _build_index()
    products_dicts = [_product_to_dict(p) for p in index.all_products()]
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(products_dicts, indent=2))
    else:
        click.echo("\n\n".join(_format_product_text(p) for p in products_dicts))


@products.command("show")
@click.argument("name")
@click.pass_context
def products_show(ctx: click.Context, name: str) -> None:
    """Print one product's record, looked up by name or alias."""
    index = _build_index()
    product = index.product(name)
    fmt = _get_format(ctx)
    if product is None:
        # Keep stdout clean on success; the error goes to stderr and the exit
        # code is the actual success/failure signal for scripts.
        if fmt == "json":
            click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        else:
            click.echo(f"Error: product '{name}' not found", err=True)
        ctx.exit(1)
    product_dict = _product_to_dict(product)
    if fmt == "json":
        click.echo(json.dumps(product_dict, indent=2))
    else:
        click.echo(_format_product_text(product_dict))


@cli.group("action-items")
def action_items_group() -> None:
    """Manage action items recorded in the vault."""


def _get_action_items_file(kb_root: Path) -> tuple[ActionItemsFile | None, str | None]:
    path = kb_root / ACTION_ITEMS_FILENAME
    if not path.is_file():
        return None, f"Action items file {path} not found"
    try:
        return ActionItemsFile.parse(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"Error parsing action items file: {e}"


def _action_item_to_dict(item: ActionItem) -> dict:
    status = "todo"
    if item.checked:
        status = "completed"
    elif item.in_progress:
        status = "in_progress"

    return {
        "line_no": item.line_no,
        "source_group": item.source_group,
        "status": status,
        "text": item.text,
    }


def _format_action_item_text(item: dict) -> str:
    """Format an action item's fields as a human-readable text block."""
    lines = [f"Line: {item['line_no']}", f"Status: {item['status']}"]
    if item.get("source_group"):
        lines.append(f"Group: {item['source_group']}")
    lines.append(f"Text: {item['text']}")
    return "\n".join(lines)


@action_items_group.command("list")
@click.pass_context
def action_items_list(ctx: click.Context) -> None:
    """Print open or in-progress action items."""
    kb_root = resolve_kb_root(None, validate=True)
    file_obj, error = _get_action_items_file(kb_root)
    fmt = _get_format(ctx)
    if file_obj is None:
        if fmt == "json":
            click.echo(json.dumps({"error": error or "unknown error"}), err=True)
        else:
            click.echo(f"Error: {error or 'unknown error'}", err=True)
        ctx.exit(1)

    # We only return "open" action items (not completed/checked)
    open_items = [i for i in file_obj.items if not i.checked]
    items = [_action_item_to_dict(i) for i in open_items]
    if fmt == "json":
        click.echo(json.dumps(items, indent=2))
    else:
        click.echo("\n\n".join(_format_action_item_text(i) for i in items))


def _update_action_item_status(line_no: int, status: str) -> None:
    kb_root = resolve_kb_root(None, validate=True)
    file_obj, error = _get_action_items_file(kb_root)
    if file_obj is None:
        click.echo(json.dumps({"error": error or "unknown error"}), err=True)
        click.get_current_context().exit(1)

    matching_items = [i for i in file_obj.items if i.line_no == line_no]
    if not matching_items:
        click.echo(json.dumps({"error": f"No action item found at line {line_no}"}), err=True)
        click.get_current_context().exit(1)

    item = matching_items[0]
    file_obj.set_status(item, status)

    path = kb_root / ACTION_ITEMS_FILENAME
    path.write_text(file_obj.serialize(), encoding="utf-8")
    click.echo(json.dumps({"ok": True, "line_no": line_no, "status": status}))


@action_items_group.command("complete")
@click.argument("line_no", type=int)
def action_items_complete(line_no: int) -> None:
    """Mark an action item completed."""
    _update_action_item_status(line_no, "completed")


@action_items_group.command("progress")
@click.argument("line_no", type=int)
def action_items_progress(line_no: int) -> None:
    """Mark an action item as in-progress."""
    _update_action_item_status(line_no, "in_progress")


@action_items_group.command("todo")
@click.argument("line_no", type=int)
def action_items_todo(line_no: int) -> None:
    """Mark an action item as todo."""
    _update_action_item_status(line_no, "todo")


@cli.group()
def journal() -> None:
    """Manage journal entries in the vault."""


@journal.command("append")
@click.option(
    "--date", "date_str", help="The date of the journal entry (YYYY-MM-DD). Defaults to today."
)
@click.option("--section", help="The section heading to append to (e.g., 'Git Activity').")
@click.option("--content", help="The content to append. Reads from stdin if not provided or '-'.")
@click.pass_context
def journal_append(
    ctx: click.Context, date_str: str | None, section: str | None, content: str | None
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
                    "retryable": False,
                },
                "warnings": [],
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
                heading=target_section.heading, level=target_section.level, lines=new_lines
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
                heading=last_section.heading, level=last_section.level, lines=new_lines
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
            "bytes_written": len(new_text.encode("utf-8")),
        },
        "warnings": [],
    }
    click.echo(json.dumps(success_resp, indent=2))


def _format_journal_entry_text(entry: dict) -> str:
    """Format a journal entry's listing fields as a text block."""
    lines = [f"Date: {entry['date']}"]
    if entry.get("file"):
        lines.append(f"File: {entry['file']}")
    return "\n".join(lines)


@journal.command("list")
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=_validate_date_param,
    help="Start date filter (YYYY-MM-DD, inclusive).",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=_validate_date_param,
    help="End date filter (YYYY-MM-DD, inclusive).",
)
@click.pass_context
def journal_list(ctx: click.Context, from_date: str | None, to_date: str | None) -> None:
    """Print every journal entry in the vault, optionally filtered by date."""
    index = _build_index()
    from_d = date.fromisoformat(from_date) if from_date else None
    to_d = date.fromisoformat(to_date) if to_date else None
    entries = index.journal_entries(start=from_d, end=to_d)
    results = [
        {
            "date": entry.date,
            "file": entry.file,
        }
        for entry in entries
    ]
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(results, indent=2))
    else:
        click.echo("\n\n".join(_format_journal_entry_text(e) for e in results))


def _format_journal_entry_detail_text(entry: dict) -> str:
    """Render a journal entry as markdown: its date H1 plus each section."""
    parts = [f"# {entry['date']}"]
    for section in entry["sections"]:
        part: list[str] = []
        if section["heading"] is not None:
            part.append(f"{'#' * section['level']} {section['heading']}")
        part.extend(section["lines"])
        parts.append("\n".join(part))
    return "\n\n".join(parts)


@journal.command("show")
@click.argument("date_str", metavar="DATE", callback=_validate_date_param)
@click.pass_context
def journal_show(ctx: click.Context, date_str: str) -> None:
    """Print one journal entry's sections/content, looked up by date (YYYY-MM-DD)."""
    index = _build_index()
    d = date.fromisoformat(date_str)
    entries = index.journal_entries(start=d, end=d)
    fmt = _get_format(ctx)
    if not entries:
        if fmt == "json":
            click.echo(json.dumps({"error": "not found", "date": date_str}), err=True)
        else:
            click.echo(f"Error: journal entry '{date_str}' not found", err=True)
        ctx.exit(1)

    entry = entries[0]
    result = {
        "date": entry.date,
        "file": entry.file,
        "sections": [
            {
                "heading": s.heading,
                "level": s.level,
                "lines": s.lines,
            }
            for s in entry.sections
        ],
    }
    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(_format_journal_entry_detail_text(result))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# CQ projection — deterministic projection into the configured local CQ DB
# ---------------------------------------------------------------------------


_DEFAULT_PROJECTION_LEDGER = "~/.local/share/kb/cq-projection-ledger.json"
_PROJECTION_SCOPE_CHOICES = (
    "people",
    "projects",
    "products",
    "decisions",
    "standing",
)


@cli.group()
def cq() -> None:
    """Project canonical KB records into the isolated local CQ index."""


def _projection_scopes(values: tuple[str, ...]) -> tuple[ProjectionScope, ...]:
    if not values:
        return (
            ProjectionScope.PEOPLE,
            ProjectionScope.PROJECTS,
            ProjectionScope.PRODUCTS,
            ProjectionScope.DECISIONS,
            ProjectionScope.STANDING,
        )
    try:
        return tuple(ProjectionScope(value) for value in values)
    except ValueError as exc:
        raise click.BadParameter(
            "scope must be people, projects, products, decisions, or standing"
        ) from exc


def _projection_root(value: str | None) -> Path:
    root = Path(value or get_config_value("path") or "").expanduser()
    if not root.is_dir():
        raise click.ClickException(f"KB vault root does not exist: {root}")
    return root.resolve()


def _projection_ledger(value: str | None) -> ProjectionLedger:
    return ProjectionLedger.open(Path(value or _DEFAULT_PROJECTION_LEDGER).expanduser())


def _projection_target() -> Path:
    configured = os.environ.get("CQ_LOCAL_DB_PATH")
    if not configured:
        raise click.ClickException("CQ_LOCAL_DB_PATH must configure the local CQ database")
    target = Path(configured).expanduser().resolve()
    if not target.is_file():
        raise click.ClickException(f"configured CQ target does not exist: {target}")
    return target


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".cq-projection-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _build_projection_plan(
    *,
    scope: tuple[str, ...],
    kb_root: str | None,
    ledger_path: str | None,
    authorization_policy: str | None,
) -> ProjectionManifest:
    return build_plan(
        kb_root=_projection_root(kb_root),
        ledger=_projection_ledger(ledger_path),
        target_db=_projection_target(),
        authorization_policy=authorization_policy,
        scopes=_projection_scopes(scope),
    )


@cq.group()
def projection() -> None:
    """Plan, approve, apply, verify, and backfill local CQ projection."""


@projection.command("plan")
@click.option("--scope", multiple=True, type=click.Choice(_PROJECTION_SCOPE_CHOICES))
@click.option("--kb-root")
@click.option("--ledger-path")
@click.option("--authorization-policy", type=click.Choice([ALL_LOCAL_AGENTS_POLICY]))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
def projection_plan(
    scope: tuple[str, ...],
    kb_root: str | None,
    ledger_path: str | None,
    authorization_policy: str | None,
    output: Path,
) -> None:
    """Write a non-mutating unapproved plan manifest."""
    _write_json(
        output,
        _build_projection_plan(
            scope=scope,
            kb_root=kb_root,
            ledger_path=ledger_path,
            authorization_policy=authorization_policy,
        ).to_dict(),
    )
    click.echo(str(output))


@projection.command("approve")
@click.argument("plan_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
def projection_approve(plan_path: Path, output: Path) -> None:
    """Bind approval to the reviewed full manifest content digest."""
    manifest = ProjectionManifest.from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
    if manifest.approved_digest is not None:
        raise click.ClickException("plan already contains an approval digest")
    _write_json(output, manifest.approve().to_dict())
    click.echo(str(output))


@projection.command("apply")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--ledger-path")
@click.option("--kb-root")
def projection_apply(manifest_path: Path, ledger_path: str | None, kb_root: str | None) -> None:
    """Apply only an approval-bound manifest through the CQ CLI."""
    manifest = ProjectionManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    target = _projection_target()
    results = apply_manifest(
        manifest=manifest,
        ledger=_projection_ledger(ledger_path),
        kb_root=_projection_root(kb_root),
        target_db=target,
        cq=CQCli(),
    )
    click.echo(json.dumps({"results": [result.to_dict() for result in results]}, indent=2))


@projection.command("status")
@click.option("--ledger-path")
def projection_status(ledger_path: str | None) -> None:
    """Show durable expected-source completion and stale state."""
    ledger = _projection_ledger(ledger_path)
    click.echo(
        json.dumps(
            {
                "scopes": [completion.to_dict() for completion in ledger.completions()],
                "records": [record.to_dict() for record in ledger.records()],
                "pending": [pending.to_dict() for pending in ledger.pending()],
            },
            indent=2,
        )
    )


@projection.command("verify")
@click.option("--scope", multiple=True, type=click.Choice(_PROJECTION_SCOPE_CHOICES))
@click.option("--ledger-path")
def projection_verify(scope: tuple[str, ...], ledger_path: str | None) -> None:
    """Verify exact CQ identity, KU ID, and source content marker mappings."""
    target = _projection_target()
    results = verify(
        ledger=_projection_ledger(ledger_path),
        cq=CQCli(),
        scopes=_projection_scopes(scope),
    )
    invalid = sum(not result.valid for result in results)
    click.echo(
        json.dumps(
            {
                "valid": len(results) - invalid,
                "invalid": invalid,
                "results": [result.to_dict() for result in results],
            },
            indent=2,
        )
    )
    if invalid:
        raise click.exceptions.Exit(1)


@projection.command("backfill")
@click.option("--kb-root")
@click.option("--ledger-path")
@click.option("--authorization-policy", type=click.Choice([ALL_LOCAL_AGENTS_POLICY]))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
def projection_backfill(
    kb_root: str | None,
    ledger_path: str | None,
    authorization_policy: str | None,
    output: Path,
) -> None:
    """Write a one-time all-scope unapproved backfill plan."""
    _write_json(
        output,
        _build_projection_plan(
            scope=(),
            kb_root=kb_root,
            ledger_path=ledger_path,
            authorization_policy=authorization_policy,
        ).to_dict(),
    )
    click.echo(str(output))


# ---------------------------------------------------------------------------
# openspec — query archived OpenSpec changes and standing specs
# ---------------------------------------------------------------------------


def _validate_date_param(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Click callback that validates --from/--to are valid YYYY-MM-DD strings."""
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise click.BadParameter("must be in YYYY-MM-DD format", ctx=ctx, param=param) from exc
    return value


def _openspec_store() -> OpenSpecStore:
    """Resolve the OpenSpec store root and return a store instance.

    The store root is resolved from the ``KB_OPENSPEC_ROOT`` environment
    variable (for tests), or from ``KB_ROOT`` by appending ``openspec`` to
    the parent directory.
    """
    env_root = os.environ.get("KB_OPENSPEC_ROOT")
    if env_root:
        return OpenSpecStore(Path(env_root))
    kb_root = resolve_kb_root(None, validate=False)
    return OpenSpecStore(kb_root / "openspec")


@cli.group()
def openspec() -> None:
    """Query and import archived OpenSpec changes and standing specs."""


@openspec.command("import")
@click.argument("record_path", type=click.Path(dir_okay=False, path_type=Path))
@click.pass_context
def openspec_import(ctx: click.Context, record_path: Path) -> None:
    """Import one approved OMP plan record from JSON."""
    try:
        with record_path.open(encoding="utf-8") as record_file:
            record = json.load(record_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        click.echo(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_record",
                        "message": f"could not read record: {exc}",
                    }
                }
            ),
            err=True,
        )
        ctx.exit(1)

    try:
        result = _openspec_store().import_archive(record)
    except OpenSpecImportError as exc:
        click.echo(
            json.dumps({"error": {"code": exc.code, "message": exc.message}}),
            err=True,
        )
        ctx.exit(1)

    click.echo(json.dumps(result, indent=2))


def _format_archive_text(archive: dict) -> str:
    """Format an archived change's listing fields as a text block."""
    lines = [f"Change: {archive.get('change', '')}"]
    if archive.get("repo"):
        lines.append(f"Repo: {archive['repo']}")
    if archive.get("date"):
        lines.append(f"Date: {archive['date']}")
    if archive.get("branch"):
        lines.append(f"Branch: {archive['branch']}")
    if archive.get("worktree"):
        lines.append(f"Worktree: {archive['worktree']}")
    if archive.get("path"):
        lines.append(f"Path: {archive['path']}")
    return "\n".join(lines)


@openspec.command("list")
@click.option("--repo", help="Filter by repo-slug directory name.")
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=_validate_date_param,
    help="Start date filter (YYYY-MM-DD, inclusive).",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=_validate_date_param,
    help="End date filter (YYYY-MM-DD, inclusive).",
)
@click.pass_context
def openspec_list(
    ctx: click.Context,
    repo: str | None,
    from_date: str | None,
    to_date: str | None,
) -> None:
    """Print all archived OpenSpec changes, optionally filtered."""
    store = _openspec_store()
    archives = store.list_archives(repo=repo, from_date=from_date, to_date=to_date)
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(archives, indent=2))
    else:
        click.echo("\n\n".join(_format_archive_text(a) for a in archives))


def _format_archive_detail_text(archive: dict) -> str:
    """Render an archived change as a metadata block plus its design.md."""
    meta = archive.get("meta", {})
    lines = [f"Change: {meta.get('change', '')}"]
    if meta.get("repo"):
        lines.append(f"Repo: {meta['repo']}")
    if meta.get("date"):
        lines.append(f"Date: {meta['date']}")
    if meta.get("branch"):
        lines.append(f"Branch: {meta['branch']}")
    if meta.get("worktree"):
        lines.append(f"Worktree: {meta['worktree']}")
    header = "\n".join(lines)
    design = archive.get("design")
    return f"{header}\n\n{design}" if design else header


@openspec.command("show")
@click.argument("change_name")
@click.option("--repo", help="Scope the search to a specific repo-slug.")
@click.pass_context
def openspec_show(
    ctx: click.Context,
    change_name: str,
    repo: str | None,
) -> None:
    """Print one change's metadata and design.md, looked up by name."""
    store = _openspec_store()
    fmt = _get_format(ctx)
    try:
        result = store.show_archive(change_name, repo=repo)
    except AmbiguousChangeError as exc:
        repos = [c["meta"]["repo"] for c in exc.candidates]
        if fmt == "json":
            click.echo(
                json.dumps(
                    {
                        "error": "ambiguous",
                        "change": exc.change_name,
                        "repos": repos,
                    }
                ),
                err=True,
            )
        else:
            click.echo(
                f"Error: change '{change_name}' is ambiguous across repos: {', '.join(repos)}",
                err=True,
            )
        ctx.exit(1)
    if result is None:
        if fmt == "json":
            click.echo(
                json.dumps({"error": "not found", "change": change_name}),
                err=True,
            )
        else:
            click.echo(f"Error: change '{change_name}' not found", err=True)
        ctx.exit(1)
    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(_format_archive_detail_text(result))


@openspec.group()
def specs() -> None:
    """Query standing specs from the OpenSpec store."""


def _format_spec_text(spec: dict) -> str:
    """Format a standing spec's listing fields as a text block."""
    lines = [f"Name: {spec['name']}"]
    if spec.get("repo"):
        lines.append(f"Repo: {spec['repo']}")
    if spec.get("path"):
        lines.append(f"Path: {spec['path']}")
    return "\n".join(lines)


@specs.command("list")
@click.option("--repo", help="Filter by repo-slug directory name.")
@click.pass_context
def openspec_specs_list(ctx: click.Context, repo: str | None) -> None:
    """Print all standing specs, optionally filtered by repo."""
    store = _openspec_store()
    specs_list = store.list_specs(repo=repo)
    fmt = _get_format(ctx)
    if fmt == "json":
        click.echo(json.dumps(specs_list, indent=2))
    else:
        click.echo("\n\n".join(_format_spec_text(s) for s in specs_list))


def _format_spec_detail_text(spec: dict) -> str:
    """Render a standing spec as its name/repo header plus raw markdown."""
    header = f"# {spec['name']} ({spec['repo']})"
    content = spec.get("content", "")
    return f"{header}\n\n{content}" if content else header


@specs.command("show")
@click.argument("spec_name")
@click.option("--repo", required=True, help="The repo-slug containing the spec.")
@click.pass_context
def openspec_specs_show(
    ctx: click.Context,
    spec_name: str,
    repo: str,
) -> None:
    """Print one standing spec's content, looked up by name and repo."""
    store = _openspec_store()
    result = store.show_spec(spec_name, repo=repo)
    fmt = _get_format(ctx)
    if result is None:
        if fmt == "json":
            click.echo(
                json.dumps({"error": "not found", "spec": spec_name, "repo": repo}),
                err=True,
            )
        else:
            click.echo(f"Error: spec '{spec_name}' not found in repo '{repo}'", err=True)
        ctx.exit(1)
    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(_format_spec_detail_text(result))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
