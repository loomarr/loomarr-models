# Loomarr LLM inventory

Source: Loomarr `main` at `c2fef697729579ba856ab8c7e4b45fe39fd0faec` (2026-09-27), from reading the
code only. No settings, prompts from households, or private certification data were read.

## Why this exists

Every model change to the shared serving stack has to be judged against every function that uses
it. That includes fine-tuning Flash-Next, changing its quantization, upgrading it, or switching
provider. Until now this repository evaluated only the channel planner.

## Model settings (routing today)

| Setting group | Used for | Fallback |
| --- | --- | --- |
| `llm.provider` / `llm.url` / `llm.model` | all text chat | none |
| `filler.vision.provider` / `.url` / `.model` | image and video questions | `llm.*` when `filler.vision.url` is unset |
| `asr.provider` / `asr.model`, `filler.language_model` | transcription, language ID | local whisper (`ingest.whisper_*`) |

On `fictional-ai-server`, `llm.*` and vision presumably both resolve to the Flash-Next llama-server
(`--vision`), and ASR resolves to the whisper service. A change to Flash-Next therefore reaches
every live chat and image function at once: planner, filler text enrichment, filler research,
split rescue, and both filler vision stages.

`internal/llm/role_policy.go` defines five certified inference roles (`lineup`, `filler_text`,
`filler_frames`, `filler_video`, `transcription`) with per-role routes and limits. Nothing in
production uses them yet. When wired, a role is the natural unit for scoping any model change,
e.g. a planner-only adapter.

## Call sites

| Function | Call site (`llm.WithCallSite`) | Capability | Setting | Live in app | Loomarr evaluation | Evaluated here |
| --- | --- | --- | --- | --- | --- | --- |
| Channel planner (curation) | `suggest.chat` in `internal/suggest/suggester.go` | chat + `catalog_search` tool | `llm.*` | yes | `cmd/planner-cert-compare`, `internal/eval` judge and mood review | yes: v1/v2 gate |
| Channel recommendation | `internal/recommend/runner.go` | chat, JSON | `llm.*` | **no**, cert/diagnostic commands only | `cmd/channel-recommend-cert` | no |
| Filler text enrichment | `filler.text_single`, `filler.text_batch` in `internal/fillerenrichment/text.go` | chat | `llm.*` | yes, optional | not found as a dedicated harness | no |
| Filler research | `internal/fillerresearch/research.go` | chat, bounded JSON (512 tokens) over web results | `llm.*` | yes | not found as a dedicated harness | no |
| Filler split rescue | `filler.split_rescue` in `internal/filler/splitrescue.go` | chat over a transcript | `llm.*` | yes | indirect at most: filler certifiers score pipeline outputs, not this call | no |
| Filler vision tier | `filler.vision` in `internal/filler/stage_vision.go` | images (keyframes) | `filler.vision.*` | yes | indirect at most: `cmd/filler-cert` replays captured decisions without a model | no |
| Filler split vision | `filler.split_vision` in `internal/filler/stage_split.go` | images | `filler.vision.*` | yes | indirect at most | no |
| Filler segment role | `internal/filler/stage_split_video_role.go` | video | OpenRouter video only | **no**, escalator is not wired in the app | `filler-temporal-structure(-window)-certify` | no |
| Language ID / transcription | `internal/filler/languagehosted.go`, `internal/mediatools/hosted_transcription.go` | audio transcription | `asr.*` | yes | `filler-spoken-*-certify` | no |

Development and certification tools also call models: `internal/eval` (judge, mood review),
`cmd/*-diagnostic`, and `cmd/*-cert`.

## Existing Loomarr certification harnesses

`planner-cert-compare`, `channel-recommend-cert`, `filler-cert` (replay, no model),
`filler-spoken-cascade-certify`, `filler-spoken-safety-certify`, `filler-temporal-structure-certify`,
`filler-temporal-structure-window-certify`, and `image-cert` (Rust image worker, not an LLM). Several
filler certifiers score privately labeled material. They stay in the Loomarr repository and must
not be copied here.

## Implications

1. A Flash-Next fine-tune is a change to six live call sites, not one. The planner gate alone
   cannot approve it. The Loomarr filler and planner certifiers would all have to pass on the
   changed model.
2. Scoped alternatives match Loomarr's own direction. A per-request LoRA adapter for the planner
   call site, or a separate specialist behind a future `lineup` role route, leaves the other roles
   untouched.
3. The immediate risk is not training. It is an unmeasured serving change, such as a Flash-Next
   upgrade or requantization, that silently regresses filler vision or research. A regression
   check that replays the existing certifiers against the served model would cover that.

## Open questions

- Confirm the live values of `llm.*`, `filler.vision.*`, and `asr.*` on the household install. This
  document infers them from the server's running services.
- None of the six live Flash-Next call sites except the planner has a harness that calls a model
  directly. Filler text enrichment, research, split rescue, and both vision stages are measured only
  indirectly, if at all.
