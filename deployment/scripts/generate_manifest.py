from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_PLATFORMS = [
    ("windows", "x64", "consultant.exe"),
    ("linux", "x64", "consultant"),
    ("linux", "arm64", "consultant"),
    ("macos", "x64", "consultant"),
    ("macos", "arm64", "consultant"),
]

INSTALLER_NAMES = {
    ("windows", "x64"): "1c-consultant-installer-windows-x64.exe",
    ("linux", "x64"): "1c-consultant-installer-linux-x64",
    ("linux", "arm64"): "1c-consultant-installer-linux-arm64",
    ("macos", "x64"): "1c-consultant-installer-macos-x64",
    ("macos", "arm64"): "1c-consultant-installer-macos-arm64",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--base-url", type=str, required=True)
    parser.add_argument("--version", type=str, required=True)
    parser.add_argument("--installer-version", type=str, default="0.5.3")
    args = parser.parse_args()

    release_dir: Path = args.release_dir
    base_url = args.base_url.rstrip("/")

    app_artifacts = []
    for os_name, arch_name, exe_name in EXPECTED_PLATFORMS:
        zip_name = f"1c-consultant-{args.version}-{os_name}-{arch_name}.zip"
        zip_path = release_dir / zip_name
        if zip_path.is_file():
            app_artifacts.append({
                "os": os_name,
                "arch": arch_name,
                "url": f"{base_url}/{zip_name}",
                "sha256": sha256_file(zip_path),
                "size": zip_path.stat().st_size,
                "executable": exe_name,
                "health_check_args": ["--version"]
            })

    installer_artifacts = []
    for (os_name, arch_name), inst_name in INSTALLER_NAMES.items():
        inst_path = release_dir / inst_name
        if inst_path.is_file():
            installer_artifacts.append({
                "os": os_name,
                "arch": arch_name,
                "url": f"{base_url}/{inst_name}",
                "sha256": sha256_file(inst_path),
                "size": inst_path.stat().st_size,
                "filename": inst_name
            })

    manifest = {
        "schema_version": 1,
        "application": {
            "version": args.version,
            "artifacts": app_artifacts
        },
        "installer": {
            "version": args.installer_version,
            "artifacts": installer_artifacts
        },
        "graphs": []
    }

    manifest_path = release_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
