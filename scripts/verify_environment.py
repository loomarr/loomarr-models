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
    "transformers": "5.15.1",
    "triton": "3.4.0",
    "trl": "0.22.2",
    "unsloth": "2026.9.2",
    "unsloth-zoo": "2026.9.1",
}
EXPECTED_UV_X86_64_LINUX_SHA256 = "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("platform") != {
        "os": "linux",
        "architecture": "amd64",
        "gpuClass": "nvidia-48gb",
        "validatedSku": "NVIDIA A40",
    }:
        raise SystemExit("environment platform differs from the pinned A40 lane")
    resolver = manifest.get("resolver", {})
    if (
        resolver.get("name"),
        resolver.get("version"),
        resolver.get("releaseAssetSha256"),
    ) != ("uv", "0.12.9", EXPECTED_UV_X86_64_LINUX_SHA256):
        raise SystemExit("resolver identity or Linux x86_64 release hash drifted")
    requirements = manifest["requirements"]
    input_path = ROOT / requirements["inputPath"]
    overrides_path = ROOT / requirements["overridesPath"]
    lock_path = ROOT / requirements["lockPath"]
    if digest(input_path) != requirements["inputSha256"]:
        raise SystemExit("requirements input digest mismatch")
    if digest(overrides_path) != requirements["overridesSha256"]:
        raise SystemExit("requirements overrides digest mismatch")
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
    if manifest["trainingArtifact"]["revision"] != "8aa5f05d26b7205477066e1449e0af13f762a299":
        raise SystemExit("Unsloth 4-bit artifact revision drifted")
    if manifest["recipe"]["revision"] != "24a61a6f128a835de6a8c1f68a01b9cb00d60b4d":
        raise SystemExit("official Qwen3.8 recipe revision drifted")
    print(json.dumps({"environmentId": manifest["environmentId"], "packages": len(pins), "lockSha256": requirements["lockSha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
