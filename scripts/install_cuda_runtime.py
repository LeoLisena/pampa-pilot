from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile


PACKAGES = (
    {
        "name": "cublas",
        "version": "12.8.4.1",
        "url": "https://developer.download.nvidia.com/compute/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.8.4.1-archive.zip",
        "sha256": "57a470112cec7e112c95253dde8b3c7184d795dbd92b0bde77a4cb7f8c94c8aa",
    },
    {
        "name": "cudnn",
        "version": "9.17.0.29",
        "url": "https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.17.0.29_cuda12-archive.zip",
        "sha256": "46776b0a4e28878a619c682d58d7974ff6b90ea3c73f20519f111cfb36987c0d",
    },
)


def _safe_extract(bundle: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in bundle.infolist():
        target = (destination / member.filename).resolve()
        if target != root and not target.is_relative_to(root):
            raise RuntimeError(f"unsafe archive member: {member.filename}")
    bundle.extractall(destination)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(package: dict[str, str], downloads: Path) -> Path:
    destination = downloads / Path(package["url"]).name
    if destination.is_file() and _digest(destination) == package["sha256"]:
        return destination
    partial = destination.with_suffix(destination.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(package["url"], headers={"User-Agent": "PampaPilot/0.1"})
    with urllib.request.urlopen(request) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    if _digest(partial) != package["sha256"]:
        partial.unlink()
        raise RuntimeError(f"checksum mismatch for {package['name']}")
    partial.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install official NVIDIA CUDA runtime libraries inside .runtime only."
    )
    parser.add_argument("--runtime-root", type=Path, default=Path(".runtime/cuda"))
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    downloads, packages_root = root / "downloads", root / "packages"
    downloads.mkdir(parents=True, exist_ok=True)
    packages_root.mkdir(parents=True, exist_ok=True)
    installed = []
    for package in PACKAGES:
        archive = _download(package, downloads)
        destination = packages_root / f"{package['name']}-{package['version']}"
        expected_library = "cublas64_12.dll" if package["name"] == "cublas" else "cudnn64_9.dll"
        if not any(destination.rglob(expected_library)):
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                _safe_extract(bundle, destination)
        if not any(destination.rglob(expected_library)):
            raise RuntimeError(f"{expected_library} was not found after extracting {package['name']}")
        installed.append(
            {
                **package,
                "archive": str(archive),
                "destination": str(destination),
            }
        )
    manifest = {
        "schema_version": "0.1",
        "source": "official_nvidia_redistributable_archives",
        "system_install_modified": False,
        "packages": installed,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    import truststore

    truststore.inject_into_ssl()
    main()
