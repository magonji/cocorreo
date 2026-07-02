from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from . import db, fix_dates, importer, keystore
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


def _read_passphrase_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    # We allow a trailing newline (common when editing with text editors); the rest is kept as-is.
    passphrase = raw.rstrip("\r\n")
    if not passphrase:
        raise keystore.KeystoreError(f"the file {path} is empty")
    return passphrase


@app.command("init")
def init_cmd(
    data_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory where the database, attachments and configuration will be stored. Created if it doesn't exist.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = Path("data"),
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Reads the passphrase from this file (mode 600 recommended) instead of prompting via TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Initialises a new cocorreo archive: asks for a passphrase and creates the empty encrypted database."""
    if keystore.is_initialised(data_dir):
        console.print(f"[red]An initialised archive already exists at[/red] {data_dir}")
        console.print("If you want to start from scratch, delete that directory manually first.")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Initialising cocorreo archive at[/cyan] {data_dir}")
    if passphrase_file is None:
        console.print(
            "[dim]The passphrase will not be stored on disk. You'll have to enter it every time "
            "you start the service. Keep it safe.[/dim]\n"
        )
    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=True)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Deriving master key (scrypt)…", spinner="dots"):
        ks = keystore.initialise(data_dir, passphrase)

    with console.status("Creating database schema…", spinner="dots"):
        with db.connect(ks.db_path, ks.keys) as conn:
            db.init_schema(conn)

    console.print(f"[green]✓[/green] Configuration created at {ks.data_dir / '.cocorreo-config.json'}")
    console.print(f"[green]✓[/green] Database initialised at {ks.db_path}")
    if db.HAS_SQLCIPHER:
        console.print(f"[green]✓[/green] Database encrypted with SQLCipher (key derived in memory)")
    else:
        console.print(
            "[yellow]⚠[/yellow]  SQLCipher not available on this platform "
            "→ the database uses stdlib SQLite [bold]unencrypted[/bold]."
        )
        console.print(
            "   [dim]Attachments are still encrypted regardless. On the Raspberry Pi (Linux) "
            "the database will be encrypted automatically.[/dim]"
        )


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
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Reads the passphrase from this file (mode 600 recommended) instead of prompting via TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Phase 2: imports the profile's mbox files into the encrypted database (idempotent)."""
    if not keystore.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        console.print(f"Run this first: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=False)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Unlocking archive (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]incorrect passphrase[/red]")
            raise typer.Exit(code=1)

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
        f"[cyan]Destination[/cyan]: {ks.db_path}\n"
        + (f"[cyan]Limit[/cyan]:      {limit:,} messages\n" if limit else "")
        + (f"[cyan]Accounts[/cyan]:   {sorted(account_filter)}\n" if account_filter else "")
    )

    with db.connect(ks.db_path, ks.keys) as conn:
        db.init_schema(conn)
        imp = importer.Importer(ks, conn, profile, console)
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
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Reads the passphrase from this file instead of prompting via TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Starts the local API server (FastAPI + uvicorn)."""
    if not keystore.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        console.print(f"Run this first: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=False)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Unlocking archive (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]incorrect passphrase[/red]")
            raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Archive unlocked: {ks.db_path}")
    console.print(f"[cyan]Serving at[/cyan] [bold]http://{host}:{port}[/bold]")
    console.print(f"[dim]Interactive docs: http://{host}:{port}/docs[/dim]\n")

    from .api import create_app
    import uvicorn

    app_instance = create_app(ks)
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
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Reads the passphrase from this file instead of prompting via TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Fills in `date_utc` for messages with an epoch date using the first Received header."""
    if not keystore.is_initialised(data_dir):
        console.print(f"[red]{data_dir} is not initialised.[/red]")
        raise typer.Exit(code=1)

    try:
        passphrase = (
            _read_passphrase_file(passphrase_file)
            if passphrase_file is not None
            else keystore.prompt_passphrase(confirm=False)
        )
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Unlocking archive (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]incorrect passphrase[/red]")
            raise typer.Exit(code=1)

    with console.status("Repairing dates from Received headers…", spinner="dots"):
        with db.connect(ks.db_path, ks.keys) as conn:
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
