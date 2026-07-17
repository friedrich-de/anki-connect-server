"""Install the pinned official OpenAI tunnel-client release for Linux images."""

import argparse
import hashlib
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "v0.0.10"
CHECKSUMS = {
    "amd64": "b9e0388a343f2d7adeff3992f411a0bd3d916a64bc56534aac5fd15ac1b20cd5",
    "arm64": "b842a9b2352eebd80514cf01a1fbb1c0d400a7d24a4015e85a7ea5f1aeaa5b30",
}
ARCHITECTURE_ALIASES = {
    "aarch64": "arm64",
    "arm64": "arm64",
    "x86_64": "amd64",
    "amd64": "amd64",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", default=platform.machine().lower())
    parser.add_argument("--install-dir", type=Path, default=Path("/usr/local/bin"))
    return parser.parse_args()


def _download(url: str, destination: Path) -> None:
    with (
        urllib.request.urlopen(url) as response,  # noqa: S310 - pinned HTTPS release URL
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def _verify_checksum(archive: Path, expected: str) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != expected:
        raise RuntimeError(f"unexpected tunnel-client archive checksum: {digest}")


def _install_archive(archive: Path, install_dir: Path) -> None:
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as release:
        destination = install_dir / "tunnel-client"
        with release.open("tunnel-client") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    args = _parse_args()
    requested_architecture = args.architecture.strip().lower() or platform.machine().lower()
    architecture = ARCHITECTURE_ALIASES.get(requested_architecture)
    if architecture is None:
        raise RuntimeError(f"unsupported tunnel-client architecture: {requested_architecture}")

    archive_name = f"tunnel-client-{VERSION}-linux-{architecture}.zip"
    url = f"https://github.com/openai/tunnel-client/releases/download/{VERSION}/{archive_name}"
    with tempfile.TemporaryDirectory(prefix="tunnel-client-install-") as temporary_directory:
        archive = Path(temporary_directory) / archive_name
        _download(url, archive)
        _verify_checksum(archive, CHECKSUMS[architecture])
        _install_archive(archive, args.install_dir)


if __name__ == "__main__":
    main()
