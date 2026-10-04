# bin/judge-stills -- Design Spec (Phase 3 of the self-improvement loop: still-image judging)

Date: 2026-10-04
Status: The design was approved section by section with the user in brainstorming, and this document transcribes it. Choices made while writing this document to remove ambiguity are marked **[spec choice]**. Items the brainstorm did not settle, and grounding facts that turned out different from the brief when checked against the real code, docs, and files on disk, are listed in Section 8 (Known gaps / open questions). **Read G1 before implementing.** It records that the current pipeline produces only one still per story. That does not block implementation, because the tool is fully defined for 1..N stills, but it limits what the tool can do on stories generated today. G1 is RESOLVED (see Section 8): `visual_continuity` is conditionally required rather than always required, so the 1-still case is fully specified rather than merely tolerated.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`

**Two different "phase" numberings appear in this document. Do not confuse them.**

- **Self-improvement-loop phases** (this project): Phase 1 = `bin/judge-story` (shipped), Phase 2 = `bin/iterate-story` (shipped), Phase 3 = `bin/judge-stills` (this spec). This document says "loop Phase N" when it means these.
- **Pipeline phases** (`bin/ltx-movie`'s own sequence): Phase 1 = story authoring, Phase 2 = stills (`bin/ltx-story-images`), Phase 3 = manifest, Phase 4 = render. This document says "pipeline Phase N" when it means these.

So `bin/judge-stills` (loop Phase 3) judges the output of pipeline Phase 2.

---

## 0. Purpose and scope

### 0.1 Purpose

This is loop Phase 3 of the self-improvement-loop project. It covers judging at the panel/image level.

- Loop Phase 1 (`bin/judge-story`, `docs/superpowers/specs/2026-10-02-judge-story-design.md`) judges the TEXT of a generated `story.md`.
- Loop Phase 2 (`bin/iterate-story`, `docs/superpowers/specs/2026-10-03-iterate-story-design.md`) automates loop Phase 1's judge -> revise -> regenerate -> re-judge cycle.
- Loop Phase 3 extends judging to the GENERATED IMAGES: the `panel_NN.png` stills that pipeline Phase 2 writes.

The tool does one thing. A human runs `bin/judge-stills --story-id <id>` by hand against a story whose stills already exist, and gets back a structured critique grounded in the images:

1. up to four 1-10 scores (`visual_continuity` is conditional on there being at least 2 stills to compare; see Section 4.3 and G1 in Section 8), and
2. a free-text critique that names specific panels.

The tool only observes. It regenerates nothing, proposes no revised prompt, and is not wired into the pipeline.

### 0.2 Grounding evidence

The facts below come from the brief. Each was checked during the writing of this spec against the installed SDK, the current Anthropic docs, the repo source, or the files on disk. Where a check found something different from the brief, the difference is noted here and carried into Section 8.

**Anthropic API: images yes, video no.**

- The installed `anthropic` SDK (0.116.0) has no video content type. `grep -ril video anthropic/types/` returns nothing, and `ContentBlockParam`'s Union has no video variant. Images are the only visual input. This is why judging clips (video) is out of scope: it would need a frame-extraction step that has not been designed.
- Image content block shape, from `anthropic/types/image_block_param.py` and `anthropic/types/base64_image_source_param.py` (re-checked this session; `media_type` is `Literal["image/jpeg", "image/png", "image/gif", "image/webp"]`):
  ```python
  {
      "type": "image",
      "source": {
          "type": "base64",
          "media_type": "image/png",
          "data": "<base64-encoded string>",
      },
  }
  ```
- API limits. The current vision docs (`https://platform.claude.com/docs/en/build-with-claude/vision`, fetched 2026-10-03) **correct the brief's figures**:
  - The per-image cap is **10 MB base64-encoded on the direct Claude API**. The brief's 5 MB is the Amazon Bedrock / Google Cloud figure.
  - Up to **600 images per request**, or 100 for models with a 200k-token context window.
  - When a request has more than **20 images**, a stricter per-image dimension limit applies. The docs say to keep both dimensions at or below 2000 px to stay safe.
  - The total request-size limit is **32 MB** for standard endpoints. For this tool, that cap is the one that matters (G2).
  - Claude 4.7 and later models use the high-resolution tier: 2576 px long edge, 4784 visual tokens. Larger images are downscaled server-side, not rejected. The brief's 1568 px is the standard-tier figure.

  None of these corrections changes the design. No resizing is needed (see below), and the payload risk stays an unsolved known gap (G2).

**Where the stills are.**

- Pipeline Phase 2 runs `bin/ltx-story-images`. It writes each still to `generated/stories/<story_id>/images/panel_%02d.png` (`bin/ltx-story-images:214`), plus an `images.json` sidecar. This tool does not read the sidecar.
- `bin/ltx-story-images` pairs still `i` with the `i`-th panel section, by position, as parsed by `bin/ltx-story-manifest`'s `_parse_prompts_md` (`bin/ltx-story-manifest:175-247`). In its loop, `prompt = _compose_prompt(panels[i - 1]["image"], style)` is written to `panel_%02d.png % i`.

**Still dimensions (correction).**

