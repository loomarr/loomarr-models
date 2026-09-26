#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "environments/qwen38-strixhalo-v1.json"
EXPECTED_PINS = {
    "accelerate": "1.15.0",
    "amd-torch-device-gfx1151": "2.13.0+rocm10.0.0",
    "peft": "0.18.0",
    "rocm-sdk-device-gfx1151": "10.0.0",
    "torch": "2.13.0+rocm10.0.0",
    "transformers": "5.15.1",
    "trl": "0.22.2",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    requirements = manifest["requirements"]
    if digest(ROOT / requirements["inputPath"]) != requirements["inputSha256"]:
        raise SystemExit("strixhalo requirements input digest mismatch")
    lock_path = ROOT / requirements["lockPath"]
    if digest(lock_path) != requirements["lockSha256"]:
        raise SystemExit("strixhalo requirements lock digest mismatch")
    lock = lock_path.read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^ \\\n]+)", lock, re.MULTILINE))
    if len(pins) != requirements["resolvedPackageCount"]:
        raise SystemExit(f"resolved package count is {len(pins)}, want {requirements['resolvedPackageCount']}")
    for package, version in EXPECTED_PINS.items():
        if pins.get(package) != version:
            raise SystemExit(f"{package} pin is {pins.get(package)!r}, want {version!r}")
    if "--hash=sha256:" not in lock or not requirements["hashesRequired"]:
        raise SystemExit("strixhalo requirements lock is not hash-bound")
    if manifest["baseModel"] != {
        "repository": "Qwen/Qwen3.8-27B",
        "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
        "dtype": "bfloat16",
    }:
        raise SystemExit("strixhalo base model drifted")
    print(json.dumps({"environmentId": manifest["environmentId"], "packages": len(pins), "lockSha256": requirements["lockSha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
