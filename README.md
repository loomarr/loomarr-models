# loomarr-models

[![CI](https://github.com/loomarr/loomarr-models/actions/workflows/ci.yml/badge.svg)](https://github.com/loomarr/loomarr-models/actions/workflows/ci.yml)

Offline research assets for Loomarr-specific model experiments. This repository is deliberately
separate from the Go application: Loomarr consumes released model bytes through its existing provider
boundary and never imports this toolchain.

The first milestone is [loomarr/loomarr#937](https://github.com/loomarr/loomarr/issues/937): a
validated 50-trace planner smoke corpus. Current files establish the fail-closed trace contract and
the pinned Qwen 3.8 / Unsloth candidate environment. No GPU training or model download occurs here.

## Checks

```bash
make check
```

`validate-corpus` accepts reviewed artifacts only. Draft validation is available explicitly for the
human-review workflow and never promotes a draft into training data.

Review decisions have separate primary and secondary evidence. Exactly 22 traces require a second,
distinct GitHub reviewer. Once all required decisions approve, `make finalize-corpus` creates the
immutable 50-trace artifact, manifest, and validation report; it refuses pending, rejected, disputed,
partial, or drifted inputs.

The candidate NVIDIA environment is resolved with uv 0.12.9 for Linux x86_64, Python 3.12, CUDA
12.8, and PyTorch 2.8. `make lock-qwen38-a40` reproduces the hash-bound lock; inside the pinned
container, `make sync-qwen38-a40` installs it using uv's `cu128` package backend. Neither command
downloads model weights or starts training.

Issue [loomarr/loomarr#938](https://github.com/loomarr/loomarr/issues/938) adds the no-spend QLoRA
smoke runner. Its checked-in experiment intentionally fails preflight while the 50 traces remain
pending review. See [docs/qwen38-qlora-smoke.md](docs/qwen38-qlora-smoke.md) for the NVIDIA training
lane, the 64 GB Mac development/evaluation lane, and the paid-run stop point.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Report security issues privately as
described in [SECURITY.md](SECURITY.md). Product bugs and feature requests belong in the main
[Loomarr repository](https://github.com/loomarr/loomarr/issues).
