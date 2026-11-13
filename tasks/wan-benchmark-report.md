# Approved Wan 2.2 TI2V 5B feasibility — 2026-11-14

## Outcome: CUDA works; model feasibility BLOCKED before acquisition

The pinned PyTorch/CUDA runtime executed real, synchronized, numerically
checked kernels on the RTX 5070 Ti (`sm_120`). **No model was downloaded,
loaded, or marked READY; no scene was generated.** Shared-machine RAM
headroom did not establish a conservative native-offload budget. Stop here,
not at an OOM experiment or a success-shaped CPU/cloud fallback.

This is partial P2 evidence, **not P2-06 completion, P3/P9 acceptance,
visual-quality approval, or a production deployment**. Auth, workflow runtime,
studio, publication, and approval documents are deliberately untouched.
The owner separately manages model consent records. This experiment used no
Hugging Face credential and never accessed `huggingfaceinfo.env`.

Worktree: `D:\animetron\.worktrees\wan-benchmark`;
branch: `benchmark/wan-ti2v-5b`;
baseline: `7bf34e2cc3ed81c1ca69ade4143b1eb02b3a6a5f`.
Before merge, the tracker was reconciled with master `d4ef716`: explicit
consent #32 and merged preview-core #35 are preserved. This does not change
the historical experiment baseline or certify complete model feasibility.
Execution timestamps below are UTC (local date is 2026-11-14 JST).

## Scope and acquisition gate

The owner's explicit license acceptance and acquisition/local-test permission
apply ONLY to public, ungated `Comfy-Org/Wan-2.2`, immutable revision
`ee6f4a40737a995bf5818954cfce6d59443b0f04`, and these three files:

| Exact repository path | Bytes | SHA-256 |
| --- | ---: | --- |
| `split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` | 9999658848 | `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e` |
| `split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6735906897 | `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| `split_files/vae/wan2.2_vae.safetensors` | 1409400960 | `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156` |
| **Total** | **18144966705** | |

