# Loomarr models working agreement

This repository owns offline model-research artifacts only. The Loomarr application repository owns
runtime behavior, prompts, tool schemas, certification holdouts, and product authority.

- Never copy certification prompts or cases into train/development data.
- Never ingest household prompts, histories, catalogs, decisions, paths, databases, or credentials.
- Every generated artifact must be reproducible from reviewed sources and bound to SHA-256 identities.
- Unreviewed traces stay drafts and must fail closed when an artifact is built.
- GPU/model work requires a tracked experiment and an explicit aggregate-spend check.
- Application safety, approval, authorization, scheduling, and playback authority remain deterministic Go.

Run `make check` before committing. Do not add a dependency without pinning it and recording why it is
needed in the relevant environment manifest.
