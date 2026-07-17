"""OpenAI Secure MCP Tunnel launcher."""

import os
import re
import shlex
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Never

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from anki_connect_server.config import Config

TUNNEL_CLIENT_DOWNLOAD_URL = "https://github.com/openai/tunnel-client/releases/latest"
_TUNNEL_ID_PATTERN = re.compile(r"^tunnel_[a-z0-9]{32}$")

type ExecFunction = Callable[[str, list[str], dict[str, str]], Never]


def _missing_tunnel_id() -> str:
    raise ValueError("CONTROL_PLANE_TUNNEL_ID is required")


def _missing_api_key() -> SecretStr:
    raise ValueError("CONTROL_PLANE_API_KEY is required")


class TunnelConfig(BaseSettings):
    """Configuration consumed by OpenAI's tunnel-client process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    tunnel_id: str = Field(
        default_factory=_missing_tunnel_id,
        validation_alias="CONTROL_PLANE_TUNNEL_ID",
    )
    api_key: SecretStr = Field(
        default_factory=_missing_api_key,
        validation_alias="CONTROL_PLANE_API_KEY",
    )
    client_path: str = Field(
        default="tunnel-client",
        validation_alias="TUNNEL_CLIENT_PATH",
    )

    @field_validator("tunnel_id")
    @classmethod
    def validate_tunnel_id(cls, value: str) -> str:
        if not _TUNNEL_ID_PATTERN.fullmatch(value):
            raise ValueError("tunnel ID must match tunnel_<32 lowercase letters or digits>")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("CONTROL_PLANE_API_KEY must not be empty")
        return value

    @field_validator("client_path")
    @classmethod
    def validate_client_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("TUNNEL_CLIENT_PATH must not be empty")
        return value


def build_tunnel_environment(
    tunnel_settings: TunnelConfig,
    anki_settings: Config,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the child environment without placing secrets in process arguments."""
    environment = dict(os.environ if base_environment is None else base_environment)
    environment.update(
        {
            "CONTROL_PLANE_TUNNEL_ID": tunnel_settings.tunnel_id,
            "CONTROL_PLANE_API_KEY": tunnel_settings.api_key.get_secret_value(),
            "ANKICONNECT_COLLECTION_PATH": str(anki_settings.collection_path),
            "ANKICONNECT_PORT": str(anki_settings.port),
            "ANKICONNECT_BIND": anki_settings.bind,
            "ANKICONNECT_FULL_UPLOAD": str(anki_settings.full_upload).lower(),
        }
    )
    optional_anki_settings = {
        "ANKICONNECT_ANKIWEB_USER": anki_settings.ankiweb_user,
        "ANKICONNECT_ANKIWEB_PASS": anki_settings.ankiweb_pass,
        "ANKICONNECT_ANKIWEB_URL": anki_settings.ankiweb_url,
    }
    environment.update(
        {name: value for name, value in optional_anki_settings.items() if value is not None}
    )
    return environment


def build_tunnel_command(
    tunnel_client: str,
    mcp_command: Sequence[str],
    *,
    doctor: bool = False,
) -> list[str]:
    """Build a tunnel-client command for this server's stdio MCP transport."""
    if not mcp_command:
        raise ValueError("MCP command must not be empty")

    command = [
        tunnel_client,
        "doctor" if doctor else "run",
        "--control-plane.api-key",
        "env:CONTROL_PLANE_API_KEY",
        "--mcp-command",
        shlex.join(mcp_command),
    ]
    if doctor:
        command.append("--explain")
    return command


def _resolve_executable(command: str, *, purpose: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        if purpose == "tunnel-client":
            raise RuntimeError(
                "tunnel-client was not found; download the official release from "
                f"{TUNNEL_CLIENT_DOWNLOAD_URL} or set TUNNEL_CLIENT_PATH"
            )
        raise RuntimeError("anki-connect-server was not found on PATH")
    return str(Path(executable).resolve())


def run_tunnel(
    *,
    doctor: bool = False,
    tunnel_settings: TunnelConfig | None = None,
    anki_settings: Config | None = None,
    tunnel_client: str | None = None,
    mcp_executable: str | None = None,
    base_environment: Mapping[str, str] | None = None,
    exec_function: ExecFunction = os.execvpe,
) -> Never:
    """Replace this process with tunnel-client supervising the stdio MCP server."""
    resolved_tunnel_settings = tunnel_settings or TunnelConfig()
    resolved_anki_settings = anki_settings or Config()
    resolved_tunnel_client = tunnel_client or _resolve_executable(
        resolved_tunnel_settings.client_path,
        purpose="tunnel-client",
    )
    resolved_mcp_executable = mcp_executable or _resolve_executable(
        "anki-connect-server",
        purpose="MCP server",
    )
    command = build_tunnel_command(
        resolved_tunnel_client,
        [resolved_mcp_executable, "mcp"],
        doctor=doctor,
    )
    environment = build_tunnel_environment(
        resolved_tunnel_settings,
        resolved_anki_settings,
        base_environment,
    )
    exec_function(resolved_tunnel_client, command, environment)
