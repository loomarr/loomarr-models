#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "environments/qwen38-a40-v1.json"
EXPECTED_PINS = {
    "bitsandbytes": "0.50.2",
    "datasets": "4.3.0",
    "peft": "0.18.0",
    "torch": "2.8.0+cu128",
    "transformers": "5.5.0",
    "triton": "3.4.0",
    "trl": "0.24.0",
    "unsloth": "2026.9.2",
    "unsloth-zoo": "2026.9.1",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    requirements = manifest["requirements"]
    input_path = ROOT / requirements["inputPath"]
    lock_path = ROOT / requirements["lockPath"]
    if digest(input_path) != requirements["inputSha256"]:
        raise SystemExit("requirements input digest mismatch")
    if digest(lock_path) != requirements["lockSha256"]:
        raise SystemExit("requirements lock digest mismatch")

    lock = lock_path.read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^ \\\n]+)", lock, re.MULTILINE))
    if len(pins) != requirements["resolvedPackageCount"]:
        raise SystemExit(f"resolved package count is {len(pins)}, want {requirements['resolvedPackageCount']}")
    for package, version in EXPECTED_PINS.items():
        if pins.get(package) != version:
            raise SystemExit(f"{package} pin is {pins.get(package)!r}, want {version!r}")
    if "--hash=sha256:" not in lock or not requirements["hashesRequired"]:
        raise SystemExit("requirements lock is not hash-bound")
    if requirements["pythonPlatform"] != "x86_64-manylinux_2_28" or requirements["torchBackend"] != "cu128":
        raise SystemExit("requirements target differs from the pinned A40 environment")
    if manifest["baseModel"]["revision"] != "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0":
        raise SystemExit("Qwen base revision drifted")
    print(json.dumps({"environmentId": manifest["environmentId"], "packages": len(pins), "lockSha256": requirements["lockSha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
