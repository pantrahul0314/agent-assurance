from __future__ import annotations

from pathlib import Path

import typer

from assure_contracts.config import load_config
from assure_runner.doctor import run_doctor
from assure_runner.engine import run_suite
from assure_runner.upload import upload_results

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def doctor(
    config: Path = typer.Option(Path("assure.yaml"), "--config", exists=True),
) -> None:
    cfg = load_config(config)
    ok, errors = _run(run_doctor(cfg))
    if ok:
        typer.echo("doctor: ok")
        raise typer.Exit(0)
    for error in errors:
        typer.echo(f"doctor: {error}")
    raise typer.Exit(3)


@app.command()
def run(
    config: Path = typer.Option(Path("assure.yaml"), "--config", exists=True),
    suite: Path = typer.Option(Path("suites/support_v1"), "--suite"),
    output: Path = typer.Option(Path("reports"), "--output"),
) -> None:
    cfg = load_config(config)
    _summary, _manifest, exit_code = _run(run_suite(cfg, suite, output))
    typer.echo(f"wrote reports to {output}")
    raise typer.Exit(exit_code)


@app.command()
def upload(
    config: Path = typer.Option(Path("assure.yaml"), "--config", exists=True),
    manifest: Path = typer.Option(..., "--manifest", exists=True),
    summary: Path = typer.Option(..., "--summary", exists=True),
) -> None:
    cfg = load_config(config)
    result = _run(upload_results(cfg, manifest, summary))
    typer.echo(f"uploaded run {result.get('id', '')} gate={result.get('gate', {}).get('status')}")


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
