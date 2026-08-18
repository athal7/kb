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
from datetime import date
from pathlib import Path

import click

from kb.config import resolve_kb_root
from kb.core.actionitems import (
    ACTION_ITEMS_FILENAME,
    ActionItem,
    ActionItemsFile,
    load_action_items,
)
from kb.core.index import VaultIndex
from kb.core.models import Person, Product, Project
from kb.core.openspec import AmbiguousChangeError, OpenSpecImportError, OpenSpecStore
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


def _product_to_dict(product: Product) -> dict:
    return {
        "name": _entity_display_name(product),
        "status": product.status,
        "repos": product.repos,
        "linear": product.linear_label,
        "aliases": product.aliases,
    }


def _validate_date_param(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Click callback that validates --from/--to are valid YYYY-MM-DD strings."""
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise click.BadParameter(
            "must be in YYYY-MM-DD format", ctx=ctx, param=param
        ) from exc
    return value


@click.group(invoke_without_command=True)
@click.version_option(package_name="kb")
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
def projects() -> None:
    """Query projects recorded in the vault."""


@projects.command("list")
def projects_list() -> None:
    """Print every project in the vault as a JSON array."""
    index = _build_index()
    click.echo(json.dumps([_project_to_dict(p) for p in index.all_projects()], indent=2))


@projects.command("show")
@click.argument("name")
@click.pass_context
def projects_show(ctx: click.Context, name: str) -> None:
    """Print one project's record as JSON, looked up by name or alias."""
    index = _build_index()
    project = index.project(name)
    if project is None:
        # Keep stdout clean JSON-on-success; the error goes to stderr and the
        # exit code is the actual success/failure signal for scripts.
        click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        ctx.exit(1)
    click.echo(json.dumps(_project_to_dict(project), indent=2))


@cli.group()
def products() -> None:
    """Query products recorded in the vault."""


@products.command("list")
def products_list() -> None:
    """Print every product in the vault as a JSON array."""
    index = _build_index()
    click.echo(json.dumps([_product_to_dict(p) for p in index.all_products()], indent=2))


@products.command("show")
@click.argument("name")
@click.pass_context
def products_show(ctx: click.Context, name: str) -> None:
    """Print one product's record as JSON, looked up by name or alias."""
    index = _build_index()
    product = index.product(name)
    if product is None:
        # Keep stdout clean JSON-on-success; the error goes to stderr and the
        # exit code is the actual success/failure signal for scripts.
        click.echo(json.dumps({"error": "not found", "name": name}), err=True)
        ctx.exit(1)
    click.echo(json.dumps(_product_to_dict(product), indent=2))


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


@action_items_group.command("list")
def action_items_list() -> None:
    """Print open or in-progress action items as a JSON array."""
    kb_root = resolve_kb_root(None, validate=True)
    file_obj, error = _get_action_items_file(kb_root)
    if file_obj is None:
        click.echo(json.dumps({"error": error or "unknown error"}), err=True)
        click.get_current_context().exit(1)

    # We only return "open" action items (not completed/checked)
    open_items = [i for i in file_obj.items if not i.checked]
    click.echo(json.dumps([_action_item_to_dict(i) for i in open_items], indent=2))


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
def journal_list(from_date: str | None, to_date: str | None) -> None:
    """Print every journal entry in the vault as a JSON array, optionally filtered by date."""
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
    click.echo(json.dumps(results, indent=2))


@journal.command("show")
@click.argument("date_str", metavar="DATE", callback=_validate_date_param)
@click.pass_context
def journal_show(ctx: click.Context, date_str: str) -> None:
    """Print one journal entry's sections/content as JSON, looked up by date (YYYY-MM-DD)."""
    index = _build_index()
    d = date.fromisoformat(date_str)
    entries = index.journal_entries(start=d, end=d)
    if not entries:
        click.echo(json.dumps({"error": "not found", "date": date_str}), err=True)
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
        ]
    }
    click.echo(json.dumps(result, indent=2))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

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
        raise click.BadParameter(
            "must be in YYYY-MM-DD format", ctx=ctx, param=param
        ) from exc
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
def openspec_list(
    repo: str | None,
    from_date: str | None,
    to_date: str | None,
) -> None:
    """Print all archived OpenSpec changes as a JSON array."""
    store = _openspec_store()
    archives = store.list_archives(repo=repo, from_date=from_date, to_date=to_date)
    click.echo(json.dumps(archives, indent=2))


@openspec.command("show")
@click.argument("change_name")
@click.option("--repo", help="Scope the search to a specific repo-slug.")
@click.pass_context
def openspec_show(
    ctx: click.Context,
    change_name: str,
    repo: str | None,
) -> None:
    """Print one change's metadata and design.md as JSON."""
    store = _openspec_store()
    try:
        result = store.show_archive(change_name, repo=repo)
    except AmbiguousChangeError as exc:
        click.echo(
            json.dumps(
                {
                    "error": "ambiguous",
                    "change": exc.change_name,
                    "repos": [c["meta"]["repo"] for c in exc.candidates],
                }
            ),
            err=True,
        )
        ctx.exit(1)
    if result is None:
        click.echo(
            json.dumps({"error": "not found", "change": change_name}),
            err=True,
        )
        ctx.exit(1)
    click.echo(json.dumps(result, indent=2))


@openspec.group()
def specs() -> None:
    """Query standing specs from the OpenSpec store."""


@specs.command("list")
@click.option("--repo", help="Filter by repo-slug directory name.")
def openspec_specs_list(repo: str | None) -> None:
    """Print all standing specs as a JSON array."""
    store = _openspec_store()
    specs_list = store.list_specs(repo=repo)
    click.echo(json.dumps(specs_list, indent=2))


@specs.command("show")
@click.argument("spec_name")
@click.option("--repo", required=True, help="The repo-slug containing the spec.")
@click.pass_context
def openspec_specs_show(
    ctx: click.Context,
    spec_name: str,
    repo: str,
) -> None:
    """Print one standing spec's content as JSON."""
    store = _openspec_store()
    result = store.show_spec(spec_name, repo=repo)
    if result is None:
        click.echo(
            json.dumps({"error": "not found", "spec": spec_name, "repo": repo}),
            err=True,
        )
        ctx.exit(1)
    click.echo(json.dumps(result, indent=2))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