- The brief said 1280x768. A survey of the first still in every `generated/stories/*/images/` directory found **1280x704 as the most common size** (`bin/ltx-story-images`'s default `--height` is 704). Other sizes seen: 1408x960, 1408x896, 1024x1024, 768x1152, and smaller hardware-gate sizes such as 320x576.
- The largest long edge seen was 1408 px.
- `_still_size()` is at `bin/ltx-movie:781-787` (the brief cited `772-778`). It returns twice the video dimensions.
- The conclusion is unchanged: every observed still is under both tiers' long-edge limits and under the 2000 px many-image rule, so no resizing is needed.

**Still file sizes (correction).**

- The brief said 200 KB-1 MB raw. On disk, first stills range from **141 KB to 1.66 MB raw**, or about 2.2 MB after base64's ~33% overhead.
- That is far under the 10 MB per-image cap.

**How many stills a story has (correction, critical; see G1).**

- Since the narrative-chain redesign (`docs/superpowers/specs/2026-09-24-ltx-movie-narrative-chain-redesign-design.md`, its pipeline table, row 2), `bin/ltx-movie`'s `phase2_stills` runs `bin/ltx-story-images --only 1` (`bin/ltx-movie:794-797`). It renders **only `panel_01.png`**.
- Chain-format stories give only Panel 1 an `Image:` field. Panels 2..N have `Motion:`/`Narration:` only. `bin/ltx-story-images` refuses to render a panel that has no `Image:` field (`bin/ltx-story-images:195`, `Error: panel %d has no Image: field`).
- On-disk survey results:
  - Every chain-format story with two or more panels has exactly one still, for example `test_story1`..`test_story7` (5 panels, 1 still) and `hwgate-*` (2 panels, 1 still).
  - Stories with one still per panel are all pre-chain stories in which every panel has `Image:`, for example `frogjump` (5/5), `band_red_test` (6/6), and `mydemo5` (8/8). Their `story.md` mtimes date from before the chain redesign, 2026-09-11 to 2026-09-13.

**`story.md` panel format.** Checked on `generated/stories/frogjump/story.md` (pre-chain, every panel has `Image:`/`Motion:`/`Narration:`) and `generated/stories/ronin-iterate-test/story.md` (chain format, 20 panels).

- Each panel starts with a header line `## Panel <N> — <title>`.
- The title can be empty. `ronin-iterate-test` has `## Panel 12 —` with nothing after the dash.
- Fields are lines that start with `Image:`, `Motion:`, or `Narration:`. Panel 1 of a `--seed-image` story also has a `Style:` field.
- Panels are separated by blank lines.

**`bin/judge-story`'s judging mechanics as they stand now**, from the real source (`bin/judge-story`, 322 lines):

- Model `claude-opus-5-5`.
- `max_tokens=21333`.
- `thinking={"type": "adaptive"}` plus a top-level `output_config={"effort": "high"}`. The original `{"type": "enabled", "budget_tokens": ...}` shape was rejected by the live API and replaced in commit `3203d8c`; see judge-story's Amendments.
- Exactly one tool, with `tool_choice={"type": "auto"}`.
- One retry in the same conversation when no `tool_use` block comes back. The retry passes `r1.content` back unmodified, including thinking blocks and their signatures.
- On a double failure, a raw-response dump and exit 1.
- Schema validation with `jsonschema`. A validation failure gets no retry: raw dump and exit 1.
- `ANTHROPIC_API_KEY` is checked only via `os.environ.get`, before the client is constructed, and is never read into a variable or logged.
- `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, read at call time by `resolve_paths`.

**Dependencies.** Under `python3` 3.13.0 on this machine, `anthropic` 0.116.0 and `jsonschema` 4.23.0 both import (checked this session).

### 0.3 In scope (the whole deliverable)

| # | Item | File |
|---|---|---|
| D1 | New standalone script | `bin/judge-stills` (new) |
| D2 | Tests for D1 | `tests/test_judge_stills.py` (new) |

No other file is created or modified. In particular, `bin/judge-story`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, and `bin/ltx-movie` are not touched.

### 0.4 Out of scope

- **Judging clips (rendered video).** The API has no video input. Clip judging would need a frame-extraction step that does not exist yet. It is a separate future sub-project.
- **Any automated stills-regeneration loop**, and any `bin/iterate-story`-style orchestration over stills. Also a separate future sub-project.
- A `revised_prompt` field, or any other output meant to feed regeneration. Nothing exists yet to consume one.
- A `--story-md` (direct path) mode. Stills always live under a story-id's own directory.
- Reading `images.json`, including its `source: "seed"` marker and its `status` per panel (G4).
- Sending the `Style:` or `Prompt:` fields of `story.md` to the judge (G5).
- Resizing, recompressing, chunking, or size-based rejection of stills or of the request (G2).
- Checking whether the stills are stale relative to `story.md`, beyond the pairing check in Section 3.3 (G6).
- Supporting any still format other than PNG. `media_type` is always `"image/png"`.
- Retry with backoff for API errors (Section 6).
- Validating `--story-id` values (for example, rejecting `..`). No existing `bin/*` script does this.
- Streaming API responses.
- Wiring the tool into `bin/ltx-movie`'s `_phase_sequence`, or adding it to the deploy package (`tests/test_deploy_pkg.py`). It is a dev-machine tool, like `bin/judge-story`.
- A shared Python module, or importing another `bin/*` file. The parsing logic is duplicated inline (Section 3.2, G7).

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `bin/judge-stills --story-id <id>` resolves `generated/stories/<id>/`, `images/`, and `story.md`, and finds exactly the `panel_NN.png` stills, sorted numerically | T2, T3 |
| SC2 | Each still is paired with the matching panel section of `story.md`, by position, and that section's `Image:`/`Motion:`/`Narration:` text is extracted exactly as Section 3.2 specifies | T4, T5, T9e |
| SC3 | The single user message is an ordered list: a text block then an image block for each still, in panel order, then one final text block. Images are base64 PNG blocks in the exact SDK shape | T6, T7, T10 |
| SC4 | The judging call uses exactly `bin/judge-story`'s current parameters (Section 4.1), with this tool's own system prompt, tool, and schema | T10 |
| SC5 | A successful run writes `stills_judgment.json` (Section 5.1) to the story directory, prints the scores table and the critique (Section 5.3), and exits 0. It does not write or modify `judge-story`'s `judgment.json` | T10 |
| SC6 | Every row of the error table (Section 6) produces the specified exit code and message, and scores are never fabricated | T1, T9, T11, T13, T14, T15 |
| SC7 | No test makes a real network call. If `ANTHROPIC_API_KEY` is unset, the Anthropic client is never constructed | T11; review of the test file |
| SC8 | The value of `ANTHROPIC_API_KEY` never appears in stdout, stderr, or any file written | T16 |

### 0.6 Must-have vs nice-to-have

Every requirement in Sections 1-7 is a must-have. This phase has no nice-to-haves, and nothing beyond these sections is to be built.

---

## 1. Architecture

### 1.1 Script conventions

`bin/judge-stills` follows the existing `bin/*` convention, modeled directly on `bin/judge-story`:

- Plain executable script: shebang `#!/usr/bin/env python3`, module docstring at the top, no file extension, executable bit set (`chmod +x`).
- Loaded as `__main__`. It defines `def main(argv=None):`, which returns an `int`, and the file ends with:
  ```python
  if __name__ == "__main__":
      sys.exit(main())
  ```
- It imports nothing from another `bin/*` file and introduces no shared module, the same as `bin/judge-story`.
  - It does **not** load `bin/ltx-story-manifest` through `SourceFileLoader` the way `bin/ltx-story-images` does.
  - It duplicates that tool's two panel regexes and its section and field logic inline instead (Section 3.2).
  - This is a deliberate trade-off. See G7.
- Top-level imports, in this order: `argparse`, `base64`, `datetime`, `json`, `os`, `re`, `sys`, then `anthropic` and `jsonschema`.
  - `anthropic` and `jsonschema` are imported at module top level, as in `bin/judge-story`, so that tests can monkeypatch `judge_stills.anthropic.Anthropic`.
- Docstring: modeled on `bin/judge-story`'s, in prose of the implementer's choosing. It must state:
  - the purpose (Section 0.1), naming this as loop Phase 3 and citing this spec's path;
  - the usage line (Section 2.1);
  - that it requires `ANTHROPIC_API_KEY`;
  - the exit codes (Section 2.5);
  - that on a judging failure the raw responses go to `stills_judgment.raw.json` and no scores are reported.

### 1.2 Execution sequence

`main(argv)` performs these steps in this exact order. **[spec choice on ordering: every local file precondition runs before the env check, as in `bin/judge-story`; the brief's order (a) images, (b) `story.md`, (c) key is kept, and the pairing check, which needs `story.md`, sits between (b) and (c).]**

1. Parse arguments (Section 2.1). argparse errors exit 2 through argparse's own `SystemExit(2)`.
2. `story_dir, images_dir, story_md_path = resolve_paths(args.story_id)` (Section 2.2).
3. If `images_dir` is not an existing directory (`os.path.isdir`): print E2 to stderr and return 2.
4. `stills = find_stills(images_dir)` (Section 3.1). If it is empty: print E3 to stderr and return 2.
5. If `story_md_path` is not an existing regular file (`os.path.isfile`): print E4 to stderr and return 2.
6. Read `story.md` as UTF-8. `panels = parse_panels(story_md_text)` (Section 3.2).
7. Pairing check (Section 3.3). Go through `stills` in order. For the first `(index, path)` with `not 1 <= index <= len(panels)`, print E5 to stderr and return 2.
8. Build `entries = [(format_panel_text(panels[index - 1]), encode_still(path)) for index, path in stills]`, then `user_content = build_user_content(entries)` (Sections 3.4-3.6).
9. If `ANTHROPIC_API_KEY` is unset or empty: print E6 to stderr and return 1. This happens before `anthropic.Anthropic` is constructed.
10. Construct `anthropic.Anthropic()` with no arguments.
11. Run the judging call and its single possible retry (Section 4.6).
12. Validate the tool input: `validate_judgment_input(block.input, len(stills))` (Section 4.4). This runs the JSON Schema check and then, when `len(stills) >= 2`, the additional check that `visual_continuity` is present. Either kind of failure is handled identically: raw dump, print E9, return 1 (no retry).
13. Write `stills_judgment.json` (Section 5.1).
14. Print the stdout summary (Section 5.3). Return 0.

### 1.3 Internal names [spec choice]

The implementer must use these names so that tests can target them:

| Name | Kind | Responsibility |
|---|---|---|
| `WS` | module global | `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` |
| `MODEL` | module constant | `"claude-opus-5-5"` |
| `EFFORT` | module constant | `"high"` |
| `MAX_TOKENS` | module constant | `21333`. Same value and rationale as `bin/judge-story` (the SDK's largest non-streaming `max_tokens` without an explicit `timeout=`) |
| `TOOL_NAME` | module constant | `"submit_judgment"` |
| `TOOL_DESCRIPTION` | module constant (str) | Section 4.1 |
| `SCORE_KEYS` | module constant | `("prompt_fidelity", "visual_continuity", "rendering_quality", "composition")`. The order used in the output file and on stdout |
| `SUBMIT_JUDGMENT_SCHEMA` | module constant (dict) | Section 4.3 |
| `SYSTEM_PROMPT` | module constant (str) | Section 4.5 |
| `FINAL_USER_TEXT_SINGLE` | module constant (str) | Section 3.6. Final text block used when exactly 1 still is judged |
| `FINAL_USER_TEXT_MULTI_TEMPLATE` | module constant (str, one `%d` placeholder) | Section 3.6. Final text block template used when 2 or more stills are judged, formatted with the stills count |
| `RETRY_USER_MESSAGE` | module constant (str) | Section 4.6 |
| `MEDIA_TYPE` | module constant | `"image/png"` |
| `STILL_NAME_RE` | module constant | `re.compile(r"panel_(\d{2,})\.png")` (Section 3.1) |
| `PANEL_HEADER_RE` | module constant | `re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$")`. Verbatim copy of `bin/ltx-story-manifest:81` |
| `PANEL_LABEL_RE` | module constant | `re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")`. Verbatim copy of `bin/ltx-story-manifest:82` |
| `build_parser()` | function | Returns the `argparse.ArgumentParser` (Section 2.1) |
| `resolve_paths(story_id)` | function | Returns `(story_dir, images_dir, story_md_path)`. Reads `WS` at call time |
| `find_stills(images_dir)` | function | Section 3.1. Returns a list of `(index, path)` |
| `parse_panels(story_md_text)` | function | Section 3.2. Pure |
| `format_panel_text(panel)` | function | Section 3.4. Pure |
| `encode_still(path)` | function | Section 3.5 |
| `build_user_content(entries)` | function | Section 3.6. Pure |
| `find_tool_use(response)` | function | Returns the first content block with `type == "tool_use"` and `name == TOOL_NAME`, else `None`. Identical to `bin/judge-story` |
| `validate_judgment_input(tool_input, stills_count)` | function | Runs `jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)`, then the additional `visual_continuity`-presence check for the 2+-stills case (Section 4.4). `stills_count` is `len(stills)` |
| `format_score_line(name, value)` | function | Section 5.3. Returns one stdout line for a score, formatting `None` as the `n/a` text instead of `%d` |
| `_create_message(client, messages)` | function | One API call with the Section 4.1 parameters |
| `_write_raw(story_dir, responses)` | function | Writes `stills_judgment.raw.json` and returns its path (Section 5.2) |
| `main(argv=None)` | function | Section 1.2. Returns the exit code |

---

## 2. CLI

### 2.1 Synopsis

```
bin/judge-stills --story-id <id>
```

`build_parser()`:

- `argparse.ArgumentParser(prog="judge-stills", description="Judge a story's generated panel stills with Claude against the story text.")` **[spec choice: description wording]**
- `parser.add_argument("--story-id", dest="story_id", metavar="ID", required=True, help="judge generated/stories/ID/images/panel_NN.png against generated/stories/ID/story.md")`
- No other arguments.
  - There is no `--story-md` alternative, unlike `bin/judge-story`. Stills always live under a story-id's own directory, so there is no use case for an arbitrary path.
  - There is no `--target-panels`; nothing here is revised.

A missing `--story-id`, or an unknown flag such as `--story-md`, is an argparse error: usage goes to stderr and the process raises `SystemExit(2)`.

### 2.2 Path resolution (`resolve_paths`)

This uses the same inline pattern as `bin/judge-story`'s `--story-id` branch. `WS` is read at call time, not import time:

```python
story_dir = os.path.join(WS, "generated", "stories", story_id)
images_dir = os.path.join(story_dir, "images")
story_md_path = os.path.join(story_dir, "story.md")
return story_dir, images_dir, story_md_path
```

### 2.3 Preconditions

Checked in the Section 1.2 order:

1. `images/` must exist and contain at least one still that matches `STILL_NAME_RE`. Otherwise exit 2 (E2 or E3).
2. `story.md` must exist in the story directory. Otherwise exit 2 (E4).
3. Every still must pair with a panel section (Section 3.3). Otherwise exit 2 (E5). **[spec choice: added; not in the brief's precondition list]**
4. `ANTHROPIC_API_KEY` must be set and non-empty. Otherwise exit 1 (E6). This is checked before the client is constructed.

### 2.4 Output location

All output files are written to `story_dir`, the story directory root. That is the same directory where `bin/judge-story` writes `judgment.json`. The files are `stills_judgment.json`, or on failure `stills_judgment.raw.json`.

- Existing files with those names are overwritten without a prompt **[spec choice]**.
- Files from an earlier run are never deleted. A failed run leaves any earlier `stills_judgment.json` in place.
- The names are distinct from `bin/judge-story`'s `judgment.json` and `judgment.raw.json`, and from `bin/iterate-story`'s `.vN` archives and `run-summary.json`, so running this tool can never overwrite their outputs **[spec choice: the `stills_` prefix on the raw dump name too]**.

### 2.5 Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Runtime or API failure: E6-E9 |
| 2 | Argument or precondition failure: E1-E5. This matches `bin/judge-story` and the repo-wide convention |

---

## 3. Image encoding and message construction

### 3.1 Still discovery (`find_stills`)

```python
def find_stills(images_dir):
    found = []
    for name in os.listdir(images_dir):
        m = STILL_NAME_RE.fullmatch(name)
        if m:
            found.append((int(m.group(1)), os.path.join(images_dir, name)))
    found.sort(key=lambda item: (item[0], item[1]))
    return found
```

- The brief says the directory is "glob-matched". It is implemented with `os.listdir` plus a regex `fullmatch` rather than `glob.glob` **[spec choice]**. `glob` would treat `[`, `]`, `*`, and `?` in a story-id as wildcards. The set of files matched is the set the brief describes.
- `STILL_NAME_RE` is `panel_(\d{2,})\.png`, which takes two or more digits **[spec choice]**.
  - This matches every name that `bin/ltx-story-images`'s `"panel_%02d.png" % i` can produce, including three-digit names once `i >= 100`.
  - It rejects `panel_1.png`, `panel_01.jpg`, `panel_01.png.bak`, `Panel_01.png`, and `images.json`.
- Sorting is numeric on the captured index. For example, `panel_99.png` comes before `panel_100.png`, even though a string sort would reverse them. The path is a tie-breaker that keeps the order deterministic: `panel_01.png` and `panel_001.png` would both have index 1, and both would be sent.
- Gaps are allowed. If `panel_02.png` is missing, for example because `bin/ltx-story-images` blocked it on content safety, the stills that do exist are sent and panel 2 is not.
- No `os.path.isfile` filter is applied. A non-file entry named like a still is not a case this tool handles. If one exists, reading it raises an uncaught `OSError` (Section 6).

### 3.2 Panel-text parsing (`parse_panels`)

Normative algorithm **[spec choice: a verbatim duplicate of `bin/ltx-story-manifest`'s `_parse_prompts_md` section-splitting and field-collection rules, `bin/ltx-story-manifest:202-245`, reduced to the three fields this tool sends]**:

```python
def parse_panels(story_md_text):
    sections = []
    current = None
    for line in story_md_text.splitlines():
        if PANEL_HEADER_RE.match(line):
            if current is not None:
                sections.append(current)
            current = {"header": line, "body": []}
            continue
        if line.startswith("##"):
            if current is not None:
                sections.append(current)
                current = None
            continue
        if current is not None:
            current["body"].append(line)
    if current is not None:
        sections.append(current)

    panels = []
    for section in sections:
        fields = {"Image": [], "Motion": [], "Narration": [], "Prompt": [], "Style": []}
        open_field = None
        for line in section["body"]:
            m = PANEL_LABEL_RE.match(line)
            if m:
                open_field = m.group(1)
                value = m.group(2).strip()
                if value:
                    fields[open_field].append(value)
                continue
            if open_field is not None and line.strip():
                fields[open_field].append(line.strip())
        panels.append({"header": section["header"],
                       "image": " ".join(fields["Image"]),
                       "motion": " ".join(fields["Motion"]),
                       "narration": " ".join(fields["Narration"])})
    return panels
```

Rules this encodes. Each one is identical to the parser that `bin/ltx-story-images` used to render the stills:

- A panel section starts at a line matching `PANEL_HEADER_RE`: `## Panel <N> <dash> <title>`, where the dash is an em dash, an en dash, or `-`, and the title may be empty.
- `header` is that line exactly as it appears, with no stripping.
- Any other line that starts with `##` closes the current section, and its lines are not attached to any panel. Examples are a `## Notes` heading, or a malformed panel header with no dash.
- Inside a section, a line matching `PANEL_LABEL_RE` opens that field. Its inline value is stripped and kept if it is non-empty.
- After that, non-blank unlabeled lines are stripped and appended to whichever field is open. Values are space-joined.
- `Prompt:` and `Style:` are recognized so that they close the field that was open before them. Without this, a `Style:` line in a seed-image story's Panel 1 would be appended to `Image`. Their values are then discarded, as Section 0.4 and G5 specify.
- A field that never appears is `""`.
- The `N` in the header is captured by the regex but not used. Pairing is by position (Section 3.3).
- `parse_panels` is pure: no I/O and no globals other than the two regex constants.
- This was verified while writing this spec. The algorithm above was run against `generated/stories/frogjump/story.md` (5 panels), `ronin-iterate-test/story.md` (20 panels, chain format, including the empty-title `## Panel 12 —`), and `test_story7/story.md` (5 panels). Its `image`/`motion`/`narration` output equals `bin/ltx-story-manifest._parse_prompts_md`'s, field for field, with the same panel count. It also reproduces the T4a and T5 expected values in Section 7 exactly.

### 3.3 Pairing stills with panels

Still `(index, path)` pairs with `panels[index - 1]`, the `index`-th panel section in file order **[spec choice: position, not the header's own number]**.

- `bin/ltx-story-images` writes `panel_%02d.png % i` from `panels[i - 1]` of the same parser, so position is exactly how each still was actually produced.
- In every well-formed `story.md`, headers run 1..N in order (`bin/ltx-movie`'s Phase 1 validation), so position and header number agree.
- The header line, including its own number, is still what the judge sees (Section 3.4).

If any still has `index < 1` or `index > len(panels)`, the run fails with E5 (exit 2) before any API work. **[spec choice; see G6]**

- Example causes: `panel_00.png`, or a `panel_07.png` left behind after `story.md` was regenerated with fewer panels.
- Judging a still against missing or wrong text would produce a misleading critique.
- The error names the first offending still in sorted order.

Panels that have no still are not sent at all **[spec choice; see G1]**. The user message carries one text-plus-image pair per still found, and nothing for panels without one.

### 3.4 Panel text block (`format_panel_text`)

```python
def format_panel_text(panel):
    lines = [panel["header"]]
    for label, key in (("Image", "image"), ("Motion", "motion"), ("Narration", "narration")):
        if panel[key]:
            lines.append("%s: %s" % (label, panel[key]))
    return "\n".join(lines)
```

- The output is the header line, then one line for each non-empty field, in the fixed order `Image`, `Motion`, `Narration`. There is no trailing newline.
- A chain-format panel 2 renders as its header plus its `Motion:` and `Narration:` lines.
- A panel with none of the three fields renders as its header alone. That is not an error.

### 3.5 Encoding (`encode_still`)

```python
def encode_still(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")
```

- The bytes are read raw. There is no decoding, no resizing, and no recompression.
- `media_type` is always `MEDIA_TYPE` (`"image/png"`), because the pipeline always writes PNG.
- The file's magic bytes are not checked **[spec choice]**. A non-PNG file named `panel_NN.png` is rejected by the API as an `invalid_request_error`, which surfaces as E7.

### 3.6 User message content (`build_user_content`)

`entries` is a list of `(panel_text, image_b64)` in still order. The function returns a list of content blocks:

```python
def build_user_content(entries):
    content = []
    for panel_text, image_b64 in entries:
        content.append({"type": "text", "text": panel_text})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": MEDIA_TYPE,
                                   "data": image_b64}})
    count = len(entries)
    if count >= 2:
        final_text = FINAL_USER_TEXT_MULTI_TEMPLATE % count
    else:
        final_text = FINAL_USER_TEXT_SINGLE
    content.append({"type": "text", "text": final_text})
    return content
```

- For each still, in order: its panel's text block, then immediately its image block. This lets the model tie each image to its story text, panel by panel.
- One final text block comes last. There is no introductory block. The framing lives in `SYSTEM_PROMPT` (Section 4.5).
- The content list always has `2 * len(entries) + 1` blocks.
- **The final text block states the actual stills count and, for the 2+-stills case, the word count, so the judge knows which case applies without counting images itself** (G1 resolution; see Section 8). It branches on `count = len(entries)`:
  - `count >= 2` uses `FINAL_USER_TEXT_MULTI_TEMPLATE % count`.
  - `count < 2` (in practice always exactly 1, since `main()` never calls this with zero stills — E3 rejects that earlier) uses `FINAL_USER_TEXT_SINGLE` verbatim.
- `FINAL_USER_TEXT_SINGLE` **[spec choice, verbatim]**: `"You are judging 1 still above against its panel text. There is only one still, so there is nothing to compare for visual_continuity: omit it from your scores object entirely and call submit_judgment with prompt_fidelity, rendering_quality, and composition only."`
- `FINAL_USER_TEXT_MULTI_TEMPLATE` **[spec choice, verbatim; `%d` is the stills count]**: `"You are judging all %d stills above against their panel text. Score all four dimensions, including visual_continuity, and call submit_judgment."`
- The first call's `messages` is `[{"role": "user", "content": user_content}]`.

### 3.7 No resizing

Every observed still is at most 1408 px on its long edge and 1.66 MB raw (about 2.2 MB base64). That is under the API's per-image cap (10 MB base64 on the direct API) and under every resolution limit in Section 0.2, so nothing is resized.

The total size of the request is a known risk that this spec does not solve: G2. No chunking, compression, or size-based rejection is designed here.

---

## 4. Judging-call mechanics

### 4.1 Request parameters

Every `client.messages.create(...)` call, made through `_create_message`, uses exactly these parameters. They are the same as `bin/judge-story`'s current `_create_message`:

```python
client.messages.create(
    model=MODEL,                         # "claude-opus-5-5"
    max_tokens=MAX_TOKENS,               # 21333
    thinking={"type": "adaptive"},
    output_config={"effort": EFFORT},    # "high"
    system=SYSTEM_PROMPT,
    tools=[{
        "name": TOOL_NAME,               # "submit_judgment"
        "description": TOOL_DESCRIPTION,
        "input_schema": SUBMIT_JUDGMENT_SCHEMA,
    }],
    tool_choice={"type": "auto"},
    messages=messages,
)
```

- Do NOT use `thinking={"type": "enabled", "budget_tokens": ...}`. The live API rejects it for this model (judge-story Amendments, commit `3203d8c`).
- `tool_choice` must be `{"type": "auto"}`. Extended thinking cannot force a specific tool, so the script offers exactly one tool and `SYSTEM_PROMPT` requires the call.
- Do not pass `temperature`, `top_k`, or `top_p`.
- Do not stream. Use the plain non-streaming `messages.create`.
- `TOOL_DESCRIPTION` **[spec choice, verbatim]**: `"Submit your judgment of the stills: 1-10 scores for prompt_fidelity, rendering_quality, and composition always, plus visual_continuity when you are judging 2 or more stills, and a critique naming specific panels by number. You must call this exactly once."`

### 4.2 API key handling

- Check the key only with `os.environ.get("ANTHROPIC_API_KEY")`. `None` and `""` both count as unset. Never assign the value to a variable.
- If it is unset, print E6 to stderr and return 1, without constructing `anthropic.Anthropic`.
- If it is set, construct `anthropic.Anthropic()` with no `api_key` argument. The SDK reads the environment itself.
- The key value is never printed, logged, interpolated into a message, or written to a file. The raw dumps (Section 5.2) are API response bodies; they contain neither the key nor the request's images.

### 4.3 `submit_judgment` input schema (`SUBMIT_JUDGMENT_SCHEMA`)

```json
{
  "type": "object",
  "properties": {
    "scores": {
      "type": "object",
      "properties": {
        "prompt_fidelity":    {"type": "integer", "minimum": 1, "maximum": 10},
        "visual_continuity":  {"type": "integer", "minimum": 1, "maximum": 10},
        "rendering_quality":  {"type": "integer", "minimum": 1, "maximum": 10},
        "composition":        {"type": "integer", "minimum": 1, "maximum": 10}
      },
      "required": ["prompt_fidelity", "rendering_quality", "composition"]
    },
    "critique": {
      "type": "string",
      "description": "Free-text critique. Name specific panels by number (e.g. 'Panel 3')."
    }
  },
  "required": ["scores", "critique"]
}
```

- There is no `revised_prompt` field. Loop Phase 3 only observes, and nothing exists to consume one.
- No `additionalProperties` constraint is added. Extra keys are tolerated and ignored, and only the specified keys are copied into `stills_judgment.json`. This matches `bin/judge-story`.
- **Schema change (G1 resolution): `visual_continuity` moves out of `scores`'s `required` array.** Its own property definition (`{"type": "integer", "minimum": 1, "maximum": 10}`) is unchanged; only its membership in `required` changes. The schema goes from 4 unconditionally required score fields to **3 always-required** (`prompt_fidelity`, `rendering_quality`, `composition`) **+ 1 conditionally-required** (`visual_continuity`, required only when 2 or more stills are judged).
  - JSON Schema (the draft this project uses, with no `$schema` key) cannot express "required only when some external fact — the runtime stills count — holds." `required` is static and has no access to data outside the instance being validated. So the condition is enforced in two other places instead:
    - the system prompt (Section 4.5) and the final user-message text block (Section 3.6), which tell the judge which case applies and what to do in each; and
    - for the 2+-stills case only, an additional check in the script itself, run immediately after `jsonschema.validate` succeeds (Section 4.4), since the schema alone cannot catch a judge that ignores the instruction.
  - For the <2-stills case, `visual_continuity`'s absence from `tool_input` is schema-valid and expected; nothing further checks it.

### 4.4 Tool-input validation

This is mostly identical to `bin/judge-story`, with one addition for the conditional `visual_continuity` requirement (**[spec choice]**, the point 3 decision below):

- `find_tool_use(response)` scans `response.content` in order and returns the first block with `block.type == "tool_use"` and `block.name == "submit_judgment"`, or `None`.
- `validate_judgment_input(tool_input, stills_count)` is:
  ```python
  def validate_judgment_input(tool_input, stills_count):
      jsonschema.validate(instance=tool_input, schema=SUBMIT_JUDGMENT_SCHEMA)
      if stills_count >= 2 and "visual_continuity" not in tool_input["scores"]:
          raise jsonschema.ValidationError(
              "visual_continuity is required when judging 2 or more stills"
          )
  ```
  Called as `validate_judgment_input(block.input, len(stills))` (Section 1.2, step 12). Because the schema has no `$schema` key, `jsonschema.validate` uses its latest draft, which does not count booleans as integers.
- **[spec choice, point 3 of the G1 fix]:** for the 2+-stills case, `visual_continuity`'s absence from `tool_input` is schema-valid (it is unconditionally optional in `SUBMIT_JUDGMENT_SCHEMA`) but is a **failure of instruction-following** by the judge: the system prompt and the final user-message text block both told it, for this stills count, to score and include `visual_continuity`. Two ways to handle this were considered:
  - (i) accept it silently and write `scores.visual_continuity` as JSON `null` even though 2+ stills were judged, treating it the same as the legitimate <2-stills case; or
  - (ii) treat it as equivalent to any other invalid/incomplete judgment: the same raw-dump-and-exit-1 handling the error table already gives every other schema-validation failure.
  - **Recommendation taken: (ii).** A `null` `visual_continuity` must mean "there was nothing to compare," never "the judge was supposed to score this and didn't." Collapsing both into `null` would make the output file lie about why the field is missing, and would hide a real judge failure as if it were the ordinary 1-still case. So the check above is implemented as an extra step in `validate_judgment_input`, *not* as a JSON Schema construct (JSON Schema cannot express "required if an external count is 2+"; see Section 4.3), raised as a `jsonschema.ValidationError` so it flows through the exact same E9 path — same message format, same `stills_judgment.raw.json` dump, same exit code — as a genuine schema-validation failure. No new error code was added.
- Validation (the combination of the schema check and the check above) rejects:
  - a missing `scores` or `critique`;
  - a missing `prompt_fidelity`, `rendering_quality`, or `composition` (always required by the schema);
  - a missing `visual_continuity` when `stills_count >= 2` (rejected by the additional check above, not by the schema's `required` array — the schema itself allows `visual_continuity` to be absent in every case; see Section 4.3);
  - a score below 1 or above 10, for any score key that is present;
  - a non-integer score, including strings, floats, and booleans, for any score key that is present.
  - A missing `visual_continuity` when `stills_count < 2` is **not** rejected; it is the expected shape (Section 5.1).
- On a validation failure (from either the schema or the additional check) there is no retry. Write `stills_judgment.raw.json` with every response received so far, print E9, and return 1.

### 4.5 `SYSTEM_PROMPT`

**[spec choice, verbatim text written from the approved dimension definitions; see G8]**:

```
You are an expert visual director judging the still images generated for a story by an AI image-and-video generation pipeline. Each still was generated by an image model from the text of one story panel. The target output goal is the most realistic action scenes possible.

You will receive the panels in panel order. For each panel you get its "## Panel N" header and whichever of its Image:, Motion:, and Narration: text it has, immediately followed by the still generated for that panel. Panels that have no generated still are not included. The final message tells you exactly how many stills you are judging.

Score the stills on these dimensions, each an integer from 1 (worst) to 10 (best):
- prompt_fidelity: whether each still actually depicts what that panel's Image: and Motion: text describes.
- visual_continuity: whether character appearance, setting, lighting, and style actually stay consistent across the stills as rendered. Judge the rendered images themselves, not whether the text descriptions are consistent with each other.
- rendering_quality: rendering artifacts, anatomical errors, loss of detail, a flattened or overly stylized look where photorealism was intended, and general image quality.
- composition: whether each still's shot type and framing match what the panel text specifies, and whether the still is well composed.

If you are judging fewer than 2 stills, do not include visual_continuity in your submit_judgment call at all: with a single still there is nothing to compare it against. If you are judging 2 or more stills, you must include visual_continuity, scored normally like the other three dimensions.

Then write a critique that names specific panels by number (for example, "Panel 3") when identifying strengths and problems.

You must deliver your judgment by calling the submit_judgment tool exactly once. Do not put the judgment in a plain text reply; a response without a submit_judgment call is a failure.
```

Implement it as one Python string built from adjacent literals, the way `bin/judge-story` builds its `SYSTEM_PROMPT`.

- **[spec choice, G1 resolution]**: the fourth paragraph above (the `visual_continuity` conditional instruction) is new relative to the version of this spec the brainstorm first approved. It is the system-prompt half of the point-2 requirement; Section 3.6's final user-message text block is the other half, and states the concrete count so the judge does not have to infer which case applies from the image count itself.

- Each paragraph break above is `"\n\n"`, and each bullet line ends in `"\n"`.
- There is no trailing newline after the last sentence.
- The text must match the block above character for character.

### 4.6 Retry and double failure

This is identical to `bin/judge-story`'s flow, with this tool's names:

1. Call 1 sends `[{"role": "user", "content": user_content}]`. Let `r1` be the response.
2. If `find_tool_use(r1)` returns a block, go to validation (Section 4.4).
3. Otherwise make exactly one retry in the same conversation:
   ```python
   [
       {"role": "user", "content": user_content},          # the same list, images included
       {"role": "assistant", "content": r1.content},       # unmodified, thinking blocks and signatures included
       {"role": "user", "content": RETRY_USER_MESSAGE},
   ]
   ```
   - The parameters are the same as Section 4.1. Let `r2` be the response.
   - The retry sends every image again. The request is about the same size as call 1, so the size limit is the same (G2).
   - `RETRY_USER_MESSAGE` **[spec choice, verbatim]**: `"You did not call the submit_judgment tool. Call submit_judgment now with your scores and critique. Do not reply with plain text."`
4. If `find_tool_use(r2)` returns a block, go to validation.
5. Otherwise it is a double failure:
   - Write `stills_judgment.raw.json` (Section 5.2) containing `[r1, r2]`.
   - Print E8.
   - Return 1. No `stills_judgment.json` is written, and scores are never fabricated.

Both `create` calls are wrapped together in one `try: ... except anthropic.APIError as e:`, as in `bin/judge-story`. If either call raises, the result is E7. If the retry call raises, `r1` is not dumped. The run makes at most two API calls.

`timestamp` is captured immediately after a `submit_judgment` block is found and before validation, exactly where `bin/judge-story` captures it.

---

## 5. Output

### 5.1 `stills_judgment.json`

Written to `story_dir/stills_judgment.json` as UTF-8 with `json.dump(obj, f, indent=2, ensure_ascii=False)` followed by a trailing `"\n"`. The formatting is identical to `bin/judge-story`. Keys appear in this order **[spec choice: the brief's listing order]**:

```json
{
  "story_id": "frogjump",
  "model": "claude-opus-5-5",
  "effort": "high",
  "timestamp": "2026-10-04T14:03:11Z",
  "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
  "scores": {
    "prompt_fidelity": 0,
    "visual_continuity": 0,
    "rendering_quality": 0,
    "composition": 0
  },
  "critique": "string"
}
```

The example above is the 2+-stills shape, where `visual_continuity` is a real score. The 1-still shape differs only in that one field:

```json
  "scores": {
    "prompt_fidelity": 0,
    "visual_continuity": null,
    "rendering_quality": 0,
    "composition": 0
  },
```

Field rules:

- `story_id`: `args.story_id` verbatim.
- `model`: the literal `MODEL`, not `response.model`.
- `effort`: the literal `EFFORT` (`"high"`).
- `timestamp`: `datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`, captured as Section 4.6 specifies.
- `usage`: the same shape and rules as `bin/judge-story`, summed over every response received (r1, plus r2 if a retry happened):
  - `input_tokens`: the sum of `r.usage.input_tokens`;
  - `output_tokens`: the sum of `r.usage.output_tokens`;
  - `thinking_tokens`: the sum of `r.usage.output_tokens_details.thinking_tokens` over the responses where both `output_tokens_details` and `thinking_tokens` are not `None`. If no response reports it, write JSON `null`, never a fabricated `0`.
- `scores`: all four `SCORE_KEYS`, in order.
  - `prompt_fidelity`, `rendering_quality`, and `composition` are copied from the validated tool input's `scores` object. Validation (Section 4.4) guarantees all three are present, so this never needs a fallback.
  - `visual_continuity` is `tool_input["scores"].get("visual_continuity")`:
    - when `len(stills) >= 2`, validation (Section 4.4) guarantees the key is present, so this copies the judge's real score;
    - when `len(stills) < 2`, the key is normally absent (the schema allows this, and the system prompt instructs the judge to omit it), and `.get(...)` yields Python `None`, written as JSON `null` — never a fabricated integer.
- `critique`: copied verbatim from the validated tool input.

The list of stills judged is not recorded **[the brief's key list followed exactly; see G9]**.

### 5.2 `stills_judgment.raw.json`

Written only on E8 or E9, to `story_dir/stills_judgment.raw.json`, as UTF-8 with `indent=2, ensure_ascii=False` and no trailing newline added. This is identical to `bin/judge-story`'s `_write_raw`:

```json
{"responses": [<r1.model_dump(mode="json")>, <r2.model_dump(mode="json")>]}
```

It holds one response on E9 when no retry happened, and two on E8.

### 5.3 Stdout (success only)

**[spec choice: `bin/judge-story`'s exact layout, without its revised-prompt section]**:

```
Scores:
  prompt_fidelity       7
  visual_continuity     6
  rendering_quality     8
  composition           5

--- Critique ---
<full critique text>
```

The 1-still case, where `scores["visual_continuity"]` is `None`, prints that row differently instead of crashing on `"%d" % None`:

```
Scores:
  prompt_fidelity       7
  visual_continuity     n/a (only 1 still)
  rendering_quality     8
  composition           5

--- Critique ---
<full critique text>
```

- Each score line is produced by `format_score_line(name, value)`:
  ```python
  def format_score_line(name, value):
      if value is None:
          return "  %-20s  n/a (only 1 still)" % name
      return "  %-20s  %d" % (name, value)
  ```
  **[spec choice: the exact wording `"n/a (only 1 still)"` for the null case]**. It is only ever reached for `visual_continuity`, and only when `len(stills) == 1` (Section 5.1), so the literal "1 still" wording is always accurate — `len(stills)` is never 0 (E3) and `visual_continuity` is never `None` when `len(stills) >= 2` (Section 4.4's post-validation check).
  - For a non-`None` value, `format_score_line`'s output is byte-identical to the old `"  %-20s  %d" % (name, value)` line, so the 2+-stills case's stdout is unchanged from the pre-fix spec.
- Lines are produced in `SCORE_KEYS` order by calling `format_score_line(key, scores[key])` for each key.
- One blank line comes before `--- Critique ---`.
- The critique is printed in full and never truncated. It is followed by the single newline that `print` adds.
- Nothing else goes to stdout: no progress lines, no usage, and no output paths. Exactly, stdout is `"Scores:\n" + score_lines + "\n--- Critique ---\n" + critique + "\n"`, where `score_lines` is each `format_score_line(...)` result joined with `"\n"` plus a trailing `"\n"`.

---

## 6. Error handling

All error messages go to stderr and begin with `Error: `. The wording of each is a **[spec choice]**.

| # | Condition | Section 1.2 step | Message to stderr | Exit | Files written |
|---|---|---|---|---|---|
| E1 | `--story-id` missing, or any unknown argument | 1 | argparse's own usage error | 2 (argparse `SystemExit`) | none |
| E2 | `images/` directory missing | 3 | `Error: stills directory not found: <images_dir>` | 2 | none |
| E3 | `images/` contains no file matching `panel_NN.png` | 4 | `Error: no panel_NN.png stills found in <images_dir>` | 2 | none |
| E4 | `story.md` missing | 5 | `Error: story.md not found: <story_md_path>` (identical to `bin/judge-story`) | 2 | none |
| E5 | A still has no panel section at its position (Section 3.3) | 7 | `Error: <still_path> has no matching panel section in story.md (story.md has <len(panels)> panel sections); the stills may be stale relative to story.md.` | 2 | none |
| E6 | `ANTHROPIC_API_KEY` unset or empty | 9 | `Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-stills.` | 1 | none |
| E7 | Anthropic API error (auth, rate limit, overloaded, connection, timeout, request too large, invalid image, or any other `anthropic.APIError`) on either call | 11 | `Error: Anthropic API call failed: <type(e).__name__>: <str(e)>` | 1 | none |
| E8 | No `submit_judgment` tool_use after one retry | 11 | `Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>` | 1 | `stills_judgment.raw.json` |
| E9 | Tool input fails schema validation, **or** (G1 fix) 2 or more stills were judged and the tool input omits `visual_continuity` | 12 | `Error: submit_judgment input failed schema validation: <ValidationError.message>` (the latter case's `ValidationError.message` is the literal `"visual_continuity is required when judging 2 or more stills"`, Section 4.4) | 1 | `stills_judgment.raw.json` |

- The brief combines "missing directory" and "no stills" into one row. This spec splits it into E2 and E3 so the message names the actual problem; both exit 2.
- E7: the tool adds no retry or backoff of its own. The SDK's built-in default `max_retries` (2) is left unchanged, as in `bin/judge-story` (its G2).
- Python exceptions outside this table propagate as tracebacks, the same rule as `bin/judge-story`. Examples: `OSError` reading a still, `UnicodeDecodeError` reading `story.md`, `OSError` writing an output file.

---

## 7. Testing

### 7.1 Framework and style

- File: `tests/test_judge_stills.py`. Use pytest with plain `assert` statements, following `tests/test_judge_story.py`'s structure exactly. Do not use the `check()` helper style.
- Load the script as a module:
  ```python
  WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
  _SCRIPT_PATH = os.path.join(WS, "bin", "judge-stills")
  judge_stills = importlib.machinery.SourceFileLoader("judge_stills", _SCRIPT_PATH).load_module()
  ```
- **No real API calls, ever.** An autouse fixture `_no_real_client(monkeypatch)`, copied from `tests/test_judge_story.py`, does two things. It sets `judge_stills.anthropic.Anthropic` to a function that raises `AssertionError("test constructed a real anthropic.Anthropic client")`, and it runs `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`.
- Tests that reach the API install a `_FakeAnthropic` recorder. It has the same class shape as `tests/test_judge_story.py`'s: it records constructions and `create` kwargs, and returns or raises scripted items in order.
- Responses are real SDK objects built with `anthropic.types.Message.model_validate({...})`, using the same `_message`, `_tool_response`, `_text_response`, and `_usage` helpers as `tests/test_judge_story.py`. Each includes a `thinking` block with a `signature`.
- **Story fixtures live under `tmp_path`.** Each test that calls `main` or `resolve_paths` with a fixture runs `monkeypatch.setattr(judge_stills, "WS", str(tmp_path))`, then builds `tmp_path/generated/stories/<id>/`, with `story.md` and `images/panel_NN.png`. Nothing is written to the real `generated/` tree.
- **Still fixtures are distinct, fake byte strings**, not real PNGs. For example, panel `k` gets `b"\x89PNG\r\n\x1a\n" + b"still-%d" % k`. Nothing decodes them, and distinct bytes let a test check panel order by decoding the base64 back.
- The key sentinel is `"sk-test-SENTINEL-do-not-leak"`, as in `tests/test_judge_story.py`.
- Shared fixture `CHAIN_STORY_MD` **[spec choice: synthesized; it does not depend on any real story directory]**:
  ```
  ## Panel 1 — Dawn on the Pad
  Image: A green frog on a lily pad — dawn.
  Second image line.
  Style: photorealistic, natural light
  Motion: The frog crouches.
  Narration: He waits.

  ## Notes
  Not a panel; must not attach anywhere.

  ## Panel 2 —
  Motion: The frog leaps.
  Narration: He jumps.

  ## Panel 3 — Landing
  Motion: The frog lands on the log.
  Narration: Safe.
  ```
  `parse_panels(CHAIN_STORY_MD)` must return exactly three panels:
  1. `{"header": "## Panel 1 — Dawn on the Pad", "image": "A green frog on a lily pad — dawn. Second image line.", "motion": "The frog crouches.", "narration": "He waits."}`
  2. `{"header": "## Panel 2 —", "image": "", "motion": "The frog leaps.", "narration": "He jumps."}`
  3. `{"header": "## Panel 3 — Landing", "image": "", "motion": "The frog lands on the log.", "narration": "Safe."}`

### 7.2 Real (unmocked) tests

| ID | Test | Assertion |
|---|---|---|
| T1a | `main([])` | raises `SystemExit`, `code == 2` |
| T1b | `main(["--story-md", "x"])` | raises `SystemExit`, `code == 2` (the flag does not exist) |
| T2 | `resolve_paths("abc")` with the real `WS`, then again after monkeypatching `judge_stills.WS` to `str(tmp_path)` | First: `judge_stills.WS == WS` and the result `== (os.path.join(WS, "generated", "stories", "abc"), <that>/images, <that>/story.md)`. Second: `story_dir == os.path.join(str(tmp_path), "generated", "stories", "abc")`, which proves `WS` is read at call time |
| T3 | `find_stills` on a dir containing `panel_03.png`, `panel_01.png`, `panel_100.png`, `panel_99.png`, `panel_02.png`, and the non-matching `panel_1.png`, `panel_01.jpg`, `panel_01.png.bak`, `Panel_04.png`, `images.json` | Returns exactly `[(1, .../panel_01.png), (2, .../panel_02.png), (3, .../panel_03.png), (99, .../panel_99.png), (100, .../panel_100.png)]`. This order pins numeric sorting, since a string sort would put `panel_100` before `panel_99` |
| T4a | `parse_panels(CHAIN_STORY_MD)` | Equals the three-dict list in Section 7.1 exactly. That pins: `Style:` closes `Image` and is dropped; continuation lines are space-joined; `## Notes` text does not attach; an empty-title header is recognized; and missing fields are `""` |
| T4b | `parse_panels` on a two-panel all-`Image:` text (frogjump shape: each panel has `Image:`, `Motion:`, `Narration:` on single lines; headers `## Panel 1 — A` / `## Panel 2 — B`) | Two panels, each with all three fields equal to the fixture's values |
| T4c | `parse_panels("")` and `parse_panels("# Title\nno panels\n")` | Both `== []` |
| T5 | `format_panel_text` on panels 1 and 2 of T4a, and on `{"header": "## Panel 9 — X", "image": "", "motion": "", "narration": ""}` | `== "## Panel 1 — Dawn on the Pad\nImage: A green frog on a lily pad — dawn. Second image line.\nMotion: The frog crouches.\nNarration: He waits."`; `== "## Panel 2 —\nMotion: The frog leaps.\nNarration: He jumps."`; `== "## Panel 9 — X"` |
| T6 | `encode_still` on a `tmp_path` file containing fixture bytes | `== base64.standard_b64encode(data).decode("ascii")`, and `base64.b64decode(result) == data` |
| T7 | `build_user_content([("T1", "QQ=="), ("T3", "Qg==")])` (2 entries) | `== [{"type": "text", "text": "T1"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QQ=="}}, {"type": "text", "text": "T3"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "Qg=="}}, {"type": "text", "text": judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2}]` (2 >= 2, multi template) |
| T7b | `build_user_content([("T1", "QQ==")])` (1 entry) | Final block `== {"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE}` (1 < 2, single text); the rest of the list is the one text/image pair |
| T7c | `build_user_content([])` (0 entries, a pure-function edge case never reached through `main()` since E3 requires at least 1 still) | `== [{"type": "text", "text": judge_stills.FINAL_USER_TEXT_SINGLE}]` (0 < 2, same branch as T7b) |
| T8a | `validate_judgment_input` with each top-level key (`scores`, `critique`) removed in turn, `stills_count=2` (2 cases) | raises `jsonschema.ValidationError` |
| T8b | Each of `prompt_fidelity`, `rendering_quality`, `composition` removed in turn, `stills_count=2` (3 cases) | raises `jsonschema.ValidationError` (schema-level: these three are unconditionally required) |
| T8c | Each of the four score keys (including `visual_continuity`) set in turn to `0`, `11`, `"7"`, `7.5`, `True`, `stills_count=2` so `visual_continuity` is present to be checked | raises `jsonschema.ValidationError` |
| T8d | All four scores at 1, then at 10, `stills_count=2`; then a valid payload plus an extra top-level key and an extra score key, `stills_count=2`; then a payload with `visual_continuity` omitted and the other three valid, `stills_count=1` | does not raise, in every case |
| T8e | `visual_continuity` removed, `stills_count=1` | does not raise (schema allows the omission, and the count is below 2 so the additional check does not apply) |
| T8f | `visual_continuity` removed, `stills_count=2` | raises `jsonschema.ValidationError`, with `.message == "visual_continuity is required when judging 2 or more stills"` (the additional check, not the schema's `required` array) |
| T9a | Story dir with `story.md` but no `images/` | `main(["--story-id", id]) == 2`; stderr `== "Error: stills directory not found: <images_dir>\n"`; stdout empty |
| T9b | `images/` exists, containing only `panel_1.png` and `images.json` | `== 2`; stderr `== "Error: no panel_NN.png stills found in <images_dir>\n"` |
| T9c | `images/panel_01.png` present, no `story.md` | `== 2`; stderr `== "Error: story.md not found: <story_md_path>\n"` |
| T9d | Neither `images/` nor `story.md` (a nonexistent story id under the patched `WS`) | `== 2`; stderr starts with `Error: stills directory not found:`, which pins the check order |
| T9e | `CHAIN_STORY_MD` (3 panels) with `panel_01.png` and `panel_04.png` | `== 2`; stderr `== "Error: <.../panel_04.png> has no matching panel section in story.md (story.md has 3 panel sections); the stills may be stale relative to story.md.\n"` |
| T10 | Successful mocked run, the 2+-stills normal case (item (b) of the G1 fix): `CHAIN_STORY_MD`, stills `panel_01.png` and `panel_03.png` only (panel 2 missing), the key set to the sentinel, and one `_tool_response` with valid input (all four scores, including `visual_continuity`) whose usage values are distinct and non-zero | See the list directly below |

All T9 cases also assert: no file is written under the story dir, and the autouse client guard was not tripped.

T10 assertions:

- `main(["--story-id", id]) == 0`.
- `stills_judgment.json` exists in the story dir.
  - It has exactly the keys `["story_id", "model", "effort", "timestamp", "usage", "scores", "critique"]`, in that order.
  - `story_id == id`, `model == "claude-opus-5-5"`, `effort == "high"`, and `timestamp` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`.
  - `usage` equals the mocked values. `list(scores) == list(SCORE_KEYS)`, and scores and critique equal the mocked input.
  - The raw text contains a non-ASCII `—` from the critique (`ensure_ascii=False`) and ends with `"}\n"`.
- None of `stills_judgment.raw.json`, `judgment.json`, or `judgment.raw.json` exists. The last two confirm there is no collision with `bin/judge-story`'s outputs.
- stdout `== "Scores:\n" + "".join(format_score_line(k, scores[k]) + "\n" for k in SCORE_KEYS) + "\n--- Critique ---\n" + critique + "\n"` (every score, including `visual_continuity`, is a plain integer here, so this equals the pre-fix `"  %-20s  %d\n" % (k, v)` formula byte for byte), and stderr `== ""`.
- `fake.constructions == [((), {})]`, and `create` was called exactly once.
- The kwargs:
  - `sorted(kwargs) == ["max_tokens", "messages", "model", "output_config", "system", "thinking", "tool_choice", "tools"]`;
  - `model == "claude-opus-5-5"`, `max_tokens == 21333`, `thinking == {"type": "adaptive"}`, `output_config == {"effort": "high"}`, and `tool_choice == {"type": "auto"}`;
  - `system == judge_stills.SYSTEM_PROMPT`;
  - exactly one tool, named `submit_judgment`, with `input_schema == SUBMIT_JUDGMENT_SCHEMA` and `description == TOOL_DESCRIPTION`.
- `messages` has length 1, with role `user`, and its `content` has exactly 5 blocks: text, image, text, image, text.
  - Block 0 text `== format_panel_text(panel 1)`.
  - Block 1's base64 data decodes to the `panel_01.png` fixture bytes.
  - Block 2 text `== format_panel_text(panel 3)`, so panel 2 (no still) is absent.
  - Block 3 decodes to the `panel_03.png` bytes.
  - Block 4 text `== judge_stills.FINAL_USER_TEXT_MULTI_TEMPLATE % 2` (2 stills judged, so the multi-still branch, and the count is correct even though one of the three chain panels has no still).
  - Every image block has `media_type == "image/png"`.

A separate mocked-run test covers the 1-still case (item (a) of the G1 fix):

| ID | Test | Assertion |
|---|---|---|
| T10b | Successful mocked run, the 1-still case: a one-panel story (`## Panel 1 — Only` with `Image:`/`Motion:`/`Narration:`), one still `panel_01.png`, one `_tool_response` whose `tool_input["scores"]` has only `prompt_fidelity`, `rendering_quality`, and `composition` (`visual_continuity` is absent from the mocked tool call entirely, modeling a judge that correctly followed the instruction) | `main(["--story-id", id]) == 0`. `stills_judgment.json`'s `scores == {"prompt_fidelity": <v>, "visual_continuity": None, "rendering_quality": <v>, "composition": <v>}` (JSON `null` on disk for `visual_continuity`, checked by reading the raw file text and finding the literal substring `"visual_continuity": null`). stdout's `visual_continuity` line equals `format_score_line("visual_continuity", None)`, i.e. `"  %-20s  n/a (only 1 still)" % "visual_continuity"`, while the other three lines still use `"%d"`. `create`'s sole call has `messages[0]["content"]` of length 3 (text, image, text), and its last block's text `== judge_stills.FINAL_USER_TEXT_SINGLE` (not the multi template), confirming the judge was never asked to score `visual_continuity` for this run. `create` called exactly once (no retry; this is a single valid tool_use, not a validation failure) |

### 7.3 Mocked tests

| ID | Test | Assertion |
|---|---|---|
| T11 | Valid fixtures; key unset (`delenv`), then set to `""` | Each run returns `== 1`; the fake `Anthropic` was constructed zero times and `create` was called zero times; stderr `== "Error: ANTHROPIC_API_KEY is not set; export it in your environment to run judge-stills.\n"`; no file written |
| T12 | Retry path: r1 has only thinking and text blocks with `thinking_tokens` unreported; r2 has a valid tool_use | `== 0`. `create` called twice. The second call's `messages` has length 3 with roles `user, assistant, user`. `messages[0]` equals the first call's `messages[0]`, so the same image content is re-sent. The assistant content `== r1.content`, and its first block is a `thinking` block with signature `"sig-abc123"`. The last content `== RETRY_USER_MESSAGE`. All non-`messages` kwargs are identical across the two calls. `usage` input and output are sums of r1 and r2, and `thinking_tokens` equals r2's alone. No raw dump is written |
| T13 | Double failure: r1 and r2 are both text-only | `== 1`; `create` called twice; `stills_judgment.raw.json`'s `responses == [r1.model_dump(mode="json"), r2.model_dump(mode="json")]`; no `stills_judgment.json`; stderr `== "Error: Claude did not call submit_judgment after one retry; raw responses written to <raw_path>\n"`; stdout empty |
| T14 | Schema-invalid tool input (`composition: 11`) | `== 1`; `create` called once (no retry); the raw dump has 1 response; no `stills_judgment.json`; stderr starts with `Error: submit_judgment input failed schema validation: ` |
| T14b | 2+-stills case (two stills, as in T10's fixture), but the judge's tool input omits `visual_continuity` despite the system-prompt instruction — item (c) of the G1 fix, caught by the Section 4.4 post-validation check rather than by `find_tool_use` (a `tool_use` block was found; this is not a double-failure/no-tool-call case like T13) | `== 1`; `create` called once (no retry — this is a validation failure, same handling as T14); the raw dump (`stills_judgment.raw.json`) has exactly 1 response; no `stills_judgment.json` is written; stderr `== "Error: submit_judgment input failed schema validation: visual_continuity is required when judging 2 or more stills\n"`; stdout empty |
| T15 | API error: (a) the first `create` raises `anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))`; (b) r1 is text-only and the retry raises the same error | Both return `== 1`; stderr starts with `Error: Anthropic API call failed: APIConnectionError: `; `create` called 1 and 2 times respectively; no output files in the story dir in either case |
| T16 | No key leakage: rerun the T10 and T13 scenarios with the sentinel key. The T10 rerun uses responses that omit `output_tokens_details` | The sentinel does not appear in captured stdout, captured stderr, `stills_judgment.json`, or `stills_judgment.raw.json`. The T10 rerun's `usage.thinking_tokens` is `None` (pins `null`, not `0`) |

### 7.4 Mutation checks (negative controls)

Before declaring D2 complete, the implementer applies each mutation below to `bin/judge-stills` one at a time, runs the suite, confirms that at least one named test fails, and reverts the mutation.

| Mutation | Must fail |
|---|---|
| Move the API-key check after `anthropic.Anthropic()` construction | T11 |
| `find_stills` sorts by filename string instead of integer index | T3 |
| `STILL_NAME_RE` changed to `panel_(\d+)\.png` | T3 |
| `"Style"` removed from `PANEL_LABEL_RE` | T4a |
| `line.startswith("##")` section-closing branch removed | T4a |
| Image block appended before its panel's text block | T7, T10 |
| `MEDIA_TYPE` changed to `"image/jpeg"` | T7, T10 |
| Pairing check (E5) removed | T9e |
| Images-dir check moved after the `story.md` check | T9d |
| Every story panel sent (panels without a still get a text block) | T10 |
| Output written to `judgment.json` instead of `stills_judgment.json` | T10 |
| `"maximum": 10` changed to `"maximum": 11` | T8c, T14 |
| Retry removed (straight to double failure on r1) | T12 |
| Retry message list built without re-sending `user_content` | T12 |
| `stills_judgment.raw.json` write skipped | T13 |
| `visual_continuity` left in (or restored to) `scores.required` in `SUBMIT_JUDGMENT_SCHEMA` | T8e, T10b |
| The post-validation `stills_count >= 2` check in `validate_judgment_input` removed or short-circuited | T14b |
| `build_user_content` always uses `FINAL_USER_TEXT_MULTI_TEMPLATE`, regardless of count | T7b, T7c, T10b |
| `build_user_content` always uses `FINAL_USER_TEXT_SINGLE`, regardless of count | T7, T10 |
| `format_score_line` formats every value with `"%d"` unconditionally (no `None` branch) | T10b (raises or mis-renders instead of printing `n/a (only 1 still)`) |
| `scores["visual_continuity"]` written with `tool_input["scores"]["visual_continuity"]` instead of `.get(...)` | T10b (raises `KeyError` instead of writing `null`) |

### 7.5 Files and dependencies

| File | Action |
|---|---|
| `bin/judge-stills` | Create, `chmod +x` |
| `tests/test_judge_stills.py` | Create |

- `anthropic` and `jsonschema` are already used by `bin/judge-story`. Under `python3` 3.13.0 on this machine they import at 0.116.0 and 4.23.0 (checked this session). `base64` and `re` are standard library.
- The tool is not added to the deploy package, so the dual-interpreter gate does not apply.

### 7.6 Acceptance

| ID | Check | Pass condition |
|---|---|---|
| A1 | `python3 -m pytest tests/test_judge_stills.py -v`, run from `WS` by the main thread. Counts reported by the implementer are not accepted | Every test in Sections 7.2 and 7.3 passes, and the count of test functions matches the IDs defined there. Multi-case IDs loop inside one function, as in `tests/test_judge_story.py` |
| A2 | Mutation checks in Section 7.4 | Each mutation makes at least one named test fail |
| R1 | `python3 -m pytest tests/test_judge_story.py` | Unchanged result; D1 does not touch `bin/judge-story` |
| M1 | Manual: `bin/judge-stills --story-id frogjump` with a real key. frogjump has 5 stills, every panel has `Image:`, and the stills total 6.05 MB raw, about 8.1 MB base64 | Exit 0. `generated/stories/frogjump/stills_judgment.json` is present with the 7 keys. stdout layout matches Section 5.3. The critique names panels by number. No other file in `generated/stories/frogjump/` is created or modified |
| M2 | Manual, informational, and not a pass/fail gate: run it once against a current chain-format story with a single still, for example `final_e2e_verify` or `test_story1` | Exit 0. `stills_judgment.json`'s `scores.visual_continuity` is JSON `null`, and stdout prints the `n/a (only 1 still)` line, confirming the real model actually omits `visual_continuity` from its `submit_judgment` call when told there is 1 still (G1, resolved in Sections 4.3-4.5, 5.1, 5.3) rather than fabricating a score the mocked tests cannot catch |

---

## 8. Known gaps / open questions

No item here blocks implementation. Every item has a spec choice recorded above, which the user may override. **G2 still needs a decision from the user before this tool is relied on at scale. G1 is RESOLVED (below).**

- **G1: RESOLVED. The current pipeline produces only one still per story; the brief assumed one per panel.**
  - Since the narrative-chain redesign, `bin/ltx-movie`'s pipeline Phase 2 runs `bin/ltx-story-images --only 1` (`bin/ltx-movie:794-797`). Chain-format panels 2..N have no `Image:` field, and `bin/ltx-story-images` refuses to render a panel without one (`:195`).
  - On-disk survey: every chain-format story has exactly one still (`test_story1`..`7`: 1 still / 5 panels). Every multi-still story is a pre-chain story from 2026-09-11 to 2026-09-13 (`frogjump`, `band_red_test`, `mydemo5`, ...).
  - So for any story generated by today's `bin/ltx-movie`, this tool judges exactly one image, panel 1, and `visual_continuity` has nothing to compare.
  - **Resolution (user decision, 2026-10-03):** ship the design as written, but make `visual_continuity` conditional rather than always-required: omit it (as JSON `null`, never a fabricated score) when fewer than 2 stills exist, since there's nothing to compare across. The user chose this explicitly over options (b) and (c) that this section originally raised — moving the clip-level/frame-extraction sub-project ahead, or simplifying the `visual_continuity` dimension/prompt for the single-still case. Neither of those was pursued; the fix is scoped entirely to this tool's schema, prompt, and output handling.
  - The fix touches:
    - **Section 4.3**: `visual_continuity` removed from `scores`'s `required` array (3 always-required + 1 conditionally-required, instead of 4 unconditionally required).
    - **Section 4.5** (system prompt) and **Section 3.6** (final user-message text block): explicit instructions for both the <2-stills and 2+-stills cases, and the final text block states the actual stills count so the judge does not have to infer which case applies.
    - **Section 4.4**: a post-validation check, run after `jsonschema.validate` succeeds, that treats a 2+-stills judgment missing `visual_continuity` as equivalent to any other schema-validation failure (same raw-dump-and-exit-1 handling, same E9 code path) — a deliberate choice that an instruction-following failure in the 2+-stills case is not the same as the legitimate <2-stills omission, and must not be silently written as `null`.
    - **Section 5.1**: `scores.visual_continuity` is JSON `null`, never a fabricated integer, when the tool call omitted it (the <2-stills case only, since the 2+-stills case now fails before this point if it's missing).
    - **Section 5.3**: stdout prints `n/a (only 1 still)` instead of crashing on `"%d" % None`.
    - **Section 7.2/7.3**: new test IDs T7b, T7c, T8e, T8f, T10b, T14b cover the <2-stills success path, the 2+-stills normal path (already covered by the existing T10), and the 2+-stills-but-omitted failure path, with matching Section 7.4 mutation rows.
  - For chain stories, what panels 2..N actually look like still exists only in the rendered clips — that remains the clip-level, frame-extraction sub-project this spec puts out of scope, unaffected by this resolution.
  - Related spec choice (Section 3.3): panels without a still are omitted from the message entirely. The alternative is to send every panel's text and attach images only where they exist. That gives the judge the whole story's context, but it makes the message mostly text for chain stories. This choice is unaffected by the G1 resolution.

- **G2: total request size for stories with many stills, known and not solved.**
  - The binding limit is the API's **32 MB request-size cap** (current docs, Section 0.2). Neither the per-image cap nor the image count is the constraint.
  - At the observed 1.0-1.66 MB raw per still (about 1.3-2.2 MB base64), a request reaches about 32 MB at roughly 14-24 stills.
  - Requests over 20 images also trigger the stricter per-image dimension rule. The observed stills, at most 1408 px, already satisfy it.
  - The retry (Section 4.6) re-sends every image, so each of the two calls is about the same size.
  - The SDK's default `max_retries=2` can also re-send the full payload on 429/5xx/connection errors.
  - Too large a request surfaces as E7 (exit 1). As instructed, nothing is designed for this here: no chunking, no compression, no size-based rejection.
  - Options for later: downscale to the 1568 px tier, convert to JPEG, upload once through the Files API and reference by `file_id` (the docs recommend this for many images), or split panels across calls. Splitting loses holistic continuity judging.
  - Per G1, this risk applies only to pre-chain or hand-rendered stories with many stills.

- **G3: grounding figures in the brief that were corrected** (Section 0.2). None changes the design.
  - The per-image cap is 10 MB on the direct API (not 5 MB, which is Bedrock / Google Cloud).
  - Up to 600 images per request (not 100) for non-200k-context models.
  - The long-edge figure for Claude 4.7+ is 2576 px (not 1568).
  - Real still dimensions are mostly 1280x704 (not 1280x768).
  - Raw sizes run up to 1.66 MB (not 1 MB).
  - `_still_size()` is at `bin/ltx-movie:781-787` (not `772-778`).

- **G4: `images.json` is not read, so seed images are judged as if generated.**
  - In `--seed-image` stories, `panel_01.png` is the user's own reference image fitted to size (`images.json` `"source": "seed"`, for example `test_story7`). It was not generated by the image model.
  - The judge scores it for `rendering_quality` and `prompt_fidelity` as if it were model output.
  - Blocked or errored panels (`status`) are invisible here; a missing still is simply skipped.
  - Fixing this means reading `images.json`, which the brief excluded.

- **G5: `Style:` text is not sent.**
  - In grounded (seed-image) stories, `bin/ltx-story-images` appends Panel 1's `Style:` text verbatim to every panel's image prompt. So each still's real prompt was `Image:` + `Style:`.
  - The brief names only `Image:`/`Motion:`/`Narration:`. The parser recognizes `Style:` only so it can close the `Image` field, then drops it.
  - `prompt_fidelity` is therefore judged against less than the full prompt. Style mismatches may also be unfairly blamed on `visual_continuity` or `rendering_quality`.
  - `Prompt:` (the collapsed `--no-stills` format) is dropped too. Such stories have no stills, so this is moot.

- **G6: no staleness detection beyond pairing.**
  - `bin/iterate-story` and `bin/ltx-movie --force-story --story-only` regenerate `story.md` without touching `images/`. After either, the stills can describe a different story while still pairing by position.
  - The E5 check catches only stills that point past the end of the parsed panel list.
  - A content check would need a recorded per-still prompt, which `images.json` has, or an mtime comparison. Neither is in the brief.
  - Spec choice: no check, only E5. E5 itself is an addition to the brief's error table, made so that a still never pairs with missing text.

- **G7: the parser is duplicated rather than loaded.**
  - `bin/ltx-story-images` loads `bin/ltx-story-manifest`'s `_parse_prompts_md` through `SourceFileLoader`. Its comment, marked LOAD-BEARING, says exactly one `story.md` parser must exist, to prevent drift.
  - This spec follows the brief's "no import from another `bin/*`; match `bin/judge-story`'s precedent exactly" instead. It duplicates the two regexes and the section and field rules verbatim, with a comment citing the source lines.
  - Risk: if `bin/ltx-story-manifest`'s rules change, pairing here can drift from what was rendered.
  - Alternative: load `bin/ltx-story-manifest` via `SourceFileLoader` as `bin/ltx-story-images` does. That module imports `PIL` at top level, which is installed under `python3` 3.13, and it takes a file path rather than text.

- **G8: the prompt wording was written for this spec.**
  - `SYSTEM_PROMPT`, `TOOL_DESCRIPTION`, `FINAL_USER_TEXT_SINGLE`, `FINAL_USER_TEXT_MULTI_TEMPLATE`, `RETRY_USER_MESSAGE`, the dimension glosses, and all error messages were written from the approved requirements. The brainstorm approved their content, not their exact wording.
  - Two points deserve the user's review:
    - `prompt_fidelity` asks whether a single still depicts the `Motion:` text, which describes action over a whole clip. The prompt gives the judge no guidance on how a single frame should satisfy a description of motion.
    - The current vision docs note that Claude does best with images placed before their text. Interleaved text-then-image, the approved order, "still performs well".
  - A third point this section used to raise — the prompt not telling the judge whether it may be seeing only one panel — is **RESOLVED** by the G1 fix (Section 4.5's system prompt and Section 3.6's final user-message text block now state exactly that, including the real stills count).

- **G9: the judged stills are not recorded in the output.**
  - `stills_judgment.json` follows the brief's seven keys exactly, so it does not record which `panel_NN.png` files were judged or how many.
  - Given G1 (often one still) and G4/G6 (possible seed or stale stills), a `stills` list would make each judgment self-describing. Adding one is a one-line change if the user wants it.

- **G10: SDK built-in retries.** The same as `bin/judge-story`'s G2. "No retry-with-backoff" is read as "the tool adds none", and the SDK default `max_retries=2` is kept. Given G2's payload sizes, `anthropic.Anthropic(max_retries=0)` is the alternative if strict single attempts are wanted.

- **G11: cost.** Each image costs about `ceil(w/28) * ceil(h/28)` visual tokens on the high-resolution tier. That is 1,196 for 1280x704 and 1,785 for 1408x960. Each run is one Opus call, or two on a retry. There is no cost guard, and none was asked for.
