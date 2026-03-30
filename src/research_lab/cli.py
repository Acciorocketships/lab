"""CLI entry points for the `lab` command — thin wrapper around :mod:`research_lab.runner`."""

from __future__ import annotations

from pathlib import Path

import click

from research_lab.global_config import global_config_exists, project_is_initialized
from research_lab.runner import (
    LabConfigError,
    init_project_at,
    run_interactive_global_setup,
    run_lab_console,
)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """AI research agent. Run without a subcommand to start the console."""
    if ctx.invoked_subcommand is None:
        try:
            run_lab_console()
        except LabConfigError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)


@main.command()
def setup() -> None:
    """One-time global setup: model provider, credentials, and preferences."""
    path = run_interactive_global_setup()
    click.echo(f"\nGlobal config saved to {path}")


@main.command()
@click.option("--idea", default=None, help="Research idea (prompted if omitted).")
@click.option("--criteria", default=None, help="Acceptance criteria (prompted if omitted).")
def init(idea: str | None, criteria: str | None) -> None:
    """Initialize a project in the current directory."""
    if not global_config_exists():
        click.echo("Error: global config not found. Run `lab setup` first.", err=True)
        raise SystemExit(1)

    project_dir = Path.cwd()
    if project_is_initialized(project_dir):
        click.echo(f"Project already initialized at {project_dir / '.airesearcher'}")
        if not click.confirm("Overwrite project config?", default=False):
            return
        overwrite = True
    else:
        overwrite = False

    if idea is None:
        idea = click.prompt("Research idea")
    if criteria is None:
        criteria = click.prompt("Acceptance criteria")

    prefs = click.prompt(
        "Project-specific preferences (blank to use global)",
        default="",
    )

    from research_lab.global_config import ProjectConfig

    pcfg = ProjectConfig(
        research_idea=idea,
        acceptance_criteria=criteria,
        preferences=prefs,
    )
    try:
        root = init_project_at(project_dir, pcfg, overwrite=overwrite)
    except LabConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"\nProject initialized at {root}")
    click.echo("Run `lab` to start the console.")


if __name__ == "__main__":
    main()
