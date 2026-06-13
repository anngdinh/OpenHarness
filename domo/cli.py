"""domo CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(name="domo", help="Domain-assistant agent over A2A")


@app.command("serve")
def serve(
    host: Optional[str] = typer.Option(None, "--host", help="Bind host"),
    port: Optional[int] = typer.Option(None, "--port", help="Bind port"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Agent working directory"),
    model: Optional[str] = typer.Option(None, "--model", help="Model override"),
    public_url: Optional[str] = typer.Option(None, "--public-url", help="Advertised URL"),
) -> None:
    """Run the domo A2A server."""
    from openharness.a2a import A2AServerSettings, run_a2a_server

    from domo.agent import make_build_engine
    from domo.config import DomoConfig

    config = DomoConfig.from_env()
    if cwd:
        config = config.model_copy(update={"cwd": cwd})
    if model:
        config = config.model_copy(update={"model": model})

    a2a_settings = A2AServerSettings.from_env().model_copy(
        update={
            **({"host": host} if host is not None else {}),
            **({"port": port} if port is not None else {}),
            **({"public_url_override": public_url} if public_url else {}),
            "agent_name": "domo",
            "agent_description": "Domain assistant: product info, datasources, infra status.",
        }
    )
    run_a2a_server(
        a2a_settings=a2a_settings,
        cwd=config.cwd or str(Path.cwd()),
        build_engine=make_build_engine(config),
    )


@app.command("doctor")
def doctor() -> None:
    """Print resolved domo + A2A configuration (no server started)."""
    from openharness.a2a import A2AServerSettings

    from domo.config import DomoConfig

    config = DomoConfig.from_env()
    a2a = A2AServerSettings.from_env()
    typer.echo(f"model={config.model} cwd={config.cwd} permission_mode={config.permission_mode}")
    typer.echo(f"datasources={[d.name for d in config.datasources]}")
    typer.echo(f"a2a host={a2a.host} port={a2a.port} auth={'set' if a2a.auth_token else 'open'}")


if __name__ == "__main__":
    app()
