from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never, cast

import pytest
from pydantic import SecretStr

from anki_connect_server.config import Config
from anki_connect_server.tunnel import (
    TunnelConfig,
    build_tunnel_command,
    build_tunnel_environment,
    run_tunnel,
)

TUNNEL_ID = "tunnel_0123456789abcdef0123456789abcdef"


def _tunnel_settings() -> TunnelConfig:
    return TunnelConfig(tunnel_id=TUNNEL_ID, api_key=SecretStr("runtime-secret"))


def test_tunnel_config_loads_existing_environment_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CONTROL_PLANE_TUNNEL_ID", raising=False)
    monkeypatch.delenv("CONTROL_PLANE_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        f"CONTROL_PLANE_TUNNEL_ID={TUNNEL_ID}\nCONTROL_PLANE_API_KEY=runtime-secret\n",
        encoding="utf-8",
    )

    settings = TunnelConfig()

    assert settings.tunnel_id == TUNNEL_ID
    assert settings.api_key.get_secret_value() == "runtime-secret"
    assert "runtime-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("environment_name", "message"),
    [
        ("CONTROL_PLANE_TUNNEL_ID", "CONTROL_PLANE_TUNNEL_ID is required"),
        ("CONTROL_PLANE_API_KEY", "CONTROL_PLANE_API_KEY is required"),
    ],
)
def test_tunnel_config_requires_credentials(
    environment_name: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONTROL_PLANE_TUNNEL_ID", TUNNEL_ID)
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "runtime-secret")
    monkeypatch.delenv(environment_name)

    with pytest.raises(ValueError, match=message):
        TunnelConfig()


def test_tunnel_config_rejects_invalid_tunnel_id() -> None:
    with pytest.raises(ValueError, match="tunnel ID must match"):
        TunnelConfig(tunnel_id="not-a-tunnel", api_key=SecretStr("runtime-secret"))


def test_tunnel_command_uses_stdio_and_an_environment_secret_reference() -> None:
    command = build_tunnel_command(
        "/usr/local/bin/tunnel-client",
        ["/path with spaces/anki-connect-server", "mcp"],
        doctor=True,
    )

    assert command == [
        "/usr/local/bin/tunnel-client",
        "doctor",
        "--control-plane.api-key",
        "env:CONTROL_PLANE_API_KEY",
        "--mcp-command",
        "'/path with spaces/anki-connect-server' mcp",
        "--explain",
    ]
    assert "runtime-secret" not in command


def test_tunnel_environment_forwards_tunnel_and_anki_settings(tmp_path: Path) -> None:
    environment = build_tunnel_environment(
        _tunnel_settings(),
        Config(
            collection_path=tmp_path / "collection.anki2",
            ankiweb_user="user@example.com",
            ankiweb_pass="anki-secret",
        ),
        {"PATH": "/usr/bin"},
    )

    assert environment == {
        "PATH": "/usr/bin",
        "CONTROL_PLANE_TUNNEL_ID": TUNNEL_ID,
        "CONTROL_PLANE_API_KEY": "runtime-secret",
        "ANKICONNECT_COLLECTION_PATH": str(tmp_path / "collection.anki2"),
        "ANKICONNECT_PORT": "8765",
        "ANKICONNECT_BIND": "127.0.0.1",
        "ANKICONNECT_ANKIWEB_USER": "user@example.com",
        "ANKICONNECT_ANKIWEB_PASS": "anki-secret",
    }


class ExecCalledError(Exception):
    pass


def test_run_tunnel_replaces_process_without_exposing_secret_in_arguments(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_exec(
        executable: str,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> Never:
        captured.update(
            executable=executable,
            command=list(command),
            environment=dict(environment),
        )
        raise ExecCalledError

    with pytest.raises(ExecCalledError):
        run_tunnel(
            tunnel_settings=_tunnel_settings(),
            anki_settings=Config(collection_path=tmp_path / "collection.anki2"),
            tunnel_client="/usr/local/bin/tunnel-client",
            mcp_executable="/usr/local/bin/anki-connect-server",
            base_environment={"PATH": "/usr/local/bin"},
            exec_function=fake_exec,
        )

    command = cast(list[str], captured["command"])
    environment = cast(dict[str, str], captured["environment"])
    assert captured["executable"] == "/usr/local/bin/tunnel-client"
    assert command[-1] == "/usr/local/bin/anki-connect-server mcp"
    assert "runtime-secret" not in command
    assert environment["CONTROL_PLANE_API_KEY"] == "runtime-secret"
