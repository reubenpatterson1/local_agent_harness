# bin/judge-clips -- Design Spec (Phase 4 of the self-improvement loop: rendered-clip judging)

Date: 2026-10-04
Status: The user approved the design decisions in the brief, and this document transcribes them. Choices made while writing this document to remove ambiguity are marked **[spec choice]**. Grounding facts that turned out different from the brief when checked against the real files, the installed tools, and the current Anthropic docs are recorded in Section 0.2 and carried into Section 8 (Known gaps / open questions). **Read G1 before implementing.** The brief's "100 images = API per-request image limit" premise is wrong for `claude-opus-5-5`. The approved 25-clip cap is kept, and the E5 message is worded so that it stays true.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`

**Two different "phase" numberings appear in this document. Do not confuse them.**

- **Self-improvement-loop phases** (this project): Phase 1 = `bin/judge-story`, Phase 2 = `bin/iterate-story`, Phase 3 = `bin/judge-stills`, Phase 4 = `bin/judge-clips` (this spec). This document says "loop Phase N" when it means these.
- **Pipeline phases** (`bin/ltx-movie`'s own sequence): Phase 1 = story authoring, Phase 2 = stills, Phase 3 = manifest, Phase 4 = render. This document says "pipeline Phase N" when it means these.

So `bin/judge-clips` (loop Phase 4) judges the output of pipeline Phase 4.

---

## 0. Purpose and scope

### 0.1 Purpose

Loop Phase 3 (`bin/judge-stills`) judges the generated stills. For chain-format stories, which are every story the current pipeline produces, that is only panel 1's still. Panels 2..N exist only as rendered video. Loop Phase 4 judges the rendered clips themselves.

A human runs `bin/judge-clips --story-id <id>` against a story whose clips are all rendered. The tool:

1. finds every `clips/panel_NN.mp4`;
2. pairs each one with its panel in `manifest.json`;
3. samples 4 frames from each clip with ffmpeg;
4. sends all of them, with each panel's Motion:/Narration: text, to Claude in one API call.

Claude returns three 1-10 scores per clip (`motion_fidelity`, `physical_realism`, `temporal_stability`), two 1-10 movie-level scores (`seam_continuity`, which is required only when there are 2 or more clips, and `narrative_clarity`), and a free-text critique that names panels. The tool writes `clips_judgment.json` and prints a score table and the critique.

The tool only observes. It regenerates nothing and is not wired into the pipeline.

### 0.2 Grounding evidence

Everything below was checked while this spec was written (2026-10-04), against the real files under `WS/generated/stories/`, the installed ffmpeg, and the current Anthropic docs.

**Tools on this machine.** `/opt/homebrew/bin/ffmpeg` and `/opt/homebrew/bin/ffprobe`, version `9.0.1`. Its encoders include `libx264` and `mjpeg`. `python3` is 3.13.0, `anthropic` is 0.116.0, and `jsonschema` is 4.23.0.

**Manifest fields (checked on `test_story1/manifest.json`, schema_version 3, and `frogjump/manifest.json`, schema_version 2; the writer is `bin/ltx-story-manifest:470-528`).**

- Top level: `schema_version`, `story_id`, `title`, `narrative`, `created_at`, `fps`, `target_seconds`, `pace`, `total_num_frames`, `total_duration_s`, `panels`.
- Each panel: `index` (int, 1..N in order), `image_path`, `title`, `panel_text`, `narration`, `narration_words`, `num_frames`, `duration_s`, `motion_prompt`, `transition_to_next`. Schema 3 adds `conditioning`.
- Schema 3 (`--chain`, the current `bin/ltx-movie` flow):
  - Panel 1: `image_path` is the still's absolute path, `conditioning` is `"still"`, and `panel_text` is the panel's `Image:` text (the opening still's description).
  - Panels 2..N: `image_path` is `null`, `conditioning` is `"chain"`, and `panel_text` is a copy of the `Motion:` text.
  - In every panel, `motion_prompt` is the `Motion:` text.
- Schema 2 (legacy): `motion_prompt` can be `null` (`bin/ltx-story-manifest:501`), `title` and `narration` can be `""`, `panel_text` is documented as non-empty, and there is no `conditioning` key. `--no-images` writes `image_path: null` for every panel.
- Field values are already stripped, space-joined strings (`bin/ltx-story-manifest:202-245`).

**Clips on disk.**

- `test_story1/clips/` holds `panel_01.mp4` .. `panel_05.mp4`. Next to them are files the tool must ignore: `panel_NN.mp4.provenance.json` and `panel_NN.chainseed.png`.
- Every clip has an `h264` `yuv420p` video stream at 704x448, `r_frame_rate` = `avg_frame_rate` = `24/1`, and 145 frames. It also has an `aac` audio stream (283 packets, 6.01 s).
- Survey of every clip under `generated/stories/*/clips/` (90 clips):
  - Every clip has both a video and an audio stream, and every frame rate is `24/1`.
  - Dimensions: 704x448 (55 clips), 384x576, 512x512, 448x384, 384x512, 320x576, 960x320. The largest long edge is 960 px.
  - Frame counts: 145, 241, and 9 (`final_e2e_verify`).

**Frame count: `-count_frames` / `nb_read_frames`, not the header's `nb_frames`.**

- On all 90 clips, the decoded count (`nb_read_frames`), the container header's `nb_frames`, and the manifest's `num_frames` agree. The tool still uses `nb_read_frames` **[spec choice]**:
  - It is the number of frames the decoder actually produces. That is exactly what the `select` filter's `n` counts, so the sampled indices are guaranteed to exist.
  - `nb_frames` is container metadata. It can be absent (`N/A`) or wrong (edit lists, truncated files).
- Cost: 0.117 s per 145-frame clip with `-count_frames`, against 0.018 s without. The whole test_story1 probe-and-extract pass for 5 clips took 0.90 s wall-clock.
- Real JSON output shape (`ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames,avg_frame_rate -of json <clip>`):
  `{"programs": [], "stream_groups": [], "streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "145"}]}`. The values are strings.
- Failure shapes, observed:
  - A garbage file or an empty file gives exit 1, stderr `... moov atom not found` / `<path>: Invalid data found when processing input`, and stdout `{}`.
  - An audio-only mp4 gives exit 0 and `"streams": []`.
  - An mp4 written with `-frames:v 0` (261 bytes) also gives exit 0 and `"streams": []`. A video stream with zero decodable frames could not be produced, so the `nb_read_frames == "0"` guard is covered only by a canned-output test (T9c).

**Frame extraction: one ffmpeg invocation per clip, verified.**

- The command is:
  `ffmpeg -nostdin -v error -i <clip> -map 0:v:0 -vf "select=eq(n\,0)+eq(n\,48)+eq(n\,96)+eq(n\,144)" -fps_mode passthrough -q:v 2 -f image2 <dir>/frame_%d.jpg`.
  On `test_story1/clips/panel_01.mp4` it wrote exactly 4 JPEGs, each 704x448 `mjpeg` `yuvj420p`.
- **Independent check against a full decode:**
  - `ffmpeg -i panel_01.mp4 -map 0:v:0 -f framemd5 -` produced 145 lines with 145 distinct hashes.
  - The same select filter with `-f framemd5` produced 4 lines with pts `0, 48, 96, 144`. Their hashes `721b7846…`, `e2933372…`, `f920e673…`, and `623d3554…` equal lines 1, 49, 97, and 145 of the full decode.
  - Each batch JPEG is also byte-identical (`cmp`) to a per-index single-frame extraction of the same index.
- **`-fps_mode passthrough` is load-bearing.** Without it, or with `-fps_mode cfr`, the same command writes **191** JPEGs, because the image2 muxer duplicates frames to fill the timestamp gaps. On a synthetic 25-frame clip it writes **31** JPEGs instead of 4.
- **Repeated select terms do not repeat frames.** `select=eq(n\,48)+eq(n\,48)` writes **1** file. So the tool extracts each distinct index once and repeats the bytes in Python for n < 4 (Section 3.6).
- **Indices past the end are silently missing.** Selecting `0,1,2,5` from a 3-frame clip writes 3 files with exit 0. This is why the file-count check in Section 3.6 exists.
- Garbage input to ffmpeg exits 183. An audio-only input with `-map 0:v:0` exits 234 (`Stream map '' matches no streams`).
- Both `-vf` spellings work when passed as one argv element from Python: `select=eq(n\,0)+...` (unquoted, comma-escaped) and `select='eq(n\,0)+...'`. The tool uses the unquoted form **[spec choice]**.

**Extracted JPEG sizes (`-q:v 2`, native resolution).**

| Story (frames measured) | Raw mean | Raw max | base64 mean |
|---|---|---|---|
| test_story1 (20 = 5 clips x 4) | 28.1 KB | 40.3 KB | 37.5 KB |
| test_story7 (20) | 30.7 KB | 57.5 KB | -- |
| hwgate-wide (8, 960x320) | 44.8 KB | 61.2 KB | -- |
| frogjump (20, pre-chain, more detail) | 56.6 KB | 85.1 KB | -- |

- At test_story1's measured base64 mean, a 20-panel movie (80 images) is about **3.0 MB** of image data, and the 25-clip cap (100 images) is about **3.75 MB**.
- Worst case, using frogjump's 85.1 KB max (about 113 KB base64) for every frame: 100 images is about **11.3 MB**. That is well under the 32 MB request-size limit.

**Anthropic API limits** (`https://platform.claude.com/docs/en/build-with-claude/vision` and `.../about-claude/models/overview`, fetched 2026-10-04).

- Images per request: **100 for models with a 200k-token context window, and 600 for all other models.** `claude-opus-5-5` has a **1M-token** context window, so its limit is 600 (see G1).
- Per-image cap: 10 MB base64 on the direct API. Request-size limit: **32 MB** for standard endpoints.
- More than 20 images in a request triggers a stricter per-image dimension limit. Keeping both dimensions at or below 2000 px is safe, and every observed clip is at most 960 px.
- Supported `media_type` values include `image/jpeg`.
- Visual-token cost is `ceil(w/28) * ceil(h/28)`. 704x448 costs 26*16 = 416 tokens per frame: 8,320 for test_story1's 20 frames, 41,600 for 100.
- The docs recommend introducing each of several images with a short text label, which this design does (Section 3.8). They also note that images placed before text perform slightly better. The approved layout puts the panel text first; see G7.

**Stories on disk relevant to the live gates (Section 7.6).**

- `test_story1`: 5 clips, schema 3, 5 panels.
- `final_e2e_verify`: 1 clip (9 frames), schema 2, 1 panel. **This is the 1-clip case.**
- `mlxdemo`: clips `01` and `03`, 3 panels. A partial render that must be refused, naming panel 2.
- `mystorytest2`: clip `05` only, 5 panels. Must be refused, naming panels 1, 2, 3, 4.
- `generated/` is gitignored (`qwen-agent-workspace/.gitignore:2`), so live-gate artifacts are never committed.

**Shipped precedent.** `bin/judge-stills` (441 lines) and `tests/test_judge_stills.py` are the models for every convention not restated here. They include the `pipeline_log.run_logged` wiring added in commit `6cb17bb`.

### 0.3 In scope (the whole deliverable)

| # | Item | File |
|---|---|---|
| D1 | New standalone script | `bin/judge-clips` (new, `chmod +x`) |
| D2 | Tests for D1 | `tests/test_judge_clips.py` (new) |

No other file is created or modified. In particular, `bin/judge-stills`, `pipeline_log.py`, `tests/test_pipeline_log.py`, and the deploy package are not touched. The pipeline_log wiring test lives in D2 (T24).

### 0.4 Out of scope

- **Judging audio.** The API takes no audio input. The system prompt says so (Section 4.5).
- Regenerating clips, or any automated re-render loop.
- Checking whether clips are stale relative to the current `story.md`, or reading `*.provenance.json` / `prompt_sha256` (Section 9, item 5).
- **Judging partial renders.** Every manifest panel must have a clip (E12).
- Including the tool in the deploy package (`scripts/deploy/build_pkg.py`, `tests/test_deploy_pkg.py`).
- Reading `story.md`. Panel text comes only from `manifest.json`.
- Reading `movie.mp4`. Seams are judged from adjacent clips' last and first frames.
- Resizing, recompressing beyond the single JPEG encode, chunking, or uploading through the Files API.
- Retry with backoff for API errors. Streaming.
- Validating `--story-id` values. No existing `bin/*` script does this.
- A shared Python module, or importing another `bin/*` file.
- A command-line override of the frame count, the clip cap, or the model.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `--story-id <id>` resolves `generated/stories/<id>/`, `clips/`, and `manifest.json`, and finds exactly the `panel_NN.mp4` clips, sorted numerically | T2, T3 |
| SC2 | Each clip is paired with the manifest panel whose `index` equals its number. Partial renders, stale extra clips, duplicate clip numbers, and malformed manifests are refused with exit 2 before any subprocess or API work | T5, T14a-T14o |
| SC3 | Each clip contributes exactly 4 frames at indices `round(k*(n-1)/3)`, k=0..3, where n is the decoded frame count. The JPEGs are the frames at those indices (independent luma oracle), at native resolution, written only to a temporary directory that is removed afterward | T4a, T4b, T9a, T10a, T10b, T17 |
| SC4 | The single user message is: per panel, a text block, then 4 (label, image) pairs; then one final text block whose variant depends on the clip count | T8a, T8b, T17, T18 |
| SC5 | The judging call uses exactly judge-stills' parameters (Section 4.1), with this tool's prompt, tool, and schema | T17 |
| SC6 | A successful run writes `clips_judgment.json` (Section 5.1) with the exact key order, prints the Section 5.3 stdout, and exits 0 | T17, T18, T25 |
| SC7 | Every row of the error table (Section 6) gives the specified exit code and message, and scores are never fabricated | T1, T14, T15, T16, T19-T22 |
| SC8 | No test makes a network call. If the key is unset, neither ffprobe/ffmpeg nor the client is invoked | T15; review of the test file |
| SC9 | The value of `ANTHROPIC_API_KEY` never appears in stdout, stderr, or any file written | T23 |
| SC10 | `__main__` is wired through `pipeline_log.run_logged("judge-clips", ...)` | T24 |

### 0.6 Must-have vs nice-to-have

Every requirement in Sections 1-7 is a must-have. There are no nice-to-haves, and nothing beyond these sections is to be built.

---

## 1. Architecture

### 1.1 Script conventions

`bin/judge-clips` follows `bin/judge-stills` exactly in these respects:

- Shebang `#!/usr/bin/env python3`. Module docstring at the top. No file extension. `chmod +x`.
- Top-level imports, in this order: `argparse`, `base64`, `datetime`, `fractions`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, then a blank line, then `anthropic` and `jsonschema`. Use `import fractions` and refer to `fractions.Fraction`, not `from fractions import Fraction`.
- Directly after the third-party imports:
  ```python
  WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
  sys.path.insert(0, WS)
  import pipeline_log  # noqa: E402
  ```
- `def main(argv=None):` returns an `int`. The file ends with exactly:
  ```python
  def _pipeline_log_story_dir(argv):
      story_id = pipeline_log.argv_value(argv, "--story-id")
      return os.path.join(WS, "generated", "stories", story_id) if story_id else None


  if __name__ == "__main__":
      sys.exit(pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv))
  ```
  (`run_logged` calls `main()` with no arguments, so argparse reads `sys.argv[1:]`.)
- Docstring: the same structure as judge-stills', in the implementer's own prose. It must state:
  - the purpose, naming this as loop Phase 4 and citing this spec's path;
  - the usage line `bin/judge-clips --story-id <id>`;
  - that it requires `ANTHROPIC_API_KEY`, `ffmpeg`, and `ffprobe`;
  - the exit codes (0 success, 1 runtime or API failure, 2 argument or precondition failure);
  - that audio is not judged;
  - that on a judging failure the raw responses go to `clips_judgment.raw.json` and no scores are reported.
- Every subprocess call captures its output (`capture_output=True`). ffmpeg/ffprobe output therefore never reaches the terminal directly. It surfaces only inside E15 messages, and those go through `sys.stderr`, which `pipeline_log` captures.

### 1.2 Execution sequence

`main(argv)` performs these steps in this exact order. Cheap filesystem and manifest checks come first, then the PATH check, then the key, then the subprocess work, then the API. Section 1.4 gives the normative code.

1. Parse the arguments (E1).
2. `story_dir, clips_dir, manifest_path = resolve_paths(args.story_id)`.
3. `clips_dir` is not a directory: E2, return 2.
4. `clips = find_clips(clips_dir)`. If it is empty: E3, return 2.
5. Two clip files have the same panel number: E4, return 2.
6. `len(clips) > MAX_CLIPS`: E5, return 2.
7. `manifest_path` is not a regular file: E6, return 2.
8. `panels_by_index = load_manifest_panels(manifest_path)`. A `ManifestError` gives E7, E8, E9, or E10, and returns 2.
9. A clip number has no manifest panel: E11, return 2.
10. A manifest panel has no clip: E12, return 2.
11. `shutil.which("ffmpeg")`, then `shutil.which("ffprobe")`. The first one that is `None` gives E13, return 2.
12. `ANTHROPIC_API_KEY` is unset or empty: E14, return 1.
13. Inside one `tempfile.TemporaryDirectory(prefix="judge-clips-")`, for each clip in panel order: `probe_clip`, `frame_indices`, then `extract_frames` into its own subdirectory. Read the JPEG bytes into memory and base64-encode them. A `ClipError` gives E15 and returns 1. The temporary directory is removed when the `with` block exits, on success or failure.
14. `user_content = build_user_content(clip_inputs)`.
15. `client = anthropic.Anthropic()`, with no arguments.
16. Make the judging call and its single possible retry (Section 4.6): E16 or E17.
17. Capture the timestamp, then `validate_judgment_input(block.input, numbers)`: E18.
18. Write `clips_judgment.json`.
19. Print the stdout summary. Return 0.

### 1.3 Internal names [spec choice]

| Name | Kind | Responsibility |
|---|---|---|
| `WS` | module global | As in 1.1 |
| `MODEL` | constant | `"claude-opus-5-5"` |
| `EFFORT` | constant | `"high"` |
| `MAX_TOKENS` | constant | `21333` (same value and rationale as judge-stills) |
| `TOOL_NAME` | constant | `"submit_judgment"` |
| `TOOL_DESCRIPTION` | constant | Section 4.1 |
| `FRAMES_PER_CLIP` | constant | `4` |
| `MAX_CLIPS` | constant | `25` |
| `MEDIA_TYPE` | constant | `"image/jpeg"` |
| `CLIP_NAME_RE` | constant | `re.compile(r"panel_(\d{2,})\.mp4")` |
| `CLIP_SCORE_KEYS` | constant | `("motion_fidelity", "physical_realism", "temporal_stability")` |
| `MOVIE_SCORE_KEYS` | constant | `("seam_continuity", "narrative_clarity")` |
| `CLIP_TABLE_FORMAT` | constant | `"  %-5s  %-16s  %-16s  %s"` (Section 5.3) |
| `SUBMIT_JUDGMENT_SCHEMA` | constant | Section 4.3 |
| `SYSTEM_PROMPT` | constant | Section 4.5 |
| `FINAL_USER_TEXT_SINGLE` | constant | Section 3.9 |
| `FINAL_USER_TEXT_MULTI_TEMPLATE` | constant (one `%d`) | Section 3.9 |
| `RETRY_USER_MESSAGE` | constant | Section 4.6 |
| `ManifestError` | `class ManifestError(Exception)` | Its `str()` is the E7-E10 message without the `Error: ` prefix |
| `ClipError` | `class ClipError(Exception)` | Its `str()` is the E15 detail (Section 3.4, 3.6) |
| `build_parser()` | function | Section 2.1 |
| `resolve_paths(story_id)` | function | Section 2.2 |
| `find_clips(clips_dir)` | function | Section 3.1 |
| `load_manifest_panels(manifest_path)` | function | Section 3.2 |
| `_text_field(panel, key)` | function | Section 3.7 |
| `format_panel_text(number, panel)` | function | Section 3.7. Pure |
| `_stderr_tail(stderr)` | function | Section 3.4 |
| `probe_clip(path)` | function | Section 3.4 |
| `frame_indices(n)` | function | Section 3.5. Pure |
| `extract_frames(path, indices, out_dir)` | function | Section 3.6 |
| `format_frame_label(panel, position, t)` | function | Section 3.8. Pure |
| `build_user_content(clips)` | function | Section 3.9. Pure |
| `find_tool_use(response)` | function | Identical to judge-stills |
| `_panel_list(panels)` | function | `", ".join(str(p) for p in panels)` |
| `validate_judgment_input(tool_input, panels)` | function | Section 4.4 |
| `format_clip_row(entry)` | function | Section 5.3 |
| `format_movie_line(name, value)` | function | Section 5.3 |
| `_create_message(client, messages)` | function | Identical to judge-stills' (Section 4.1) |
| `_write_raw(story_dir, responses)` | function | Section 5.2 |
| `main(argv=None)` | function | Section 1.4 |
| `_pipeline_log_story_dir(argv)` | function | Section 1.1 |

### 1.4 `main` (normative)

```python
def main(argv=None):
    args = build_parser().parse_args(argv)
    story_dir, clips_dir, manifest_path = resolve_paths(args.story_id)

    # Cheap filesystem and manifest checks first; all exit 2 (spec 1.2, 2.3).
    if not os.path.isdir(clips_dir):
        print("Error: clips directory not found: %s" % clips_dir, file=sys.stderr)
        return 2
    clips = find_clips(clips_dir)
    if not clips:
        print("Error: no panel_NN.mp4 clips found in %s" % clips_dir, file=sys.stderr)
        return 2
    numbers = [number for number, _ in clips]
    for number in sorted(set(numbers)):
        if numbers.count(number) > 1:
            names = [os.path.basename(path) for n, path in clips if n == number]
            print("Error: more than one clip for panel %d in %s: %s"
                  % (number, clips_dir, ", ".join(names)), file=sys.stderr)
            return 2
    if len(clips) > MAX_CLIPS:
        print("Error: %d clips found in %s; judge-clips sends 4 frames per clip in one request "
              "and judges at most 25 clips (100 images, the Anthropic API's per-request image "
              "limit for 200k-context models)." % (len(clips), clips_dir), file=sys.stderr)
        return 2
    if not os.path.isfile(manifest_path):
        print("Error: manifest.json not found: %s" % manifest_path, file=sys.stderr)
        return 2
    try:
        panels_by_index = load_manifest_panels(manifest_path)
    except ManifestError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    extra = [os.path.basename(path) for number, path in clips if number not in panels_by_index]
    if extra:
        print("Error: clips with no matching panel in manifest.json: %s; the clips in %s may "
              "be stale relative to manifest.json." % (", ".join(extra), clips_dir),
              file=sys.stderr)
        return 2
    missing = sorted(set(panels_by_index) - set(numbers))
    if missing:
        print("Error: manifest.json panels with no rendered clip in %s: %s; judge-clips "
              "judges only complete renders." % (clips_dir, _panel_list(missing)),
              file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print("Error: %s not found on PATH; judge-clips needs ffmpeg and ffprobe to "
                  "extract frames." % tool, file=sys.stderr)
            return 2

    # Checked before any subprocess runs and before the client exists; the key is never
    # read into a variable (spec 4.2).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-clips.", file=sys.stderr)
        return 1

    clip_inputs = []
    frames_by_panel = {}
    try:
        with tempfile.TemporaryDirectory(prefix="judge-clips-") as tmp_dir:
            for number, path in clips:
                frame_count, fps = probe_clip(path)
                indices = frame_indices(frame_count)
                out_dir = os.path.join(tmp_dir, "panel_%02d" % number)
                os.mkdir(out_dir)
                images = extract_frames(path, indices, out_dir)
                frames_by_panel[number] = indices
                clip_inputs.append({
                    "panel": number,
                    "text": format_panel_text(number, panels_by_index[number]),
                    "frames": [{"t": float(index / fps),
                                "data": base64.standard_b64encode(data).decode("ascii")}
                               for index, data in zip(indices, images)],
                })
    except ClipError as e:
        print("Error: frame extraction failed: %s" % e, file=sys.stderr)
        return 1
    user_content = build_user_content(clip_inputs)
    client = anthropic.Anthropic()

    responses = []
    try:
        responses.append(_create_message(client, [{"role": "user", "content": user_content}]))
        block = find_tool_use(responses[0])
        if block is None:
            # One retry in the same conversation, re-sending every frame. r1.content goes
            # back exactly as received (thinking blocks and signatures) (spec 4.6).
            responses.append(_create_message(client, [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_USER_MESSAGE},
            ]))
            block = find_tool_use(responses[1])
    except anthropic.APIError as e:
        print("Error: Anthropic API call failed: %s: %s" % (type(e).__name__, e),
              file=sys.stderr)
        return 1
    if block is None:
        raw_path = _write_raw(story_dir, responses)
        print("Error: Claude did not call submit_judgment after one retry; raw responses "
              "written to %s" % raw_path, file=sys.stderr)
        return 1
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        validate_judgment_input(block.input, numbers)
    except jsonschema.ValidationError as e:
        _write_raw(story_dir, responses)
        print("Error: submit_judgment input failed schema validation: %s" % e.message,
              file=sys.stderr)
        return 1

    tool_input = block.input
    movie = tool_input["movie"]
    thinking_counts = [r.usage.output_tokens_details.thinking_tokens for r in responses
                       if r.usage.output_tokens_details is not None
                       and r.usage.output_tokens_details.thinking_tokens is not None]
    judgment = {
        "story_id": args.story_id,
        "model": MODEL,
        "effort": EFFORT,
        "timestamp": timestamp,
        "frames_per_clip": FRAMES_PER_CLIP,
        "usage": {
            "input_tokens": sum(r.usage.input_tokens for r in responses),
            "output_tokens": sum(r.usage.output_tokens for r in responses),
            "thinking_tokens": sum(thinking_counts) if thinking_counts else None,
        },
        # int(): jsonschema accepts 7.0 as an integer; the file always holds JSON integers
        # (spec 5.1). Sorted by panel regardless of the order the judge listed them.
        "clips": [
            {"panel": int(entry["panel"]),
             "frames": frames_by_panel[int(entry["panel"])],
             "motion_fidelity": int(entry["motion_fidelity"]),
             "physical_realism": int(entry["physical_realism"]),
             "temporal_stability": int(entry["temporal_stability"])}
            for entry in sorted(tool_input["clips"], key=lambda entry: entry["panel"])
        ],
        "movie": {
            # Absent (-> JSON null) only in the 1-clip case; validation rejects every other
            # absence and every 1-clip presence (spec 4.4).
            "seam_continuity": (int(movie["seam_continuity"]) if "seam_continuity" in movie
                                else None),
            "narrative_clarity": int(movie["narrative_clarity"]),
        },
        "critique": tool_input["critique"],
    }
    with open(os.path.join(story_dir, "clips_judgment.json"), "w", encoding="utf-8") as f:
        json.dump(judgment, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Clip scores:")
    print(CLIP_TABLE_FORMAT % (("panel",) + CLIP_SCORE_KEYS))
    for entry in judgment["clips"]:
        print(format_clip_row(entry))
    print()
    print("Movie scores:")
    for name in MOVIE_SCORE_KEYS:
        print(format_movie_line(name, judgment["movie"][name]))
    print()
    print("--- Critique ---")
    print(judgment["critique"])
    return 0
```

Code comments may be reworded. Statements, message strings, and their order may not change.

---

## 2. CLI

### 2.1 Synopsis

```
bin/judge-clips --story-id <id>
```

```python
def build_parser():
    parser = argparse.ArgumentParser(
        prog="judge-clips",
        description="Judge a story's rendered panel clips with Claude against the manifest text.")
    parser.add_argument("--story-id", dest="story_id", metavar="ID", required=True,
                        help="judge generated/stories/ID/clips/panel_NN.mp4 against "
                             "generated/stories/ID/manifest.json")
    return parser
```

There are no other arguments. A missing `--story-id`, or any unknown flag, gives argparse's usage error and `SystemExit(2)` (E1).

### 2.2 Path resolution

```python
def resolve_paths(story_id):
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    clips_dir = os.path.join(story_dir, "clips")
    manifest_path = os.path.join(story_dir, "manifest.json")
    return story_dir, clips_dir, manifest_path
```

`WS` is read at call time.

### 2.3 Preconditions

These are checked in the Section 1.2 order. E2-E13 exit 2. E14 (key) exits 1 and is checked after every exit-2 check, and before any ffprobe or ffmpeg runs.

### 2.4 Output location

- Success writes `story_dir/clips_judgment.json`. E17 and E18 write `story_dir/clips_judgment.raw.json`.
- Existing files with those names are overwritten without a prompt. Files from an earlier run are never deleted.
- The names cannot collide with `judgment.json` (judge-story) or `stills_judgment*.json` (judge-stills).
- Nothing is written to `clips/`. Frames exist only in the temporary directory.
- Unless `STORY_PIPELINE_LOGGED` is set, `pipeline_log` appends a run record to `story_dir/iterate-story.log` when the story directory exists at the end of the run.

### 2.5 Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | E14-E18: key unset, frame extraction failure, API error, no tool call after retry, validation failure |
| 2 | E1-E13: argument or precondition failure |

---

## 3. Inputs, frames, and message construction

### 3.1 Clip discovery

```python
def find_clips(clips_dir):
    """[(panel_number, path)] for every panel_NN.mp4 in clips_dir, sorted numerically (path
    breaks ties). os.listdir + fullmatch, not glob (spec 3.1)."""
    found = []
    for name in os.listdir(clips_dir):
        m = CLIP_NAME_RE.fullmatch(name)
        if m:
            found.append((int(m.group(1)), os.path.join(clips_dir, name)))
    found.sort(key=lambda item: (item[0], item[1]))
    return found
```

- The regex takes two or more digits, so it matches `panel_01.mp4` and `panel_100.mp4`. It rejects `panel_1.mp4`, `panel_01.mp4.provenance.json`, `panel_02.chainseed.png`, `panel_01.mov`, `Panel_01.mp4`, and `panel_01.mp4.bak`.
- Sorting is numeric: `panel_99` comes before `panel_100`.
- `panel_01.mp4` and `panel_001.mp4` both have panel number 1. That is E4 **[spec choice]**: judge-stills sends both, but here two clips for one panel would make the clip/panel pairing and the judge's per-panel entries ambiguous.

### 3.2 Manifest loading

```python
def load_manifest_panels(manifest_path):
    """{index: panel dict} from manifest.json. Raises ManifestError for E7-E10 (spec 3.2)."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except ValueError as e:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueError subclasses.
        raise ManifestError("manifest.json is not valid JSON: %s: %s" % (manifest_path, e))
    panels = manifest.get("panels") if isinstance(manifest, dict) else None
    if not isinstance(panels, list) or not panels:
        raise ManifestError("manifest.json has no panels list: %s" % manifest_path)
    by_index = {}
    for position, panel in enumerate(panels, 1):
        index = panel.get("index") if isinstance(panel, dict) else None
        if not isinstance(index, int) or isinstance(index, bool):
            raise ManifestError("manifest.json panel entry %d has no integer index: %s"
                                % (position, manifest_path))
        if index in by_index:
            raise ManifestError("manifest.json lists panel index %d more than once: %s"
                                % (index, manifest_path))
        by_index[index] = panel
    return by_index
```

- `schema_version` is not read or checked. Schema 2 and 3 manifests are both accepted (G2).
- Only `index` is required. Every text field is optional, as Section 3.7 specifies: a missing, `null`, non-string, or whitespace-only `title`, `panel_text`, `motion_prompt`, `narration`, or `image_path` just means "absent" and is never an error **[spec choice]**.
- An `OSError` on open, such as a permissions error, propagates as a traceback, the same as judge-stills.

### 3.3 Pairing clips with panels

Clip `panel_NN.mp4` pairs with the manifest panel whose `index == NN` **[spec choice: by `index`, not list position]**. `bin/ltx-story-manifest` writes `index = i` for list position `i`, so on every real manifest the two agree. Pairing by `index` is what the brief names, and it survives a hand-reordered `panels` list (T5).

- **E11.** A clip number has no panel with that index. This catches a stale `panel_06.mp4` left over from an earlier, longer render. All offending clip names are listed, in sorted clip order.
- **E12.** A panel index has no clip. This is a partial render, which this tool refuses. All missing panel numbers are listed, ascending.
- E11 is checked before E12. A directory with both an extra clip and a missing clip reports E11.

### 3.4 Probing a clip (frame count and fps)

```python
def _stderr_tail(stderr):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else "(no error output)"


def probe_clip(path):
    """(frame_count, fps) of the clip's first video stream. frame_count is the number of
    frames the decoder actually produces (-count_frames nb_read_frames), never the
    container header's nb_frames; fps is avg_frame_rate as a Fraction (spec 3.4)."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json", path],
        capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ClipError("ffprobe failed on %s (exit %d): %s"
                        % (path, proc.returncode, _stderr_tail(proc.stderr)))
    try:
        streams = json.loads(proc.stdout).get("streams")
    except ValueError:
        raise ClipError("ffprobe returned unreadable output for %s" % path)
    if not streams:
        raise ClipError("%s has no video stream" % path)
    count = streams[0].get("nb_read_frames", "")
    if not count.isdigit() or int(count) == 0:
        raise ClipError("%s has no decodable video frames" % path)
    rate = streams[0].get("avg_frame_rate", "")
    try:
        fps = fractions.Fraction(rate)
    except (ValueError, ZeroDivisionError):
        fps = fractions.Fraction(0)
    if fps <= 0:
        raise ClipError("%s has no usable frame rate (avg_frame_rate=%r)" % (path, rate))
    return int(count), fps
```

- **Frame count source.** It is `nb_read_frames`, for the reasons in Section 0.2 **[spec choice, verified]**. The manifest's `num_frames` is never read for sampling (Section 9, item 1).
- **fps source.** It is ffprobe's `avg_frame_rate` for this clip, not the manifest's `fps` **[spec choice]**. The clip file is the ground truth for its own timestamps. A manifest edited or rebuilt after rendering cannot skew the `t=` labels. `"0/0"` (seen on the audio streams) raises `ZeroDivisionError`, and `""` raises `ValueError`. Both become the "no usable frame rate" `ClipError`.
- n == 0 is a `ClipError` ("has no decodable video frames"). So is a clip with no video stream at all, which is what audio-only and zero-frame mp4s actually produce.
- No subprocess timeout is set **[spec choice]**. Probing and extracting all 5 test_story1 clips takes 0.9 s.

### 3.5 Frame indices

```python
def frame_indices(n):
    """The FRAMES_PER_CLIP frame indices sampled from a clip of n >= 1 frames:
    round(k * (n - 1) / 3) for k = 0..3 -- first frame, two evenly spaced middle frames,
    last frame. Repeats are kept when n < 4 (spec 3.5). Pure."""
    return [round(k * (n - 1) / (FRAMES_PER_CLIP - 1)) for k in range(FRAMES_PER_CLIP)]
```

| n | indices |
|---|---|
| 241 | `[0, 80, 160, 240]` |
| 145 | `[0, 48, 96, 144]` |
| 25 | `[0, 8, 16, 24]` |
| 9 | `[0, 3, 5, 8]` (`final_e2e_verify`) |
| 5 | `[0, 1, 3, 4]` |
| 4 | `[0, 1, 2, 3]` |
| 3 | `[0, 1, 1, 2]` |
| 2 | `[0, 0, 1, 1]` |
| 1 | `[0, 0, 0, 0]` |

- `k*(n-1)/3` always has a fractional part of 0, 1/3, or 2/3. It is never .5, so Python's round-half-even never applies.
- Checked for every n in 1..2000: the result has length 4, starts at 0, ends at n-1, and each value is within 0.5 of `k*(n-1)/3`.
- **n < 4 is allowed. The clip still contributes 4 frames, with repeats** (approved). n is always at least 1 when this is called, because `probe_clip` rejects 0.

### 3.6 Frame extraction

```python
def extract_frames(path, indices, out_dir):
    """JPEG bytes for each entry of indices, in the same order. Each distinct index is
    extracted once (a repeated select term yields one frame, not two) and its bytes are
    reused for repeats. out_dir must be an existing empty directory (spec 3.6)."""
    unique = sorted(set(indices))
    select = "select=" + "+".join("eq(n\\,%d)" % i for i in unique)
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0",
         "-vf", select, "-fps_mode", "passthrough", "-q:v", "2",
         "-f", "image2", os.path.join(out_dir, "frame_%d.jpg")],
        capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ClipError("ffmpeg failed on %s (exit %d): %s"
                        % (path, proc.returncode, _stderr_tail(proc.stderr)))
    expected = ["frame_%d.jpg" % j for j in range(1, len(unique) + 1)]
    written = os.listdir(out_dir)
    if sorted(written) != sorted(expected):
        raise ClipError("ffmpeg wrote %d frames from %s; expected %d"
                        % (len(written), path, len(unique)))
    by_index = {}
    for j, index in enumerate(unique, 1):
        with open(os.path.join(out_dir, "frame_%d.jpg" % j), "rb") as f:
            by_index[index] = f.read()
    return [by_index[i] for i in indices]
```

What each option does, and the evidence for it (Section 0.2):

- `-nostdin`: ffmpeg never reads the terminal.
- `-v error`: only errors go to stderr, and stderr is captured.
- `-map 0:v:0`: the audio stream is ignored.
- `select=eq(n\,i)+...`: `n` is the 0-based decoded frame number, which is the same count as `nb_read_frames`. `\,` escapes the comma at the filtergraph level. The Python literal is `"eq(n\\,%d)"`.
- `-fps_mode passthrough`: required. Without it, 191 files are written instead of 4.
- `-q:v 2`: mjpeg quality scale 2, near the best. Measured sizes are 21-85 KB.
- `-f image2 .../frame_%d.jpg`: frames are numbered from 1, in ascending index order. The `%d` is passed literally to ffmpeg and is not Python-formatted.
- There is no `scale` filter, so the JPEG is at native resolution: 704x448 for current renders. The pixel format is `yuvj420p`, ffmpeg's default for mjpeg.

Further behavior:

- `frame_N.jpg` holds the N-th smallest distinct index.
- The file-count check catches indices past the end of the clip. Those are silently skipped, with exit 0.
- `main` creates the per-clip `out_dir` as `<tmp>/panel_%02d` with `os.mkdir`. Clip numbers are unique (E4), so these never collide.
- Frames are read into memory, base64-encoded with `base64.standard_b64encode(...).decode("ascii")`, and the temporary directory is removed before the API call.
- `media_type` is always `"image/jpeg"`.

### 3.7 Panel text block

```python
def _text_field(panel, key):
    """panel[key] stripped when it is a string; "" when missing, null, or not a string."""
    value = panel.get(key)
    return value.strip() if isinstance(value, str) else ""


def format_panel_text(number, panel):
    """Header, then Opening still: (panel 1 only, when it has a still), Motion:, Narration:,
    each only when non-empty; no trailing newline (spec 3.7). Pure."""
    title = _text_field(panel, "title")
    lines = ["## Panel %d — %s" % (number, title) if title else "## Panel %d —" % number]
    if number == 1 and _text_field(panel, "image_path"):
        opening = _text_field(panel, "panel_text")
        if opening:
            lines.append("Opening still: %s" % opening)
    for label, key in (("Motion", "motion_prompt"), ("Narration", "narration")):
        value = _text_field(panel, key)
        if value:
            lines.append("%s: %s" % (label, value))
    return "\n".join(lines)
```

- The dash in the header is U+2014 (EM DASH), as in `story.md`. An empty title gives `## Panel 3 —` with no trailing space, matching the empty-title header shape in `story.md`.
- **The opening-still line is sent only for panel number 1, and only when that panel has a non-empty `image_path`** **[spec choice]**. For schema 3, panel 1 always has one. A `--no-images` schema-2 manifest has `image_path: null`, and its `panel_text` there is not a still description, so labeling it "Opening still" would be false.
- `panel_text` of panels 2..N is never sent. In schema 3 it duplicates `motion_prompt`.
- A panel with no title and none of the three texts renders as its header line alone. That is not an error.
- The real test_story1 panel 1 renders as:
  ```
  ## Panel 1 — The Beach at Dawn
  Opening still: A wide shot captures the young woman in the sundress, ... shallow depth of field.
  Motion: The young woman in the sundress takes a slow step forward into the shallow surf, ...
  Narration: She had come to the shore seeking solitude, but the sea had other plans.
  ```

### 3.8 Frame labels

```python
def format_frame_label(panel, position, t):
    """Text block placed immediately before each frame image (spec 3.8). Pure."""
    return "Panel %d, frame %d of %d (t=%.2fs)" % (panel, position, FRAMES_PER_CLIP, t)
```

- `position` is 1..4.
- `t` is `float(index / fps)`, where `index` is the sampled frame index and `fps` is the clip's ffprobe `avg_frame_rate` (a `Fraction`).
- For a 145-frame clip at 24 fps the labels read `t=0.00s`, `t=2.00s`, `t=4.00s`, and `t=6.00s`.
- Example: `format_frame_label(3, 2, 2.0) == "Panel 3, frame 2 of 4 (t=2.00s)"`.

### 3.9 User message content

```python
def build_user_content(clips):
    """The single user turn's content blocks (spec 3.9). clips is a list, in panel order, of
    {"panel": int, "text": str, "frames": [{"t": float, "data": base64 str}] * 4}. Per clip:
    its text block, then a label text block and an image block for each frame; then one
    final text block. Always 9 * len(clips) + 1 blocks. Pure."""
    content = []
    for clip in clips:
        content.append({"type": "text", "text": clip["text"]})
        for position, frame in enumerate(clip["frames"], 1):
            content.append({"type": "text",
                            "text": format_frame_label(clip["panel"], position, frame["t"])})
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                       "data": frame["data"]}})
    count = len(clips)
    if count >= 2:
        final_text = FINAL_USER_TEXT_MULTI_TEMPLATE % count
    else:
        final_text = FINAL_USER_TEXT_SINGLE
    content.append({"type": "text", "text": final_text})
    return content
```

- Each frame gets its own label text block. The label is not merged into the panel text block.
- For test_story1 (5 clips) the content list has 46 blocks: 20 images and 26 text blocks.

```python
FINAL_USER_TEXT_SINGLE = ("You are judging 1 clip above, shown as 4 sampled frames, against "
                          "its panel text. There is only one clip, so there is no join "
                          "between clips to judge: omit seam_continuity from your movie "
                          "object entirely. Score motion_fidelity, physical_realism, and "
                          "temporal_stability for the clip, score narrative_clarity for the "
                          "movie, and call submit_judgment.")
FINAL_USER_TEXT_MULTI_TEMPLATE = ("You are judging all %d clips above, 4 sampled frames from "
                                  "each, against their panel text. Submit one clips entry per "
                                  "panel with motion_fidelity, physical_realism, and "
                                  "temporal_stability, score both seam_continuity and "
                                  "narrative_clarity for the movie, and call submit_judgment.")
```

`FINAL_USER_TEXT_MULTI_TEMPLATE % 2 == "You are judging all 2 clips above, 4 sampled frames from each, against their panel text. Submit one clips entry per panel with motion_fidelity, physical_realism, and temporal_stability, score both seam_continuity and narrative_clarity for the movie, and call submit_judgment."`

The first call's `messages` is `[{"role": "user", "content": user_content}]`.

### 3.10 Sizes

Nothing is resized. The measured and estimated payloads are in Section 0.2: about 0.75 MB of base64 image data for test_story1, about 3 MB for a 20-panel movie, and at most about 11.3 MB at the 25-clip cap under worst-case frame sizes. All are under the 32 MB request limit. The retry (Section 4.6) re-sends everything in a second request of the same size.

---

## 4. Judging-call mechanics

### 4.1 Request parameters

`_create_message` is byte-for-byte judge-stills' function:

```python
def _create_message(client, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
        tools=[{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": SUBMIT_JUDGMENT_SCHEMA,
        }],
        tool_choice={"type": "auto"},
        messages=messages,
    )
```

The call does not pass `temperature`, `top_k`, `top_p`, or `budget_tokens`, and it does not stream.

```python
TOOL_DESCRIPTION = ("Submit your judgment of the clips: for every clip, its panel number and "
                    "1-10 scores for motion_fidelity, physical_realism, and "
                    "temporal_stability; for the movie, a 1-10 narrative_clarity score "
                    "always, plus seam_continuity when you are judging 2 or more clips; and a "
                    "critique naming specific panels by number. You must call this exactly "
                    "once.")
```

### 4.2 API key handling

This is identical to judge-stills:

- The key is read only through `os.environ.get("ANTHROPIC_API_KEY")`. `None` and `""` both count as unset, and the value is never assigned to a variable.
- The client is constructed as `anthropic.Anthropic()`, with no `api_key` argument.
- The key is never printed, logged, or written.
- The raw dumps contain response bodies only.

### 4.3 `SUBMIT_JUDGMENT_SCHEMA`

```python
SUBMIT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "description": "Exactly one entry per clip judged.",
            "items": {
                "type": "object",
                "properties": {
                    "panel": {"type": "integer",
                              "description": "The clip's panel number as an integer, e.g. 3."},
                    "motion_fidelity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "physical_realism": {"type": "integer", "minimum": 1, "maximum": 10},
                    "temporal_stability": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["panel", "motion_fidelity", "physical_realism",
                             "temporal_stability"],
            },
        },
        "movie": {
            "type": "object",
            "properties": {
                "seam_continuity": {"type": "integer", "minimum": 1, "maximum": 10},
                "narrative_clarity": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["narrative_clarity"],
        },
        "critique": {
            "type": "string",
            "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 3').",
        },
    },
    "required": ["clips", "movie", "critique"],
}
```

- There is no `$schema` key, so jsonschema 4.23.0 uses its latest draft. Verified this session: it rejects `True` and `"7"` for an integer, but **accepts `7.0`**. The output writes `int(...)` of every panel and score, so the file always holds JSON integers (T25) **[spec choice]**.
- `seam_continuity` is deliberately not in `movie.required`. Its conditional requirement is enforced in `validate_judgment_input`, mirroring judge-stills' `visual_continuity`.
- There is no `additionalProperties` constraint. Extra keys are tolerated and are not copied to the output.
- There is no `minItems`/`maxItems`. The panel-set check in 4.4 is stricter.

### 4.4 Validation

```python
def validate_judgment_input(tool_input, panels):
    """Raise jsonschema.ValidationError unless tool_input is a complete judgment of exactly
    the judged panels (spec 4.4). panels is the list of judged clip numbers."""
    jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)
    submitted = [entry["panel"] for entry in tool_input["clips"]]
    duplicates = sorted({p for p in submitted if submitted.count(p) > 1})
    if duplicates:
        raise jsonschema.ValidationError(
            "clips lists these panels more than once: %s" % _panel_list(duplicates))
    missing = sorted(set(panels) - set(submitted))
    if missing:
        raise jsonschema.ValidationError(
            "clips is missing these judged panels: %s" % _panel_list(missing))
    extra = sorted(set(submitted) - set(panels))
    if extra:
        raise jsonschema.ValidationError(
            "clips includes panels that were not judged: %s" % _panel_list(extra))
    if len(panels) >= 2 and "seam_continuity" not in tool_input["movie"]:
        raise jsonschema.ValidationError(
            "seam_continuity is required when judging 2 or more clips")
    if len(panels) < 2 and "seam_continuity" in tool_input["movie"]:
        raise jsonschema.ValidationError(
            "seam_continuity must be omitted when judging fewer than 2 clips")
```

- The checks run in this order: schema, duplicates, missing, extra, seam required, seam rejected. The first failure wins.
- Every failure is a `jsonschema.ValidationError`, so it takes the single E18 path: raw dump, `e.message` printed, exit 1, no retry.
- A string panel (`"3"`) or a boolean panel fails the schema (`'3' is not of type 'integer'`). A float panel `3.0` passes, and it compares equal to `3` in the set checks.

### 4.5 `SYSTEM_PROMPT` (normative Python literal)

```python
SYSTEM_PROMPT = (
    "You are an expert film director and visual-effects supervisor judging the video clips "
    "generated for a story by an AI image-and-video generation pipeline. The target output "
    "goal is the most realistic action scenes possible.\n"
    "\n"
    "The story is told in panels. A video model rendered each panel as one short clip from "
    "that panel's Motion: text, and the clips are joined in panel order into one movie. Clip "
    "1 starts from an opening still image described by Panel 1's Opening still: text. Each "
    "later clip starts from the last frame of the previous clip, so the movie is meant to "
    "play as one continuous take.\n"
    "\n"
    "You cannot watch the video. You will receive the panels in panel order. For each panel "
    "you get its \"## Panel N\" header and whichever of its Opening still:, Motion:, and "
    "Narration: text it has, followed by 4 frames sampled from its clip: the first frame, "
    "two evenly spaced middle frames, and the last frame. Each frame is preceded by a label "
    "giving its panel, its position (frame 1 of 4 to frame 4 of 4), and its time in seconds "
    "from the start of that clip. A clip shorter than 4 frames repeats some frames. The "
    "final message tells you exactly how many clips you are judging. Judge motion by "
    "comparing a clip's frames with each other and with its Motion: text; you cannot see "
    "what happens between the sampled frames, so do not reward or penalize anything the "
    "frames cannot show.\n"
    "\n"
    "The movie also has a soundtrack and spoken narration, but you receive no audio. Do not "
    "judge audio, voice, music, or sound effects. The Narration: text is what is spoken "
    "over that panel's clip.\n"
    "\n"
    "Score each clip on these dimensions, each an integer from 1 (worst) to 10 (best):\n"
    "- motion_fidelity: whether the clip actually performs the action its Motion: text "
    "describes.\n"
    "- physical_realism: whether the action, anatomy, and physics are plausible: people, "
    "animals, objects, water, and cloth move and interact the way they would in real "
    "footage.\n"
    "- temporal_stability: whether people, animals, objects, and the setting keep their "
    "identity, shape, and appearance across the clip's frames, with no morphing, melting, "
    "or identity drift.\n"
    "\n"
    "Score the movie as a whole on these dimensions, on the same 1-10 scale:\n"
    "- seam_continuity: whether each clip's first frame continues from the previous clip's "
    "last frame, so the joins between clips read as one continuous take, with no jump in "
    "character appearance, position, setting, lighting, or camera.\n"
    "- narrative_clarity: whether a viewer could follow the story from the visuals together "
    "with the Narration: text.\n"
    "\n"
    "Put exactly one entry in clips for every panel you receive, with its panel number as "
    "an integer. If you are judging fewer than 2 clips, do not include seam_continuity in "
    "your movie object at all: with a single clip there is no join to judge. If you are "
    "judging 2 or more clips, you must include seam_continuity, scored normally.\n"
    "\n"
    "Then write a critique that names specific panels by number (for example, \"Panel 3\") "
    "when identifying strengths and problems.\n"
    "\n"
    "You must deliver your judgment by calling the submit_judgment tool exactly once. Do not "
    "put the judgment in a plain text reply; a response without a submit_judgment call is a "
    "failure."
)
```

The wording is a **[spec choice]**, written from the approved dimension definitions (G6). Tests pin it through `kwargs["system"] == judge_clips.SYSTEM_PROMPT` and through the substring checks in T8c.

### 4.6 Retry and double failure

This is identical to judge-stills (Section 1.4 code):

- If r1 has no `submit_judgment` block, exactly one retry is made with the fresh list `[user(user_content), assistant(r1.content unmodified), user(RETRY_USER_MESSAGE)]`, using the same parameters.
- If r2 also has no block, the result is E17: `clips_judgment.raw.json` containing `[r1, r2]`, and exit 1.
- An `anthropic.APIError` on either call is E16: nothing is written, and r1 is not dumped.
- The timestamp is captured after a block is found and before validation.
- The SDK's default `max_retries=2` is left unchanged.

```python
RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your clip scores, movie scores, and critique. Do not reply with "
                      "plain text.")
```

---

## 5. Output

### 5.1 `clips_judgment.json`

The file is written as UTF-8 with `json.dump(obj, f, indent=2, ensure_ascii=False)`, followed by `"\n"`. Keys appear in exactly this order: `story_id`, `model`, `effort`, `timestamp`, `frames_per_clip`, `usage`, `clips`, `movie`, `critique`.

```json
{
  "story_id": "test_story1",
  "model": "claude-opus-5-5",
  "effort": "high",
  "timestamp": "2026-10-04T20:41:07Z",
  "frames_per_clip": 4,
  "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
  "clips": [
    {"panel": 1, "frames": [0, 48, 96, 144], "motion_fidelity": 0, "physical_realism": 0, "temporal_stability": 0},
    {"panel": 2, "frames": [0, 48, 96, 144], "motion_fidelity": 0, "physical_realism": 0, "temporal_stability": 0}
  ],
  "movie": {"seam_continuity": 0, "narrative_clarity": 0},
  "critique": "string"
}
```

The example is shown compactly. The real file is `indent=2` throughout.

Field rules:

- `story_id`, `model`, `effort`, and `timestamp`: the same as judge-stills (the `MODEL` and `EFFORT` literals; UTC `%Y-%m-%dT%H:%M:%SZ`).
- `frames_per_clip`: the literal `FRAMES_PER_CLIP` (`4`).
- `usage`: judge-stills' rules, summed over r1 and r2. `thinking_tokens` is `null` when no response reports it, never a fabricated 0.
- `clips`:
  - one object per judged clip, sorted ascending by panel, whatever order the judge listed them in;
  - key order `panel`, `frames`, `motion_fidelity`, `physical_realism`, `temporal_stability`;
  - `frames` is the `frame_indices(n)` list actually sampled, with repeats for n < 4;
  - every number is `int(...)`.
- `movie`:
  - key order `seam_continuity`, `narrative_clarity`;
  - `seam_continuity` is JSON `null` exactly when 1 clip was judged.
- `critique`: copied verbatim.

### 5.2 `clips_judgment.raw.json`

This is written only on E17 and E18, and is identical in form to judge-stills' `_write_raw`, with the file name changed:

```python
def _write_raw(story_dir, responses):
    path = os.path.join(story_dir, "clips_judgment.raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"responses": [r.model_dump(mode="json") for r in responses]}, f,
                  indent=2, ensure_ascii=False)
    return path
```

### 5.3 Stdout (success only)

```python
CLIP_TABLE_FORMAT = "  %-5s  %-16s  %-16s  %s"


def format_clip_row(entry):
    return CLIP_TABLE_FORMAT % (entry["panel"], entry["motion_fidelity"],
                                entry["physical_realism"], entry["temporal_stability"])


def format_movie_line(name, value):
    """None is reached only for seam_continuity when exactly 1 clip was judged."""
    if value is None:
        return "  %-20s  n/a (only 1 clip)" % name
    return "  %-20s  %d" % (name, value)
```

Exact output for two clips with panel 1 scores (7, 6, 8), panel 2 scores (4, 3, 5), seam 9, and narrative 2. The strings were computed with Python this session:

```
Clip scores:
  panel  motion_fidelity   physical_realism  temporal_stability
  1      7                 6                 8
  2      4                 3                 5

Movie scores:
  seam_continuity       9
  narrative_clarity     2

--- Critique ---
<full critique text>
```

In the 1-clip case the seam line is `  seam_continuity       n/a (only 1 clip)`.

Formally, stdout is:

```
"Clip scores:\n"
+ CLIP_TABLE_FORMAT % (("panel",) + CLIP_SCORE_KEYS) + "\n"
+ "".join(format_clip_row(e) + "\n" for e in judgment["clips"])
+ "\n"
+ "Movie scores:\n"
+ "".join(format_movie_line(k, judgment["movie"][k]) + "\n" for k in MOVIE_SCORE_KEYS)
+ "\n--- Critique ---\n"
+ critique + "\n"
```

Nothing else goes to stdout: no progress lines, no paths, and no usage.

---

## 6. Error handling

All messages go to stderr, begin with `Error: `, and end with the newline that `print` adds. In the message templates, `<clips_dir>`, `<manifest_path>`, and `<path>` are absolute paths built by `resolve_paths`/`find_clips`.

| # | Condition | Step | Message | Exit | Files written |
|---|---|---|---|---|---|
| E1 | `--story-id` missing, or an unknown argument | 1 | argparse usage error | 2 (`SystemExit`) | none |
| E2 | `clips/` is not a directory | 3 | `Error: clips directory not found: <clips_dir>` | 2 | none |
| E3 | No file matches `CLIP_NAME_RE` | 4 | `Error: no panel_NN.mp4 clips found in <clips_dir>` | 2 | none |
| E4 | Two clip files share a panel number (e.g. `panel_01.mp4`, `panel_001.mp4`) | 5 | `Error: more than one clip for panel <N> in <clips_dir>: <name>, <name>` (the lowest such N; names in `find_clips` order) | 2 | none |
| E5 | More than 25 clips | 6 | `Error: <count> clips found in <clips_dir>; judge-clips sends 4 frames per clip in one request and judges at most 25 clips (100 images, the Anthropic API's per-request image limit for 200k-context models).` | 2 | none |
| E6 | `manifest.json` is not a regular file | 7 | `Error: manifest.json not found: <manifest_path>` | 2 | none |
| E7 | `manifest.json` is not valid JSON or not UTF-8 | 8 | `Error: manifest.json is not valid JSON: <manifest_path>: <exception text>` | 2 | none |
| E8 | The top level is not an object, or `panels` is missing, not a list, or empty | 8 | `Error: manifest.json has no panels list: <manifest_path>` | 2 | none |
| E9 | A panel entry is not an object, or its `index` is missing, not an int, or a bool | 8 | `Error: manifest.json panel entry <position> has no integer index: <manifest_path>` (position is 1-based within `panels`) | 2 | none |
| E10 | Two panels share an `index` | 8 | `Error: manifest.json lists panel index <N> more than once: <manifest_path>` | 2 | none |
| E11 | Clip(s) with no manifest panel of that index | 9 | `Error: clips with no matching panel in manifest.json: <name>, <name>; the clips in <clips_dir> may be stale relative to manifest.json.` | 2 | none |
| E12 | Manifest panel(s) with no clip (partial render) | 10 | `Error: manifest.json panels with no rendered clip in <clips_dir>: <N>, <N>; judge-clips judges only complete renders.` | 2 | none |
| E13 | `ffmpeg` or `ffprobe` not on PATH (ffmpeg is checked first) | 11 | `Error: <tool> not found on PATH; judge-clips needs ffmpeg and ffprobe to extract frames.` | 2 | none |
| E14 | `ANTHROPIC_API_KEY` unset or empty | 12 | `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-clips.` | 1 | none |
| E15 | Any `ClipError` from `probe_clip` or `extract_frames` (first failing clip in panel order) | 13 | `Error: frame extraction failed: <detail>`, where `<detail>` is one of: `ffprobe failed on <path> (exit <rc>): <last stderr line>`; `ffprobe returned unreadable output for <path>`; `<path> has no video stream`; `<path> has no decodable video frames`; `<path> has no usable frame rate (avg_frame_rate=<repr>)`; `ffmpeg failed on <path> (exit <rc>): <last stderr line>`; `ffmpeg wrote <k> frames from <path>; expected <u>`. A blank stderr gives `(no error output)` | 1 | none (temp dir removed) |
| E16 | `anthropic.APIError` on either call | 16 | `Error: Anthropic API call failed: <type(e).__name__>: <str(e)>` | 1 | none |
| E17 | No `submit_judgment` tool_use after one retry | 16 | `Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>` | 1 | `clips_judgment.raw.json` |
| E18 | Schema failure, or a panel-set or seam rule failure (Section 4.4) | 17 | `Error: submit_judgment input failed schema validation: <ValidationError.message>` | 1 | `clips_judgment.raw.json` |

Python exceptions outside this table propagate as tracebacks, the same rule as judge-stills. Examples: an `OSError` opening `manifest.json` for a reason other than absence, and an `OSError` writing an output file.

---

## 7. Testing

### 7.1 Framework, fixtures, and helpers

- File: `tests/test_judge_clips.py`. Use pytest with plain `assert` statements and **no `check()` helper**. The structure is `tests/test_judge_stills.py`'s.
- Load the script:
  ```python
  WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
  _SCRIPT_PATH = os.path.join(WS, "bin", "judge-clips")
  judge_clips = importlib.machinery.SourceFileLoader("judge_clips", _SCRIPT_PATH).load_module()
  ```
- Copy the autouse `_no_real_client(monkeypatch)` from test_judge_stills, retargeted to `judge_clips.anthropic.Anthropic`. Copy `_FakeAnthropic`, `_install_fake`, `_usage`, `_message`, `_tool_response`, `_text_response`, `THINKING_BLOCK` (signature `"sig-abc123"`), and `_listing` verbatim. Set `SENTINEL_KEY = "sk-test-SENTINEL-do-not-leak"`.
- **Real ffmpeg and ffprobe, no skips.** If ffmpeg, ffprobe, or libx264 is missing, the fixture's `subprocess.run(..., check=True)` raises and the tests error out loudly. There is no `pytest.skip` or `importorskip` anywhere.
- **Synthetic clip generator** (verified this session; each frame's luma encodes its frame number):
  ```python
  def _make_clip(path, frames):
      subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                      "-f", "lavfi", "-i",
                      "color=c=black:s=64x48:r=24,format=yuv420p,geq=lum='16+N*8':cb=128:cr=128",
                      "-f", "lavfi", "-t", "2", "-i", "anullsrc=r=48000:cl=mono",
                      "-map", "0:v", "-map", "1:a", "-frames:v", str(frames),
                      "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p",
                      "-c:a", "aac", str(path)], check=True)
  ```
  - Frame N has a uniform luma of `16 + 8N` (limited range). That stays inside 16..235 for N <= 27, so tests use clips of at most 25 frames.
  - `-qp 0` is lossless.
  - The audio stream makes the fixture match real clips (video plus aac).
  - ffprobe on the 25-, 3-, and 1-frame outputs reports `nb_read_frames` of 25, 3, and 1, all at `avg_frame_rate` `24/1`.
- **Frame-number oracle** (verified this session for all 25 frames of the 25-frame clip, 0 mismatches):
  ```python
  def _frame_number(jpeg_bytes, tmp_path):
      path = tmp_path / ("oracle_%s.jpg" % uuid.uuid4().hex)
      path.write_bytes(jpeg_bytes)
      out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                            "-vf", "scale=1:1:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, check=True).stdout
      return round(out[0] * 219 / 255 / 8)
  ```
  The JPEG is full range (`yuvj420p`), so a gray value of g maps back to frame `round(g * 219/255 / 8)`. Observed gray values were 0, 9, 19, 28, ... 224 for frames 0..24.
- Session-scoped fixture `synthetic_clips(tmp_path_factory)` generates `clip25.mp4`, `clip3.mp4`, and `clip1.mp4` once and returns `{25: path, 3: path, 1: path}`.
- `GARBAGE_CLIP = b"not a real clip"`. Precondition tests use dummy bytes `b"dummy clip %d" % n`, because nothing decodes the clips before E14.
- Manifest panel fixtures:
  ```python
  PANEL_1 = {"index": 1, "image_path": "/abs/story/images/panel_01.png", "title": "The Beach at Dawn",
             "panel_text": "A wide shot of a woman in a yellow sundress at the water's edge — dawn.",
             "narration": "She came to the shore for solitude.", "num_frames": 25,
             "motion_prompt": "She takes a slow step into the surf.", "conditioning": "still"}
  PANEL_2 = {"index": 2, "image_path": None, "title": "The Horse Appears",
             "panel_text": "A chestnut horse trots out of the mist.",
             "narration": "A wild horse appeared.", "num_frames": 3,
             "motion_prompt": "A chestnut horse trots out of the mist.", "conditioning": "chain"}

  def _manifest(panels):
      # fps 30 deliberately differs from the clips' real 24 fps, so a label computed from
      # the manifest fps instead of ffprobe's avg_frame_rate is caught (T17).
      return {"schema_version": 3, "story_id": STORY_ID, "fps": 30, "panels": panels}
  ```
  `STORY_ID = "clips-test"`.
- `_make_story(tmp_path, monkeypatch, manifest=_manifest([PANEL_1, PANEL_2]), clips={1: 25, 2: 3}, story_id=STORY_ID, with_clips_dir=True, synthetic=None)`:
  - Runs `monkeypatch.setattr(judge_clips, "WS", str(tmp_path))`.
  - Creates `tmp_path/generated/stories/<story_id>/`.
  - Writes the manifest: `json.dumps(manifest)` for a dict or list, the str as-is, bytes with `write_bytes`, and no file for `None`.
  - Unless `with_clips_dir` is False, creates `clips/`. For each `(number, spec)` in `clips`, writes `clips/panel_%02d.mp4 % number`:
    - an int spec copies `synthetic[spec]`;
    - a bytes spec writes those bytes;
    - a str key in place of an int number is used verbatim as the filename (for `panel_001.mp4`).
  - Returns the story dir as a `pathlib.Path`.
- `_no_subprocess(monkeypatch)` sets `judge_clips.subprocess.run` to a function that raises `AssertionError("subprocess ran")`. `_no_tempdir(monkeypatch)` does the same for `judge_clips.tempfile.TemporaryDirectory`.
- `_record_tempdirs(monkeypatch)` wraps the real `tempfile.TemporaryDirectory` (captured before patching), appends each created `.name` to a list, and returns the list.
- `VALID_INPUT` for 2 clips (deliberately in reverse panel order, with distinct values, and a non-ASCII dash):
  ```python
  VALID_INPUT = {
      "clips": [
          {"panel": 2, "motion_fidelity": 4, "physical_realism": 3, "temporal_stability": 5},
          {"panel": 1, "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}],
      "movie": {"seam_continuity": 9, "narrative_clarity": 2},
      "critique": "Panel 1 holds the dawn light; Panel 2's horse melts by frame 3 — fix it.",
  }
  ```
  `ONE_CLIP_INPUT` is the panel-1 entry only, with `movie == {"narrative_clarity": 2}` and the same critique.

### 7.2 Real (unmocked-API) tests

| ID | Test | Assertion |
|---|---|---|
| T1a | `main([])` | `SystemExit`, code 2 |
| T1b | `main(["--story-md", "x"])` | `SystemExit`, code 2 |
| T2 | `resolve_paths("abc")` with the real `WS`, then with `judge_clips.WS` patched to `str(tmp_path)` | First: `== (WS/generated/stories/abc, .../clips, .../manifest.json)`. Second: `story_dir == os.path.join(str(tmp_path), "generated", "stories", "abc")` |
| T3 | `find_clips` on a dir holding `panel_03.mp4`, `panel_01.mp4`, `panel_100.mp4`, `panel_99.mp4`, `panel_02.mp4`, plus the non-matching `panel_1.mp4`, `panel_01.mp4.provenance.json`, `panel_02.chainseed.png`, `panel_01.mov`, `Panel_04.mp4`, `panel_05.mp4.bak` | Exactly `[(1, …/panel_01.mp4), (2, …02), (3, …03), (99, …99), (100, …100)]` |
| T4a | `frame_indices` for n in 241, 145, 25, 9, 5, 4, 3, 2, 1 | Equals the Section 3.5 table row for row |
| T4b | For n in `range(1, 2001)`: `idx = frame_indices(n)` | `len(idx) == 4`, `idx[0] == 0`, `idx[3] == n - 1`, `idx == sorted(idx)`, and `abs(idx[k] - k * (n - 1) / 3) <= 0.5` for every k |
| T5 | `load_manifest_panels` on a file with `{"schema_version": 3, "panels": [PANEL_2, PANEL_1]}` (out of order) | `== {1: PANEL_1, 2: PANEL_2}`, which pins pairing by `index`, not position |
| T6 | `format_panel_text`: (a) `(1, PANEL_1)`; (b) `(2, PANEL_2)`; (c) `(1, dict(PANEL_1, image_path=None))`; (d) `(1, dict(PANEL_1, panel_text="   "))`; (e) `(3, {"index": 3, "title": "", "motion_prompt": None})`; (f) `(4, {"index": 4, "title": "  Padded  ", "motion_prompt": "  Runs.  ", "narration": 7})`; (g) `(2, dict(PANEL_2, image_path="/abs/story/images/panel_02.png"))` | (a) `"## Panel 1 — The Beach at Dawn\nOpening still: A wide shot of a woman in a yellow sundress at the water's edge — dawn.\nMotion: She takes a slow step into the surf.\nNarration: She came to the shore for solitude."` (b) `"## Panel 2 — The Horse Appears\nMotion: A chestnut horse trots out of the mist.\nNarration: A wild horse appeared."` (c) and (d) are (a) without its `Opening still:` line. (e) `"## Panel 3 —"` (f) `"## Panel 4 — Padded\nMotion: Runs."` (g) equals (b): a still path on a panel other than 1 never adds an `Opening still:` line |
| T7 | `format_frame_label(3, 2, 2.0)`, `(1, 4, 6.0)`, `(2, 1, 1/3)` | `"Panel 3, frame 2 of 4 (t=2.00s)"`, `"Panel 1, frame 4 of 4 (t=6.00s)"`, `"Panel 2, frame 1 of 4 (t=0.33s)"` |
| T8a | `build_user_content` with 2 clips: `{"panel": 1, "text": "T1", "frames": [{"t": 0.0, "data": "A0"}, {"t": 0.5, "data": "A1"}, {"t": 1.0, "data": "A2"}, {"t": 1.5, "data": "A3"}]}` and the same for panel 2 with `"T2"` and data `"B0".."B3"` | The exact 19-block list: `text T1`, then for each k `text format_frame_label(1, k+1, t_k)` and `image {"type": "base64", "media_type": "image/jpeg", "data": "Ak"}`, then the same for panel 2, then `text FINAL_USER_TEXT_MULTI_TEMPLATE % 2`. Also asserts `FINAL_USER_TEXT_MULTI_TEMPLATE % 2` equals the literal string in Section 3.9 |
| T8b | `build_user_content` with the panel-1 clip only | 10 blocks. The last is `{"type": "text", "text": FINAL_USER_TEXT_SINGLE}`, and `FINAL_USER_TEXT_SINGLE` equals the Section 3.9 literal |
| T8c | `SYSTEM_PROMPT` content | Contains each of: `"the most realistic action scenes possible"`, `"you receive no audio"`, `"Do not judge audio"`, `"motion_fidelity:"`, `"physical_realism:"`, `"temporal_stability:"`, `"seam_continuity:"`, `"narrative_clarity:"`, `"do not include seam_continuity"`, `"you must include seam_continuity"`, `"exactly once"`. Has no trailing newline |
| T9a | `probe_clip` on the synthetic 25-, 3-, and 1-frame clips | `(25, Fraction(24))`, `(3, Fraction(24))`, `(1, Fraction(24))` |
| T9b | `probe_clip` real failures: (a) a file holding `GARBAGE_CLIP`; (b) an audio-only mp4 from `ffmpeg -nostdin -v error -f lavfi -t 1 -i anullsrc=r=48000:cl=mono -c:a aac <path>`; (c) a zero-frame mp4 from the `_make_clip` command with `-frames:v 0` and no audio input (`["ffmpeg","-nostdin","-v","error","-y","-f","lavfi","-i","color=c=black:s=64x48:r=24","-frames:v","0","-c:v","libx264","-pix_fmt","yuv420p",path]`) | (a) `ClipError` whose `str` starts with `"ffprobe failed on <path> (exit 1): "`. (b) and (c) `str == "<path> has no video stream"` |
| T9c | `probe_clip` with `judge_clips.subprocess.run` replaced by a recorder returning `subprocess.CompletedProcess(args, rc, stdout=..., stderr=...)`: (a) rc 0, stdout `'{"streams": [{"avg_frame_rate": "24/1", "nb_read_frames": "145"}]}'`; (b) `nb_read_frames` `"0"`; (c) `nb_read_frames` absent; (d) `avg_frame_rate` `"0/0"`; (e) stdout `"not json"`; (f) rc 1, stderr `"line one\nlast line\n\n"`; (g) rc 1, stderr `""` | (a) returns `(145, Fraction(24))`, and the recorded argv `== ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json", "/x/panel_01.mp4"]`. (b), (c) `"/x/panel_01.mp4 has no decodable video frames"`. (d) `"/x/panel_01.mp4 has no usable frame rate (avg_frame_rate='0/0')"`. (e) `"ffprobe returned unreadable output for /x/panel_01.mp4"`. (f) `"ffprobe failed on /x/panel_01.mp4 (exit 1): last line"`. (g) `"... (exit 1): (no error output)"` |
| T10a | `extract_frames(clip25, [0, 8, 16, 24], out)` with a fresh `out` | Returns 4 byte strings, each starting `b"\xff\xd8"`. `_frame_number` of each gives `[0, 8, 16, 24]`. `ffprobe -v error -show_entries stream=width,height -of csv=p=0` of the first one gives `64,48`. `sorted(os.listdir(out)) == ["frame_1.jpg", …, "frame_4.jpg"]` |
| T10b | `extract_frames(clip3, [0, 1, 1, 2], out)`; `extract_frames(clip1, [0, 0, 0, 0], out2)` | clip3: 4 items, `items[1] == items[2]`, oracle `[0, 1, 1, 2]`, and `out` holds exactly 3 files. clip1: 4 identical items, oracle `[0, 0, 0, 0]`, and `out2` holds exactly 1 file |
| T10c | `extract_frames("/x/panel_02.mp4", [0, 1, 1, 2], out)` with the subprocess recorder: (a) rc 0, writes nothing; (b) rc 1, stderr `"bad\nworse\n"` | (a) argv `== ["ffmpeg", "-nostdin", "-v", "error", "-i", "/x/panel_02.mp4", "-map", "0:v:0", "-vf", "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,2)", "-fps_mode", "passthrough", "-q:v", "2", "-f", "image2", os.path.join(out, "frame_%d.jpg")]`, then `ClipError` `"ffmpeg wrote 0 frames from /x/panel_02.mp4; expected 3"`. (b) `"ffmpeg failed on /x/panel_02.mp4 (exit 1): worse"` |
| T10d | Real: `extract_frames(clip3, [0, 1, 2, 5], out)`, then `extract_frames(<GARBAGE_CLIP file>, [0], out3)` | First: `ClipError` `"ffmpeg wrote 3 frames from <clip3>; expected 4"`. Second: `str` starts with `"ffmpeg failed on <path> (exit "` |
| T11a | `validate_judgment_input` with each of `clips`, `movie`, `critique` removed, `panels=[1, 2]` | Raises `ValidationError` |
| T11b | Each of `panel`, `motion_fidelity`, `physical_realism`, `temporal_stability` removed from the panel-1 entry | Raises |
| T11c | Each clip score of the panel-1 entry, then each movie score, set in turn to `0`, `11`, `"7"`, `7.5`, `True` | Raises |
| T11d | The panel-1 entry's `panel` set to `"1"`, `True`, `1.5`, `None` | Raises (schema) |
| T11e | All scores 1; all scores 10; extra keys at the top level, in a clip entry, and in `movie`; every score `7.0` and panels `1.0`/`2.0` | Does not raise in any case |
| T11f | `narrative_clarity` removed, with `panels=[1, 2]` and with the 1-clip input and `panels=[1]` | Raises |
| T12 | Panel-set rules with `panels=[1, 2]`: (a) two entries for panel 1, none for 2; (b) only panel 1; (c) panels 1, 2, 3; (d) panels 1, 1, 3 | `.message`: (a) `"clips lists these panels more than once: 1"`, which shows the duplicate check precedes the missing check. (b) `"clips is missing these judged panels: 2"`. (c) `"clips includes panels that were not judged: 3"`. (d) `"clips lists these panels more than once: 1"` |
| T13 | Seam two-way rule: (a) `VALID_INPUT` without `seam_continuity`, `panels=[1, 2]`; (b) `ONE_CLIP_INPUT` plus `seam_continuity: 5`, `panels=[1]`; (c) `ONE_CLIP_INPUT`, `panels=[1]`; (d) `VALID_INPUT`, `panels=[1, 2]` | (a) `.message == "seam_continuity is required when judging 2 or more clips"`. (b) `.message == "seam_continuity must be omitted when judging fewer than 2 clips"`. (c), (d) do not raise |

**T14: main() preconditions.** Every T14 case applies `_no_subprocess` and `_no_tempdir`, installs `_FakeAnthropic([])`, and sets the key to `SENTINEL_KEY` (so a precondition that wrongly ran after the key check would still reach the subprocess guard). Every case asserts `main(["--story-id", STORY_ID]) == 2` (or the story id named), `stdout == ""`, the exact stderr below plus `"\n"`, `fake.constructions == []`, and an unchanged `_listing(story_dir)` (where the story dir exists).

| ID | Fixture | stderr |
|---|---|---|
| T14a | Manifest present, no `clips/` | `Error: clips directory not found: <clips_dir>` |
| T14b | `clips/` holding only `panel_1.mp4`, `panel_01.mp4.provenance.json`, `panel_02.chainseed.png` | `Error: no panel_NN.mp4 clips found in <clips_dir>` |
| T14c | `panel_01.mp4` and `panel_001.mp4` (dummy), manifest `[PANEL_1]` | `Error: more than one clip for panel 1 in <clips_dir>: panel_001.mp4, panel_01.mp4` |
| T14d | 26 dummy clips `panel_01`..`panel_26`, no manifest | `Error: 26 clips found in <clips_dir>; judge-clips sends 4 frames per clip in one request and judges at most 25 clips (100 images, the Anthropic API's per-request image limit for 200k-context models).` |
| T14e | 25 dummy clips, no manifest (boundary) | `Error: manifest.json not found: <manifest_path>` |
| T14f | 1 dummy clip, no manifest | `Error: manifest.json not found: <manifest_path>` |
| T14g | Manifest text `"{not json"`, then bytes `b"\xff\xfe{}"` | Both start with `Error: manifest.json is not valid JSON: <manifest_path>: ` |
| T14h | Manifest `[]`, `{}`, `{"panels": {}}`, `{"panels": []}` (4 runs) | Each `Error: manifest.json has no panels list: <manifest_path>` |
| T14i | Manifest `{"panels": [{"title": "x"}]}`, `{"panels": [{"index": 1}, {"index": "2"}]}`, `{"panels": [{"index": true}]}`, `{"panels": ["panel"]}` (with clip 1 present) | `... panel entry 1 has no integer index: <manifest_path>`, `... entry 2 ...`, `... entry 1 ...`, `... entry 1 ...` |
| T14j | Manifest `{"panels": [{"index": 1}, {"index": 1}]}` | `Error: manifest.json lists panel index 1 more than once: <manifest_path>` |
| T14k | Clips 1, 2, 3 (dummy); manifest `[PANEL_1, PANEL_2]` | `Error: clips with no matching panel in manifest.json: panel_03.mp4; the clips in <clips_dir> may be stale relative to manifest.json.` |
| T14l | Clips 1, 3 (dummy); manifest panels with indices 1, 2, 3, 4 | `Error: manifest.json panels with no rendered clip in <clips_dir>: 2, 4; judge-clips judges only complete renders.` |
| T14m | Nonexistent story id under the patched `WS` (no story dir at all) | Starts with `Error: clips directory not found:`. `tmp_path/generated` does not exist |
| T14n | A valid 2-clip story (dummy bytes). `judge_clips.shutil.which` patched: (a) `lambda t: None if t == "ffprobe" else "/bin/" + t`; (b) `lambda t: None` | (a) `Error: ffprobe not found on PATH; judge-clips needs ffmpeg and ffprobe to extract frames.` (b) `Error: ffmpeg not found on PATH; ...`, which pins the check order |
| T14o | Clips 1, 3 (dummy); manifest `[PANEL_1, PANEL_2]`, which gives an extra clip (3) and a missing clip (2) | `Error: clips with no matching panel in manifest.json: panel_03.mp4; the clips in <clips_dir> may be stale relative to manifest.json.` This pins E11 before E12 |

### 7.3 Mocked-API tests

| ID | Test | Assertion |
|---|---|---|
| T15 | Key gate. A valid 2-clip story (synthetic clips), `_no_subprocess`, `_no_tempdir`, `_install_fake([])`. Key unset, then `""` | Each run `== 1`. stderr `== "Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-clips.\n"`, stdout `""`, `fake.constructions == []`, `fake.calls == []`, listing unchanged. The subprocess and tempdir guards never fired (the run returned 1, not an `AssertionError`) |
| T16 | Extraction failure. Clip 1 is synthetic 25, clip 2 is `GARBAGE_CLIP`. Key set. `_install_fake([])`. `_record_tempdirs` | `== 1`. stderr starts with `"Error: frame extraction failed: ffprobe failed on %s (exit 1): " % <clip 2 path>`. stdout `""`. `fake.constructions == []`. Exactly 1 tempdir was recorded, and it no longer exists. The story-dir listing is unchanged |
| T17 | Success, 2 clips (`clips={1: 25, 2: 3}`, `_manifest([PANEL_1, PANEL_2])`). Key = sentinel. `_record_tempdirs`. One `_tool_response(VALID_INPUT, _usage(1200, 3400, 2100))` | See the list directly below |
| T18 | Success, 1 clip (`clips={1: 1}`, `_manifest([PANEL_1])`). One `_tool_response(ONE_CLIP_INPUT, _usage(900, 2500, 1500))` | `== 0`. File `clips == [{"panel": 1, "frames": [0, 0, 0, 0], "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}]`. `movie == {"seam_continuity": None, "narrative_clarity": 2}`, and the raw text contains `'"seam_continuity": null'`. stdout `== "Clip scores:\n  panel  motion_fidelity   physical_realism  temporal_stability\n  1      7                 6                 8\n\nMovie scores:\n  seam_continuity       n/a (only 1 clip)\n  narrative_clarity     2\n\n--- Critique ---\n" + critique + "\n"`. `messages[0]["content"]` has 10 blocks. All 4 image `data` values are identical. The labels are `"Panel 1, frame k of 4 (t=0.00s)"` for k = 1..4. The last block's text `== FINAL_USER_TEXT_SINGLE`. `create` was called once |
| T19 | Retry. 2-clip story. r1 is `_text_response` with thinking unreported; r2 is a valid tool response | `== 0`. 2 calls. The second call's messages have roles `user, assistant, user`. `messages[0] ==` the first call's `messages[0]`, with 19 content blocks (all frames re-sent). The assistant content `== r1.content`, with a thinking block whose signature is `"sig-abc123"`. The last content `== RETRY_USER_MESSAGE`. The non-`messages` kwargs are identical across calls. `usage` sums both responses, and `thinking_tokens` is r2's alone. No raw dump |
| T20 | Double failure. r1 and r2 are both text-only | `== 1`. `clips_judgment.raw.json`'s `responses == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]`. No `clips_judgment.json`. stderr `== "Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>\n"`. stdout `""` |
| T21a | Schema-invalid input (panel 2's `temporal_stability: 11`) | `== 1`. 1 call. The raw dump has 1 response. No `clips_judgment.json`. stderr starts with `"Error: submit_judgment input failed schema validation: "` |
| T21b | 2-clip story; the input lists only panel 1 | `== 1`. stderr `== "Error: submit_judgment input failed schema validation: clips is missing these judged panels: 2\n"`. Raw dump with 1 response. 1 call |
| T21c | 2-clip story; `VALID_INPUT` without `seam_continuity` | `== 1`. stderr `== "Error: submit_judgment input failed schema validation: seam_continuity is required when judging 2 or more clips\n"`. Raw dump with 1 response |
| T22 | API error: (a) the first `create` raises `anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))`; (b) r1 is text-only and the retry raises the same error | Both `== 1`. stderr starts with `"Error: Anthropic API call failed: APIConnectionError: "`. 1 and 2 calls respectively. The story-dir listing is unchanged (no output files) |
| T23 | No key leakage: rerun the T17 scenario with responses lacking `output_tokens_details`, and the T20 scenario | The sentinel does not appear in any captured stdout or stderr, `clips_judgment.json`, or `clips_judgment.raw.json`. The T17 rerun's `usage.thinking_tokens is None` |
| T24 | pipeline_log wiring. Read `bin/judge-clips` as text | It contains `'pipeline_log.run_logged("judge-clips", _pipeline_log_story_dir(sys.argv[1:]), main, sys.argv)'`, `"sys.path.insert(0, WS)"`, and `"import pipeline_log"`. It does not contain `"    sys.exit(main())"`. `judge_clips._pipeline_log_story_dir(["--story-id", "abc"]) == os.path.join(WS, "generated", "stories", "abc")`, and `_pipeline_log_story_dir([]) is None` |
| T25 | Float coercion. 1-clip story; tool input `{"clips": [{"panel": 1.0, "motion_fidelity": 7.0, "physical_realism": 6.0, "temporal_stability": 8.0}], "movie": {"narrative_clarity": 2.0}, "critique": "c"}` | `== 0`. In the loaded JSON, `type(v) is int` for every clip and movie number, and the raw text contains `'"panel": 1,'` |

**T17 assertions:**

- `main(["--story-id", STORY_ID]) == 0`.
- The keys of `clips_judgment.json` are exactly `["story_id", "model", "effort", "timestamp", "frames_per_clip", "usage", "clips", "movie", "critique"]`, in that order.
  - `story_id`, `model == "claude-opus-5-5"`, and `effort == "high"`. `timestamp` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`. `frames_per_clip == 4`.
  - `usage == {"input_tokens": 1200, "output_tokens": 3400, "thinking_tokens": 2100}`.
- `clips == [{"panel": 1, "frames": [0, 8, 16, 24], "motion_fidelity": 7, "physical_realism": 6, "temporal_stability": 8}, {"panel": 2, "frames": [0, 1, 1, 2], "motion_fidelity": 4, "physical_realism": 3, "temporal_stability": 5}]`. Each entry's key order is `["panel", "frames", "motion_fidelity", "physical_realism", "temporal_stability"]`. The entries are sorted even though the judge listed panel 2 first.
- `movie == {"seam_continuity": 9, "narrative_clarity": 2}`, with key order `["seam_continuity", "narrative_clarity"]`.
- `critique` equals the input. The raw text contains `"—"` and ends with `"}\n"`.
- None of `clips_judgment.raw.json`, `judgment.json`, or `stills_judgment.json` exists.
- stdout `== "Clip scores:\n  panel  motion_fidelity   physical_realism  temporal_stability\n  1      7                 6                 8\n  2      4                 3                 5\n\nMovie scores:\n  seam_continuity       9\n  narrative_clarity     2\n\n--- Critique ---\n" + critique + "\n"`, and stderr `== ""`.
- `fake.constructions == [((), {})]`, with 1 call.
  - `sorted(kwargs) == ["max_tokens", "messages", "model", "output_config", "system", "thinking", "tool_choice", "tools"]`.
  - The kwarg values equal judge-stills' T10 values, with `system == judge_clips.SYSTEM_PROMPT`, one tool named `submit_judgment`, `input_schema == SUBMIT_JUDGMENT_SCHEMA`, and `description == TOOL_DESCRIPTION`.
- `messages[0]["content"]` has 19 blocks, of types `text`, then `(text, image) x 4`, then `text`, then `(text, image) x 4`, then `text`.
  - Block 0 `== format_panel_text(1, PANEL_1)`. Block 9 `== format_panel_text(2, PANEL_2)`.
  - The label texts are, in order:
    - for panel 1: `"Panel 1, frame 1 of 4 (t=0.00s)"`, `"... frame 2 of 4 (t=0.33s)"`, `"... frame 3 of 4 (t=0.67s)"`, `"... frame 4 of 4 (t=1.00s)"`;
    - for panel 2: `"Panel 2, frame 1 of 4 (t=0.00s)"`, `"... (t=0.04s)"`, `"... (t=0.04s)"`, `"... (t=0.08s)"`.
    - These are 24-fps values. The manifest's fps of 30 would give 0.27, 0.53, 0.80, and 0.03, 0.03, 0.07.
  - Every image block has `source.type == "base64"` and `media_type == "image/jpeg"`. Decoding each image's data and applying `_frame_number` gives `[0, 8, 16, 24]` for panel 1 and `[0, 1, 1, 2]` for panel 2.
  - Block 18 `== FINAL_USER_TEXT_MULTI_TEMPLATE % 2`.
- Exactly 1 tempdir was recorded. Its basename starts with `"judge-clips-"`, it no longer exists, and it is not under `story_dir`.
- The `_listing(story_dir / "clips")` taken before the run equals the one taken after it.

### 7.4 Mutation checks (negative controls)

Before declaring D2 complete, the implementer applies each mutation below to `bin/judge-clips` one at a time, runs `python3 -m pytest tests/test_judge_clips.py`, confirms that at least one named test fails, and reverts the mutation.

| Mutation | Must fail |
|---|---|
| Key check moved after the extraction block | T15 |
| Key check moved after `anthropic.Anthropic()` | T15 |
| PATH check (E13) removed | T14n |
| PATH check order swapped (ffprobe first) | T14n |
| `find_clips` sorts by filename string | T3 |
| `CLIP_NAME_RE` changed to `panel_(\d+)\.mp4` | T3 |
| Duplicate-clip check (E4) removed | T14c |
| `MAX_CLIPS` changed to 26, or `>` changed to `>=` | T14d, T14e |
| `load_manifest_panels` pairs by list position | T5 |
| `isinstance(index, bool)` exclusion removed | T14i |
| Extra-clip check (E11) removed | T14k |
| Missing-clip check (E12) removed | T14l |
| E11 and E12 order swapped | T14o |
| `frame_indices` uses `int()` (floor) instead of `round` | T4a, T4b |
| `frame_indices` uses `n` instead of `n - 1` | T4a, T4b |
| ffprobe uses `stream=nb_frames` without `-count_frames` | T9c |
| `-fps_mode passthrough` removed | T10a, T10b (ffmpeg writes 31 files, so ClipError), T10c |
| Dedup removed (select built from `indices`, not `unique`) | T10b (3 files for 4 expected), T10c |
| File-count check removed | T10c, T10d |
| fps taken from the manifest's `fps` instead of ffprobe | T17 |
| `MEDIA_TYPE` changed to `"image/png"` | T8a, T17 |
| Label block emitted after its image block | T8a, T17 |
| `number == 1` condition removed from the opening-still branch | T6 (g) |
| Opening-still line emitted without the `image_path` condition | T6 (c) |
| Final text always MULTI | T8b, T18 |
| Final text always SINGLE | T8a, T17 |
| Audio sentence removed from `SYSTEM_PROMPT` | T8c |
| Duplicate-panel validation removed | T12 (a), (d) |
| Missing-panel validation removed | T12 (b), T21b |
| Extra-panel validation removed | T12 (c) |
| Seam `>= 2` check removed | T13 (a), T21c |
| Seam `< 2` check removed | T13 (b) |
| `seam_continuity` added to `movie.required` | T13 (c), T18 |
| Output `clips` not sorted by panel | T17 |
| `int()` coercion removed from the output | T25 |
| `seam_continuity` read with `movie["seam_continuity"]` and no presence check | T18 (`KeyError`) |
| `format_movie_line` without the `None` branch | T18 |
| `TemporaryDirectory` replaced by `tempfile.mkdtemp()` without cleanup | T16, T17 |
| Frames written into `clips/` instead of the temp dir | T17 |
| Retry removed | T19 |
| Retry list built without re-sending `user_content` | T19 |
| Raw dump skipped on double failure | T20 |
| Output file named `stills_judgment.json` | T17 |
| `__main__` reverted to `sys.exit(main())` | T24 |

### 7.5 Files and dependencies

| File | Action |
|---|---|
| `bin/judge-clips` | Create, `chmod +x` |
| `tests/test_judge_clips.py` | Create |

- Standard library only, plus `anthropic` and `jsonschema`, which are already used by judge-stills. External binaries: `ffmpeg` and `ffprobe` (>= 5.1 for `-fps_mode`; 9.0.1 installed). The tests also need the `libx264` encoder.
- The tool is not in the deploy package, so the dual-interpreter gate does not apply.

### 7.6 Acceptance and live gates

| ID | Check | Pass condition |
|---|---|---|
| A1 | `python3 -m pytest tests/test_judge_clips.py -v`, run from `WS` **by the main thread**. Counts the implementer reports are not accepted | Every test in Sections 7.2-7.3 passes. There is one test function per ID; multi-case IDs loop inside their function |
| A2 | Section 7.4 mutations | Each mutation makes at least one named test fail |
| R1 | `python3 -m pytest tests/test_judge_stills.py tests/test_pipeline_log.py` | Unchanged results |
| L1 | Live: `bin/judge-clips --story-id test_story1`, with a real key, the main thread or the user running it. Before the run, record `ls -la generated/stories/test_story1/clips` and `shasum generated/stories/test_story1/clips/*` | Exit 0. `clips_judgment.json` has the 9 keys and 5 `clips` entries, each with `"frames": [0, 48, 96, 144]`. `seam_continuity` is an integer. The critique names panels by number. stdout matches Section 5.3. `clips/` listing and checksums are unchanged. `iterate-story.log` gained a `=== stage: judge-clips ===` record with `exit: 0`. No `judge-clips-*` directory remains under `$TMPDIR` |
| L2 | Live, 1-clip case: `bin/judge-clips --story-id final_e2e_verify` (1 clip, 9 frames, schema 2) | Exit 0. `clips[0].frames == [0, 3, 5, 8]`. `movie.seam_continuity` is `null`, and stdout shows `n/a (only 1 clip)`. This confirms the real model omits seam when told there is 1 clip. If the model includes it anyway, the run exits 1 via E18. That is a real finding to report, not a test bug |
| L3 | Live, no API: `STORY_PIPELINE_LOGGED=1 env -u ANTHROPIC_API_KEY bin/judge-clips --story-id mlxdemo`, then `--story-id mystorytest2`. `STORY_PIPELINE_LOGGED=1` keeps the real stories' `iterate-story.log` untouched | Both exit 2 with no key needed. The stderr is `Error: manifest.json panels with no rendered clip in <WS>/generated/stories/mlxdemo/clips: 2; judge-clips judges only complete renders.` and `... mystorytest2/clips: 1, 2, 3, 4; ...` |

---

## 8. Known gaps / open questions

No item here blocks implementation. Each records a spec choice the user may override.

- **G1: the image-limit premise is wrong for this model (verification changed the E5 wording, not the cap).**
  - The brief says 100 images is the API's per-request limit. Per the current docs, 100 is the limit **for models with a 200k-token context window**. `claude-opus-5-5` has a 1M-token window, so its limit is **600**.
  - The approved cap of 25 clips is kept as-is. The E5 message says "100 images, the Anthropic API's per-request image limit for 200k-context models", which is true and states the reason for the number.
  - **Open question for the user:** keep 25, or raise it?
    - The binding constraint would then be the 32 MB request size. At the worst observed frame size (113 KB base64), that allows about 280 images (about 70 clips).
    - At test_story1's mean (37.5 KB), it allows about 850 images, which is above the 600-image count limit.
- **G2: legacy schema-2 manifests are judged as if chained.**
  - In non-chain stories (`frogjump`, `mydemo*`, `mlxdemo`, `final_e2e_verify`), every clip starts from its own still, not from the previous clip's last frame.
  - The system prompt states the chain premise, so `seam_continuity` there is judged against a false claim and will score low by construction. Panels 2..N's own still descriptions (`panel_text`) are also not sent.
  - Spec choice: no `schema_version` or `conditioning` check, because the approved design is manifest-agnostic.
  - Alternatives: refuse multi-clip manifests without `"conditioning"`, or vary the prompt per panel's `conditioning`. This affects pre-chain stories only, and the pipeline has written schema 3 since 2026-09-24.
- **G3: 4 frames cannot show motion between samples.** At 145 frames, the samples are 2 s apart. Flicker, a mid-clip morph that recovers, or a limb that briefly melts can be invisible. The prompt tells the judge not to score what it cannot see. A denser sample is a cost and count trade-off (G1) and was not requested.
- **G4: staleness against `story.md` is unchecked** (out of scope by decision). `bin/iterate-story` and `ltx-movie --force-story --story-only` can rewrite `story.md` and the manifest while the old clips stay in place. E11 catches only clip numbers beyond the manifest. Also see the memory note "ltx-movie --resume ignores model provenance".
- **G5: the SDK's built-in retries** (`max_retries=2`) re-send the full payload on 429, 5xx, and connection errors. This is the same as judge-stills' G10.
- **G6: prompt wording was written for this spec.** That covers `SYSTEM_PROMPT`, `TOOL_DESCRIPTION`, both final texts, `RETRY_USER_MESSAGE`, the frame labels, and every error message. The brainstorm approved the dimensions and layout, not this exact text.
- **G7: text-before-image order.** The docs say images placed before text perform slightly better. The approved layout is panel text, then (label, frame) pairs. Labels before images is the docs' own multi-image pattern.
- **G8: `-select_streams v:0` would pick an attached-picture stream (cover art) if a clip had one.** No pipeline clip does (all 90 surveyed have exactly one video and one audio stream). Such a clip would probe as 1 frame and be judged as a still.

---

## 9. Review Focus

These are the five failure modes most likely to bite that the test suite does not cover. A design review should weigh each one.

1. **ffprobe's frame count disagreeing with the manifest's `num_frames`.**
   - The tool samples from the decoded count and never reads `num_frames`. Today all 90 clips agree three ways: decoded count, header count, and manifest.
   - A disagreement means the manifest no longer describes the clip: a re-render at a different length, or a hand-edited or rebuilt manifest.
   - The tool still samples the clip correctly, and labels are timed from the clip's own fps. But the judge is then scoring a clip against text that may not have produced it, and nothing warns.
   - Mitigation, not designed: warn on stderr when `n != panel["num_frames"]`.
2. **Variable-frame-rate, odd-stream, and audio-only edge cases.**
   - `n` in `select` is decode order, so indices stay exact under VFR. Only the `t=` labels (from `avg_frame_rate`) become approximate.
   - Audio-only and zero-frame files fail cleanly as E15 "has no video stream" (verified).
   - Unverified: a clip whose first video stream is cover art (G8), or an h264 stream with an edit list that makes ffprobe's decode count differ from ffmpeg's `select` numbering. ffprobe and ffmpeg share the same demuxer and decoder, and the file-count check turns any shortfall into E15 rather than a wrong frame. An *excess* of frames cannot occur, because `select` emits only the listed indices.
3. **Request size and count limits.**
   - Measured: test_story1's 20 frames are 0.75 MB base64. A 20-panel movie is estimated at about 3.0 MB, and the 25-clip cap at about 3.75 MB at the mean or about 11.3 MB at the worst observed frame size. The limit is 32 MB.
   - The retry, and up to 2 SDK retries, each re-send the whole payload.
   - Over 20 images, the stricter per-image dimension rule applies (2000 px). The largest clip is 960 px.
   - Larger future renders (for example 1408x960 clips at a higher `-q:v` quality) would raise per-frame size. Re-measure before raising `MAX_CLIPS`.
4. **The judge returning panels as strings, labels, or floats.**
   - `"3"`, `"Panel 3"`, and `true` fail the schema and become E18: a whole Opus call is spent, a raw dump is written, and there is **no retry**, by the approved design.
   - `3.0` passes and is coerced (T25).
   - The schema's `panel` description says "as an integer, e.g. 3", and the system prompt says "with its panel number as an integer". Whether that suffices is only learned from L1 and L2.
   - Similar exposure: the judge putting the 1-clip `seam_continuity` in anyway (E18 by design, as in judge-stills).
5. **Stale extra clips from an earlier, longer render.**
   - E11 refuses a `clips/` that has `panel_06.mp4` when the manifest now has 5 panels, and names the clip.
   - Not caught: same-numbered stale clips. For example, the story was shortened from 5 to 3 panels and re-rendered only partially, or the manifest was rebuilt from a new `story.md` with the same panel count while the old clips stayed.
   - The provenance sidecars (`prompt_sha256`, `output_sha256`) could detect this, but reading them is out of scope (Section 0.4).
   - Also note: `mystorytest2/clips/` has provenance sidecars for panels 1-4 but no `.mp4` files. The tool ignores sidecars, so it correctly reports those panels as missing (L3).
