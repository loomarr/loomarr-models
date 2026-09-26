# Contributing

This repository contains reproducible, offline model-research assets for Loomarr. Product behavior,
runtime prompts and tool schemas remain in [loomarr/loomarr](https://github.com/loomarr/loomarr).

Before opening a pull request:

1. Link a tracking issue in `loomarr/loomarr` or this repository.
2. Read `AGENTS.md` and preserve the privacy, holdout, review and spend boundaries.
3. Run `make check` with Python 3.12 or newer.
4. Record exact model, dataset, recipe and environment revisions and SHA-256 identities.
5. Report external API/GPU spend, including zero-spend work.

Never commit credentials, `.env` files, household data, certification holdouts, downloaded model
weights or training checkpoints. Generated training artifacts require the documented independent
review workflow and must pass the fail-closed finalizer.
