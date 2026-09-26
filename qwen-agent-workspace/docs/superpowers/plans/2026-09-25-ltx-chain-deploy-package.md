# ltx-chain USB Deployment Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Save this document to:** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md`. The Baseline table (Task 0) and the Real Build Results table (Task 12) are filled in inside this file, never in `/private/tmp`.

**Goal:** Build `scripts/deploy/build_pkg.py`, `scripts/deploy/install_pkg.py`, `scripts/deploy/credential_allowlist.json`, `tests/test_deploy_pkg.py` and `tests/mutate_deploy_pkg.py` as specified. Then run a real, verified `--apply` build of the 131.71 GiB ltx-chain package onto `/Volumes/ltx-chain-deploy` (a fresh dedicated volume created after Task 11's whole-branch review found `/Volumes/Ollama`, the originally-planned target, carrying live HF credentials outside any package's own directory — see Task 12's own header note).

**Architecture:** Two stdlib-only scripts at the Python 3.9 language level. `build_pkg.py` holds the shared helpers (R8): entry I/O, hashing, L1/L2 scanning, `CheckResult`. `install_pkg.py` loads it from its own directory with `importlib.util.spec_from_file_location` and keeps its **own** `HOOKS` dict and path constants. The build flow:
1. It enumerates 17 components from an explicit list into schema-4 JSONL entries.
2. It runs every check (B01-B20, including the offline gates) before anything is written.
3. It writes the root files, then copies the payload. The copy hashes while copying, L3-scans every chunk, and aborts on source drift.
4. It finishes with PC1-PC5, and `MANIFEST.json` is written last.

The installer runs explicit phases with a dry-run default and an `--apply` gate. Every real system probe goes through `HOOKS`, so the unit tests never touch the host.

**Tech Stack:** Python stdlib only. Build interpreter: `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (3.13.0). Install interpreter and second test runner: Apple `/usr/bin/python3` (3.9.6). The pytest runner is 8.3.4 on the framework Python. Tests are `unittest` with `unittest.mock`.

**Spec (single source of truth):** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md` (commit `96307596a24d7b47804c71c6e3a30c2ab0110ff0`, branch `ltx2-mlx-video-pipeline`). Plan written against HEAD `6ab72ac3f29e8d68e06095574bcbd97d8f621240`.

**Workspace root `WS`:** `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. **Repo root `REPO`:** `/Users/reubenpatterson/local_model_harness`. Every relative path is relative to `WS`, and every command runs from `WS` unless it says otherwise.

---

## Global Constraints (copied verbatim from the spec; every task implicitly includes them)

**Scope decisions (spec D2, D3, D8, D4, D7):**
- Ship **vision-mode story generation only** (Qwen3-VL-32B via vLLM-Metal). Text mode (MTPLX 27B) is out of scope.
- Ship **only `ltx-2.5-mlx-q8`**, untrimmed (D5). ltx-2.3 and Gemma-3-12B are not shipped.
- The code payload is an **explicit file list, never a tree walk**: exactly the 10 pipeline files plus 7 test files.
- The Huihui-27B / qwen-serve-guard group is excluded.
- The editable references `fubotv_mcp_common` / `student_agent_mcp` are excluded.

**Files (spec §5.1):** create only `scripts/deploy/build_pkg.py`, `scripts/deploy/install_pkg.py`, `scripts/deploy/credential_allowlist.json`, `tests/test_deploy_pkg.py` and `tests/mutate_deploy_pkg.py`.
- **No existing file is modified.**
- No pipeline file changes.
- Do not revive `tests/test_deploy_package.py`.

**Language/deps (spec §5.2):** Stdlib only. Python 3.9 language level everywhere, including the test file:
- no `match`;
- no PEP 604 in runtime annotations (use no annotations at all);
- no `zip(strict=)`, `int.bit_count`, `datetime.UTC`, `tomllib` or `str.removeprefix`;
- no parenthesized multi-item `with`;
- no f-strings (use `%` formatting, for uniformity).

Importing either script has no side effects. All work happens in `main()` under `if __name__ == "__main__":`.

**Constants (spec §5.3, verbatim):**
```
REQUIRED_USER = "reubenpatterson"
REQUIRED_HOME = "/Users/reubenpatterson"
FRAMEWORK_ROOT = "/Library/Frameworks/Python.framework"
USR_LOCAL_BIN = "/usr/local/bin"
VOLUMES_ROOT = "/Volumes"
FALCONSAI_USB_HUB = "/Volumes/Ollama/hf_home/hub"
BREW_BIN = "/opt/homebrew/bin/brew"
BREW_PY312 = "/opt/homebrew/opt/python@3.12/bin/python3.12"
USB_ROOT_DEFAULT = "/Volumes/Ollama"
CHUNK_SIZE = 8 * 1024 * 1024
L2_MAX_BYTES = 4 * 1024 * 1024
SCHEMA_VERSION = 4
MIN_MEMSIZE_BYTES = 51539607552          # 48 GiB
BUILD_HEADROOM_BYTES = 5 * 1024 ** 3
INSTALL_HEADROOM_BYTES = 10 * 1024 ** 3
STORY_PORT = 8177
```
- Call-time derived paths: `home()` = `os.path.expanduser("~")`, `workspace()` = `home() + "/local_model_harness/qwen-agent-workspace"`, `repo_root()` = `home() + "/local_model_harness"`, `framework_py()` = `FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"`, `ltx25_model_path()` = `home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"`.
- Constants are read at call time and never captured in default arguments or closures.

**Schema (spec §6.2):** `SCHEMA_VERSION = 4`.
- `MANIFEST-ENTRIES.jsonl`: one JSON object per line, UTF-8, separators `(",", ":")`.
- Keys in the order `k, c, p, t, b, m, h, mt, l, s`, and only the keys that apply:
  - `k` kind `f`/`l`/`d`;
  - `c` component;
  - `p` payload path (non-synthetic payload components);
  - `t` absolute target;
  - `b` size (f);
  - `m` 4-digit octal mode (f, d);
  - `h` sha256 (f);
  - `mt` source `st_mtime_ns` (f);
  - `l` symlink value verbatim (l);
  - `s` `true` = synthetic.
- Global order: component order as in the table below; within a component, entries with `p` sorted by `p`, then entries without `p` sorted by `t`.
- `MANIFEST.json` is written LAST by atomic rename. `BUILD-FAILED.json` is never alongside it.

**The 17 components (spec §7, verbatim; `H` = `/Users/reubenpatterson` = `home()`):**

| Id | Slug | Kind | Source | Target | Excludes / notes | Measured |
|---|---|---|---|---|---|---|
| A1 | `workspace-code` | filelist | `WS/<rel>` for the 17 files below | same | Explicit list only (D8) | 715,917 B (17 files) |
| A2 | `hw-gate-seeds` | filelist | `WS/generated/hw_gate_seeds/{portrait,wide3x1,square}.png` | same | Acceptance-run inputs | 1,616,096 B (3 files) |
| B1 | `ltx2mlx-repo` | tree | `H/ltx-2-mlx` | same | Top-level `models`, `hf_cache`, `converted_models`, `source_caches`, `.venv`, `.claude`, `.git` | 7,620,820 B (0.01 GiB) |
| B2 | `ltx2mlx-venv` | tree | `H/ltx-2-mlx/.venv` | same | — | 382,091,499 B (0.36 GiB) |
| B3 | `uv-cpython311` | tree | `H/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none` | same | B2's base interpreter | 50,325,472 B (0.05 GiB) |
| B4 | `ltx25-mlx-q8` | tree | `H/ltx-2-mlx/models/ltx-2.5-mlx-q8` | same | Excludes `.cache`. File set pinned (B04). | 74,718,758,789 B (69.59 GiB, 28 files) |
| B5 | `ltx2mlx-hf-cache-dirs` | synthetic dirs | — | `H/ltx-2-mlx/hf_cache`, `H/ltx-2-mlx/hf_cache/hub` (0755) | Empty scoped HF_HOME | 0 |
| D1 | `vllm-venv` | tree | `H/.venv-vllm-metal` | same | Base is `/opt/homebrew/opt/python@3.12/bin` | 1,724,423,499 B (1.61 GiB) |
| F1 | `framework-python` | tree | `FRAMEWORK_ROOT/Versions/3.13` | same | Excludes `lib/python3.13/site-packages/` members `__editable___fubotv_mcp_common_0_1_0_finder.py`, `__editable___student_agent_mcp_1_0_0_finder.py`, `__editable__.fubotv_mcp_common-0.1.0.pth`, `__editable__.student_agent_mcp-1.0.0.pth`, `fubotv_mcp_common-0.1.0.dist-info`, `student_agent_mcp-1.0.0.dist-info`. Root phase. | 2,148,085,949 B (2.00 GiB) |
| F2 | `framework-symlinks` | enumerated | 20 paths, read live with `os.lstat`/`os.readlink` | same | No payload; root phase | 0 |
| F3 | `user-site` | tree | `H/Library/Python/3.13` | same | Excludes `lib/python/site-packages/` members `__editable___fubotv_mcp_common_0_1_0_finder.py`, `__editable__.fubotv_mcp_common-0.1.0.pth`, `fubotv_mcp_common-0.1.0.dist-info` | 1,524,525,421 B (1.42 GiB) |
| H0 | `hf-home-dirs` | synthetic dirs | — | `H/hf_home`, `H/hf_home/hub` (0755) | — | 0 |
| H1 | `hf-zimage` | tree | `H/hf_home/hub/models--Tongyi-MAI--Z-Image-Turbo` | same | Pin `f332072aa78be7aecdf3ee76d5c247082da564a6` | 32,848,312,686 B (30.59 GiB) |
| H2 | `hf-zimage-te` | tree | `H/hf_home/hub/models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1` | same | Pin `ce497d288a7ddfd5d0f337c7139349d5d0236bfa` | 8,044,983,783 B (7.49 GiB) |
| H3 | `hf-nsfw` | tree | `models--Falconsai--nsfw_image_detection` under the R6 hub (`~/hf_home/hub` first, then `FALCONSAI_USB_HUB`) | `H/hf_home/hub/models--Falconsai--nsfw_image_detection` | Pin `96cb0d0342c7afb80cab76ecc58b265fa44da256` | 343,225,057 B (0.32 GiB) |
| H4 | `hf-qwen3vl32b` | tree | `H/hf_home/hub/models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx` | same | Pin `5428d6aaca0103a1e32f47261a20fecaa47700ec` | 19,632,160,689 B (18.28 GiB) |
| H5 | `mlx-models-link` | synthetic | — | d `H/mlx_models` (0755); l `H/mlx_models/qwen3-vl` → `H/hf_home/hub/models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx/snapshots/5428d6aaca0103a1e32f47261a20fecaa47700ec` | story-server `VISION_MODEL_DIR` | 0 |
| | | | | | **Total** | **141,426,845,677 B (131.71 GiB)** |

- **A1 (exact):**
  - `z_image_skill.py`, `ltx2_mlx_video_skill.py`, `ltx_image_fit.py`, `content_safety.py`, `bin/ltx-movie`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/story-server`, `bin/qwen-agent`;
  - `tests/test_ltx_movie_offline.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_images.py`, `tests/test_ltx2_mlx_video_skill.py`, `tests/test_ltx_image_fit.py`, `tests/test_ltx_story_manifest_chain.py`, `tests/check_ltx2_mlx_no_forbidden_imports.py`;
  - plus `d` entries for `WS`, `WS/bin`, `WS/tests`.
- **A2:** one `d` entry for `WS/generated/hw_gate_seeds`.
- **Never shipped:** `ltx_video_skill.py`, `mps_guard.py`, `flux_skill.py`, `bin/ltx-chain`, `bin/ltx-generate`, `bin/ltx-host-prep`, `bin/ltx-host-restore`, `bin/ltx-story-video`, `bin/pad-images`, `start_vllm.sh`.
- **F2 (exact, 20 entries):**
  - 3 `d`: `FRAMEWORK_ROOT`, `FRAMEWORK_ROOT/Versions`, `USR_LOCAL_BIN`.
  - 4 `l`: `FRAMEWORK_ROOT/{Headers,Python,Resources}`, `FRAMEWORK_ROOT/Versions/Current`.
  - 13 `l` under `USR_LOCAL_BIN`: `idle3`, `idle3.13`, `pip3`, `pip3.13`, `pydoc3`, `pydoc3.13`, `python3`, `python3-config`, `python3-intel64`, `python3.13`, `python3.13-config`, `python3.13-intel64`, `python`.
- **B4's 28 names (`LTX25_PACK_FILES`):** `.gitattributes`, `LICENSE`, `README.md`, `audio_vae.safetensors`, `chat_template.jinja`, `connector.safetensors`, `duration_head.safetensors`, `embedded_config.json`, `generation_config.json`, `ltx-2.5-22b-distilled-lora-450-bf16.safetensors`, `processor_config.json`, `quantize_config.json`, `spatial_upscaler_x2_v1_0.safetensors`, `spatial_upscaler_x2_v1_0_config.json`, `split_model.json`, `temporal_upscaler_x2_v1_0.safetensors`, `temporal_upscaler_x2_v1_0_config.json`, `text_encoder.safetensors`, `text_encoder_config.json`, `tokenizer.json`, `tokenizer_config.json`, `transformer-dev.safetensors`, `transformer-distilled.safetensors`, `vae_decoder_av.safetensors`, `vae_decoder_conv.safetensors`, `vae_encoder_av.safetensors`, `vae_encoder_conv.safetensors`, `vocoder.safetensors`.
- **Tree rules:**
  - sorted `os.listdir`;
  - skip `.DS_Store`;
  - prune directories named `__pycache__`, `.git`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`;
  - apply excludes against the component-relative path;
  - `d` with `m`; `l` never followed; `f` with `b`, `m`, `mt`;
  - any other file type, or `os.access(path, os.R_OK)` false, fails B03 naming the path;
  - the tree root is the component's first `d` entry.

**Credential gate (spec §8, verbatim):**
```python
L1_NAMES = frozenset(["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"])

L2_PATTERNS = (
    ("hf_token", re.compile(rb"hf_[A-Za-z0-9]{34,40}")),
    ("private_key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key_id", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}")),
    ("anthropic_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{32,}")),
    ("openai_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
)

def is_allowlisted(allow, component, relpath, sha256, pattern_id):
    return (component, relpath, sha256, pattern_id) in allow

class KnownSecretScanner(object):
    def __init__(self, secrets):
        self.secrets = list(secrets)
        self.keep = max(len(s) for s in self.secrets) - 1 if self.secrets else 0
        self.tail = b""

    def feed(self, chunk):
        window = self.tail + chunk
        for s in self.secrets:
            if window.find(s) != -1:
                return True
        self.tail = window[-self.keep:] if self.keep else b""
        return False

    def __repr__(self):
        return "<KnownSecretScanner values=%d>" % len(self.secrets)
```

- **L1:**
  - Checks the exact, case-sensitive basename of regular files and symlinks. Directories are not checked.
  - A hit fails B12. There is no allowlist.
- **L2:**
  - Scans every `f` entry with `b <= L2_MAX_BYTES`, read whole from source, with `.search`.
  - Records one hit per (file, pattern). Matched bytes are never printed, logged or stored.
  - The allowlist lives in `scripts/deploy/credential_allowlist.json` as `{"schema_version": 1, "entries": [{"component","relpath","sha256","pattern","note"}]}`.
  - A `note` that is not a non-empty string means a load failure and B13 fails.
  - A NEW hit fails B13 before any payload byte is written.
  - A stale entry prints `WARN B13 stale allowlist entry <json>` and is non-fatal.
- **L3 sources**, in this order:

  | Source | Values extracted |
  |---|---|
  | `home()/.cache/huggingface/token` | whole content `.strip()` |
  | `home()/.cache/huggingface/stored_tokens` | configparser: every key named `hf_token`, `.strip()` |
  | `home()/ltx-2-mlx/hf_cache/token` | whole content `.strip()` |
  | `$HF_TOKEN` | `.strip()` |

  - Values are UTF-8 bytes, de-duplicated, and empty values are ignored. Absent sources give `present: false`.
  - B14 fails on any value under 16 bytes, an unparsable `stored_tokens`, or a `stored_tokens` with no `hf_token`.
  - A new scanner is created per byte stream. Every byte written into the package passes through one.
  - **On a hit in a payload file:**
    1. close both fds;
    2. unlink the partial dst;
    3. flush and fsync the partial JSONL;
    4. raise `CredentialLeak("L3: a known secret value was found in <source path>; the partial payload file was deleted and no MANIFEST.json was written")` → exit 5.
- **L4:** L1+L2 over every file and symlink under the package root.
  - Payload keys are `(component, relpath)`. Other files use `("ROOT", <package-relative path>)`.
  - Any `.DS_Store` fails.
  - A failure goes through the post-copy handler → exit 3 + `BUILD-FAILED.json`.

**R-PRE (spec §9, verbatim):** "Once the first payload byte has been written, the build process opens no file outside the package root, except the source files it is actively copying. It also runs no subprocess."
- `CTX_STATE["payload_started"] = True` is set immediately before the first payload write, and `_run()` raises `RPreViolation(argv[0])` when it is set.
- `--apply` stage order:
  1. parse args, compute `package_root`;
  2. `load_known_secrets()`;
  3. `enumerate_components()` with L1 inline;
  4. `run_prebuild_checks(ctx)` (B01-B17 in table order, containing the exact line `    results.append(check_offline_gates(ctx))`);
  5. any fatal → print everything, exit 4, and the package root is never created;
  6. create or open the root, deleting a stale `BUILD-FAILED.json` on resume;
  7. `write_root_files(ctx)`;
  8. `    copy_payload(ctx)` (exact line);
  9. `return finish_build(ctx)`, which runs PC1-PC5 (PC4 is the exact line `    l4_rescan(ctx)`). Any PC exception writes `BUILD-FAILED.json` and exits 3.
- Exceptions in steps 6-8 → fsync the partial, exit 5. Unexpected exceptions in steps 1-5 → traceback, exit 1.

**Build checks (spec §10, verbatim, all fatal):**

| Id | Check | Detail |
|---|---|---|
| B01 | USB volume | `HOOKS["ismount"](usb_root)`, and `diskutil_personality` contains both `APFS` and `Case-sensitive`. |
| B02 | Free space | `statvfs_free(usb_root) ≥ remaining_bytes + BUILD_HEADROOM_BYTES`. `remaining_bytes` is total `f` bytes minus the bytes of entries already in a verified resume prefix. |
| B03 | Sources readable and venv pins | Enumeration raised no error. `H/ltx-2-mlx/.venv/pyvenv.cfg` has `home = <B3 source>/bin`. `H/.venv-vllm-metal/pyvenv.cfg` has `home = /opt/homebrew/opt/python@3.12/bin`. |
| B04 | 2.5 pack file set | `set(os.listdir(pack)) - {".cache", ".DS_Store"} == LTX25_PACK_FILES`, each a regular file; message lists `extra=` and `missing=`. |
| B05 | HF repos complete | For H1-H4: repo dir exists; `refs/main` `.strip()` equals the pin; `snapshots/` entries (minus `.DS_Store`) are exactly `[pin]`; nothing under `blobs/` ends in `.incomplete`; every symlink in the repo resolves (`realpath`) to an existing regular file under that repo's `blobs/`. |
| B06 | No case-insensitive collisions | Separately among `p` values and among `t` values. |
| B07 | Package root state | Without `--resume` the root must not exist. With `--resume` it must exist, must not contain `MANIFEST.json`, and its resume prefix must validate (§11.3). |
| B08 | Synthetic symlink target shipped | H5's `l` equals the `t` of an H4 `d` entry; live `os.readlink(home()+"/mlx_models/qwen3-vl")` equals the same pinned path. |
| B09 | Port 8177 free | `port_free(8177)`; message: stop the story server before building. |
| B10 | HF scope | Every entry whose source lies under `H/hf_home`, `/Volumes/Ollama/hf_home`, `H/.cache/huggingface` or `H/ltx-2-mlx/hf_cache` is inside one of the four pinned repo dirs. Every target under `H/hf_home` is an H0 dir or inside a pinned target repo dir. Every target under `H/ltx-2-mlx/hf_cache` is a B5 dir. |
| B11 | Target-path allowlist | Every `t` starts with `REQUIRED_HOME + "/"`, or equals/starts with `FRAMEWORK_ROOT(+"/")`, or equals/starts with `USR_LOCAL_BIN(+"/")`. No `t` starts with the literal `"/Volumes/"` or `"/opt/homebrew/"`. `home() == REQUIRED_HOME`. (**Plan addition C3:** `t` must also be absolute and equal `os.path.normpath(t)`.) |
| B12 | L1 | §8.1 |
| B13 | L2 | §8.2 |
| B14 | L3 sources loaded | §8.3 |
| B15 | Offline gates pass | G1-G7, X1, X2, measured now; the result becomes `acceptance-baseline.json`. |
| B16 | Host facts and freezes | Every §6.4 command rc 0. |
| B17 | Provenance (D12) | For each of the 10 pipeline files (`<rp>` = `qwen-agent-workspace/<rel>`), three commands must pass: `/usr/bin/git -C REPO ls-files --error-unmatch -- <rp>` rc 0; `git -C REPO status --porcelain -- <rp>` empty; `git -C REPO hash-object <abs>` == `git -C REPO rev-parse HEAD:<rp>`. The message names each failing file and reason (`untracked`, `modified`, `blob differs`). |

**Offline gates (spec §10.1):** each runs as `[framework_py()] + argv`, `cwd=workspace()`, inherited env, `timeout=900`. `last_line` = `text.rstrip().splitlines()[-1]`, or `""`.

| Id | argv | Pass |
|---|---|---|
| G1-G6 | `tests/test_ltx_movie_offline.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_images.py`, `tests/test_ltx2_mlx_video_skill.py`, `tests/test_ltx_image_fit.py`, `tests/test_ltx_story_manifest_chain.py` | rc 0 and `last_line` matches `^OK (\d+)/\1$` |
| G7 | `tests/check_ltx2_mlx_no_forbidden_imports.py` | rc 0 and `last_line == "RESULT: ok"` |
| X1 | `bin/ltx-mlx-render --help` | rc 0 |
| X2 | `bin/ltx-movie "a test narrative" --story-id deploy-gate-dry --dry-run --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8` | rc 0, 0 output lines contain `{` or `}` |

**Install checks (spec §12.3, verbatim; P = preflight, S = system-python, U = user, V = verify, A = accept; all fatal):**

| Id | Check | Phases |
|---|---|---|
| I01 | `sys.version_info >= (3, 9)` | all |
| I02 | `platform.system() == "Darwin"` and `platform.machine() == "arm64"` | P S U |
| I03 | `hw.memsize ≥ 48 GiB`, via exact code `rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "hw.memsize"])`, `memsize = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1`, then `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)`; the message states the measured peak was 36.61 GiB with the vision model at 0.70 memory utilization, so a 16 GiB Mac cannot run it | P S U A |
| I04 | `sw_vers -productVersion` major ≥ 26 | P S U |
| I05 | `getpwnam("reubenpatterson").pw_dir == REQUIRED_HOME`; non-root phases also `getuser() == REQUIRED_USER` and `$HOME == REQUIRED_HOME` | all |
| I06 | `MANIFEST.json` present with `schema_version == 4`; no `BUILD-FAILED.json`; `sha256(MANIFEST-ENTRIES.jsonl) == entries_sha256`; every `root_files` hash matches; for P S U, `payload/` exists | all |
| I07 | No `.DS_Store` under the package root; message lists them and prints `find "<pkg>" -name .DS_Store -delete` | P S U |
| I08 | L1+L2 rescan of payload and root files with the package's allowlist | P S U |
| I09 | `statvfs_free(REQUIRED_HOME) ≥ Σb(f entries whose t does not lexist) + INSTALL_HEADROOM_BYTES` | P S U |
| I10 | Every target absent or identical; for U the receipts files are included; exact lines `        same, reason = target_matches_entry(target, entry)`, `        if not same:`, `            collisions.append((target, reason))`; every collision prints `COLLISION <reason>: <target>`, then the count | P S U |
| I11 | No two targets equal ignoring case | P S U |
| I12 | `which("ffmpeg")`/`which("ffprobe")` found; first `-version` line matches `^ffmpeg version n?(\d+)\.` / `^ffprobe version n?(\d+)\.` with group 1 = `9` | P U A |
| I13 | `BREW_BIN` exists and is executable | P U |
| I14 | `BREW_PY312 --version` matches `^Python 3\.12\.\d+\s*$` | P U A |
| I15 | `/usr/sbin/lsof` and `/usr/bin/python3` exist and are executable | P U |
| I16 | `port_free(8177)` | P U |
| I17 | `os.environ.get("HF_HOME") == home()+"/hf_home"`; `/bin/zsh -c 'printf "%s" "$HF_HOME"'` gives the same; no `~/.zshenv` line matching `^\s*(export\s+)?HF_HOME=` contains `/Volumes/`; failure prints line numbers and `export HF_HOME="/Users/reubenpatterson/hf_home"`; never edits dotfiles | P U A |
| I18 | `workspace()` writable (existing writable dir, or nearest existing ancestor `W_OK`) | P U |
| I19 | S requires `geteuid() == 0`; every other phase requires `geteuid() != 0` | all |
| I20 | `framework_py() -c "import sys;print(sys.version.split()[0])"` outputs `3.13.0`; in P, if `FRAMEWORK_ROOT/Versions/3.13` is absent, `PENDING` (ok) "run --phase system-python next" | P U V A |

**Exit codes (spec §16):**
- `build_pkg.py`: 0 ok; 1 verify mismatch / report not clean / unexpected pre-write error; 2 usage; 3 post-copy failure; 4 pre-build check failed; 5 copy-stage abort.
- `install_pkg.py`: 0 ok / ACCEPT PASS; 1 runtime failure / ACCEPT FAIL; 2 usage; 4 fatal checks; 5 GPU refusal.

**Mutation anchors (spec §15.3):** the anchor lines in spec §8, §9, §11 and §12 are written **verbatim, including indentation**, and each must occur exactly once in its file. The plan's code blocks already do this, so do not reformat them:
- `["token", "stored_tokens",`
- `self.tail = window[-self.keep:] if self.keep else b""`
- `    l4_rescan(ctx)`
- `    results.append(check_offline_gates(ctx))\n`
- `    copy_payload(ctx)\n`
- `    if before_key != after_key:`
- `    return (component, relpath, sha256, pattern_id) in allow`
- `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)`
- `    if digest != entry["h"]:`
- `            collisions.append((target, reason))`
- `glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))`
- `    if not args.apply:`
- `    if fatal_failures:  # refuse --apply`

No comment or docstring anywhere may repeat these substrings.

**Process constraints (this project's established practice):**
- Commit only the files a task names, with explicit `git -C /Users/reubenpatterson/local_model_harness add <path>`. **Never `git add -A` / `git add .`.** The tree has unrelated dirty files (`.gitignore`, `bin/ltx-story-video`, `ltx_ceiling.json`, `ltx_video_skill.py`, untracked `scripts/run_e2e_dynamic_frames_test.sh`, …); leave them untouched.
- Every commit message ends with the attribution trailer that the executing session's instructions specify.
- Gates run by direct invocation and by exit code, never through pytest counts. The main thread re-runs every gate itself; self-reported counts are not accepted.
- Dual-interpreter gate: `tests/test_deploy_pkg.py` must pass under `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q` **and** under `/usr/bin/python3 tests/test_deploy_pkg.py`. The latter's last line must be exactly `OK`. The two counts differ by design.
- Grep gate: no new file may contain `comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend`. Test code builds any such string by concatenation.
- `rm` may be blocked by the permission system. If a real-host step needs a deletion (e.g. "delete <package_root> and rebuild"), STOP and ask the user; never replace a file with a stub.
- Tests run only against temp fixtures. No test touches `/Volumes/Ollama`, the real home, the real framework or the network.

## Plan-level decisions and spec corrections (binding for the executor)

The spec is silent or factually wrong on these points. Each was decided here with evidence.

| # | Decision | Reason / evidence |
|---|---|---|
| C1 | **`vllm_version` (source-host.json) and A2(b) both use the LAST non-empty output line, not the first.** | Measured 2026-09-25: `~/.venv-vllm-metal/bin/python -c "import vllm; print(vllm.__version__)"` prints 4 timestamped `INFO 09-25 07:36:25 [__init__.py:52] …` lines to stdout before `0.27.1`. With "first line", B16 would record a timestamp and A2(b) would always fail. **This deviates from the spec text; flag it to the user when handing back.** |
| C2 | `install_pkg.py` adds two hooks beyond the §5.3 table: `spawn(argv, cwd=None, env=None, stdout_path=None, new_session=False)` (real: `subprocess.Popen` with stdin DEVNULL, stdout+stderr to the file) and `killpg(pid, sig)` (real: `os.killpg`). | T83/T84 must check the ltx-movie argv/env and the sampler launch without running processes; §13.2 needs Popen-style concurrency, which `run` cannot provide. |
| C3 | B11 also requires `t.startswith("/")` and `os.path.normpath(t) == t`. | Review Focus RF5. Without it, `REQUIRED_HOME + "/../../etc/x"` passes the spec's prefix test. The user may strike this addition; mutation M-set is unaffected. |
| C4 | Accept runs the r1-r5 GPU refusals **immediately after A0** (only with `--gpu`/`--gpu-all`), before A1-A4. | This makes T82 literally true ("no story-server call made"; A4 itself calls story-server) and fails fast before minutes of gates. |
| C5 | PENDING is represented as `CheckResult(ok=True, fatal=True, message="PENDING: <text>")`. `format_result` prints `PENDING <id> <text>`. | Keeps the 4-field namedtuple exact. |
| C6 | `stored_tokens` is parsed with `configparser.ConfigParser(interpolation=None)` over the UTF-8 text. | Default interpolation raises on `%`; interpolation is not wanted for token values. |
| C7 | The spec numbers TestInstallChecks T60-T79 **and** TestInstallApply T70-T77, which overlap. Here TestInstallChecks methods are `test_T60_I01_…` … `test_T79_I20_…` (T60+n ↔ I(n+1)) and TestInstallApply keeps `test_T70_…`-`test_T77_…`; the classes disambiguate. | Numbering conflict in the spec. |
| C8 | T31 asserts the exact message `source changed mid-copy: <src>`. A second case, T31b, rewrites the same number of bytes and bumps mtime. | With an append-only T31, mutation M6 would SURVIVE: the read loop picks up the appended bytes and step 7's size check fires instead. |
| C9 | README rendering (spec §14) is Task 5, before the stage-order task. | `write_root_files` (Task 6) needs `render_readme`; the caller's order listed README 11th ("roughly"). |
| C10 | P0 is **resolved** at HEAD `6ab72ac`. All 10 pipeline files are tracked, porcelain-clean and blob-equal (verified 2026-09-25 while planning). P1 (allowlist review) is still open and handled in Task 12 with the user. | `git ls-files/status/hash-object/rev-parse` on each file. |
| C11 | CLI: `--dry-run` (default), `--apply`, `--verify-only`, `--credential-report` are mutually exclusive. `--resume` requires `--apply`, else a usage error (exit 2). `--usb-root` defaults to `USB_ROOT_DEFAULT` read at call time and is `abspath`ed. | Spec lists the flags without their interplay. |
| C12 | The real `run` hook: stdin is `DEVNULL`. A spawn `OSError` returns `(127, "<argv0>: <error>")`. | Gates and `ltx-movie --dry-run` must never block on stdin. |
| C13 | If the `BUILD-FAILED.json` bytes would contain secret material (L3 known value or L2 secret-shaped pattern), its `error` field is replaced by `"error text withheld: it contained secret material"` before writing (Task 11 fix round widened this from an L3-only check). | Spec requires L3 on every written byte, but is silent on the hit case for this file. |
| C14 | Accept prints `ACCEPT REFUSED (A0: <ids>)` for exit 4 and `ACCEPT REFUSED (GPU precondition; nothing was started)` for exit 5. It writes `accept-<ts>.json` in every outcome. | Spec defines only PASS/FAIL lines. |
| C15 | If A1 fails, A2-A5 are skipped (`ACCEPT FAIL`). A2-A4 all run regardless of each other. | A1 "runs before anything executes". |
| C16 | The `user phase complete` counts are the totals of U's install set (installed plus already identical). | Spec wording ambiguous. |
| C17 | The sampler's stdout/stderr go to `story_dir/sampler_console.txt`. After a 60 s wait a still-running sampler is `kill()`ed. | Diagnosability; spec says only "wait up to 60 s". |
| C18 | `stored_tokens` also holds `refresh_token`. User approved extending L3 to scan it too (not just `hf_token`) — the whole point of L3 is catching real secrets that name/pattern checks miss, and a refresh_token is exactly that class of value. `load_known_secrets()` now checks both keys per section. | Observed key set `['expires_at', 'hf_token', 'refresh_token']`. |

## Rejected alternatives

- **One shared `HOOKS` dict across both modules.** Rejected: `install_pkg.py` loads its own `build_pkg` instance, so patches on the test's `bp` would not reach it. `install_pkg.HOOKS = dict(_bp.HOOKS)` plus its own constants keeps each module patchable. Shared helpers never read `HOOKS`.
- **Splitting install checks from install apply into separate tasks.** Rejected: the `--apply` gate tests (T70/T71, M11/M12/M5) are only meaningful when real apply code exists, so both land in Task 8.
- **Placeholder dispatch lines filled in later.** Rejected in favour of explicit insert-edits:
  - Task 7 inserts the `--verify-only` dispatch into `build_pkg.main`.
  - Task 9 inserts the `accept` dispatch into `install_pkg.main`.
  - Before those tasks the flags fall through to read-only behaviour (a dry run / the plan print).
- **Running the mutation harness in the test suite.** Rejected: spec §15.3 makes it a separate script run by the main thread.

## Caller-requested order → plan task mapping

| Caller item | Plan task |
|---|---|
| 1 layout + manifest schema + copy engine | Task 1 |
| 2 enumeration of 17 components | Task 2 |
| 3 credential gate L1-L4 + `--credential-report` | Task 3 (end-to-end L3/L4 cases in Task 6) |
| 4 R-PRE ordering | Task 6 |
| 5 checks B01-B17 | Task 4 |
| 6 build CLI | Task 6 (+ `--resume`/`--verify-only` in Task 7) |
| 7 install phases + I01-I20 | Task 8 |
| 8 accept | Task 9 |
| 9 remaining test classes | Task 7 (resume/verify), Task 8 (install-apply), Task 5 (README grep rules) |
| 10 mutation harness | Task 10 |
| 11 README content | Task 5 |
| 12 real build on `/Volumes/Ollama` | Task 12 (after Task 11's whole-suite gates) |

## Review Focus

The five failure modes most likely to bite a person using this. Each is pinned by a named test in its owning task.

1. **RF1: a credential file that matches no L1 name and no L2 pattern but IS a real secret.** This is exactly tonight's leak class: the 825-byte `hf_…` tokens do not match `hf_[A-Za-z0-9]{34,40}`.
   - Expected: the build aborts during the copy (exit 5). The partial payload file is deleted. The message names the source path but never the value. No `MANIFEST.json` is written.
   - This holds for a long, multi-chunk secret in an arbitrarily named file, and also for a secret that surfaces in a root file (e.g. pip-freeze output).
   - Pinned by Task 6 `test_RF1_long_jwt_like_token_in_unrecognized_file_is_caught_by_l3` and `test_RF1b_secret_in_a_root_file_aborts_before_payload`, plus T13 (boundary/inside).
2. **RF2: a source file changing underneath the build mid-copy.**
   - Expected: exit 5 with `source changed mid-copy: <src>` (or `since enumeration`). The dst is unlinked and the entry is not listed. A later `--apply --resume` completes, and `--verify-only` passes.
   - Pinned by Task 1 T31a/T31b/T32a, Task 6 T31/T32, Task 7 `test_RF2_resume_after_mid_copy_abort_completes_and_verifies`.
3. **RF3: the 2.5 pack is missing one of its 28 pinned files** (or holds an extra/partial file, or a pinned name that is not a regular file).
   - Expected: B04 FAIL naming `missing=[…]` / `extra=[…]` / `not_regular=[…]`, exit 4, and the package root is never created.
   - Pinned by Task 4 `test_B04_RF3_pack_file_set` and Task 6 `test_RF3_missing_pack_file_refuses_apply_without_creating_root`.
4. **RF4: resuming after a partial or failed attempt.** This covers a torn line, a corrupted listed payload, a changed listed source, `MANIFEST.json` already present, a post-copy (exit 3) failure, and a root that was never created.
   - Expected: the result is byte-identical to an uninterrupted build, or there is a precise B07 refusal.
   - Pinned by Task 4 `test_B07_resume_prefix_analysis`, Task 7 T40-T44, `test_RF4_resume_after_post_copy_failure`, `test_RF4b_resume_without_package_root_refuses`.
5. **RF5: the target-path allowlist letting a component write outside `/Users/reubenpatterson/`, `FRAMEWORK_ROOT` or `USR_LOCAL_BIN`.** This covers prefix-boundary tricks (`/Users/reubenpattersonX`, `…Python.frameworkX`), `..`/`//`/`.` segments, `/Volumes/`, `/opt/homebrew/`, and `home() != REQUIRED_HOME`.
   - Expected: B11 FAIL, exit 4, nothing written.
   - Pinned by Task 4 `test_B11_RF5_target_path_allowlist` (includes C3).

## File Structure

| Path (absolute) | Responsibility |
|---|---|
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/build_pkg.py` | Constants, `HOOKS`, shared helpers (entry I/O, hashing, `CheckResult`, L1/L2/L3/L4), enumeration, B01-B17, README, stage order, copy engine, resume, verify-only, credential report, CLI. |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/install_pkg.py` | Own constants and `HOOKS`; I01-I20; phases preflight/system-python/user/verify/accept; atomic per-file install; receipts; GPU acceptance. |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/credential_allowlist.json` | Human-reviewed L2 allowlist; starts `{"schema_version": 1, "entries": []}`. |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_deploy_pkg.py` | All unit tests (fixture host, fake hooks, T01-T95). |
| `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/mutate_deploy_pkg.py` | The 12-mutation harness plus control. |

**Code layout rules:**
- **build_pkg.py:** tasks append sections in order. Task 6 appends the line `# ---- CLI entry point ----` followed by `main()` and the `__main__` guard. Task 7 inserts its block immediately **above** that marker line.
- **install_pkg.py:** Task 8 creates the whole file ending with the same marker, `parse_args`, `main` and the guard. Task 9 inserts above the marker and makes one edit in `main`.
- **tests/test_deploy_pkg.py:** Task 1 creates it ending with `if __name__ == "__main__":` / `    unittest.main()`. Every later task inserts its code immediately **above** the `if __name__ == "__main__":` line, except the header edit in Task 8.

---

### Task 0: Preconditions, snapshot and baseline (main thread)

**Files:** none are created. This task fills in the Baseline table in this document.

- [ ] **Step 1: Snapshot (CLAUDE.md §3).**
```bash
cd /Users/reubenpatterson/local_model_harness
TS=$(date +%Y%m%d%H%M%S); mkdir -p .claude/snapshots/deploy-pkg-pre-$TS
tar czf .claude/snapshots/deploy-pkg-pre-$TS/workspace-code.tar.gz --exclude qwen-agent-workspace/generated --exclude qwen-agent-workspace/qwen38-6bit qwen-agent-workspace
ls -l .claude/snapshots/deploy-pkg-pre-$TS/workspace-code.tar.gz
```
Expected: one tarball of about 3.5 GB or less (the workspace is 5.2 GB, of which `generated/` is 1.8 GB).

- [ ] **Step 2: Provenance and absence checks.**
```bash
cd /Users/reubenpatterson/local_model_harness
git rev-parse HEAD
for f in z_image_skill.py ltx2_mlx_video_skill.py ltx_image_fit.py content_safety.py bin/ltx-movie bin/ltx-story-images bin/ltx-story-manifest bin/ltx-mlx-render bin/story-server bin/qwen-agent; do rp=qwen-agent-workspace/$f; git ls-files --error-unmatch -- $rp >/dev/null 2>&1 || echo "UNTRACKED $f"; [ -z "$(git status --porcelain -- $rp)" ] || echo "MODIFIED $f"; [ "$(git hash-object $rp)" = "$(git rev-parse HEAD:$rp)" ] || echo "BLOBDIFF $f"; done; echo provenance-done
ls qwen-agent-workspace/scripts/deploy 2>&1
```
Expected:
- HEAD is `6ab72ac…` or a descendant;
- no `UNTRACKED`/`MODIFIED`/`BLOBDIFF` lines, then `provenance-done`;
- `ls: …scripts/deploy: No such file or directory`.

If any file line prints, STOP and report it: B17 would fail.

- [ ] **Step 3: Baseline gates (direct invocation).**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
for f in tests/test_ltx_movie_offline.py tests/test_ltx_mlx_render.py tests/test_ltx_story_images.py tests/test_ltx2_mlx_video_skill.py tests/test_ltx_image_fit.py tests/test_ltx_story_manifest_chain.py tests/check_ltx2_mlx_no_forbidden_imports.py; do /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 $f > /tmp/gate.$$ 2>&1; echo "$f rc=$? $(tail -1 /tmp/gate.$$)"; done
/usr/bin/python3 --version; /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 --version; /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest --version
```
Expected (measured while planning): `OK 316/316`, `OK 431/431`, `OK 98/98`, `OK 138/138`, `OK 73/73`, `OK 32/32`, `RESULT: ok`, all rc=0; Python 3.9.6, 3.13.0; pytest 8.3.4.

**Baseline (fill in):**

| Gate | rc | last line |
|---|---|---|
| G1 test_ltx_movie_offline | 0 | OK 316/316 |
| G2 test_ltx_mlx_render | 0 | OK 431/431 |
| G3 test_ltx_story_images | 0 | OK 98/98 |
| G4 test_ltx2_mlx_video_skill | 0 | OK 138/138 |
| G5 test_ltx_image_fit | 0 | OK 73/73 |
| G6 test_ltx_story_manifest_chain | 0 | OK 32/32 |
| G7 check_ltx2_mlx_no_forbidden_imports | 0 | RESULT: ok |

---

### Task 1: build_pkg.py foundation — constants, hooks, entry format, atomic writes, L3 scanner, copy engine

**Files:**
- Create: `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/build_pkg.py`
- Create: `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/test_deploy_pkg.py`

**Interfaces:**
- Consumes: nothing.
- Produces (used by every later task):
  - constants from Global Constraints plus `GIT = "/usr/bin/git"`, `WS_REPO_PREFIX = "qwen-agent-workspace"`, `PACKAGE_ID_RE`, `PENDING_PREFIX = "PENDING: "`, `ENTRY_KEYS`, `DEPLOY_SCRIPT_FILES = ("build_pkg.py", "install_pkg.py", "credential_allowlist.json")`, `HOST_TIMEOUT = 120`, `FREEZE_TIMEOUT = 300`, `GATE_TIMEOUT = 900`;
  - `HOOKS` (dict with the 14 spec hooks) and `CTX_STATE = {"payload_started": False}`;
  - exceptions `SourceChanged`, `CredentialLeak`, `RPreViolation`;
  - `CheckResult(check_id, ok, message, fatal)` and `format_result(result) -> str`;
  - `_run(argv, timeout=120, env=None, cwd=None) -> (rc, text)`;
  - `home()`, `workspace()`, `repo_root()`, `framework_py()`, `ltx25_model_path()`, `deploy_dir()`, `iso_now()`;
  - `sha256_bytes(data) -> hex`, `sha256_file(path, nocache=False) -> hex`;
  - `mode_str(st) -> "0644"`, `write_all(fd, data)`, `fsync_dir(path)`;
  - `entry_line(entry) -> str` (ends in `\n`), `read_entries(path) -> list[dict]`, `last_line(text) -> str`;
  - `KnownSecretScanner`, `l3_message(name) -> str`, `l3_check_bytes(secrets, data, name)` (raises `CredentialLeak`);
  - `write_package_file(ctx, rel, data, mode) -> sha256 hex` (uses `ctx.package_root`, `ctx.secrets`);
  - `copy_regular_file(src, dst, entry, secrets) -> sha256 hex`.
- Test-file helpers produced: `DEPLOY_DIR`, `load_module`, `bp`, `HOOKED_MODULES`, `FIXED_NOW`, `SECRET_CANARY`, `GITHUB_CANARY`, `unfaked`, `run_main`, `write_file`, `make_link`, `file_sha256`, `snapshot`, `payload_snapshot`, `DeployTestCase`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_deploy_pkg.py` with exactly this content:

```python
#!/usr/bin/env python3
"""tests/test_deploy_pkg.py -- unit tests for scripts/deploy/{build_pkg,install_pkg}.py.

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md (section 15)

Run both ways (the counts differ by design):
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py
    /usr/bin/python3 tests/test_deploy_pkg.py

unittest.TestCase classes with real assertions; never imports pytest; Python
3.9 language level. setUp replaces every HOOKS entry with a fake that raises,
so no test can touch the real system. Secret and pattern canaries and the
forbidden README strings are built by concatenation, so this file never holds
a matching literal.
"""
import ast
import collections
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

DEPLOY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "deploy")


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DEPLOY_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = load_module("build_pkg", "build_pkg.py")
HOOKED_MODULES = [bp]

FIXED_NOW = time.gmtime(1790000000)
SECRET_CANARY = "Lx3." + "k9Qm2vR7" + "Tz5.Wp8N"   # 20 bytes; the "." keeps every L2 pattern from matching
GITHUB_CANARY = "gh" + "p_" + "A" * 36


def unfaked(name):
    def hook(*args, **kwargs):
        raise AssertionError("unfaked hook %s" % name)
    return hook


def run_main(func, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = func(argv)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue(), err.getvalue()


def write_file(path, data=b"x", mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def make_link(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(value, path)


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def snapshot(root):
    """path -> (kind, mode, size, mtime_ns, link value, sha256) for everything under root."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                snap[path] = ("l", None, None, None, os.readlink(path), None)
            elif stat.S_ISDIR(st.st_mode):
                snap[path] = ("d", stat.S_IMODE(st.st_mode), None, st.st_mtime_ns, None, None)
            else:
                snap[path] = ("f", stat.S_IMODE(st.st_mode), st.st_size, st.st_mtime_ns, None, file_sha256(path))
    return snap


def payload_snapshot(pkg_root):
    """Relative view of payload/ for byte-identity (spec 11.3): file bytes, mode and
    mtime_ns; symlink values; directory modes. Directory mtimes are excluded."""
    snap = {}
    base = pkg_root + "/payload"
    for dirpath, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, base)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                snap[rel] = ("l", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                snap[rel] = ("d", stat.S_IMODE(st.st_mode))
            else:
                snap[rel] = ("f", stat.S_IMODE(st.st_mode), st.st_mtime_ns, file_sha256(path))
    return snap


class DeployTestCase(unittest.TestCase):
    def setUp(self):
        for module in HOOKED_MODULES:
            fakes = dict((name, unfaked(name)) for name in list(module.HOOKS))
            patcher = mock.patch.dict(module.HOOKS, fakes)
            patcher.start()
            self.addCleanup(patcher.stop)
        bp.CTX_STATE["payload_started"] = False


class TestLanguageLevel(DeployTestCase):
    def test_T95_scripts_parse_at_python_3_9(self):
        names = sorted(n for n in os.listdir(DEPLOY_DIR) if n.endswith(".py"))
        self.assertIn("build_pkg.py", names)
        for name in names:
            with open(os.path.join(DEPLOY_DIR, name), "rb") as fh:
                source = fh.read().decode("utf-8")
            ast.parse(source, filename=name, feature_version=(3, 9))


class TestPrimitives(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="deploypkg-prim-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None

    def make_src(self, data):
        src = self.tmp + "/src/file.bin"
        write_file(src, data, 0o640)
        os.utime(src, ns=(1700000000123456789, 1700000000123456789))
        st = os.lstat(src)
        entry = {"k": "f", "b": st.st_size, "m": "%04o" % stat.S_IMODE(st.st_mode), "mt": st.st_mtime_ns}
        return src, entry

    def test_constants_verbatim(self):
        self.assertEqual(bp.SCHEMA_VERSION, 4)
        self.assertEqual(bp.CHUNK_SIZE, 8 * 1024 * 1024)
        self.assertEqual(bp.L2_MAX_BYTES, 4 * 1024 * 1024)
        self.assertEqual(bp.MIN_MEMSIZE_BYTES, 51539607552)
        self.assertEqual(bp.BUILD_HEADROOM_BYTES, 5 * 1024 ** 3)
        self.assertEqual(bp.INSTALL_HEADROOM_BYTES, 10 * 1024 ** 3)
        self.assertEqual(bp.STORY_PORT, 8177)
        self.assertEqual((bp.REQUIRED_USER, bp.REQUIRED_HOME), ("reubenpatterson", "/Users/reubenpatterson"))
        self.assertEqual(bp.FRAMEWORK_ROOT, "/Library/Frameworks/Python.framework")
        self.assertEqual(bp.USR_LOCAL_BIN, "/usr/local/bin")
        self.assertEqual(bp.VOLUMES_ROOT, "/Volumes")
        self.assertEqual(bp.FALCONSAI_USB_HUB, "/Volumes/Ollama/hf_home/hub")
        self.assertEqual(bp.BREW_BIN, "/opt/homebrew/bin/brew")
        self.assertEqual(bp.BREW_PY312, "/opt/homebrew/opt/python@3.12/bin/python3.12")
        self.assertEqual(bp.USB_ROOT_DEFAULT, "/Volumes/Ollama")
        self.assertEqual(sorted(bp.HOOKS), sorted(["run", "ismount", "diskutil_personality", "statvfs_free", "port_free", "which", "geteuid", "getpwnam", "getuser", "now_utc", "after_chunk", "after_entry", "http_ok", "sleep"]))

    def test_T06a_entry_line_key_order_and_separators(self):
        link = {"s": True, "l": "x", "t": "/a", "c": "H5", "k": "l", "_src": "/ignored"}
        self.assertEqual(bp.entry_line(link), '{"k":"l","c":"H5","t":"/a","l":"x","s":true}\n')
        f = {"mt": 5, "h": "ab", "m": "0644", "b": 3, "t": "/t", "p": "payload/A1-workspace-code/x", "c": "A1", "k": "f", "_rel": "x"}
        self.assertEqual(bp.entry_line(f), '{"k":"f","c":"A1","p":"payload/A1-workspace-code/x","t":"/t","b":3,"m":"0644","h":"ab","mt":5}\n')
        path = self.tmp + "/e.jsonl"
        write_file(path, (bp.entry_line(link) + "\n" + bp.entry_line(f)).encode("utf-8"))
        self.assertEqual(bp.read_entries(path), [{"k": "l", "c": "H5", "t": "/a", "l": "x", "s": True}, {"k": "f", "c": "A1", "p": "payload/A1-workspace-code/x", "t": "/t", "b": 3, "m": "0644", "h": "ab", "mt": 5}])

    def test_format_result_and_last_line(self):
        self.assertEqual(bp.format_result(bp.CheckResult("B01", True, "ok", True)), "PASS B01 ok")
        self.assertEqual(bp.format_result(bp.CheckResult("B01", False, "bad", True)), "FAIL B01 bad")
        self.assertEqual(bp.format_result(bp.CheckResult("B13", False, "stale", False)), "WARN B13 stale")
        self.assertEqual(bp.format_result(bp.CheckResult("I20", True, bp.PENDING_PREFIX + "later", True)), "PENDING I20 later")
        self.assertEqual(bp.last_line("a\nOK 3/3\n\n"), "OK 3/3")
        self.assertEqual(bp.last_line(""), "")

    def test_scanner_finds_secret_across_chunk_boundary(self):
        secret = SECRET_CANARY.encode("ascii")
        data = b"a" * 50 + secret + b"b" * 50
        chunks = [data[i:i + 64] for i in range(0, len(data), 64)]
        scanner = bp.KnownSecretScanner([secret])
        self.assertEqual([scanner.feed(c) for c in chunks], [False, True])
        self.assertNotIn(SECRET_CANARY, repr(scanner))
        self.assertEqual(repr(scanner), "<KnownSecretScanner values=1>")
        self.assertFalse(bp.KnownSecretScanner([]).feed(data))

    def test_write_package_file_is_atomic_and_l3_scanned(self):
        ctx = types.SimpleNamespace(package_root=self.tmp + "/pkg", secrets=[SECRET_CANARY.encode("ascii")])
        os.makedirs(ctx.package_root)
        digest = bp.write_package_file(ctx, "manifests/a.json", b'{"a": 1}\n', 0o644)
        self.assertEqual(digest, hashlib.sha256(b'{"a": 1}\n').hexdigest())
        self.assertEqual(sorted(os.listdir(ctx.package_root + "/manifests")), ["a.json"])
        self.assertEqual(stat.S_IMODE(os.lstat(ctx.package_root + "/manifests/a.json").st_mode), 0o644)
        with self.assertRaises(bp.CredentialLeak) as cm:
            bp.write_package_file(ctx, "manifests/b.json", b"x" + SECRET_CANARY.encode("ascii"), 0o644)
        self.assertIn("manifests/b.json", str(cm.exception))
        self.assertNotIn(SECRET_CANARY, str(cm.exception))
        self.assertEqual(sorted(os.listdir(ctx.package_root + "/manifests")), ["a.json"])

    def test_T30a_copy_preserves_bytes_mode_mtime(self):
        data = os.urandom(1000)
        src, entry = self.make_src(data)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            digest = bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        with open(dst, "rb") as fh:
            self.assertEqual(fh.read(), data)
        st = os.lstat(dst)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640)
        self.assertEqual(st.st_mtime_ns, entry["mt"])

    def test_T31a_append_mid_copy_raises_mid_copy(self):
        src, entry = self.make_src(b"x" * 200)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        state = {"done": False}

        def after_chunk(path, nbytes):
            if not state["done"]:
                state["done"] = True
                with open(path, "ab") as fh:
                    fh.write(b"appended")
        bp.HOOKS["after_chunk"] = after_chunk
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.SourceChanged) as cm:
                bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(str(cm.exception), "source changed mid-copy: " + src)
        self.assertFalse(os.path.lexists(dst))

    def test_T31b_same_size_rewrite_mid_copy_raises_mid_copy(self):
        src, entry = self.make_src(b"x" * 200)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        state = {"done": False}

        def after_chunk(path, nbytes):
            if not state["done"]:
                state["done"] = True
                fd = os.open(path, os.O_WRONLY)
                os.pwrite(fd, b"Y", 150)
                os.close(fd)
                os.utime(path, ns=(entry["mt"] + 1000, entry["mt"] + 1000))
        bp.HOOKS["after_chunk"] = after_chunk
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.SourceChanged) as cm:
                bp.copy_regular_file(src, dst, entry, [])
        self.assertEqual(str(cm.exception), "source changed mid-copy: " + src)
        self.assertFalse(os.path.lexists(dst))

    def test_T32a_changed_since_enumeration(self):
        src, entry = self.make_src(b"x" * 200)
        write_file(src, b"x" * 201, 0o640)
        with self.assertRaises(bp.SourceChanged) as cm:
            bp.copy_regular_file(src, self.tmp + "/pkg/payload/X/file.bin", entry, [])
        self.assertEqual(str(cm.exception), "source changed since enumeration: " + src)

    def test_T13a_known_secret_in_copy_deletes_partial_dst(self):
        secret = SECRET_CANARY.encode("ascii")
        src, entry = self.make_src(b"a" * 50 + secret + b"b" * 50)
        dst = self.tmp + "/pkg/payload/X/file.bin"
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            with self.assertRaises(bp.CredentialLeak) as cm:
                bp.copy_regular_file(src, dst, entry, [secret])
        self.assertIn(src, str(cm.exception))
        self.assertNotIn(SECRET_CANARY, str(cm.exception))
        self.assertFalse(os.path.lexists(dst))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py`
Expected: collection ERROR `FileNotFoundError` for `scripts/deploy/build_pkg.py`.

- [ ] **Step 3: Write the implementation** — create `scripts/deploy/build_pkg.py` with exactly this content:

```python
#!/usr/bin/env python3
"""build_pkg.py -- build the ltx-chain USB deployment package (schema 4).

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md
Plan: docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md

Runs on the source host under
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3. Written at the
Python 3.9 language level because install_pkg.py loads this file under Apple's
/usr/bin/python3 (3.9.6) for the shared helpers (R8). Stdlib only. Importing
this module has no side effects: all work happens in main().
"""
import argparse
import collections
import configparser
import fcntl
import getpass
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import traceback
import urllib.request

# ---------------------------------------------------------------------------
# Constants (spec 5.3). Read at call time; never captured in default arguments.
# ---------------------------------------------------------------------------
REQUIRED_USER = "reubenpatterson"
REQUIRED_HOME = "/Users/reubenpatterson"
FRAMEWORK_ROOT = "/Library/Frameworks/Python.framework"
USR_LOCAL_BIN = "/usr/local/bin"
VOLUMES_ROOT = "/Volumes"
FALCONSAI_USB_HUB = "/Volumes/Ollama/hf_home/hub"
BREW_BIN = "/opt/homebrew/bin/brew"
BREW_PY312 = "/opt/homebrew/opt/python@3.12/bin/python3.12"
USB_ROOT_DEFAULT = "/Volumes/Ollama"
CHUNK_SIZE = 8 * 1024 * 1024
L2_MAX_BYTES = 4 * 1024 * 1024
SCHEMA_VERSION = 4
MIN_MEMSIZE_BYTES = 51539607552          # 48 GiB
BUILD_HEADROOM_BYTES = 5 * 1024 ** 3
INSTALL_HEADROOM_BYTES = 10 * 1024 ** 3
STORY_PORT = 8177

GIT = "/usr/bin/git"
WS_REPO_PREFIX = "qwen-agent-workspace"
PACKAGE_ID_RE = re.compile(r"^ltx-chain-deploy-[0-9]{8}$")
PENDING_PREFIX = "PENDING: "
ENTRY_KEYS = ("k", "c", "p", "t", "b", "m", "h", "mt", "l", "s")
DEPLOY_SCRIPT_FILES = ("build_pkg.py", "install_pkg.py", "credential_allowlist.json")
HOST_TIMEOUT = 120
FREEZE_TIMEOUT = 300
GATE_TIMEOUT = 900


# ---------------------------------------------------------------------------
# Hooks: every real external probe goes through HOOKS; tests replace entries.
# ---------------------------------------------------------------------------
def _real_run(argv, timeout=120, env=None, cwd=None):
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, env=env, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or b""
        return 124, partial.decode("utf-8", "replace")
    except OSError as exc:
        return 127, "%s: %s" % (argv[0], exc)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _real_diskutil_personality(path):
    rc, text = _real_run(["/usr/sbin/diskutil", "info", path], timeout=60)
    if rc != 0:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("File System Personality:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _real_statvfs_free(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _real_port_free(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _real_http_ok(url):
    try:
        response = urllib.request.urlopen(url, timeout=10)
        try:
            return response.status == 200
        finally:
            response.close()
    except Exception:
        return False


def _noop_after_chunk(src, nbytes):
    return None


def _noop_after_entry(index):
    return None


HOOKS = {
    "run": _real_run,
    "ismount": os.path.ismount,
    "diskutil_personality": _real_diskutil_personality,
    "statvfs_free": _real_statvfs_free,
    "port_free": _real_port_free,
    "which": shutil.which,
    "geteuid": os.geteuid,
    "getpwnam": pwd.getpwnam,
    "getuser": getpass.getuser,
    "now_utc": time.gmtime,
    "after_chunk": _noop_after_chunk,
    "after_entry": _noop_after_entry,
    "http_ok": _real_http_ok,
    "sleep": time.sleep,
}

CTX_STATE = {"payload_started": False}


class SourceChanged(Exception):
    """A source file differs from its enumeration, or changed while being copied."""


class CredentialLeak(Exception):
    """L3 or L4 found secret material headed into the package."""


class RPreViolation(Exception):
    """A subprocess was requested after the first payload byte (rule R-PRE)."""


CheckResult = collections.namedtuple("CheckResult", "check_id ok message fatal")


def format_result(result):
    if result.ok:
        if result.message.startswith(PENDING_PREFIX):
            return "PENDING %s %s" % (result.check_id, result.message[len(PENDING_PREFIX):])
        return "PASS %s %s" % (result.check_id, result.message)
    if result.fatal:
        return "FAIL %s %s" % (result.check_id, result.message)
    return "WARN %s %s" % (result.check_id, result.message)


def _run(argv, timeout=120, env=None, cwd=None):
    if CTX_STATE["payload_started"]:
        raise RPreViolation(argv[0])
    return HOOKS["run"](argv, timeout=timeout, env=env, cwd=cwd)


# ---------------------------------------------------------------------------
# Paths computed at call time
# ---------------------------------------------------------------------------
def home():
    return os.path.expanduser("~")


def workspace():
    return home() + "/local_model_harness/qwen-agent-workspace"


def repo_root():
    return home() + "/local_model_harness"


def framework_py():
    return FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"


def ltx25_model_path():
    return home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def deploy_dir():
    return os.path.dirname(os.path.abspath(__file__))


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", HOOKS["now_utc"]())


# ---------------------------------------------------------------------------
# Hashing, entry I/O, atomic writes
# ---------------------------------------------------------------------------
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path, nocache=False):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY)
    try:
        if nocache and hasattr(fcntl, "F_NOCACHE"):
            try:
                fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
            except OSError:
                pass
        while True:
            chunk = os.read(fd, CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def mode_str(st):
    return "%04o" % stat.S_IMODE(st.st_mode)


def write_all(fd, data):
    view = memoryview(data)
    offset = 0
    while offset < len(data):
        offset += os.write(fd, view[offset:])


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def entry_line(entry):
    ordered = dict((key, entry[key]) for key in ENTRY_KEYS if key in entry)
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False) + "\n"


def read_entries(path):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def last_line(text):
    stripped = text.rstrip()
    return stripped.splitlines()[-1] if stripped else ""


# ---------------------------------------------------------------------------
# L3 known-secret scanner (spec 8.3, exact)
# ---------------------------------------------------------------------------
class KnownSecretScanner(object):
    def __init__(self, secrets):
        self.secrets = list(secrets)
        self.keep = max(len(s) for s in self.secrets) - 1 if self.secrets else 0
        self.tail = b""

    def feed(self, chunk):
        window = self.tail + chunk
        for s in self.secrets:
            if window.find(s) != -1:
                return True
        self.tail = window[-self.keep:] if self.keep else b""
        return False

    def __repr__(self):
        return "<KnownSecretScanner values=%d>" % len(self.secrets)


def l3_message(name):
    return ("L3: a known secret value was found in %s; the partial payload file was deleted "
            "and no MANIFEST.json was written" % name)


def l3_check_bytes(secrets, data, name):
    if KnownSecretScanner(secrets).feed(data):
        raise CredentialLeak(l3_message(name))


def write_package_file(ctx, rel, data, mode):
    """L3-scan data, write <dir>/.<name>.tmp, fsync, chmod, os.replace, fsync the dir."""
    l3_check_bytes(ctx.secrets, data, rel)
    final = ctx.package_root + "/" + rel
    parent = os.path.dirname(final)
    os.makedirs(parent, exist_ok=True)
    tmp = parent + "/." + os.path.basename(final) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, final)
    fsync_dir(parent)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Copy engine (spec 11.1)
# ---------------------------------------------------------------------------
def copy_regular_file(src, dst, entry, secrets):
    before = os.lstat(src)
    if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime_ns) != (entry["b"], entry["mt"]):
        raise SourceChanged("source changed since enumeration: %s" % src)
    before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    scanner = KnownSecretScanner(secrets)
    digest = hashlib.sha256()
    total = 0
    src_fd = os.open(src, os.O_RDONLY)
    try:
        dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError:
        os.close(src_fd)
        raise
    try:
        while True:
            chunk = os.read(src_fd, CHUNK_SIZE)
            if not chunk:
                break
            if scanner.feed(chunk):
                os.close(dst_fd)
                dst_fd = -1
                os.close(src_fd)
                src_fd = -1
                os.unlink(dst)
                raise CredentialLeak(l3_message(src))
            write_all(dst_fd, chunk)
            digest.update(chunk)
            total += len(chunk)
            HOOKS["after_chunk"](src, total)
        os.fsync(dst_fd)
    finally:
        if dst_fd != -1:
            os.close(dst_fd)
        if src_fd != -1:
            os.close(src_fd)
    after = os.lstat(src)
    after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_key != after_key:
        os.unlink(dst)
        raise SourceChanged("source changed mid-copy: %s" % src)
    os.chmod(dst, int(entry["m"], 8))
    os.utime(dst, ns=(entry["mt"], entry["mt"]))
    if os.lstat(dst).st_size != entry["b"]:
        os.unlink(dst)
        raise SourceChanged("copied size differs from the enumerated size: %s" % src)
    return digest.hexdigest()
```

Notes for the implementer:
- The imports `argparse`, `configparser`, `platform`, `traceback` are unused until Tasks 2-6. Keep them anyway, so later tasks never edit the header.
- The line `    if before_key != after_key:` is a mutation anchor (M6); keep it exactly.
- The line `        self.tail = window[-self.keep:] if self.keep else b""` contains anchor M2; keep it exactly.

- [ ] **Step 4: Run the tests to verify they pass (both interpreters).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py; echo rc=$?`
Expected: `11 passed`, rc=0.

Run: `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -3; /usr/bin/python3 tests/test_deploy_pkg.py >/dev/null 2>&1; echo rc=$?`
Expected: `Ran 11 tests`, last line `OK`, rc=0.

- [ ] **Step 5: Negative control.** Temporarily change `self.tail = window[-self.keep:] if self.keep else b""` to `self.tail = b""`, then rerun pytest.
  - Expected: `test_scanner_finds_secret_across_chunk_boundary` and `test_T13a_…` FAIL.
  - Revert, rerun, and confirm 11 passed.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: build_pkg foundation (hooks, schema-4 entries, L3 scanner, copy engine)"
```

---

### Task 2: Component enumeration (all 17 components)

**Files:**
- Modify: `scripts/deploy/build_pkg.py` (append a section at the end of the file)
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes (Task 1): `mode_str`, `home`, `workspace`, `framework_py`, `ltx25_model_path`, constants.
- Produces:
  - constants: `COMPONENT_ORDER`, `SLUGS`, `PIPELINE_FILES`, `TEST_FILES`, `A1_FILES`, `A1_DIRS`, `A2_DIR_REL`, `A2_FILES`, `L1_NAMES`, `PRUNE_DIRS`, `B1_EXCLUDES`, `B4_EXCLUDES`, `F1_EXCLUDES`, `F3_EXCLUDES`, `UV_CPYTHON_DIR`, `F2_FRAMEWORK_LINKS`, `F2_BIN_LINKS`, `LTX25_PACK_FILES`, `HF_PINS` (cid → `(repo_dirname, pin)`);
  - `class BuildCtx(args)` with the attributes listed in the code;
  - `parse_args(argv) -> argparse.Namespace` (flags `--dry-run --apply --verify-only --credential-report --resume --usb-root --package-id`);
  - `default_package_id()`, `payload_prefix(cid) -> "payload/<cid>-<slug>"`, `b3_source()`, `select_falconsai_hub() -> str|None`, `walk_tree(ctx, cid, src_root, dst_root, excludes) -> list`, `enum_a1(ctx)`, `enum_a2(ctx)`, `enum_f2(ctx)`, `synthetic_dir(cid, t)`, `h5_link_value()`, `sort_component(entries)`, `component_stats(entries) -> dict`, `stats_totals(stats) -> dict`, `enumerate_components(ctx)` (sets `ctx.entries`, `ctx.comp_stats`, `ctx.falconsai_hub`, appends to `ctx.enum_errors`/`ctx.l1_hits`).
  - Every entry dict also carries internal keys `_src` (absolute source path; absent for synthetic entries) and `_rel` (component-relative path: `WS`-relative for A1, basename for A2, the tree-relative path for trees, `""` for tree roots). `entry_line` never writes them.
- Test helpers produced: `PIPELINE`, `TESTS7`, `LEGACY`, `PACK28`, `BIN_LINKS13`, `PINS`, `ORDER`, `HEAD_SHA`, `VLLM_OUT`, `GATE_OUT`, `GATE_ARGV`, `X2_ARGV`, `GEOMS`, `git_blob`, `_under_path`, `FixtureRun`, `Fixture` (methods `cleanup`, `patch_build_module`, `write_deploy_dir`, `write_allowlist`, `make_repo`, `build_sources`, `configure_build_hooks`, `ctx`), `expected_keys`, `order_by_spec`.

- [ ] **Step 1: Write the failing tests.** Insert this block into `tests/test_deploy_pkg.py` immediately above `if __name__ == "__main__":`. The `FixtureRun` table deliberately already holds the install/accept argv that Tasks 8-9 use, so later tasks never edit it.

```python
PIPELINE = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py",
            "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
            "bin/story-server", "bin/qwen-agent")
TESTS7 = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
          "tests/test_ltx2_mlx_video_skill.py", "tests/test_ltx_image_fit.py",
          "tests/test_ltx_story_manifest_chain.py", "tests/check_ltx2_mlx_no_forbidden_imports.py")
LEGACY = ("ltx_video_skill.py", "mps_guard.py", "flux_skill.py", "bin/ltx-chain", "bin/ltx-generate",
          "bin/ltx-host-prep", "bin/ltx-host-restore", "bin/ltx-story-video", "bin/pad-images", "start_vllm.sh")
PACK28 = (".gitattributes", "LICENSE", "README.md", "audio_vae.safetensors", "chat_template.jinja",
          "connector.safetensors", "duration_head.safetensors", "embedded_config.json", "generation_config.json",
          "ltx-2.5-22b-distilled-lora-450-bf16.safetensors", "processor_config.json", "quantize_config.json",
          "spatial_upscaler_x2_v1_0.safetensors", "spatial_upscaler_x2_v1_0_config.json", "split_model.json",
          "temporal_upscaler_x2_v1_0.safetensors", "temporal_upscaler_x2_v1_0_config.json",
          "text_encoder.safetensors", "text_encoder_config.json", "tokenizer.json", "tokenizer_config.json",
          "transformer-dev.safetensors", "transformer-distilled.safetensors", "vae_decoder_av.safetensors",
          "vae_decoder_conv.safetensors", "vae_encoder_av.safetensors", "vae_encoder_conv.safetensors",
          "vocoder.safetensors")
BIN_LINKS13 = ("idle3", "idle3.13", "pip3", "pip3.13", "pydoc3", "pydoc3.13", "python3", "python3-config",
               "python3-intel64", "python3.13", "python3.13-config", "python3.13-intel64", "python")
PINS = {
    "H1": ("models--Tongyi-MAI--Z-Image-Turbo", "f332072aa78be7aecdf3ee76d5c247082da564a6"),
    "H2": ("models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1", "ce497d288a7ddfd5d0f337c7139349d5d0236bfa"),
    "H3": ("models--Falconsai--nsfw_image_detection", "96cb0d0342c7afb80cab76ecc58b265fa44da256"),
    "H4": ("models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx", "5428d6aaca0103a1e32f47261a20fecaa47700ec"),
}
ORDER = ("A1", "A2", "B1", "B2", "B3", "B4", "B5", "D1", "F1", "F2", "F3", "H0", "H1", "H2", "H3", "H4", "H5")
HEAD_SHA = "6ab72ac3f29e8d68e06095574bcbd97d8f621240"
VLLM_OUT = ("INFO 09-25 07:36:25 [__init__.py:52] Available plugins for group vllm.platform_plugins:\n"
            "INFO 09-25 07:36:27 [__init__.py:237] Platform plugin metal is activated\n0.27.1\n")
GATE_OUT = {"G1": "OK 118/118", "G2": "OK 431/431", "G3": "OK 98/98", "G4": "OK 138/138",
            "G5": "OK 73/73", "G6": "OK 32/32", "G7": "RESULT: ok"}
GATE_ARGV = {"G1": "tests/test_ltx_movie_offline.py", "G2": "tests/test_ltx_mlx_render.py",
             "G3": "tests/test_ltx_story_images.py", "G4": "tests/test_ltx2_mlx_video_skill.py",
             "G5": "tests/test_ltx_image_fit.py", "G6": "tests/test_ltx_story_manifest_chain.py",
             "G7": "tests/check_ltx2_mlx_no_forbidden_imports.py"}
X2_ARGV = ("bin/ltx-movie", "a test narrative", "--story-id", "deploy-gate-dry", "--dry-run", "--no-review",
           "--model", "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8")
GEOMS = {"portrait": (320, 576, 320, 576), "wide": (960, 320, 960, 320),
         "square": (512, 512, 512, 512), "noseed": (704, 448, 1408, 896)}


def git_blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _under_path(path, root):
    return path == root or path.startswith(root + "/")


class FixtureRun(object):
    """Fake HOOKS["run"]: argv-keyed responses for every command build_pkg and install_pkg issue."""

    def __init__(self, fx):
        self.fx = fx
        self.overrides = {}
        self.calls = []
        self.kwcalls = []
        self.memsize = "68719476736"
        self.fw_version = "3.13.0"
        self.zsh_hf_home = None
        self.freeze_text = "pkg==1.0\n"
        self.media_overrides = {}

    def __call__(self, argv, timeout=120, env=None, cwd=None):
        key = tuple(argv)
        self.calls.append(key)
        self.kwcalls.append((key, timeout, cwd))
        self.fx.events.append(("run", key))
        if key in self.overrides:
            value = self.overrides[key]
            return value(key) if callable(value) else value
        if key and key[0] == bp.GIT:
            return self.git(key)
        table = self.table()
        if key in table:
            return table[key]
        if key and key[0] in (self.fx.ffprobe, self.fx.ffmpeg) and len(key) > 2:
            return self.media(key)
        raise AssertionError("unfaked run argv %r" % (key,))

    def table(self):
        fx = self.fx
        t = {
            ("/usr/sbin/sysctl", "-n", "hw.model"): (0, "Mac16,9\n"),
            ("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"): (0, "Apple M4 Max\n"),
            ("/usr/sbin/sysctl", "-n", "hw.memsize"): (0, self.memsize + "\n"),
            ("/usr/bin/sw_vers", "-productVersion"): (0, "26.0\n"),
            ("/usr/bin/sw_vers", "-buildVersion"): (0, "25A100\n"),
            (fx.fw_py, "-c", "import sys;print(sys.version.split()[0])"): (0, self.fw_version + "\n"),
            (fx.ffmpeg, "-version"): (0, "ffmpeg version 9.0.1 Copyright (c) 2000-2026 the FFmpeg developers\nbuilt with Apple clang\n"),
            (fx.ffprobe, "-version"): (0, "ffprobe version 9.0.1 Copyright (c) 2007-2026 the FFmpeg developers\n"),
            (fx.brew_bin, "--version"): (0, "Homebrew 5.0.0\n"),
            (fx.brew_py312, "--version"): (0, "Python 3.12.9\n"),
            (fx.vllm_py, "-c", "import vllm; print(vllm.__version__)"): (0, VLLM_OUT),
            (fx.fw_py, "-m", "pip", "freeze", "--all", "--exclude", "fubotv-mcp-common", "--exclude", "student-agent-mcp"): (0, self.freeze_text),
            (fx.fw + "/Versions/3.13/bin/uv", "pip", "freeze", "--python", fx.home + "/ltx-2-mlx/.venv/bin/python"): (0, "ltx-core==0.15.4\n"),
            (fx.vllm_py, "-m", "pip", "freeze", "--all"): (0, "vllm==0.27.1\n"),
            (fx.fw_py, "bin/ltx-mlx-render", "--help"): (0, "usage: ltx-mlx-render [-h]\n"),
            (fx.fw_py,) + X2_ARGV: (0, "dry run: 2 panels\n"),
            ("/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'): (0, self.zsh_hf_home if self.zsh_hf_home is not None else fx.home + "/hf_home"),
            (fx.fw_py, "-s", "-c", "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])"): (0, "3.13.0\n"),
            (fx.fw_py, "-c", "import torch, diffusers, transformers, PIL, numpy, safetensors, psutil, pytest, pexpect"): (0, ""),
            (fx.vllm_py, "-c", "import vllm, vllm_metal, mlx_vlm; print(vllm.__version__)"): (0, VLLM_OUT.replace("07:36:2", "08:00:0")),
            (fx.home + "/ltx-2-mlx/.venv/bin/ltx-2-mlx", "--help"): (0, "usage: ltx-2-mlx [-h]\n"),
            (fx.ws + "/bin/story-server",): (2, "usage: story-server [vision|text|status|stop]\n"),
            (fx.ws + "/bin/story-server", "vision"): (0, ""),
            (fx.ws + "/bin/story-server", "stop"): (0, ""),
            ("/usr/bin/pgrep", "-fl", "ltx-2-mlx|z_image|mlx_lm|vllm"): (1, ""),
            ("/usr/sbin/sysctl", "-n", "vm.swapusage"): (0, "total = 2048.00M  used = 100.00M  free = 1948.00M  (encrypted)\n"),
        }
        for gid, rel in GATE_ARGV.items():
            t[(fx.fw_py, rel)] = (0, "running\n" + GATE_OUT[gid] + "\n")
        return t

    def git(self, key):
        fx = self.fx
        if key[1] != "-C" or key[2] != fx.repo:
            raise AssertionError("git must run as git -C <repo>: %r" % (key,))
        cmd = key[3:]
        if cmd == ("rev-parse", "HEAD"):
            return (0, HEAD_SHA + "\n")
        if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
            return (0, "ltx2-mlx-video-pipeline\n")
        if cmd == ("status", "--porcelain", "--", "qwen-agent-workspace"):
            return (0, "".join(" M %s\n" % rp for rp in sorted(fx.modified)))
        if cmd[:3] == ("ls-files", "--error-unmatch", "--"):
            rp = cmd[3]
            if rp in fx.untracked:
                return (1, "error: pathspec '%s' did not match any file(s) known to git\n" % rp)
            return (0, rp + "\n")
        if cmd[:3] == ("status", "--porcelain", "--"):
            rp = cmd[3]
            if rp in fx.untracked:
                return (0, "?? %s\n" % rp)
            return (0, " M %s\n" % rp) if rp in fx.modified else (0, "")
        if cmd[0] == "hash-object":
            with open(cmd[1], "rb") as fh:
                return (0, git_blob(fh.read()) + "\n")
        if cmd[0] == "rev-parse" and cmd[1].startswith("HEAD:"):
            rp = cmd[1][len("HEAD:"):]
            if rp in fx.untracked:
                return (128, "fatal: path '%s' does not exist in 'HEAD'\n" % rp)
            if rp in fx.committed:
                return (0, fx.committed[rp] + "\n")
            with open(fx.repo + "/" + rp, "rb") as fh:
                return (0, git_blob(fh.read()) + "\n")
        raise AssertionError("unfaked git argv %r" % (key,))

    def media(self, key):
        fx = self.fx
        path = key[-1] if key[0] == fx.ffprobe else key[key.index("-i") + 1]
        found = re.search(r"deploy-accept-(portrait|wide|square|noseed)-", path)
        label = found.group(1) if found else "portrait"
        width, height, still_w, still_h = GEOMS[label]
        media = self.media_overrides.get(label, {})
        if key[0] == fx.ffprobe:
            select = key[key.index("-select_streams") + 1]
            if path.endswith(".png"):
                stream = {"width": media.get("still_w", still_w), "height": media.get("still_h", still_h)}
            elif select == "a:0":
                stream = {"codec_name": media.get("audio", "aac")}
            else:
                stream = {"width": media.get("w", width), "height": media.get("h", height),
                          "codec_name": media.get("vcodec", "h264"), "nb_read_frames": media.get("frames", "290")}
            return (0, json.dumps({"streams": [stream]}) + "\n")
        default = ["0,0,0,1,6220800,ac2833aa09711810c612e6b20955113e"]
        rows = media.get("rows_seed" if path.endswith(".chainseed.png") else "rows_clip", default)
        return (0, "#format: frame checksums\n#version: 2\n" + "".join(row + "\n" for row in rows))


class Fixture(object):
    """A fake source host under one temp dir (Task 8's InstallFixture turns it into a fake target)."""

    def __init__(self, tc):
        self.tc = tc
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="deploypkg-"))
        tc.addCleanup(self.cleanup)
        self.home = self.root + "/Users/reubenpatterson"
        self.ws = self.home + "/local_model_harness/qwen-agent-workspace"
        self.repo = self.home + "/local_model_harness"
        self.fw = self.root + "/Library/Frameworks/Python.framework"
        self.ulb = self.root + "/usr/local/bin"
        self.volumes = self.root + "/Volumes"
        self.usb = self.volumes + "/USB"
        self.usb2 = self.volumes + "/USB2"
        self.usb_hub = self.usb + "/hf_home/hub"
        self.brew_bin = self.root + "/opt/homebrew/bin/brew"
        self.brew_py312 = self.root + "/opt/homebrew/opt/python@3.12/bin/python3.12"
        self.ffmpeg = self.root + "/opt/homebrew/bin/ffmpeg"
        self.ffprobe = self.root + "/opt/homebrew/bin/ffprobe"
        self.deploy = self.root + "/deploy"
        self.package_id = "ltx-chain-deploy-20260925"
        self.pkg = self.usb + "/" + self.package_id
        self.fw_py = self.fw + "/Versions/3.13/bin/python3"
        self.vllm_py = self.home + "/.venv-vllm-metal/bin/python"
        self.mounts = set([self.usb, self.usb2])
        self.untracked = set()
        self.modified = set()
        self.committed = {}
        self.events = []
        self.allowlist_entries = []
        self.run = FixtureRun(self)
        for path in (self.home, self.usb, self.usb2, self.deploy, self.ulb):
            os.makedirs(path)
        self.patch_build_module()

    def cleanup(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            for name in dirnames:
                path = os.path.join(dirpath, name)
                if not os.path.islink(path):
                    os.chmod(path, 0o755)
        shutil.rmtree(self.root, True)

    def patch_build_module(self):
        values = {"REQUIRED_HOME": self.home, "FRAMEWORK_ROOT": self.fw, "USR_LOCAL_BIN": self.ulb,
                  "VOLUMES_ROOT": self.volumes, "FALCONSAI_USB_HUB": self.usb_hub, "BREW_BIN": self.brew_bin,
                  "BREW_PY312": self.brew_py312, "USB_ROOT_DEFAULT": self.usb}
        patchers = [mock.patch.object(bp, name, value) for name, value in sorted(values.items())]
        patchers.append(mock.patch.object(bp, "deploy_dir", lambda: self.deploy))
        patchers.append(mock.patch.dict(os.environ, {"HOME": self.home}))
        for patcher in patchers:
            patcher.start()
            self.tc.addCleanup(patcher.stop)
        for name in ("HF_TOKEN", "HF_HOME", "Z_IMAGE_HF_HOME", "LTX2_MLX_HF_HOME", "HF_HUB_CACHE",
                     "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
            os.environ.pop(name, None)

    def write_deploy_dir(self):
        for name in ("build_pkg.py", "install_pkg.py"):
            real = os.path.join(DEPLOY_DIR, name)
            if os.path.exists(real):
                with open(real, "rb") as fh:
                    data = fh.read()
            else:
                data = b"# install_pkg.py stand-in written by the test fixture before Task 8 exists\n"
            write_file(self.deploy + "/" + name, data, 0o755)
        self.write_allowlist()

    def write_allowlist(self, entries=None):
        if entries is not None:
            self.allowlist_entries = entries
        doc = {"schema_version": 1, "entries": self.allowlist_entries}
        write_file(self.deploy + "/credential_allowlist.json", (json.dumps(doc, indent=2) + "\n").encode("utf-8"))

    def make_repo(self, hub, repo, pin):
        root = hub + "/" + repo
        blob = hashlib.sha1(repo.encode("utf-8")).hexdigest()
        write_file(root + "/blobs/" + blob, ("weights for %s\n" % repo).encode("utf-8"))
        write_file(root + "/refs/main", pin.encode("ascii"))
        make_link(root + "/snapshots/" + pin + "/config.json", "../../blobs/" + blob)
        write_file(root + "/.DS_Store", b"ds")

    def build_sources(self):
        H, WS = self.home, self.ws
        for rel in PIPELINE + TESTS7:
            write_file(WS + "/" + rel, ("# fixture %s\n" % rel).encode("utf-8"), 0o755 if rel.startswith("bin/") else 0o644)
        for rel in LEGACY:
            write_file(WS + "/" + rel, b"# legacy, never shipped\n")
        for name in ("portrait.png", "wide3x1.png", "square.png"):
            write_file(WS + "/generated/hw_gate_seeds/" + name, b"\x89PNG fixture " + name.encode("ascii"))
        write_file(WS + "/generated/hw_gate_seeds/last_portrait.sid", b"sid\n")
        write_file(WS + "/__pycache__/z_image_skill.cpython-313.pyc", b"pyc")
        L = H + "/ltx-2-mlx"
        write_file(L + "/README.md", b"ltx-2-mlx fixture\n")
        write_file(L + "/packages/ltx_core/__init__.py", b"# core\n")
        write_file(L + "/packages/ltx_core/__pycache__/__init__.cpython-311.pyc", b"pyc")
        write_file(L + "/packages/.DS_Store", b"ds")
        write_file(L + "/.git/HEAD", b"ref: refs/heads/main\n")
        for name in ("hf_cache/hub", "converted_models", "source_caches", ".claude", "models/other-model"):
            write_file(L + "/" + name + "/excluded.txt", b"excluded\n")
        B3 = H + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none"
        write_file(B3 + "/bin/python3.11", b"#!fake\n", 0o755)
        make_link(B3 + "/bin/python3", "python3.11")
        write_file(B3 + "/lib/libpython3.11.dylib", b"dylib")
        V = L + "/.venv"
        write_file(V + "/pyvenv.cfg", ("home = %s/bin\nversion_info = 3.11.13\n" % B3).encode("utf-8"))
        make_link(V + "/bin/python", B3 + "/bin/python3.11")
        write_file(V + "/bin/ltx-2-mlx", b"#!fake\n", 0o755)
        write_file(V + "/lib/python3.11/site-packages/ltx_pipelines.pth", (L + "/packages/ltx_core\n").encode("utf-8"))
        write_file(V + "/lib/python3.11/site-packages/__pycache__/x.cpython-311.pyc", b"pyc")
        P = L + "/models/ltx-2.5-mlx-q8"
        for name in PACK28:
            write_file(P + "/" + name, ("pack:%s\n" % name).encode("utf-8"))
        write_file(P + "/.cache/huggingface/download/x.metadata", b"cache")
        write_file(P + "/.DS_Store", b"ds")
        os.chmod(P, 0o750)
        D = H + "/.venv-vllm-metal"
        write_file(D + "/pyvenv.cfg", ("home = %s\nversion_info = 3.12.9\n" % os.path.dirname(self.brew_py312)).encode("utf-8"))
        make_link(D + "/bin/python", self.brew_py312)
        write_file(D + "/lib/python3.12/site-packages/vllm/__init__.py", b"__version__ = '0.27.1'\n")
        write_file(D + "/lib/python3.12/site-packages/vllm/.mypy_cache/x", b"cache")
        F = self.fw + "/Versions/3.13"
        write_file(F + "/bin/python3.13", b"#!fake\n", 0o755)
        make_link(F + "/bin/python3", "python3.13")
        SP = F + "/lib/python3.13/site-packages"
        write_file(SP + "/psutil/__init__.py", b"# psutil\n")
        write_file(SP + "/psutil/__pycache__/__init__.cpython-313.pyc", b"pyc")
        write_file(SP + "/.ruff_cache/x", b"cache")
        write_file(SP + "/.pytest_cache/x", b"cache")
        for name in ("__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
                     "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth"):
            write_file(SP + "/" + name, b"# editable reference\n")
        write_file(SP + "/fubotv_mcp_common-0.1.0.dist-info/METADATA", b"Name: fubotv-mcp-common\n")
        write_file(SP + "/student_agent_mcp-1.0.0.dist-info/METADATA", b"Name: student-agent-mcp\n")
        for name in ("Headers", "Python", "Resources"):
            make_link(self.fw + "/" + name, "Versions/Current/" + name)
        make_link(self.fw + "/Versions/Current", "3.13")
        os.chmod(self.fw + "/Versions", 0o775)
        for name in BIN_LINKS13:
            value = self.ulb + "/python3" if name == "python" else "../../../Library/Frameworks/Python.framework/Versions/3.13/bin/" + name
            make_link(self.ulb + "/" + name, value)
        U = H + "/Library/Python/3.13"
        USP = U + "/lib/python/site-packages"
        write_file(USP + "/torch/__init__.py", b"# torch\n")
        for name in ("__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth"):
            write_file(USP + "/" + name, b"# editable reference\n")
        write_file(USP + "/fubotv_mcp_common-0.1.0.dist-info/METADATA", b"Name: fubotv-mcp-common\n")
        write_file(U + "/bin/torchrun", b"#!fake\n", 0o755)
        hub = H + "/hf_home/hub"
        for cid in ("H1", "H2", "H4"):
            self.make_repo(hub, PINS[cid][0], PINS[cid][1])
        self.make_repo(self.usb_hub, PINS["H3"][0], PINS["H3"][1])
        big27 = "models--ailexleon--Huihui-Qwen3.8-27B-abliterated-mlx-6Bit"
        self.make_repo(hub, big27, "a68be749cc7a1e762811b899b3af9ca13c97d29d")
        write_file(H + "/.mtplx/state.json", b"{}")
        make_link(H + "/mlx_models/qwen3-vl", hub + "/" + PINS["H4"][0] + "/snapshots/" + PINS["H4"][1])
        make_link(H + "/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit", hub + "/" + big27 + "/snapshots/a68be749cc7a1e762811b899b3af9ca13c97d29d")
        self.write_deploy_dir()

    def configure_build_hooks(self):
        bp.HOOKS.update({
            "run": self.run,
            "ismount": lambda path: path in self.mounts,
            "diskutil_personality": lambda path: "Case-sensitive APFS",
            "statvfs_free": lambda path: 10 ** 15,
            "port_free": lambda port: True,
            "which": lambda name: {"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe}.get(name),
            "now_utc": lambda: FIXED_NOW,
            "after_chunk": lambda src, nbytes: None,
            "after_entry": lambda index: None,
        })

    def ctx(self, *extra):
        args = bp.parse_args(["--usb-root", self.usb, "--package-id", self.package_id] + list(extra))
        ctx = bp.BuildCtx(args)
        bp.enumerate_components(ctx)
        return ctx


def order_by_spec(keys):
    out = []
    for cid in ORDER:
        mine = [k for k in keys if k[1] == cid]
        out.extend(sorted([k for k in mine if k[2] is not None], key=lambda k: k[2]))
        out.extend(sorted([k for k in mine if k[2] is None], key=lambda k: k[3]))
    return out


def expected_keys(fx):
    H, WS = fx.home, fx.ws
    exp = []

    def tree(cid, slug, target, items):
        prefix = "payload/%s-%s" % (cid, slug)
        exp.append(("d", cid, prefix, target))
        for kind, rel in items:
            exp.append((kind, cid, prefix + "/" + rel, target + "/" + rel))

    a1 = "payload/A1-workspace-code"
    exp.extend([("d", "A1", a1, WS), ("d", "A1", a1 + "/bin", WS + "/bin"), ("d", "A1", a1 + "/tests", WS + "/tests")])
    exp.extend(("f", "A1", a1 + "/" + rel, WS + "/" + rel) for rel in PIPELINE + TESTS7)
    a2 = "payload/A2-hw-gate-seeds"
    exp.append(("d", "A2", a2, WS + "/generated/hw_gate_seeds"))
    exp.extend(("f", "A2", a2 + "/" + n, WS + "/generated/hw_gate_seeds/" + n) for n in ("portrait.png", "wide3x1.png", "square.png"))
    L = H + "/ltx-2-mlx"
    tree("B1", "ltx2mlx-repo", L, [("f", "README.md"), ("d", "packages"), ("d", "packages/ltx_core"), ("f", "packages/ltx_core/__init__.py")])
    tree("B2", "ltx2mlx-venv", L + "/.venv", [("f", "pyvenv.cfg"), ("d", "bin"), ("l", "bin/python"), ("f", "bin/ltx-2-mlx"), ("d", "lib"), ("d", "lib/python3.11"), ("d", "lib/python3.11/site-packages"), ("f", "lib/python3.11/site-packages/ltx_pipelines.pth")])
    tree("B3", "uv-cpython311", H + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none", [("d", "bin"), ("f", "bin/python3.11"), ("l", "bin/python3"), ("d", "lib"), ("f", "lib/libpython3.11.dylib")])
    tree("B4", "ltx25-mlx-q8", L + "/models/ltx-2.5-mlx-q8", [("f", n) for n in PACK28])
    exp.extend([("d", "B5", None, L + "/hf_cache"), ("d", "B5", None, L + "/hf_cache/hub")])
    tree("D1", "vllm-venv", H + "/.venv-vllm-metal", [("f", "pyvenv.cfg"), ("d", "bin"), ("l", "bin/python"), ("d", "lib"), ("d", "lib/python3.12"), ("d", "lib/python3.12/site-packages"), ("d", "lib/python3.12/site-packages/vllm"), ("f", "lib/python3.12/site-packages/vllm/__init__.py")])
    tree("F1", "framework-python", fx.fw + "/Versions/3.13", [("d", "bin"), ("f", "bin/python3.13"), ("l", "bin/python3"), ("d", "lib"), ("d", "lib/python3.13"), ("d", "lib/python3.13/site-packages"), ("d", "lib/python3.13/site-packages/psutil"), ("f", "lib/python3.13/site-packages/psutil/__init__.py")])
    exp.extend([("d", "F2", None, fx.fw), ("d", "F2", None, fx.fw + "/Versions"), ("d", "F2", None, fx.ulb)])
    exp.extend(("l", "F2", None, fx.fw + "/" + n) for n in ("Headers", "Python", "Resources", "Versions/Current"))
    exp.extend(("l", "F2", None, fx.ulb + "/" + n) for n in BIN_LINKS13)
    tree("F3", "user-site", H + "/Library/Python/3.13", [("d", "bin"), ("f", "bin/torchrun"), ("d", "lib"), ("d", "lib/python"), ("d", "lib/python/site-packages"), ("d", "lib/python/site-packages/torch"), ("f", "lib/python/site-packages/torch/__init__.py")])
    exp.extend([("d", "H0", None, H + "/hf_home"), ("d", "H0", None, H + "/hf_home/hub")])
    slugs = {"H1": "hf-zimage", "H2": "hf-zimage-te", "H3": "hf-nsfw", "H4": "hf-qwen3vl32b"}
    for cid in ("H1", "H2", "H3", "H4"):
        repo, pin = PINS[cid]
        blob = hashlib.sha1(repo.encode("utf-8")).hexdigest()
        tree(cid, slugs[cid], H + "/hf_home/hub/" + repo, [("d", "blobs"), ("f", "blobs/" + blob), ("d", "refs"), ("f", "refs/main"), ("d", "snapshots"), ("d", "snapshots/" + pin), ("l", "snapshots/" + pin + "/config.json")])
    exp.extend([("d", "H5", None, H + "/mlx_models"), ("l", "H5", None, H + "/mlx_models/qwen3-vl")])
    return order_by_spec(exp)


class TestComponentCollection(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()

    def keys(self, ctx):
        return [(e["k"], e["c"], e.get("p"), e["t"]) for e in ctx.entries]

    def test_T01_golden_entry_list(self):
        ctx = self.fx.ctx()
        self.assertEqual(ctx.enum_errors, [])
        self.assertEqual(ctx.l1_hits, [])
        self.assertEqual(self.keys(ctx), expected_keys(self.fx))

    def test_T02_exclusions(self):
        ctx = self.fx.ctx()
        targets = [e["t"] for e in ctx.entries]
        sources = [e.get("_src", "") for e in ctx.entries]
        for pruned in ("__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
            self.assertEqual([t for t in targets if ("/" + pruned + "/") in (t + "/")], [], pruned)
        self.assertEqual([t for t in targets if t.endswith("/.DS_Store")], [])
        self.assertEqual([t for t in targets if "/ltx-2.5-mlx-q8/.cache" in t], [])
        L = self.fx.home + "/ltx-2-mlx"
        for name in ("models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"):
            self.assertEqual([e["t"] for e in ctx.entries if e["c"] == "B1" and _under_path(e["t"], L + "/" + name)], [], name)
        for marker in ("fubotv_mcp_common", "student_agent_mcp"):
            self.assertEqual([t for t in targets if marker in t], [], marker)
        a1 = sorted(e["_rel"] for e in ctx.entries if e["c"] == "A1" and e["k"] == "f")
        self.assertEqual(a1, sorted(PIPELINE + TESTS7))
        for rel in LEGACY:
            self.assertTrue(os.path.exists(self.fx.ws + "/" + rel), rel)
            self.assertNotIn(self.fx.ws + "/" + rel, targets)
        self.assertEqual([p for p in sources + targets if "Huihui-Qwen3.8-27B" in p or "/.mtplx" in p], [])
        self.assertNotIn(self.fx.ws + "/generated/hw_gate_seeds/last_portrait.sid", targets)

    def test_T02b_constants_verbatim(self):
        self.assertEqual(bp.COMPONENT_ORDER, ORDER)
        self.assertEqual(bp.LTX25_PACK_FILES, frozenset(PACK28))
        self.assertEqual(len(bp.LTX25_PACK_FILES), 28)
        self.assertEqual(bp.PIPELINE_FILES, PIPELINE)
        self.assertEqual(bp.TEST_FILES, TESTS7)
        self.assertEqual(bp.F2_BIN_LINKS, BIN_LINKS13)
        self.assertEqual(bp.F2_FRAMEWORK_LINKS, ("Headers", "Python", "Resources", "Versions/Current"))
        self.assertEqual(bp.HF_PINS, PINS)
        self.assertEqual(bp.PRUNE_DIRS, frozenset(["__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"]))
        self.assertEqual(bp.B1_EXCLUDES, frozenset(["models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"]))
        self.assertEqual(bp.F1_EXCLUDES, frozenset("lib/python3.13/site-packages/" + n for n in (
            "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
            "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth",
            "fubotv_mcp_common-0.1.0.dist-info", "student_agent_mcp-1.0.0.dist-info")))
        self.assertEqual(bp.F3_EXCLUDES, frozenset("lib/python/site-packages/" + n for n in (
            "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth",
            "fubotv_mcp_common-0.1.0.dist-info")))
        self.assertEqual(bp.SLUGS["B4"], "ltx25-mlx-q8")
        self.assertEqual(len(bp.SLUGS), 17)

    def test_T03a_hf_snapshot_links_are_relative_l_entries(self):
        ctx = self.fx.ctx()
        for cid in ("H1", "H2", "H3", "H4"):
            repo, pin = PINS[cid]
            links = [e for e in ctx.entries if e["c"] == cid and e["k"] == "l"]
            self.assertEqual([e["l"] for e in links], ["../../blobs/" + hashlib.sha1(repo.encode("utf-8")).hexdigest()])

    def test_T04_synthetic_entries(self):
        ctx = self.fx.ctx()
        synth = [e for e in ctx.entries if e["c"] in ("B5", "H0", "H5")]
        self.assertEqual(len(synth), 6)
        for e in synth:
            self.assertIs(e.get("s"), True)
            self.assertNotIn("p", e)
            self.assertNotIn("_src", e)
        link = [e for e in synth if e["k"] == "l"][0]
        self.assertEqual(link["l"], self.fx.home + "/hf_home/hub/" + PINS["H4"][0] + "/snapshots/" + PINS["H4"][1])
        self.assertEqual([e["m"] for e in synth if e["k"] == "d"], ["0755"] * 5)

    def test_T05_f2_has_17_links_and_3_dirs(self):
        ctx = self.fx.ctx()
        f2 = [e for e in ctx.entries if e["c"] == "F2"]
        self.assertEqual(sorted(collections.Counter(e["k"] for e in f2).items()), [("d", 3), ("l", 17)])
        self.assertEqual([e for e in f2 if "p" in e], [])
        by_t = dict((e["t"], e) for e in f2)
        self.assertEqual(by_t[self.fx.fw + "/Versions"]["m"], "0775")
        self.assertEqual(by_t[self.fx.fw + "/Versions/Current"]["l"], "3.13")
        self.assertEqual(by_t[self.fx.ulb + "/python"]["l"], self.fx.ulb + "/python3")

    def test_T05b_f2_wrong_type_is_an_enumeration_error(self):
        os.unlink(self.fx.ulb + "/pip3")
        write_file(self.fx.ulb + "/pip3", b"not a symlink")
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if self.fx.ulb + "/pip3" in m and "not a symlink" in m], ctx.enum_errors)

    def test_T07a_fifo_is_an_enumeration_error(self):
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        os.mkfifo(fifo)
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if fifo in m and "special file" in m], ctx.enum_errors)

    def test_missing_source_root_is_an_enumeration_error(self):
        B3 = self.fx.home + "/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none"
        shutil.rmtree(B3)
        ctx = self.fx.ctx()
        self.assertTrue([m for m in ctx.enum_errors if m.startswith("B3:") and B3 in m], ctx.enum_errors)

    def test_R6_falconsai_hub_selection(self):
        ctx = self.fx.ctx()
        self.assertEqual(ctx.falconsai_hub, self.fx.usb_hub)
        h3 = [e for e in ctx.entries if e["c"] == "H3"]
        self.assertTrue(all(e["_src"].startswith(self.fx.usb_hub + "/") for e in h3))
        self.assertTrue(all(e["t"].startswith(self.fx.home + "/hf_home/hub/") for e in h3))
        self.fx.make_repo(self.fx.home + "/hf_home/hub", PINS["H3"][0], PINS["H3"][1])
        self.assertEqual(self.fx.ctx().falconsai_hub, self.fx.home + "/hf_home/hub")
        shutil.rmtree(self.fx.home + "/hf_home/hub/" + PINS["H3"][0])
        shutil.rmtree(self.fx.usb_hub + "/" + PINS["H3"][0])
        ctx = self.fx.ctx()
        self.assertIsNone(ctx.falconsai_hub)
        self.assertTrue([m for m in ctx.enum_errors if m.startswith("H3:")])

    def test_stats(self):
        ctx = self.fx.ctx()
        self.assertEqual(list(ctx.comp_stats), list(ORDER))
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (17, 3))
        self.assertEqual(ctx.comp_stats["F2"], {"slug": "framework-symlinks", "files": 0, "symlinks": 17, "dirs": 3, "bytes": 0})
        totals = bp.stats_totals(ctx.comp_stats)
        self.assertEqual(totals["bytes"], sum(e["b"] for e in ctx.entries if e["k"] == "f"))

    def test_parse_args_usage_errors(self):
        for argv in (["--resume"], ["--package-id", "ltx-chain-deploy-2026"], ["--apply", "--verify-only"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    bp.parse_args(argv)
            self.assertEqual(cm.exception.code, 2, argv)
        args = bp.parse_args(["--usb-root", self.fx.usb + "/"])
        self.assertEqual(bp.BuildCtx(args).usb_root, self.fx.usb)
```

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k TestComponentCollection`
Expected: FAIL/ERROR with `AttributeError: module 'build_pkg' has no attribute 'parse_args'` (and `COMPONENT_ORDER`).

- [ ] **Step 3: Write the implementation** — append to the end of `scripts/deploy/build_pkg.py`:

```python


# ---------------------------------------------------------------------------
# Components (spec 7)
# ---------------------------------------------------------------------------
COMPONENT_ORDER = ("A1", "A2", "B1", "B2", "B3", "B4", "B5", "D1", "F1", "F2", "F3", "H0", "H1", "H2", "H3", "H4", "H5")
SLUGS = {
    "A1": "workspace-code", "A2": "hw-gate-seeds", "B1": "ltx2mlx-repo", "B2": "ltx2mlx-venv",
    "B3": "uv-cpython311", "B4": "ltx25-mlx-q8", "B5": "ltx2mlx-hf-cache-dirs", "D1": "vllm-venv",
    "F1": "framework-python", "F2": "framework-symlinks", "F3": "user-site", "H0": "hf-home-dirs",
    "H1": "hf-zimage", "H2": "hf-zimage-te", "H3": "hf-nsfw", "H4": "hf-qwen3vl32b", "H5": "mlx-models-link",
}
PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py",
                  "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
                  "bin/story-server", "bin/qwen-agent")
TEST_FILES = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
              "tests/test_ltx2_mlx_video_skill.py", "tests/test_ltx_image_fit.py",
              "tests/test_ltx_story_manifest_chain.py", "tests/check_ltx2_mlx_no_forbidden_imports.py")
A1_FILES = PIPELINE_FILES + TEST_FILES
A1_DIRS = ("", "bin", "tests")
A2_DIR_REL = "generated/hw_gate_seeds"
A2_FILES = ("portrait.png", "wide3x1.png", "square.png")
L1_NAMES = frozenset(["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"])
PRUNE_DIRS = frozenset(["__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"])
B1_EXCLUDES = frozenset(["models", "hf_cache", "converted_models", "source_caches", ".venv", ".claude", ".git"])
B4_EXCLUDES = frozenset([".cache"])
F1_EXCLUDES = frozenset("lib/python3.13/site-packages/" + name for name in (
    "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable___student_agent_mcp_1_0_0_finder.py",
    "__editable__.fubotv_mcp_common-0.1.0.pth", "__editable__.student_agent_mcp-1.0.0.pth",
    "fubotv_mcp_common-0.1.0.dist-info", "student_agent_mcp-1.0.0.dist-info"))
F3_EXCLUDES = frozenset("lib/python/site-packages/" + name for name in (
    "__editable___fubotv_mcp_common_0_1_0_finder.py", "__editable__.fubotv_mcp_common-0.1.0.pth",
    "fubotv_mcp_common-0.1.0.dist-info"))
UV_CPYTHON_DIR = "cpython-3.11.13-macos-aarch64-none"
F2_FRAMEWORK_LINKS = ("Headers", "Python", "Resources", "Versions/Current")
F2_BIN_LINKS = ("idle3", "idle3.13", "pip3", "pip3.13", "pydoc3", "pydoc3.13", "python3", "python3-config",
                "python3-intel64", "python3.13", "python3.13-config", "python3.13-intel64", "python")
LTX25_PACK_FILES = frozenset([
    ".gitattributes", "LICENSE", "README.md", "audio_vae.safetensors", "chat_template.jinja",
    "connector.safetensors", "duration_head.safetensors", "embedded_config.json", "generation_config.json",
    "ltx-2.5-22b-distilled-lora-450-bf16.safetensors", "processor_config.json", "quantize_config.json",
    "spatial_upscaler_x2_v1_0.safetensors", "spatial_upscaler_x2_v1_0_config.json", "split_model.json",
    "temporal_upscaler_x2_v1_0.safetensors", "temporal_upscaler_x2_v1_0_config.json",
    "text_encoder.safetensors", "text_encoder_config.json", "tokenizer.json", "tokenizer_config.json",
    "transformer-dev.safetensors", "transformer-distilled.safetensors", "vae_decoder_av.safetensors",
    "vae_decoder_conv.safetensors", "vae_encoder_av.safetensors", "vae_encoder_conv.safetensors",
    "vocoder.safetensors"])
HF_PINS = {
    "H1": ("models--Tongyi-MAI--Z-Image-Turbo", "f332072aa78be7aecdf3ee76d5c247082da564a6"),
    "H2": ("models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1", "ce497d288a7ddfd5d0f337c7139349d5d0236bfa"),
    "H3": ("models--Falconsai--nsfw_image_detection", "96cb0d0342c7afb80cab76ecc58b265fa44da256"),
    "H4": ("models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx", "5428d6aaca0103a1e32f47261a20fecaa47700ec"),
}


def default_package_id():
    return "ltx-chain-deploy-" + time.strftime("%Y%m%d", time.localtime())


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="build_pkg.py", description="Build the ltx-chain USB deployment package.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="the default: run every check, write nothing")
    mode.add_argument("--apply", action="store_true", help="build the package")
    mode.add_argument("--verify-only", action="store_true", help="re-verify a finished package; writes nothing")
    mode.add_argument("--credential-report", action="store_true", help="enumeration + L1 + L2 report; writes nothing")
    parser.add_argument("--resume", action="store_true", help="with --apply: continue an interrupted build")
    parser.add_argument("--usb-root", default=None, help="default: %s" % USB_ROOT_DEFAULT)
    parser.add_argument("--package-id", default=None, help="default: ltx-chain-deploy-<local YYYYMMDD>")
    args = parser.parse_args(argv)
    if args.resume and not args.apply:
        parser.error("--resume requires --apply")
    if args.package_id is not None and not PACKAGE_ID_RE.match(args.package_id):
        parser.error("--package-id must match ^ltx-chain-deploy-[0-9]{8}$")
    return args


class BuildCtx(object):
    """Everything one invocation knows. Never printed: it holds the L3 secret values."""

    def __init__(self, args):
        self.args = args
        self.usb_root = os.path.abspath(args.usb_root if args.usb_root else USB_ROOT_DEFAULT)
        self.package_id = args.package_id if args.package_id else default_package_id()
        self.package_root = os.path.join(self.usb_root, self.package_id)
        self.apply = bool(args.apply)
        self.resume = bool(args.resume)
        self.started_at = ""
        self.secrets = []
        self.l3_sources = []
        self.l3_errors = []
        self.entries = []
        self.comp_stats = {}
        self.enum_errors = []
        self.l1_hits = []
        self.falconsai_hub = None
        self.allow = set()
        self.allow_entries = []
        self.allow_error = None
        self.l2_hits = []
        self.l2_new = []
        self.l2_allowed = []
        self.l2_errors = []
        self.host = {}
        self.host_failures = []
        self.freezes = {}
        self.git_record = {}
        self.git_problems = []
        self.baseline = None
        self.script_bytes = {}
        self.root_files = collections.OrderedDict()
        self.resume_prefix_len = 0
        self.resume_keep_bytes = 0
        self.resume_rename = False
        self.resume_error = None
        self.remaining_bytes = 0
        self.required_bytes = 0
        self.free_bytes = 0
        self.partial_fh = None
        self.entries_sha256 = ""

    def __repr__(self):
        return "<BuildCtx %s>" % self.package_id


def payload_prefix(cid):
    return "payload/%s-%s" % (cid, SLUGS[cid])


def b3_source():
    return home() + "/.local/share/uv/python/" + UV_CPYTHON_DIR


def l1_check(ctx, name, path):
    if name in L1_NAMES:
        ctx.l1_hits.append(path)


def _lstat_or_error(ctx, cid, path):
    try:
        return os.lstat(path)
    except OSError as exc:
        ctx.enum_errors.append("%s: cannot stat %s: %s" % (cid, path, exc))
        return None


def walk_tree(ctx, cid, src_root, dst_root, excludes):
    entries = []
    try:
        st = os.lstat(src_root)
    except OSError:
        ctx.enum_errors.append("%s: source root %s is missing" % (cid, src_root))
        return entries
    if not stat.S_ISDIR(st.st_mode):
        ctx.enum_errors.append("%s: source root %s is not a directory" % (cid, src_root))
        return entries
    prefix = payload_prefix(cid)
    entries.append({"k": "d", "c": cid, "p": prefix, "t": dst_root, "m": mode_str(st), "_src": src_root, "_rel": ""})
    _walk_dir(ctx, cid, src_root, dst_root, prefix, "", excludes, entries)
    return entries


def _walk_dir(ctx, cid, src_root, dst_root, prefix, rel_dir, excludes, entries):
    abs_dir = src_root + "/" + rel_dir if rel_dir else src_root
    try:
        names = sorted(os.listdir(abs_dir))
    except OSError as exc:
        ctx.enum_errors.append("%s: cannot list %s: %s" % (cid, abs_dir, exc))
        return
    for name in names:
        if name == ".DS_Store":
            continue
        rel = rel_dir + "/" + name if rel_dir else name
        if rel in excludes:
            continue
        path = src_root + "/" + rel
        st = _lstat_or_error(ctx, cid, path)
        if st is None:
            continue
        base = {"c": cid, "p": prefix + "/" + rel, "t": dst_root + "/" + rel, "_src": path, "_rel": rel}
        if stat.S_ISDIR(st.st_mode):
            if name in PRUNE_DIRS:
                continue
            entries.append(dict(base, k="d", m=mode_str(st)))
            _walk_dir(ctx, cid, src_root, dst_root, prefix, rel, excludes, entries)
        elif stat.S_ISLNK(st.st_mode):
            entries.append(dict(base, k="l", l=os.readlink(path)))
            l1_check(ctx, name, path)
        elif stat.S_ISREG(st.st_mode):
            if not os.access(path, os.R_OK):
                ctx.enum_errors.append("%s: unreadable file %s" % (cid, path))
                continue
            entries.append(dict(base, k="f", b=st.st_size, m=mode_str(st), mt=st.st_mtime_ns))
            l1_check(ctx, name, path)
        else:
            ctx.enum_errors.append("%s: special file (not a regular file, directory or symlink) %s" % (cid, path))


def _file_entry(ctx, cid, path, p, rel):
    st = _lstat_or_error(ctx, cid, path)
    if st is None:
        return None
    if not stat.S_ISREG(st.st_mode):
        ctx.enum_errors.append("%s: %s is not a regular file" % (cid, path))
        return None
    if not os.access(path, os.R_OK):
        ctx.enum_errors.append("%s: unreadable file %s" % (cid, path))
        return None
    l1_check(ctx, os.path.basename(path), path)
    return {"k": "f", "c": cid, "p": p, "t": path, "b": st.st_size, "m": mode_str(st),
            "mt": st.st_mtime_ns, "_src": path, "_rel": rel}


def _dir_entry(ctx, cid, path, p, rel):
    st = _lstat_or_error(ctx, cid, path)
    if st is None:
        return None
    if not stat.S_ISDIR(st.st_mode):
        ctx.enum_errors.append("%s: %s is not a directory" % (cid, path))
        return None
    return {"k": "d", "c": cid, "p": p, "t": path, "m": mode_str(st), "_src": path, "_rel": rel}


def enum_a1(ctx):
    ws = workspace()
    prefix = payload_prefix("A1")
    entries = []
    for rel in A1_DIRS:
        entry = _dir_entry(ctx, "A1", ws + "/" + rel if rel else ws, prefix + "/" + rel if rel else prefix, rel)
        if entry is not None:
            entries.append(entry)
    for rel in A1_FILES:
        entry = _file_entry(ctx, "A1", ws + "/" + rel, prefix + "/" + rel, rel)
        if entry is not None:
            entries.append(entry)
    return entries


def enum_a2(ctx):
    base = workspace() + "/" + A2_DIR_REL
    prefix = payload_prefix("A2")
    entries = []
    entry = _dir_entry(ctx, "A2", base, prefix, "")
    if entry is not None:
        entries.append(entry)
    for name in A2_FILES:
        entry = _file_entry(ctx, "A2", base + "/" + name, prefix + "/" + name, name)
        if entry is not None:
            entries.append(entry)
    return entries


def enum_f2(ctx):
    entries = []
    for path in (FRAMEWORK_ROOT, FRAMEWORK_ROOT + "/Versions", USR_LOCAL_BIN):
        st = _lstat_or_error(ctx, "F2", path)
        if st is None:
            continue
        if not stat.S_ISDIR(st.st_mode):
            ctx.enum_errors.append("F2: %s is not a directory" % path)
            continue
        entries.append({"k": "d", "c": "F2", "t": path, "m": mode_str(st), "_src": path})
    links = [FRAMEWORK_ROOT + "/" + n for n in F2_FRAMEWORK_LINKS] + [USR_LOCAL_BIN + "/" + n for n in F2_BIN_LINKS]
    for path in links:
        st = _lstat_or_error(ctx, "F2", path)
        if st is None:
            continue
        if not stat.S_ISLNK(st.st_mode):
            ctx.enum_errors.append("F2: %s is not a symlink" % path)
            continue
        l1_check(ctx, os.path.basename(path), path)
        entries.append({"k": "l", "c": "F2", "t": path, "l": os.readlink(path), "_src": path})
    return entries


def synthetic_dir(cid, target):
    return {"k": "d", "c": cid, "t": target, "m": "0755", "s": True}


def h5_link_value():
    repo, pin = HF_PINS["H4"]
    return home() + "/hf_home/hub/" + repo + "/snapshots/" + pin


def select_falconsai_hub():
    repo = HF_PINS["H3"][0]
    for hub in (home() + "/hf_home/hub", FALCONSAI_USB_HUB):
        if os.path.isdir(hub + "/" + repo):
            return hub
    return None


def sort_component(entries):
    with_p = sorted([e for e in entries if "p" in e], key=lambda e: e["p"])
    without_p = sorted([e for e in entries if "p" not in e], key=lambda e: e["t"])
    return with_p + without_p


def component_stats(entries):
    stats = collections.OrderedDict()
    for cid in COMPONENT_ORDER:
        stats[cid] = {"slug": SLUGS[cid], "files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
    for entry in entries:
        row = stats[entry["c"]]
        if entry["k"] == "f":
            row["files"] += 1
            row["bytes"] += entry["b"]
        elif entry["k"] == "l":
            row["symlinks"] += 1
        else:
            row["dirs"] += 1
    return stats


def stats_totals(stats):
    totals = {"files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
    for row in stats.values():
        for key in totals:
            totals[key] += row[key]
    return totals


def enumerate_components(ctx):
    H = home()
    hub = H + "/hf_home/hub"
    ctx.falconsai_hub = select_falconsai_hub()
    parts = {}
    parts["A1"] = enum_a1(ctx)
    parts["A2"] = enum_a2(ctx)
    parts["B1"] = walk_tree(ctx, "B1", H + "/ltx-2-mlx", H + "/ltx-2-mlx", B1_EXCLUDES)
    parts["B2"] = walk_tree(ctx, "B2", H + "/ltx-2-mlx/.venv", H + "/ltx-2-mlx/.venv", frozenset())
    parts["B3"] = walk_tree(ctx, "B3", b3_source(), b3_source(), frozenset())
    parts["B4"] = walk_tree(ctx, "B4", ltx25_model_path(), ltx25_model_path(), B4_EXCLUDES)
    parts["B5"] = [synthetic_dir("B5", H + "/ltx-2-mlx/hf_cache"), synthetic_dir("B5", H + "/ltx-2-mlx/hf_cache/hub")]
    parts["D1"] = walk_tree(ctx, "D1", H + "/.venv-vllm-metal", H + "/.venv-vllm-metal", frozenset())
    parts["F1"] = walk_tree(ctx, "F1", FRAMEWORK_ROOT + "/Versions/3.13", FRAMEWORK_ROOT + "/Versions/3.13", F1_EXCLUDES)
    parts["F2"] = enum_f2(ctx)
    parts["F3"] = walk_tree(ctx, "F3", H + "/Library/Python/3.13", H + "/Library/Python/3.13", F3_EXCLUDES)
    parts["H0"] = [synthetic_dir("H0", H + "/hf_home"), synthetic_dir("H0", hub)]
    for cid in ("H1", "H2", "H3", "H4"):
        repo = HF_PINS[cid][0]
        if cid == "H3":
            if ctx.falconsai_hub is None:
                ctx.enum_errors.append("H3: %s not found under %s or %s" % (repo, hub, FALCONSAI_USB_HUB))
                parts[cid] = []
                continue
            source_hub = ctx.falconsai_hub
        else:
            source_hub = hub
        parts[cid] = walk_tree(ctx, cid, source_hub + "/" + repo, hub + "/" + repo, frozenset())
    parts["H5"] = [synthetic_dir("H5", H + "/mlx_models"),
                   {"k": "l", "c": "H5", "t": H + "/mlx_models/qwen3-vl", "l": h5_link_value(), "s": True}]
    ctx.entries = []
    for cid in COMPONENT_ORDER:
        ctx.entries.extend(sort_component(parts[cid]))
    ctx.comp_stats = component_stats(ctx.entries)
```

- [ ] **Step 4: Run the tests to verify they pass (both interpreters).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py; echo rc=$?`
Expected: `23 passed`, rc=0.

Run: `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1`
Expected: `OK`.

If T01 fails, print the diff with `-x -vv`. Fix the implementation, never the golden list, unless the golden list contradicts spec §7. A contradiction goes back to the planner.

- [ ] **Step 5: Negative control.** Temporarily remove `"__pycache__",` from `PRUNE_DIRS` → T01 and T02 FAIL. Revert.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: enumerate the 17 package components (explicit A1 list, pruned trees, F2, synthetic dirs)"
```

---

### Task 3: Credential gate — L1/L2 checks, allowlist, L3 source loading, L4 package scan, `--credential-report`

**Files:**
- Create: `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/credential_allowlist.json`
- Modify: `scripts/deploy/build_pkg.py` (append at end)
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: Task 1 (`sha256_bytes`, `KnownSecretScanner`, `CheckResult`, `CredentialLeak`) and Task 2 (`BuildCtx`, `enumerate_components`, `L1_NAMES`, `COMPONENT_ORDER`).
- Produces:
  - `L2_PATTERNS`;
  - `is_allowlisted(allow, component, relpath, sha256, pattern_id)`;
  - `parse_allowlist(data, label) -> (set_of_4tuples, entries_list)`, which raises `ValueError`;
  - `load_allowlist(path)`;
  - `l2_scan_bytes(data) -> [pattern_id]`;
  - `l2_scan_sources(ctx) -> (hits, errors)`, where a hit is `{"component","relpath","sha256","pattern"}`;
  - `classify_l2_hits(hits, allow) -> (new, allowed)`;
  - `stale_allowlist_entries(entries, hits)`, `report_json(hit)`, `load_deploy_files(ctx)`, `prepare_l2(ctx)`;
  - `load_known_secrets() -> (values, sources, errors)`;
  - `list_tree(root) -> [(rel, lstat)]`, `allowlist_key(rel) -> (component, relpath)`;
  - `scan_package(package_root, allow) -> (failures, allowed_hits)`;
  - `check_b12(ctx)`, `check_b13(ctx)`, `stale_allowlist_warnings(ctx) -> [CheckResult]`, `check_b14(ctx)`;
  - `credential_scan_doc(ctx) -> dict`, `l4_rescan(ctx)`, `cmd_credential_report(args) -> int`.
- Test helpers produced: `allow_entry(hit, note=...)`, `L2_CANARIES`.

- [ ] **Step 1: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
def allow_entry(hit, note="reviewed: test fixture canary"):
    return {"component": hit["component"], "relpath": hit["relpath"], "sha256": hit["sha256"],
            "pattern": hit["pattern"], "note": note}


L2_CANARIES = (
    ("hf_token", "hf" + "_" + "Ab3" * 12),
    ("private_key", "-----BEGIN " + "RSA PRIVATE" + " KEY-----"),
    ("aws_access_key_id", "AK" + "IA" + "ABCDEFGHIJKLMNOP"),
    ("github_token", GITHUB_CANARY),
    ("anthropic_api_key", " sk-" + "ant-" + "a" * 40),
    ("openai_api_key", " sk-" + "proj-" + "b" * 40),
)


class TestCredentialGates(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.torch = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch"

    def l2_ctx(self):
        ctx = self.fx.ctx()
        bp.load_deploy_files(ctx)
        bp.prepare_l2(ctx)
        return ctx

    def test_T10a_nested_token_file_is_an_l1_hit_and_tokenizer_json_is_not(self):
        write_file(self.torch + "/tokenizer.json", b"{}")
        write_file(self.torch + "/credentials.py", b"# code\n")
        os.makedirs(self.torch + "/token")
        ctx = self.fx.ctx()
        self.assertEqual(ctx.l1_hits, [])
        self.assertTrue(bp.check_b12(ctx).ok)
        write_file(self.torch + "/sub/token", b"not-a-secret-value-xyz\n")
        ctx = self.fx.ctx()
        self.assertEqual(ctx.l1_hits, [self.torch + "/sub/token"])
        result = bp.check_b12(ctx)
        self.assertFalse(result.ok)
        self.assertTrue(result.fatal)
        self.assertIn(self.torch + "/sub/token", result.message)

    def test_T11_each_l1_name_fails_b12(self):
        names = ["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials",
                 "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"]
        self.assertEqual(sorted(bp.L1_NAMES), sorted(names))
        for name in names:
            path = self.torch + "/" + name
            write_file(path, b"harmless\n")
            ctx = self.fx.ctx()
            self.assertEqual(ctx.l1_hits, [path], name)
            self.assertFalse(bp.check_b12(ctx).ok, name)
            os.unlink(path)
        link = self.torch + "/id_rsa"
        make_link(link, "elsewhere")
        self.assertEqual(self.fx.ctx().l1_hits, [link])

    def test_T12_each_l2_pattern_is_allowlisted_only_by_exact_hash(self):
        for pid, canary in L2_CANARIES:
            path = self.torch + "/leak_%s.txt" % pid
            rel = "lib/python/site-packages/torch/leak_%s.txt" % pid
            write_file(path, ("prefix " + canary + " suffix\n").encode("utf-8"))
            ctx = self.l2_ctx()
            mine = [h for h in ctx.l2_hits if h["relpath"] == rel]
            self.assertIn(pid, [h["pattern"] for h in mine], pid)
            self.assertTrue(all(h["component"] == "F3" and h["sha256"] == file_sha256(path) for h in mine))
            self.assertFalse(bp.check_b13(ctx).ok, pid)
            self.fx.write_allowlist([allow_entry(h) for h in mine])
            ctx = self.l2_ctx()
            self.assertEqual(ctx.l2_new, [], pid)
            self.assertTrue(bp.check_b13(ctx).ok, pid)
            write_file(path, ("Prefix " + canary + " suffix\n").encode("utf-8"))   # one byte changed
            ctx = self.l2_ctx()
            self.assertFalse(bp.check_b13(ctx).ok, pid)
            warnings = bp.stale_allowlist_warnings(ctx)
            self.assertEqual(len(warnings), len(mine))
            self.assertTrue(all(w.check_id == "B13" and not w.ok and not w.fatal and w.message.startswith("stale allowlist entry {") for w in warnings))
            os.unlink(path)
            self.fx.write_allowlist([])

    def test_T12b_l2_size_limit(self):
        big = self.torch + "/big.bin"
        write_file(big, GITHUB_CANARY.encode("ascii") + b"\0" * bp.L2_MAX_BYTES)
        at_limit = self.torch + "/limit.bin"
        payload = GITHUB_CANARY.encode("ascii")
        write_file(at_limit, payload + b"\0" * (bp.L2_MAX_BYTES - len(payload)))
        ctx = self.l2_ctx()
        rels = [h["relpath"] for h in ctx.l2_hits]
        self.assertNotIn("lib/python/site-packages/torch/big.bin", rels)
        self.assertIn("lib/python/site-packages/torch/limit.bin", rels)

    def test_allowlist_validation(self):
        good = {"component": "F3", "relpath": "x", "sha256": "0" * 64, "pattern": "hf_token", "note": "ok"}
        allow, entries = bp.parse_allowlist(json.dumps({"schema_version": 1, "entries": [good]}).encode("utf-8"), "t")
        self.assertEqual(allow, set([("F3", "x", "0" * 64, "hf_token")]))
        self.assertEqual(entries, [good])
        for bad in ({"schema_version": 2, "entries": []}, {"schema_version": 1},
                    {"schema_version": 1, "entries": [dict(good, note="")]},
                    {"schema_version": 1, "entries": [dict(good, note="   ")]},
                    {"schema_version": 1, "entries": [dict((k, v) for k, v in good.items() if k != "note")]},
                    {"schema_version": 1, "entries": [dict(good, sha256=5)]}):
            with self.assertRaises(ValueError):
                bp.parse_allowlist(json.dumps(bad).encode("utf-8"), "t")
        with self.assertRaises(ValueError):
            bp.parse_allowlist(b"not json", "t")
        write_file(self.fx.deploy + "/credential_allowlist.json", b'{"schema_version": 1, "entries": [{"component": "F3"}]}')
        ctx = self.l2_ctx()
        self.assertIsNotNone(ctx.allow_error)
        result = bp.check_b13(ctx)
        self.assertFalse(result.ok)
        self.assertIn("allowlist failed to load", result.message)

    def test_T14_known_secret_sources(self):
        H = self.fx.home
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual((values, errors), ([], []))
        self.assertEqual([s["source"] for s in sources], [H + "/.cache/huggingface/token", H + "/.cache/huggingface/stored_tokens", H + "/ltx-2-mlx/hf_cache/token", "$HF_TOKEN"])
        self.assertEqual([s["present"] for s in sources], [False, False, False, False])
        tok_a = "tokA." + "x" * 20
        tok_b = "tokB." + "y" * 20
        tok_r = "reft." + "z" * 20
        write_file(H + "/.cache/huggingface/token", (tok_a + "\n").encode("ascii"))
        write_file(H + "/.cache/huggingface/stored_tokens", ("[default]\nhf_token = %s\nrefresh_token = %s\n[other]\nhf_token = %s\n" % (tok_b, tok_r, tok_a)).encode("ascii"))
        write_file(H + "/ltx-2-mlx/hf_cache/token", (tok_a + "\n").encode("ascii"))
        os.environ["HF_TOKEN"] = "  " + tok_b + "  "
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual(errors, [])
        self.assertEqual(values, [tok_a.encode("ascii"), tok_b.encode("ascii"), tok_r.encode("ascii")])
        self.assertEqual([s["values"] for s in sources], [1, 3, 1, 1])
        self.assertEqual([s["present"] for s in sources], [True, True, True, True])
        write_file(H + "/.cache/huggingface/token", b"fifteen.bytes15\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "too short" in e], errors)
        self.assertEqual([e for e in errors if "fifteen" in e], [])
        write_file(H + "/.cache/huggingface/token", (tok_a + "\n").encode("ascii"))
        write_file(H + "/.cache/huggingface/stored_tokens", b"no section header here\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "cannot be parsed" in e], errors)
        write_file(H + "/.cache/huggingface/stored_tokens", b"[default]\nsomething_else = abc\n")
        values, sources, errors = bp.load_known_secrets()
        self.assertTrue([e for e in errors if "no hf_token or refresh_token" in e], errors)
        ctx = self.fx.ctx()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = values, sources, errors
        self.assertFalse(bp.check_b14(ctx).ok)
        write_file(H + "/.cache/huggingface/stored_tokens", ("[default]\nrefresh_token = %s\n" % tok_r).encode("ascii"))
        values, sources, errors = bp.load_known_secrets()
        self.assertEqual([e for e in errors if "stored_tokens" in e], [])
        self.assertIn(tok_r.encode("ascii"), values)
        stored_source = [s for s in sources if s["source"] == H + "/.cache/huggingface/stored_tokens"][0]
        self.assertEqual(stored_source["values"], 1)

    def test_T16_scripts_are_l2_clean(self):
        names = sorted(n for n in os.listdir(DEPLOY_DIR) if n.endswith(".py"))
        self.assertIn("build_pkg.py", names)
        for name in names:
            with open(os.path.join(DEPLOY_DIR, name), "rb") as fh:
                self.assertEqual(bp.l2_scan_bytes(fh.read()), [], name)

    def test_T17_credential_report(self):
        path = self.torch + "/leak.txt"
        write_file(path, ("x " + GITHUB_CANARY + "\n").encode("ascii"))
        write_file(self.torch + "/deep/.netrc", b"machine example\n")
        before = snapshot(self.fx.root)
        args = bp.parse_args(["--credential-report", "--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = bp.cmd_credential_report(args)
        text = out.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("L1 " + self.torch + "/deep/.netrc", text.splitlines())
        new = [line for line in text.splitlines() if line.startswith("L2 NEW ")]
        self.assertEqual(len(new), 1)
        doc = json.loads(new[0][len("L2 NEW "):])
        self.assertEqual(doc, {"component": "F3", "relpath": "lib/python/site-packages/torch/leak.txt",
                               "sha256": file_sha256(path), "pattern": "github_token", "note": ""})
        self.assertIn('", "', new[0])
        self.assertNotIn(GITHUB_CANARY, text)
        self.assertEqual(snapshot(self.fx.root), before)
        self.assertFalse(os.path.exists(self.fx.pkg))
        os.unlink(self.torch + "/deep/.netrc")
        stale = {"component": "F3", "relpath": "gone.txt", "sha256": "0" * 64, "pattern": "hf_token", "note": "old"}
        self.fx.write_allowlist([dict(doc, note="reviewed"), stale])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = bp.cmd_credential_report(args)
        text = out.getvalue()
        self.assertEqual(rc, 0, text)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("L2 ALLOWLISTED ")]), 1)
        self.assertEqual([l for l in text.splitlines() if l.startswith("STALE ")], ["STALE " + json.dumps(stale, separators=(", ", ": "))])
        self.assertTrue(text.splitlines()[-1].startswith("build_pkg: CREDENTIAL REPORT CLEAN"))

    def test_scan_package_l1_l2_keys_and_ds_store(self):
        pkg = self.fx.root + "/pkgscan"
        write_file(pkg + "/payload/F3-user-site/lib/x.txt", ("a " + GITHUB_CANARY).encode("ascii"))
        write_file(pkg + "/manifests/source-host.json", ('{"k": "' + GITHUB_CANARY + '"}').encode("ascii"))
        write_file(pkg + "/payload/B1-ltx2mlx-repo/.DS_Store", b"ds")
        write_file(pkg + "/payload/B1-ltx2mlx-repo/deep/.netrc", b"machine x\n")
        make_link(pkg + "/payload/B1-ltx2mlx-repo/token", "nowhere")
        failures, allowed = bp.scan_package(pkg, set())
        self.assertEqual(sorted(failures), sorted([
            "L2 github_token payload/F3-user-site/lib/x.txt",
            "L2 github_token manifests/source-host.json",
            "DS_Store: payload/B1-ltx2mlx-repo/.DS_Store",
            "L1 payload/B1-ltx2mlx-repo/deep/.netrc",
            "L1 payload/B1-ltx2mlx-repo/token"]))
        self.assertEqual([f for f in failures if GITHUB_CANARY in f], [])
        allow = set([("F3", "lib/x.txt", file_sha256(pkg + "/payload/F3-user-site/lib/x.txt"), "github_token"),
                     ("ROOT", "manifests/source-host.json", file_sha256(pkg + "/manifests/source-host.json"), "github_token")])
        failures, allowed = bp.scan_package(pkg, allow)
        self.assertEqual(len(allowed), 2)
        self.assertEqual(sorted(failures), sorted(["DS_Store: payload/B1-ltx2mlx-repo/.DS_Store",
                                                   "L1 payload/B1-ltx2mlx-repo/deep/.netrc",
                                                   "L1 payload/B1-ltx2mlx-repo/token"]))
        self.assertEqual(bp.allowlist_key("payload/A2-hw-gate-seeds/portrait.png"), ("A2", "portrait.png"))
        self.assertEqual(bp.allowlist_key("README.md"), ("ROOT", "README.md"))

    def test_credential_scan_doc_holds_no_secret_material(self):
        secret = SECRET_CANARY
        write_file(self.fx.home + "/.cache/huggingface/token", (secret + "\n").encode("ascii"))
        ctx = self.l2_ctx()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = bp.load_known_secrets()
        doc = bp.credential_scan_doc(ctx)
        text = json.dumps(doc)
        self.assertNotIn(secret, text)
        self.assertNotIn(hashlib.sha256(secret.encode("ascii")).hexdigest(), text)
        self.assertEqual(doc["l1_names"], sorted(bp.L1_NAMES))
        self.assertEqual(list(doc["l2_patterns"]), [pid for pid, rx in bp.L2_PATTERNS])
        self.assertEqual(doc["l2_max_bytes"], 4194304)
        self.assertEqual(doc["l3_sources"][0], {"source": self.fx.home + "/.cache/huggingface/token", "present": True, "values": 1})
        self.assertEqual(bp.l2_scan_bytes(text.encode("utf-8")), [])
```

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k TestCredentialGates`
Expected: FAIL with `AttributeError: module 'build_pkg' has no attribute 'check_b12'` (and similar).

- [ ] **Step 3a: Create `scripts/deploy/credential_allowlist.json`** with exactly (plus a trailing newline):
```json
{"schema_version": 1, "entries": []}
```

- [ ] **Step 3b: Write the implementation** — append to the end of `scripts/deploy/build_pkg.py`:

```python


# ---------------------------------------------------------------------------
# Credential gate (spec 8)
# ---------------------------------------------------------------------------
L2_PATTERNS = (
    ("hf_token", re.compile(rb"hf_[A-Za-z0-9]{34,40}")),
    ("private_key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key_id", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}")),
    ("anthropic_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{32,}")),
    ("openai_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
)


def is_allowlisted(allow, component, relpath, sha256, pattern_id):
    return (component, relpath, sha256, pattern_id) in allow


def parse_allowlist(data, label):
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("entries"), list):
        raise ValueError('%s: expected {"schema_version": 1, "entries": [...]}' % label)
    allow = set()
    entries = []
    for index, item in enumerate(doc["entries"]):
        if not isinstance(item, dict):
            raise ValueError("%s: entry %d is not an object" % (label, index))
        for key in ("component", "relpath", "sha256", "pattern"):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValueError("%s: entry %d: %s must be a non-empty string" % (label, index, key))
        note = item.get("note")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("%s: entry %d: note must be a non-empty string" % (label, index))
        allow.add((item["component"], item["relpath"], item["sha256"], item["pattern"]))
        entries.append(item)
    return allow, entries


def load_allowlist(path):
    with open(path, "rb") as fh:
        return parse_allowlist(fh.read(), path)


def l2_scan_bytes(data):
    return [pid for pid, rx in L2_PATTERNS if rx.search(data)]


def l2_scan_sources(ctx):
    hits = []
    errors = []
    for entry in ctx.entries:
        if entry["k"] != "f" or "_src" not in entry or entry["b"] > L2_MAX_BYTES:
            continue
        try:
            with open(entry["_src"], "rb") as fh:
                data = fh.read()
        except OSError as exc:
            errors.append("cannot read %s for the L2 scan: %s" % (entry["_src"], exc))
            continue
        pids = l2_scan_bytes(data)
        if pids:
            digest = sha256_bytes(data)
            for pid in pids:
                hits.append({"component": entry["c"], "relpath": entry["_rel"], "sha256": digest, "pattern": pid})
    return hits, errors


def classify_l2_hits(hits, allow):
    new = []
    allowed = []
    for hit in hits:
        if is_allowlisted(allow, hit["component"], hit["relpath"], hit["sha256"], hit["pattern"]):
            allowed.append(hit)
        else:
            new.append(hit)
    return new, allowed


def stale_allowlist_entries(entries, hits):
    keys = set((h["component"], h["relpath"], h["sha256"], h["pattern"]) for h in hits)
    return [e for e in entries if (e["component"], e["relpath"], e["sha256"], e["pattern"]) not in keys]


def report_json(hit):
    return json.dumps({"component": hit["component"], "relpath": hit["relpath"], "sha256": hit["sha256"],
                       "pattern": hit["pattern"], "note": ""}, separators=(", ", ": "))


def load_deploy_files(ctx):
    """Read scripts/deploy/* into memory before any write (stage step 4); parse the allowlist."""
    directory = deploy_dir()
    for name in DEPLOY_SCRIPT_FILES:
        with open(os.path.join(directory, name), "rb") as fh:
            ctx.script_bytes[name] = fh.read()
    try:
        ctx.allow, ctx.allow_entries = parse_allowlist(ctx.script_bytes["credential_allowlist.json"],
                                                       os.path.join(directory, "credential_allowlist.json"))
        ctx.allow_error = None
    except ValueError as exc:
        ctx.allow, ctx.allow_entries, ctx.allow_error = set(), [], str(exc)


def prepare_l2(ctx):
    ctx.l2_hits, ctx.l2_errors = l2_scan_sources(ctx)
    ctx.l2_new, ctx.l2_allowed = classify_l2_hits(ctx.l2_hits, ctx.allow)


def _read_token_file(path, label, add, sources, errors):
    if not os.path.lexists(path):
        sources.append({"source": label, "present": False, "values": 0})
        return
    try:
        with open(path, "rb") as fh:
            value = fh.read().strip()
    except OSError as exc:
        errors.append("B14: cannot read %s: %s" % (label, exc))
        sources.append({"source": label, "present": True, "values": 0})
        return
    sources.append({"source": label, "present": True, "values": add(label, [value])})


def load_known_secrets():
    """L3 secret values (spec 8.3). Values are never written, logged, hashed into output or measured."""
    H = home()
    values = []
    sources = []
    errors = []

    def add(label, candidates):
        count = 0
        for value in candidates:
            if not value:
                continue
            count += 1
            if len(value) < 16:
                errors.append("B14: a known-secret value from %s is too short to scan safely (< 16 bytes)" % label)
            if value not in values:
                values.append(value)
        return count

    _read_token_file(H + "/.cache/huggingface/token", H + "/.cache/huggingface/token", add, sources, errors)
    stored = H + "/.cache/huggingface/stored_tokens"
    if not os.path.lexists(stored):
        sources.append({"source": stored, "present": False, "values": 0})
    else:
        found = []
        try:
            with open(stored, "rb") as fh:
                text = fh.read().decode("utf-8")
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            for section in parser.sections():
                if parser.has_option(section, "hf_token"):
                    found.append(parser.get(section, "hf_token").strip().encode("utf-8"))
                if parser.has_option(section, "refresh_token"):
                    found.append(parser.get(section, "refresh_token").strip().encode("utf-8"))
        except (OSError, UnicodeDecodeError, configparser.Error):
            errors.append("B14: %s exists but cannot be parsed" % stored)
            sources.append({"source": stored, "present": True, "values": 0})
        else:
            if not [v for v in found if v]:
                errors.append("B14: %s yields no hf_token or refresh_token values" % stored)
            sources.append({"source": stored, "present": True, "values": add(stored, found)})
    ltx_token = H + "/ltx-2-mlx/hf_cache/token"
    _read_token_file(ltx_token, ltx_token, add, sources, errors)
    env_value = os.environ.get("HF_TOKEN")
    if env_value is None:
        sources.append({"source": "$HF_TOKEN", "present": False, "values": 0})
    else:
        sources.append({"source": "$HF_TOKEN", "present": True, "values": add("$HF_TOKEN", [env_value.strip().encode("utf-8")])})
    return values, sources, errors


def list_tree(root):
    """[(relpath, lstat)] for everything under root, sorted, never following symlinks."""
    out = []

    def walk(rel_dir):
        abs_dir = root + "/" + rel_dir if rel_dir else root
        for name in sorted(os.listdir(abs_dir)):
            rel = rel_dir + "/" + name if rel_dir else name
            st = os.lstat(root + "/" + rel)
            out.append((rel, st))
            if stat.S_ISDIR(st.st_mode):
                walk(rel)
    walk("")
    return out


def allowlist_key(rel):
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "payload":
        return parts[1].split("-", 1)[0], "/".join(parts[2:])
    return "ROOT", rel


def scan_package(package_root, allow):
    """L1 + L2 over every file and symlink under package_root; any .DS_Store fails."""
    failures = []
    allowed = []
    for rel, st in list_tree(package_root):
        name = rel.rsplit("/", 1)[-1]
        if name == ".DS_Store":
            failures.append("DS_Store: " + rel)
            continue
        if stat.S_ISDIR(st.st_mode):
            continue
        if name in L1_NAMES:
            failures.append("L1 " + rel)
        if stat.S_ISREG(st.st_mode) and st.st_size <= L2_MAX_BYTES:
            with open(package_root + "/" + rel, "rb") as fh:
                data = fh.read()
            pids = l2_scan_bytes(data)
            if pids:
                component, relpath = allowlist_key(rel)
                digest = sha256_bytes(data)
                for pid in pids:
                    if is_allowlisted(allow, component, relpath, digest, pid):
                        allowed.append({"component": component, "relpath": relpath, "sha256": digest, "pattern": pid})
                    else:
                        failures.append("L2 %s %s" % (pid, rel))
    return failures, allowed


def check_b12(ctx):
    ok = not ctx.l1_hits
    message = ("L1: no credential-named files" if ok else
               "L1: credential-named file(s) (a component root is wrong): %s" % ", ".join(ctx.l1_hits))
    return CheckResult("B12", ok, message, True)


def check_b13(ctx):
    problems = []
    if ctx.allow_error:
        problems.append("allowlist failed to load: %s" % ctx.allow_error)
    problems.extend(ctx.l2_errors)
    if ctx.l2_new:
        shown = "; ".join("%s %s %s" % (h["component"], h["relpath"], h["pattern"]) for h in ctx.l2_new[:20])
        problems.append("%d L2 hit(s) not allowlisted (review them with --credential-report): %s" % (len(ctx.l2_new), shown))
    ok = not problems
    message = ("L2: %d hit(s), all allowlisted" % len(ctx.l2_allowed)) if ok else " | ".join(problems)
    return CheckResult("B13", ok, message, True)


def stale_allowlist_warnings(ctx):
    return [CheckResult("B13", False, "stale allowlist entry " + json.dumps(entry, separators=(", ", ": ")), False)
            for entry in stale_allowlist_entries(ctx.allow_entries, ctx.l2_hits)]


def check_b14(ctx):
    ok = not ctx.l3_errors
    present = ", ".join("%s=%s" % (s["source"], "present" if s["present"] else "absent") for s in ctx.l3_sources)
    message = ("L3: %d distinct known-secret value(s) loaded (%s)" % (len(ctx.secrets), present)) if ok else "; ".join(ctx.l3_errors)
    return CheckResult("B14", ok, message, True)


def credential_scan_doc(ctx):
    return {
        "l1_names": sorted(L1_NAMES),
        "l2_patterns": dict((pid, rx.pattern.decode("latin-1")) for pid, rx in L2_PATTERNS),
        "l2_max_bytes": L2_MAX_BYTES,
        "l2_allowlisted_hits": list(ctx.l2_allowed),
        "l3_sources": list(ctx.l3_sources),
    }


def l4_rescan(ctx):
    failures, allowed = scan_package(ctx.package_root, ctx.allow)
    if failures:
        raise CredentialLeak("L4: %d finding(s) in the package: %s" % (len(failures), "; ".join(failures[:20])))


def cmd_credential_report(args):
    ctx = BuildCtx(args)
    enumerate_components(ctx)
    load_deploy_files(ctx)
    prepare_l2(ctx)
    for path in ctx.l1_hits:
        print("L1 " + path)
    for hit in ctx.l2_hits:
        print("L2 %s %s" % ("ALLOWLISTED" if hit in ctx.l2_allowed else "NEW", report_json(hit)))
    stale = stale_allowlist_entries(ctx.allow_entries, ctx.l2_hits)
    for entry in stale:
        print("STALE " + json.dumps(entry, separators=(", ", ": ")))
    for message in ctx.enum_errors + ctx.l2_errors:
        print("ENUM-ERROR " + message)
    if ctx.allow_error:
        print("ALLOWLIST-ERROR " + ctx.allow_error)
    clean = not (ctx.l1_hits or ctx.l2_new or ctx.enum_errors or ctx.l2_errors or ctx.allow_error)
    print("build_pkg: CREDENTIAL REPORT %s: l1=%d new=%d allowlisted=%d stale=%d" % (
        "CLEAN" if clean else "NOT CLEAN", len(ctx.l1_hits), len(ctx.l2_new), len(ctx.l2_allowed), len(stale)))
    return 0 if clean else 1
```

Implementer notes:
- `    return (component, relpath, sha256, pattern_id) in allow` is mutation anchor M9; keep it exactly.
- `l4_rescan` is only **defined** here. Its single call site (`        l4_rescan(ctx)`) is added in Task 6.
- Nothing in this file may contain the substring `    l4_rescan(ctx)` other than that call. `def l4_rescan(ctx):` is fine, because "def " precedes the name.

- [ ] **Step 4: Run the tests to verify they pass (both interpreters).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py; echo rc=$?`
Expected: `33 passed`, rc=0.

Run: `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (each one must turn at least one test red; revert after each).**
  - (a) Change `["token", "stored_tokens",` to `["stored_tokens",` → `test_T10a_…` and `test_T11_…` FAIL.
  - (b) Replace the `is_allowlisted` body with `    return any(a[0] == component and a[1] == relpath and a[3] == pattern_id for a in allow)` → `test_T12_…` FAILS.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/scripts/deploy/credential_allowlist.json qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: four-layer credential gate helpers (L1/L2/allowlist, L3 sources, L4 scan) and --credential-report"
```

---

### Task 4: Build-side checks B01-B17 (host facts, freezes, git record, offline gates) and resume-prefix analysis

**Files:**
- Modify: `scripts/deploy/build_pkg.py` (append at end)
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - constants `LTX25_LITERAL`, `GATE_SPECS`, `EXTRA_SPECS`, `OK_LINE_RE`;
  - `run_offline_gates(run, py, cwd) -> (gates, extras)`. It is shared with `install_pkg`; `run` is any callable with the `HOOKS["run"]` signature;
  - `gate_build_failures(gates, extras) -> [str]`;
  - `check_offline_gates(ctx)` (id B15; sets `ctx.baseline`);
  - `freeze_commands() -> ((rel, argv), ...)`, `gather_host_facts(ctx)`, `gather_freezes(ctx)`, `git_file_state(repo, rel) -> (info, reason)`, `gather_git_record(ctx)`;
  - `read_pyvenv_home(path)`, `hf_repo_problems(repo_dir, pin)`, `target_allowed(t)`;
  - `entry_identity(entry)`, `payload_matches(package_root, line)`, `analyze_resume(ctx)`;
  - `check_b01` … `check_b11`, `check_b16`, `check_b17`;
  - `run_prebuild_checks(ctx) -> [CheckResult]`.
- Test helper produced: `prebuild(fx, *extra) -> (ctx, results, by_id)`.

- [ ] **Step 1: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
def prebuild(fx, *extra):
    args = bp.parse_args(["--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))
    ctx = bp.BuildCtx(args)
    ctx.secrets, ctx.l3_sources, ctx.l3_errors = bp.load_known_secrets()
    bp.enumerate_components(ctx)
    results = bp.run_prebuild_checks(ctx)
    by_id = {}
    for result in results:
        by_id.setdefault(result.check_id, result)
    return ctx, results, by_id


class TestBuildChecks(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.fx.configure_build_hooks()

    def check(self, check_id, *extra):
        return prebuild(self.fx, *extra)[2][check_id]

    def test_clean_fixture_passes_every_check_in_table_order(self):
        ctx, results, by_id = prebuild(self.fx)
        self.assertEqual([r.check_id for r in results], ["B%02d" % i for i in range(1, 18)])
        self.assertEqual([bp.format_result(r) for r in results if not r.ok], [])
        self.assertEqual(ctx.baseline["schema_version"], 1)
        self.assertEqual(ctx.baseline["interpreter"], self.fx.fw_py)
        self.assertEqual(ctx.baseline["cwd"], self.fx.ws)
        self.assertEqual(ctx.baseline["gates"][0], {"id": "G1", "argv": ["tests/test_ltx_movie_offline.py"], "rc": 0, "last_line": "OK 118/118"})
        self.assertEqual([g["id"] for g in ctx.baseline["gates"]], ["G1", "G2", "G3", "G4", "G5", "G6", "G7"])
        self.assertEqual(ctx.baseline["extras"], [
            {"id": "X1", "argv": ["bin/ltx-mlx-render", "--help"], "rc": 0},
            {"id": "X2", "argv": list(X2_ARGV), "rc": 0, "brace_lines": 0}])
        self.assertEqual(ctx.host["vllm_version"], "0.27.1")          # C1: last line, not the INFO line
        self.assertEqual(ctx.host["memsize"], 68719476736)
        self.assertEqual(ctx.host["ffmpeg_version"], "ffmpeg version 9.0.1 Copyright (c) 2000-2026 the FFmpeg developers")
        self.assertEqual(ctx.host["falconsai_source_hub"], self.fx.usb_hub)
        self.assertEqual(sorted(ctx.freezes), ["manifests/pip-freeze-framework-py313.txt", "manifests/pip-freeze-ltx2mlx-venv.txt", "manifests/pip-freeze-vllm-venv.txt"])
        self.assertEqual(ctx.git_record["head"], HEAD_SHA)
        self.assertEqual(ctx.git_record["branch"], "ltx2-mlx-video-pipeline")
        self.assertEqual(list(ctx.git_record["pipeline_files"]), list(PIPELINE))
        self.assertEqual(list(ctx.git_record["test_files"]), list(TESTS7))
        info = ctx.git_record["pipeline_files"]["bin/ltx-movie"]
        self.assertEqual(info["sha256"], file_sha256(self.fx.ws + "/bin/ltx-movie"))
        self.assertTrue(info["clean"])
        gate_calls = [c for c in self.fx.run.kwcalls if c[0][1:2] == ("tests/test_ltx_movie_offline.py",)]
        self.assertEqual(gate_calls, [((self.fx.fw_py, "tests/test_ltx_movie_offline.py"), 900, self.fx.ws)])

    def test_B01_usb_volume(self):
        self.fx.mounts.clear()
        self.assertFalse(self.check("B01").ok)
        self.fx.mounts.add(self.fx.usb)
        for personality in ("APFS", "Case-sensitive Journaled HFS+"):
            bp.HOOKS["diskutil_personality"] = lambda path, value=personality: value
            self.assertFalse(self.check("B01").ok, personality)

    def test_B02_free_space(self):
        bp.HOOKS["statvfs_free"] = lambda path: 1000
        ctx, results, by_id = prebuild(self.fx)
        self.assertFalse(by_id["B02"].ok)
        total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
        self.assertEqual(ctx.required_bytes, total + bp.BUILD_HEADROOM_BYTES)
        self.assertIn("required=%d" % ctx.required_bytes, by_id["B02"].message)

    def test_B03_sources_and_venv_pins(self):
        cfg = self.fx.home + "/.venv-vllm-metal/pyvenv.cfg"
        write_file(cfg, b"home = /usr/bin\n")
        result = self.check("B03")
        self.assertFalse(result.ok)
        self.assertIn(cfg, result.message)
        write_file(cfg, ("home = %s\n" % os.path.dirname(self.fx.brew_py312)).encode("utf-8"))
        self.assertTrue(self.check("B03").ok)
        ltx_cfg = self.fx.home + "/ltx-2-mlx/.venv/pyvenv.cfg"
        write_file(ltx_cfg, b"home = /opt/other/bin\n")
        self.assertFalse(self.check("B03").ok)
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        write_file(ltx_cfg, ("home = %s/bin\n" % bp.b3_source()).encode("utf-8"))
        os.mkfifo(fifo)
        result = self.check("B03")
        self.assertFalse(result.ok)
        self.assertIn(fifo, result.message)

    def test_B04_RF3_pack_file_set(self):
        P = self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"
        self.assertTrue(self.check("B04").ok)
        os.unlink(P + "/vocoder.safetensors")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("missing=['vocoder.safetensors']", result.message)
        self.assertIn("extra=[]", result.message)
        write_file(P + "/vocoder.safetensors", b"v")
        write_file(P + "/transformer-dev.safetensors.part", b"partial")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("extra=['transformer-dev.safetensors.part']", result.message)
        os.unlink(P + "/transformer-dev.safetensors.part")
        os.unlink(P + "/LICENSE")
        os.makedirs(P + "/LICENSE")
        result = self.check("B04")
        self.assertFalse(result.ok)
        self.assertIn("not_regular=['LICENSE']", result.message)

    def test_B05_hf_repo_completeness(self):
        hub = self.fx.home + "/hf_home/hub"
        repo, pin = PINS["H1"]
        R = hub + "/" + repo
        write_file(R + "/refs/main", b"0" * 40)
        self.assertFalse(self.check("B05").ok)
        write_file(R + "/refs/main", pin.encode("ascii"))
        self.assertTrue(self.check("B05").ok)
        os.makedirs(R + "/snapshots/" + "1" * 40)
        self.assertFalse(self.check("B05").ok)
        os.rmdir(R + "/snapshots/" + "1" * 40)
        write_file(R + "/blobs/abc.incomplete", b"")
        self.assertFalse(self.check("B05").ok)
        os.unlink(R + "/blobs/abc.incomplete")
        make_link(R + "/snapshots/" + pin + "/missing.json", "../../blobs/nothere")
        result = self.check("B05")
        self.assertFalse(result.ok)
        self.assertIn("missing.json", result.message)
        os.unlink(R + "/snapshots/" + pin + "/missing.json")
        write_file(self.fx.usb_hub + "/" + PINS["H3"][0] + "/refs/main", b"f" * 40)
        self.assertFalse(self.check("B05").ok)

    def test_B06_case_insensitive_collisions(self):
        ctx = self.fx.ctx()
        self.assertTrue(bp.check_b06(ctx).ok)
        entry = [e for e in ctx.entries if e["c"] == "A1" and e["k"] == "f"][0]
        ctx.entries.append(dict(entry, t=entry["t"].upper(), p=entry["p"] + "-other"))
        result = bp.check_b06(ctx)
        self.assertFalse(result.ok)
        self.assertIn("t collision", result.message)
        ctx = self.fx.ctx()
        ctx.entries.append(dict(entry, p=entry["p"].upper(), t=entry["t"] + "-other"))
        result = bp.check_b06(ctx)
        self.assertFalse(result.ok)
        self.assertIn("p collision", result.message)

    def test_B07_package_root_state(self):
        self.assertTrue(self.check("B07").ok)
        os.makedirs(self.fx.pkg)
        result = self.check("B07")
        self.assertFalse(result.ok)
        self.assertIn("already exists", result.message)
        result = self.check("B07", "--apply", "--resume")
        self.assertTrue(result.ok, result.message)
        self.assertIn("resume prefix: 0 of", result.message)
        write_file(self.fx.pkg + "/MANIFEST.json", b"{}")
        result = self.check("B07", "--apply", "--resume")
        self.assertFalse(result.ok)
        self.assertIn("MANIFEST.json", result.message)
        shutil.rmtree(self.fx.pkg)
        result = self.check("B07", "--apply", "--resume")
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.message)

    def test_B07_resume_prefix_analysis(self):
        root = self.fx.pkg
        os.makedirs(root)
        ctx = self.fx.ctx("--apply", "--resume")
        e0, e1, e2 = ctx.entries[0], ctx.entries[1], ctx.entries[2]
        self.assertEqual((e0["k"], e1["k"], e2["k"]), ("d", "d", "f"))
        os.makedirs(root + "/" + e1["p"])
        shutil.copyfile(e2["_src"], root + "/" + e2["p"])
        lines = [dict(e0), dict(e1), dict(e2, h=file_sha256(e2["_src"]))]
        data = "".join(bp.entry_line(x) for x in lines).encode("utf-8")
        partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
        write_file(partial, data + b'{"k":"f","c":"A')
        bp.analyze_resume(ctx)
        self.assertEqual((ctx.resume_prefix_len, ctx.resume_keep_bytes, ctx.resume_rename, ctx.resume_error), (3, len(data), False, None))
        self.assertEqual(ctx.entries[2]["h"], file_sha256(e2["_src"]))
        with open(root + "/" + e2["p"], "r+b") as fh:
            fh.write(b"X")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertEqual(ctx.resume_prefix_len, 2)
        self.assertEqual(ctx.resume_keep_bytes, len("".join(bp.entry_line(x) for x in lines[:2]).encode("utf-8")))
        os.rename(partial, root + "/MANIFEST-ENTRIES.jsonl")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertTrue(ctx.resume_rename)
        os.unlink(root + "/MANIFEST-ENTRIES.jsonl")
        write_file(partial, bp.entry_line(dict(e0, t=e0["t"] + "x")).encode("utf-8"))
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertTrue(ctx.resume_error.startswith("enumeration changed since the interrupted build; delete %s and rebuild" % root))
        write_file(partial, "".join(bp.entry_line(x) for x in [lines[0], lines[1], dict(lines[2], mt=e2["mt"] + 1)]).encode("utf-8"))
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertEqual(ctx.resume_error, "source changed since the interrupted build: " + e2["_src"])
        write_file(partial, b"not json\n")
        ctx = self.fx.ctx("--apply", "--resume")
        bp.analyze_resume(ctx)
        self.assertIn("not valid JSON", ctx.resume_error)

    def test_B08_synthetic_symlink_target(self):
        link = self.fx.home + "/mlx_models/qwen3-vl"
        os.unlink(link)
        make_link(link, "/elsewhere")
        self.assertFalse(self.check("B08").ok)
        os.unlink(link)
        self.assertFalse(self.check("B08").ok)

    def test_B09_port(self):
        bp.HOOKS["port_free"] = lambda port: False
        result = self.check("B09")
        self.assertFalse(result.ok)
        self.assertIn("stop the story server", result.message)

    def test_B10_hf_scope(self):
        H = self.fx.home
        self.assertTrue(bp.check_b10(self.fx.ctx()).ok)
        base = {"k": "f", "c": "B1", "p": "payload/B1-ltx2mlx-repo/x", "b": 1, "m": "0644", "mt": 1}
        cases = [
            dict(base, t=H + "/ltx-2-mlx/x", _src=H + "/hf_home/hub/models--other/x"),
            dict(base, t=H + "/ltx-2-mlx/x", _src=H + "/.cache/huggingface/token"),
            dict(base, t=H + "/ltx-2-mlx/x", _src=os.path.dirname(self.fx.usb_hub) + "/hub/models--other/y"),
            dict(base, c="H1", t=H + "/hf_home/hub/models--other/y", _src=H + "/hf_home/hub/" + PINS["H1"][0] + "/y"),
            dict(base, t=H + "/ltx-2-mlx/hf_cache/token", _src=H + "/ltx-2-mlx/README.md"),
        ]
        for extra in cases:
            ctx = self.fx.ctx()
            ctx.entries.append(extra)
            self.assertFalse(bp.check_b10(ctx).ok, extra)

    def test_B11_RF5_target_path_allowlist(self):
        H, fw, ulb = self.fx.home, self.fx.fw, self.fx.ulb
        for t in (H + "/x", fw, fw + "/Versions/3.13/bin/python3", ulb, ulb + "/python3"):
            self.assertTrue(bp.target_allowed(t), t)
        for t in ("/tmp/evil", H, H + "X/evil", fw + "X", fw + "X/y", ulb + "X", "/Volumes/Ollama/x",
                  "/opt/homebrew/bin/x", H + "/../evil", H + "/a/../../evil", H + "//x", H + "/./x", H + "/x/",
                  "relative/x", ""):
            self.assertFalse(bp.target_allowed(t), t)
        ctx = self.fx.ctx()
        self.assertTrue(bp.check_b11(ctx).ok)
        ctx.entries.append({"k": "d", "c": "H0", "t": H + "/../../etc/evil", "m": "0755", "s": True})
        result = bp.check_b11(ctx)
        self.assertFalse(result.ok)
        self.assertIn(H + "/../../etc/evil", result.message)
        with mock.patch.object(bp, "REQUIRED_HOME", H + "-other"):
            result = bp.check_b11(self.fx.ctx())
        self.assertFalse(result.ok)
        self.assertIn("home()", result.message)

    def test_B15_offline_gates(self):
        fw = self.fx.fw_py
        cases = [((fw, "tests/test_ltx_story_images.py"), (1, "FAILED\nOK 97/98\n"), "G3"),
                 ((fw, "tests/check_ltx2_mlx_no_forbidden_imports.py"), (0, "RESULT: 1 forbidden import\n"), "G7"),
                 ((fw,) + X2_ARGV, (0, '{"x": 1}\n'), "X2"),
                 ((fw, "tests/test_ltx_movie_offline.py"), (0, "OK 117/118\n"), "G1"),
                 ((fw, "tests/test_ltx_mlx_render.py"), (0, ""), "G2"),
                 ((fw, "bin/ltx-mlx-render", "--help"), (2, "usage error\n"), "X1")]
        for key, value, gate_id in cases:
            self.fx.run.overrides = {key: value}
            result = self.check("B15")
            self.assertFalse(result.ok, gate_id)
            self.assertIn(gate_id, result.message)
        self.fx.run.overrides = {}
        self.assertTrue(self.check("B15").ok)

    def test_B16_host_facts_and_freezes(self):
        cases = [(("/usr/sbin/sysctl", "-n", "hw.model"), (1, "error"), "hw_model"),
                 (("/usr/sbin/sysctl", "-n", "hw.memsize"), (0, "abc\n"), "memsize"),
                 ((self.fx.vllm_py, "-m", "pip", "freeze", "--all"), (1, "boom"), "pip-freeze-vllm-venv.txt")]
        for key, value, word in cases:
            self.fx.run.overrides = {key: value}
            result = self.check("B16")
            self.assertFalse(result.ok, word)
            self.assertIn(word, result.message)
        self.fx.run.overrides = {}
        bp.HOOKS["which"] = lambda name: None
        result = self.check("B16")
        self.assertFalse(result.ok)
        self.assertIn("ffmpeg", result.message)

    def test_B17_provenance(self):
        self.fx.untracked.add("qwen-agent-workspace/bin/story-server")
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("bin/story-server: untracked", result.message)
        self.fx.untracked.clear()
        self.fx.modified.add("qwen-agent-workspace/bin/qwen-agent")
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("bin/qwen-agent: modified", result.message)
        self.fx.modified.clear()
        self.fx.committed["qwen-agent-workspace/z_image_skill.py"] = "0" * 40
        result = self.check("B17")
        self.assertFalse(result.ok)
        self.assertIn("z_image_skill.py: blob differs", result.message)
        self.fx.committed.clear()
        self.fx.modified.add("qwen-agent-workspace/tests/test_ltx_image_fit.py")
        ctx, results, by_id = prebuild(self.fx)
        self.assertTrue(by_id["B17"].ok, by_id["B17"].message)
        self.assertFalse(ctx.git_record["test_files"]["tests/test_ltx_image_fit.py"]["clean"])
        self.assertEqual(ctx.git_record["porcelain"], [" M qwen-agent-workspace/tests/test_ltx_image_fit.py"])
```

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k TestBuildChecks`
Expected: FAIL with `AttributeError: module 'build_pkg' has no attribute 'run_prebuild_checks'`.

- [ ] **Step 3: Write the implementation** — append to the end of `scripts/deploy/build_pkg.py`:

```python


# ---------------------------------------------------------------------------
# Offline gates (spec 10.1) -- shared with install_pkg (accept A3)
# ---------------------------------------------------------------------------
LTX25_LITERAL = "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"
GATE_SPECS = (
    ("G1", ("tests/test_ltx_movie_offline.py",)),
    ("G2", ("tests/test_ltx_mlx_render.py",)),
    ("G3", ("tests/test_ltx_story_images.py",)),
    ("G4", ("tests/test_ltx2_mlx_video_skill.py",)),
    ("G5", ("tests/test_ltx_image_fit.py",)),
    ("G6", ("tests/test_ltx_story_manifest_chain.py",)),
    ("G7", ("tests/check_ltx2_mlx_no_forbidden_imports.py",)),
)
EXTRA_SPECS = (
    ("X1", ("bin/ltx-mlx-render", "--help")),
    ("X2", ("bin/ltx-movie", "a test narrative", "--story-id", "deploy-gate-dry", "--dry-run", "--no-review",
            "--model", LTX25_LITERAL)),
)
OK_LINE_RE = re.compile(r"^OK (\d+)/\1$")


def run_offline_gates(run, py, cwd):
    """Run G1-G7 then X1, X2 by direct invocation (never through pytest)."""
    gates = []
    for gate_id, argv in GATE_SPECS:
        rc, text = run([py] + list(argv), timeout=GATE_TIMEOUT, cwd=cwd)
        gates.append({"id": gate_id, "argv": list(argv), "rc": rc, "last_line": last_line(text)})
    extras = []
    for extra_id, argv in EXTRA_SPECS:
        rc, text = run([py] + list(argv), timeout=GATE_TIMEOUT, cwd=cwd)
        record = {"id": extra_id, "argv": list(argv), "rc": rc}
        if extra_id == "X2":
            record["brace_lines"] = sum(1 for line in text.splitlines() if "{" in line or "}" in line)
        extras.append(record)
    return gates, extras


def gate_build_failures(gates, extras):
    bad = []
    for gate in gates:
        if gate["id"] == "G7":
            ok = gate["rc"] == 0 and gate["last_line"] == "RESULT: ok"
        else:
            ok = gate["rc"] == 0 and OK_LINE_RE.match(gate["last_line"]) is not None
        if not ok:
            bad.append("%s rc=%r last_line=%r" % (gate["id"], gate["rc"], gate["last_line"]))
    for extra in extras:
        if extra["id"] == "X1" and extra["rc"] != 0:
            bad.append("X1 rc=%r" % extra["rc"])
        if extra["id"] == "X2" and (extra["rc"] != 0 or extra["brace_lines"] != 0):
            bad.append("X2 rc=%r brace_lines=%r" % (extra["rc"], extra["brace_lines"]))
    return bad


def check_offline_gates(ctx):
    gates, extras = run_offline_gates(_run, framework_py(), workspace())
    ctx.baseline = {"schema_version": 1, "measured_at": iso_now(), "interpreter": framework_py(),
                    "cwd": workspace(), "gates": gates, "extras": extras}
    bad = gate_build_failures(gates, extras)
    message = "offline gates G1-G7, X1, X2 passed" if not bad else "offline gate failure(s): " + "; ".join(bad)
    return CheckResult("B15", not bad, message, True)


# ---------------------------------------------------------------------------
# Host facts, pip freezes, git provenance (spec 6.4, B16, B17)
# ---------------------------------------------------------------------------
def _first_line(text):
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _probe(ctx, key, argv, pick_last=False):
    rc, text = _run(argv, timeout=HOST_TIMEOUT)
    if rc != 0:
        ctx.host_failures.append("%s: %s exited %d" % (key, " ".join(argv), rc))
        return ""
    return last_line(text).strip() if pick_last else _first_line(text)


def gather_host_facts(ctx):
    H = home()
    host = {}
    host["hw_model"] = _probe(ctx, "hw_model", ["/usr/sbin/sysctl", "-n", "hw.model"])
    host["cpu"] = _probe(ctx, "cpu", ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"])
    memsize = _probe(ctx, "memsize", ["/usr/sbin/sysctl", "-n", "hw.memsize"])
    if memsize.isdigit():
        host["memsize"] = int(memsize)
    else:
        host["memsize"] = -1
        ctx.host_failures.append("memsize: %r is not an integer" % memsize)
    host["product_version"] = _probe(ctx, "product_version", ["/usr/bin/sw_vers", "-productVersion"])
    host["build_version"] = _probe(ctx, "build_version", ["/usr/bin/sw_vers", "-buildVersion"])
    host["machine"] = platform.machine()
    host["framework_python_version"] = _probe(ctx, "framework_python_version",
                                              [framework_py(), "-c", "import sys;print(sys.version.split()[0])"])
    for key, tool in (("ffmpeg_version", "ffmpeg"), ("ffprobe_version", "ffprobe")):
        path = HOOKS["which"](tool)
        if path:
            host[key] = _probe(ctx, key, [path, "-version"])
        else:
            host[key] = ""
            ctx.host_failures.append("%s: %s not found on PATH" % (key, tool))
    host["brew_version"] = _probe(ctx, "brew_version", [BREW_BIN, "--version"])
    host["brew_python312_version"] = _probe(ctx, "brew_python312_version", [BREW_PY312, "--version"])
    # C1: vllm logs timestamped INFO lines before the version; the version is the LAST line.
    host["vllm_version"] = _probe(ctx, "vllm_version", [H + "/.venv-vllm-metal/bin/python", "-c",
                                                        "import vllm; print(vllm.__version__)"], pick_last=True)
    host["falconsai_source_hub"] = ctx.falconsai_hub or ""
    host["gathered_at"] = iso_now()
    ctx.host = host


def freeze_commands():
    H = home()
    return (
        ("manifests/pip-freeze-framework-py313.txt",
         [framework_py(), "-m", "pip", "freeze", "--all", "--exclude", "fubotv-mcp-common", "--exclude", "student-agent-mcp"]),
        ("manifests/pip-freeze-ltx2mlx-venv.txt",
         [FRAMEWORK_ROOT + "/Versions/3.13/bin/uv", "pip", "freeze", "--python", H + "/ltx-2-mlx/.venv/bin/python"]),
        ("manifests/pip-freeze-vllm-venv.txt",
         [H + "/.venv-vllm-metal/bin/python", "-m", "pip", "freeze", "--all"]),
    )


def gather_freezes(ctx):
    for rel, argv in freeze_commands():
        rc, text = _run(argv, timeout=FREEZE_TIMEOUT)
        if rc != 0:
            ctx.host_failures.append("%s: %s exited %d" % (rel, " ".join(argv), rc))
        ctx.freezes[rel] = text


def git_file_state(repo, rel):
    rp = WS_REPO_PREFIX + "/" + rel
    abs_path = workspace() + "/" + rel
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return {"sha256": "", "git_blob": "", "clean": False}, "missing"
    rc_ls, _ = _run([GIT, "-C", repo, "ls-files", "--error-unmatch", "--", rp])
    rc_st, st_out = _run([GIT, "-C", repo, "status", "--porcelain", "--", rp])
    rc_ho, ho_out = _run([GIT, "-C", repo, "hash-object", abs_path])
    rc_rp, rp_out = _run([GIT, "-C", repo, "rev-parse", "HEAD:" + rp])
    blob = rp_out.strip() if rc_rp == 0 else ""
    reason = ""
    if rc_ls != 0:
        reason = "untracked"
    elif rc_st != 0 or st_out.strip():
        reason = "modified"
    elif rc_ho != 0 or rc_rp != 0 or ho_out.strip() != blob:
        reason = "blob differs"
    return {"sha256": sha256_bytes(data), "git_blob": blob, "clean": not reason}, reason


def gather_git_record(ctx):
    repo = repo_root()
    problems = []
    rc, out = _run([GIT, "-C", repo, "rev-parse", "HEAD"])
    if rc != 0:
        problems.append("git rev-parse HEAD failed (rc=%d)" % rc)
    head = out.strip() if rc == 0 else ""
    rc, out = _run([GIT, "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    branch = out.strip() if rc == 0 else ""
    rc, out = _run([GIT, "-C", repo, "status", "--porcelain", "--", WS_REPO_PREFIX])
    porcelain = [line for line in out.splitlines() if line.strip()] if rc == 0 else []
    record = {"head": head, "branch": branch, "porcelain": porcelain, "pipeline_files": {}, "test_files": {}}
    for rel in PIPELINE_FILES:
        info, reason = git_file_state(repo, rel)
        record["pipeline_files"][rel] = info
        if reason:
            problems.append("%s: %s" % (rel, reason))
    for rel in TEST_FILES:
        info, reason = git_file_state(repo, rel)
        record["test_files"][rel] = info
    ctx.git_record = record
    ctx.git_problems = problems


# ---------------------------------------------------------------------------
# Resume-prefix analysis (spec 11.3; read-only, used by B07)
# ---------------------------------------------------------------------------
def entry_identity(entry):
    return tuple(entry.get(key) for key in ("k", "c", "p", "t", "l", "s"))


def payload_matches(package_root, line):
    if "p" not in line:
        return True
    path = package_root + "/" + line["p"]
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if line["k"] == "f":
        return stat.S_ISREG(st.st_mode) and st.st_size == line.get("b") and sha256_file(path) == line.get("h")
    if line["k"] == "l":
        return stat.S_ISLNK(st.st_mode) and os.readlink(path) == line.get("l")
    return stat.S_ISDIR(st.st_mode)


def analyze_resume(ctx):
    root = ctx.package_root
    partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
    final = root + "/MANIFEST-ENTRIES.jsonl"
    ctx.resume_prefix_len = 0
    ctx.resume_keep_bytes = 0
    ctx.resume_rename = False
    ctx.resume_error = None
    if os.path.exists(partial):
        source = partial
    elif os.path.exists(final):
        source = final
        ctx.resume_rename = True
    else:
        return
    with open(source, "rb") as fh:
        data = fh.read()
    complete = data[:data.rfind(b"\n") + 1]
    offset = 0
    for index, raw in enumerate(complete.split(b"\n")[:-1]):
        try:
            line = json.loads(raw.decode("utf-8"))
        except ValueError:
            ctx.resume_error = "line %d of %s is not valid JSON; delete %s and rebuild" % (index, source, root)
            return
        if index >= len(ctx.entries) or entry_identity(line) != entry_identity(ctx.entries[index]):
            ctx.resume_error = "enumeration changed since the interrupted build; delete %s and rebuild" % root
            return
        fresh = ctx.entries[index]
        if (line.get("b"), line.get("m"), line.get("mt")) != (fresh.get("b"), fresh.get("m"), fresh.get("mt")):
            ctx.resume_error = "source changed since the interrupted build: %s" % fresh.get("_src", fresh["t"])
            return
        if not payload_matches(root, line):
            break
        if line["k"] == "f":
            fresh["h"] = line["h"]
        offset += len(raw) + 1
        ctx.resume_prefix_len = index + 1
    ctx.resume_keep_bytes = offset


# ---------------------------------------------------------------------------
# B01-B17 (spec 10)
# ---------------------------------------------------------------------------
def _under(path, root):
    return path == root or path.startswith(root + "/")


def check_b01(ctx):
    mounted = bool(HOOKS["ismount"](ctx.usb_root))
    personality = HOOKS["diskutil_personality"](ctx.usb_root) if mounted else ""
    ok = mounted and "APFS" in personality and "Case-sensitive" in personality
    return CheckResult("B01", ok, "usb_root=%s mounted=%s personality=%r (need a mounted Case-sensitive APFS volume)"
                       % (ctx.usb_root, mounted, personality), True)


def check_b02(ctx):
    total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
    done = sum(e["b"] for e in ctx.entries[:ctx.resume_prefix_len] if e["k"] == "f")
    ctx.remaining_bytes = total - done
    ctx.required_bytes = ctx.remaining_bytes + BUILD_HEADROOM_BYTES
    try:
        ctx.free_bytes = HOOKS["statvfs_free"](ctx.usb_root)
    except OSError:
        ctx.free_bytes = -1
    ok = ctx.free_bytes >= ctx.required_bytes
    return CheckResult("B02", ok, "free=%d required=%d (remaining %d + headroom %d)"
                       % (ctx.free_bytes, ctx.required_bytes, ctx.remaining_bytes, BUILD_HEADROOM_BYTES), True)


def read_pyvenv_home(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, sep, value = line.partition("=")
                if sep and key.strip() == "home":
                    return value.strip()
    except OSError:
        return None
    return None


def check_b03(ctx):
    problems = list(ctx.enum_errors)
    H = home()
    for cfg, want in ((H + "/ltx-2-mlx/.venv/pyvenv.cfg", b3_source() + "/bin"),
                      (H + "/.venv-vllm-metal/pyvenv.cfg", os.path.dirname(BREW_PY312))):
        got = read_pyvenv_home(cfg)
        if got != want:
            problems.append("%s: home = %r, expected %r" % (cfg, got, want))
    ok = not problems
    return CheckResult("B03", ok, "sources readable; venv base interpreters pinned" if ok else "; ".join(problems[:20]), True)


def check_b04(ctx):
    pack = ltx25_model_path()
    try:
        names = set(os.listdir(pack)) - set([".cache", ".DS_Store"])
    except OSError as exc:
        return CheckResult("B04", False, "cannot list %s: %s" % (pack, exc), True)
    extra = sorted(names - LTX25_PACK_FILES)
    missing = sorted(LTX25_PACK_FILES - names)
    not_regular = sorted(n for n in names & LTX25_PACK_FILES if not stat.S_ISREG(os.lstat(pack + "/" + n).st_mode))
    ok = not extra and not missing and not not_regular
    return CheckResult("B04", ok, "%s: %d pinned files; extra=%s missing=%s not_regular=%s"
                       % (pack, len(LTX25_PACK_FILES), extra, missing, not_regular), True)


def hf_repo_problems(repo_dir, pin):
    if not os.path.isdir(repo_dir):
        return ["%s: repo dir missing" % repo_dir]
    problems = []
    try:
        with open(repo_dir + "/refs/main", "r") as fh:
            ref = fh.read().strip()
    except OSError:
        ref = None
    if ref != pin:
        problems.append("%s: refs/main=%r, expected %s" % (repo_dir, ref, pin))
    try:
        snaps = sorted(n for n in os.listdir(repo_dir + "/snapshots") if n != ".DS_Store")
    except OSError:
        snaps = None
    if snaps != [pin]:
        problems.append("%s: snapshots=%r, expected [%r]" % (repo_dir, snaps, pin))
    blobs = repo_dir + "/blobs"
    if not os.path.isdir(blobs):
        problems.append("%s: blobs/ missing" % repo_dir)
    for dirpath, dirnames, filenames in os.walk(blobs):
        for name in dirnames + filenames:
            if name.endswith(".incomplete"):
                problems.append("%s: incomplete download %s" % (repo_dir, os.path.join(dirpath, name)))
    blobs_real = os.path.realpath(blobs)
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                real = os.path.realpath(path)
                if not (real.startswith(blobs_real + "/") and os.path.isfile(real)):
                    problems.append("%s: symlink does not resolve to a blob: %s" % (repo_dir, path))
    return problems


def check_b05(ctx):
    hub = home() + "/hf_home/hub"
    problems = []
    for cid in ("H1", "H2", "H3", "H4"):
        repo, pin = HF_PINS[cid]
        source_hub = ctx.falconsai_hub if cid == "H3" else hub
        if source_hub is None:
            problems.append("H3: %s not found in either hub" % repo)
            continue
        problems.extend(hf_repo_problems(source_hub + "/" + repo, pin))
    ok = not problems
    return CheckResult("B05", ok, "H1-H4 complete at their pinned snapshots" if ok else "; ".join(problems[:20]), True)


def check_b06(ctx):
    problems = []
    for key in ("p", "t"):
        seen = {}
        for entry in ctx.entries:
            if key in entry:
                seen.setdefault(entry[key].lower(), []).append(entry[key])
        for values in seen.values():
            if len(values) > 1:
                problems.append("%s collision: %s" % (key, " | ".join(values)))
    ok = not problems
    return CheckResult("B06", ok, "no case-insensitive p/t collisions" if ok else "; ".join(problems[:20]), True)


def check_b07(ctx):
    root = ctx.package_root
    if not ctx.resume:
        if os.path.lexists(root):
            return CheckResult("B07", False, "package root %s already exists; pass --resume to continue an interrupted build, or choose another --package-id" % root, True)
        return CheckResult("B07", True, "package root %s does not exist yet" % root, True)
    if not os.path.isdir(root):
        return CheckResult("B07", False, "--resume given but %s does not exist" % root, True)
    if os.path.lexists(root + "/MANIFEST.json"):
        return CheckResult("B07", False, "%s already holds MANIFEST.json (the build is complete; nothing to resume)" % root, True)
    if ctx.resume_error:
        return CheckResult("B07", False, ctx.resume_error, True)
    return CheckResult("B07", True, "resume prefix: %d of %d entries verified" % (ctx.resume_prefix_len, len(ctx.entries)), True)


def check_b08(ctx):
    want = h5_link_value()
    problems = []
    h5 = [e for e in ctx.entries if e["c"] == "H5" and e["k"] == "l"]
    h4_dirs = set(e["t"] for e in ctx.entries if e["c"] == "H4" and e["k"] == "d")
    if len(h5) != 1 or h5[0]["l"] != want or want not in h4_dirs:
        problems.append("H5 link value is not the t of the pinned H4 snapshot dir %s" % want)
    link = home() + "/mlx_models/qwen3-vl"
    try:
        live = os.readlink(link)
    except OSError:
        live = None
    if live != want:
        problems.append("live %s -> %r, expected %s" % (link, live, want))
    ok = not problems
    return CheckResult("B08", ok, "mlx_models/qwen3-vl -> pinned H4 snapshot" if ok else "; ".join(problems), True)


def check_b09(ctx):
    ok = bool(HOOKS["port_free"](STORY_PORT))
    message = ("port %d is free" % STORY_PORT) if ok else (
        "port %d is in use: stop the story server before building (bin/story-server stop)" % STORY_PORT)
    return CheckResult("B09", ok, message, True)


def check_b10(ctx):
    H = home()
    src_scopes = (H + "/hf_home", os.path.dirname(FALCONSAI_USB_HUB), H + "/.cache/huggingface", H + "/ltx-2-mlx/hf_cache")
    pinned_src = [H + "/hf_home/hub/" + HF_PINS[c][0] for c in ("H1", "H2", "H4")]
    if ctx.falconsai_hub:
        pinned_src.append(ctx.falconsai_hub + "/" + HF_PINS["H3"][0])
    pinned_tgt = [H + "/hf_home/hub/" + HF_PINS[c][0] for c in ("H1", "H2", "H3", "H4")]
    problems = []
    for entry in ctx.entries:
        src = entry.get("_src")
        if src and any(_under(src, s) for s in src_scopes) and not any(_under(src, r) for r in pinned_src):
            problems.append("source outside the pinned HF repos: %s" % src)
        target = entry["t"]
        if _under(target, H + "/hf_home") and entry["c"] != "H0" and not any(_under(target, r) for r in pinned_tgt):
            problems.append("target under ~/hf_home outside the pinned repos: %s" % target)
        if _under(target, H + "/ltx-2-mlx/hf_cache") and entry["c"] != "B5":
            problems.append("target under ~/ltx-2-mlx/hf_cache that is not a B5 dir: %s" % target)
    ok = not problems
    return CheckResult("B10", ok, "HF sources and targets stay inside the pinned repos" if ok else "; ".join(problems[:20]), True)


def target_allowed(t):
    # C3 (plan addition): absolute and already normalised, so "..", "//" and "." cannot escape.
    if not t.startswith("/") or os.path.normpath(t) != t:
        return False
    if t.startswith("/Volumes/") or t.startswith("/opt/homebrew/"):
        return False
    return (t.startswith(REQUIRED_HOME + "/")
            or t == FRAMEWORK_ROOT or t.startswith(FRAMEWORK_ROOT + "/")
            or t == USR_LOCAL_BIN or t.startswith(USR_LOCAL_BIN + "/"))


def check_b11(ctx):
    problems = []
    if home() != REQUIRED_HOME:
        problems.append("home() is %s, expected %s" % (home(), REQUIRED_HOME))
    bad = [e["t"] for e in ctx.entries if not target_allowed(e["t"])]
    if bad:
        problems.append("%d target(s) outside the allowlist: %s" % (len(bad), ", ".join(bad[:20])))
    ok = not problems
    return CheckResult("B11", ok, "every target is under %s, %s or %s" % (REQUIRED_HOME, FRAMEWORK_ROOT, USR_LOCAL_BIN) if ok else "; ".join(problems), True)


def check_b16(ctx):
    gather_host_facts(ctx)
    gather_freezes(ctx)
    ok = not ctx.host_failures
    return CheckResult("B16", ok, "host facts and 3 pip freezes gathered" if ok else "; ".join(ctx.host_failures), True)


def check_b17(ctx):
    gather_git_record(ctx)
    ok = not ctx.git_problems
    message = ("all 10 pipeline files match HEAD %s" % ctx.git_record.get("head", "")) if ok else (
        "provenance: " + "; ".join(ctx.git_problems))
    return CheckResult("B17", ok, message, True)


def run_prebuild_checks(ctx):
    """Stage step 4: B01-B17 in table order. Reads only; writes nothing."""
    load_deploy_files(ctx)
    prepare_l2(ctx)
    if ctx.resume and os.path.isdir(ctx.package_root) and not os.path.lexists(ctx.package_root + "/MANIFEST.json"):
        analyze_resume(ctx)
    results = []
    results.append(check_b01(ctx))
    results.append(check_b02(ctx))
    results.append(check_b03(ctx))
    results.append(check_b04(ctx))
    results.append(check_b05(ctx))
    results.append(check_b06(ctx))
    results.append(check_b07(ctx))
    results.append(check_b08(ctx))
    results.append(check_b09(ctx))
    results.append(check_b10(ctx))
    results.append(check_b11(ctx))
    results.append(check_b12(ctx))
    results.append(check_b13(ctx))
    results.extend(stale_allowlist_warnings(ctx))
    results.append(check_b14(ctx))
    results.append(check_offline_gates(ctx))
    results.append(check_b16(ctx))
    results.append(check_b17(ctx))
    return results
```

Implementer notes:
- `    results.append(check_offline_gates(ctx))` is anchor M4a; it must be exactly that line, once.
- B15's check function is named `check_offline_gates` (not `check_b15`), because the spec anchor requires that name.

- [ ] **Step 4: Run the tests to verify they pass (both interpreters).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py; echo rc=$?`
Expected: `49 passed`, rc=0.

Run: `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (each must turn a test red; revert after each).**
  - (a) In `gather_host_facts`, change `pick_last=True` to `pick_last=False` → `test_clean_fixture_passes_every_check_in_table_order` FAILS (vllm_version is the INFO line).
  - (b) Delete the `os.path.normpath(t) != t` clause → `test_B11_RF5_…` FAILS.
  - (c) Remove `missing` from the `ok` expression in `check_b04` → `test_B04_RF3_…` FAILS.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: pre-build checks B01-B17 (offline gates, host facts, provenance) and resume-prefix analysis"
```

---

### Task 5: README rendering (spec §14)

**Files:**
- Modify: `scripts/deploy/build_pkg.py` (append at end)
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: `ctx.package_id`, `ctx.usb_root`, `ctx.comp_stats` (Task 2), `ctx.git_record["head"/"branch"]` (Task 4), `LTX25_LITERAL` (Task 4).
- Produces: `README_PY`, `README_NARRATIVE`, `README_TEMPLATE`, `render_readme(ctx) -> str`.

- [ ] **Step 1: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
class TestReadme(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        ctx = self.fx.ctx()
        ctx.git_record = {"head": HEAD_SHA, "branch": "ltx2-mlx-video-pipeline"}
        self.text = bp.render_readme(ctx)
        self.lines = self.text.splitlines()

    def test_T90_every_ltx_movie_line_passes_model_explicitly(self):
        model = "--model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"
        hits = [line for line in self.lines if "bin/ltx-movie" in line]
        self.assertGreaterEqual(len(hits), 2)
        for line in hits:
            self.assertIn(model, line)
            self.assertFalse(line.rstrip().endswith("\\"), line)
            self.assertIn("--story-server-stop-after-story", line)
            self.assertTrue(line.strip().startswith("/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 bin/ltx-movie "), line)
        self.assertEqual(len([line for line in hits if "--seed-image " in line]), 1)

    def test_T90b_sections_and_install_commands(self):
        for heading in ("## 1. What this package is", "## 2. Target requirements", "## 3. Install",
                        "## 4. Running the pipeline", "## 5. Warnings", "## 6. Troubleshooting", "## 7. Not included"):
            self.assertIn(heading, self.text)
        inst = "/usr/bin/python3 %s/%s/scripts/deploy/install_pkg.py" % (self.fx.usb, self.fx.package_id)
        for tail in ("--phase preflight", "--phase user --apply", "--phase verify", "--phase accept --gpu", "--phase accept --gpu-all"):
            self.assertIn(inst + " " + tail, self.text)
        self.assertIn("sudo " + inst + " --phase system-python --apply", self.text)
        self.assertIn("/usr/bin/python3 /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/deploy-receipts/%s/scripts/deploy/install_pkg.py --phase accept --gpu" % self.fx.package_id, self.text)
        for needle in ('export HF_HOME="/Users/reubenpatterson/hf_home"', "brew install ffmpeg python@3.12", HEAD_SHA,
                       "2026-09-25", "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "--image-seed",
                       "~/.qwen-serve-guard/stand-down", "curl -sf http://127.0.0.1:8177/v1/models",
                       ">= 48 GiB RAM", "sudo", "32 MB/min"):
            self.assertIn(needle, self.text)

    def test_T91_forbidden_strings_absent(self):
        low = self.text.lower()
        for needle in ("--video" + "-backend", "comf" + "yui", "cct" + "ech", "chriscole" + "tech", "81" + "89"):
            self.assertNotIn(needle, low)

    def test_T92_readme_is_l2_clean(self):
        self.assertEqual(bp.l2_scan_bytes(self.text.encode("utf-8")), [])
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k TestReadme`
Expected: ERROR `AttributeError: module 'build_pkg' has no attribute 'render_readme'`.

- [ ] **Step 3: Write the implementation** — append to the end of `scripts/deploy/build_pkg.py`. The template uses 4-space-indented command blocks, not code fences; keep them exactly.

```python


# ---------------------------------------------------------------------------
# README (spec 14): rendered from a string constant before the copy
# ---------------------------------------------------------------------------
README_PY = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
README_NARRATIVE = ("An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm "
                    "rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward "
                    "the lighthouse door.")
README_TEMPLATE = """\
# ltx-chain deployment package %(package_id)s

## 1. What this package is

- Package id: %(package_id)s
- Build date: %(build_date)s
- Source git HEAD: %(head)s (branch %(branch)s)
- It installs exactly the ltx-movie sequential I2V frame-chaining pipeline on a second, similar Mac that has the same account (user reubenpatterson, home /Users/reubenpatterson). No path is re-pinned.
- Video model: %(model)s (ltx-2.5 only). Story model: Qwen3-VL-32B served by vLLM-Metal (vision mode only).
- Code: the 10 pipeline files and their 7 offline test files, listed explicitly (no tree walk).

What ships (component, counts, size):

%(component_lines)s

## 2. Target requirements

The package does not provide these; installing them needs network.

1. A local account `reubenpatterson` with home `/Users/reubenpatterson`, on macOS >= 26, Apple Silicon, >= 48 GiB RAM.
2. Homebrew at `/opt/homebrew`. Installing it also installs the Command Line Tools, which `/usr/bin/python3` needs on a fresh Mac.
3. `brew install ffmpeg python@3.12`. ffmpeg/ffprobe must be major version 9, and `/opt/homebrew/opt/python@3.12/bin/python3.12` must report 3.12.x. It is the vLLM venv's base interpreter.
4. `~/.zshenv` contains `export HF_HOME="/Users/reubenpatterson/hf_home"` and no `HF_HOME` line that mentions `/Volumes/`. The exact line to add is:

    export HF_HOME="/Users/reubenpatterson/hf_home"

5. A real Terminal session that can `sudo`, for the `system-python` phase.

## 3. Install

Run these in order, each on one line. A phase changes nothing unless it says --apply.

    %(inst)s --phase preflight
    sudo %(inst)s --phase system-python --apply
    %(inst)s --phase user --apply
    %(inst)s --phase verify
    %(inst)s --phase accept --gpu

The system-python phase needs a real Terminal, because sudo asks for a password.

Optional, all four acceptance geometries (portrait, wide, square, no seed):

    %(inst)s --phase accept --gpu-all

After the drive is ejected, run acceptance from the receipts copy:

    /usr/bin/python3 /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/deploy-receipts/%(package_id)s/scripts/deploy/install_pkg.py --phase accept --gpu

## 4. Running the pipeline

Start the story server and wait until it answers:

    cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
    bin/story-server vision
    until curl -sf http://127.0.0.1:8177/v1/models > /dev/null; do sleep 15; done

A plain run:

    %(py)s bin/ltx-movie "%(narrative)s" --story-id my-first-story --panels 4 --model %(model)s --story-server-stop-after-story

A run seeded from an image:

    %(py)s bin/ltx-movie "%(narrative)s" --story-id my-seeded-story --panels 4 --seed-image generated/hw_gate_seeds/portrait.png --model %(model)s --story-server-stop-after-story

## 5. Warnings

- The code's `--model` default for ltx-movie is `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8`, an ltx-2.3 model that is NOT shipped. Always pass `--model %(model)s`.
- `--seed-image` takes an image path. `--image-seed` is a different flag that takes an integer.
- Restart the story server (`bin/story-server vision`) before every run: `--story-server-stop-after-story` stops it after each run's story phase.
- Keep swap under 3 GiB before a run (check `sysctl -n vm.swapusage`). Swap drains at about 32 MB/min, and `purge` does not help.

## 6. Troubleshooting

- `~/.qwen-serve-guard/stand-down` makes Phase 1 exit 2 without probing port 8177 (a known open bug). Report it; do not delete it blindly.

## 7. Not included

- Text-mode story generation (MTPLX 27B) and the 27B fallback model.
- ltx-2.3 models and the Gemma-3-12B text encoder.
- Path re-pinning: the target must have the same account and home.
"""


def render_readme(ctx):
    pid = ctx.package_id
    lines = []
    for cid in COMPONENT_ORDER:
        row = ctx.comp_stats.get(cid) or {"slug": SLUGS[cid], "files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}
        lines.append("- %s %s: %d files, %d symlinks, %d dirs, %.2f GiB"
                     % (cid, row["slug"], row["files"], row["symlinks"], row["dirs"], row["bytes"] / 1024.0 ** 3))
    values = {
        "package_id": pid,
        "build_date": "%s-%s-%s" % (pid[-8:-4], pid[-4:-2], pid[-2:]),
        "head": ctx.git_record.get("head", ""),
        "branch": ctx.git_record.get("branch", ""),
        "component_lines": "\n".join(lines),
        "inst": "/usr/bin/python3 %s/%s/scripts/deploy/install_pkg.py" % (ctx.usb_root, pid),
        "py": README_PY,
        "model": LTX25_LITERAL,
        "narrative": README_NARRATIVE,
    }
    return README_TEMPLATE % values
```

- [ ] **Step 4: Run to verify they pass (both interpreters).** Expected: pytest `53 passed`; `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative control.** Temporarily delete ` --model %(model)s` from the "A plain run" template line → T90 FAILS. Revert.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: render the package README (explicit --model on every ltx-movie command)"
```

---

### Task 6: Stage order, R-PRE, post-copy stage and the build CLI (`--dry-run` / `--apply` / `--credential-report`)

**Files:**
- Modify: `scripts/deploy/build_pkg.py` (append at end; this adds the `# ---- CLI entry point ----` marker, `main()` and the `__main__` guard)
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces:
  - `root_file_contents(ctx) -> OrderedDict rel -> (bytes, mode)`, `write_root_files(ctx)`, `open_package_root(ctx)`;
  - `copy_entry(ctx, entry)`, `chmod_component_dirs(ctx, cid)`, `flush_partial(ctx)`, `copy_payload(ctx)`;
  - `build_stage(ctx)`, `abort_copy_stage(ctx, exc) -> 5`;
  - `finalize_entries(ctx)`, `check_a1_consistency(ctx)`, `manifest_doc(ctx)`, `write_manifest(ctx)`;
  - `fail_post_copy(ctx, step, exc) -> 3`, `finish_build(ctx) -> 0|3`;
  - `print_prebuild_report(ctx, results)`, `cmd_build(args)`, `main(argv=None) -> int`.
- Test helpers produced: `build_apply(fx, *extra)`, `build_dry(fx, *extra)`.

- [ ] **Step 1: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
def build_apply(fx, *extra):
    return run_main(bp.main, ["--apply", "--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))


def build_dry(fx, *extra):
    return run_main(bp.main, ["--dry-run", "--usb-root", fx.usb, "--package-id", fx.package_id] + list(extra))


ROOT_FILES = ["README.md", "manifests/source-host.json", "manifests/pip-freeze-framework-py313.txt",
              "manifests/pip-freeze-ltx2mlx-venv.txt", "manifests/pip-freeze-vllm-venv.txt",
              "manifests/source-git.json", "manifests/acceptance-baseline.json", "manifests/credential-scan.json",
              "scripts/deploy/build_pkg.py", "scripts/deploy/install_pkg.py", "scripts/deploy/credential_allowlist.json"]


class BuildE2ECase(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = Fixture(self)
        self.fx.build_sources()
        self.fx.configure_build_hooks()

    def fresh_fixture(self):
        fx = Fixture(self)
        fx.build_sources()
        fx.configure_build_hooks()
        return fx


class TestBuildCli(BuildE2ECase):
    def test_dry_run_report_format_and_writes_nothing(self):
        before = snapshot(self.fx.root)
        rc, out, err = build_dry(self.fx)
        self.assertEqual(rc, 0, out + err)
        lines = out.splitlines()
        self.assertEqual(lines[-1], "build_pkg: DRY RUN OK")
        comp = [line for line in lines if re.match(r"^[A-H][0-9] ", line)]
        self.assertEqual([line.split()[0] for line in comp], list(ORDER))
        self.assertTrue(re.match(r"^A1 workspace-code files=17 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
        self.assertEqual(comp[9], "F2 framework-symlinks files=0 symlinks=17 dirs=3 bytes=0 (0.00 GiB)")
        totals = [line for line in lines if line.startswith("TOTAL ")]
        self.assertEqual(len(totals), 1)
        self.assertTrue(re.match(r"^TOTAL files=\d+ symlinks=\d+ dirs=\d+ bytes=\d+ \(\d+\.\d\d GiB\)$", totals[0]))
        self.assertEqual(len([line for line in lines if line.startswith("SPACE required=")]), 1)
        self.assertEqual([line.split()[1] for line in lines if line.startswith("PASS ")], ["B%02d" % i for i in range(1, 20)])
        self.assertEqual(snapshot(self.fx.root), before)

    def test_default_mode_is_dry_run_and_failures_exit_4(self):
        bp.HOOKS["port_free"] = lambda port: False
        rc, out, err = run_main(bp.main, ["--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 4)
        self.assertIn("FAIL B09 ", out)
        self.assertEqual(out.splitlines()[-1], "build_pkg: DRY RUN FAILED (1 checks)")
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_apply_builds_a_complete_package(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        pkg = self.fx.pkg
        with open(pkg + "/MANIFEST.json") as fh:
            manifest = json.load(fh)
        entries = bp.read_entries(pkg + "/MANIFEST-ENTRIES.jsonl")
        self.assertEqual(manifest["schema_version"], 4)
        self.assertEqual(manifest["package_id"], self.fx.package_id)
        self.assertEqual(manifest["entries_file"], "MANIFEST-ENTRIES.jsonl")
        self.assertEqual(manifest["entries_sha256"], file_sha256(pkg + "/MANIFEST-ENTRIES.jsonl"))
        self.assertEqual(manifest["entries_count"], len(entries))
        self.assertEqual(list(manifest["components"]), list(ORDER))
        self.assertEqual(list(manifest["root_files"]), ROOT_FILES)
        for rel, digest in manifest["root_files"].items():
            self.assertEqual(file_sha256(pkg + "/" + rel), digest, rel)
        self.assertEqual(manifest["source_git_head"], HEAD_SHA)
        self.assertEqual(manifest["models"], {"video_model_path": self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8",
                                              "vision_model_snapshot": PINS["H4"][1],
                                              "vision_model_symlink": self.fx.home + "/mlx_models/qwen3-vl"})
        self.assertEqual(manifest["credential_scan"], {"l1": "clean", "l2_allowlisted": 0, "l3_values_loaded": 0, "l4": "clean"})
        self.assertIs(manifest["build"]["resumed"], False)
        self.assertEqual(manifest["totals"]["files"], len([e for e in entries if e["k"] == "f"]))
        self.assertFalse(os.path.lexists(pkg + "/BUILD-FAILED.json"))
        self.assertFalse(os.path.lexists(pkg + "/MANIFEST-ENTRIES.jsonl.partial"))
        self.assertEqual([n for n in os.listdir(pkg) if n.endswith(".tmp")], [])
        ctx = self.fx.ctx()
        ctx.git_record = {"head": HEAD_SHA, "branch": "ltx2-mlx-video-pipeline"}
        with open(pkg + "/README.md") as fh:
            self.assertEqual(fh.read(), bp.render_readme(ctx))
        with open(pkg + "/scripts/deploy/build_pkg.py", "rb") as a, open(os.path.join(DEPLOY_DIR, "build_pkg.py"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(stat.S_IMODE(os.lstat(pkg + "/scripts/deploy/build_pkg.py").st_mode), 0o755)
        with open(pkg + "/manifests/acceptance-baseline.json") as fh:
            self.assertEqual(json.load(fh)["gates"][6], {"id": "G7", "argv": ["tests/check_ltx2_mlx_no_forbidden_imports.py"], "rc": 0, "last_line": "RESULT: ok"})
        self.assertTrue(out.splitlines()[-1].startswith("build_pkg: BUILD OK: " + pkg))

    def test_T06_jsonl_on_disk(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl", "rb") as fh:
            raw_lines = fh.read().decode("utf-8").splitlines()
        shapes = set()
        for raw in raw_lines:
            obj = json.loads(raw)
            self.assertEqual(raw, json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
            shapes.add(tuple(obj))
        self.assertEqual(shapes, set([
            ("k", "c", "p", "t", "b", "m", "h", "mt"),
            ("k", "c", "p", "t", "m"),
            ("k", "c", "p", "t", "l"),
            ("k", "c", "t", "m"),
            ("k", "c", "t", "l"),
            ("k", "c", "t", "m", "s"),
            ("k", "c", "t", "l", "s")]))

    def test_T03_payload_symlinks_after_apply(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        repo, pin = PINS["H1"]
        link = self.fx.pkg + "/payload/H1-hf-zimage/snapshots/" + pin + "/config.json"
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "../../blobs/" + hashlib.sha1(repo.encode("utf-8")).hexdigest())
        self.assertEqual(os.readlink(self.fx.pkg + "/payload/B3-uv-cpython311/bin/python3"), "python3.11")

    def test_T07_fifo_fails_b03_and_refuses_apply(self):
        fifo = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/pipe"
        os.mkfifo(fifo)
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B03 ") and fifo in line])
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_RF3_missing_pack_file_refuses_apply_without_creating_root(self):
        os.unlink(self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8/transformer-distilled.safetensors")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertIn("missing=['transformer-distilled.safetensors']", out)
        self.assertIn("build_pkg: APPLY REFUSED (1 checks)", out)
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_credential_report_through_main(self):
        rc, out, err = run_main(bp.main, ["--credential-report", "--usb-root", self.fx.usb, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.splitlines()[-1].startswith("build_pkg: CREDENTIAL REPORT CLEAN"))

    def test_unexpected_pre_write_error_exits_1(self):
        def boom(ctx):
            raise RuntimeError("injected")
        with mock.patch.object(bp, "run_prebuild_checks", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 1)
        self.assertIn("RuntimeError: injected", err)
        self.assertFalse(os.path.lexists(self.fx.pkg))


class TestRPre(BuildE2ECase):
    def test_T20_failing_gate_refuses_before_any_write(self):
        self.fx.run.overrides[(self.fx.fw_py, "tests/test_ltx_story_images.py")] = (1, "boom\n")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4, out + err)
        self.assertIn("FAIL B15 ", out)
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_T21_no_outside_open_and_no_subprocess_after_first_payload_write(self):
        root = self.fx.pkg
        sources = set()
        violations = []
        real_enumerate = bp.enumerate_components
        real_open = open
        real_os_open = os.open
        real_run = bp.HOOKS["run"]

        def spy_enumerate(ctx):
            real_enumerate(ctx)
            sources.update(e["_src"] for e in ctx.entries if "_src" in e)

        def allowed(path):
            if isinstance(path, int):
                return True
            p = os.path.abspath(os.fsdecode(path))
            return p == root or p.startswith(root + "/") or p in sources

        def guarded_open(file, *args, **kwargs):
            if bp.CTX_STATE["payload_started"] and not allowed(file):
                violations.append(("open", file))
                raise AssertionError("R-PRE: open(%r) after the first payload write" % (file,))
            return real_open(file, *args, **kwargs)

        def guarded_os_open(path, *args, **kwargs):
            if bp.CTX_STATE["payload_started"] and not allowed(path):
                violations.append(("os.open", path))
                raise AssertionError("R-PRE: os.open(%r) after the first payload write" % (path,))
            return real_os_open(path, *args, **kwargs)

        def guarded_run(argv, timeout=120, env=None, cwd=None):
            if bp.CTX_STATE["payload_started"]:
                violations.append(("run", tuple(argv)))
                raise AssertionError("R-PRE: subprocess after the first payload write")
            return real_run(argv, timeout=timeout, env=env, cwd=cwd)

        bp.HOOKS["run"] = guarded_run
        with mock.patch.object(bp, "enumerate_components", spy_enumerate), \
                mock.patch("builtins.open", guarded_open), \
                mock.patch.object(os, "open", guarded_os_open):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(violations, [])
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(root + "/MANIFEST.json"))
        bp.CTX_STATE["payload_started"] = True
        with self.assertRaises(bp.RPreViolation):
            bp._run(["/usr/bin/true"])
        bp.CTX_STATE["payload_started"] = False

    def test_T22_post_copy_failure_writes_build_failed_and_no_manifest(self):
        def boom(ctx):
            raise RuntimeError("injected L4 failure")
        with mock.patch.object(bp, "l4_rescan", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["schema_version"], doc["package_id"], doc["failed_step"], doc["error_type"], doc["error"]),
                         (4, self.fx.package_id, "PC4", "RuntimeError", "injected L4 failure"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertTrue(os.path.isfile(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial"))

    def test_T23_root_files_exist_before_the_first_entry_is_listed(self):
        seen = {}

        def after_entry(index):
            if index == 0:
                seen["present"] = [rel for rel in ROOT_FILES if os.path.isfile(self.fx.pkg + "/" + rel)]
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(seen["present"], ROOT_FILES)


class TestCopyEngineE2E(BuildE2ECase):
    def test_T30_payload_matches_sources(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)
        pkg = self.fx.pkg
        ctx = self.fx.ctx()
        src_by_p = dict((e["p"], e["_src"]) for e in ctx.entries if "p" in e)
        entries = bp.read_entries(pkg + "/MANIFEST-ENTRIES.jsonl")
        for entry in entries:
            if "p" not in entry:
                continue
            dst = pkg + "/" + entry["p"]
            if entry["k"] == "f":
                src = src_by_p[entry["p"]]
                with open(src, "rb") as a, open(dst, "rb") as b:
                    self.assertEqual(a.read(), b.read(), entry["p"])
                self.assertEqual(entry["h"], file_sha256(src))
                sst, dstat = os.lstat(src), os.lstat(dst)
                self.assertEqual(stat.S_IMODE(dstat.st_mode), stat.S_IMODE(sst.st_mode), entry["p"])
                self.assertEqual(dstat.st_mtime_ns, sst.st_mtime_ns)
                self.assertEqual(dstat.st_mtime_ns, entry["mt"])
            elif entry["k"] == "d":
                self.assertEqual(stat.S_IMODE(os.lstat(dst).st_mode), int(entry["m"], 8), entry["p"])
        self.assertEqual(stat.S_IMODE(os.lstat(pkg + "/payload/B4-ltx25-mlx-q8").st_mode), 0o750)

    def test_T31_source_appended_mid_copy_aborts_with_exit_5(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"
        state = {"done": False}

        def after_chunk(src, nbytes):
            if src == target and not state["done"]:
                state["done"] = True
                with open(src, "ab") as fh:
                    fh.write(b"more\n")
        bp.HOOKS["after_chunk"] = after_chunk
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("source changed mid-copy: " + target, err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md"))

    def test_T32_source_changed_between_enumeration_and_copy(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"

        def after_entry(index):
            if index == 0:
                write_file(target, b"a different, longer README\n")
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("source changed since enumeration: " + target, err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))


class TestCredentialGatesE2E(BuildE2ECase):
    def test_T10_nested_token_file_refuses_apply(self):
        path = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/sub/token"
        write_file(path, b"not-a-secret-value-xyz\n")
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B12 ") and path in line])
        self.assertFalse(os.path.lexists(self.fx.pkg))

    def test_T13_known_secret_across_boundary_and_inside_chunk(self):
        secret = SECRET_CANARY.encode("ascii")
        for label, content in (("boundary", b"a" * 50 + secret + b"b" * 50), ("inside", b"a" * 10 + secret + b"b" * 10)):
            fx = self.fresh_fixture()
            write_file(fx.home + "/.cache/huggingface/token", secret + b"\n")
            src = fx.home + "/ltx-2-mlx/packages/ltx_core/leak.txt"
            write_file(src, content)
            with mock.patch.object(bp, "CHUNK_SIZE", 64):
                rc, out, err = build_apply(fx)
            self.assertEqual(rc, 5, label + out + err)
            self.assertIn(src, err)
            self.assertNotIn(SECRET_CANARY, out + err)
            self.assertFalse(os.path.lexists(fx.pkg + "/payload/B1-ltx2mlx-repo/packages/ltx_core/leak.txt"))
            self.assertFalse(os.path.lexists(fx.pkg + "/MANIFEST.json"))
            with open(fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "rb") as fh:
                partial = fh.read()
            self.assertNotIn(b"leak.txt", partial)
            self.assertNotIn(secret, partial)

    def test_RF1_long_jwt_like_token_in_unrecognized_file_is_caught_by_l3(self):
        token = "hf" + "_" + "eyJ0eXAi" + "." + "Q" * 800
        self.assertEqual(bp.l2_scan_bytes(token.encode("ascii")), [])
        write_file(self.fx.home + "/ltx-2-mlx/hf_cache/token", (token + "\n").encode("ascii"))
        src = self.fx.home + "/Library/Python/3.13/lib/python/site-packages/torch/hub_auth.cfg"
        write_file(src, b"[auth]\nvalue = " + token.encode("ascii") + b"\n")
        self.assertEqual(self.fx.ctx().l1_hits, [])
        with mock.patch.object(bp, "CHUNK_SIZE", 64):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn(src, err)
        self.assertNotIn(token, out + err)
        self.assertNotIn("Q" * 64, out + err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload/F3-user-site/lib/python/site-packages/torch/hub_auth.cfg"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))

    def test_RF1b_secret_in_a_root_file_aborts_before_payload(self):
        write_file(self.fx.home + "/.cache/huggingface/token", (SECRET_CANARY + "\n").encode("ascii"))
        self.fx.run.freeze_text = "pkg==1.0\n# " + SECRET_CANARY + "\n"
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("manifests/pip-freeze-framework-py313.txt", err)
        self.assertNotIn(SECRET_CANARY, out + err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/manifests/pip-freeze-framework-py313.txt"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/manifests/.pip-freeze-framework-py313.txt.tmp"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/payload"))
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))

    def test_T15_l4_catches_a_pattern_in_a_root_file(self):
        self.fx.run.freeze_text = "pkg==1.0\n# " + GITHUB_CANARY + "\n"
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["failed_step"], doc["error_type"], doc["schema_version"]), ("PC4", "CredentialLeak", 4))
        self.assertIn("manifests/pip-freeze-framework-py313.txt", doc["error"])
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertNotIn(GITHUB_CANARY, out + err + json.dumps(doc))

    def test_l4_rejects_a_ds_store_dropped_into_the_package(self):
        def after_entry(index):
            if index == 0:
                write_file(self.fx.pkg + "/payload/.DS_Store", b"finder")
        bp.HOOKS["after_entry"] = after_entry
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3, out + err)
        with open(self.fx.pkg + "/BUILD-FAILED.json") as fh:
            self.assertIn("DS_Store", json.load(fh)["error"])
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k "TestBuildCli or TestRPre or E2E"`
Expected: FAIL with `AttributeError: module 'build_pkg' has no attribute 'main'`.

- [ ] **Step 3: Write the implementation** — append to the end of `scripts/deploy/build_pkg.py`:

```python


# ---------------------------------------------------------------------------
# Root files, copy stage, post-copy stage (spec 9, 11)
# ---------------------------------------------------------------------------
def root_file_contents(ctx):
    def as_json(obj):
        return (json.dumps(obj, indent=2) + "\n").encode("utf-8")
    files = collections.OrderedDict()
    files["README.md"] = (render_readme(ctx).encode("utf-8"), 0o644)
    files["manifests/source-host.json"] = (as_json(ctx.host), 0o644)
    for rel, argv in freeze_commands():
        files[rel] = (ctx.freezes.get(rel, "").encode("utf-8"), 0o644)
    files["manifests/source-git.json"] = (as_json(ctx.git_record), 0o644)
    files["manifests/acceptance-baseline.json"] = (as_json(ctx.baseline), 0o644)
    files["manifests/credential-scan.json"] = (as_json(credential_scan_doc(ctx)), 0o644)
    for name in DEPLOY_SCRIPT_FILES:
        files["scripts/deploy/" + name] = (ctx.script_bytes[name], 0o755 if name.endswith(".py") else 0o644)
    return files


def write_root_files(ctx):
    ctx.root_files = collections.OrderedDict()
    for rel, (data, mode) in root_file_contents(ctx).items():
        ctx.root_files[rel] = write_package_file(ctx, rel, data, mode)


def open_package_root(ctx):
    root = ctx.package_root
    if not ctx.resume:
        os.mkdir(root)
        return
    failed = root + "/BUILD-FAILED.json"
    if os.path.lexists(failed):
        os.unlink(failed)
    partial = root + "/MANIFEST-ENTRIES.jsonl.partial"
    if ctx.resume_rename:
        os.replace(root + "/MANIFEST-ENTRIES.jsonl", partial)
    if os.path.exists(partial):
        os.truncate(partial, ctx.resume_keep_bytes)
    if ctx.resume_prefix_len < len(ctx.entries):
        entry = ctx.entries[ctx.resume_prefix_len]
        if "p" in entry:
            dst = root + "/" + entry["p"]
            if os.path.lexists(dst) and not (os.path.isdir(dst) and not os.path.islink(dst)):
                os.unlink(dst)


def copy_entry(ctx, entry):
    dst = ctx.package_root + "/" + entry["p"]
    if entry["k"] == "f":
        entry["h"] = copy_regular_file(entry["_src"], dst, entry, ctx.secrets)
    elif entry["k"] == "l":
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.unlink(dst)
        os.symlink(entry["l"], dst)
    else:
        os.makedirs(dst, exist_ok=True)


def chmod_component_dirs(ctx, cid):
    for entry in ctx.entries:
        if entry["c"] == cid and entry["k"] == "d" and "p" in entry:
            os.chmod(ctx.package_root + "/" + entry["p"], int(entry["m"], 8))


def flush_partial(ctx):
    ctx.partial_fh.flush()
    os.fsync(ctx.partial_fh.fileno())


def copy_payload(ctx):
    ctx.partial_fh = open(ctx.package_root + "/MANIFEST-ENTRIES.jsonl.partial", "ab")
    last_index = {}
    for index, entry in enumerate(ctx.entries):
        last_index[entry["c"]] = index
    start = ctx.resume_prefix_len
    for cid in COMPONENT_ORDER:
        if cid in last_index and last_index[cid] < start:
            chmod_component_dirs(ctx, cid)
    since_sync = 0
    for index in range(start, len(ctx.entries)):
        entry = ctx.entries[index]
        if "p" in entry:
            CTX_STATE["payload_started"] = True
            copy_entry(ctx, entry)
        line = entry_line(entry).encode("utf-8")
        l3_check_bytes(ctx.secrets, line, "MANIFEST-ENTRIES.jsonl")
        ctx.partial_fh.write(line)
        since_sync += 1
        component_end = last_index[entry["c"]] == index
        if since_sync >= 512 or component_end:
            flush_partial(ctx)
            since_sync = 0
        if component_end:
            chmod_component_dirs(ctx, entry["c"])
        HOOKS["after_entry"](index)


def build_stage(ctx):
    """Stage steps 6-8. Any exception here is a copy-stage abort (exit 5)."""
    open_package_root(ctx)
    write_root_files(ctx)
    copy_payload(ctx)


def abort_copy_stage(ctx, exc):
    fh = ctx.partial_fh
    if fh is not None and not fh.closed:
        try:
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
        except OSError:
            pass
    print("build_pkg: COPY ABORTED (%s): %s" % (type(exc).__name__, exc), file=sys.stderr)
    print("build_pkg: no MANIFEST.json was written; fix the cause, then rerun with --apply --resume --package-id %s"
          % ctx.package_id, file=sys.stderr)
    return 5


def finalize_entries(ctx):
    flush_partial(ctx)
    ctx.partial_fh.close()
    os.replace(ctx.package_root + "/MANIFEST-ENTRIES.jsonl.partial", ctx.package_root + "/MANIFEST-ENTRIES.jsonl")
    fsync_dir(ctx.package_root)


def check_a1_consistency(ctx):
    records = {}
    records.update(ctx.git_record.get("pipeline_files", {}))
    records.update(ctx.git_record.get("test_files", {}))
    for entry in ctx.entries:
        if entry["c"] == "A1" and entry["k"] == "f":
            record = records.get(entry["_rel"])
            if record is None or record["sha256"] != entry.get("h"):
                raise ValueError("PC3: A1 file %s was copied with a sha256 that differs from the provenance record"
                                 % entry["_rel"])


def manifest_doc(ctx):
    stats = component_stats(ctx.entries)
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": ctx.package_id,
        "created_at": iso_now(),
        "entries_file": "MANIFEST-ENTRIES.jsonl",
        "entries_sha256": ctx.entries_sha256,
        "entries_count": len(ctx.entries),
        "totals": stats_totals(stats),
        "components": stats,
        "root_files": ctx.root_files,
        "source_git_head": ctx.git_record.get("head", ""),
        "models": {"video_model_path": ltx25_model_path(), "vision_model_snapshot": HF_PINS["H4"][1],
                   "vision_model_symlink": home() + "/mlx_models/qwen3-vl"},
        "credential_scan": {"l1": "clean", "l2_allowlisted": len(ctx.l2_allowed),
                            "l3_values_loaded": len(ctx.secrets), "l4": "clean"},
        "build": {"started_at": ctx.started_at, "finished_at": iso_now(), "resumed": ctx.resume},
    }


def write_manifest(ctx):
    data = (json.dumps(manifest_doc(ctx), indent=2) + "\n").encode("utf-8")
    write_package_file(ctx, "MANIFEST.json", data, 0o644)


def fail_post_copy(ctx, step, exc):
    error = str(exc)
    doc = {"schema_version": SCHEMA_VERSION, "package_id": ctx.package_id, "failed_step": step,
           "error_type": type(exc).__name__, "error": error, "created_at": iso_now()}
    if has_secret(ctx, error):
        doc["error"] = "error text withheld: it contained secret material"
    data = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    manifest = ctx.package_root + "/MANIFEST.json"
    if os.path.lexists(manifest):
        os.unlink(manifest)
    try:
        write_package_file(ctx, "BUILD-FAILED.json", data, 0o644)
    except Exception as write_exc:
        print(safe_line(ctx, "build_pkg: could not write BUILD-FAILED.json: %s" % write_exc,
                        "build_pkg: could not write BUILD-FAILED.json (%s): (error text withheld: it contained secret material)"
                        % type(write_exc).__name__), file=sys.stderr)
    print(safe_line(ctx, "build_pkg: POST-COPY FAILURE at %s (%s): %s" % (step, doc["error_type"], error),
                    "build_pkg: POST-COPY FAILURE at %s (%s): (error text withheld: it contained secret material)"
                    % (step, doc["error_type"])), file=sys.stderr)
    print("build_pkg: BUILD-FAILED.json written; no MANIFEST.json. Fix the cause, then rerun with --apply --resume --package-id %s"
          % ctx.package_id, file=sys.stderr)
    return 3


def finish_build(ctx):
    step = "PC1"
    try:
        finalize_entries(ctx)
        step = "PC2"
        ctx.entries_sha256 = sha256_file(ctx.package_root + "/MANIFEST-ENTRIES.jsonl")
        step = "PC3"
        check_a1_consistency(ctx)
        step = "PC4"
        l4_rescan(ctx)
        step = "PC5"
        write_manifest(ctx)
    except Exception as exc:
        return fail_post_copy(ctx, step, exc)
    total = sum(e["b"] for e in ctx.entries if e["k"] == "f")
    print("build_pkg: BUILD OK: %s (%d entries, %d bytes)" % (ctx.package_root, len(ctx.entries), total))
    return 0


def print_prebuild_report(ctx, results):
    gib = 1024.0 ** 3
    for cid in COMPONENT_ORDER:
        row = ctx.comp_stats[cid]
        print("%s %s files=%d symlinks=%d dirs=%d bytes=%d (%.2f GiB)"
              % (cid, row["slug"], row["files"], row["symlinks"], row["dirs"], row["bytes"], row["bytes"] / gib))
    totals = stats_totals(ctx.comp_stats)
    print("TOTAL files=%d symlinks=%d dirs=%d bytes=%d (%.2f GiB)"
          % (totals["files"], totals["symlinks"], totals["dirs"], totals["bytes"], totals["bytes"] / gib))
    print("SPACE required=%d (%.2f GiB) free=%d (%.2f GiB)"
          % (ctx.required_bytes, ctx.required_bytes / gib, ctx.free_bytes, ctx.free_bytes / gib))
    for result in results:
        print(format_result(result))


def cmd_build(args):
    ctx = BuildCtx(args)
    try:
        ctx.started_at = iso_now()
        ctx.secrets, ctx.l3_sources, ctx.l3_errors = load_known_secrets()
        enumerate_components(ctx)
        results = run_prebuild_checks(ctx)
    except Exception:
        traceback.print_exc()
        print("build_pkg: UNEXPECTED ERROR before any write", file=sys.stderr)
        return 1
    print_prebuild_report(ctx, results)
    fatal = [r for r in results if r.fatal and not r.ok]
    if not ctx.apply:
        if fatal:
            print("build_pkg: DRY RUN FAILED (%d checks)" % len(fatal))
            return 4
        print("build_pkg: DRY RUN OK")
        return 0
    if fatal:
        print("build_pkg: APPLY REFUSED (%d checks); the package root was not created" % len(fatal))
        return 4
    try:
        build_stage(ctx)
    except Exception as exc:
        return abort_copy_stage(ctx, exc)
    return finish_build(ctx)


# ---- CLI entry point ----


def main(argv=None):
    args = parse_args(argv)
    CTX_STATE["payload_started"] = False
    try:
        if args.credential_report:
            return cmd_credential_report(args)
        return cmd_build(args)
    finally:
        CTX_STATE["payload_started"] = False


if __name__ == "__main__":
    sys.exit(main())
```

Implementer notes (anchors; do not reformat):
- `    copy_payload(ctx)` in `build_stage` is anchor M4b. It must be the only line in the file that equals `    copy_payload(ctx)` followed by a newline.
- `        l4_rescan(ctx)` in `finish_build` is the only occurrence of `    l4_rescan(ctx)` (anchor M3).
- `return finish_build(ctx)` is spec §9 step 9.
- In `test_T13_…`, `test_RF1_…`, `test_T31_…` and `test_T32_…` the error text is on **stderr**, because `abort_copy_stage` prints there.

- [ ] **Step 4: Run to verify they pass (both interpreters).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py; echo rc=$?`
Expected: `75 passed`, rc=0.

Run: `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (revert after each).**
  - (a) M4: delete `    results.append(check_offline_gates(ctx))` and add `    check_offline_gates(ctx)` after `    copy_payload(ctx)` → T20 FAILS (exit 5, root exists).
  - (b) M3: replace `        l4_rescan(ctx)` with `        pass` → T15 FAILS.
  - (c) M6: `    if before_key != after_key:` → `    if False:` → T31 FAILS (message is "copied size differs").

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: build stage order, R-PRE, post-copy stage and build CLI (--dry-run/--apply/--credential-report)"
```

---

### Task 7: `--resume` end-to-end and `--verify-only`

**Files:**
- Modify: `scripts/deploy/build_pkg.py`:
  - insert the verify block immediately **above** the line `# ---- CLI entry point ----`;
  - make one edit in `main()`.
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes:
  - resume: `analyze_resume`, `check_b07` (Task 4) and `open_package_root`, `copy_payload` (Task 6), which already honour `ctx.resume_*`;
  - `scan_package`, `load_allowlist`, `list_tree` (Task 3).
- Produces: `verify_package(root) -> (failures [(reason, path)], nfiles)` and `cmd_verify_only(args) -> 0|1`.
- Test helper produced: `build_verify(fx, package_id=None)`.

The resume tests below exercise code that already exists, so they are expected to **pass on first run**. Their red step is a negative control: a deliberate mutation that must turn them red. The verify-only tests are ordinary red/green.

- [ ] **Step 1: Write the tests** (insert above `if __name__ == "__main__":`):

```python
def build_verify(fx, package_id=None):
    return run_main(bp.main, ["--verify-only", "--usb-root", fx.usb, "--package-id", package_id or fx.package_id])


class TestResume(BuildE2ECase):
    def interrupt_at(self, k):
        def after_entry(index):
            if index == k:
                raise RuntimeError("injected interrupt at entry %d" % k)
        bp.HOOKS["after_entry"] = after_entry
        result = build_apply(self.fx)
        bp.HOOKS["after_entry"] = lambda index: None
        return result

    def reference(self):
        rc, out, err = run_main(bp.main, ["--apply", "--usb-root", self.fx.usb2, "--package-id", self.fx.package_id])
        self.assertEqual(rc, 0, out + err)
        return self.fx.usb2 + "/" + self.fx.package_id

    def assert_identical(self, ref):
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl", "rb") as a, open(ref + "/MANIFEST-ENTRIES.jsonl", "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(payload_snapshot(self.fx.pkg), payload_snapshot(ref))

    def partial_lines(self):
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "rb") as fh:
            return fh.read().split(b"\n")[:-1]

    def test_T40_interrupt_then_resume_is_byte_identical(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5, out + err)
        self.assertIn("injected interrupt at entry 30", err)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/MANIFEST.json"))
        self.assertEqual(len(self.partial_lines()), 31)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 31 of ", out)
        with open(self.fx.pkg + "/MANIFEST.json") as fh:
            self.assertIs(json.load(fh)["build"]["resumed"], True)
        self.assert_identical(self.reference())

    def test_T41_torn_final_line_is_truncated(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl.partial", "ab") as fh:
            fh.write(b'{"k":"f","c":"B')
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 31 of ", out)
        self.assert_identical(self.reference())

    def test_T42_listed_source_changed_fails_b07(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        readme = self.fx.home + "/ltx-2-mlx/README.md"
        write_file(readme, b"changed after the interrupted build\n")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4, out + err)
        self.assertIn("FAIL B07 source changed since the interrupted build: " + readme, out)

    def test_T43_corrupted_listed_payload_is_recopied(self):
        rc, out, err = self.interrupt_at(30)
        self.assertEqual(rc, 5)
        victim = self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md"
        with open(victim, "r+b") as fh:
            fh.write(b"L")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 25 of ", out)
        self.assert_identical(self.reference())

    def test_T44_resume_with_manifest_present_fails_b07(self):
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4)
        self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL B07 ") and "MANIFEST.json" in line])

    def test_RF2_resume_after_mid_copy_abort_completes_and_verifies(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"
        state = {"done": False}

        def after_chunk(src, nbytes):
            if src == target and not state["done"]:
                state["done"] = True
                with open(src, "ab") as fh:
                    fh.write(b"appended while copying\n")
        bp.HOOKS["after_chunk"] = after_chunk
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 5)
        self.assertEqual([l for l in self.partial_lines() if b"B1-ltx2mlx-repo/README.md" in l], [])
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 25 of ", out)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
        with open(self.fx.pkg + "/payload/B1-ltx2mlx-repo/README.md", "rb") as fh:
            self.assertTrue(fh.read().endswith(b"appended while copying\n"))

    def test_RF4_resume_after_post_copy_failure(self):
        def boom(ctx):
            raise RuntimeError("injected L4 failure")
        with mock.patch.object(bp, "l4_rescan", boom):
            rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 3)
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        entries = bp.read_entries(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl")
        self.assertIn("PASS B07 resume prefix: %d of %d entries verified" % (len(entries), len(entries)), out)
        self.assertFalse(os.path.lexists(self.fx.pkg + "/BUILD-FAILED.json"))
        self.assertTrue(os.path.isfile(self.fx.pkg + "/MANIFEST.json"))
        self.assertEqual(build_verify(self.fx)[0], 0)
        self.assert_identical(self.reference())

    def test_RF4b_resume_without_package_root_refuses(self):
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 4)
        self.assertIn("--resume given but %s does not exist" % self.fx.pkg, out)
        self.assertFalse(os.path.lexists(self.fx.pkg))


class TestVerifyOnly(BuildE2ECase):
    def setUp(self):
        BuildE2ECase.setUp(self)
        rc, out, err = build_apply(self.fx)
        self.assertEqual(rc, 0, out + err)

    def test_T50_clean_package_verifies_and_nothing_is_written(self):
        before = snapshot(self.fx.usb)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
        nfiles = len([e for e in bp.read_entries(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl") if e["k"] == "f" and "p" in e])
        self.assertEqual(out.splitlines()[-1], "build_pkg: VERIFY ok: %d files re-hashed" % nfiles)
        self.assertEqual(snapshot(self.fx.usb), before)

    def test_T50_each_corruption_fails(self):
        repo, pin = PINS["H1"]

        def flip(path):
            with open(path, "r+b") as fh:
                first = fh.read(1)
                fh.seek(0)
                fh.write(b"L" if first != b"L" else b"M")

        def truncate(path):
            os.truncate(path, 0)

        def relink(path):
            os.unlink(path)
            os.symlink("../../blobs/other", path)

        def append(path, data):
            with open(path, "ab") as fh:
                fh.write(data)

        cases = [
            ("flipped byte", lambda r: flip(r + "/payload/B1-ltx2mlx-repo/README.md"), "hash mismatch"),
            ("truncated", lambda r: truncate(r + "/payload/B1-ltx2mlx-repo/README.md"), "size mismatch"),
            ("missing", lambda r: os.unlink(r + "/payload/A2-hw-gate-seeds/square.png"), "missing"),
            ("extra", lambda r: write_file(r + "/payload/B1-ltx2mlx-repo/extra.txt", b"extra"), "extra"),
            ("entries edited", lambda r: append(r + "/MANIFEST-ENTRIES.jsonl", b"\n"), "entries sha256 mismatch"),
            ("root file edited", lambda r: append(r + "/README.md", b"edited\n"), "root file hash mismatch"),
            ("build failed marker", lambda r: write_file(r + "/BUILD-FAILED.json", b"{}"), "build failed marker present"),
            ("symlink changed", lambda r: relink(r + "/payload/H1-hf-zimage/snapshots/" + pin + "/config.json"), "symlink mismatch"),
            ("ds_store", lambda r: write_file(r + "/payload/.DS_Store", b"ds"), "credential scan"),
            ("manifest missing", lambda r: os.unlink(r + "/MANIFEST.json"), "manifest missing or unreadable"),
        ]
        for index, (label, mutate, reason) in enumerate(cases):
            package_id = "ltx-chain-deploy-202610%02d" % index
            copy = self.fx.usb + "/" + package_id
            shutil.copytree(self.fx.pkg, copy, symlinks=True)
            mutate(copy)
            before = snapshot(copy)
            rc, out, err = build_verify(self.fx, package_id)
            self.assertEqual(rc, 1, label + out + err)
            self.assertTrue([line for line in out.splitlines() if line.startswith("FAIL VERIFY " + reason + ": ")], label + out)
            self.assertEqual(snapshot(copy), before, label)
```

- [ ] **Step 2: Run them.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k "TestResume or TestVerifyOnly"`
Expected:
- TestResume passes, **except** `test_RF2_…` and `test_RF4_…`, which fail at their `build_verify` call. Before this task, `--verify-only` falls through to a dry run, and the dry run exits 4 because the root exists.
- Both TestVerifyOnly tests FAIL for the same reason.

- [ ] **Step 3a: Insert the verify block** immediately above the line `# ---- CLI entry point ----` in `scripts/deploy/build_pkg.py`:

```python
# ---------------------------------------------------------------------------
# --verify-only (spec 11.4): re-verify a finished package; writes nothing
# ---------------------------------------------------------------------------
def verify_package(root):
    failures = []
    manifest_path = root + "/MANIFEST.json"
    try:
        with open(manifest_path, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return [("manifest missing or unreadable", manifest_path)], 0
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return [("manifest is not schema_version %d" % SCHEMA_VERSION, manifest_path)], 0
    if os.path.lexists(root + "/BUILD-FAILED.json"):
        failures.append(("build failed marker present", root + "/BUILD-FAILED.json"))
    entries_path = root + "/" + manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl")
    try:
        entries_sha = sha256_file(entries_path, nocache=True)
        entries = read_entries(entries_path)
    except (OSError, ValueError):
        failures.append(("entries file unreadable", entries_path))
        return failures, 0
    if entries_sha != manifest.get("entries_sha256"):
        failures.append(("entries sha256 mismatch", entries_path))
    root_files = manifest.get("root_files", {})
    for rel in sorted(root_files):
        path = root + "/" + rel
        try:
            got = sha256_file(path, nocache=True)
        except OSError:
            got = None
        if got != root_files[rel]:
            failures.append(("root file hash mismatch", path))
    listed = set()
    nfiles = 0
    for entry in entries:
        if "p" not in entry:
            continue
        path = root + "/" + entry["p"]
        listed.add(entry["p"])
        try:
            st = os.lstat(path)
        except OSError:
            failures.append(("missing", path))
            continue
        if entry["k"] == "f":
            if not stat.S_ISREG(st.st_mode):
                failures.append(("not a regular file", path))
            elif st.st_size != entry["b"]:
                failures.append(("size mismatch", path))
            else:
                nfiles += 1
                if sha256_file(path, nocache=True) != entry["h"]:
                    failures.append(("hash mismatch", path))
        elif entry["k"] == "l":
            if not stat.S_ISLNK(st.st_mode) or os.readlink(path) != entry["l"]:
                failures.append(("symlink mismatch", path))
        elif not stat.S_ISDIR(st.st_mode):
            failures.append(("dir missing", path))
    if os.path.isdir(root + "/payload"):
        for rel, st in list_tree(root + "/payload"):
            if not stat.S_ISDIR(st.st_mode) and ("payload/" + rel) not in listed:
                failures.append(("extra", root + "/payload/" + rel))
    allow_path = root + "/scripts/deploy/credential_allowlist.json"
    try:
        allow, _ = load_allowlist(allow_path)
    except (OSError, ValueError):
        failures.append(("allowlist unreadable", allow_path))
        allow = set()
    scan_failures, _ = scan_package(root, allow)
    for item in scan_failures:
        failures.append(("credential scan", item))
    return failures, nfiles


def cmd_verify_only(args):
    usb_root = os.path.abspath(args.usb_root if args.usb_root else USB_ROOT_DEFAULT)
    package_id = args.package_id if args.package_id else default_package_id()
    root = os.path.join(usb_root, package_id)
    failures, nfiles = verify_package(root)
    for reason, path in failures:
        print("FAIL VERIFY %s: %s" % (reason, path))
    if failures:
        print("build_pkg: VERIFY FAILED: %d problem(s) in %s" % (len(failures), root))
        return 1
    print("build_pkg: VERIFY ok: %d files re-hashed" % nfiles)
    return 0


```

- [ ] **Step 3b: Edit `main()`.** Replace:
```python
        if args.credential_report:
            return cmd_credential_report(args)
```
with:
```python
        if args.verify_only:
            return cmd_verify_only(args)
        if args.credential_report:
            return cmd_credential_report(args)
```

- [ ] **Step 4: Run the whole suite (both interpreters).** Expected: pytest `85 passed`; `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (revert after each).**
  - (a) In `analyze_resume`, change `if not payload_matches(root, line):` to `if False:` → T43 FAILS (prefix is 31, not 25).
  - (b) In `open_package_root`, delete the line `        os.truncate(partial, ctx.resume_keep_bytes)` → T41 FAILS.
  - (c) In `open_package_root`, delete the two `BUILD-FAILED.json` lines → RF4 FAILS.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/build_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: --verify-only and end-to-end --resume coverage"
```

---

### Task 8: install_pkg.py — phases, checks I01-I20, the `--apply` gate, per-file install, receipts, verify

**Files:**
- Create: `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/scripts/deploy/install_pkg.py`
- Modify: `tests/test_deploy_pkg.py`:
  - a header edit (the `ip` load line, shown in Step 1a);
  - new classes inserted above `if __name__ == "__main__":`.

**Interfaces:**
- Consumes (from `build_pkg`, loaded as `_bp`): `CheckResult`, `format_result`, `PENDING_PREFIX`, `sha256_file`, `read_entries`, `list_tree`, `load_allowlist`, `scan_package`, `last_line`, `run_offline_gates` (the last two in Task 9). It never uses `_bp.HOOKS`, `_bp.iso_now` or any `_bp` path function.
- Produces:
  - constants and `HOOKS` (a copy of `_bp.HOOKS` plus `spawn`, `killpg`);
  - `InstallError`, `InstallCtx(args)` (with `.package_id()`);
  - path functions `home`, `workspace`, `framework_py`, `ltx25_model_path`, `receipts_dir(pid)`, `default_package_root`, `iso_now`;
  - `check_i01` … `check_i20`, `CHECKS` (id → function), `PHASE_CHECKS` (phase → ids);
  - `target_matches_entry(target, entry) -> (bool, reason)`, `build_receipt_entries(ctx)`, `install_check_entries(ctx)`;
  - `phase_components(ctx)`, `print_plan(ctx)`, `gated_install(ctx, fatal_failures)`;
  - `install_file(src, entry)`, `install_symlink(entry)`, `install_entry(ctx, entry)`, `chmod_created_dirs(ctx, cid)`, `install_components(ctx, components) -> counts`, `write_receipts(ctx)`;
  - `apply_system_python(ctx)`, `apply_user(ctx)`, `verify_entry(entry)`, `phase_verify(ctx, fatal_failures)`;
  - `run_checks(ctx)`, `parse_args(argv)`, `main(argv=None)`.
- Test helpers produced: `ip`, `PW`, `FakeProc`, `InstallFixture` (methods `build_and_become_target`, `configure_install`, `spawn`, `install`, `install_all`, `eject_hf_home`).

- [ ] **Step 1a: Header edit in `tests/test_deploy_pkg.py`.** Replace the two lines
```python
bp = load_module("build_pkg", "build_pkg.py")
HOOKED_MODULES = [bp]
```
with
```python
bp = load_module("build_pkg", "build_pkg.py")
ip = load_module("install_pkg", "install_pkg.py")
HOOKED_MODULES = [bp, ip, ip._bp]
```

- [ ] **Step 1b: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
PW = collections.namedtuple("PW", "pw_dir")


class FakeProc(object):
    def __init__(self, pid, rc=0):
        self.pid = pid
        self.returncode = rc

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


class InstallFixture(Fixture):
    """Build a package from the fake source host, then turn the fake host into a fresh target."""

    def __init__(self, tc):
        Fixture.__init__(self, tc)
        self.euid = 501
        self.spawned = []
        self.killed = []
        self.lsof = self.root + "/usr/sbin/lsof"
        self.system_py = self.root + "/usr/bin/python3"

    def build_and_become_target(self):
        self.build_sources()
        self.configure_build_hooks()
        rc, out, err = run_main(bp.main, ["--apply", "--usb-root", self.usb, "--package-id", self.package_id])
        self.tc.assertEqual(rc, 0, out + err)
        os.rename(self.home, self.root + "/source-home")
        os.makedirs(self.home)
        os.rename(self.fw, self.root + "/source-framework")
        os.rename(self.ulb, self.root + "/source-usr-local-bin")
        self.configure_install()

    def configure_install(self):
        for path in (self.brew_bin, self.lsof, self.system_py):
            write_file(path, b"#!fake\n", 0o755)
        values = {"REQUIRED_HOME": self.home, "FRAMEWORK_ROOT": self.fw, "VOLUMES_ROOT": self.volumes,
                  "BREW_BIN": self.brew_bin, "BREW_PY312": self.brew_py312, "LSOF_PATH": self.lsof,
                  "SYSTEM_PY": self.system_py}
        for name, value in sorted(values.items()):
            patcher = mock.patch.object(ip, name, value)
            patcher.start()
            self.tc.addCleanup(patcher.stop)
        os.environ["HF_HOME"] = self.home + "/hf_home"

        def getpwnam(name):
            if name == "reubenpatterson":
                return PW(self.home)
            raise KeyError(name)
        ip.HOOKS.update({
            "run": self.run,
            "geteuid": lambda: self.euid,
            "getpwnam": getpwnam,
            "getuser": lambda: "reubenpatterson",
            "statvfs_free": lambda path: 10 ** 15,
            "port_free": lambda port: True,
            "which": lambda name: {"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe}.get(name),
            "now_utc": lambda: FIXED_NOW,
            "after_chunk": lambda src, nbytes: None,
            "http_ok": lambda url: True,
            "sleep": lambda seconds: None,
            "spawn": self.spawn,
            "killpg": lambda pid, sig: self.killed.append((pid, sig)),
        })

    def spawn(self, argv, cwd=None, env=None, stdout_path=None, new_session=False):
        self.spawned.append({"argv": list(argv), "cwd": cwd, "env": env, "stdout_path": stdout_path, "new_session": new_session})
        self.events.append(("spawn", tuple(argv)))
        if argv[1:2] == ["-c"]:
            write_file(argv[3], json.dumps({"phase4_max_pressure": 1, "phase4_swap_delta_gib": 0.0,
                                            "phase4_peak_used_gib": 30.0}).encode("utf-8"))
            return FakeProc(4243)
        story_dir = os.path.dirname(stdout_path)
        write_file(stdout_path, b"(residual pad 7 px, 1.00x of the measured 704x448 area)\n")
        write_file(story_dir + "/runs/r1/story_summary.json", json.dumps(
            {"completed_units": 2, "requested_units": 2, "units": [{"seconds": 59.2}, {"seconds": 58.0}]}).encode("utf-8"))
        for rel in ("movie.mp4", "images/panel_01.png", "clips/panel_01.mp4", "clips/panel_02.chainseed.png"):
            write_file(story_dir + "/" + rel, b"media")
        return FakeProc(4242)

    def install(self, phase, *extra, **kw):
        self.euid = kw.get("euid", 0 if phase == "system-python" else 501)
        argv = ["--phase", phase, "--package-root", kw.get("root", self.pkg)] + list(extra)
        return run_main(ip.main, argv)

    def install_all(self):
        rc, out, err = self.install("system-python", "--apply")
        self.tc.assertEqual(rc, 0, out + err)
        rc, out, err = self.install("user", "--apply")
        self.tc.assertEqual(rc, 0, out + err)

    def eject_hf_home(self):
        shutil.rmtree(self.usb + "/hf_home")


class InstallCase(DeployTestCase):
    def setUp(self):
        DeployTestCase.setUp(self)
        self.fx = InstallFixture(self)
        self.fx.build_and_become_target()

    def entries(self):
        return bp.read_entries(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl")


class TestInstallChecks(InstallCase):
    def check(self, check_id, phase="preflight", root=None):
        ctx = ip.InstallCtx(ip.parse_args(["--phase", phase, "--package-root", root or self.fx.pkg]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if check_id in ("I09", "I10", "I11"):
                ip.check_i06(ctx)
            result = ip.CHECKS[check_id](ctx)
        return result, out.getvalue(), ctx

    def test_T60_I01_python_version(self):
        self.assertTrue(self.check("I01")[0].ok)
        with mock.patch.object(ip, "MIN_PYTHON", (99, 0)):
            self.assertFalse(self.check("I01")[0].ok)

    def test_T61_I02_platform(self):
        self.assertTrue(self.check("I02")[0].ok)
        with mock.patch.object(ip.platform, "machine", return_value="x86_64"):
            self.assertFalse(self.check("I02")[0].ok)
        with mock.patch.object(ip.platform, "system", return_value="Linux"):
            self.assertFalse(self.check("I02")[0].ok)

    def test_T62_I03_memsize(self):
        result, out, ctx = self.check("I03")
        self.assertTrue(result.ok)
        self.assertEqual(ctx.memsize, 68719476736)
        self.fx.run.memsize = str(48 * 1024 ** 3)
        self.assertTrue(self.check("I03")[0].ok)
        self.fx.run.memsize = str(16 * 1024 ** 3)
        result = self.check("I03")[0]
        self.assertFalse(result.ok)
        self.assertTrue(result.fatal)
        self.assertIn("36.61 GiB", result.message)
        self.fx.run.memsize = "garbage"
        self.assertFalse(self.check("I03")[0].ok)

    def test_T63_I04_macos_major(self):
        self.assertTrue(self.check("I04")[0].ok)
        self.fx.run.overrides[("/usr/bin/sw_vers", "-productVersion")] = (0, "15.6.1\n")
        self.assertFalse(self.check("I04")[0].ok)

    def test_T64_I05_account(self):
        self.assertTrue(self.check("I05")[0].ok)
        ip.HOOKS["getuser"] = lambda: "someone"
        self.assertFalse(self.check("I05")[0].ok)
        self.assertTrue(self.check("I05", phase="system-python")[0].ok)
        ip.HOOKS["getuser"] = lambda: "reubenpatterson"
        os.environ["HOME"] = self.fx.home + "-other"
        self.assertFalse(self.check("I05")[0].ok)
        os.environ["HOME"] = self.fx.home

        def no_user(name):
            raise KeyError(name)
        ip.HOOKS["getpwnam"] = no_user
        self.assertFalse(self.check("I05")[0].ok)

    def test_T65_I06_package_integrity(self):
        result, out, ctx = self.check("I06")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(ctx.entries), len(self.entries()))
        write_file(self.fx.pkg + "/BUILD-FAILED.json", b"{}")
        self.assertFalse(self.check("I06")[0].ok)
        os.unlink(self.fx.pkg + "/BUILD-FAILED.json")
        with open(self.fx.pkg + "/README.md", "ab") as fh:
            fh.write(b"x")
        self.assertFalse(self.check("I06")[0].ok)
        os.rename(self.fx.pkg + "/payload", self.fx.pkg + "/payload-away")
        result = self.check("I06")[0]
        self.assertFalse(result.ok)
        self.assertIn("receipts root", result.message)

    def test_T65b_I06_verify_phase_accepts_a_receipts_root(self):
        os.rename(self.fx.pkg + "/payload", self.fx.pkg + "/payload-away")
        self.assertTrue(self.check("I06", phase="verify")[0].ok)
        with open(self.fx.pkg + "/MANIFEST-ENTRIES.jsonl", "ab") as fh:
            fh.write(b"\n")
        self.assertFalse(self.check("I06", phase="verify")[0].ok)

    def test_T66_I07_ds_store(self):
        self.assertTrue(self.check("I07")[0].ok)
        write_file(self.fx.pkg + "/payload/.DS_Store", b"ds")
        result = self.check("I07")[0]
        self.assertFalse(result.ok)
        self.assertIn('find "%s" -name .DS_Store -delete' % self.fx.pkg, result.message)

    def test_T67_I08_rescan(self):
        self.assertTrue(self.check("I08")[0].ok)
        write_file(self.fx.pkg + "/payload/F3-user-site/leak.txt", ("x " + GITHUB_CANARY).encode("ascii"))
        result = self.check("I08")[0]
        self.assertFalse(result.ok)
        self.assertNotIn(GITHUB_CANARY, result.message)

    def test_T68_I09_free_space(self):
        self.assertTrue(self.check("I09")[0].ok)
        ip.HOOKS["statvfs_free"] = lambda path: 1000
        self.assertFalse(self.check("I09")[0].ok)

    def test_T69_I10_collisions(self):
        self.assertTrue(self.check("I10")[0].ok)
        target = self.fx.home + "/ltx-2-mlx/README.md"
        write_file(target, b"something else\n")
        result, out, ctx = self.check("I10")
        self.assertFalse(result.ok)
        self.assertIn("COLLISION size differs: " + target, out)
        self.assertIn("COLLISIONS 1", out)

    def test_T70_I11_case_duplicates(self):
        ctx = ip.InstallCtx(ip.parse_args(["--phase", "preflight", "--package-root", self.fx.pkg]))
        ip.check_i06(ctx)
        self.assertTrue(ip.check_i11(ctx).ok)
        ctx.entries.append(dict(ctx.entries[-1], t=ctx.entries[-1]["t"].upper()))
        self.assertFalse(ip.check_i11(ctx).ok)

    def test_T71_I12_ffmpeg(self):
        self.assertTrue(self.check("I12")[0].ok)
        self.fx.run.overrides[(self.fx.ffmpeg, "-version")] = (0, "ffmpeg version n9.0 Copyright\n")
        self.assertTrue(self.check("I12")[0].ok)
        self.fx.run.overrides[(self.fx.ffmpeg, "-version")] = (0, "ffmpeg version 8.1 Copyright\n")
        self.assertFalse(self.check("I12")[0].ok)
        self.fx.run.overrides = {}
        ip.HOOKS["which"] = lambda name: None
        self.assertFalse(self.check("I12")[0].ok)

    def test_T72_I13_brew(self):
        self.assertTrue(self.check("I13")[0].ok)
        os.unlink(self.fx.brew_bin)
        self.assertFalse(self.check("I13")[0].ok)

    def test_T73_I14_brew_python312(self):
        self.assertTrue(self.check("I14")[0].ok)
        for text in ("Python 3.11.9\n", "Python 3.12.9\nextra line\n"):
            self.fx.run.overrides[(self.fx.brew_py312, "--version")] = (0, text)
            self.assertFalse(self.check("I14")[0].ok, text)

    def test_T74_I15_lsof_and_system_python(self):
        self.assertTrue(self.check("I15")[0].ok)
        os.unlink(self.fx.lsof)
        self.assertFalse(self.check("I15")[0].ok)

    def test_T75_I16_port(self):
        self.assertTrue(self.check("I16")[0].ok)
        ip.HOOKS["port_free"] = lambda port: False
        self.assertFalse(self.check("I16")[0].ok)

    def test_T76_I17_hf_home(self):
        self.assertTrue(self.check("I17")[0].ok)
        os.environ["HF_HOME"] = "/Volumes/Ollama/hf_home"
        self.assertFalse(self.check("I17")[0].ok)
        os.environ["HF_HOME"] = self.fx.home + "/hf_home"
        self.fx.run.zsh_hf_home = "/Volumes/Ollama/hf_home"
        self.assertFalse(self.check("I17")[0].ok)
        self.fx.run.zsh_hf_home = None
        write_file(self.fx.home + "/.zshenv", b"# HF cache used to be on /Volumes/Ollama\nexport PATH=/x\nexport HF_HOME=/Volumes/Ollama/hf_home\n")
        result = self.check("I17")[0]
        self.assertFalse(result.ok)
        self.assertIn("3", result.message)
        self.assertIn('export HF_HOME="/Users/reubenpatterson/hf_home"', result.message)
        write_file(self.fx.home + "/.zshenv", b"# HF cache used to be on /Volumes/Ollama\n")
        self.assertTrue(self.check("I17")[0].ok)

    def test_T77_I18_workspace_writable(self):
        self.assertTrue(self.check("I18")[0].ok)
        os.makedirs(self.fx.ws)
        os.chmod(self.fx.ws, 0o555)
        self.assertFalse(self.check("I18")[0].ok)

    def test_T78_I19_euid(self):
        self.fx.euid = 0
        self.assertTrue(self.check("I19", phase="system-python")[0].ok)
        self.assertFalse(self.check("I19", phase="user")[0].ok)
        self.fx.euid = 501
        result = self.check("I19", phase="system-python")[0]
        self.assertFalse(result.ok)
        self.assertIn("sudo", result.message)
        self.assertTrue(self.check("I19", phase="user")[0].ok)

    def test_T79_I20_framework_python(self):
        result = self.check("I20")[0]
        self.assertTrue(result.ok)
        self.assertTrue(bp.format_result(result).startswith("PENDING I20 "))
        self.assertIn("run --phase system-python next", result.message)
        self.fx.run.overrides[(self.fx.fw_py, "-c", "import sys;print(sys.version.split()[0])")] = (127, "no such file\n")
        self.assertFalse(self.check("I20", phase="user")[0].ok)
        os.makedirs(self.fx.fw + "/Versions/3.13")
        self.fx.run.overrides[(self.fx.fw_py, "-c", "import sys;print(sys.version.split()[0])")] = (0, "3.12.0\n")
        self.assertFalse(self.check("I20")[0].ok)

    def test_phase_check_lists_match_the_spec_table(self):
        self.assertEqual(ip.PHASE_CHECKS["system-python"], ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I19"))
        self.assertEqual(ip.PHASE_CHECKS["verify"], ("I01", "I05", "I06", "I19", "I20"))
        self.assertEqual(ip.PHASE_CHECKS["accept"], ("I01", "I03", "I05", "I06", "I12", "I14", "I17", "I19", "I20"))
        self.assertEqual(ip.PHASE_CHECKS["preflight"], tuple("I%02d" % i for i in range(1, 21)))
        self.assertEqual(ip.PHASE_CHECKS["user"], tuple("I%02d" % i for i in range(1, 21)))

    def test_usage_errors(self):
        for argv in (["--phase", "verify", "--apply"], ["--phase", "user", "--gpu"],
                     ["--phase", "accept", "--gpu", "--gpu-all"], ["--phase", "all"], []):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    ip.parse_args(argv)
            self.assertEqual(cm.exception.code, 2, argv)


class TestInstallApply(InstallCase):
    def test_T70_S_and_U_without_apply_change_nothing(self):
        before = snapshot(self.fx.root)
        rc, out, err = self.fx.install("system-python")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PLAN F1 copy=", out)
        rc, out, err = self.fx.install("user")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PLAN B4 copy=", out)
        rc, out, err = self.fx.install("preflight")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PENDING I20 ", out)
        self.assertEqual(snapshot(self.fx.root), before)

    def test_T71_low_memory_refuses_apply_and_writes_nothing(self):
        self.fx.run.memsize = str(16 * 1024 ** 3)
        before = snapshot(self.fx.root)
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 4, out + err)
        self.assertIn("FAIL I03 ", out)
        rc, out, err = self.fx.install("system-python", "--apply")
        self.assertEqual(rc, 4, out + err)
        self.assertEqual(snapshot(self.fx.root), before)

    def test_T72_identical_targets_skipped_and_every_collision_listed(self):
        self.fx.install_all()
        t_file = self.fx.home + "/ltx-2-mlx/README.md"
        t_link = self.fx.home + "/ltx-2-mlx/.venv/bin/python"
        st1 = os.lstat(t_file)
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 0, out + err)
        st2 = os.lstat(t_file)
        self.assertEqual((st1.st_ino, st1.st_mtime_ns), (st2.st_ino, st2.st_mtime_ns))
        with open(t_file, "r+b") as fh:
            fh.write(b"L")
        os.unlink(t_link)
        os.symlink("/somewhere/else", t_link)
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 4, out + err)
        self.assertIn("COLLISION content differs: " + t_file, out)
        self.assertIn("COLLISION symlink target differs: " + t_link, out)
        self.assertIn("COLLISIONS 2", out)

    def test_T73_interrupted_file_never_appears_under_its_final_name(self):
        rc, out, err = self.fx.install("system-python", "--apply")
        self.assertEqual(rc, 0, out + err)
        calls = {"n": 0}

        def after_chunk(src, nbytes):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("injected failure mid-file")
        ip.HOOKS["after_chunk"] = after_chunk
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 1, out + err)
        first = [e for e in self.entries() if e["c"] == "A1" and e["k"] == "f"][0]
        self.assertFalse(os.path.lexists(first["t"]))
        tmp = os.path.dirname(first["t"]) + "/." + os.path.basename(first["t"]) + ".ltxdeploy.tmp"
        self.assertTrue(os.path.lexists(tmp))
        ip.HOOKS["after_chunk"] = lambda src, nbytes: None
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(file_sha256(first["t"]), first["h"])
        self.assertFalse(os.path.lexists(tmp))

    def test_T74_installed_bytes_modes_mtimes_links_and_dirs(self):
        os.makedirs(self.fx.ws)
        os.chmod(self.fx.ws, 0o700)
        self.fx.install_all()
        for entry in self.entries():
            t = entry["t"]
            if entry["k"] == "f":
                st = os.lstat(t)
                self.assertEqual(file_sha256(t), entry["h"], t)
                self.assertEqual(stat.S_IMODE(st.st_mode), int(entry["m"], 8), t)
                self.assertEqual(st.st_mtime_ns, entry["mt"], t)
            elif entry["k"] == "l":
                self.assertEqual(os.readlink(t), entry["l"], t)
            else:
                self.assertTrue(os.path.isdir(t) and not os.path.islink(t), t)
        self.assertEqual(stat.S_IMODE(os.lstat(self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8").st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(os.lstat(self.fx.fw + "/Versions").st_mode), 0o775)
        self.assertEqual(stat.S_IMODE(os.lstat(self.fx.ws).st_mode), 0o700)

    def test_T75_corrupted_payload_byte_fails_the_file(self):
        first = [e for e in self.entries() if e["c"] == "A1" and e["k"] == "f"][0]
        with open(self.fx.pkg + "/" + first["p"], "r+b") as fh:
            fh.write(b"X")
        rc, out, err = self.fx.install("system-python", "--apply")
        self.assertEqual(rc, 0, out + err)
        rc, out, err = self.fx.install("user", "--apply")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("sha256 mismatch for " + first["t"], err)
        self.assertFalse(os.path.lexists(first["t"]))
        self.assertFalse(os.path.lexists(os.path.dirname(first["t"]) + "/." + os.path.basename(first["t"]) + ".ltxdeploy.tmp"))

    def test_T76_receipts_and_running_from_them(self):
        self.fx.install_all()
        receipts = self.fx.ws + "/generated/deploy-receipts/" + self.fx.package_id
        with open(self.fx.pkg + "/MANIFEST.json") as fh:
            manifest = json.load(fh)
        for rel in ["MANIFEST.json", "MANIFEST-ENTRIES.jsonl"] + list(manifest["root_files"]):
            self.assertEqual(file_sha256(receipts + "/" + rel), file_sha256(self.fx.pkg + "/" + rel), rel)
        shutil.rmtree(self.fx.usb)
        rc, out, err = self.fx.install("verify", root=receipts)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.splitlines()[-1].startswith("VERIFY OK "))
        for phase in ("preflight", "system-python", "user"):
            rc, out, err = self.fx.install(phase, root=receipts)
            self.assertEqual(rc, 4, phase + out + err)
            self.assertIn("FAIL I06 ", out)

    def test_T77_euid_rules(self):
        rc, out, err = self.fx.install("system-python", euid=501)
        self.assertEqual(rc, 4)
        self.assertIn("FAIL I19 ", out)
        rc, out, err = self.fx.install("system-python", euid=0)
        self.assertEqual(rc, 0, out + err)
        rc, out, err = self.fx.install("user", euid=0)
        self.assertEqual(rc, 4)
        self.assertIn("FAIL I19 ", out)

    def test_system_python_post_check(self):
        key = (self.fx.fw_py, "-s", "-c", "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])")
        self.fx.run.overrides[key] = (1, "ModuleNotFoundError: No module named 'psutil'\n")
        rc, out, err = self.fx.install("system-python", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("No module named 'psutil'", err)

    def test_verify_phase_reports_mismatches(self):
        self.fx.install_all()
        rc, out, err = self.fx.install("verify")
        self.assertEqual(rc, 0, out + err)
        target = self.fx.home + "/ltx-2-mlx/README.md"
        with open(target, "r+b") as fh:
            fh.write(b"L")
        os.chmod(self.fx.home + "/ltx-2-mlx/.venv/pyvenv.cfg", 0o600)
        rc, out, err = self.fx.install("verify")
        self.assertEqual(rc, 1)
        self.assertIn("MISMATCH content differs: " + target, out)
        self.assertIn("MISMATCH mode differs: " + self.fx.home + "/ltx-2-mlx/.venv/pyvenv.cfg", out)
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py`
Expected: collection ERROR `FileNotFoundError: …/scripts/deploy/install_pkg.py`.

- [ ] **Step 3: Create `scripts/deploy/install_pkg.py`** with exactly this content:

```python
#!/usr/bin/env python3
"""install_pkg.py -- install the ltx-chain deployment package on the target Mac.

Spec: docs/superpowers/specs/2026-09-25-ltx-chain-deploy-package-design.md (sections 12-13)
Plan: docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md

    /usr/bin/python3 <pkg>/scripts/deploy/install_pkg.py --phase {preflight,system-python,user,verify,accept}
        [--apply] [--package-root PATH] [--gpu | --gpu-all]

Runs under Apple's /usr/bin/python3 (3.9.6); stdlib only; Python 3.9 language
level. The shared helpers (entry I/O, hashing, L1/L2 scanning, CheckResult) are
loaded from build_pkg.py in this file's own directory (R8). This module keeps its
own HOOKS and constants; it never calls a build_pkg function that reads HOOKS.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time


def _load_build_pkg():
    spec = importlib.util.spec_from_file_location("build_pkg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_pkg.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bp = _load_build_pkg()
CheckResult = _bp.CheckResult

REQUIRED_USER = "reubenpatterson"
REQUIRED_HOME = "/Users/reubenpatterson"
FRAMEWORK_ROOT = "/Library/Frameworks/Python.framework"
VOLUMES_ROOT = "/Volumes"
BREW_BIN = "/opt/homebrew/bin/brew"
BREW_PY312 = "/opt/homebrew/opt/python@3.12/bin/python3.12"
LSOF_PATH = "/usr/sbin/lsof"
SYSTEM_PY = "/usr/bin/python3"
CHUNK_SIZE = 8 * 1024 * 1024
SCHEMA_VERSION = 4
MIN_PYTHON = (3, 9)
MIN_MEMSIZE_BYTES = 51539607552          # 48 GiB
INSTALL_HEADROOM_BYTES = 10 * 1024 ** 3
STORY_PORT = 8177

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_REFUSED = 4
EXIT_GPU_REFUSED = 5

PHASES = ("preflight", "system-python", "user", "verify", "accept")
SYSTEM_COMPONENTS = ("F1", "F2")
FFMPEG_RE = re.compile(r"^ffmpeg version n?(\d+)\.")
FFPROBE_RE = re.compile(r"^ffprobe version n?(\d+)\.")
PY312_RE = re.compile(r"^Python 3\.12\.\d+\s*$")
HF_HOME_LINE_RE = re.compile(r"^\s*(export\s+)?HF_HOME=")


def _real_spawn(argv, cwd=None, env=None, stdout_path=None, new_session=False):
    out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    try:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=new_session)
    finally:
        if stdout_path:
            out.close()


HOOKS = dict(_bp.HOOKS)
HOOKS["spawn"] = _real_spawn
HOOKS["killpg"] = os.killpg


class InstallError(Exception):
    """A runtime failure during --apply (exit 1)."""


def home():
    return os.path.expanduser("~")


def workspace():
    return home() + "/local_model_harness/qwen-agent-workspace"


def framework_py():
    return FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"


def ltx25_model_path():
    return home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def receipts_dir(package_id):
    return workspace() + "/generated/deploy-receipts/" + package_id


def default_package_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", HOOKS["now_utc"]())


class InstallCtx(object):
    def __init__(self, args):
        self.args = args
        self.phase = args.phase
        self.package_root = os.path.abspath(args.package_root) if args.package_root else default_package_root()
        self.is_receipts = not os.path.isdir(self.package_root + "/payload")
        self.manifest = None
        self.entries = []
        self.receipt_entries = []
        self.target_status = {}
        self.memsize = -1
        self.ffmpeg = None
        self.ffprobe = None

    def package_id(self):
        if self.manifest and self.manifest.get("package_id"):
            return self.manifest["package_id"]
        return os.path.basename(self.package_root)


# ---------------------------------------------------------------------------
# Checks I01-I20 (spec 12.3)
# ---------------------------------------------------------------------------
def _not_loaded(check_id):
    return CheckResult(check_id, False, "manifest entries not loaded (see I06)", True)


def check_i01(ctx):
    ok = sys.version_info >= MIN_PYTHON
    return CheckResult("I01", ok, "python %s (need >= %d.%d)" % (platform.python_version(), MIN_PYTHON[0], MIN_PYTHON[1]), True)


def check_i02(ctx):
    system, machine = platform.system(), platform.machine()
    return CheckResult("I02", system == "Darwin" and machine == "arm64", "%s %s (need Darwin arm64)" % (system, machine), True)


def check_i03(ctx):
    rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "hw.memsize"])
    memsize = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
    ctx.memsize = memsize
    message = ("hw.memsize=%d bytes, need >= %d (48 GiB): the measured peak was 36.61 GiB with the vision model "
               "at 0.70 memory utilization, so a 16 GiB Mac cannot run it" % (memsize, MIN_MEMSIZE_BYTES))
    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)


def check_i04(ctx):
    rc, out = HOOKS["run"](["/usr/bin/sw_vers", "-productVersion"])
    text = out.strip()
    found = re.match(r"^(\d+)", text)
    major = int(found.group(1)) if rc == 0 and found else -1
    return CheckResult("I04", major >= 26, "macOS %s (need major >= 26)" % text, True)


def check_i05(ctx):
    problems = []
    try:
        pw_dir = HOOKS["getpwnam"](REQUIRED_USER).pw_dir
    except KeyError:
        pw_dir = None
    if pw_dir != REQUIRED_HOME:
        problems.append("user %s has home %r, expected %s" % (REQUIRED_USER, pw_dir, REQUIRED_HOME))
    if ctx.phase != "system-python":
        user = HOOKS["getuser"]()
        if user != REQUIRED_USER:
            problems.append("running as %r, expected %s" % (user, REQUIRED_USER))
        if os.environ.get("HOME") != REQUIRED_HOME:
            problems.append("$HOME=%r, expected %s" % (os.environ.get("HOME"), REQUIRED_HOME))
    ok = not problems
    return CheckResult("I05", ok, "account %s with home %s" % (REQUIRED_USER, REQUIRED_HOME) if ok else "; ".join(problems), True)


def check_i06(ctx):
    root = ctx.package_root
    manifest_path = root + "/MANIFEST.json"
    try:
        with open(manifest_path, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult("I06", False, "cannot read %s: %s" % (manifest_path, exc), True)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return CheckResult("I06", False, "%s is not a schema_version %d manifest" % (manifest_path, SCHEMA_VERSION), True)
    ctx.manifest = manifest
    problems = []
    if os.path.lexists(root + "/BUILD-FAILED.json"):
        problems.append("BUILD-FAILED.json is present")
    entries_path = root + "/" + manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl")
    try:
        entries_sha = _bp.sha256_file(entries_path)
    except OSError:
        entries_sha = None
    if entries_sha != manifest.get("entries_sha256"):
        problems.append("sha256(%s) does not match entries_sha256" % entries_path)
    else:
        ctx.entries = _bp.read_entries(entries_path)
    root_files = manifest.get("root_files", {})
    for rel in sorted(root_files):
        try:
            got = _bp.sha256_file(root + "/" + rel)
        except OSError:
            got = None
        if got != root_files[rel]:
            problems.append("root file %s does not match its recorded sha256" % rel)
    if ctx.phase in ("preflight", "system-python", "user") and ctx.is_receipts:
        problems.append("%s has no payload/: it is a receipts root, from which only --phase verify and --phase accept run" % root)
    ok = not problems
    return CheckResult("I06", ok, "package %s: %d entries" % (manifest.get("package_id"), len(ctx.entries)) if ok else "; ".join(problems), True)


def check_i07(ctx):
    root = ctx.package_root
    if not os.path.isdir(root):
        return CheckResult("I07", False, "package root %s is missing" % root, True)
    found = [root + "/" + rel for rel, st in _bp.list_tree(root) if rel.rsplit("/", 1)[-1] == ".DS_Store"]
    ok = not found
    message = "no .DS_Store under the package" if ok else (
        "%d .DS_Store file(s): %s; remove them with: find \"%s\" -name .DS_Store -delete" % (len(found), ", ".join(found[:10]), root))
    return CheckResult("I07", ok, message, True)


def check_i08(ctx):
    root = ctx.package_root
    if not os.path.isdir(root):
        return CheckResult("I08", False, "package root %s is missing" % root, True)
    allow_path = root + "/scripts/deploy/credential_allowlist.json"
    try:
        allow, _ = _bp.load_allowlist(allow_path)
    except (OSError, ValueError) as exc:
        return CheckResult("I08", False, "cannot load %s: %s" % (allow_path, exc), True)
    failures, allowed = _bp.scan_package(root, allow)
    ok = not failures
    message = ("L1+L2 rescan clean (%d allowlisted hit(s))" % len(allowed)) if ok else (
        "%d finding(s): %s" % (len(failures), "; ".join(failures[:20])))
    return CheckResult("I08", ok, message, True)


def check_i09(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I09")
    need = sum(e["b"] for e in ctx.entries if e["k"] == "f" and not os.path.lexists(e["t"])) + INSTALL_HEADROOM_BYTES
    free = HOOKS["statvfs_free"](REQUIRED_HOME)
    return CheckResult("I09", free >= need, "free=%d need=%d (absent files + %d headroom) on %s" % (free, need, INSTALL_HEADROOM_BYTES, REQUIRED_HOME), True)


def target_matches_entry(target, entry):
    try:
        st = os.lstat(target)
    except OSError:
        return False, "missing"
    kind = entry["k"]
    if kind == "f":
        if not stat.S_ISREG(st.st_mode):
            return False, "not a regular file"
        if st.st_size != entry["b"]:
            return False, "size differs"
        try:
            actual = _bp.sha256_file(target)
        except OSError:
            return False, "unreadable"
        if actual != entry["h"]:
            return False, "content differs"
        return True, ""
    if kind == "l":
        if not stat.S_ISLNK(st.st_mode):
            return False, "not a symlink"
        if os.readlink(target) != entry["l"]:
            return False, "symlink target differs"
        return True, ""
    if not stat.S_ISDIR(st.st_mode):
        return False, "not a directory"
    return True, ""


def build_receipt_entries(ctx):
    root = ctx.package_root
    manifest = ctx.manifest
    dest = receipts_dir(ctx.package_id())
    items = [("MANIFEST.json", None), (manifest.get("entries_file", "MANIFEST-ENTRIES.jsonl"), manifest.get("entries_sha256"))]
    items.extend(sorted(manifest.get("root_files", {}).items()))
    out = []
    for rel, digest in items:
        src = root + "/" + rel
        try:
            st = os.lstat(src)
        except OSError:
            continue
        if digest is None:
            digest = _bp.sha256_file(src)
        out.append({"k": "f", "c": "RECEIPTS", "t": dest + "/" + rel, "b": st.st_size,
                    "m": "%04o" % stat.S_IMODE(st.st_mode), "h": digest, "mt": st.st_mtime_ns, "_src": src})
    return out


def install_check_entries(ctx):
    entries = list(ctx.entries)
    if ctx.phase == "user":
        ctx.receipt_entries = build_receipt_entries(ctx)
        entries.extend(ctx.receipt_entries)
    return entries


def check_i10(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I10")
    collisions = []
    for entry in install_check_entries(ctx):
        target = entry["t"]
        if not os.path.lexists(target):
            ctx.target_status[target] = "absent"
            continue
        same, reason = target_matches_entry(target, entry)
        if not same:
            collisions.append((target, reason))
        ctx.target_status[target] = "same" if same else reason
    for target, reason in collisions:
        print("COLLISION %s: %s" % (reason, target))
    if collisions:
        print("COLLISIONS %d" % len(collisions))
    ok = not collisions
    message = "every target is absent or identical" if ok else (
        "%d collision(s) listed above; the target Mac must be fresh (D11)" % len(collisions))
    return CheckResult("I10", ok, message, True)


def check_i11(ctx):
    if ctx.manifest is None or not ctx.entries:
        return _not_loaded("I11")
    seen = {}
    for entry in ctx.entries:
        seen.setdefault(entry["t"].lower(), []).append(entry["t"])
    dups = [values for values in seen.values() if len(values) > 1]
    ok = not dups
    return CheckResult("I11", ok, "no case-insensitive target duplicates" if ok else "; ".join(" | ".join(v) for v in dups[:20]), True)


def check_i12(ctx):
    problems = []
    for name, rx in (("ffmpeg", FFMPEG_RE), ("ffprobe", FFPROBE_RE)):
        path = HOOKS["which"](name)
        if not path:
            problems.append("%s not found on PATH" % name)
            continue
        setattr(ctx, name, path)
        rc, out = HOOKS["run"]([path, "-version"])
        lines = out.splitlines()
        first = lines[0] if lines else ""
        found = rx.match(first)
        if rc != 0 or not found or found.group(1) != "9":
            problems.append("%s: %r (need major version 9)" % (path, first))
    ok = not problems
    return CheckResult("I12", ok, "ffmpeg/ffprobe major version 9" if ok else "; ".join(problems), True)


def check_i13(ctx):
    ok = os.path.isfile(BREW_BIN) and os.access(BREW_BIN, os.X_OK)
    return CheckResult("I13", ok, "%s %s" % (BREW_BIN, "is executable" if ok else "is missing or not executable (install Homebrew)"), True)


def check_i14(ctx):
    rc, out = HOOKS["run"]([BREW_PY312, "--version"])
    ok = rc == 0 and PY312_RE.match(out) is not None
    return CheckResult("I14", ok, "%s --version -> %r (need Python 3.12.x; brew install python@3.12)" % (BREW_PY312, out.strip()), True)


def check_i15(ctx):
    missing = [p for p in (LSOF_PATH, SYSTEM_PY) if not (os.path.isfile(p) and os.access(p, os.X_OK))]
    return CheckResult("I15", not missing, "%s and %s are executable" % (LSOF_PATH, SYSTEM_PY) if not missing else "missing or not executable: %s" % ", ".join(missing), True)


def check_i16(ctx):
    ok = bool(HOOKS["port_free"](STORY_PORT))
    return CheckResult("I16", ok, "port %d is %s" % (STORY_PORT, "free" if ok else "in use"), True)


def zshenv_volume_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return [number for number, line in enumerate(lines, 1) if HF_HOME_LINE_RE.match(line) and "/Volumes/" in line]


def check_i17(ctx):
    want = home() + "/hf_home"
    problems = []
    env_value = os.environ.get("HF_HOME")
    if env_value != want:
        problems.append("process HF_HOME=%r, expected %r" % (env_value, want))
    rc, out = HOOKS["run"](["/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'])
    if rc != 0 or out != want:
        problems.append("zsh HF_HOME=%r, expected %r" % (out, want))
    bad = zshenv_volume_lines(home() + "/.zshenv")
    if bad:
        problems.append("~/.zshenv HF_HOME line(s) mentioning /Volumes/ at line(s) %s" % ", ".join(str(n) for n in bad))
    ok = not problems
    if ok:
        return CheckResult("I17", True, "HF_HOME=%s in the process and in zsh" % want, True)
    return CheckResult("I17", False, "; ".join(problems) + '. Add exactly this line to ~/.zshenv: export HF_HOME="/Users/reubenpatterson/hf_home" (this installer never edits dotfiles)', True)


def check_i18(ctx):
    ws = workspace()
    if os.path.lexists(ws):
        ok = os.path.isdir(ws) and os.access(ws, os.W_OK)
        return CheckResult("I18", ok, "%s %s" % (ws, "is a writable directory" if ok else "is not a writable directory"), True)
    ancestor = os.path.dirname(ws)
    while not os.path.lexists(ancestor):
        ancestor = os.path.dirname(ancestor)
    ok = os.path.isdir(ancestor) and os.access(ancestor, os.W_OK)
    return CheckResult("I18", ok, "%s absent; nearest ancestor %s %s" % (ws, ancestor, "is writable" if ok else "is not writable"), True)


def check_i19(ctx):
    euid = HOOKS["geteuid"]()
    if ctx.phase == "system-python":
        ok = euid == 0
        return CheckResult("I19", ok, "running as root" if ok else "euid=%d: --phase system-python must run as root; run it with sudo" % euid, True)
    ok = euid != 0
    return CheckResult("I19", ok, "euid=%d (--phase %s must not run as root)" % (euid, ctx.phase), True)


def check_i20(ctx):
    if ctx.phase == "preflight" and not os.path.isdir(FRAMEWORK_ROOT + "/Versions/3.13"):
        return CheckResult("I20", True, _bp.PENDING_PREFIX + "%s/Versions/3.13 is not installed yet; run --phase system-python next" % FRAMEWORK_ROOT, True)
    rc, out = HOOKS["run"]([framework_py(), "-c", "import sys;print(sys.version.split()[0])"])
    got = out.strip()
    return CheckResult("I20", rc == 0 and got == "3.13.0", "%s reports %r (need 3.13.0)" % (framework_py(), got), True)


CHECKS = {
    "I01": check_i01, "I02": check_i02, "I03": check_i03, "I04": check_i04, "I05": check_i05,
    "I06": check_i06, "I07": check_i07, "I08": check_i08, "I09": check_i09, "I10": check_i10,
    "I11": check_i11, "I12": check_i12, "I13": check_i13, "I14": check_i14, "I15": check_i15,
    "I16": check_i16, "I17": check_i17, "I18": check_i18, "I19": check_i19, "I20": check_i20,
}
PHASE_CHECKS = {
    "preflight": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I12", "I13", "I14", "I15", "I16", "I17", "I18", "I19", "I20"),
    "system-python": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I19"),
    "user": ("I01", "I02", "I03", "I04", "I05", "I06", "I07", "I08", "I09", "I10", "I11", "I12", "I13", "I14", "I15", "I16", "I17", "I18", "I19", "I20"),
    "verify": ("I01", "I05", "I06", "I19", "I20"),
    "accept": ("I01", "I03", "I05", "I06", "I12", "I14", "I17", "I19", "I20"),
}


def run_checks(ctx):
    results = [CHECKS[check_id](ctx) for check_id in PHASE_CHECKS[ctx.phase]]
    for result in results:
        print(_bp.format_result(result))
    return results


# ---------------------------------------------------------------------------
# Plan print, --apply gate, per-file install (spec 12.2, 12.4)
# ---------------------------------------------------------------------------
def phase_components(ctx):
    components = list((ctx.manifest or {}).get("components", {}))
    if ctx.phase == "system-python":
        return [c for c in components if c in SYSTEM_COMPONENTS]
    if ctx.phase == "user":
        return [c for c in components if c not in SYSTEM_COMPONENTS]
    return components


def print_plan(ctx):
    for cid in phase_components(ctx):
        copy = same = collisions = 0
        for entry in ctx.entries:
            if entry["c"] != cid:
                continue
            status = ctx.target_status.get(entry["t"], "absent")
            if status == "absent":
                copy += 1
            elif status == "same":
                same += 1
            else:
                collisions += 1
        print("PLAN %s copy=%d identical=%d collisions=%d" % (cid, copy, same, collisions))
    if ctx.phase == "user":
        print("PLAN receipts -> %s" % receipts_dir(ctx.package_id()))


def gated_install(ctx, fatal_failures):
    """preflight / system-python / user: dry-run by default; --apply refused on any fatal check."""
    args = ctx.args
    if not args.apply:
        print_plan(ctx)
        return EXIT_OK if not fatal_failures else EXIT_REFUSED
    if fatal_failures:  # refuse --apply
        print("install_pkg: --apply REFUSED: %d fatal check(s) failed; nothing was written" % len(fatal_failures))
        return EXIT_REFUSED
    try:
        if ctx.phase == "system-python":
            return apply_system_python(ctx)
        if ctx.phase == "user":
            return apply_user(ctx)
    except Exception as exc:
        print("install_pkg: ERROR during --apply (%s): %s" % (type(exc).__name__, exc), file=sys.stderr)
        print("install_pkg: files already installed stay in place; a rerun skips them as identical", file=sys.stderr)
        return EXIT_RUNTIME
    return EXIT_OK


def _write_all(fd, data):
    view = memoryview(data)
    offset = 0
    while offset < len(data):
        offset += os.write(fd, view[offset:])


def install_file(src, entry):
    target = entry["t"]
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    tmp = parent + "/." + os.path.basename(target) + ".ltxdeploy.tmp"
    hasher = hashlib.sha256()
    src_fd = os.open(src, os.O_RDONLY)
    try:
        dst_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            total = 0
            while True:
                chunk = os.read(src_fd, CHUNK_SIZE)
                if not chunk:
                    break
                _write_all(dst_fd, chunk)
                hasher.update(chunk)
                total += len(chunk)
                HOOKS["after_chunk"](src, total)
            os.fsync(dst_fd)
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)
    digest = hasher.hexdigest()
    if digest != entry["h"]:
        os.unlink(tmp)
        raise InstallError("sha256 mismatch for %s" % target)
    os.chmod(tmp, int(entry["m"], 8))
    os.utime(tmp, ns=(entry["mt"], entry["mt"]))
    os.replace(tmp, target)


def install_symlink(entry):
    target = entry["t"]
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    tmp = parent + "/." + os.path.basename(target) + ".ltxdeploy.tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(entry["l"], tmp)
    os.replace(tmp, target)


def install_entry(ctx, entry):
    target = entry["t"]
    if ctx.target_status.get(target) == "same":
        return False
    if os.path.lexists(target):
        same, reason = target_matches_entry(target, entry)
        if same:
            return False
        raise InstallError("%s changed after the checks ran (%s)" % (target, reason))
    if entry["k"] == "f":
        install_file(ctx.package_root + "/" + entry["p"], entry)
    elif entry["k"] == "l":
        install_symlink(entry)
    else:
        os.makedirs(target, exist_ok=True)
    return True


def chmod_created_dirs(ctx, component):
    for entry in ctx.entries:
        if entry["c"] == component and entry["k"] == "d" and ctx.target_status.get(entry["t"]) == "absent":
            if os.path.isdir(entry["t"]) and not os.path.islink(entry["t"]):
                os.chmod(entry["t"], int(entry["m"], 8))


def install_components(ctx, components):
    selected = [e for e in ctx.entries if e["c"] in components]
    last = {}
    for index, entry in enumerate(selected):
        last[entry["c"]] = index
    counts = {"files": 0, "symlinks": 0, "bytes": 0}
    for index, entry in enumerate(selected):
        install_entry(ctx, entry)
        if entry["k"] == "f":
            counts["files"] += 1
            counts["bytes"] += entry["b"]
        elif entry["k"] == "l":
            counts["symlinks"] += 1
        if last[entry["c"]] == index:
            chmod_created_dirs(ctx, entry["c"])
    return counts


def write_receipts(ctx):
    for entry in ctx.receipt_entries:
        if ctx.target_status.get(entry["t"]) == "same":
            continue
        install_file(entry["_src"], entry)


def apply_system_python(ctx):
    install_components(ctx, SYSTEM_COMPONENTS)
    rc, out = HOOKS["run"]([framework_py(), "-s", "-c", "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])"], timeout=300)
    lines = out.splitlines()
    first = lines[0].strip() if lines else ""
    if rc != 0 or first != "3.13.0":
        print("install_pkg: system-python post-check FAILED (rc=%d): %s" % (rc, out[-200:]), file=sys.stderr)
        return EXIT_RUNTIME
    print("install_pkg: system-python phase complete")
    return EXIT_OK


def apply_user(ctx):
    counts = install_components(ctx, phase_components(ctx))
    write_receipts(ctx)
    print("install_pkg: user phase complete: %d files, %d symlinks, %d bytes" % (counts["files"], counts["symlinks"], counts["bytes"]))
    return EXIT_OK


def verify_entry(entry):
    target = entry["t"]
    try:
        st = os.lstat(target)
    except OSError:
        return "missing"
    if entry["k"] == "f":
        if not stat.S_ISREG(st.st_mode):
            return "not a regular file"
        try:
            actual = _bp.sha256_file(target)
        except OSError:
            return "unreadable"
        if actual != entry["h"]:
            return "content differs"
        if stat.S_IMODE(st.st_mode) != int(entry["m"], 8):
            return "mode differs"
        return None
    if entry["k"] == "l":
        if not stat.S_ISLNK(st.st_mode):
            return "not a symlink"
        if os.readlink(target) != entry["l"]:
            return "symlink target differs"
        return None
    if not stat.S_ISDIR(st.st_mode):
        return "not a directory"
    return None


def phase_verify(ctx, fatal_failures):
    if fatal_failures:
        print("install_pkg: verify REFUSED: %d fatal check(s) failed" % len(fatal_failures))
        return EXIT_REFUSED
    counts = {"f": 0, "l": 0, "d": 0}
    mismatches = 0
    for entry in ctx.entries:
        counts[entry["k"]] += 1
        reason = verify_entry(entry)
        if reason:
            mismatches += 1
            print("MISMATCH %s: %s" % (reason, entry["t"]))
    if mismatches:
        print("install_pkg: verify FAILED: %d mismatch(es)" % mismatches)
        return EXIT_RUNTIME
    print("VERIFY OK %d files, %d symlinks, %d dirs" % (counts["f"], counts["l"], counts["d"]))
    return EXIT_OK


# ---- CLI entry point ----


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="install_pkg.py", description="Install the ltx-chain deployment package.")
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--package-root", default=None)
    gpu = parser.add_mutually_exclusive_group()
    gpu.add_argument("--gpu", action="store_true")
    gpu.add_argument("--gpu-all", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and args.phase not in ("system-python", "user"):
        parser.error("--apply is valid only with --phase system-python or --phase user")
    if (args.gpu or args.gpu_all) and args.phase != "accept":
        parser.error("--gpu/--gpu-all are valid only with --phase accept")
    return args


def main(argv=None):
    args = parse_args(argv)
    ctx = InstallCtx(args)
    results = run_checks(ctx)
    fatal_failures = [r for r in results if r.fatal and not r.ok]
    if args.phase == "verify":
        return phase_verify(ctx, fatal_failures)
    return gated_install(ctx, fatal_failures)


if __name__ == "__main__":
    sys.exit(main())
```

Implementer notes (anchors; exact text, once each):
- `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)` (M5)
- `    if digest != entry["h"]:` (M7, only in `install_file`)
- `            collisions.append((target, reason))` (M8)
- `    if not args.apply:` (M11)
- `    if fatal_failures:  # refuse --apply` (M12)
- `parse_args` must not contain the text `if not args.apply`.
- `install_pkg.py` must pass T16 (L2-clean) and T95 (3.9 grammar). Both tests iterate over every `.py` in `scripts/deploy`, so they now cover this file automatically.

- [ ] **Step 4: Run to verify they pass (both interpreters).** Expected: pytest `118 passed`; `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (revert after each).**
  - (a) M11 `    if not args.apply:` → `    if False:` → T70 FAILS.
  - (b) M12 → T71 FAILS.
  - (c) M5 → T71 FAILS.
  - (d) M7 → T75 FAILS.
  - (e) M8 → T72 FAILS.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/install_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: install_pkg phases, checks I01-I20, --apply gate, atomic installs, receipts, verify"
```

---

### Task 9: The accept phase (A0-A5, GPU refusals r1-r5, GPU runs with c1-c5)

**Files:**
- Modify: `scripts/deploy/install_pkg.py`:
  - insert the accept block immediately **above** `# ---- CLI entry point ----`;
  - make one edit in `main()`.
- Modify: `tests/test_deploy_pkg.py` (insert above `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: Task 8 (`InstallCtx`, `HOOKS`, `receipts_dir`, `iso_now`, `framework_py`, `workspace`, `ltx25_model_path`) and `_bp.run_offline_gates`, `_bp.last_line`.
- Produces:
  - constants `ACCEPT_NARR`, `GEOMETRIES`, `SCOPED_HF_VARS`, `REFUSAL_ENV_VARS`, `STORY_SERVER_USAGE`, `SWAP_REFUSE_MB`, `LTX_MOVIE_TIMEOUT`, `STORY_SERVER_UP_TIMEOUT`, `POLL_SECONDS`, `SAMPLER_SRC`;
  - `load_json(path)`, `accept_a1_metadata(ctx)`, `accept_a2_probes(ctx)`, `accept_a3_gates(ctx)`, `accept_a4_story_server(ctx)` (each returns `{"ok": bool, "problems": [...], ...}`);
  - `gpu_refusals(ctx) -> [str]`, `wait_for_story_server()`, `accept_env()`;
  - `ffprobe_stream(ctx, path, select, entries, count=False)`, `framemd5(ctx, path, vf)`;
  - `evaluate_run(ctx, story_dir, rc, W, H, SW, SH) -> {"c1".."c5", "record"}`;
  - `gpu_run(ctx, label, seed, W, H, SW, SH) -> dict`, `write_accept_record(ctx, record, stamp, verdict)`, `report_step(step_id, result)`, `phase_accept(ctx, fatal_failures)`.

- [ ] **Step 1: Write the failing tests** (insert above `if __name__ == "__main__":`):

```python
NARR = "An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward the lighthouse door."


class TestAccept(InstallCase):
    def setUp(self):
        InstallCase.setUp(self)
        self.fx.install_all()
        self.fx.eject_hf_home()
        self.story_server = self.fx.ws + "/bin/story-server"
        self.ltx_movie = self.fx.ws + "/bin/ltx-movie"

    def accept(self, *extra):
        self.fx.events[:] = []
        self.fx.spawned[:] = []
        return self.fx.install("accept", *extra)

    def accept_records(self):
        receipts = self.fx.ws + "/generated/deploy-receipts/" + self.fx.package_id
        names = sorted(n for n in os.listdir(receipts) if n.startswith("accept-") and n.endswith(".json"))
        with open(receipts + "/" + names[-1]) as fh:
            return json.load(fh)

    def test_accept_without_gpu_passes_a0_to_a4(self):
        rc, out, err = self.accept()
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(out.splitlines()[-1], "ACCEPT PASS")
        for step in ("A1 PASS", "A2 PASS", "A3 PASS", "A4 PASS"):
            self.assertIn(step, out.splitlines())
        self.assertEqual(self.fx.spawned, [])
        record = self.accept_records()
        self.assertEqual(record["verdict"], "PASS")
        self.assertEqual(sorted(record["steps"]), ["A0", "A1", "A2", "A3", "A4"])

    def test_T76b_accept_runs_from_receipts_with_the_usb_gone(self):
        receipts = self.fx.ws + "/generated/deploy-receipts/" + self.fx.package_id
        shutil.rmtree(self.fx.usb)
        rc, out, err = self.fx.install("accept", root=receipts)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(out.splitlines()[-1], "ACCEPT PASS")

    def test_T80_gate_last_line_must_equal_the_baseline(self):
        self.fx.run.overrides[(self.fx.fw_py, "tests/test_ltx_movie_offline.py")] = (0, "OK 117/118\n")
        rc, out, err = self.accept()
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(out.splitlines()[-1], "ACCEPT FAIL")
        self.assertIn("OK 117/118", out)
        self.assertIn("OK 118/118", out)
        self.assertEqual(self.accept_records()["verdict"], "FAIL")

    def test_A1_metadata_mismatch_skips_everything_else(self):
        target = self.fx.home + "/ltx-2-mlx/README.md"
        os.utime(target, ns=(1, 1))
        rc, out, err = self.accept()
        self.assertEqual(rc, 1)
        self.assertIn("mtime differs: " + target, out)
        self.assertNotIn(("run", (self.story_server,)), self.fx.events)

    def make_story(self, label):
        story_dir = self.fx.ws + "/generated/stories/deploy-accept-%s-20260925000000" % label
        write_file(story_dir + "/runs/r1/story_summary.json", json.dumps({"completed_units": 2, "requested_units": 2, "units": [{"seconds": 1.0}, {"seconds": 2.0}]}).encode("utf-8"))
        write_file(story_dir + "/hw_gate.json", json.dumps({"phase4_max_pressure": 1, "phase4_swap_delta_gib": 0.0, "phase4_peak_used_gib": 30.5}).encode("utf-8"))
        write_file(story_dir + "/console.txt", b"(residual pad 7 px, 1.00x)\n")
        return story_dir

    def test_T81_criteria_c1_to_c5(self):
        ctx = ip.InstallCtx(ip.parse_args(["--phase", "accept", "--package-root", self.fx.pkg]))
        ctx.ffprobe, ctx.ffmpeg = self.fx.ffprobe, self.fx.ffmpeg
        d = self.make_story("portrait")
        crit = ["c1", "c2", "c3", "c4", "c5"]

        def verdict(rc=0):
            res = ip.evaluate_run(ctx, d, rc, 320, 576, 320, 576)
            return [c for c in crit if not res[c]], res
        failed, res = verdict()
        self.assertEqual(failed, [])
        self.assertEqual(res["record"]["pad_px"], 7)
        self.assertEqual(verdict(1)[0], ["c1"])
        self.assertEqual(verdict("timeout")[0], ["c1"])
        for media, expect in (({"frames": "289"}, ["c2"]), ({"audio": "mp3"}, ["c2"]), ({"w": 704}, ["c2"]),
                              ({"still_w": 640}, ["c3"]),
                              ({"rows_seed": ["0,0,0,1,6220800,ffffffffffffffffffffffffffffffff"]}, ["c4"]),
                              ({"rows_clip": ["0,0,0,1,6220800,ac2833aa09711810c612e6b20955113e", "0,1,1,1,6220800,00"]}, ["c4"])):
            self.fx.run.media_overrides = {"portrait": media}
            self.assertEqual(verdict()[0], expect, media)
        self.fx.run.media_overrides = {}
        write_file(d + "/hw_gate.json", json.dumps({"phase4_max_pressure": 4, "phase4_swap_delta_gib": 0.0}).encode("utf-8"))
        self.assertEqual(verdict()[0], ["c5"])
        write_file(d + "/hw_gate.json", json.dumps({"phase4_max_pressure": 1, "phase4_swap_delta_gib": 1.5}).encode("utf-8"))
        self.assertEqual(verdict()[0], ["c5"])
        write_file(d + "/runs/r1/story_summary.json", json.dumps({"completed_units": 1, "requested_units": 2}).encode("utf-8"))
        self.assertIn("c1", verdict()[0])
        ffmpeg_calls = [c for c in self.fx.run.calls if c[0] == self.fx.ffmpeg and "-f" in c]
        self.assertTrue(ffmpeg_calls)
        for call in ffmpeg_calls:
            index = call.index("-map")
            self.assertEqual(call[index + 1], "0:v:0")
        self.assertIn("select=eq(n\\,144),format=rgb24", [c[c.index("-vf") + 1] for c in ffmpeg_calls])

    def assert_refused(self):
        rc, out, err = self.accept("--gpu")
        self.assertEqual(rc, 5, out + err)
        self.assertEqual(self.fx.spawned, [])
        self.assertEqual([e for e in self.fx.events if e[0] == "run" and e[1][0] == self.story_server], [])
        self.assertIn("ACCEPT REFUSED (GPU precondition; nothing was started)", out)
        return out

    def test_T82_r1_external_hf_home_refuses(self):
        os.makedirs(self.fx.volumes + "/Other/hf_home")
        self.assertIn("r1: ", self.assert_refused())

    def test_T82_r2_scoped_hf_variable_on_a_volume_refuses(self):
        for name in ("Z_IMAGE_HF_HOME", "TRANSFORMERS_CACHE"):
            os.environ[name] = "/Volumes/Ollama/cache"
            self.assertIn("r2: %s=" % name, self.assert_refused())
            del os.environ[name]

    def test_T82_r3_other_gpu_job_refuses(self):
        self.fx.run.overrides[("/usr/bin/pgrep", "-fl", "ltx-2-mlx|z_image|mlx_lm|vllm")] = (0, "123 vllm serve\n")
        self.assertIn("r3: ", self.assert_refused())

    def test_T82_r4_port_in_use_refuses(self):
        ip.HOOKS["port_free"] = lambda port: False
        self.assertIn("r4: ", self.assert_refused())

    def test_T82_r5_swap_refuses_at_3072_and_not_below(self):
        key = ("/usr/sbin/sysctl", "-n", "vm.swapusage")
        self.fx.run.overrides[key] = (0, "total = 4096.00M  used = 3072.00M  free = 1024.00M  (encrypted)\n")
        self.assertIn("r5: ", self.assert_refused())
        self.fx.run.overrides[key] = (0, "total = 4096.00M  used = 3071.99M  free = 1024.01M  (encrypted)\n")
        rc, out, err = self.accept("--gpu")
        self.assertEqual(rc, 0, out + err)

    def test_T83_portrait_argv_and_env(self):
        os.environ["HF_TOKEN"] = "abc"
        os.environ["Z_IMAGE_HF_HOME"] = self.fx.home + "/z"
        os.environ["HF_HUB_CACHE"] = self.fx.home + "/c"
        rc, out, err = self.accept("--gpu")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("ACCEPT PASS", out.splitlines())
        movies = [s for s in self.fx.spawned if s["argv"][1] == self.ltx_movie]
        self.assertEqual(len(movies), 1)
        spawn = movies[0]
        sid = spawn["argv"][4]
        self.assertTrue(re.match(r"^deploy-accept-portrait-\d{14}$", sid), sid)
        story_dir = self.fx.ws + "/generated/stories/" + sid
        self.assertEqual(spawn["argv"], [self.fx.fw_py, self.ltx_movie, NARR, "--story-id", sid, "--panels", "2",
                                         "--seed-image", self.fx.ws + "/generated/hw_gate_seeds/portrait.png",
                                         "--model", self.fx.home + "/ltx-2-mlx/models/ltx-2.5-mlx-q8",
                                         "--no-review", "--story-server-stop-after-story"])
        self.assertEqual(spawn["cwd"], self.fx.ws)
        self.assertTrue(spawn["new_session"])
        self.assertEqual(spawn["stdout_path"], story_dir + "/console.txt")
        env = spawn["env"]
        self.assertEqual(env["HF_HOME"], self.fx.home + "/hf_home")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        for name in ("Z_IMAGE_HF_HOME", "LTX2_MLX_HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "HF_TOKEN"):
            self.assertNotIn(name, env)
        sampler = [s for s in self.fx.spawned if s["argv"][1:2] == ["-c"]][0]
        self.assertEqual(sampler["argv"], [self.fx.fw_py, "-c", ip.SAMPLER_SRC, story_dir + "/hw_gate.json", "4242", "68719476736"])
        with open(story_dir + "/gate_rc.txt") as fh:
            self.assertEqual(fh.read(), "0\n")
        self.assertIn("movie: " + story_dir + "/movie.mp4 (pad_px=7)", out)
        run = self.accept_records()["steps"]["A5"][0]
        self.assertTrue(run["pass"])
        self.assertEqual(run["story_server_stop_rc"], 0)

    def test_T84_gpu_all_runs_four_geometries_restarting_the_server_each_time(self):
        rc, out, err = self.accept("--gpu-all")
        self.assertEqual(rc, 0, out + err)
        seq = []
        for kind, argv in self.fx.events:
            if kind == "run" and argv == (self.story_server, "vision"):
                seq.append("vision")
            elif kind == "spawn" and argv[1] == self.ltx_movie:
                seq.append(argv[4].split("-")[2])
        self.assertEqual(seq, ["vision", "portrait", "vision", "wide", "vision", "square", "vision", "noseed"])
        noseed = [s for s in self.fx.spawned if s["argv"][1] == self.ltx_movie][-1]
        self.assertNotIn("--seed-image", noseed["argv"])
        self.assertEqual(len([e for e in self.fx.events if e == ("run", (self.story_server, "stop"))]), 4)

    def test_story_server_that_never_comes_up_fails_the_run(self):
        ip.HOOKS["http_ok"] = lambda url: False
        sleeps = []
        ip.HOOKS["sleep"] = lambda seconds: sleeps.append(seconds)
        rc, out, err = self.accept("--gpu")
        self.assertEqual(rc, 1)
        self.assertIn("story server did not come up", out)
        self.assertEqual(sum(sleeps), 1800)
        self.assertEqual(self.fx.spawned, [])

    def test_T85_a4_story_server_usage_check(self):
        ctx = ip.InstallCtx(ip.parse_args(["--phase", "accept", "--package-root", self.fx.pkg]))
        self.assertTrue(ip.accept_a4_story_server(ctx)["ok"])
        for value in ((0, "usage: story-server [vision|text|status|stop]\n"), (2, "something else\n")):
            self.fx.run.overrides[(self.story_server,)] = value
            self.assertFalse(ip.accept_a4_story_server(ctx)["ok"], value)

    def test_sampler_source(self):
        compile(ip.SAMPLER_SRC, "sampler", "exec")
        self.assertIn("memsize / 2**30 - min(", ip.SAMPLER_SRC)
        self.assertNotIn("48.0 -", ip.SAMPLER_SRC)
        self.assertIn("kern.memorystatus_vm_pressure_level", ip.SAMPLER_SRC)
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py -k TestAccept`
Expected: FAIL/ERROR. Before this task `--phase accept` falls through to `gated_install` and prints PLAN lines, not `ACCEPT PASS`, and `ip.evaluate_run` is missing.

- [ ] **Step 3a: Insert the accept block** immediately above `# ---- CLI entry point ----` in `scripts/deploy/install_pkg.py`:

```python
# ---------------------------------------------------------------------------
# accept (spec 13)
# ---------------------------------------------------------------------------
ACCEPT_NARR = ("An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm "
               "rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward "
               "the lighthouse door.")
GEOMETRIES = (
    ("portrait", "generated/hw_gate_seeds/portrait.png", 320, 576, 320, 576),
    ("wide", "generated/hw_gate_seeds/wide3x1.png", 960, 320, 960, 320),
    ("square", "generated/hw_gate_seeds/square.png", 512, 512, 512, 512),
    ("noseed", None, 704, 448, 1408, 896),
)
SCOPED_HF_VARS = ("Z_IMAGE_HF_HOME", "LTX2_MLX_HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE")
REFUSAL_ENV_VARS = ("HF_HOME",) + SCOPED_HF_VARS
STORY_SERVER_USAGE = "usage: story-server [vision|text|status|stop]"
SWAP_REFUSE_MB = 3072.00
LTX_MOVIE_TIMEOUT = 7200
STORY_SERVER_UP_TIMEOUT = 1800
POLL_SECONDS = 15

# The plan's Task 13 Step 3 sampler (2026-09-24 redesign plan), with one change:
# phase4_peak_used_gib = memsize/2**30 - min(avail) instead of the hard-coded 48.0.
SAMPLER_SRC = r'''
import glob, json, os, subprocess, sys, time, psutil
out, pid, memsize = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
story_dir = os.path.dirname(out)
samples = []
while psutil.pid_exists(pid):
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    lvl = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                         capture_output=True, text=True).stdout.strip()
    samples.append({"t": time.time(), "avail_gib": vm.available / 2**30,
                    "swap_used_gib": sw.used / 2**30, "pressure": int(lvl or 0)})
    time.sleep(2)
runs = glob.glob(os.path.join(story_dir, "runs", "*"))
t4 = max(os.stat(r).st_birthtime for r in runs) if runs else samples[0]["t"]
p4 = [s for s in samples if s["t"] >= t4] or samples
json.dump({"phase4_start": t4,
           "phase4_min_avail_gib": min(s["avail_gib"] for s in p4),
           "phase4_peak_used_gib": memsize / 2**30 - min(s["avail_gib"] for s in p4),
           "phase4_max_pressure": max(s["pressure"] for s in p4),
           "phase4_swap_delta_gib": max(s["swap_used_gib"] for s in p4) - p4[0]["swap_used_gib"],
           "samples": samples}, open(out, "w"), indent=2)
'''


def load_json(path):
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}


def accept_a1_metadata(ctx):
    problems = []
    for entry in ctx.entries:
        target = entry["t"]
        try:
            st = os.lstat(target)
        except OSError:
            problems.append("missing: %s" % target)
            continue
        if entry["k"] == "f":
            if not stat.S_ISREG(st.st_mode):
                problems.append("not a regular file: %s" % target)
            elif st.st_size != entry["b"]:
                problems.append("size differs: %s" % target)
            elif st.st_mtime_ns != entry["mt"]:
                problems.append("mtime differs: %s" % target)
        elif entry["k"] == "l":
            if not stat.S_ISLNK(st.st_mode) or os.readlink(target) != entry["l"]:
                problems.append("symlink target differs: %s" % target)
        elif not stat.S_ISDIR(st.st_mode):
            problems.append("not a directory: %s" % target)
    return {"ok": not problems, "problems": problems[:200], "problem_count": len(problems), "entries": len(ctx.entries)}


def accept_a2_probes(ctx):
    problems = []
    rc, out = HOOKS["run"]([framework_py(), "-c", "import torch, diffusers, transformers, PIL, numpy, safetensors, psutil, pytest, pexpect"], timeout=300)
    if rc != 0:
        problems.append("framework + user-site import probe rc=%d: %s" % (rc, out[-200:]))
    want = load_json(ctx.package_root + "/manifests/source-host.json").get("vllm_version")
    rc, out = HOOKS["run"]([home() + "/.venv-vllm-metal/bin/python", "-c", "import vllm, vllm_metal, mlx_vlm; print(vllm.__version__)"], timeout=300)
    got = _bp.last_line(out).strip()   # C1: the version is the last line
    if rc != 0 or got != want:
        problems.append("vLLM probe rc=%d version=%r, source-host vllm_version=%r" % (rc, got, want))
    rc, out = HOOKS["run"]([home() + "/ltx-2-mlx/.venv/bin/ltx-2-mlx", "--help"], timeout=300)
    if rc != 0:
        problems.append("ltx-2-mlx --help rc=%d: %s" % (rc, out[-200:]))
    return {"ok": not problems, "problems": problems}


def accept_a3_gates(ctx):
    baseline = load_json(ctx.package_root + "/manifests/acceptance-baseline.json")
    gates, extras = _bp.run_offline_gates(HOOKS["run"], framework_py(), workspace())
    base_gates = dict((g["id"], g) for g in baseline.get("gates", []))
    base_extras = dict((x["id"], x) for x in baseline.get("extras", []))
    problems = []
    for gate in gates:
        base = base_gates.get(gate["id"], {})
        if gate["rc"] != base.get("rc") or gate["last_line"] != base.get("last_line"):
            problems.append("%s: rc=%r last_line=%r; baseline rc=%r last_line=%r"
                            % (gate["id"], gate["rc"], gate["last_line"], base.get("rc"), base.get("last_line")))
    for extra in extras:
        if extra["id"] == "X1" and extra["rc"] != base_extras.get("X1", {}).get("rc"):
            problems.append("X1: rc=%r; baseline rc=%r" % (extra["rc"], base_extras.get("X1", {}).get("rc")))
        if extra["id"] == "X2" and (extra["rc"] != 0 or extra["brace_lines"] != 0):
            problems.append("X2: rc=%r brace_lines=%r" % (extra["rc"], extra["brace_lines"]))
    return {"ok": not problems, "problems": problems, "gates": gates, "extras": extras}


def accept_a4_story_server(ctx):
    rc, out = HOOKS["run"]([workspace() + "/bin/story-server"], timeout=120)
    ok = rc == 2 and STORY_SERVER_USAGE in out
    return {"ok": ok, "problems": [] if ok else ["story-server with no arguments: rc=%r output=%r" % (rc, out[-200:])]}


def gpu_refusals(ctx):
    refusals = []
    for path in sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))):
        if os.path.exists(path):
            refusals.append("r1: %s exists; eject the drive, so that the run can only use the shipped weights" % path)
    for name in REFUSAL_ENV_VARS:
        value = os.environ.get(name, "")
        if value.startswith("/Volumes/"):
            refusals.append("r2: %s=%s points at an external volume" % (name, value))
    rc, out = HOOKS["run"](["/bin/zsh", "-c", 'printf "%s" "$HF_HOME"'])
    if out.startswith("/Volumes/"):
        refusals.append("r2: zsh HF_HOME=%s points at an external volume" % out)
    rc, out = HOOKS["run"](["/usr/bin/pgrep", "-fl", "ltx-2-mlx|z_image|mlx_lm|vllm"])
    if out.strip():
        refusals.append("r3: another GPU job or a live story server is running: %s" % " | ".join(out.strip().splitlines()[:5]))
    if not HOOKS["port_free"](STORY_PORT):
        refusals.append("r4: port %d is in use" % STORY_PORT)
    rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "vm.swapusage"])
    found = re.search(r"used = ([0-9]+(?:\.[0-9]+)?)M", out)
    if rc != 0 or not found:
        refusals.append("r5: cannot read swap usage (%r)" % out.strip())
    elif float(found.group(1)) >= SWAP_REFUSE_MB:
        refusals.append("r5: swap used = %sM >= 3072.00M; wait: swap drains at about 32 MB/min and purge does not help" % found.group(1))
    return refusals


def wait_for_story_server():
    url = "http://127.0.0.1:%d/v1/models" % STORY_PORT
    waited = 0
    while True:
        if HOOKS["http_ok"](url):
            return True
        if waited >= STORY_SERVER_UP_TIMEOUT:
            return False
        HOOKS["sleep"](POLL_SECONDS)
        waited += POLL_SECONDS


def accept_env():
    env = dict(os.environ)
    env["HF_HOME"] = home() + "/hf_home"
    env["HF_HUB_OFFLINE"] = "1"
    for name in SCOPED_HF_VARS + ("HF_TOKEN",):
        env.pop(name, None)
    return env


def ffprobe_stream(ctx, path, select, entries, count=False):
    argv = ([ctx.ffprobe or "ffprobe", "-v", "error", "-select_streams", select] + (["-count_frames"] if count else [])
            + ["-show_entries", "stream=" + entries, "-of", "json", path])
    rc, out = HOOKS["run"](argv, timeout=300)
    if rc != 0:
        return {}
    try:
        streams = json.loads(out or "{}").get("streams") or [{}]
    except ValueError:
        return {}
    return streams[0]


def framemd5(ctx, path, vf):
    # -map 0:v:0 is mandatory: without it the AAC track adds rows and c4 always fails (fixed 2026-09-24).
    argv = [ctx.ffmpeg or "ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", "0:v:0", "-vf", vf,
            "-fps_mode", "passthrough", "-f", "framemd5", "-"]
    rc, out = HOOKS["run"](argv, timeout=300)
    rows = [line for line in out.splitlines() if line.strip() and not line.startswith("#")]
    return rows[0].split(",")[-1].strip() if rc == 0 and len(rows) == 1 else None


def evaluate_run(ctx, story_dir, rc, W, H, SW, SH):
    result = {}
    summaries = glob.glob(os.path.join(story_dir, "runs", "*", "story_summary.json"))
    summary = load_json(max(summaries, key=os.path.getmtime)) if summaries else {}
    result["c1"] = rc == 0 and summary.get("completed_units") == summary.get("requested_units") == 2
    movie = story_dir + "/movie.mp4"
    video = ffprobe_stream(ctx, movie, "v:0", "width,height,codec_name,nb_read_frames", count=True)
    audio = ffprobe_stream(ctx, movie, "a:0", "codec_name")
    result["c2"] = ((video.get("width"), video.get("height")) == (W, H) and str(video.get("nb_read_frames")) == "290"
                    and video.get("codec_name") == "h264" and audio.get("codec_name") == "aac")
    still = ffprobe_stream(ctx, story_dir + "/images/panel_01.png", "v:0", "width,height")
    result["c3"] = (still.get("width"), still.get("height")) == (SW, SH)
    seed_md5 = framemd5(ctx, story_dir + "/clips/panel_02.chainseed.png", "format=rgb24")
    last_md5 = framemd5(ctx, story_dir + "/clips/panel_01.mp4", "select=eq(n\\,144),format=rgb24")
    result["c4"] = seed_md5 is not None and seed_md5 == last_md5
    gate = load_json(story_dir + "/hw_gate.json")
    result["c5"] = bool(gate) and gate.get("phase4_max_pressure", 99) < 4 and gate.get("phase4_swap_delta_gib", 99) <= 1.0
    try:
        with open(story_dir + "/console.txt", "r", encoding="utf-8", errors="replace") as fh:
            console = fh.read()
    except OSError:
        console = ""
    found = re.search(r"residual pad (\d+) px", console)
    result["record"] = {"pad_px": int(found.group(1)) if found else 0, "movie": video, "still": still,
                        "peak_used_gib": round(gate.get("phase4_peak_used_gib", -1.0), 2),
                        "max_pressure": gate.get("phase4_max_pressure"),
                        "swap_delta_gib": round(gate.get("phase4_swap_delta_gib", -1.0), 3),
                        "unit_seconds": [u.get("seconds") for u in summary.get("units", [])]}
    return result


def gpu_run(ctx, label, seed, W, H, SW, SH):
    ws = workspace()
    result = {"label": label, "pass": False}
    rc, out = HOOKS["run"]([ws + "/bin/story-server", "vision"], timeout=120)
    result["story_server_vision_rc"] = rc
    if rc != 0:
        result["error"] = "story-server vision rc=%d: %s" % (rc, out[-200:])
        return result
    if not wait_for_story_server():
        result["error"] = "story server did not come up"
        return result
    stamp = time.strftime("%Y%m%d%H%M%S", HOOKS["now_utc"]())
    sid = "deploy-accept-%s-%s" % (label, stamp)
    story_dir = ws + "/generated/stories/" + sid
    result["story_id"] = sid
    if os.path.lexists(story_dir):
        result["error"] = "story dir %s already exists; a story id is never reused" % story_dir
        return result
    os.makedirs(story_dir)
    argv = ([framework_py(), ws + "/bin/ltx-movie", ACCEPT_NARR, "--story-id", sid, "--panels", "2"]
            + (["--seed-image", ws + "/" + seed] if seed else [])
            + ["--model", ltx25_model_path(), "--no-review", "--story-server-stop-after-story"])
    started = time.time()
    proc = HOOKS["spawn"](argv, cwd=ws, env=accept_env(), stdout_path=story_dir + "/console.txt", new_session=True)
    sampler = HOOKS["spawn"]([framework_py(), "-c", SAMPLER_SRC, story_dir + "/hw_gate.json", str(proc.pid), str(ctx.memsize)],
                             cwd=ws, env=None, stdout_path=story_dir + "/sampler_console.txt", new_session=False)
    try:
        movie_rc = proc.wait(timeout=LTX_MOVIE_TIMEOUT)
    except subprocess.TimeoutExpired:
        HOOKS["killpg"](proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            HOOKS["killpg"](proc.pid, signal.SIGKILL)
            proc.wait()
        movie_rc = "timeout"
    with open(story_dir + "/gate_rc.txt", "w") as fh:
        fh.write("%s\n" % movie_rc)
    try:
        sampler.wait(timeout=60)
    except subprocess.TimeoutExpired:
        sampler.kill()
        sampler.wait()
    stop_rc, _ = HOOKS["run"]([ws + "/bin/story-server", "stop"], timeout=120)
    result["story_server_stop_rc"] = stop_rc
    result["rc"] = movie_rc
    result["seconds"] = round(time.time() - started, 1)
    result.update(evaluate_run(ctx, story_dir, movie_rc, W, H, SW, SH))
    result["pass"] = all(result[c] for c in ("c1", "c2", "c3", "c4", "c5"))
    result["movie"] = story_dir + "/movie.mp4"
    return result


def write_accept_record(ctx, record, stamp, verdict):
    record["verdict"] = verdict
    record["finished_at"] = iso_now()
    directory = receipts_dir(ctx.package_id())
    os.makedirs(directory, exist_ok=True)
    path = directory + "/accept-%s.json" % stamp
    with open(path, "w") as fh:
        fh.write(json.dumps(record, indent=2) + "\n")
    print("install_pkg: accept record written to %s" % path)
    return path


def report_step(step_id, result):
    print("%s %s" % (step_id, "PASS" if result["ok"] else "FAIL"))
    for problem in result["problems"]:
        print("%s   %s" % (step_id, problem))


def phase_accept(ctx, fatal_failures):
    args = ctx.args
    stamp = time.strftime("%Y%m%d%H%M%S", HOOKS["now_utc"]())
    geometries = GEOMETRIES if args.gpu_all else (GEOMETRIES[:1] if args.gpu else ())
    record = {"schema_version": 1, "package_id": ctx.package_id(), "started_at": iso_now(),
              "gpu": "all" if args.gpu_all else ("portrait" if args.gpu else "none"), "steps": {}}
    steps = record["steps"]
    steps["A0"] = {"ok": not fatal_failures, "failed": [r.check_id for r in fatal_failures]}
    if fatal_failures:
        write_accept_record(ctx, record, stamp, "REFUSED")
        print("ACCEPT REFUSED (A0: %s)" % ", ".join(r.check_id for r in fatal_failures))
        return EXIT_REFUSED
    if geometries:
        refusals = gpu_refusals(ctx)
        steps["refusals"] = refusals
        if refusals:
            for line in refusals:
                print("REFUSE " + line)
            write_accept_record(ctx, record, stamp, "GPU-REFUSED")
            print("ACCEPT REFUSED (GPU precondition; nothing was started)")
            return EXIT_GPU_REFUSED
    a1 = accept_a1_metadata(ctx)
    steps["A1"] = a1
    report_step("A1", a1)
    ok = a1["ok"]
    if ok:
        for step_id, func in (("A2", accept_a2_probes), ("A3", accept_a3_gates), ("A4", accept_a4_story_server)):
            result = func(ctx)
            steps[step_id] = result
            report_step(step_id, result)
            ok = ok and result["ok"]
    else:
        print("A2-A5 skipped: A1 found installed files that do not match the manifest")
    runs = []
    if ok and geometries:
        runs = [gpu_run(ctx, *geometry) for geometry in geometries]
        steps["A5"] = runs
        for run in runs:
            failed = [c for c in ("c1", "c2", "c3", "c4", "c5") if not run.get(c)]
            print("A5 %s %s%s" % (run["label"], "PASS" if run["pass"] else "FAIL",
                                  "" if run["pass"] else " (%s)" % (run.get("error") or "failed: " + ", ".join(failed))))
        ok = all(run["pass"] for run in runs)
    write_accept_record(ctx, record, stamp, "PASS" if ok else "FAIL")
    if not ok:
        print("ACCEPT FAIL")
        return EXIT_RUNTIME
    for run in runs:
        print("movie: %s (pad_px=%d)" % (run["movie"], run["record"]["pad_px"]))
    if runs:
        print("Eyeball each movie.mp4 now (manual sign-off, not part of the exit code): the subject is not cropped; "
              "there is no black bar beyond pad_px; panel 2 continues panel 1.")
    print("ACCEPT PASS")
    return EXIT_OK


```

- [ ] **Step 3b: Edit `main()` in `install_pkg.py`.** Replace:
```python
    if args.phase == "verify":
        return phase_verify(ctx, fatal_failures)
    return gated_install(ctx, fatal_failures)
```
with:
```python
    if args.phase == "verify":
        return phase_verify(ctx, fatal_failures)
    if args.phase == "accept":
        return phase_accept(ctx, fatal_failures)
    return gated_install(ctx, fatal_failures)
```

Notes:
- `ACCEPT PASS` is printed **last**, after the movie lines; `test_accept_without_gpu…` asserts the last line.
- The line `    for path in sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))):` is anchor M10; keep it exactly.
- The `-map 0:v:0` comment must not be reworded into anything that contains an anchor.

- [ ] **Step 4: Run to verify they pass (both interpreters).** Expected: pytest `133 passed`; `/usr/bin/python3 tests/test_deploy_pkg.py 2>&1 | tail -1` → `OK`.

- [ ] **Step 5: Negative controls (revert after each).**
  - (a) M10: `glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))` → `[]` → `test_T82_r1_…` FAILS.
  - (b) Remove `"-map", "0:v:0", ` from `framemd5` → T81 FAILS.
  - (c) Change `env["HF_HUB_OFFLINE"] = "1"` to `"0"` → T83 FAILS.

- [ ] **Step 6: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/install_pkg.py qwen-agent-workspace/tests/test_deploy_pkg.py
git commit -m "deploy: accept phase (metadata, probes, gate baselines, GPU refusals, c1-c5 hardware runs)"
```

---

### Task 10: Mutation harness `tests/mutate_deploy_pkg.py` (spec §15.3)

**Files:**
- Create: `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/tests/mutate_deploy_pkg.py`

**Interfaces:**
- Consumes: the four files under test, and the anchors written verbatim in Tasks 1-9.
- Produces: exit 0 iff 12/12 mutants are caught and the control passes. The last line is `MUTANTS <n>/12 CONTROL ok|FAIL`.

- [ ] **Step 1: Create the harness** with exactly this content:

```python
#!/usr/bin/env python3
"""tests/mutate_deploy_pkg.py -- mutation harness for scripts/deploy (spec 15.3).

For each of the 12 mutations: copy scripts/deploy/{build_pkg.py, install_pkg.py,
credential_allowlist.json} and tests/test_deploy_pkg.py into a fresh temp dir with
the same relative layout, apply the (old, new) edits (every old must occur exactly
once and the mutated file must compile, else "ANCHOR <id>" and exit 2), run the
suite with pytest -x, and record caught (rc != 0) or SURVIVED. A no-edit control
must pass. Exit 0 iff 12/12 are caught and the control is ok.

    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 tests/mutate_deploy_pkg.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = "scripts/deploy/build_pkg.py"
INSTALL = "scripts/deploy/install_pkg.py"
FILES = (BUILD, INSTALL, "scripts/deploy/credential_allowlist.json", "tests/test_deploy_pkg.py")
TIMEOUT = 600

MUTATIONS = (
    ("M1", BUILD, (('["token", "stored_tokens",', '["stored_tokens",'),)),
    ("M2", BUILD, (('self.tail = window[-self.keep:] if self.keep else b""', 'self.tail = b""'),)),
    ("M3", BUILD, (("    l4_rescan(ctx)", "    pass"),)),
    ("M4", BUILD, (("    results.append(check_offline_gates(ctx))\n", ""),
                   ("    copy_payload(ctx)\n", "    copy_payload(ctx)\n    check_offline_gates(ctx)\n"))),
    ("M5", INSTALL, (('    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)',
                      '    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, False)'),)),
    ("M6", BUILD, (("    if before_key != after_key:", "    if False:"),)),
    ("M7", INSTALL, (('    if digest != entry["h"]:', "    if False:"),)),
    ("M8", INSTALL, (("            collisions.append((target, reason))", "            pass"),)),
    ("M9", BUILD, (("    return (component, relpath, sha256, pattern_id) in allow",
                    "    return any(a[0] == component and a[1] == relpath and a[3] == pattern_id for a in allow)"),)),
    ("M10", INSTALL, (('glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))', "[]"),)),
    ("M11", INSTALL, (("    if not args.apply:", "    if False:"),)),
    ("M12", INSTALL, (("    if fatal_failures:  # refuse --apply", "    if False:  # refuse --apply"),)),
)


def framework_py():
    return "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"


def make_copy():
    root = tempfile.mkdtemp(prefix="mutate-deploy-")
    for rel in FILES:
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(WS, rel), dst)
    return root


def apply_edits(root, rel, edits):
    path = os.path.join(root, rel)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for old, new in edits:
        if text.count(old) != 1:
            return False
        text = text.replace(old, new, 1)
    try:
        compile(text, path, "exec")
    except SyntaxError:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def run_suite(root):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [framework_py(), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
            os.path.join(root, "tests", "test_deploy_pkg.py")]
    try:
        proc = subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124
    return proc.returncode


def main():
    control_root = make_copy()
    try:
        control_ok = run_suite(control_root) == 0
    finally:
        shutil.rmtree(control_root, True)
    caught = 0
    for mutation_id, rel, edits in MUTATIONS:
        root = make_copy()
        try:
            if not apply_edits(root, rel, edits):
                print("ANCHOR %s" % mutation_id)
                return 2
            rc = run_suite(root)
        finally:
            shutil.rmtree(root, True)
        if rc != 0:
            caught += 1
            print("MUTATION %s caught" % mutation_id)
        else:
            print("MUTATION %s SURVIVED" % mutation_id)
        sys.stdout.flush()
    print("MUTANTS %d/%d CONTROL %s" % (caught, len(MUTATIONS), "ok" if control_ok else "FAIL"))
    return 0 if caught == len(MUTATIONS) and control_ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it (main thread; about 13 suite runs).**

Run: `cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 tests/mutate_deploy_pkg.py > generated/deploy-mutate-$(date +%Y%m%d%H%M%S).txt 2>&1; echo "rc=$?"; tail -13 generated/deploy-mutate-*.txt | tail -13`
Expected: `MUTATION M1 caught` … `MUTATION M12 caught`, then `MUTANTS 12/12 CONTROL ok`, rc=0.
- An `ANCHOR <id>` means an anchor was reformatted or duplicated: fix the source text, not the harness.
- A `SURVIVED` means a test is too weak. Strengthen the named catching test from spec §15.3; never weaken the mutation.

- [ ] **Step 3: Commit.**
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/tests/mutate_deploy_pkg.py
git commit -m "deploy: 12-mutation harness with clean control"
```

---

### Task 11: Whole-suite gates and design review (main thread)

**Files:** none are created. The results are recorded in this document.

- [ ] **Step 1: Dual-interpreter gate (SC1).**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py > generated/deploy-pytest313.txt 2>&1; echo "pytest rc=$?"; tail -1 generated/deploy-pytest313.txt
/usr/bin/python3 tests/test_deploy_pkg.py > generated/deploy-unittest39.txt 2>&1; echo "unittest rc=$?"; tail -3 generated/deploy-unittest39.txt
```
Expected:
- `pytest rc=0` and `133 passed`;
- `unittest rc=0`, `Ran 133 tests`, and a last line of exactly `OK`, never `OK (skipped=…)`.

- [ ] **Step 2: Mutation gate (SC2).** Rerun Task 10 Step 2. Expected: `MUTANTS 12/12 CONTROL ok`, rc=0.

- [ ] **Step 3: Grep gates.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/usr/bin/grep -nE 'comfyui_|cctech_|wan_video_skill|wan-generate|COMFY_MLX|video_backend|video-backend' scripts/deploy/*.py tests/test_deploy_pkg.py tests/mutate_deploy_pkg.py; echo "grep1 rc=$?"
/usr/bin/grep -niE 'comfyui|cctech|chriscoletech|8189' scripts/deploy/build_pkg.py scripts/deploy/install_pkg.py; echo "grep2 rc=$?"
```
Expected: no output, and both `rc=1`. The absolute `/usr/bin/grep` is used because the shell's grep wrapper hides some paths.

- [ ] **Step 4: Nothing else changed.**
```bash
cd /Users/reubenpatterson/local_model_harness
git status --porcelain -- qwen-agent-workspace/z_image_skill.py qwen-agent-workspace/ltx2_mlx_video_skill.py qwen-agent-workspace/ltx_image_fit.py qwen-agent-workspace/content_safety.py qwen-agent-workspace/bin/ltx-movie qwen-agent-workspace/bin/ltx-story-images qwen-agent-workspace/bin/ltx-story-manifest qwen-agent-workspace/bin/ltx-mlx-render qwen-agent-workspace/bin/story-server qwen-agent-workspace/bin/qwen-agent; echo "---"
git log --stat --oneline 6ab72ac..HEAD
```
Expected:
- the porcelain output is empty;
- the log shows only the 5 files, with `docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md` if it was committed.

Then rerun the 7 offline gates as in Task 0 Step 3. Expected: the same last lines as the Baseline table.

- [ ] **Step 5: Design review (CLAUDE.md §3).** Dispatch `design-reviewer` over `git diff 6ab72ac..HEAD -- qwen-agent-workspace/scripts/deploy qwen-agent-workspace/tests/test_deploy_pkg.py qwen-agent-workspace/tests/mutate_deploy_pkg.py`, with this plan and the spec attached.
  - Tell the reviewer the work is complete and nothing is running.
  - Require a per-finding disposition table.
  - Verify each finding before acting on it; three findings on a previous track were factually wrong.
  - For every NEEDS-FIX, the reviewer authors the verbatim patch, the executor applies it, and Steps 1-4 rerun.

- [ ] **Step 6: Record the results.**

| Gate | Result |
|---|---|
| pytest 3.13 | |
| unittest 3.9.6 (last line) | |
| mutation harness | |
| grep gates | |
| pipeline files untouched | |
| design review disposition | |

---

### Task 12: The real build onto `/Volumes/ltx-chain-deploy` (main thread only — real hardware, real USB drive)

**Target volume changed after Task 11's whole-branch review (Finding C1):** the drive's default volume, `/Volumes/Ollama`, was found to carry live HF credentials (`hf_home/token`, `hf_home/stored_tokens`) and old deploy packages outside any package's own directory — a real gap this whole plan exists to prevent. Rather than rely solely on a code check, a fresh, empty, dedicated, case-sensitive APFS volume, `/Volumes/ltx-chain-deploy`, was created in the same physical drive's APFS container (`disk5`, 255.9 GB free at creation time), leaving `/Volumes/Ollama` and the separate `/Volumes/My Passport` Time Machine backup volume untouched. Every command below targets it explicitly via `--usb-root /Volumes/ltx-chain-deploy` (build_pkg.py's own default, `USB_ROOT_DEFAULT`, is still `/Volumes/Ollama` — do not omit the flag). Task 11 also added a new fatal check, B20, which independently refuses to build onto any volume already holding a present, file-backed known-secret source (defense-in-depth: it would fail loudly if `--usb-root` were ever pointed at `/Volumes/Ollama` by mistake).

**Files:**
- Modify: `scripts/deploy/credential_allowlist.json` (only with the user-approved notes, Step 4).
- Logs go in `generated/` (gitignored, but inside the repo).
- Results are recorded in the table at the end of this task.

**Depends on:** Task 11 complete. The user must be present for Step 4, which is a human review.

**Never** run these steps from a subagent. Offline checks against fakes do not prove real I/O to a physical device.

- [ ] **Step 1: Preconditions.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
mount | /usr/bin/grep -i '/Volumes/ltx-chain-deploy'; /usr/sbin/diskutil info /Volumes/ltx-chain-deploy | /usr/bin/grep -i 'Personality\|Container Free'
/usr/sbin/lsof -nP -iTCP:8177 -sTCP:LISTEN; echo "lsof rc=$?"
pgrep -fl 'ltx-2-mlx|z_image|mlx_lm|vllm' || echo "no GPU job"
PKG=ltx-chain-deploy-$(date +%Y%m%d); echo "PKG=$PKG"; ls -d /Volumes/ltx-chain-deploy/$PKG 2>&1
```
Expected:
- the mount is present and `Case-sensitive APFS`, with ≥ 147 GB free (measured 255.9 GB while planning);
- `lsof rc=1`, meaning nothing is on port 8177;
- `no GPU job`;
- `/Volumes/ltx-chain-deploy/$PKG: No such file or directory`.

If 8177 is held, **ask the user** before running `bin/story-server stop`. If the package dir exists, STOP and ask the user; do not delete it (rm may be blocked).

Write the literal `PKG` value into the results table and use that literal in every later command. Do not recompute it after midnight.

- [ ] **Step 2: First dry run.** Do not open `/Volumes/ltx-chain-deploy` in Finder at any point in this task: Finder writes `.DS_Store`, which fails L4.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --dry-run --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-dryrun-1.txt 2>&1; echo "rc=$?" >> generated/deploy-dryrun-1.txt; tail -25 generated/deploy-dryrun-1.txt
```
Expected: rc=4 with exactly one `FAIL` line, `FAIL B13 …` (P1: roughly 64 un-reviewed L2 hits). All of B01-B12 and B14-B20 are `PASS`; B17 passes now that P0 is resolved at 6ab72ac; B20 passes because `/Volumes/ltx-chain-deploy` is a fresh volume with no known-secret source on it.
- Any other FAIL is a real finding. Read its message, diagnose from the evidence, and report to the user before changing anything.
- A `FAIL B20` here would mean `--usb-root` was mistyped onto a volume holding a real credential — STOP immediately and do not proceed with any `--apply`.
- Do not call it an environment issue without evidence.

- [ ] **Step 3: SC3 totals.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 - generated/deploy-dryrun-1.txt <<'PY'
import re, sys
EXPECTED = {"A1": 715917, "A2": 1616096, "B1": 7620820, "B2": 382091499, "B3": 50325472, "B4": 74718758789,
            "B5": 0, "D1": 1724423499, "F1": 2148085949, "F2": 0, "F3": 1524525421, "H0": 0, "H1": 32848312686,
            "H2": 8044983783, "H3": 343225057, "H4": 19632160689, "H5": 0}
TOTAL = 141426845677
GIB = 1024 ** 3
got, total = {}, None
for line in open(sys.argv[1]):
    m = re.match(r"^([A-H][0-9]) \S+ files=\d+ symlinks=\d+ dirs=\d+ bytes=(\d+) ", line)
    if m:
        got[m.group(1)] = int(m.group(2))
    m = re.match(r"^TOTAL files=\d+ symlinks=\d+ dirs=\d+ bytes=(\d+) ", line)
    if m:
        total = int(m.group(1))
bad = []
for cid, want in sorted(EXPECTED.items()):
    have = got.get(cid)
    tol = want * 0.01 if want >= GIB else 10737418
    if have is None or abs(have - want) > tol:
        bad.append("%s have=%r want=%d tol=%d" % (cid, have, want, tol))
if total is None or abs(total - TOTAL) > TOTAL * 0.01:
    bad.append("TOTAL have=%r want=%d" % (total, TOTAL))
print("SC3", "PASS" if not bad else "FAIL", bad)
PY
```
Expected: `SC3 PASS []`. A FAIL names the component. Report it to the user; component sizes can legitimately drift (e.g. a package installed into F3). Any change to the tolerance or the expected table is the user's decision.

- [ ] **Step 4: Credential report and human allowlist review (P1).**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --credential-report --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-credential-report-1.txt 2>&1; echo "rc=$?" >> generated/deploy-credential-report-1.txt
/usr/bin/grep -c '^L2 NEW ' generated/deploy-credential-report-1.txt; /usr/bin/grep -c '^L1 ' generated/deploy-credential-report-1.txt; tail -2 generated/deploy-credential-report-1.txt
```
Expected: rc=1, 0 `L1` lines, and about 64 `L2 NEW` lines.
- Any `L1` line is a hard stop: report it.
- `ENUM-ERROR` / `ALLOWLIST-ERROR` lines are a hard stop.

Then:
1. Group the NEW lines by pattern and path family (PyCryptodome, `ecdsa`, `tornado`, `rsa`, `google-auth`, `cryptography` test keys, `googleapiclient` discovery docs, `cv2/.dylibs`, `botocore`/`boto3` examples, `PIL/ImageFont.py`, `transformers/testing_utils.py`, `django_extensions` RECORD, `litellm/proxy/_super_secret_config.yaml`, `diffusers` RECORD, …).
2. Write a proposed `note` for each line. It describes what the match is (e.g. "PyCryptodome self-test RSA key; public test vector, not a credential"). It must never contain matched bytes.
3. Present the grouped list and proposed notes to the user, and **wait for explicit approval**. Nothing is allowlisted automatically.
4. Apply any edits the user makes to the notes.
5. After approval, build the allowlist from the report lines and the approved notes. `NOTES` is a dict that maps `"<component>|<relpath>|<pattern>"` to the approved note, written to `generated/deploy-allowlist-notes.json`:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 - <<'PY'
import json
notes = json.load(open("generated/deploy-allowlist-notes.json"))
entries = []
for line in open("generated/deploy-credential-report-1.txt"):
    if line.startswith("L2 NEW "):
        hit = json.loads(line[len("L2 NEW "):])
        key = "%s|%s|%s" % (hit["component"], hit["relpath"], hit["pattern"])
        note = notes[key]
        assert isinstance(note, str) and note.strip(), key
        hit["note"] = note
        entries.append(hit)
with open("scripts/deploy/credential_allowlist.json", "w") as fh:
    fh.write(json.dumps({"schema_version": 1, "entries": entries}, indent=2) + "\n")
print("allowlist entries:", len(entries))
PY
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --credential-report --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-credential-report-2.txt 2>&1; echo "rc=$?"; tail -1 generated/deploy-credential-report-2.txt
```
Expected: `allowlist entries: <n>` equal to the NEW count, then rc=0 and `build_pkg: CREDENTIAL REPORT CLEAN: l1=0 new=0 allowlisted=<n> stale=0`. A `KeyError` means a line has no approved note: go back to the user.

Then rerun the unit suite and confirm it is still green (Task 11 Step 1). The committed allowlist is only stale for fixtures, which is a non-fatal WARN. Commit:
```bash
cd /Users/reubenpatterson/local_model_harness
git add qwen-agent-workspace/scripts/deploy/credential_allowlist.json
git commit -m "deploy: human-reviewed L2 credential allowlist (P1)"
```
The new commit leaves B17 unaffected, because B17 checks only the 10 pipeline files against HEAD. B19 requires it: until the allowlist is committed, B19 fails with `scripts/deploy/credential_allowlist.json: modified`.

- [ ] **Step 5: Second dry run.**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --dry-run --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-dryrun-2.txt 2>&1; echo "rc=$?" >> generated/deploy-dryrun-2.txt; tail -22 generated/deploy-dryrun-2.txt
```
Expected: rc=0, the final line `build_pkg: DRY RUN OK`, and 20 `PASS B..` lines (B01-B20). B13's message reads `L2: <n> hit(s), all allowlisted`.

- [ ] **Step 6: The real `--apply`.** Launch it as **one** background Bash invocation (`run_in_background: true`), with no `nohup` or `&` inside, and capture rc into the log:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --apply --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-apply.log 2>&1; echo "rc=$?" >> generated/deploy-apply.log
```
The expected duration is about 40-60 min at roughly 60 MB/s, plus the L4 rescan. While it runs:
- start no GPU render and no heavy I/O;
- do not browse the drive in Finder;
- do not stop the process.

**Completion is all three of these**; a "background task exited" notification alone is not completion:
1. `tail -1 generated/deploy-apply.log` is `rc=0`;
2. `pgrep -f 'build_pkg.py --apply'` prints nothing;
3. `ls -l /Volumes/ltx-chain-deploy/<PKG>/MANIFEST.json` exists and `/Volumes/ltx-chain-deploy/<PKG>/BUILD-FAILED.json` does not.

The line before `rc=0` is `build_pkg: BUILD OK: /Volumes/ltx-chain-deploy/<PKG> (<n> entries, <bytes> bytes)`.

**Failure handling:**
- **rc=5 (copy-stage abort):** read the `COPY ABORTED` line. For `SourceChanged`, find what touched the source (a running job, a pip install, Spotlight is not one), wait until it is quiet, then run the same command with `--apply --resume --usb-root /Volumes/ltx-chain-deploy --package-id <PKG>`. For `CredentialLeak` (L3), STOP and report to the user **without printing any value**: a real HF token value is in the named source file.
- **rc=3 (post-copy):** read `BUILD-FAILED.json`'s `failed_step` and `error`.
  - A PC4 `DS_Store:` failure means Finder touched the drive. Ask the user to allow `find "/Volumes/ltx-chain-deploy/<PKG>" -name .DS_Store -delete`, then run `--apply --resume --usb-root /Volumes/ltx-chain-deploy --package-id <PKG>`.
  - A PC4 `L2 … MANIFEST-ENTRIES.jsonl` (or another ROOT file) finding needs a `("ROOT", "<rel>", sha256, pattern)` allowlist entry. The user must approve its note, and the sha256 is that of the package file. Add it, commit it, then run `--apply --resume --usb-root /Volumes/ltx-chain-deploy --package-id <PKG>`.
- **rc=4:** a check failed at launch. Read the FAIL lines; nothing was written.

- [ ] **Step 7: `--verify-only` (SC4).** Launch it as one background invocation, the same way:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/deploy/build_pkg.py --verify-only --usb-root /Volumes/ltx-chain-deploy --package-id <PKG> > generated/deploy-verify.log 2>&1; echo "rc=$?" >> generated/deploy-verify.log
```
Expected (about 40 min): the last two lines are `build_pkg: VERIFY ok: <n> files re-hashed` and `rc=0`. Here `<n>` equals the number of `f` entries (check with `/usr/bin/grep -c '"k":"f"' /Volumes/ltx-chain-deploy/<PKG>/MANIFEST-ENTRIES.jsonl`). Any `FAIL VERIFY` line is a real finding: report it.

- [ ] **Step 8: Spot checks on the real package.**
```bash
P=/Volumes/ltx-chain-deploy/<PKG>
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "import json;m=json.load(open('$P/MANIFEST.json'));print(m['schema_version'],m['entries_count'],m['totals'],m['credential_scan'],m['source_git_head'])"
ls "$P/payload" | sort; ls "$P/manifests"; /usr/bin/grep -c 'bin/ltx-movie' "$P/README.md"
/usr/bin/grep -n 'bin/ltx-movie' "$P/README.md" | /usr/bin/grep -vc -- '--model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8'
```
Expected:
- `4 <n> {…bytes≈141.4e9…} {'l1': 'clean', 'l2_allowlisted': <n>, 'l3_values_loaded': <k>, 'l4': 'clean'} <HEAD sha>`.
  - `<k>` is the number of **distinct** HF token values found across the two `token` files, `stored_tokens` and `$HF_TOKEN`. Record the actual value.
  - `<k> >= 1` is expected on this host, where both token files are present.
  - `<k> == 0` means L3 loaded nothing, so the leak defense was inert: STOP and report.
- 13 payload dirs: every component except B5, F2, H0, H5.
- 7 manifests.
- A `bin/ltx-movie` line count ≥ 2, and a final count of `0` lines without `--model`.

- [ ] **Step 9: Record the results and report to the user.**

**Real Build Results (filled in 2026-09-26, `--usb-root /Volumes/ltx-chain-deploy` — retargeted from the plan's original `/Volumes/Ollama` per Task 11's whole-branch review, Finding C1):**

| Step | Command | rc | Key line | Time (UTC) |
|---|---|---|---|---|
| PKG id | — | — | `PKG=ltx-chain-deploy-20260925` | 2026-09-26 02:43 |
| dry run 1 | `--dry-run` | 4 | `FAIL B13 64 L2 hit(s) not allowlisted`; all other B01-B20 PASS | 2026-09-26 02:44 |
| SC3 | totals check | — | `SC3 PASS []` | 2026-09-26 02:44 |
| credential report 1 | `--credential-report` | 1 | `CREDENTIAL REPORT NOT CLEAN: l1=0 new=64 allowlisted=0 stale=0` | 2026-09-26 02:46 |
| user allowlist approval | — | — | "Approve all as written" (all 64 hits grouped by pattern/library family, notes describing legitimate open-source library internals — self-tests, PEM-parsers, docs, deprecated example data — none containing matched bytes) | 2026-09-26 02:47 |
| credential report 2 | `--credential-report` | 0 | `CREDENTIAL REPORT CLEAN: l1=0 new=0 allowlisted=64 stale=0` | 2026-09-26 02:55 |
| dry run 2 | `--dry-run` | 0 | `build_pkg: DRY RUN OK`; 20 `PASS B..` lines (B01-B20) | 2026-09-26 02:57 |
| apply | `--apply` | 0 | `build_pkg: BUILD OK: /Volumes/ltx-chain-deploy/ltx-chain-deploy-20260925 (172694 entries, 141426845403 bytes)` | 2026-09-26 03:37 |
| verify-only | `--verify-only` | 0 | `build_pkg: VERIFY ok: 152670 files re-hashed`, 0 `FAIL VERIFY` lines | 2026-09-26 04:12 |

Step 8 spot checks, all as expected: `MANIFEST.json` schema 4, 172694 entries, 141,426,845,403 bytes, `credential_scan={'l1': 'clean', 'l2_allowlisted': 64, 'l3_values_loaded': 2, 'l4': 'clean'}`, `source_git_head=05903afbb48611329b7f07419f9bf26a6f1b3de1`; 13 payload dirs present (B5/F2/H0/H5 correctly absent — symlink/dir-only components); 7 manifest files present; `bin/ltx-movie` appears 2 times in the README, 0 of those lines missing `--model`.

Report to the user:
- the table (above);
- correction C1 (vllm last line) and addition C3 (B11 normpath), which need their explicit acknowledgement;
- the fact that SC5 (install plus `accept --gpu` on the second Mac) is still outstanding by design;
- the target-volume change (Finding C1 from Task 11's review): built onto a fresh dedicated `/Volumes/ltx-chain-deploy` volume instead of the originally-planned `/Volumes/Ollama`, which was found to carry live HF credentials outside any package's own directory.

---

## Self-Review

**1. Spec coverage**

| Spec § | Requirement | Task |
|---|---|---|
| §2 SC1 | dual-interpreter suite, no skips | 1-9 (Step 4 each), 11 Step 1 |
| §2 SC2 | 12 mutants plus control | 10, 11 Step 2 |
| §2 SC3 | dry-run totals within tolerance | 12 Step 3 |
| §2 SC4 | real `--apply`, then `--verify-only` | 12 Steps 6-7 |
| §2 SC5 | target-Mac install/accept | out of plan scope (no second Mac); code in 8-9; flagged in 12 Step 9 |
| §2 SC6 | README checks T90-T92 | 5 |
| §2 SC7 | L1-L4 during the build; I08 | 3, 6, 8, 12 |
| §3.1 D1-D12 | decisions | Global Constraints; D12/B17 in 4; D10/L3 in 1, 3, 6 |
| §3.2 R1-R12 | resolutions | R1 `s` (2); R2 F2 (2); R3/R4 excludes/prune (2); R5 pins (4 B05); R6 (2); R7 patterns (3); R8 shared helpers (8); R9 no state file (4/6/7); R10 README interpreter (5); R11 probes in accept (9); R12 A1 metadata / verify full hash (8, 9) |
| §4 P0/P1 | provenance, allowlist review | P0 resolved (C10, Task 0); P1 in 12 Step 4 |
| §5.1-5.3 | files, language level, constants, HOOKS, CheckResult, line formats | 1, 8; T95 |
| §6.1-6.5 | layout, schema 4, MANIFEST.json, manifests/*, BUILD-FAILED | 1 (entry line), 4 (host/freeze/git/baseline), 3 (credential-scan), 6 (root files, MANIFEST, BUILD-FAILED) |
| §7 | 17 components, exact lists | 2 (T01/T02/T02b/T04/T05) |
| §8.1-8.4 | L1, L2 + allowlist + report, L3, L4 | 1, 3, 6 |
| §9 | R-PRE, stage order, exit mapping, dry-run output | 6 (T20-T23, TestBuildCli) |
| §10 B01-B17, §10.1 | checks, gates | 4 |
| §11.1-11.4 | copy engine, resume, verify-only | 1, 6, 7 |
| §12.1-12.6 | install CLI, gate, I01-I20, identity, phases, receipts | 8 |
| §13, 13.1, 13.2 | accept, refusals, GPU procedure, c1-c5 | 9 |
| §14 | README | 5 (+ equality in 6) |
| §15.1-15.3 | conventions, T01-T95, mutations | 1-10 |
| §15.4 | real-host checks | 12 |
| §16 | exit codes | 6, 7, 8, 9 |

Gaps: none. SC5 is excluded by the caller's instruction (no second Mac) and is flagged in Task 12 Step 9.

**2. Placeholder scan.**
- The only `<…>` tokens in commands are `<PKG>`, a literal the executor fixes once in Task 12 Step 1 and records.
- Each "fill in" table is a results table, not missing content.
- Every code step contains the complete code.

**3. Type and name consistency.**
- The names used across tasks were checked. Among them: `prepare_l2`, `load_deploy_files`, `check_offline_gates` (B15), `run_offline_gates(run, py, cwd)`, `analyze_resume`, `resume_prefix_len`, `resume_keep_bytes`, `resume_rename`, `resume_error`.
- Also checked: `copy_payload`, `build_stage`, `finish_build`, `fail_post_copy`, `l4_rescan`, `verify_package`, `cmd_verify_only`, `InstallCtx.package_id()`, `target_status`, `receipt_entries`, `phase_components`, `gated_install`, `phase_verify`, `phase_accept`, `evaluate_run`, `gpu_run`, `SAMPLER_SRC`.
- `install_pkg` uses only `_bp` helpers that never read `_bp.HOOKS` (`sha256_file`, `read_entries`, `list_tree`, `load_allowlist`, `scan_package`, `format_result`, `PENDING_PREFIX`, `last_line`, `run_offline_gates`). The tests enforce this: `_bp.HOOKS` is filled with raising fakes.
- Test counts per task: 11 → 23 → 33 → 49 → 53 → 75 → 85 → 118 → 133.

**4. Review Focus.** Each RF1-RF5 has a named test in its owning task (listed in the Review Focus section). Other risks considered but not added as tests:
- A path in `MANIFEST-ENTRIES.jsonl` could match `openai_api_key` (for example `_sk-` followed by 32 name characters). This is handled operationally in Task 12 Step 6.
- Directories created by a failed install run are created via a temp-name-then-atomic-rename pattern (`make_dir`), so a killed run can never leave a manifest directory under its real name at the wrong mode; `verify` now checks directory modes for every manifest directory, not just file modes (Task 8b, commit b79c8918519f6e7d62ebe8238764daeb0b6acecf — closes a real bug found in Task 8's review).
- If accept's A3 compares combined output lines and the target prints an environment-specific warning, A3 fails (KR2: diagnose, do not loosen the check).
- `HF_HUB_OFFLINE=1` has never been exercised for the vision server (KR1). `accept --gpu` on the target exposes it.

---

## Execution Handoff

Plan complete; save it to `docs/superpowers/plans/2026-09-25-ltx-chain-deploy-package.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** — a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** — I implement every task myself in this session, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end.

**For this plan I recommend Subagent-driven.** Tasks 1-9 chain tightly through exact function names and the mutation anchors, and a shipped mistake here is a credential leak onto a portable drive. A per-task review with a verbatim-anchor check before the next task starts is worth the extra contexts. Tasks 0, 11 and 12 must run in the main thread in either mode. Does the plan capture what you want, and which approach should we use?
