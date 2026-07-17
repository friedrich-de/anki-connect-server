FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Pin uv while keeping the project-managed Ruff version from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

ARG TARGETARCH
COPY scripts/install_tunnel_client.py /tmp/install_tunnel_client.py
RUN python /tmp/install_tunnel_client.py --architecture "${TARGETARCH}" \
    && rm /tmp/install_tunnel_client.py

# The base image's unused Yarn repository currently has an expired signing key.
RUN rm -f /etc/apt/sources.list.d/yarn.list

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bubblewrap \
    ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o vscode -g vscode /home/vscode/.codex
