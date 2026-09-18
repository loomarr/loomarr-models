# Corrected current-contract QLoRA v2 runbook

This runbook permits one training launch only. It does not permit a sweep or an automatic paid
retry.

## Authorization boundary

Before provisioning, the repository must be clean, `make check` must pass, and
`make preflight-current-qlora-v2-plan` must report `trainingAuthorized: false`. Paid execution
requires a later authorization naming the exact plan commit and the $3.00 combined ceiling:
$1.50 training plus $1.50 adapter evaluation. After that transition,
`make preflight-current-qlora-v2` must report `trainingAuthorized: true`.

Re-read Runpod immediately before launch. Record active pods, secure A40 availability, exact
hourly price, datacenter, and projected aggregate spend on issue #20. Do not provision unless the
training reservation covers the 9,000-second deadline and configured storage.

## Corrected pod envelope

- One secure `NVIDIA A40`, CUDA 12.8 or later.
- Image `runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851`.
- 40 GB container disk; install the virtual environment at `/opt/loomarr-venv`.
- 80 GB pod-persistent storage mounted at `/workspace`.
- `HF_HOME=/workspace/hf-cache` and `HF_HUB_DISABLE_XET=1` exported before Python starts.
- SSH enabled; no public service port.
- Provider deletion deadline: 9,000 seconds after provider creation.

The supervisor must retain the created pod ID and delete that exact pod after evidence retrieval.
A stopped pod still incurs storage charges; deletion is required.

## Setup and fail-closed storage check

Clone and detach at the exact authorized source commit. Install `uv==0.12.9` and the locked
environment into `/opt/loomarr-venv`, never under `/workspace`. Before model acquisition:

```sh
export HF_HOME=/workspace/hf-cache
export HF_HUB_DISABLE_XET=1
test "$(df --output=avail -BG /workspace | tail -1 | tr -dc '0-9')" -ge 70
make check
PYTHONPATH=src /opt/loomarr-venv/bin/python \
  scripts/run_planner_current_qwen38_qlora_v2.py --preflight-only
```

The preflight must report 24 traces, maximum rendered length 5,416, context length 8,192, model
revision `8aa5f05d26b7205477066e1449e0af13f762a299`, and the exact authorization state. Abort before
model download if the environment variables, mount, free-space check, source commit, or plan
identity differs.

## Execute once, verify, retrieve, delete

Launch once in a detached process, with logs and the exit-code file outside the adapter directory:

```sh
export HF_HOME=/workspace/hf-cache
export HF_HUB_DISABLE_XET=1
setsid bash -c 'PYTHONPATH=src /opt/loomarr-venv/bin/python \
  scripts/run_planner_current_qwen38_qlora_v2.py; echo $? > /workspace/training.exit' \
  > /workspace/training.log 2>&1 </dev/null &
```

Do not retry a failed paid run. On success, run the artifact verifier in a fresh process, retrieve
and hash the adapter, manifest, logs, exit code, source identity, and storage snapshots locally,
then delete the pod. Confirm an empty active-pod list and settle only the exact provider billing
record. Adapter evaluation remains disabled until a verified, hash-bound adapter publication
exists; the published stock results are reused.