Independent credential-free GET of the [pinned canonical metadata](https://huggingface.co/api/models/Comfy-Org/Wan-2.2/revision/ee6f4a40737a995bf5818954cfce6d59443b0f04?blobs=true)
returned the exact canonical ID/revision, `private=false`, `gated=false`, and
matching sibling sizes/LFS SHA-256 values for all three. Alias/main URLs in
tutorials do not replace these pins. **These are public metadata comparisons,
not local payload digest verification.**

No staging or acquisition logic was introduced because the capacity gate
failed first. A future authorized retry must recheck capacity, stream only
these exact pinned paths at bounded rates/read sizes, enforce expected byte
counts and SHA-256, publish without replacement, and reuse only files whose
local digest has been checked. This report cannot confer READY status.

## Official compatibility and framework safety evidence

* The [PyTorch 2.7 release](https://pytorch.org/blog/pytorch-2-7/#prototype-nvidia-blackwell-architecture-support)
  explicitly introduced Blackwell support and CUDA 12.8 wheels. It is support
  history, not the installed version or proof of this machine's operation.
* The [previous versions matrix](https://pytorch.org/get-started/previous-versions/)
  has awkward/stale presentation; selector labels were not trusted. The
  [official v2.9.1 release](https://github.com/pytorch/pytorch/releases/tag/v2.9.1)
  (published 2025-11-12) and [official cu128 wheel index](https://download.pytorch.org/whl/cu128/torch/)
  verified that the Linux x86_64 CPython 3.12
  `torch-2.9.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl` exists.
  Index SHA-256:
  `7cb4018f4ce68b61fd3ef87dc1c4ca520731c7b5b200e360ad47b612d7844063`.
  The wheel was installed via this index, not an automatic CUDA variant.
  No independent retained-wheel hash audit was performed.
* NVIDIA's [Blackwell compatibility guide](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/)
  explains why device visibility alone is insufficient: a compatible cubin
  or PTX must actually launch. The probe below exercised kernels rather than
  relying on `is_available()` alone.
* Candidate native ComfyUI pin: tag `v0.3.64`, resolved through the official
  GitHub tag ref to commit `637221995f7424a561bd825de3e61ea117dfe1e3`.
  Reviewed that commit's [requirements](https://github.com/Comfy-Org/ComfyUI/blob/637221995f7424a561bd825de3e61ea117dfe1e3/requirements.txt),
  [loader](https://github.com/Comfy-Org/ComfyUI/blob/637221995f7424a561bd825de3e61ea117dfe1e3/comfy/utils.py),
  and [memory manager](https://github.com/Comfy-Org/ComfyUI/blob/637221995f7424a561bd825de3e61ea117dfe1e3/comfy/model_management.py).
  `.safetensors` dispatches to `safetensors.safe_open`; native offload uses
  CPU memory and `--reserve-vram` adds a GPU reserve. No pickle checkpoint,
  custom node, remote model code, or ComfyUI service was executed.
  **This limited source review is not a full dependency vulnerability audit,
  a full native-node implementation review, or a tested ComfyUI/PyTorch pairing.**
  ComfyUI and its additional dependencies were not installed.
* The [official Wan tutorial](https://docs.comfy.org/tutorials/video/wan/wan2_2)
  and [native examples](https://comfyanonymous.github.io/ComfyUI_examples/wan22/)
  specify these native model locations. The 8 GB VRAM/offloading claim is
  not a system RAM guarantee or measured acceptance.

## Measured capacity and decision

| Observation | Value |
| --- | ---: |
| Host RAM (owner-provided prior probe) | 34055766016 bytes |
| Initial Windows available physical RAM | 13236084736 bytes |
| Later Windows available physical RAM | 12365725696 bytes |
| Post-cleanup Windows available RAM | 11522170880 bytes |
| Docker Linux memory ceiling (`docker info`) | 16614367232 bytes |
| Initial D: free | 239967776768 bytes |
| Post-install D: free | 232718303232 bytes |
| Post-cleanup D: free | 239429259264 bytes |
| NVIDIA host-reported VRAM | 16303 MiB |
| Initial free VRAM (volatile) | 14060 MiB |
| NVIDIA driver | 621.01 |
| Docker Engine | 29.7.2 |

Conservative planning gate: allow **20 GiB container RAM with no swap**, plus
**8 GiB currently available host RAM left for other work**, and retain at
least 60 GiB disk free. The RAM planning allowance rounds the 16.9 GiB
approved payload plus about 2 GiB runtime/working overhead upward. It is
**not an empirically measured minimum**, and payload bytes are not equivalent
to RSS; memory-mapped tensors and native staged offloading might use less.
Conversely, dtype conversion, activations and loading can use more.

Neither Docker's 15.47 GiB ceiling nor the shared host's approximately
11–12 GiB currently available RAM establishes that planning envelope.
Even initially, leaving 8 GiB available grants only about 4.33 GiB new
resident host memory, below the 9.31 GiB diffusion payload alone. Native CPU
offloading makes the VRAM fit claim insufficient to close that uncertainty.
Disk capacity passed; safe inference RAM capacity did not.

No unrelated processes/containers were enumerated or killed. No WSL, Docker
daemon, host installation, swap or OS setting was changed to force a fit.
The safe next step is an owner-arranged quiet resource window and separately
verified sufficient Linux/container RAM, followed by a new bounded authorized
task with a reviewed runtime/workflow and fresh capacity checks. This result
does **not** assert that the GPU or model is intrinsically incompatible.

## Executed runtime probe

Existing base image (no new image build):
`python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
Installed Python: `3.12.16`, GCC `14.2.0`.
Installer pip: `25.0.1`; tested package versions are recorded in
[`wan-benchmark-runtime.txt`](wan-benchmark-runtime.txt).
The initial manifest pinned torch/cu128 and binary-only installation;
after execution the resolved transitive versions were recorded without
reinstalling. This is a version record, not complete wheel-hash locking.

Installation used only an owned project bind directory,
`D:\animetron\data\wan-478745d5`; `TMPDIR=/work/tmp`, `HOME=/work`,
no-cache pip, no source distributions, 30-second network timeout and one retry.
Installer limits: 4 CPUs, 2 GiB RAM, memory+swap also 2 GiB (no swap allowance),
128 PIDs, read-only root, all capabilities dropped, no-new-privileges,
no published ports, local logs 5 MiB x 2. Bridge egress was used only for
required package acquisition. A 10-second host watchdog enforced a
1200-second wall bound, 12 GiB owned-directory bound and 60 GiB free disk
floor. Disk checks are sampled, not a kernel filesystem quota.

Installation: 21:16:58.721812837–21:29:00.823548891 UTC;
exit 0, `OOMKilled=false`, watchdog elapsed 725.14 seconds.
Observed directory sample: 10819926630 bytes during installation;
final installed-directory size 7074703418 bytes. These are samples, not a
certified instantaneous disk or installer RAM peak. A sampled installer RAM
observation was 84.66 MiB; 2 GiB was its enforced limit.

There were **three GPU-container launch attempts**, serially:

1. Start rejected before a worker existed: local log compression is
   incompatible with `max-file=1` on this engine. State `created`, PID 0,
   exit 128. Removed that exact container before replacement.
2. With `max-file=2`, Python exited 2: `Argument expected for the -c option`.
   Reconstructing `Config.Cmd` used index 3 instead of index 2.
   No CUDA computation executed. Verified exited/PID 0, then removed.
3. Validated the three-element argv with nonempty `Cmd[2]` before startup.
   Real CUDA kernels passed; no further GPU attempt was made.

Final worker: 21:30:20.097128001–21:30:46.581415444 UTC;
exit 0, `OOMKilled=false`, wall observation 27.42 seconds.
Same CPU/RAM/PID/root/capability limits as the installer; network `none`,
read-only runtime bind, 64 MiB `/tmp` tmpfs, no ports, logs 2 MiB x 2,
120-second watchdog. Only device 0 was exposed.

Probe checks under `torch.inference_mode()`:

* Assert exact torch `2.9.1+cu128`, runtime CUDA `12.8`, device capability
  `(12, 0)`, and compiled `sm_120`.
* Require at least 8 GiB CUDA-reported free memory before allocation.
  Limit PyTorch's allocator to 3% of device memory, with tiny fixed tensors
  and 4 CPU threads. This allocator fraction is not a hard whole-process
  GPU/context quota.
* FP16 and BF16: 64 x 64 all-ones matrix multiply; synchronize and assert
  float32 sum `262144`.
* FP16 and BF16: SDPA on shape `(1, 2, 16, 64)`; synchronize and assert
  finite, all-ones output.
* FP16 and BF16: conv3d on `(1, 2, 3, 8, 8)`, weights
  `(2, 2, 1, 3, 3)`; synchronize and assert finite, first value `18`.
* FP8 e4m3fn roundtrip of 16 ones; synchronize and assert sum `16`.
  **Not scaled FP8 GEMM or full text-encoder compatibility.**

| Actual final probe measurement | Value |
| --- | ---: |
| CUDA runtime | 12.8 |
| cuDNN runtime integer | 91002 |
| Supported compiled architectures | sm_70, sm_75, sm_80, sm_86, sm_90, sm_100, sm_120 |
| CUDA-reported free bytes before compute | 15738077184 |
| CUDA-reported total bytes | 17066360832 |
| PyTorch allocated peak | 8566784 bytes |
| PyTorch reserved peak | 23068672 bytes |
| Process RSS peak | 1307267072 bytes |
| cgroup memory peak | 1415004160 bytes |
| Python probe elapsed | 25.2072 seconds |
| Sampled aggregate host GPU-used peak | 2145 MiB |

Aggregate GPU sampling includes existing users and is not an isolated worker
peak; WSL CUDA free-memory reporting also differs from the earlier host
snapshot. Neither is promoted to a hard inference reserve guarantee.
NumPy initialization warned `No module named 'numpy'`. NumPy was unnecessary
for these checks and was not installed to silence the warning. The probe
passed without it; this environment is deliberately not a ComfyUI environment.

## Scene settings: proposed only, not measured safe/useful

The [native 5B JSON example](https://comfyanonymous.github.io/ComfyUI_examples/wan22/text_to_video_wan22_5B.json)
was read as data, not executed. Its node-type candidate allowlist is
`UNETLoader`, `CLIPLoader`, `VAELoader`, `CLIPTextEncode`,
`ModelSamplingSD3`, `Wan22ImageToVideoLatent`, `KSampler`, `VAEDecode`,
`SaveWEBM`, `SaveAnimatedWEBP` (UI `Note` is not executable).
The example uses 1280 x 704, 41 frames, 30 steps, CFG 5, `uni_pc`,
`simple`, denoise 1, model shift 8, and 24 fps. It notes 121 frames as
optimal length. This remote example was not vendored or immutably pinned;
full allowlisted implementation review remains a gate for the next task.

A proposed initial reduced scene, **not a determined successful minimum**:
288 x 512 (9:16), 17 frames, batch 1, 20 steps, CFG 5, `uni_pc`,
`simple`, denoise 1, shift 8, seed 478745, 24 fps, native low-VRAM offload
and 6 GiB additional GPU reserve. One original prompt only:
“A small blue paper boat gently drifts across a calm pond at sunrise,
soft ripples, fixed camera, clean stylized animation.” No external image,
people, voice, copyrighted character, cloud inference or upload.

This would be roughly 0.71 seconds and 14.06 times fewer pixels per frame
than 1080 x 1920, not a 30–60 second narrated reel. It cannot establish
motion quality, identity consistency, audio alignment, demographic fairness
or final-resolution throughput. No demographic evaluation was applicable to
the executed tensor-only probe; no generated-human fairness claim is made.

## Cleanup, outputs and repository checks

Before cleanup, both exact owned containers reported `Running=false`,
`Pid=0`, `ExitCode=0`:

* `animetron-wan-478745d5-install`:
  `fdfb845fd91b5a788ac6fdc0388b8f3a3fa9931da617c858c1e1b1f2a16a1998`.
* Final `animetron-wan-478745d5-cuda`:
  `3e667410f075a5c58c53fba53cd54e13fb45c6d78e46c0d2c4c6c65daed1f6c9`.

Both were removed by exact name. Subsequent exact-name `docker inspect`
returned exit 1 (absent) for each. The two superseded GPU containers were
already removed after PID-0 verification. The owned runtime/temp directory
was deleted and `Test-Path` returned false. The first absence-check command
stopped on PowerShell's expected native stderr handling; a separate captured
exit-code check confirmed both absent. No worker is left running.

No owned image, custom network, Docker artifact volume, service, or output
volume was created. The pre-existing base image and unrelated resources
were preserved. Persistent approved-model paths: **none acquired by this
task**. Persistent media outputs: **none**. Output hash, frame count,
decodability, duration, visual review, and model resource peaks:
**not available, not passed**. There are no unverified payloads to retain.

Backend checks used the existing root `backend/.venv` read-only, with explicit
worktree `PYTHONPATH`, bytecode disabled and cache locations inside the worktree:

* `pytest -q -p no:cacheprovider`: **162 passed, 77 skipped**, 1.09 s.
  Existing optional integration tests skipped; no database was provisioned
  and no tests were modified/skipped by this task.
* `ruff check --no-cache .`: **passed**.
* `mypy --platform linux --cache-dir .mypy_cache app`: **passed**, 23 files.

Only this report, the probe version manifest and the relevant unchecked todo
evidence are changed. No reusable acquisition/inference script or new logic
was added: with the capacity gate unresolved, claiming such a runner had
been safely verified would overstate this experiment.
