from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from . import db, fix_dates, importer
from .discover import discover

app = typer.Typer(
    name="cocorreo",
    help="Personal email archive: import, index and search your mbox/IMAP.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _root() -> None:
    """Entry point (we force subcommands so the CLI stays stable
    even when only one is defined)."""


@app.command("init")
def init_cmd(
    data_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory where the database and attachments will be stored. Created if it doesn't exist.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = Path("data"),
) -> None:
    """Initialises a new cocorreo archive: creates the empty database."""
    if db.is_initialised(data_dir):
        console.print(f"[red]An initialised archive already exists at[/red] {data_dir}")
        console.print("If you want to start from scratch, delete that directory manually first.")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Initialising cocorreo archive at[/cyan] {data_dir}")
    archive = db.initialise_archive(data_dir)

    with console.status("Creating database schema…", spinner="dots"):
        with db.connect(archive.db_path) as conn:
            db.init_schema(conn)

    console.print(f"[green]✓[/green] Database initialised at {archive.db_path}")


@app.command("import")
def import_cmd(
    profile: Annotated[
        Path,
        typer.Argument(
            help="Path to the Thunderbird profile (must contain Mail/ and/or ImapMail/).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    data_dir: Annotated[
        Path,
        typer.Option(
            "--data-dir", "-d",
            help="Directory of the cocorreo archive (where the database and attachments live).",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
    limit: Annotated[
        Optional[int],
        typer.Option(
            "--limit", "-n",
            help="Stops the import after N messages have been processed. Useful for testing.",
        ),
    ] = None,
    accounts: Annotated[
        Optional[str],
        typer.Option(
            "--accounts", "-a",
            help="Comma-separated: account/section names to include (e.g. 'imap.gmail-3.com,Local Folders'). "
                 "Imports all by default.",
        ),
    ] = None,
) -> None:
    """Phase 2: imports the profile's mbox files into the database (idempotent)."""
    if not db.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        console.print(f"Run this first: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    archive = db.open_archive(data_dir)

    account_filter: Optional[set[str]] = None
    if accounts:
        account_filter = {a.strip() for a in accounts.split(",") if a.strip()}

    candidates = importer.enumerate_candidates(profile, account_filter)
    if not candidates:
        console.print(f"[yellow]No candidate mbox files found[/yellow]"
                      + (f" with filter accounts={account_filter}" if account_filter else "")
                      + f" under {profile}")
        raise typer.Exit(code=1)

    console.print(
        f"[cyan]Importing[/cyan] {len(candidates)} mbox files from [bold]{profile}[/bold]\n"
        f"[cyan]Destination[/cyan]: {archive.db_path}\n"
        + (f"[cyan]Limit[/cyan]:      {limit:,} messages\n" if limit else "")
        + (f"[cyan]Accounts[/cyan]:   {sorted(account_filter)}\n" if account_filter else "")
    )

    with db.connect(archive.db_path) as conn:
        db.init_schema(conn)
        imp = importer.Importer(archive, conn, profile, console)
        stats = imp.run(candidates, limit=limit)

    console.print(
        "\n[bold green]Import finished[/bold green]\n"
        f"  New messages:         [bold]{stats.messages_imported:,}[/bold]\n"
        f"  Duplicates linked:    {stats.messages_duplicate_links:,}\n"
        f"  Errors:               {stats.messages_errors:,}\n"
        f"  New attachments:      {stats.attachments_imported:,}\n"
        f"  Deduplicated attachments: {stats.attachments_dedup_hits:,}\n"
        f"  Files processed:      {stats.files_processed:,}"
    )


@app.command("serve")
def serve_cmd(
    data_dir: Annotated[
        Path,
        typer.Option(
            "--data-dir", "-d",
            help="Directory of the cocorreo archive.",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
    host: Annotated[
        str,
        typer.Option("--host", "-h", help="Interface to listen on."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port."),
    ] = 8000,
) -> None:
    """Starts the local API server (FastAPI + uvicorn)."""
    if not db.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        console.print(f"Run this first: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    archive = db.open_archive(data_dir)

    console.print(f"[green]✓[/green] Archive: {archive.db_path}")
    console.print(f"[cyan]Serving at[/cyan] [bold]http://{host}:{port}[/bold]")
    console.print(f"[dim]Interactive docs: http://{host}:{port}/docs[/dim]\n")

    from .api import create_app
    import uvicorn

    app_instance = create_app(archive)
    uvicorn.run(app_instance, host=host, port=port, log_level="info", access_log=False)


@app.command("fix-dates")
def fix_dates_cmd(
    data_dir: Annotated[
        Path,
        typer.Option(
            "--data-dir", "-d",
            help="Directory of the cocorreo archive.",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
) -> None:
    """Fills in `date_utc` for messages with an epoch date using the first Received header."""
    if not db.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        raise typer.Exit(code=1)

    archive = db.open_archive(data_dir)

    with console.status("Repairing dates from Received headers…", spinner="dots"):
        with db.connect(archive.db_path) as conn:
            reviewed, fixed = fix_dates.fix_epoch_dates(conn)

    console.print(
        f"[green]✓[/green] Messages with epoch date reviewed: [bold]{reviewed:,}[/bold]\n"
        f"[green]✓[/green] Successfully repaired:            [bold]{fixed:,}[/bold]\n"
        f"[dim]  Remaining (no parseable Received):    {reviewed - fixed:,}[/dim]"
    )


@app.command("discover")
def discover_cmd(
    profile: Annotated[
        Path,
        typer.Argument(
            help="Path to the Thunderbird profile (must contain Mail/ and/or ImapMail/).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    json_out: Annotated[
        Optional[Path],
        typer.Option(
            "--json",
            "-j",
            help="Writes a detailed report to this JSON file.",
        ),
    ] = None,
) -> None:
    """Phase 1: discovers and characterises the profile's mbox files without importing anything."""
    discover(profile, output_json=json_out)
