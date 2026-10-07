"""Stage-friendly terminal trace: every tool call, the SQL++ behind it, and what came back."""

import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console(highlight=False)
SHOW_SQL = False  # /sql toggles; off on stage so the audience follows the result cards
QUIET = False  # the web console renders events itself; nothing is printed


def out(*args, **kwargs) -> None:
    if QUIET:
        return
    console.print(*args, **kwargs)


def ask(prompt: str) -> str:
    text = console.input(prompt).strip()
    if not sys.stdin.isatty():
        console.print(f"[dim]{text}[/]")
    return text


def banner(title: str, subtitle: str = "") -> None:
    out(
        Panel(
            f"[bold]{title}[/]\n[dim]{subtitle}[/]" if subtitle else f"[bold]{title}[/]",
            border_style="cyan",
            expand=False,
        )
    )


def tool_call(name: str, args: dict) -> None:
    shown = {k: v for k, v in args.items() if k not in ("bucket_name", "scope_name", "named_parameters")}
    detail = f" [dim]{json.dumps(shown, ensure_ascii=False)[:120]}[/]" if SHOW_SQL else ""
    out(f"\n[dim]⚙ the agent calls[/] [bold magenta]{name}[/]{detail}")


def card(headline: str, footnote: str = "", color: str = "cyan") -> None:
    """One big result per beat: what the audience should read."""
    body = f"[bold]{headline}[/]" + (f"\n[dim]{footnote}[/]" if footnote else "")
    out(Panel(body, border_style=color, padding=(1, 3), expand=True))


def sql(label: str, statement: str, via: str = "MCP · run_sql_plus_plus_query (read-only)") -> None:
    if SHOW_SQL:
        out(f"  [dim]{label} → {via}[/]")
        out(Syntax(statement, "sql", theme="ansi_dark", word_wrap=True, padding=(0, 2)))


def rows(data, max_rows: int = 6) -> None:
    if not SHOW_SQL and not isinstance(data, str):
        return
    if isinstance(data, str):
        out(f"  [bold red]✗ {data}[/]")
        return
    if not data:
        out("  [dim](no rows)[/]")
        return
    cols = list(data[0].keys())
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    for c in cols:
        t.add_column(c, overflow="fold", max_width=70)
    for r in data[:max_rows]:
        t.add_row(*[_fmt(r.get(c)) for c in cols])
    out(t)
    if len(data) > max_rows:
        out(f"  [dim]… {len(data) - max_rows} more[/]")


def _fmt(v) -> str:
    if isinstance(v, list):
        return "\n".join(f"• {x}" for x in v) if all(isinstance(x, str) for x in v) else json.dumps(v)
    return "" if v is None else str(v)


def refused(msg: str) -> None:
    card("🛑  Refused by the data layer: the MCP server is read‑only", msg, "red")


def answer(text: str) -> None:
    """The model's own words: kept short and secondary to the result card."""
    text = " ".join(text.strip().split())
    out(f"[dim]💬 Quality agent:[/] {text[:220]}{'…' if len(text) > 220 else ''}")
