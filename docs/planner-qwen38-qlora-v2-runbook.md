# Runpod execution runbook for planner QLoRA v2

This runbook executes the single experiment preregistered in
[`planner-qwen38-qlora-v2.json`](../experiments/planner-qwen38-qlora-v2.json). It creates no
authority: the checked-in status must be `ready-for-training`, its exact commit must have green CI,
and the maintainer must have authorized that commit and the `$1.50` reservation before any volume or
pod is created.

## Non-negotiable launch state

- Use only the exact authorization commit. Checkout is detached and `git rev-parse HEAD` must equal
  the authorized 40-character SHA.
- Reconcile the aggregate ledger immediately before launch. Its projected commitment must remain at
  or below `$40.00`, including the `$1.50` training reservation.
- Confirm zero Loomarr training pods and volumes, then recheck secure A40 availability and price.
- Use one secure `NVIDIA A40`, the image digest in `qwen38-a40-v1.json`, one configuration, and no
  automatic retry.
- Never send household data or credentials to the pod. The public repository contains the complete
  synthetic/reviewed input.
- One supervisor owns the pod ID from creation through verified deletion. If that uninterrupted
  supervision cannot be maintained, do not create the pod.

Runpod removed `--stop-after` and `--terminate-after` in `runpodctl` 2.12.0 because the backend
accepted but did not enforce either deadline ([runpodctl#330](https://github.com/runpod/runpodctl/pull/330)).
The current REST v2 and MCP create-pod contracts expose no replacement. The live cost guard is
therefore an explicit supervisor deadline: record the provider creation time, delete the pod no
later than 9,000 seconds afterward even if setup or training is incomplete, and preserve the failed
run without retry. Do not use the still-stale documented timer flags.

At the current secure A40 rate of `$0.49/hour`, 9,000 seconds costs at most `$1.225` for GPU time.
Forty GB each of container disk and standard network volume add less than `$0.03` over that window at
the published storage rates, leaving more than `$0.24` inside the reservation. Price and storage
rates are temporal launch checks, not permanent assumptions.

## Resource and storage shape

Create one 40 GB standard network volume in a data center with secure A40 capacity, then create the
pod in that same data center with:

- image `runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851`;
- one `NVIDIA A40`, secure cloud, CUDA 12.8, and 40 GB container disk;
- the network volume mounted at `/workspace`;
- SSH only, with no HTTP service ports.

The network volume holds the repository, Hugging Face cache, logs, and adapter so a pod failure does
not erase evidence. Keep the virtual environment on the faster container disk. Record the pod ID,
volume ID, data center, exact hourly prices, creation timestamp, and 9,000-second deletion deadline
in the tracking issue immediately after creation.

After choosing the live data center, the reviewed CLI shape is:

```bash
export LOOMARR_RUNPOD_DATA_CENTER=<secure-A40-data-center>
export LOOMARR_RUNPOD_DEADLINE=<creation-time-plus-9000-seconds-rfc3339>

runpodctl user >/dev/null
runpodctl network-volume create --name loomarr-qwen38-qlora-v2 --size 40 \
  --data-center-id "$LOOMARR_RUNPOD_DATA_CENTER"
export LOOMARR_RUNPOD_VOLUME_ID=<returned-volume-id>
runpodctl pod create --name loomarr-qwen38-qlora-v2 \
  --cloud-type SECURE --gpu-id "NVIDIA A40" --gpu-count 1 \
  --data-center-ids "$LOOMARR_RUNPOD_DATA_CENTER" --min-cuda-version 12.8 \
  --image runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851 \
  --container-disk-in-gb 40 --network-volume-id "$LOOMARR_RUNPOD_VOLUME_ID" \
  --volume-mount-path /workspace --ssh --wait --wait-timeout 10m
export LOOMARR_RUNPOD_POD_ID=<returned-pod-id>
```

`LOOMARR_RUNPOD_DEADLINE` is a supervisor assertion, not a provider setting. Do not continue if
`runpodctl user` cannot authenticate from `RUNPOD_API_KEY`, or if the created pod differs from any
specified field. A creation or readiness failure still requires listing resources and deleting every
returned pod or volume before stopping.

## Prepare the exact source

The placeholders below are resolved from the reviewed authorization commit and live resource. They
must never be inferred from a mutable branch:

```bash
export LOOMARR_AUTHORIZED_COMMIT=<40-hex-authorization-commit>
export LOOMARR_MODELS_DIR=/workspace/loomarr-models
export HF_HOME=/workspace/hf-cache
export LOOMARR_VENV=/opt/loomarr-qwen38-v2
export VIRTUAL_ENV="$LOOMARR_VENV"

git clone https://github.com/loomarr/loomarr-models.git "$LOOMARR_MODELS_DIR"
git -C "$LOOMARR_MODELS_DIR" checkout --detach "$LOOMARR_AUTHORIZED_COMMIT"
test "$(git -C "$LOOMARR_MODELS_DIR" rev-parse HEAD)" = "$LOOMARR_AUTHORIZED_COMMIT"
test -z "$(git -C "$LOOMARR_MODELS_DIR" status --porcelain --untracked-files=all)"

python3 -m venv "$LOOMARR_VENV"
"$LOOMARR_VENV/bin/python" -m pip install --no-deps uv==0.12.9
PATH="$LOOMARR_VENV/bin:$PATH" make -C "$LOOMARR_MODELS_DIR" sync-qwen38-a40
make -C "$LOOMARR_MODELS_DIR" check
PATH="$LOOMARR_VENV/bin:$PATH" make -C "$LOOMARR_MODELS_DIR" preflight-qlora-v2
```

Stop without training if checkout, environment installation, repository checks, or the authorized
preflight fails. Setup time counts against the provider deletion deadline.

## Detached training

Write logs and the terminal exit code outside the runner's output directory so its overwrite guard
remains effective:

```bash
mkdir -p /workspace/planner-qwen38-qlora-v2-control
setsid bash -lc '
  set +e
  export PATH=/opt/loomarr-qwen38-v2/bin:$PATH
  export VIRTUAL_ENV=/opt/loomarr-qwen38-v2
  export HF_HOME=/workspace/hf-cache
  cd /workspace/loomarr-models
  PYTHONUNBUFFERED=1 PYTHONPATH=src python3 scripts/train_planner_smoke.py \
    --config experiments/planner-qwen38-qlora-v2.json
  task_rc=$?
  printf "%s\n" "$task_rc" > /workspace/planner-qwen38-qlora-v2-control/exit-code
  exit "$task_rc"
' > /workspace/planner-qwen38-qlora-v2-control/training.log 2>&1 </dev/null &
```

Tail the control log in separate SSH calls and inspect GPU utilization. Never launch a second
process if the first exits or disconnects. The runner itself also has a 9,000-second process alarm,
but the earlier provider-creation deadline is authoritative for cost.

## Verify, retrieve, and delete

Success requires all of the following before the pod is deleted:

```bash
test "$(cat /workspace/planner-qwen38-qlora-v2-control/exit-code)" = 0
cd /workspace/loomarr-models
PATH=/opt/loomarr-qwen38-v2/bin:$PATH python3 \
  scripts/verify_planner_qwen38_qlora_v2_artifact.py \
  --expected-source-commit "$LOOMARR_AUTHORIZED_COMMIT" \
  > /workspace/planner-qwen38-qlora-v2-control/artifact-verification.json
sha256sum /workspace/planner-qwen38-qlora-v2-control/training.log \
  /workspace/planner-qwen38-qlora-v2-control/artifact-verification.json
```

The training manifest must report all 45 steps, the exact preflight identities, one A40, the locked
package versions, an adapter-only file inventory, and a successful post-save reload/generation probe.
Copy the complete control directory and `.artifacts/planner-qwen38-qlora-v2` to local gitignored
storage, compare the remote and local SHA-256 values, and rerun the verifier locally against the
authorized commit.

Delete the pod immediately after local verification, or at the 9,000-second deadline regardless of
state. Confirm it is absent with a fresh list call. Then delete the network volume after the local
copy is verified and confirm that it too is absent. Record the terminal outcome and provisional
billing on issue #20. Any interruption is a published failed attempt; there is no automatic paid
retry.
