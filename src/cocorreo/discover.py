"""Fase 1 — Descubrimiento.

Recorre un perfil de Thunderbird, identifica los archivos mbox dentro de
`Mail/` y `ImapMail/`, cuenta mensajes en modo streaming y produce un
resumen por cuenta + un JSON detallado opcional. No escribe nada en los
datos originales (lectura pura).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

# Extensiones que nunca son mbox: índices Thunderbird, metadata varia, BDs auxiliares.
SKIP_SUFFIXES = {
    ".msf", ".dat", ".html", ".bak", ".json", ".sqlite", ".mab",
    ".sqlite-shm", ".sqlite-wal", ".db", ".ini", ".txt", ".log",
}

# Nombres exactos a saltar dentro de los árboles de correo.
SKIP_NAMES = {
    "filterlog.html", "msgFilterRules.dat", ".parentlock", ".DS_Store",
}

FROM_PREFIX = b"From "
HEADER_RE = re.compile(rb"^(From|To|Subject|Date|Message-ID|Received):", re.IGNORECASE | re.MULTILINE)


def decode_imap_utf7(s: str) -> str:
    """Decodifica el UTF-7 modificado que Thunderbird usa en nombres IMAP.

    Ejemplos:
        'Educaci&APM-n'  -> 'Educación'
        'Boletines &- newsletters' -> 'Boletines & newsletters'
    """
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.find("-", i + 1)
            if j == -1:
                out.append(s[i:])
                break
            chunk = s[i + 1 : j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:
                    out.append(s[i : j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


@dataclass
class MboxInfo:
    path: str
    rel_path: str
    account: str
    section: str           # "Local" o "IMAP"
    display_path: str      # ruta relativa con nombres decodificados
    size_bytes: int
    mtime: str
    message_count: int
    valid_mbox: bool
    warnings: list[str] = field(default_factory=list)


def is_mbox_candidate(p: Path) -> bool:
    """Heurística: archivos sin extensión y no marcados como metadatos."""
    name = p.name
    if name in SKIP_NAMES:
        return False
    if name.startswith("._"):  # AppleDouble (macOS metadata)
        return False
    if name.startswith("."):
        return False
    if p.suffix.lower() in SKIP_SUFFIXES:
        return False
    if p.suffix != "":
        return False
    return True


def _walk(account_dir: Path) -> Iterator[Path]:
    """Recorre recursivamente un árbol de cuenta, entrando en .sbd y subcarpetas."""
    try:
        children = sorted(account_dir.iterdir())
    except (PermissionError, OSError):
        return
    for child in children:
        if child.is_dir():
            yield from _walk(child)
        elif child.is_file() and is_mbox_candidate(child):
            yield child


def iter_mbox_candidates(root: Path) -> Iterator[tuple[Path, str, str]]:
    """Genera (path, cuenta, sección) para cada candidato mbox bajo Mail/ e ImapMail/."""
    for section_dirname, section_label in (("Mail", "Local"), ("ImapMail", "IMAP")):
        section_root = root / section_dirname
        if not section_root.is_dir():
            continue
        for account_dir in sorted(section_root.iterdir()):
            if not account_dir.is_dir():
                continue
            account_display = decode_imap_utf7(account_dir.name)
            for path in _walk(account_dir):
                yield path, account_display, section_label


def count_messages(
    path: Path,
    progress: Optional[Progress] = None,
    task_id=None,
) -> tuple[int, bool, list[str]]:
    """Cuenta líneas que empiezan por 'From ' (separador mbox-O). Streaming, RAM constante."""
    warnings: list[str] = []
    size = path.stat().st_size
    if size == 0:
        return 0, True, []

    count = 0
    valid = True
    with path.open("rb") as f:
        first = f.read(512)
        if not first.startswith(FROM_PREFIX):
            if HEADER_RE.search(first):
                warnings.append("no empieza por 'From ' pero contiene headers de email")
                valid = False
            else:
                warnings.append("no parece un mbox: sin separador 'From ' ni headers reconocibles")
                return 0, False, warnings
        f.seek(0)

        bytes_read = 0
        lines_since_update = 0
        for line in f:
            bytes_read += len(line)
            if line.startswith(FROM_PREFIX):
                count += 1
            lines_since_update += 1
            if progress is not None and task_id is not None and lines_since_update >= 200_000:
                progress.update(task_id, completed=bytes_read)
                lines_since_update = 0
        if progress is not None and task_id is not None:
            progress.update(task_id, completed=size)
    return count, valid, warnings


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def discover(root: Path, output_json: Optional[Path] = None) -> dict:
    console = Console()
    if not (root / "Mail").exists() and not (root / "ImapMail").exists():
        console.print(f"[red]No se encontró Mail/ ni ImapMail/ en {root}[/red]")
        raise SystemExit(2)

    console.print(f"[cyan]Escaneando perfil:[/cyan] {root}")
    candidates = list(iter_mbox_candidates(root))
    total_bytes = sum(p.stat().st_size for p, _, _ in candidates)
    console.print(
        f"Encontrados [bold]{len(candidates)}[/bold] archivos candidatos, "
        f"[bold]{human_bytes(total_bytes)}[/bold] totales\n"
    )

    results: list[MboxInfo] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[cyan]{task.fields[name]}"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        outer = progress.add_task("Procesando", total=len(candidates), name="")
        for path, account, section in candidates:
            stat = path.stat()
            display_parts = [decode_imap_utf7(part) for part in path.relative_to(root).parts]
            display = "/".join(display_parts)
            progress.update(outer, name=display)

            size = stat.st_size
            warnings: list[str] = []
            if size > 500 * 1024 * 1024:
                warnings.append(f"archivo muy grande ({human_bytes(size)})")

            if size > 100 * 1024 * 1024:
                inner = progress.add_task("  ↳ contando", total=size, name=path.name)
                count, valid, w = count_messages(path, progress, inner)
                progress.remove_task(inner)
            else:
                count, valid, w = count_messages(path)
            warnings.extend(w)

            results.append(
                MboxInfo(
                    path=str(path),
                    rel_path=str(path.relative_to(root)),
                    account=account,
                    section=section,
                    display_path=display,
                    size_bytes=size,
                    mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    message_count=count,
                    valid_mbox=valid,
                    warnings=warnings,
                )
            )
            progress.advance(outer)

    _print_summary(results, console)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "root": str(root),
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
            "total_files": len(results),
            "total_messages": sum(r.message_count for r in results),
            "total_bytes": sum(r.size_bytes for r in results),
            "files": [asdict(r) for r in results],
        }
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        console.print(f"\n[green]Reporte JSON escrito en[/green] {output_json}")

    return {
        "files": results,
        "total_messages": sum(r.message_count for r in results),
        "total_bytes": sum(r.size_bytes for r in results),
    }


def _print_summary(results: list[MboxInfo], console: Console) -> None:
    accounts: dict[tuple[str, str], dict] = {}
    for r in results:
        key = (r.section, r.account)
        agg = accounts.setdefault(key, {"files": 0, "messages": 0, "bytes": 0})
        agg["files"] += 1
        agg["messages"] += r.message_count
        agg["bytes"] += r.size_bytes

    table = Table(title="Resumen por cuenta", header_style="bold cyan")
    table.add_column("Sección")
    table.add_column("Cuenta / Categoría")
    table.add_column("Archivos", justify="right")
    table.add_column("Mensajes", justify="right")
    table.add_column("Tamaño", justify="right")
    for (section, account), agg in sorted(accounts.items()):
        table.add_row(
            section,
            account,
            f"{agg['files']:,}",
            f"{agg['messages']:,}",
            human_bytes(agg["bytes"]),
        )
    table.add_section()
    total_files = sum(a["files"] for a in accounts.values())
    total_msgs = sum(a["messages"] for a in accounts.values())
    total_bytes = sum(a["bytes"] for a in accounts.values())
    table.add_row(
        "[bold]TOTAL[/bold]", "",
        f"[bold]{total_files:,}[/bold]",
        f"[bold]{total_msgs:,}[/bold]",
        f"[bold]{human_bytes(total_bytes)}[/bold]",
    )
    console.print(table)

    top = sorted(results, key=lambda r: r.message_count, reverse=True)[:20]
    tt = Table(title="Top 20 carpetas por número de mensajes", header_style="bold cyan")
    tt.add_column("Ruta", overflow="fold")
    tt.add_column("Mensajes", justify="right")
    tt.add_column("Tamaño", justify="right")
    for r in top:
        if r.message_count == 0:
            continue
        tt.add_row(r.display_path, f"{r.message_count:,}", human_bytes(r.size_bytes))
    console.print(tt)

    flagged = [r for r in results if r.warnings]
    if flagged:
        wt = Table(title=f"Avisos ({len(flagged)} archivos)", header_style="bold yellow")
        wt.add_column("Ruta", overflow="fold")
        wt.add_column("Avisos")
        for r in flagged:
            wt.add_row(r.display_path, "; ".join(r.warnings))
        console.print(wt)
