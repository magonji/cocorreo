from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from . import db, fix_dates, importer, keystore
from .discover import discover

app = typer.Typer(
    name="cocorreo",
    help="Archivo personal de correo: importa, indexa y busca tus mbox/IMAP.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _root() -> None:
    """Punto de entrada (forzamos subcomandos para que el CLI sea estable
    aunque solo haya uno definido)."""


def _read_passphrase_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    # Permitimos newline trailing (común al editar con editores); el resto se respeta.
    passphrase = raw.rstrip("\r\n")
    if not passphrase:
        raise keystore.KeystoreError(f"el archivo {path} está vacío")
    return passphrase


@app.command("init")
def init_cmd(
    data_dir: Annotated[
        Path,
        typer.Argument(
            help="Directorio donde se guardarán BD, adjuntos y configuración. Se creará si no existe.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = Path("data"),
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Lee la passphrase desde este archivo (modo 600 recomendado) en vez de pedirla por TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Inicializa un archivo cocorreo nuevo: pide passphrase y crea la BD cifrada vacía."""
    if keystore.is_initialized(data_dir):
        console.print(f"[red]Ya existe un archivo inicializado en[/red] {data_dir}")
        console.print("Si quieres empezar de cero, borra manualmente ese directorio primero.")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Inicializando archivo cocorreo en[/cyan] {data_dir}")
    if passphrase_file is None:
        console.print(
            "[dim]La passphrase no se guardará en disco. Tendrás que introducirla cada vez "
            "que arranques el servicio. Guárdala bien.[/dim]\n"
        )
    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=True)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Derivando clave maestra (scrypt)…", spinner="dots"):
        ks = keystore.initialize(data_dir, passphrase)

    with console.status("Creando esquema de la BD…", spinner="dots"):
        with db.connect(ks.db_path, ks.keys) as conn:
            db.init_schema(conn)

    console.print(f"[green]✓[/green] Configuración creada en {ks.data_dir / '.cocorreo-config.json'}")
    console.print(f"[green]✓[/green] BD inicializada en {ks.db_path}")
    if db.HAS_SQLCIPHER:
        console.print(f"[green]✓[/green] BD cifrada con SQLCipher (clave derivada en memoria)")
    else:
        console.print(
            "[yellow]⚠[/yellow]  SQLCipher no disponible en esta plataforma "
            "→ la BD usa SQLite stdlib [bold]sin cifrar[/bold]."
        )
        console.print(
            "   [dim]Los adjuntos van cifrados igualmente. En la Raspberry Pi (Linux) "
            "la BD se cifrará automáticamente.[/dim]"
        )


@app.command("import")
def import_cmd(
    profile: Annotated[
        Path,
        typer.Argument(
            help="Ruta al perfil de Thunderbird (debe contener Mail/ y/o ImapMail/).",
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
            help="Directorio del archivo cocorreo (donde está la BD y los adjuntos).",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
    limit: Annotated[
        Optional[int],
        typer.Option(
            "--limit", "-n",
            help="Detiene la importación tras N mensajes procesados. Útil para pruebas.",
        ),
    ] = None,
    accounts: Annotated[
        Optional[str],
        typer.Option(
            "--accounts", "-a",
            help="Coma-separado: nombres de cuenta/sección a incluir (ej. 'imap.gmail-3.com,Local Folders'). "
                 "Por defecto importa todas.",
        ),
    ] = None,
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Lee la passphrase desde este archivo (modo 600 recomendado) en vez de pedirla por TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Fase 2: importa los mbox del perfil a la BD cifrada (idempotente)."""
    if not keystore.is_initialized(data_dir):
        console.print(f"[red]{data_dir} no está inicializado.[/red]")
        console.print(f"Lanza primero: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=False)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Desbloqueando archivo (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]passphrase incorrecta[/red]")
            raise typer.Exit(code=1)

    account_filter: Optional[set[str]] = None
    if accounts:
        account_filter = {a.strip() for a in accounts.split(",") if a.strip()}

    candidates = importer.enumerate_candidates(profile, account_filter)
    if not candidates:
        console.print(f"[yellow]No se encontraron mbox candidatos[/yellow]"
                      + (f" con filtro accounts={account_filter}" if account_filter else "")
                      + f" bajo {profile}")
        raise typer.Exit(code=1)

    console.print(
        f"[cyan]Importando[/cyan] {len(candidates)} archivos mbox de [bold]{profile}[/bold]\n"
        f"[cyan]Destino[/cyan]:    {ks.db_path}\n"
        + (f"[cyan]Límite[/cyan]:     {limit:,} mensajes\n" if limit else "")
        + (f"[cyan]Cuentas[/cyan]:    {sorted(account_filter)}\n" if account_filter else "")
    )

    with db.connect(ks.db_path, ks.keys) as conn:
        db.init_schema(conn)
        imp = importer.Importer(ks, conn, profile, console)
        stats = imp.run(candidates, limit=limit)

    console.print(
        "\n[bold green]Importación finalizada[/bold green]\n"
        f"  Mensajes nuevos:      [bold]{stats.messages_imported:,}[/bold]\n"
        f"  Duplicados enlazados: {stats.messages_duplicate_links:,}\n"
        f"  Errores:              {stats.messages_errors:,}\n"
        f"  Adjuntos nuevos:      {stats.attachments_imported:,}\n"
        f"  Adjuntos deduplic.:   {stats.attachments_dedup_hits:,}\n"
        f"  Archivos procesados:  {stats.files_processed:,}"
    )


@app.command("serve")
def serve_cmd(
    data_dir: Annotated[
        Path,
        typer.Option(
            "--data-dir", "-d",
            help="Directorio del archivo cocorreo.",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
    host: Annotated[
        str,
        typer.Option("--host", "-h", help="Interfaz a escuchar."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Puerto."),
    ] = 8000,
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Lee la passphrase desde este archivo en vez de pedirla por TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Arranca el servidor API local (FastAPI + uvicorn)."""
    if not keystore.is_initialized(data_dir):
        console.print(f"[red]{data_dir} no está inicializado.[/red]")
        console.print(f"Lanza primero: [bold]cocorreo init {data_dir}[/bold]")
        raise typer.Exit(code=1)

    try:
        if passphrase_file is not None:
            passphrase = _read_passphrase_file(passphrase_file)
        else:
            passphrase = keystore.prompt_passphrase(confirm=False)
    except keystore.KeystoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    with console.status("Desbloqueando archivo (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]passphrase incorrecta[/red]")
            raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Archivo desbloqueado: {ks.db_path}")
    console.print(f"[cyan]Sirviendo en[/cyan] [bold]http://{host}:{port}[/bold]")
    console.print(f"[dim]Docs interactivas: http://{host}:{port}/docs[/dim]\n")

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
            help="Directorio del archivo cocorreo.",
            file_okay=False, dir_okay=True, resolve_path=True,
        ),
    ] = Path("data"),
    passphrase_file: Annotated[
        Optional[Path],
        typer.Option(
            "--passphrase-file",
            help="Lee la passphrase desde este archivo en vez de pedirla por TTY.",
            exists=True, file_okay=True, dir_okay=False, resolve_path=True,
        ),
    ] = None,
) -> None:
    """Rellena `date_utc` en mensajes con fecha epoch usando el primer header Received."""
    if not keystore.is_initialized(data_dir):
        console.print(f"[red]{data_dir} no está inicializado.[/red]")
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

    with console.status("Desbloqueando archivo (scrypt)…", spinner="dots"):
        try:
            ks = keystore.unlock(data_dir, passphrase)
        except keystore.WrongPassphrase:
            console.print("[red]passphrase incorrecta[/red]")
            raise typer.Exit(code=1)

    with console.status("Reparando fechas desde headers Received…", spinner="dots"):
        with db.connect(ks.db_path, ks.keys) as conn:
            reviewed, fixed = fix_dates.fix_epoch_dates(conn)

    console.print(
        f"[green]✓[/green] Mensajes con fecha epoch revisados: [bold]{reviewed:,}[/bold]\n"
        f"[green]✓[/green] Reparados con éxito:              [bold]{fixed:,}[/bold]\n"
        f"[dim]  Restantes (sin Received parseable):  {reviewed - fixed:,}[/dim]"
    )


@app.command("discover")
def discover_cmd(
    profile: Annotated[
        Path,
        typer.Argument(
            help="Ruta al perfil de Thunderbird (debe contener Mail/ y/o ImapMail/).",
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
            help="Escribe un reporte detallado en este archivo JSON.",
        ),
    ] = None,
) -> None:
    """Fase 1: descubre y caracteriza los mbox del perfil sin importar nada."""
    discover(profile, output_json=json_out)
