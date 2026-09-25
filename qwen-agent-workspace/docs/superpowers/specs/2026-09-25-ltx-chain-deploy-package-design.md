# ltx-chain USB deployment package — design spec

Date: 2026-09-25
Status: Design approved by the user during brainstorming (Approach B, decisions D1-D12). Spec only; nothing is implemented. **Precondition P0 (§4) is not met today, so the build refuses to run until the user resolves it.**
Branch: `ltx2-mlx-video-pipeline`. Spec written against HEAD `8043a091d9cbe22a3569a3bb5dcc22c4aad26818`.
Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. Relative paths are relative to `WS` unless they say otherwise.
Repository root (`REPO`): `/Users/reubenpatterson/local_model_harness`.

---

## 1. Overview and motivation

Commit 8043a09 redesigned `bin/ltx-movie` for sequential I2V frame-chaining and deleted every ComfyUI, wan and cctech backend. It also deleted the old USB deployment tooling. That tooling (`scripts/deploy/build_package.py` + `install_package.py`, about 3,100 lines) cloned the whole machine into a 48 GB package tied to ComfyUI and cctech. A copy survives in `.claude/snapshots/narrative-chain-pre-20260924143621/untracked.tar.gz`.

The user wants a new USB package that installs **exactly the new pipeline** on a second, similar Mac. That Mac must have the same account. The pipeline is `z_image_skill.py`, `ltx2_mlx_video_skill.py`, `ltx_image_fit.py`, `content_safety.py`, `bin/ltx-movie`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/story-server` and `bin/qwen-agent`. The package also carries the runtimes and model weights those files need. On 2026-09-24/25 this pipeline passed a four-run real-hardware gate (plan `docs/superpowers/plans/2026-09-24-ltx-movie-narrative-chain-redesign.md`, Task 13).

**Approach B (hybrid).** Two new, small, stdlib-only scripts, about 1,600 lines together:

- `scripts/deploy/build_pkg.py` runs on the source host.
- `scripts/deploy/install_pkg.py` runs on the target.

Parts taken from the old 48 GB system (its proven copy-integrity engine):
- hashing while copying;
- aborting when a source changes mid-copy;
- `--resume` and `--verify-only`;
- JSONL manifest entries;
- `MANIFEST.json` written last by atomic rename.

Parts taken from the stale 16 GB installer (its cleaner control flow):
- explicit phases;
- dry-run by default;
- `--apply` refused while any fatal check fails;
- paths built from `~` at call time.

Auditing the 3,000+ old lines for ComfyUI/cctech leftovers would cost more than writing the new scripts.

## 2. Success criteria

| ID | Criterion | How it is verified |
|---|---|---|
| SC1 | `tests/test_deploy_pkg.py` passes under framework Python 3.13 pytest **and** under Apple `/usr/bin/python3` 3.9.6 unittest, with no skipped tests. | `cd WS && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -q tests/test_deploy_pkg.py` → rc 0. Then `cd WS && /usr/bin/python3 tests/test_deploy_pkg.py` → rc 0, and its last line is `OK` (not `OK (skipped=…)`). The two runners report different counts by design. |
| SC2 | Every mutation in §15.3 makes the suite fail, and the unmutated control passes. | `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 tests/mutate_deploy_pkg.py` → rc 0, last line `MUTANTS 12/12 CONTROL ok`. |
| SC3 | The real-host dry run reports totals within tolerance of §7's measured sizes. | `build_pkg.py --dry-run`: TOTAL bytes within 1% of 141,426,845,677. Each component ≥ 1 GiB is within 1% of its §7 value. Each component < 1 GiB is within 0.01 GiB (10,737,418 bytes) of it. |
| SC4 | A real `--apply` build completes and verifies. | `build_pkg.py --apply` → rc 0 and `MANIFEST.json` exists. `build_pkg.py --verify-only` → rc 0. |
| SC5 | Install and acceptance succeed on the target Mac. | `preflight` → `system-python --apply` → `user --apply` → `verify` → `accept --gpu`, each rc 0, and accept prints `ACCEPT PASS`. This needs the second Mac. The work is not complete without it. |
| SC6 | The shipped README passes the README checks (T90-T92). | Part of SC1. |
| SC7 | No secret byte reaches the package. | L1-L4 (§8) pass during the SC4 build. The installer's own L1+L2 rescan (I08) passes on the target. |

**Must-haves:** everything this document specifies.
**Nice-to-haves, deliberately NOT implemented:**
- running the L3 scan during dry-run;
- a USB throughput benchmark or ETA;
- an installer lock file;
- uninstall or rollback;
- preserving xattrs, ACLs or file flags;
- `chown`.

## 3. Decisions

### 3.1 Fixed decisions from brainstorming (not to be re-litigated)

| # | Decision | Where it lands |
|---|---|---|
| D1 | **Identical account.** The target has user `reubenpatterson` with home `/Users/reubenpatterson`. Paths are never re-pinned. | B11, I05; §17 |
| D2 | **Ship only `ltx-2.5-mlx-q8`.** Source is `/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8`, a plain directory (not HF-cache layout) with 28 top-level files, 69.59 GiB, excluding `.cache/`. ltx-2.3 and its Gemma-3-12B text encoder are not shipped: 2.5 loads its text encoder from `text_encoder.safetensors` inside its own pack. | Component B4, B04 |
| D3 | **Vision-mode story generation only** (Qwen3-VL-32B via vLLM-Metal). Text mode (MTPLX 27B via Homebrew) is out of scope. | §7, §17 |
| D4 | **Exclude the Huihui-27B / qwen-serve-guard group.** It only feeds `bin/qwen-agent`'s auto-restart fallback. | §7, §17 |
| D5 | **Ship the 2.5 pack untrimmed**, including `transformer-dev.safetensors` and the distilled LoRA. | B4 |
| D6 | **GPU acceptance.** `accept --gpu` runs one 2-panel portrait run. `--gpu-all` runs portrait, wide, square and no-seed. | §13 |
| D7 | **Exclude the broken employer-internal editable-install references** `fubotv_mcp_common` and `student_agent_mcp`. | F1, F3 excludes (R3) |
| D8 | **The code payload is an explicit file list**, never a tree walk. It is exactly the 10 pipeline files plus the 7 test files in §7 (A1). | A1 |
| D9 | **The `--model` default risk is handled by documentation only.** `bin/ltx-movie` keeps defaulting to `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8`. Every shipped README example passes `--model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8` explicitly. | §14, T90 |
| D10 | **L3 known-secret scan during copy.** Live HF token values are read into memory only. Every byte written into the package is scanned, with a (longest secret − 1) byte overlap across chunk boundaries. On a hit, the partial file is deleted, the error names the source file only, and no `MANIFEST.json` is written. | §8.3, B14 |
| D11 | **The target is assumed fresh.** Each target must be absent or identical. Any differing target is fatal, and the installer lists every collision. | I10 |
| D12 | **Provenance gate (B17).** The build refuses unless all 10 pipeline files match a clean git commit (HEAD). | B17; see P0 |

### 3.2 Resolutions made while writing this spec

Each of these fixes a gap or a factual error in the brainstorm brief, found by reading the code and the disk. They are binding.

| # | Resolution | Evidence |
|---|---|---|
| R1 | The entry field `s` means **synthetic** (`true` for entries created on the target with no source). It does not mean "size". Size is `b`. | Old `build_package.py:372-373, 659` |
| R2 | F2 holds exactly **17 symlinks**: 4 inside `/Library/Frameworks/Python.framework` (`Headers`, `Python`, `Resources`, `Versions/Current`) and 13 in `/usr/local/bin`. It also holds 3 directory entries. | `ls -l` on this host; old `F2_SYMLINK_PATHS` |
| R3 | The editable references sit in **both** Python trees. The framework `site-packages` holds `fubotv_mcp_common` and `student_agent_mcp`. The user site holds `fubotv_mcp_common`. D7 is applied to both components (exact names in §7). | `ls` of both `site-packages` dirs |
| R4 | `__pycache__`, `.git`, `.pytest_cache`, `.mypy_cache` and `.ruff_cache` directories are pruned in **every** tree component, and `.DS_Store` files are skipped everywhere. The brief's sizes (vLLM 1.61, framework 2.00, user site 1.42, ltx venv 0.36 GiB) are reproduced only with `__pycache__` pruned. | Measured 2026-09-25, §7 |
| R5 | **All four** HF repos are pinned to their current `refs/main` snapshot, not only Qwen3-VL-32B. | `refs/main` on this host, §7 |
| R6 | Falconsai source lookup order: `~/hf_home/hub` first, then `/Volumes/Ollama/hf_home/hub`. The first location holding the repo wins, and the choice is recorded in `source-host.json`. Today only the USB holds it. | `ls` of both hubs |
| R7 | The L2 `sk-…` patterns, which the brief elided, are defined in §8.2 with a left boundary to limit false positives. The other L2 patterns are the brief's, verbatim. | §8.2 |
| R8 | Shared code (L1/L2 scanning, entry I/O, hashing, `CheckResult`) lives in `build_pkg.py`. `install_pkg.py` loads it from its own directory. Both files ship. | §5.2 |
| R9 | There is no `BUILD-STATE.json`. Resume state is the partial JSONL alone (§11.3). | Simpler than the old advisory state file |
| R10 | README commands use the absolute framework interpreter `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, never bare `python3`. | Removes PATH ambiguity on the target |
| R11 | Functional import probes (framework+user site, vLLM venv, ltx-2-mlx CLI) run in `accept`, not in the copy phases. | §13 |
| R12 | For every file entry, `accept` checks size and mtime of **all** installed files, not a sample (cheap). `verify` does the full re-hash. | §12.5, §13 |

## 4. Preconditions

### P0 — B17 cannot pass today (blocks the build)

The brief said B17 "is satisfiable today". It is not. On 2026-09-25 at HEAD 8043a09, 4 of the 10 pipeline files fail:

| File | State | What the uncommitted change does |
|---|---|---|
| `bin/story-server` | **untracked** (627 lines, never committed) | The whole file |
| `ltx2_mlx_video_skill.py` | modified (+19/−3) | Adds `LTX2_MLX_HF_HOME` (default `~/ltx-2-mlx/hf_cache`) and scopes the render subprocess's `HF_HOME` to it |
| `z_image_skill.py` | modified (+32/−5) | Adds `Z_IMAGE_HF_HOME` (default `~/hf_home`) and per-model `cache_dir`. It also replaces the docstring line about content_safety screening with "Explicit content IS allowed." while still calling `content_safety.assert_image_safe` |
| `bin/qwen-agent` | modified (+2/−4) | **Adds `bash`, `generate_image`, `run_python`, `write_file` to `AUTO_APPROVE_TOOLS`**, which contradicts the comment directly above it ("Never add bash or run_python here"). It also deletes the content_safety NOTE from the image confirmation body |

The redesign plan's rule G8 deliberately left these hunks uncommitted. The hardware gate ran with the working-tree versions. The build stays blocked until the user decides what to commit (open question OQ1). The spec does not change B17 to fit the tree.

### P1 — The L2 allowlist needs a human review before the first build

