# Current-contract QLoRA v1 runbook

This runbook executes exactly one training configuration. It does not permit a sweep or an automatic retry.

## Authorization boundary

Before provisioning, the repository must be clean, `make check` must pass, and `make preflight-current-qlora-v1` must report `trainingAuthorized: true`. The authorization evidence must name the exact no-spend plan commit and the $3.00 combined ceiling: $1.50 training plus $1.50 adapter evaluation. Training and evaluation costs are settled separately against the canonical ledger.

Re-read Runpod immediately before launch. Record zero or existing active pods, secure A40 availability, the exact hourly rate, the selected datacenter, and the projected aggregate spend on issue #20. Do not create a pod if the training reservation cannot cover the 9,000-second hard deadline plus disk.

## Pod envelope

- One secure `NVIDIA A40`, CUDA 12.8 or later.
- Image `runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851`.
- 40 GB container disk and 40 GB pod-persistent storage mounted at `/workspace`.
- SSH enabled; no public service port is required.
- Provider deletion deadline: 9,000 seconds after provider creation.

The supervisor must retain the pod ID from the create response and delete that exact pod after artifact retrieval. A stopped pod still incurs storage charges; deletion is required.

## Setup and preflight

Clone and detach at the exact authorized source commit. Install `uv==0.12.9`, then install `environments/qwen38-a40-v1.requirements.lock` with hashes inside a dedicated virtual environment. Run:

```sh
make check
PYTHONPATH=src python3 scripts/run_planner_current_qwen38_qlora_v1.py --preflight-only
```

The preflight must report 24 traces, corpus SHA-256 `a4ce7ac3e3365148ee4bd057928cfe3f72847637fe9c8ae7ebbadc29b608dcfa`, maximum rendered length 5,416, context length 8,192, model revision `8aa5f05d26b7205477066e1449e0af13f762a299`, training reservation $1.50, combined ceiling $3.00, and `trainingAuthorized: true`.

## Execute once

Launch in a detached process with logs and an exit-code file outside the model artifact directory:

```sh
PYTHONPATH=src python3 scripts/run_planner_current_qwen38_qlora_v1.py
```

Do not retry a failed paid run. Preserve the failure log, exit code, exact source commit, and provider resource identity for terminal publication.

On success, run the verifier in a fresh lightweight process:

```sh
PYTHONPATH=src python3 scripts/verify_planner_current_qwen38_qlora_v1_artifact.py \
  --expected-source-commit "$AUTHORIZED_SOURCE_COMMIT"
```

Retrieve `.artifacts/planner-current-qwen38-qlora-v1`, setup/training logs, and exit codes before deleting the pod. Hash the transferred archive locally and replay the verifier against the retrieved artifact.

## Settlement and next gate

After deletion, confirm zero active pods and wait for the exact Runpod billing record. Publication must bind the adapter inventory, run manifest, reload probe, provider settlement, and updated aggregate ledger. Only then may the preregistered adapter-only evaluation be activated; the published stock results are reused and stock inference is not rerun.
