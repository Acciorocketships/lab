"""CLI entry points for the `lab` command — thin wrapper around :mod:`research_lab.runner`."""

from __future__ import annotations

from pathlib import Path

import click

from research_lab.global_config import (
    ProjectConfig,
    global_config_exists,
    project_is_initialized,
)
from research_lab.runner import (
    LabConfigError,
    init_project_at,
    read_multiline_terminal,
    run_auth_test,
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
    """One-time global setup: model provider, credentials, worker backend."""
    path = run_interactive_global_setup()
    click.echo(f"\nGlobal config saved to {path}")


@main.command("auth-test")
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Project root (default: current directory).",
)
def auth_test(project_dir: Path | None) -> None:
    """Show where orchestrator credentials come from and call the routing model once."""
    root = project_dir if project_dir is not None else Path.cwd()
    try:
        run_auth_test(root)
    except LabConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@main.command()
def init() -> None:
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

    click.echo("")
    click.echo(
        "Research brief — goal, approach, and what “done” looks like (all in one place)."
    )
    brief = read_multiline_terminal(click).strip()
    if not brief:
        click.echo("Error: research brief is required.", err=True)
        raise SystemExit(1)

    pcfg = ProjectConfig(research_idea=brief, preferences="")

    try:
        root = init_project_at(project_dir, pcfg, overwrite=overwrite)
    except LabConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"\nProject initialized at {root}")
    click.echo("Run `lab` to start the console.")
    click.echo(
        f"Optional: add project-specific preferences under [project] in {root / 'config.toml'}."
    )


if __name__ == "__main__":
    main()