A dry scan on 2026-09-25 of every §7 source file ≤ 4 MiB (152,559 files, with §8.2's patterns) found **64 (file, pattern) hits across 63 files**. `botocore/data/iam/2010-05-08/examples-1.json` hits two patterns. The allowlist therefore needs 64 tuples:

| Pattern | Files | Where (examples) |
|---|---|---|
| `private_key` | 49 | PyCryptodome, `ecdsa`, `tornado`, `rsa`, `google-auth` and `cryptography` test keys and code, `googleapiclient` discovery docs, and 4 `cv2/.dylibs` libraries |
| `aws_access_key_id` | 9 | e.g. `botocore`/`boto3` example docs, `PIL/ImageFont.py` (in both Python trees), `cv2/.dylibs/libunistring` |
| `hf_token` | 4 | e.g. `transformers/testing_utils.py`, `django_extensions` RECORD |
| `openai_api_key` | 2 | `litellm/proxy/_super_secret_config.yaml`, `diffusers` RECORD |

The build fails B13 until each hit is either reviewed into `scripts/deploy/credential_allowlist.json` (via `--credential-report`, §8.2) or removed from the source tree. Nothing is auto-allowlisted.

### P2 — Target prerequisites (the package does not provide these; installing them needs network)

1. A local account `reubenpatterson` with home `/Users/reubenpatterson`, on macOS ≥ 26, Apple Silicon, ≥ 48 GiB RAM.
2. Homebrew at `/opt/homebrew`. Installing it also installs the Command Line Tools, which `/usr/bin/python3` needs on a fresh Mac.
3. `brew install ffmpeg python@3.12`. ffmpeg/ffprobe must be major version 9, and `/opt/homebrew/opt/python@3.12/bin/python3.12` must report 3.12.x. It is the vLLM venv's base interpreter.
4. `~/.zshenv` contains `export HF_HOME="/Users/reubenpatterson/hf_home"` and no `HF_HOME` line that mentions `/Volumes/`.
5. A real Terminal session that can `sudo`, for the `system-python` phase.

## 5. Architecture

### 5.1 Files (all new)

| Path | Purpose |
|---|---|
| `scripts/deploy/build_pkg.py` | Build, dry-run, verify-only and credential-report on the source host. Also holds the shared helpers (R8). |
| `scripts/deploy/install_pkg.py` | Installer phases on the target. |
| `scripts/deploy/credential_allowlist.json` | The human-reviewed L2 allowlist (§8.2). It starts as `{"schema_version": 1, "entries": []}`. |
| `tests/test_deploy_pkg.py` | Unit tests (§15). |
| `tests/mutate_deploy_pkg.py` | Mutation harness (§15.3). |

No existing file is modified. The deleted 152-method `tests/test_deploy_package.py` is not revived.

### 5.2 Language level and dependencies

- Stdlib only. Both scripts are written at the **Python 3.9 language level**:
  - no `match`;
  - no PEP 604 `X | Y` in runtime-evaluated annotations;
  - no `zip(strict=)`, `int.bit_count`, `datetime.UTC` or `tomllib`;
  - no parenthesized multi-item `with`.
- `build_pkg.py` runs under `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`. `install_pkg.py` runs under `/usr/bin/python3` (3.9.6).
- `install_pkg.py` loads the shared helpers with `importlib.util.spec_from_file_location("build_pkg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_pkg.py"))`.
- Importing `build_pkg.py` has no side effects. All work happens in `main()` under `if __name__ == "__main__":`.

### 5.3 Paths, constants and hooks (testability)

Paths under the home directory are computed **at call time**:
- `home()` returns `os.path.expanduser("~")`;
- `workspace()` returns `home() + "/local_model_harness/qwen-agent-workspace"`;
- `repo_root()` returns `home() + "/local_model_harness"`.

Absolute paths outside the home directory are module-level constants, read at call time and never captured in default arguments or closures:

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

Derived at call time: `framework_py()` = `FRAMEWORK_ROOT + "/Versions/3.13/bin/python3"`, and `ltx25_model_path()` = `home() + "/ltx-2-mlx/models/ltx-2.5-mlx-q8"`.

Every real external probe goes through a module-level dict `HOOKS`. Tests replace its entries with `unittest.mock.patch.dict`:

| Hook | Real behaviour |
|---|---|
| `run(argv, timeout=120, env=None, cwd=None)` | `subprocess.run`. Stdout and stderr are combined and decoded as UTF-8 with `errors="replace"`. Returns `(rc, text)`. A timeout returns `(124, text_so_far)`. |
| `ismount(path)` | `os.path.ismount` |
| `diskutil_personality(path)` | The `File System Personality:` line of `/usr/sbin/diskutil info <path>`, or `""` |
| `statvfs_free(path)` | `st.f_bavail * st.f_frsize` |
| `port_free(port)` | Binds `127.0.0.1:port` with `SO_REUSEADDR=0`. True if the bind succeeds. |
| `which(name)` | `shutil.which` on the process `PATH` |
| `geteuid()` | `os.geteuid` |
| `getpwnam(name)` | `pwd.getpwnam` |
| `getuser()` | `getpass.getuser` |
| `now_utc()` | `time.gmtime()` |
| `after_chunk(src, nbytes)` | No-op. Called after each chunk is copied (lets tests mutate a source mid-copy). |
| `after_entry(index)` | No-op. Called after each entry line is appended to the partial JSONL (lets tests interrupt). |
| `http_ok(url)` | `urllib.request.urlopen(url, timeout=10)`. Returns True on status 200, False on any error. |
| `sleep(s)` | `time.sleep` |

In `build_pkg.py`, `HOOKS["run"]` is wrapped by `_run()`. `_run()` raises `RPreViolation(argv[0])` when `CTX_STATE["payload_started"]` is True (§9).

`CheckResult = collections.namedtuple("CheckResult", "check_id ok message fatal")`. Every check returns one. All checks in a phase run; none short-circuits. Each prints on its own line as one of:
- `PASS <id> <message>`;
- `FAIL <id> <message>` (a fatal failure);
- `WARN <id> <message>` (a non-fatal failure);
- `PENDING <id> <message>` (only I20 in preflight, §12.3).

## 6. Package layout and formats

### 6.1 Layout

```
<usb_root>/ltx-chain-deploy-<YYYYMMDD>/          # usb_root default /Volumes/Ollama
  README.md
  MANIFEST-ENTRIES.jsonl                          # MANIFEST-ENTRIES.jsonl.partial while building
  manifests/
    source-host.json
    pip-freeze-framework-py313.txt
    pip-freeze-ltx2mlx-venv.txt
    pip-freeze-vllm-venv.txt
    source-git.json
    acceptance-baseline.json
    credential-scan.json
  scripts/deploy/
    build_pkg.py
    install_pkg.py
    credential_allowlist.json
  payload/<id>-<slug>/...                         # one directory per non-synthetic, non-F2 component
  MANIFEST.json                                   # written LAST; its presence = build complete
  BUILD-FAILED.json                               # only after a post-copy failure; never alongside MANIFEST.json
```

Package id:
- The default is `ltx-chain-deploy-` plus the local date `YYYYMMDD` at build start.
- `--package-id` overrides it and must match `^ltx-chain-deploy-[0-9]{8}$`.

"Root files" are every file above except `payload/`, `MANIFEST.json`, `MANIFEST-ENTRIES.jsonl(.partial)` and `BUILD-FAILED.json`.

### 6.2 `MANIFEST-ENTRIES.jsonl` (schema 4)

One JSON object per line, UTF-8, separators `(",", ":")`. Keys are written in the order `k, c, p, t, b, m, h, mt, l, s`, and only the keys that apply to the entry are present:

| Key | Meaning | Present for |
|---|---|---|
| `k` | kind: `"f"` file, `"l"` symlink, `"d"` directory | all |
| `c` | component id (e.g. `"B4"`) | all |
| `p` | payload path relative to the package root, e.g. `"payload/B4-ltx25-mlx-q8/vocoder.safetensors"`. A tree's root directory entry has `p` = `payload/<id>-<slug>`. | non-synthetic entries of payload components |
| `t` | absolute target path on the target Mac | all |
| `b` | size in bytes | `f` |
| `m` | mode, 4-digit octal string (`"0644"`) | `f`, `d` |
| `h` | sha256 hex of the content | `f` |
| `mt` | source `st_mtime_ns` (int) | `f` |
| `l` | symlink value, verbatim from `os.readlink` (relative values stay relative) | `l` |
| `s` | `true` = synthetic (R1) | synthetic entries only |

Global order:
1. component order as in §7's table;
2. within a component, entries with `p` sorted by `p`, followed by entries without `p` sorted by `t`.

Schema 4 is deliberately different from the old system's 3, so each installer refuses the other's packages.

### 6.3 `MANIFEST.json`

```json
{
  "schema_version": 4,
  "package_id": "ltx-chain-deploy-20260925",
  "created_at": "2026-09-25T09:00:00Z",
  "entries_file": "MANIFEST-ENTRIES.jsonl",
  "entries_sha256": "<hex>",
  "entries_count": 0,
  "totals": {"files": 0, "symlinks": 0, "dirs": 0, "bytes": 0},
  "components": {"A1": {"slug": "workspace-code", "files": 0, "symlinks": 0, "dirs": 0, "bytes": 0}},
  "root_files": {"README.md": "<sha256>", "manifests/source-host.json": "<sha256>"},
  "source_git_head": "<40-hex>",
  "models": {
    "video_model_path": "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8",
    "vision_model_snapshot": "5428d6aaca0103a1e32f47261a20fecaa47700ec",
    "vision_model_symlink": "/Users/reubenpatterson/mlx_models/qwen3-vl"
  },
  "credential_scan": {"l1": "clean", "l2_allowlisted": 0, "l3_values_loaded": 0, "l4": "clean"},
  "build": {"started_at": "<iso>", "finished_at": "<iso>", "resumed": false}
}
```

`root_files` lists every root file (§6.1) with its sha256. `components` includes every component id in §7, including the synthetic ones and F2.

### 6.4 `manifests/*`

**`source-host.json`**: gathered live before copying, through `_run` with a 120 s timeout. Any rc ≠ 0 fails B16.

| Key | Source |
|---|---|
| `hw_model` | `/usr/sbin/sysctl -n hw.model` |
| `cpu` | `/usr/sbin/sysctl -n machdep.cpu.brand_string` |
| `memsize` | `/usr/sbin/sysctl -n hw.memsize` (int) |
| `product_version`, `build_version` | `/usr/bin/sw_vers -productVersion` and `-buildVersion` |
| `machine` | `platform.machine()` |
| `framework_python_version` | `framework_py() -c "import sys;print(sys.version.split()[0])"` |
| `ffmpeg_version`, `ffprobe_version` | first line of `<which ffmpeg> -version`, `<which ffprobe> -version` |
| `brew_version` | first line of `BREW_BIN --version` |
| `brew_python312_version` | `BREW_PY312 --version` |
| `vllm_version` | first line of `~/.venv-vllm-metal/bin/python -c "import vllm; print(vllm.__version__)"` |
| `falconsai_source_hub` | whichever hub R6 selected |
| `gathered_at` | UTC ISO-8601 |

**Pip freezes** (timeout 300 s, rc ≠ 0 fails B16):
- `pip-freeze-framework-py313.txt`: `framework_py() -m pip freeze --all --exclude fubotv-mcp-common --exclude student-agent-mcp`
- `pip-freeze-ltx2mlx-venv.txt`: `FRAMEWORK_ROOT/Versions/3.13/bin/uv pip freeze --python ~/ltx-2-mlx/.venv/bin/python`. The ltx venv has no pip, so `uv` is used.
- `pip-freeze-vllm-venv.txt`: `~/.venv-vllm-metal/bin/python -m pip freeze --all`

**`source-git.json`** (B17's record):
```json
{"head": "<sha>", "branch": "<name>",
 "porcelain": ["<lines of git status --porcelain -- qwen-agent-workspace>"],
 "pipeline_files": {"bin/ltx-movie": {"sha256": "<hex>", "git_blob": "<hex>", "clean": true}},
 "test_files": {"tests/test_ltx_image_fit.py": {"sha256": "<hex>", "git_blob": "<hex>", "clean": true}}}
```
`pipeline_files` has the 10 pipeline files. `test_files` has the 7 test files and is informational only; B17 does not gate on it.

**`acceptance-baseline.json`**: measured before copying (§9):
```json
{"schema_version": 1, "measured_at": "<iso>", "interpreter": "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
 "cwd": "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace",
 "gates": [{"id": "G1", "argv": ["tests/test_ltx_movie_offline.py"], "rc": 0, "last_line": "OK n/n"}],
 "extras": [{"id": "X1", "argv": ["bin/ltx-mlx-render", "--help"], "rc": 0},
            {"id": "X2", "argv": ["bin/ltx-movie", "a test narrative", "--story-id", "deploy-gate-dry", "--dry-run", "--no-review", "--model", "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"], "rc": 0, "brace_lines": 0}]}
```

**`credential-scan.json`**: paths, patterns and hashes only. It never holds secret content, secret hashes or secret lengths.
```json
{"l1_names": ["<every L1_NAMES member, sorted>"],
 "l2_patterns": {"<pattern id>": "<pattern .pattern decoded as latin-1>"},
 "l2_max_bytes": 4194304,
 "l2_allowlisted_hits": [{"component": "F1", "relpath": "...", "sha256": "...", "pattern": "private_key"}],
 "l3_sources": [{"source": "/Users/reubenpatterson/.cache/huggingface/token", "present": true, "values": 1},
                {"source": "$HF_TOKEN", "present": false, "values": 0}]}
```

### 6.5 `BUILD-FAILED.json`

`{"schema_version": 4, "package_id": "...", "failed_step": "PC4", "error_type": "<exception class name>", "error": "<str(exc)>", "created_at": "<iso>"}`. It is written atomically. It is written only by the post-copy handler (§9).

## 7. Components

`H` = `/Users/reubenpatterson` = `home()`. Sizes are apparent bytes measured on 2026-09-25 under R4's pruning rules. The build re-measures them. SC3's tolerance applies to these numbers.

| Id | Slug | Kind | Source | Target | Excludes / notes | Measured |
|---|---|---|---|---|---|---|
| A1 | `workspace-code` | filelist | `WS/<rel>` for the 17 files below | same | Explicit list only (D8) | 715,917 B (17 files) |
| A2 | `hw-gate-seeds` | filelist | `WS/generated/hw_gate_seeds/{portrait,wide3x1,square}.png` | same | Acceptance-run inputs | 1,616,096 B (3 files) |
| B1 | `ltx2mlx-repo` | tree | `H/ltx-2-mlx` | same | Top-level `models`, `hf_cache`, `converted_models`, `source_caches`, `.venv`, `.claude`, `.git`. Needed because the venv's editable installs point into `packages/`. | 7,620,820 B (0.01 GiB; the brief said ~0.03) |
| B2 | `ltx2mlx-venv` | tree | `H/ltx-2-mlx/.venv` | same | — | 382,091,499 B (0.36 GiB) |
| B3 | `uv-cpython311` | tree | `H/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none` | same | B2's base interpreter | 50,325,472 B (0.05 GiB) |
| B4 | `ltx25-mlx-q8` | tree | `H/ltx-2-mlx/models/ltx-2.5-mlx-q8` | same | Excludes `.cache`. File set pinned (B04). The only video model shipped. | 74,718,758,789 B (69.59 GiB, 28 files) |
| B5 | `ltx2mlx-hf-cache-dirs` | synthetic dirs | — | `H/ltx-2-mlx/hf_cache`, `H/ltx-2-mlx/hf_cache/hub` (0755) | Empty scoped HF_HOME for the render subprocess. Its `token` and Gemma cache are never shipped. | 0 |
| D1 | `vllm-venv` | tree | `H/.venv-vllm-metal` | same | Base is `/opt/homebrew/opt/python@3.12/bin` (a P2 prerequisite) | 1,724,423,499 B (1.61 GiB) |
| F1 | `framework-python` | tree | `FRAMEWORK_ROOT/Versions/3.13` | same | Excludes `lib/python3.13/site-packages/` members: `__editable___fubotv_mcp_common_0_1_0_finder.py`, `__editable___student_agent_mcp_1_0_0_finder.py`, `__editable__.fubotv_mcp_common-0.1.0.pth`, `__editable__.student_agent_mcp-1.0.0.pth`, `fubotv_mcp_common-0.1.0.dist-info`, `student_agent_mcp-1.0.0.dist-info`. Also excludes the top-level console-script entry point `bin/student-agent-mcp` (installed by the `student_agent_mcp` package's own RECORD, outside `site-packages/` — missed in the first draft of this table, found and fixed during Task 2's review by checking the real host filesystem). Contains psutil, pytest, pexpect. Root-owned (system-python phase). | 2,148,085,949 B (2.00 GiB) |
| F2 | `framework-symlinks` | enumerated | the 20 paths below, read live with `os.lstat` / `os.readlink` | same | No payload; recreated from `l` / `m`. Root phase. | 0 |
| F3 | `user-site` | tree | `H/Library/Python/3.13` | same | Excludes `lib/python/site-packages/` members: `__editable___fubotv_mcp_common_0_1_0_finder.py`, `__editable__.fubotv_mcp_common-0.1.0.pth`, `fubotv_mcp_common-0.1.0.dist-info`. Contains torch, diffusers, transformers, PIL, numpy. | 1,524,525,421 B (1.42 GiB) |
| H0 | `hf-home-dirs` | synthetic dirs | — | `H/hf_home`, `H/hf_home/hub` (0755) | — | 0 |
| H1 | `hf-zimage` | tree | `H/hf_home/hub/models--Tongyi-MAI--Z-Image-Turbo` | same | Pin `f332072aa78be7aecdf3ee76d5c247082da564a6`. Stills model. | 32,848,312,686 B (30.59 GiB) |
| H2 | `hf-zimage-te` | tree | `H/hf_home/hub/models--BennyDaBall--Qwen3-4b-Z-Image-Turbo-AbliteratedV1` | same | Pin `ce497d288a7ddfd5d0f337c7139349d5d0236bfa`. z_image text encoder. | 8,044,983,783 B (7.49 GiB) |
| H3 | `hf-nsfw` | tree | `models--Falconsai--nsfw_image_detection` under the R6 hub (today `FALCONSAI_USB_HUB`) | `H/hf_home/hub/models--Falconsai--nsfw_image_detection` | Pin `96cb0d0342c7afb80cab76ecc58b265fa44da256`. `content_safety.py` loads it through the global `HF_HOME`, and on this host tonight's gate runs read it off the USB. | 343,225,057 B (0.32 GiB) |
| H4 | `hf-qwen3vl32b` | tree | `H/hf_home/hub/models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx` | same | Pin `5428d6aaca0103a1e32f47261a20fecaa47700ec`. Vision story model. | 19,632,160,689 B (18.28 GiB) |
| H5 | `mlx-models-link` | synthetic | — | d `H/mlx_models` (0755); l `H/mlx_models/qwen3-vl` → `H/hf_home/hub/models--divinetribe--Huihui-Qwen3-VL-32B-Instruct-abliterated-4bit-mlx/snapshots/5428d6aaca0103a1e32f47261a20fecaa47700ec` | `bin/story-server`'s default `VISION_MODEL_DIR` | 0 |
| | | | | | **Total** | **141,426,845,677 B (131.71 GiB)** |

**A1's 17 files (exact):**
- the 10 pipeline files: `z_image_skill.py`, `ltx2_mlx_video_skill.py`, `ltx_image_fit.py`, `content_safety.py`, `bin/ltx-movie`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/story-server`, `bin/qwen-agent`;
- the 7 test files: `tests/test_ltx_movie_offline.py`, `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_images.py`, `tests/test_ltx2_mlx_video_skill.py`, `tests/test_ltx_image_fit.py`, `tests/test_ltx_story_manifest_chain.py`, `tests/check_ltx2_mlx_no_forbidden_imports.py`.

A1 also emits `d` entries, with their source modes, for:
- `WS` (`p` = `payload/A1-workspace-code`);
- `WS/bin` (`p` = `payload/A1-workspace-code/bin`);
- `WS/tests` (`p` = `payload/A1-workspace-code/tests`).

A2 emits one `d` entry for `WS/generated/hw_gate_seeds` (`p` = `payload/A2-hw-gate-seeds`). File payload paths are `payload/A1-workspace-code/<rel>` and `payload/A2-hw-gate-seeds/<basename>`.

These legacy files are **never** shipped, even though they still exist in the tree: `ltx_video_skill.py`, `mps_guard.py`, `flux_skill.py`, `bin/ltx-chain`, `bin/ltx-generate`, `bin/ltx-host-prep`, `bin/ltx-host-restore`, `bin/ltx-story-video`, `bin/pad-images`, `start_vllm.sh`.

**F2's 20 entries (exact):**
- 3 `d` entries: `FRAMEWORK_ROOT`, `FRAMEWORK_ROOT/Versions`, `USR_LOCAL_BIN`.
- 4 `l` entries: `FRAMEWORK_ROOT/{Headers,Python,Resources}` and `FRAMEWORK_ROOT/Versions/Current`.
- 13 `l` entries under `USR_LOCAL_BIN`: `idle3`, `idle3.13`, `pip3`, `pip3.13`, `pydoc3`, `pydoc3.13`, `python3`, `python3-config`, `python3-intel64`, `python3.13`, `python3.13-config`, `python3.13-intel64`, `python`.

Each must be a symlink (or directory, for the 3 `d` entries) on the source, or B03 fails.

**B4's 28 pinned names (`LTX25_PACK_FILES`):** `.gitattributes`, `LICENSE`, `README.md`, `audio_vae.safetensors`, `chat_template.jinja`, `connector.safetensors`, `duration_head.safetensors`, `embedded_config.json`, `generation_config.json`, `ltx-2.5-22b-distilled-lora-450-bf16.safetensors`, `processor_config.json`, `quantize_config.json`, `spatial_upscaler_x2_v1_0.safetensors`, `spatial_upscaler_x2_v1_0_config.json`, `split_model.json`, `temporal_upscaler_x2_v1_0.safetensors`, `temporal_upscaler_x2_v1_0_config.json`, `text_encoder.safetensors`, `text_encoder_config.json`, `tokenizer.json`, `tokenizer_config.json`, `transformer-dev.safetensors`, `transformer-distilled.safetensors`, `vae_decoder_av.safetensors`, `vae_decoder_conv.safetensors`, `vae_encoder_av.safetensors`, `vae_encoder_conv.safetensors`, `vocoder.safetensors`.

**Tree enumeration rules (all tree components):**
- Walk with sorted `os.listdir`.
- Skip `.DS_Store`.
- Prune the R4 directory names.
- Apply `excludes` against the component-relative path.
- Directories give `d` entries with `m`. Symlinks give `l` entries and are never followed. Regular files give `f` entries with `b`, `m` and `mt`.
- Any other file type (fifo, socket, device), or any unreadable file (`os.access(path, os.R_OK)` false), fails B03 and names the path.
- The tree root is the component's first `d` entry.

**Explicitly excluded groups:**
- MTPLX / text mode: `~/.mtplx/**`, `Youssofal/Qwen3.6-27B-MTPLX-Optimized-Speed-V2`, `thermalforge` (D3).
- Huihui-27B / qwen-serve-guard: `models--ailexleon--Huihui-Qwen3.8-27B-abliterated-mlx-6Bit`, `~/mlx_models/Huihui-Qwen3.8-27B-abliterated-mlx-6bit`, `~/.local/bin/qwen-serve-guard`, the LaunchAgent plist, and `WS/qwen38-6bit` (D4).

## 8. Credential gate (four fail-closed layers, all before or during the copy)

### 8.1 L1 — name check (during enumeration)

```python
L1_NAMES = frozenset(["token", "stored_tokens", ".netrc", ".git-credentials", ".pypirc", ".env", "credentials", "id_rsa", "id_ecdsa", "id_ed25519", "id_dsa"])
```

- Any regular file or symlink whose **exact** basename (case-sensitive) is in `L1_NAMES` fails B12.
- The build aborts and names the path. There is no allowlist: a hit means a component root is wrong.
- Directories are not checked. `tokenizer.json` and `credentials.py` do not match.
- A 2026-09-25 dry scan of every §7 source found 0 L1 hits.

### 8.2 L2 — content patterns (pre-copy, sources)

```python
L2_PATTERNS = (
    ("hf_token", re.compile(rb"hf_[A-Za-z0-9]{34,40}")),
    ("private_key", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key_id", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}")),
    ("anthropic_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{32,}")),
    ("openai_api_key", re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
)
```

**Scope.** Every `f` entry with `b ≤ L2_MAX_BYTES` is read whole from its source. Every pattern is checked with `.search`. One hit is recorded per (file, pattern), and matched bytes are never printed, logged or stored.

**Allowlist.** Each hit is checked with this exact function:
```python
def is_allowlisted(allow, component, relpath, sha256, pattern_id):
    return (component, relpath, sha256, pattern_id) in allow
```
- `allow` is a `set` of 4-tuples loaded from `scripts/deploy/credential_allowlist.json`: `{"schema_version": 1, "entries": [{"component", "relpath", "sha256", "pattern", "note"}]}`.
- `relpath` is component-relative. For A1 it is the `WS`-relative path, and for A2 it is the basename.
- `note` must be a non-empty string, or the allowlist fails to load and B13 fails.
- Any hit that is not allowlisted fails B13 **before any payload byte is written**.
- Allowlist entries that match no hit are printed as `WARN B13 stale allowlist entry <json of the entry>` and are not fatal.

**`--credential-report`:**
- Runs enumeration, L1 and L2 only, and writes nothing.
- Prints one line per L1 hit: `L1 <source path>`.
- Prints one line per L2 hit: `L2 NEW <json>` or `L2 ALLOWLISTED <json>`, where `<json>` is `json.dumps({"component": c, "relpath": r, "sha256": h, "pattern": pid, "note": ""}, separators=(", ", ": "))`.
- Prints `STALE <json>` for each stale entry.
- Exits 0 if there are no L1 hits and no NEW hits, else 1.

The human reviews each NEW line, writes a `note`, and pastes the line into the allowlist file. Nothing is allowlisted automatically.

The scripts' own source must not match any L2 pattern with an empty allowlist (T16). The pattern literals above satisfy this.

### 8.3 L3 — known-secret scan (during the copy, D10)

**Secret sources.** These are loaded into memory before any write and are never written, logged, hashed into output or measured into output:

| Source | Values extracted |
|---|---|
| `home()/.cache/huggingface/token` | whole content, `.strip()` |
| `home()/.cache/huggingface/stored_tokens` | parsed with `configparser`: the `.strip()`ed value of every key named `hf_token` or `refresh_token` in every section |
| `home()/ltx-2-mlx/hf_cache/token` | whole content, `.strip()` |
| `$HF_TOKEN` | `.strip()` |
| `$HF_HOME/token` (only when `$HF_HOME` is set and non-empty) | as `home()/.cache/huggingface/token` |
| `$HF_HOME/stored_tokens` (only when `$HF_HOME` is set and non-empty) | as `home()/.cache/huggingface/stored_tokens` |
| `home()/hf_home/token` | as `home()/.cache/huggingface/token` |
| `home()/hf_home/stored_tokens` | as `home()/.cache/huggingface/stored_tokens` |
| `<d>/token`, then `<d>/stored_tokens`, for each `<d>` in `sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home")))` | `token`: as `home()/.cache/huggingface/token`; `stored_tokens`: as `home()/.cache/huggingface/stored_tokens` |
| the file named by `$HF_TOKEN_PATH` (only when `$HF_TOKEN_PATH` is set and non-empty) | as `home()/.cache/huggingface/token` |
| `$HUGGING_FACE_HUB_TOKEN` | `.strip()` |

**Loading rules.**
- Values are UTF-8 encoded to bytes and de-duplicated. Empty values are ignored.
- Absent sources are allowed and recorded as `present: false`.
- B14 fails if any value is non-empty but shorter than 16 bytes ("too short to scan safely").
- B14 also fails if any `stored_tokens` source exists but cannot be parsed, or yields no `hf_token` or `refresh_token` values.
- Sources are loaded, and recorded in `sources`, in the table's order. `$HF_HOME` and `$HF_TOKEN_PATH` are expanded the way `huggingface_hub` expands them: `os.path.expandvars(os.path.expanduser(value))`. Every file path goes through `os.path.normpath`, and the normalized path is that source's label.
- A file path already loaded earlier in the order is skipped and gets no second `sources` entry. On this host `$HF_HOME` is `/Volumes/Ollama/hf_home`, which the `VOLUMES_ROOT/*/hf_home` glob also matches, so that directory is listed once, at the `$HF_HOME` rows.
- Exception to the `present: false` rule: when `$HF_HOME` or `$HF_TOKEN_PATH` is unset or empty, its rows produce no `sources` entry at all.

On this host both `token` files are 825-byte single-line values that begin with `hf_` but do **not** match the L2 `hf_token` pattern. That is exactly the leak class L3 exists for.

`~/.zshenv` sets `HF_HOME=/Volumes/Ollama/hf_home` on this host, and a `token` and a `stored_tokens` live there too. At the design review of commit `3bc3af5` they were byte-identical to the `~/.cache/huggingface` copies (compared with `cmp -s`, contents never read). That was the only reason the first four sources were enough. The copies diverge on the next `hf auth login`, so L3 also reads `$HF_HOME`, the fixed `~/hf_home`, every mounted volume's `hf_home`, `$HF_TOKEN_PATH` and `$HUGGING_FACE_HUB_TOKEN`.

**Scanner (exact):**
```python
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

A new scanner is created for every byte stream. Every byte the build writes into the package root passes through one: payload files chunk by chunk, root files, MANIFEST-ENTRIES lines, `MANIFEST.json` and `BUILD-FAILED.json`.

**On a hit** (in a payload file):
1. Close both file descriptors.
2. `os.unlink` the partial destination.
3. Flush and fsync the partial JSONL. The entry is not listed.
4. Raise `CredentialLeak("L3: a known secret value was found in <source path>; the partial payload file was deleted and no MANIFEST.json was written")`.

`main()` maps this to exit 5. For a root file the path in the message is the package-relative name.

### 8.4 L4 — whole-package rescan (post-copy, before MANIFEST.json)

L4 runs L1 and L2 over **every** file and symlink under the package root: `payload/`, `manifests/`, `scripts/deploy/`, `README.md` and `MANIFEST-ENTRIES.jsonl`.

- Payload files use allowlist keys `(component, relpath)` derived from `payload/<id>-<slug>/<relpath>`.
- Every other file uses `("ROOT", <package-relative path>)`.
- Any `.DS_Store` under the package root is an L4 failure.
- A failure raises inside the post-copy handler, which gives exit 3 and `BUILD-FAILED.json` (§9).

`--verify-only` reruns L1+L2 over the whole package. The installer reruns L1+L2 over the payload and root files in preflight (I08), and does so before it copies anything.

## 9. Rule R-PRE (the SPEC_PATH-crash fix) and build stage order

**Background.** The old build read `SPEC_PATH` (a spec file that had since been deleted) to write the acceptance baseline **after** a ~215 GiB copy. It crashed uncaught mid-build and never wrote `MANIFEST.json`.

**R-PRE.** Once the first payload byte has been written, the build process opens no file outside the package root, except the source files it is actively copying. It also runs no subprocess.

Enforcement:
- `CTX_STATE["payload_started"] = True` is set immediately before the first payload write, and `_run()` raises `RPreViolation` when it is set.
- T21 patches `builtins.open` / `os.open` to raise for any path outside the package root that is not an entry source.

**`--apply` stage order (exact):**
1. Parse the arguments and compute `package_root = <usb_root>/<package_id>`.
2. `load_known_secrets()` (B14).
3. `enumerate_components()`, with L1 applied inline (B12).
4. `run_prebuild_checks(ctx)` evaluates B01-B17 in table order. B12 and B14 report the results already computed in steps 2-3. It contains the exact line `    results.append(check_offline_gates(ctx))`, which runs the gates and sets `ctx.baseline`. It also gathers host facts, freezes and the git record into memory, and runs L2.
5. If any fatal check fails: print everything, exit 4. **The package root is never created.**
6. Create the package root (or open it for `--resume`). Delete a stale `BUILD-FAILED.json` if resuming.
7. `write_root_files(ctx)` writes README.md, `manifests/*` and `scripts/deploy/*` from in-memory bytes. Each write goes to a temp name `.<name>.tmp`, is L3-scanned, then fsync'd and `os.replace`d. Its sha256 is recorded in `ctx.root_files`. The scripts and the allowlist file were read into memory during step 4.
8. `    copy_payload(ctx)` (exact line) copies every entry in global order (§11). The first payload write sets `payload_started`.
9. `return finish_build(ctx)` runs the post-copy stage, wrapped in `try/except Exception`:
   - **PC1** fsync the partial JSONL, `os.replace` it to `MANIFEST-ENTRIES.jsonl`, fsync the root directory.
   - **PC2** compute `entries_sha256` from the package file.
   - **PC3** A1 consistency: every A1 `f` entry's `h` equals the sha256 recorded in `ctx.git_record` (in memory).
   - **PC4** `    l4_rescan(ctx)` (exact line).
   - **PC5** write `MANIFEST.json`: temp name, L3-scanned, fsync, `os.replace`, fsync the root directory.

   On any exception in PC1-PC5: write `BUILD-FAILED.json` atomically with `failed_step`, make sure `MANIFEST.json` does not exist, print the error, and exit 3.

**Exceptions in steps 6-8** — `SourceChanged`, `CredentialLeak`, `RPreViolation`, I/O errors, and anything raised by the `after_entry` hook: flush and fsync the partial JSONL if it exists, print the error, and exit 5. No `MANIFEST.json` is written. The build can be resumed after the cause is fixed.

**Exceptions in steps 1-5** that are not CheckResults (unexpected errors) print a traceback and exit 1. Nothing is written in these steps.

**Dry run** (`--dry-run`, the default mode) runs steps 1-4 and writes nothing. It prints:
- the per-component lines;
- a TOTAL line;
- required free space against actual free space;
- every CheckResult line;
- a final line: `build_pkg: DRY RUN OK`, or `build_pkg: DRY RUN FAILED (<n> checks)`.

Exit 0 or 4. Per-component line format: `<id> <slug> files=<n> symlinks=<n> dirs=<n> bytes=<n> (<x.xx> GiB)`. TOTAL line format: `TOTAL files=<n> symlinks=<n> dirs=<n> bytes=<n> (<x.xx> GiB)`.

## 10. Build-side checks (all before copying)

| Id | Check (fatal) | Detail |
|---|---|---|
| B01 | USB volume | `HOOKS["ismount"](usb_root)`, and `diskutil_personality` contains both `APFS` and `Case-sensitive`. `/Volumes/Ollama` is "Case-sensitive APFS" today. |
| B02 | Free space | `statvfs_free(usb_root) ≥ remaining_bytes + BUILD_HEADROOM_BYTES`. `remaining_bytes` is total `f` bytes minus the bytes of entries already in a verified resume prefix. |
| B03 | Sources readable and venv pins | Enumeration raised no error (missing root, unreadable file, special file, F2 path of the wrong type). `H/ltx-2-mlx/.venv/pyvenv.cfg` has `home = <B3 source>/bin`. `H/.venv-vllm-metal/pyvenv.cfg` has `home = /opt/homebrew/opt/python@3.12/bin`. |
| B04 | 2.5 pack file set | `set(os.listdir(pack)) - {".cache", ".DS_Store"} == LTX25_PACK_FILES`, and each is a regular file. The message lists `extra=` and `missing=`. |
| B05 | HF repos complete | For each of H1-H4: the repo dir exists; `refs/main` content `.strip()` equals the pin; the `snapshots/` entries (minus `.DS_Store`) are exactly `[pin]`; no path under `blobs/` ends in `.incomplete`; every symlink in the repo resolves (`os.path.realpath`) to an existing regular file under that repo's `blobs/`. |
| B06 | No case-insensitive collisions | Checked separately among `p` values and among `t` values. |
| B07 | Package root state | Without `--resume` the root must not exist. With `--resume` it must exist, must not contain `MANIFEST.json`, and its resume prefix must validate (§11.3). |
| B08 | Synthetic symlink target shipped | H5's `l` equals the `t` of an H4 `d` entry (the pinned snapshot dir). The live `os.readlink(home()+"/mlx_models/qwen3-vl")` on the source equals that same pinned path. |
| B09 | Port 8177 free | `port_free(8177)`. Message: stop the story server before building. |
| B10 | HF scope | Every entry whose **source** lies under `H/hf_home`, `/Volumes/Ollama/hf_home`, `H/.cache/huggingface` or `H/ltx-2-mlx/hf_cache` is inside one of the four pinned repo dirs. Every **target** under `H/hf_home` is an H0 dir or inside a pinned target repo dir. Every target under `H/ltx-2-mlx/hf_cache` is a B5 dir. |
| B11 | Target-path allowlist | Every `t` either starts with `REQUIRED_HOME + "/"`, or equals or starts with `FRAMEWORK_ROOT(+"/")`, or equals or starts with `USR_LOCAL_BIN(+"/")`. No `t` starts with the literal `"/Volumes/"` or `"/opt/homebrew/"`, and these literals are never patched. Also `home() == REQUIRED_HOME`. |
| B12 | L1 | §8.1 |
| B13 | L2 | §8.2 |
| B14 | L3 sources loaded | §8.3 |
| B15 | Offline gates pass | §10.1. Measured now; the result becomes `acceptance-baseline.json`. |
| B16 | Host facts and freezes | Every §6.4 command rc 0. |
| B17 | Provenance (D12) | For each of the 10 pipeline files (`<rp>` = `qwen-agent-workspace/<rel>`): `/usr/bin/git -C REPO ls-files --error-unmatch -- <rp>` rc 0; `git -C REPO status --porcelain -- <rp>` output empty; `git -C REPO hash-object <abs path>` equals `git -C REPO rev-parse HEAD:<rp>`. The message names each failing file and reason (`untracked`, `modified`, `blob differs`). **Fails today; see P0.** |
| B19 | Deploy-script provenance | Runs last, after B18, and does not depend on B17. `os.path.realpath(deploy_dir())` equals `os.path.realpath(workspace() + "/scripts/deploy")`, so the build reads the checkout's scripts, not a stray copy. A symlink into the checkout is accepted; a copy elsewhere, even a byte-identical one, is not. For each file in `DEPLOY_SCRIPT_FILES` (`build_pkg.py`, `install_pkg.py`, `credential_allowlist.json`), with `<rel>` = `scripts/deploy/<name>`, the three B17 commands pass. The message names the `deploy_dir()` mismatch and each failing file with its reason (`untracked`, `modified`, `blob differs`, `missing`). The record (`ctx.deploy_script_record`) is in memory only. **Fails until `scripts/deploy/install_pkg.py` is committed** (reason `missing`). |

### 10.1 Offline gates (B15; also used by accept A4)

Run order: G1-G7, then X1, X2. Each runs as `[framework_py()] + argv`, with `cwd=workspace()`, the inherited environment and `timeout=900`. `last_line` is `text.rstrip().splitlines()[-1]`, or `""` for empty output.

| Id | argv | Pass (build) |
|---|---|---|
| G1 | `tests/test_ltx_movie_offline.py` | rc 0 and `last_line` matches `^OK (\d+)/\1$` |
| G2 | `tests/test_ltx_mlx_render.py` | same |
| G3 | `tests/test_ltx_story_images.py` | same |
| G4 | `tests/test_ltx2_mlx_video_skill.py` | same |
| G5 | `tests/test_ltx_image_fit.py` | same |
| G6 | `tests/test_ltx_story_manifest_chain.py` | same |
| G7 | `tests/check_ltx2_mlx_no_forbidden_imports.py` | rc 0 and `last_line == "RESULT: ok"` |
| X1 | `bin/ltx-mlx-render --help` | rc 0 |
| X2 | `bin/ltx-movie "a test narrative" --story-id deploy-gate-dry --dry-run --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8` | rc 0, and 0 output lines contain `{` or `}`. Verified on 2026-09-25: rc 0, 0 brace lines, nothing written. |

The gates are always run by direct invocation, never through pytest. `test_ltx_movie_offline.py`'s non-raising `check()` makes pytest report false greens.

## 11. Copy engine, resume, verify-only

### 11.1 Per-file copy (`copy_regular_file(src, dst, entry, secrets)`)

1. `before = os.lstat(src)`. If it is not `S_ISREG`, or `(before.st_size, before.st_mtime_ns) != (entry["b"], entry["mt"])`: raise `SourceChanged("source changed since enumeration: <src>")`.
2. `os.makedirs(dirname(dst), exist_ok=True)`. Open `src` `O_RDONLY` and `dst` `O_WRONLY|O_CREAT|O_TRUNC` (0o600). Create a `KnownSecretScanner(secrets)`.
3. Loop:
   - read up to `CHUNK_SIZE`;
   - if the scanner's `feed` hits, run the L3 hit procedure (§8.3);
   - write the chunk and update sha256;
   - call `HOOKS["after_chunk"](src, total)`.
4. `os.fsync(dst_fd)`, then close both descriptors.
5. `after = os.lstat(src)`, then the exact line `    if before_key != after_key:`. The key is `(st_dev, st_ino, st_size, st_mtime_ns)`. On a mismatch: unlink `dst`, raise `SourceChanged("source changed mid-copy: <src>")`.
6. `os.chmod(dst, int(entry["m"], 8))` and `os.utime(dst, ns=(entry["mt"], entry["mt"]))`.
7. If `os.lstat(dst).st_size != entry["b"]`: raise `SourceChanged`. Return the hex digest, which becomes `entry["h"]`.

**Symlink entries with `p`:** unlink any existing `dst`, then `os.symlink(entry["l"], dst)`.
**Directory entries with `p`:** `os.makedirs(dst, exist_ok=True)`. After the last entry of a component, `os.chmod` every `d` entry of that component to `m`.
**Entries without `p`** (synthetic, F2): the build writes nothing to the payload. Only the line is recorded.

After each entry: append its line to `MANIFEST-ENTRIES.jsonl.partial`, then call `HOOKS["after_entry"](index)`. The partial is flushed and fsync'd every 512 entries, at every component end and on abort.

### 11.2 Throughput expectation (informational)

`/Volumes/Ollama` reads at about 60 MB/s (measured 2026-09-14). At that rate a full build copy takes about 40-60 min and `--verify-only` about 40 min. These are not acceptance thresholds.

### 11.3 `--resume`

1. All pre-build checks run again. Root files are regenerated and rewritten (step 7).
2. If `MANIFEST-ENTRIES.jsonl` exists and `.partial` does not (a failure after PC1), rename it back to `.partial`.
3. Truncate `.partial` after its last `\n` (a torn final line).
4. Walk the partial's lines `i = 0…` alongside the fresh enumeration in global order:
   - If the identity `(k, c, p, t, l, s)` of line `i` differs from fresh entry `i`: **fatal B07** "enumeration changed since the interrupted build; delete <package_root> and rebuild".
   - If `(b, m, mt)` differs: **fatal B07** "source changed since the interrupted build: <src>".
   - Otherwise re-verify the payload: `f` re-hashes to `h`; `l` readlink equals `l`; `d` is a directory; entries without `p` always pass. If this fails, truncate the partial to lines `< i` and stop the walk.
5. Continue copying from the first unlisted entry, and remove its payload file first if one exists.

The final `MANIFEST-ENTRIES.jsonl` and payload tree are byte-identical to an uninterrupted build of the same sources (T40). "Byte-identical" covers file bytes, mode and `mtime_ns`, and symlink values. Directory mtimes, `MANIFEST.json`'s `created_at` and `build` fields, and the root files' `gathered_at` / `measured_at` values are excluded.

### 11.4 `--verify-only`

Uses `package_root = <usb_root>/<package_id>` and writes nothing. It fails (exit 1, one `FAIL VERIFY <reason>: <path>` line each) on any of:
- `MANIFEST.json` missing or not schema 4;
- `BUILD-FAILED.json` present;
- `sha256(MANIFEST-ENTRIES.jsonl) != entries_sha256`;
- any `root_files` hash mismatch;
- any `f` payload re-hash mismatch, size mismatch or missing file (read with `F_NOCACHE` where available);
- any `l` payload readlink mismatch;
- any `d` payload dir missing;
- any file or symlink under `payload/` that is not listed (an extra);
- an L1/L2 hit over the whole package root, or a `.DS_Store`.

On success it prints `build_pkg: VERIFY ok: <n> files re-hashed` and exits 0. Pass `--package-id` when verifying a package built on a different date (the default id is today's date).

## 12. Install side

### 12.1 CLI

```
/usr/bin/python3 <pkg>/scripts/deploy/install_pkg.py --phase {preflight,system-python,user,verify,accept}
    [--apply] [--package-root PATH] [--gpu | --gpu-all]
```

- `--package-root` defaults to three levels up from `os.path.abspath(__file__)`, i.e. the package root.
- `--apply` is valid only with `system-python` and `user`; anywhere else it is a usage error (exit 2).
- `--gpu` / `--gpu-all` are valid only with `accept`, and are mutually exclusive.
- There is no `--phase all`.

A root without `payload/` is a **receipts root** (§12.6). Only `verify` and `accept` run from it. `preflight`, `system-python` and `user` fail I06 there.

### 12.2 Phase order and the `--apply` gate

`preflight` (read-only, as the user) → `system-python` (root, `sudo`) → `user` → `verify` → `accept`.

Each phase runs its checks (§12.3, column "Phases"), then:
```python
    if not args.apply:
        print_plan(ctx)
        return EXIT_OK if not fatal_failures else EXIT_REFUSED
    if fatal_failures:  # refuse --apply
        return EXIT_REFUSED
```
- `print_plan` prints, per component: entries to copy, entries identical and skipped, and collisions.
- Read-only phases (`preflight`, `verify`, `accept`) have no `--apply` branch. They exit `EXIT_REFUSED` (4) on any fatal check failure.

### 12.3 Install checks

Phases: P = preflight, S = system-python, U = user, V = verify, A = accept.

| Id | Check | Phases | Fatal |
|---|---|---|---|
| I01 | `sys.version_info >= (3, 9)` | all | yes |
| I02 | `platform.system() == "Darwin"` and `platform.machine() == "arm64"` | P S U | yes |
| I03 | `hw.memsize ≥ 48 GiB`, via exact code: `rc, out = HOOKS["run"](["/usr/sbin/sysctl", "-n", "hw.memsize"])`, `memsize = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1`, then the line `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)`. Message states that the measured peak was 36.61 GiB with the vision model at 0.70 memory utilization, so a 16 GiB Mac cannot run it. | P S U A | yes |
| I04 | `sw_vers -productVersion` major ≥ 26 | P S U | yes |
| I05 | `getpwnam("reubenpatterson").pw_dir == REQUIRED_HOME`. In non-root phases also `getuser() == REQUIRED_USER` and `$HOME == REQUIRED_HOME`. | all | yes |
| I06 | `MANIFEST.json` present with `schema_version == 4`; no `BUILD-FAILED.json`; `sha256(MANIFEST-ENTRIES.jsonl) == entries_sha256`; every `root_files` hash matches; for P S U, `payload/` exists | all | yes |
| I07 | No `.DS_Store` anywhere under the package root. The message lists them and prints `find "<pkg>" -name .DS_Store -delete`. | P S U | yes |
| I08 | L1+L2 rescan of the payload and root files, with the package's allowlist (§8.4 keys) | P S U | yes |
| I09 | `statvfs_free(REQUIRED_HOME) ≥ Σb(f entries whose t does not lexist) + INSTALL_HEADROOM_BYTES` | P S U | yes |
| I10 | Every entry's target is absent or identical (§12.4). For U, the receipts files (§12.6) are included. Collisions are gathered by the exact lines `        same, reason = target_matches_entry(target, entry)`, `        if not same:`, `            collisions.append((target, reason))`. **Every** collision prints as `COLLISION <reason>: <target>`, followed by the count. | P S U | yes |
| I11 | No two manifest targets are equal ignoring case (`t.lower()`) | P S U | yes |
| I12 | `which("ffmpeg")` and `which("ffprobe")` are found; the first lines of `-version` match `^ffmpeg version n?(\d+)\.` / `^ffprobe version n?(\d+)\.` with group 1 = `9` | P U A | yes |
| I13 | `BREW_BIN` exists and is executable | P U | yes |
| I14 | `BREW_PY312 --version` matches `^Python 3\.12\.\d+\s*$` | P U A | yes |
| I15 | `/usr/sbin/lsof` and `/usr/bin/python3` exist and are executable | P U | yes |
| I16 | `port_free(8177)` | P U | yes |
| I17 | `os.environ.get("HF_HOME") == home()+"/hf_home"`; the output of `/bin/zsh -c 'printf "%s" "$HF_HOME"'` is the same; no `~/.zshenv` line matching `^\s*(export\s+)?HF_HOME=` contains `/Volumes/`. On failure it prints the offending line numbers and the exact line to add, `export HF_HOME="/Users/reubenpatterson/hf_home"`. **It never edits dotfiles.** | P U A | yes |
| I18 | `workspace()` is writable: if it exists, it is a writable directory; otherwise its nearest existing ancestor passes `os.access(W_OK)` | P U | yes |
| I19 | S requires `geteuid() == 0` (message: run with `sudo`). Every other phase requires `geteuid() != 0`. | all | yes |
| I20 | `framework_py() -c "import sys;print(sys.version.split()[0])"` outputs `3.13.0`. In P, if `FRAMEWORK_ROOT/Versions/3.13` is absent, the result is `PENDING` (ok) with "run --phase system-python next". | P U V A | yes (except PENDING) |

### 12.4 Target identity and the per-file install procedure

`target_matches_entry(target, entry)` (uses `os.lstat`, never follows links):

| Kind | Identical when | Otherwise reason is |
|---|---|---|
| `f` | a regular file, size = `b`, sha256 = `h` | `not a regular file` / `size differs` / `content differs` |
| `l` | a symlink and `readlink == l` | `not a symlink` / `symlink target differs` |
| `d` | a directory | `not a directory` |

Absent targets (`not os.path.lexists`) are installed. Identical targets are skipped and never touched (inode and mtime unchanged).

**Install a file** (`install_file`):
1. `os.makedirs(dirname(t), exist_ok=True)`. Let `tmp = dirname(t) + "/." + basename(t) + ".ltxdeploy.tmp"`.
2. Copy `payload/<p>` to `tmp` (`O_TRUNC`, 0o600), in `CHUNK_SIZE` chunks, hashing as it goes, then fsync.
3. The exact line `    if digest != entry["h"]:`. On a mismatch: unlink `tmp` and raise `InstallError("sha256 mismatch for <t>")`, which gives exit 1.
4. `os.chmod(tmp, int(m, 8))` and `os.utime(tmp, ns=(mt, mt))`.
5. `os.replace(tmp, t)`.

A killed copy therefore never leaves a partial file under the final name. A leftover `tmp` is overwritten on the next run.

**Symlinks:** `os.symlink(l, tmp)`, then `os.replace(tmp, t)`.

**Directories:** `make_dir` creates every missing directory on the way to a target, top down. A directory that is a `d` entry of any component is created as `.<name>.ltxdeploy.tmp`, `chmod`ed to `m | 0o700`, then renamed into place, so it never appears under its final name with another mode, even when the run is killed. A directory that is not an entry is created with `os.mkdir` and the umask. A directory **created by this run** is `chmod`ed to `m` after the last entry of its component (this changes only a mode that lacks owner `rwx`; none does in the real manifest). Pre-existing directories are never `chmod`ed.

Ownership is never changed. Files written in S are root-owned, and files written in U are owned by the user.

### 12.5 Phases

- **preflight**: all P checks. Writes nothing. Exits 0 or 4.
- **system-python**: S checks. With `--apply`, installs F1 then F2 in manifest order. Post-check: `framework_py() -s -c "import sys, psutil, pytest, pexpect; print(sys.version.split()[0])"` must give rc 0 and first line `3.13.0`, else exit 1 with the last 200 characters of output.
- **user**: U checks. With `--apply`:
  1. installs every component except F1 and F2, in manifest order;
  2. writes receipts (§12.6);
  3. prints `install_pkg: user phase complete: <files> files, <symlinks> symlinks, <bytes> bytes`.
- **verify**: V checks. For every entry:
  - `f`: a regular file, sha256 = `h`, `S_IMODE` = `m`;
  - `l`: `readlink == l`;
  - `d`: a directory with `S_IMODE` = `m` (else `mode differs`). A pre-existing directory whose mode differs is reported too; the installer never changes it (§12.4).

  It prints `MISMATCH <reason>: <t>` for each failure (exit 1), or `VERIFY OK <f> files, <l> symlinks, <d> dirs` (exit 0). It reads targets only and writes nothing, so it can run from a receipts root.
- **accept**: §13.

In any phase, an exception during `--apply` other than a CheckResult failure prints the error and exits 1. This covers `InstallError`, `OSError` and a failed post-check. Files already installed stay in place. A rerun skips them as identical (I10).

### 12.6 Receipts

At the end of `user --apply`, the installer copies these files into `workspace()/generated/deploy-receipts/<package_id>/`, keeping their relative paths:
- `MANIFEST.json`
- `MANIFEST-ENTRIES.jsonl`
- every `root_files` path: README, `manifests/*`, `scripts/deploy/*`

Each copy uses the §12.4 procedure and is checked against `root_files` or `entries_sha256`. `MANIFEST.json` must be byte-identical to the source. `verify` and `accept` can then run from `<receipts>/scripts/deploy/install_pkg.py` with the USB drive ejected.

## 13. Accept phase

`accept` writes `workspace()/generated/deploy-receipts/<package_id>/accept-<YYYYmmddHHMMSS>.json`, which records every step's result. It prints `ACCEPT PASS` (exit 0) or `ACCEPT FAIL` (exit 1). If a GPU precondition refuses, it exits 5.

Steps, in this order:

| Step | What | Pass |
|---|---|---|
| A0 | Checks I01, I03, I05, I06, I12, I14, I17, I19, I20. Port 8177 is checked only for GPU runs (r4). | all pass, else exit 4 |
| A1 | Metadata check of every entry: `f` is a regular file with size = `b` and `st_mtime_ns = mt`; `l` readlink = `l`; `d` is a directory. Runs before anything executes. | no mismatch |
| A2 | Functional probes (timeout 300 s each): (a) `framework_py() -c "import torch, diffusers, transformers, PIL, numpy, safetensors, psutil, pytest, pexpect"` gives rc 0; (b) `home()/.venv-vllm-metal/bin/python -c "import vllm, vllm_metal, mlx_vlm; print(vllm.__version__)"` gives rc 0 and a first line equal to `source-host.json` `vllm_version`; (c) `home()/ltx-2-mlx/.venv/bin/ltx-2-mlx --help` gives rc 0 | all |
| A3 | Offline gates G1-G7, X1, X2 exactly as in §10.1, compared with `acceptance-baseline.json` | every gate: rc and `last_line` **equal** the recorded values; X1 rc equals recorded; X2 rc 0 and `brace_lines == 0` |
| A4 | `workspace()/bin/story-server` with no arguments | rc 2 and the output contains `usage: story-server [vision|text|status|stop]` |
| A5 | GPU runs, only with `--gpu` (portrait) or `--gpu-all` (portrait, wide, square, noseed, in that order) | every run passes c1-c5 |

### 13.1 GPU refusal checks (before any GPU run; any hit → exit 5, nothing started)

The drive check uses the exact line `    for path in sorted(glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))):`.

| # | Refusal condition |
|---|---|
| r1 | Any path in that glob exists (e.g. `/Volumes/Ollama/hf_home`). Message: eject the drive, so that the run can only use the shipped weights. |
| r2 | Any of `HF_HOME`, `Z_IMAGE_HF_HOME`, `LTX2_MLX_HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE` in the process env, or `HF_HOME` in the zsh subshell, starts with `/Volumes/` |
| r3 | `/usr/bin/pgrep -fl "ltx-2-mlx|z_image|mlx_lm|vllm"` prints anything (another GPU job or a live story server) |
| r4 | `port_free(8177)` is false |
| r5 | `sysctl -n vm.swapusage` "used = N.NNM" is ≥ 3072.00M. Message: wait; swap drains at about 32 MB/min and `purge` does not help. |

### 13.2 GPU run procedure (per geometry)

| Label | Seed (`WS`-relative) | W H SW SH |
|---|---|---|
| portrait | `generated/hw_gate_seeds/portrait.png` | 320 576 320 576 |
| wide | `generated/hw_gate_seeds/wide3x1.png` | 960 320 960 320 |
| square | `generated/hw_gate_seeds/square.png` | 512 512 512 512 |
| noseed | none | 704 448 1408 896 |

1. Run `workspace()/bin/story-server vision` (timeout 120 s) and require rc 0. Then poll `HOOKS["http_ok"]("http://127.0.0.1:8177/v1/models")` every 15 s for up to 1800 s; if it never succeeds, FAIL "story server did not come up".

   This restart happens before **every** run: `--story-server-stop-after-story` stops the server after each run's Phase 1, as learned during the 2026-09-24 gate.
2. `SID = "deploy-accept-<label>-<YYYYmmddHHMMSS>"` and `story_dir = WS/generated/stories/SID`. `story_dir` must not exist; create it. A story id is never reused.
3. Build the environment: `env = dict(os.environ)`, set `HF_HOME = home()+"/hf_home"` and `HF_HUB_OFFLINE = "1"`, and remove `Z_IMAGE_HF_HOME`, `LTX2_MLX_HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE` and `HF_TOKEN`.
4. Launch ltx-movie with `argv = [framework_py(), WS+"/bin/ltx-movie", NARR, "--story-id", SID, "--panels", "2"] + (["--seed-image", WS+"/"+seed] if seed else []) + ["--model", ltx25_model_path(), "--no-review", "--story-server-stop-after-story"]`.
   - `cwd = WS`; stdin is `DEVNULL`; stdout and stderr go to `story_dir/console.txt`; `start_new_session=True`.
   - `NARR` is exactly: `An old fisherman in a flat cap and a waxed coat stands at a lighthouse railing as a storm rolls in over the sea. He grips the rail and watches the waves, then turns and walks toward the lighthouse door.`
5. Start the memory sampler as a child: `[framework_py(), "-c", SAMPLER_SRC, story_dir+"/hw_gate.json", str(pid), str(memsize)]`. `SAMPLER_SRC` is a string constant in `install_pkg.py` that reproduces the plan's Task 13 Step 3 sampler (psutil, 2 s interval, the `phase4_*` fields), with one change: `phase4_peak_used_gib = memsize/2**30 − min(avail)` instead of the hard-coded 48.0. It runs under the framework Python because `/usr/bin/python3` has no psutil.
6. Wait for ltx-movie with a 7200 s timeout. On timeout: `os.killpg(SIGTERM)`, wait 30 s, then `SIGKILL`, and record rc `"timeout"`. Write `story_dir/gate_rc.txt`. Wait up to 60 s for the sampler.
7. Run `workspace()/bin/story-server stop` (idempotent). Record its rc; it does not affect the verdict.
8. Evaluate the criteria, which are identical to the plan's Task 13 Step 4:
   - **c1**: rc is `0`, and the newest `runs/*/story_summary.json` (by mtime) has `completed_units == requested_units == 2`.
   - **c2**: `ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=width,height,codec_name,nb_read_frames -of json movie.mp4` gives `(width, height) == (W, H)`, `nb_read_frames == "290"` and `codec_name == "h264"`. The `a:0` stream's `codec_name` is `"aac"`.
   - **c3**: `images/panel_01.png` measures `(SW, SH)`.
   - **c4**: the rgb24 framemd5 of `clips/panel_02.chainseed.png` (`-vf format=rgb24`) equals that of frame 144 of `clips/panel_01.mp4` (`-vf select=eq(n\,144),format=rgb24`). Both come from `ffmpeg -v error -nostdin -i <path> -map 0:v:0 -vf <vf> -fps_mode passthrough -f framemd5 -`, and each must give exactly one non-comment row. **`-map 0:v:0` is mandatory**: without it the AAC track adds rows and c4 always fails, which is the bug fixed on 2026-09-24.
   - **c5**: `phase4_max_pressure < 4` and `phase4_swap_delta_gib <= 1.0`.
9. Record `pad_px` (from `residual pad (\d+) px` in `console.txt`), the probe results, `peak_used_gib`, `max_pressure`, `swap_delta_gib` and the unit seconds in the accept JSON.

After a PASS, accept prints each `movie.mp4` path and asks the user to eyeball it:
- the subject is not cropped;
- there is no black bar beyond `pad_px`;
- panel 2 continues panel 1.

This sign-off is manual and not part of the exit code.

## 14. README requirements

`README.md` is rendered by `build_pkg.py` from a string constant, before the copy. It must contain these sections:

1. What this package is: the package id, the build date, the source git HEAD, and what ships.
2. Target requirements (P2 verbatim), including the Homebrew and `brew install ffmpeg python@3.12` prerequisites and the exact `~/.zshenv` line.
3. The install commands, each written out in full on one line. `INST` below stands for the literal text `/usr/bin/python3 <usb_root>/<package_id>/scripts/deploy/install_pkg.py`, with `<usb_root>` and `<package_id>` substituted at render time (e.g. `/Volumes/Ollama/ltx-chain-deploy-20260925`). The rendered README writes `INST` out in full every time:
   - `INST --phase preflight`
   - `sudo INST --phase system-python --apply` (needs a real Terminal)
   - `INST --phase user --apply`
   - `INST --phase verify`
   - `INST --phase accept --gpu`, and optionally `INST --phase accept --gpu-all`

   Then, for use after the drive is ejected, the receipts form: `/usr/bin/python3 /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/deploy-receipts/<package_id>/scripts/deploy/install_pkg.py --phase accept --gpu`.
4. Running the pipeline:
   - start `bin/story-server vision` and wait for `curl -sf http://127.0.0.1:8177/v1/models`;
   - then a plain example command and a `--seed-image` example command.

   Each example is one line of the form `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 bin/ltx-movie "<narrative>" --story-id <id> --panels 4 [--seed-image <path>] --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --story-server-stop-after-story`.
5. Warnings:
   - the code's `--model` default names an ltx-2.3 model that is **not** shipped (D9);
   - `--seed-image` (a path) is not the same flag as `--image-seed` (an int);
   - restart the story server before every run;
   - keep swap under 3 GiB before a run.
6. Troubleshooting: `~/.qwen-serve-guard/stand-down` makes Phase 1 exit 2 without probing port 8177 (a known open bug). Report it; do not delete it blindly.
7. Not included: text mode, the 27B fallback, ltx-2.3, path re-pinning.

Rules:
- Every README line containing `bin/ltx-movie` also contains `--model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8`.
- `ltx-movie` commands never use line continuations.
- Prose refers to the program as `ltx-movie`, without the `bin/` prefix.
- These strings never appear, case-insensitively: `--video-backend`, `comfyui`, `cctech`, `chriscoletech`, `8189`.
- The README is L2-clean.

## 15. Test strategy

### 15.1 Conventions

- Tests are `unittest.TestCase` classes with real `self.assert*` calls. They do not use this project's non-raising `check()` helper. The file ends with `if __name__ == "__main__": unittest.main()` and never imports pytest.
- Scripts are located as `DEPLOY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "deploy")` and loaded with `importlib.util.spec_from_file_location`. The mutation harness can therefore test copies.
- **Isolation.** Every test builds a fixture tree under `tempfile.mkdtemp()`: a fake HOME with a fake workspace and fake git repo, `FRAMEWORK_ROOT`, `USR_LOCAL_BIN`, `VOLUMES_ROOT`, a USB root and the HF hubs. Tests patch `REQUIRED_HOME`, `FRAMEWORK_ROOT`, `USR_LOCAL_BIN`, `VOLUMES_ROOT`, `FALCONSAI_USB_HUB`, `BREW_BIN`, `BREW_PY312`, `LTX25_PACK_FILES` and the HF pins, and set `HOME`.
- `setUp` replaces **every** `HOOKS` entry with a fake that raises `AssertionError("unfaked hook <name>")` unless the test configures it. No test can touch the real system.
- Fake git is served through the fake `run` hook, keyed by argv.
- Secret and pattern canaries are built by concatenation (e.g. `"gh" + "p_" + "A" * 36`), so the repo never holds a matching literal. Forbidden README strings are also spelled by concatenation, so the repo-wide backend grep gate (`comfyui_|cctech_|…`) stays clean.
- `CHUNK_SIZE` is patched to 64 in the chunk-boundary tests.

### 15.2 Test classes and cases

| Class | Cases |
|---|---|
| `TestComponentCollection` | **T01** golden `(k, c, p, t)` list for a fixture of every component. **T02** exclusions: B1 top-level names; R4 pruned dirs in every tree; `.DS_Store`; B4 `.cache`; the exact F1/F3 editable-ref names; A1 is exactly the 17 files while every legacy name in §7 exists in the fixture workspace yet is absent. **T03** HF snapshot symlinks become `l` entries with relative `l`, and after apply they are symlinks in the payload. **T04** B5/H0/H5 entries have `s: true` and no `p`. **T05** F2 has exactly 17 `l` + 3 `d`. **T06** JSONL key order and schema. **T07** a fifo in a tree fails B03. |
| `TestCredentialGates` | **T10** a nested `token` file fails B12 (exit 4, no package root); `tokenizer.json` passes. **T11** each of the 11 L1 names fails. **T12** for each L2 pattern id, a canary fails B13; hash-pinned allowlisting silences it; changing one byte fails it again; a > 4 MiB file with a canary is not flagged by L2 (documented limit). **T13** L3: a ≥ 16-byte canary in fake `~/.cache/huggingface/token`, containing a `.` so L2 cannot match it, is placed across a 64-byte chunk boundary in a payload source: exit 5; the partial dst is gone; the message contains the source path and not the canary; no `MANIFEST.json`. The same holds for a canary inside one chunk. **T14** `stored_tokens` parsing; a 15-byte value fails B14; an unparsable `stored_tokens` fails B14; the no-files baseline order includes `~/hf_home` and the fixture's `VOLUMES_ROOT/USB/hf_home`. **T14b** the `$HF_HOME`, `~/hf_home`, `VOLUMES_ROOT/*/hf_home`, `$HF_TOKEN_PATH` and `$HUGGING_FACE_HUB_TOKEN` sources: the exact 14-entry order with every source present; a volume without `hf_home` and a non-`hf_home` directory are not matched; an empty `$HF_HOME` or `$HF_TOKEN_PATH` adds no entry; a duplicate path is listed once; errors name the new paths; no secret value appears in the errors, the sources or the B14 message. **T15** L4: a pattern canary in the fake pip-freeze output gives exit 3, `BUILD-FAILED.json` with `failed_step == "PC4"`, and no `MANIFEST.json`. **T16** L2 over `scripts/deploy/*.py` with an empty allowlist finds 0 hits. **T17** `--credential-report` prints NEW lines, the canary's matched bytes are absent from the output, exit 1, nothing written. |
| `TestRPre` | **T20** a failing gate (G3 returns rc 1) gives exit 4 and the package root does not exist. **T21** after the first payload write, `builtins.open`/`os.open` raise for paths outside the root that are not entry sources, and `HOOKS["run"]` raises; the build still exits 0 with `MANIFEST.json` present. **T22** `l4_rescan` patched to raise gives exit 3, `BUILD-FAILED.json`, and no `MANIFEST.json`. **T23** at `after_entry(0)`, README, every `manifests/*` and `scripts/deploy/*` already exist. |
| `TestCopyEngine` | **T30** payload and `h` equal source bytes and sha256; mode and `mtime_ns` preserved. **T31** `after_chunk` appends to the source: exit 5, message names the source. **T32** a source changed between enumeration and copy: exit 5. |
| `TestResume` | **T40** `after_entry` raises at K: exit 5; `--resume` exits 0; the result is byte-identical (§11.3) to an uninterrupted build into a second USB root. **T41** a torn final partial line is truncated and resume succeeds. **T42** an already-listed source changes: resume fails B07 (exit 4). **T43** a corrupted listed payload file: resume re-copies from that entry and the result is identical to T40's reference. **T44** `--resume` with `MANIFEST.json` present fails B07. |
| `TestVerifyOnly` | **T50** clean: 0. Each of these gives 1: a flipped byte, a truncated file, a missing file, an extra payload file, an edited `MANIFEST-ENTRIES.jsonl`, an edited root file, `BUILD-FAILED.json` present. A stat snapshot proves nothing is written. |
| `TestInstallChecks` | **T60-T79** table-driven: one passing and one failing fixture per I01-I20, including I20's PENDING case in preflight and I17's zsh and `.zshenv` `/Volumes/` cases. |
| `TestInstallApply` | **T70** S and U without `--apply` change nothing: a full stat snapshot (path, mode, size, `mtime_ns`, symlink value) of the fake root is identical before and after. **T71** a 16 GiB memsize with `--apply` gives exit 4 and nothing written. **T72** identical targets are skipped (inode and mtime unchanged); two differing targets give exit 4 and both are listed. **T73** a hook raises mid-file: no final-named file exists; a rerun completes. **T74** installed hash, mode and `mtime_ns` match; symlinks are recreated; created dirs get `m`; a pre-existing dir keeps its mode. **T75** a corrupted payload byte: U exits 1 and the target is absent. **T76** receipts are hash-identical; `verify` and `accept` (A0-A4) succeed from receipts with the USB root deleted; P, S and U refuse on a receipts root. **T77** S passes with euid 0 and fails with 501; U fails with euid 0. |
| `TestAccept` | **T80** a gate's last line `OK 117/118` against a baseline of `OK 118/118` gives ACCEPT FAIL, exit 1. **T81** c1-c5 on synthetic ffprobe/ffmpeg outputs: all pass; each fails alone; c4 fails with two framemd5 rows; the ffmpeg argv contains `"-map", "0:v:0"`. **T82** refusals r1-r5 each give exit 5, with no story-server or ltx-movie call made. **T83** the portrait argv and env match §13.2 exactly (the `--model` path, `--panels 2`, `--story-server-stop-after-story`, `--no-review`, `HF_HUB_OFFLINE=1`, scoped variables removed). **T84** `--gpu-all` runs the 4 geometries in order and calls `story-server vision` before each. **T85** A4's story-server usage check passes and fails correctly. |
| `TestReadme` | **T90** every line with `bin/ltx-movie` contains the explicit `--model` path, and there are ≥ 2 such lines. **T91** the forbidden strings are absent. **T92** the README is L2-clean. |
| `TestLanguageLevel` | **T95** `ast.parse(src, feature_version=(3, 9))` succeeds for both scripts. |

### 15.3 Mutation harness (`tests/mutate_deploy_pkg.py`)

For each mutation below, the harness:
1. copies `scripts/deploy/{build_pkg.py, install_pkg.py, credential_allowlist.json}` and `tests/test_deploy_pkg.py` into a fresh `tempfile.mkdtemp()`, keeping their relative layout;
2. applies each `(old, new)` edit. Every `old` must occur **exactly once** in its file, and the mutated file must `compile()`. Otherwise it prints `ANCHOR <id>` and exits 2;
3. runs `[framework_py(), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", <copy>/tests/test_deploy_pkg.py]` with `PYTHONDONTWRITEBYTECODE=1` and a 600 s timeout;
4. records `caught` if rc ≠ 0, else `SURVIVED`.

It also runs a control with no edits, which must give rc 0. It prints `MUTATION <id> caught|SURVIVED` per mutation, then `MUTANTS <caught>/12 CONTROL ok|FAIL`. It exits 0 iff 12/12 are caught and the control is ok.

| Id | File | Edit(s) `old` → `new` | Must be caught by |
|---|---|---|---|
| M1 | build_pkg.py | `["token", "stored_tokens",` → `["stored_tokens",` | T10 |
| M2 | build_pkg.py | `self.tail = window[-self.keep:] if self.keep else b""` → `self.tail = b""` | T13 (boundary) |
| M3 | build_pkg.py | `    l4_rescan(ctx)` → `    pass` | T15 |
| M4 | build_pkg.py | (a) `    results.append(check_offline_gates(ctx))\n` → `` and (b) `    copy_payload(ctx)\n` → `    copy_payload(ctx)\n    check_offline_gates(ctx)\n` | T20 |
| M5 | install_pkg.py | `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, True)` → `    return CheckResult("I03", memsize >= MIN_MEMSIZE_BYTES, message, False)` | T71 |
| M6 | build_pkg.py | `    if before_key != after_key:` → `    if False:` | T31 |
| M7 | install_pkg.py | `    if digest != entry["h"]:` → `    if False:` | T75 |
| M8 | install_pkg.py | `            collisions.append((target, reason))` → `            pass` | T72 |
| M9 | build_pkg.py | `    return (component, relpath, sha256, pattern_id) in allow` → `    return any(a[0] == component and a[1] == relpath and a[3] == pattern_id for a in allow)` | T12 (one byte changed) |
| M10 | install_pkg.py | `glob.glob(os.path.join(VOLUMES_ROOT, "*", "hf_home"))` → `[]` | T82 (r1) |
| M11 | install_pkg.py | `    if not args.apply:` → `    if False:` | T70 |
| M12 | install_pkg.py | `    if fatal_failures:  # refuse --apply` → `    if False:  # refuse --apply` | T71 |

The executor writes the anchor lines in §8, §9, §11 and §12 verbatim, including indentation, so that each anchor is unique.

### 15.4 Real-host checks (main thread, after SC1/SC2)

1. `build_pkg.py --dry-run`: the totals meet SC3. Expected FAIL lines until the preconditions are met: B17 (P0), B13 (P1), and B09 if the story server is running. All other checks PASS.
2. `build_pkg.py --credential-report`: human review, then the allowlist is committed.
3. After P0 and P1 are resolved: `--apply`, then `--verify-only` (SC4).
4. On the target Mac: SC5.

## 16. Exit codes

| Script | Code | Meaning |
|---|---|---|
| build_pkg.py | 0 | dry run OK, apply complete, verify OK, or credential report clean |
| | 1 | `--verify-only` mismatch, `--credential-report` found L1 or NEW hits, or an unexpected error before any write |
| | 2 | usage error (argparse) |
| | 3 | post-copy failure: `BUILD-FAILED.json` written, no `MANIFEST.json` |
| | 4 | a pre-build check failed. Nothing is written; in `--apply` the package root is not created. |
| | 5 | copy-stage abort (SourceChanged, CredentialLeak, I/O). The partial JSONL is fsync'd and the build is resumable. |
| install_pkg.py | 0 | phase succeeded / ACCEPT PASS |
| | 1 | runtime failure: install hash mismatch, post-check failure, verify mismatch, ACCEPT FAIL |
| | 2 | usage error |
| | 4 | fatal check(s) failed; nothing written |
| | 5 | accept GPU refusal (r1-r5); retry later |

## 17. Explicitly out of scope

- Text-mode story generation: MTPLX 27B, the Homebrew `mtplx` install, `thermalforge` (D3).
- The Huihui-27B model, `qwen-serve-guard`, its LaunchAgent and `WS/qwen38-6bit` (D4).
- Any account or home other than `reubenpatterson` and `/Users/reubenpatterson`, and any path re-pinning (D1).
- Trimming the 2.5 pack (D5).
- Changing `bin/ltx-movie`'s `--model` default, or any other pipeline code change (D9).
- ltx-2.3 models and the Gemma-3-12B text encoder (D2).
- Provisioning Homebrew, ffmpeg, python@3.12 or the Command Line Tools (P2).
- Editing `~/.zshenv`, `~/.zprofile` or any dotfile.
- Network access on the target. `accept --gpu` runs with `HF_HUB_OFFLINE=1`.
- Reviving or adapting the deleted 152-method test suite or the old scripts.
- Uninstall, rollback, locks, throughput benchmarking, xattr/ACL/flag preservation, `chown`.

## 18. Known risks

| # | Risk | Handling |
|---|---|---|
| KR1 | `HF_HUB_OFFLINE=1` for the vLLM story server was never exercised; the 2026-09-24 gate ran without it. | `accept --gpu` exposes it. A failure there is a real finding (a hidden network dependency), not a flake. |
| KR2 | A3 compares the combined stdout+stderr last lines exactly. An environment-specific warning on the target could make a line differ. | The failure prints both lines. Diagnose it; do not loosen the check. |
| KR3 | The source `~/.zshenv` holds non-HF credentials (`GPU_TOKEN`, `GPU_NODE_API_TOKEN`). `~/.zshenv` is not shipped, and L3 covers HF values only (D10). | See OQ2. |
| KR4 | The target's default APFS is case-insensitive. | I11, plus I10's identity checks. |
| KR5 | xattrs are not copied. | Code signatures are embedded in the Mach-O files, so this is harmless. |

## 19. Open questions (for the user)

- **OQ1 (blocks the build, P0).** Which state of the 4 files failing B17 should be committed?
  - (a) Commit-split: commit the `ltx2_mlx_video_skill.py` and `z_image_skill.py` scoped-HF_HOME hunks (the state the hardware gate ran), `git add bin/story-server`, and leave the `bin/qwen-agent` `AUTO_APPROVE_TOOLS` hunk uncommitted. The package would then ship HEAD's `bin/qwen-agent`.
  - (b) Commit everything as-is. The package would then ship bash/run_python/write_file auto-approval.
  - (c) Something else.

  Any choice overrides the redesign plan's G8 rule for these files, so it needs your explicit decision. Separately, the `z_image_skill.py` docstring "Explicit content IS allowed." contradicts its own `content_safety.assert_image_safe` call.
- **OQ2.** Should L3's known-secret set also include the `GPU_TOKEN` / `GPU_NODE_API_TOKEN` values from `~/.zshenv`? This spec keeps D10 as decided (HF values only).

## 20. Self-review record

- **Placeholder scan.** Every threshold, path, pin, regex, exit code and anchor line is concrete. The `<…>` tokens in §6 are schema notation, not open items.
- **Consistency.** B01-B17, I01-I20, A0-A5, c1-c5, M1-M12, T01-T95 and PC1-PC5 are each defined once and referenced consistently. Schema 4 is used everywhere. Script names are `build_pkg.py` / `install_pkg.py` throughout. The §7 sizes sum to the total stated in SC3.
- **Scope.** Only the five §5.1 files are created. No pipeline code changes.
- **Ambiguity.** Items the brief left open or got wrong are resolved in §3.2 (R1-R12). The only unresolved items are OQ1-OQ2, which are user decisions.
