# loomarr-models

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
