# Spec: media-generation

Status: Approved for implementation on November 14, 2026, preserving the
duration revision approved on November 13, 2026.
Depends on: model-registry, workflow-runtime.

## Objective

Convert an original story into a coherent vertical reel using local LLM,
keyframe/video generation, narration, alignment and deterministic encoding.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_media_generation.py -q`.
Ownership: `app/engines` and allowlisted media node handlers.
Hardware benchmark commands are defined only after engine selection.

## Code style and provider contracts

Inherit shared style. Providers implement the runtime NodeHandler contract.
ScenePlan includes language, narrator text, character references, shot prompts,
scene order and duration budgets; all LLM JSON is schema-validated untrusted data.
Artifact outputs reference model revision, seed, parameters and provenance.

Nodes: StoryPlan, CharacterReference, Keyframe, SceneAnimation, Narration,
Alignment, Render. Voice and animation join through scene ids and timing rules.
ComfyUI owns the first image/video execution path; direct Diffusers is not a
second required runtime without a documented compatibility need.

## Testing and acceptance criteria

1. Deterministic fixtures prove scene order, narration/subtitle timing and render
   contracts; malformed LLM plans, missing artifacts and failed engine jobs fail
   visibly. FFmpeg receives validated argument arrays, not shell commands.
2. A real short-reel benchmark records peak VRAM/RAM, disk use, runtime, engine
   versions and output hashes. Local-only inference is verified; no cloud fallback.
3. Approved duration targets 30-60 seconds with a hard 90-second maximum;
   preflight the scene budget and reject final exports exceeding 90 seconds.
   Proposed export format is 9:16, 1080x1920 H.264/AAC, 24fps.
   Validate duration/audio/decodability with ffprobe, including focused boundary
   tests for the 90-second limit. Subtitles remain within
   frames; sampled alignment error target <=200ms requires user approval and
   human-measured evidence. Character consistency requires sample approval.

## Boundaries

Inherit shared boundaries. Rendered 3D appearance is not mesh generation.
Never infer identity/voice rights or model license permission. Use licensed
voices and original/authorized assets. No generated commands, unrestricted
ComfyUI workflow uploads or inference endpoints exposed publicly.
