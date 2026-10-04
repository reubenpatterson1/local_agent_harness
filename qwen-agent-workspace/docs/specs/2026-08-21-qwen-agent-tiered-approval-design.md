# Spec: `qwen-agent` — tiered approval, duplicate-call guard, and give-up nudge

**Status:** Ready for implementation. No open design decisions.
**Date:** 2026-08-21
**Type:** AMENDMENT to two existing specs and a surgical diff to a working script. Not a rewrite.
**Target file:** `/Users/reubenpatterson/.local/bin/qwen-agent` (single file, mode `0755`, 1187 lines
as read on 2026-08-21).

**Parent specs, both of which remain authoritative except where this document explicitly revises
them:**

- `/Volumes/Ollama/vllm-metal/docs/specs/2026-08-21-qwen-agent-tool-harness-design.md` — hereafter
  **[HARNESS]**.
- `/Volumes/Ollama/vllm-metal/docs/specs/2026-08-21-qwen-agent-oneshot-api-design.md` — hereafter
  **[ONESHOT]**.

**Neither parent file is to be edited.** This document is the overlay: where it and a parent
disagree, this document wins, and it names the parent section it supersedes in every such case
(Section 2 below is the complete list). Everything in [HARNESS] and [ONESHOT] not named in Section 2
is inherited verbatim and must not be touched.

**Interpreter constraint:** unchanged — the file must remain valid on Python **3.9.6** and **3.13.0**.
No 3.10+ syntax (no `X | Y` annotations, no `match`). Standard library only. **No new imports** —
`re`, `json`, `sys`, `os` are already imported at lines 12–22.

---

## 1. Purpose and success criteria

### 1.1 The problem this fixes

[HARNESS] Section 2 established a blanket rule: every tool call requires human confirmation, no
exceptions, no auto-approval of any kind. A live test exposed the cost. The model, having no search
tool, *guessed* URLs and called `fetch_url` on them; the guesses 404'd; the model then retried —
including re-issuing calls byte-identical to ones that had already failed. Each guess produced a full
`TOOL CALL i/n` frame and an `Approve? [y/N] ` prompt for a tool that cannot mutate a single byte of
state. The human was reduced to typing `y` at a machine that was flailing, which is exactly the
failure mode a confirmation gate is supposed to prevent: approval fatigue on low-value prompts
degrading attention for the prompts that matter (`bash`, `run_python`).

Three changes, all approved by the user in conversation before this spec was written. The design
below is final; it is not to be re-derived, and the tradeoffs in it are settled.

1. **Tiered approval by tool identity** (Section 3). `fetch_url` and `read_file` are auto-approved.
   `write_file` is auto-approved only when the target does not already exist. `bash` and `run_python`
   are unchanged: always gated, no exceptions.
2. **Per-turn duplicate-call guard** (Section 4). An exact repeat of a call that already failed this
   turn is neither prompted nor executed; the model gets an error telling it to stop repeating itself.
3. **A sixth system-prompt rule** (Section 5) telling the model to give up honestly instead of
   grinding through variations.

### 1.2 Success criteria

The change is correct and complete when, on this machine, with the vLLM server running per
[HARNESS] Section 3:

1. A turn in which the model issues three `fetch_url` calls to three different URLs, all 404,
   produces **zero** `Approve? [y/N] ` prompts and exactly three `[auto]` trace lines.
2. In that same turn, a fourth `fetch_url` call whose arguments are value-identical to one of the
   failed three is **not** executed, produces **no** HTTP request, produces one `[duplicate]` trace
   line, and returns the Section 4.4 error string to the model.
3. A `read_file` of an existing in-workspace file runs with no prompt and one `[auto]` line.
4. `write_file` to a path that does not exist runs with no prompt and one `[auto]` line;
   `write_file` to a path that does exist prints the full [HARNESS] Section 10 frame with
   `target:   OVERWRITES existing file of N bytes` and waits for a keystroke.
5. `bash` and `run_python` still print the full frame and still wait for a keystroke, every time,
   in both REPL and one-shot mode. No content-based exemption exists for either tool anywhere in the
   file (verifiable by the grep in Section 8, check S3).
6. Repeating a call that previously **succeeded** is allowed and executes normally.
7. In one-shot mode, a duplicate-blocked call appears in the envelope with
   `outcome == "duplicate"`, and stdout still carries exactly one JSON line and nothing else.
8. All of [ONESHOT] Section 8's acceptance tests A1–A10 still pass, with the two amendments in
   Section 2 (banner text; A3's denial now also being recorded in the duplicate history).
9. Both `py_compile` gates pass; the import list is byte-identical to before the change.

**Quantified KPI for the regression this fixes.** Scenario: `qwen-agent --user-prompt "Find the
current version number of vllm from its GitHub releases page."` (a prompt that reliably provokes URL
guessing). Before: ≥ 3 `Approve?` prompts per turn, ≥ 1 of which is a byte-identical repeat of an
already-failed call. After: **0** `Approve?` prompts, **0** identical repeats executed, and the number
of `fetch_url` HTTP requests issued is strictly less than the number of `fetch_url` tool calls the
model emitted whenever it repeated itself.

### 1.3 Explicitly out of scope

All non-goals of [HARNESS] 1.3 and [ONESHOT] 1.3 carry over, **except** [ONESHOT] 1.3's blanket "no
auto-approval of any kind", which Section 3 replaces with the tiered policy. Additionally, and
emphatically out of scope:

- **Content-based or keyword-based classification of `bash` / `run_python`.** See Section 3.2. This
  is not merely unimplemented; it is forbidden.
- **A `--yes` / `--auto-approve` / `--dry-run` flag, an allowlist file, a per-session "always allow"
  answer, or any other operator-configurable widening of the tier table.** The tier table is a
  compile-time constant. Do not add a flag that touches it.
- **Cross-turn duplicate memory.** The history resets every turn (Section 4.1). No persistence, no
  cache, no dedup across REPL lines or across one-shot invocations.
- **Near-duplicate / fuzzy matching, normalisation of URLs (case, trailing slash, query order), or
  path canonicalisation before comparison.** Exact value equality of the parsed arguments dict, and
  nothing else (Section 4.3).
- **A rate limit, backoff, or budget on `fetch_url`.** The duplicate guard plus the Section 5 nudge
  plus `--max-rounds` are the whole mechanism.
- **A new `outcome` value for auto-approved calls.** They report `"approved"` (Section 6.3,
  assumption A4).
- **An audit log.** [HARNESS] 14 nice-to-have 1 stays out of scope; the `[auto]` trace lines are
  terminal output only.

### 1.4 Superseded: `--danger-auto-approve` (2026-09-12)

**Two clauses of this document are superseded as of commit `fa87f9b`. They are superseded, not
reinterpreted, not read narrowly, not satisfied by a technicality.**

1. Section 1.3, bullet 2 above: "**A `--yes` / `--auto-approve` / `--dry-run` flag, an allowlist
   file, a per-session 'always allow' answer, or any other operator-configurable widening of the tier
   table.** The tier table is a compile-time constant. Do not add a flag that touches it."
2. Section 9, nice-to-have 9: "Any operator-configurable widening of `AUTO_APPROVE_TOOLS`. (Not
   merely out of scope — forbidden.)"

Both were written to forbid exactly the class of thing that now exists. A flag now lets the operator
skip the confirmation prompt. Saying otherwise would be word games. What follows is what was built,
which part of the original concern survives intact, and which part was deliberately given up.

**What was built.** `bin/qwen-agent` gained `--danger-auto-approve` (off by default, `store_true`),
covered by `tests/test_qwen_agent_danger_auto_approve.py` (37 checks, offline). When the flag is set,
every tool call except `promote` runs without a confirmation prompt — `bash`, `run_python`,
`generate_image`, and an overwriting `write_file` included. Neither `bash` nor `run_python` is
sandboxed under it; they run as the operator, with the operator's permissions.

**Why the tier table itself is still a compile-time constant.** The original clause's operational
concern was that the tier table would be widened *silently and invisibly* — that a reader of
`should_auto_approve()`, or of a transcript, could no longer tell what the harness would run without
asking. That concern is still substantively honoured, by four properties that the implementation has
and that the tests assert:

- **`should_auto_approve()` is unmodified and provably flag-blind.** It takes `(name,
  resolved_paths)` and nothing else; it has no access to `args_ns` and therefore cannot observe the
  flag. `AUTO_APPROVE_TOOLS` is untouched. The bypass is composed at the **dispatch site** instead,
  as `danger_bypass = args_ns.danger_auto_approve and name != "promote" and not auto_by_policy`, and
  the final `auto` is the `or` of the two. The policy function and the operator override are two
  separate, separately-readable decisions, which is the property Section 3.2's reasoning depends on
  and which a flag *inside* the tier table would have destroyed. Test D7 asserts the string
  `danger` does not occur anywhere in `should_auto_approve`'s source; D4–D6b assert it still refuses
  `promote`, `bash`, `run_python`, and `generate_image`; D8 asserts `AUTO_APPROVE_TOOLS` still
  excludes the whole gated tier.
- **`promote` is excluded unconditionally, before any tool-identity lookup.** The dispatch-site
  `name != "promote"` conjunct is evaluated independently of `AUTO_APPROVE_TOOLS`, mirroring the
  by-name refusal at the top of `should_auto_approve()`. A long-term memory write — the one write
  this harness never deletes and loads into every future session — still requires a human keystroke
  under the flag. Tests D17, D18, and D19 assert this, D18 specifically by *tampering*
  `AUTO_APPROVE_TOOLS` to include `"promote"` at runtime and showing the prompt is still reached;
  D19b asserts the `name != "promote"` guard is literally present in `dispatch`'s source.
- **Every bypassed call traces distinctly.** A call waved through by the flag prints `[danger-auto]`,
  never `[auto]` (tests D16, D20, D23, D23b, and the end-to-end D29), and a call the tier policy
  would have auto-approved anyway still prints `[auto]` even with the flag on (D21, D22). A
  transcript reader can always tell, per call, which ran without confirmation *and why* — tier policy
  or operator override. Nothing became invisible.
- **The bypass does not propagate.** `--danger-auto-approve` is not forwarded to `delegate_to_skill`
  child processes; a child re-derives its own approval behaviour from its own argv, which does not
  carry the flag (test D33 asserts the string is absent from `exec_delegate_to_skill`'s source).
- **The flag announces itself.** `print_danger_auto_warning()` prints a one-time banner at startup in
  both REPL and one-shot mode, stating that every tool call runs without asking, that `bash` and
  `run_python` are not sandboxed, that bypassed calls trace as `[danger-auto]`, and that `promote` is
  the only tool still asking. The flag's name contains the word `danger`; `--help` says "For
  unattended runs only." Nobody reaches this state by accident or by a default.

**The accepted risk, stated plainly.** This flag exists so that an unattended or long-running session
can proceed with no human present to answer prompts. That is its entire purpose, and the cost is
exact: with the flag set, `bash`, `run_python`, `generate_image`, and an overwriting `write_file`
execute with **zero real-time human review**. The [HARNESS] Section 2 threat model's mitigation —
"the human reads every command that can change something before it runs" — does not hold in a
`--danger-auto-approve` run. The full prompt-injection kill chain named in Section 3.3 (hostile text
fetched into context → the abliterated model complies → unsandboxed execution) has no human gate in
it when the flag is on. The tier table's compile-time constancy does not protect against this; it was
never meant to. Section 3.2's prohibition on content-based classification of `bash`/`run_python` also
still stands, and is *not* a mitigation here either: no classifier is being trusted, because no
classifier exists — the call simply runs.

This risk is **accepted as implemented, not mitigated further.** The decision is the user's, made
explicitly, with the chain above named. No additional confirmation layer, no narrower scope, no
command allowlist, no per-tool opt-in, and no interaction guard against other features is to be added
under the heading of making this flag safer. A proposal to do so is a re-litigation of a settled
tradeoff, not a finding.

**What would change the calculus.** Any of the following makes this acceptance stale and requires the
tradeoff to be re-opened rather than re-asserted:

- Evidence that the flag is being reached for in *attended* sessions — an operator sitting at the
  terminal using it to avoid typing `y`, rather than to leave the machine running. That is approval
  fatigue re-emerging as a habit, and it converts an unattended-run tool into a default posture.
- Any incident in which a `[danger-auto]` call did damage: data loss, credential exposure, an
  outbound request the operator did not intend, or an injected instruction reaching execution.
- The flag becoming reachable without an explicit operator-typed argument — set from a config file,
  an environment variable, a wrapper script's default, or any caller that passes it implicitly. The
  acceptance above rests on the flag being typed, per invocation, by a human who read its name.
- `promote`'s unconditional exclusion being weakened, or the `[danger-auto]` trace label being merged
  back into `[auto]`. Both are load-bearing for this acceptance, not incidental.

**Composition with `/resume`.** `--danger-auto-approve` composes with the session-memory `/resume`
command into a chain with no human review at any point. That composition is named and accepted in
`docs/specs/2026-09-02-qwen-agent-session-memory-design.md` Section 17; it is not repeated here.

### 1.4.1 Reopened and re-accepted: `bin/iterate-story` (2026-10-03)

A new caller, `bin/iterate-story` (`docs/superpowers/specs/2026-10-03-iterate-story-design.md`),
triggers the third bullet of "What would change the calculus" above: `bin/ltx-movie` passes
`--danger-auto-approve` to its own `qwen-agent` subprocess whenever both `--force-story` and
`--no-review` are given, and `bin/iterate-story` passes both on every regeneration round, across
however many rounds a run takes, with no human typing the flag at any point. This is exactly the
"wrapper script... any caller that passes it implicitly" trigger named above.

The same trigger also fires for a direct, human-typed `bin/ltx-movie --force-story --no-review`
invocation, with no `bin/iterate-story` involved at all: typing `--no-review` is not typing
`--danger-auto-approve`, and the bypass still composes in silently. `bin/iterate-story`'s own
design spec names this directly (`docs/superpowers/specs/2026-10-03-iterate-story-design.md`
Section 8, G16); it is not unique to that tool, and this note's scope should be read to cover
both paths, not `bin/iterate-story` alone.

**Re-opened, and re-accepted as implemented, with one addition.** The user reviewed this trigger
and chose to keep the automatic passthrough rather than build a narrower bypass mechanism. The
automatic passthrough itself is unchanged — this is not "making the flag safer" in the sense
Section 1.4 forbids (no narrower scope, no allowlist, no per-tool opt-in was added to the flag or
to `should_auto_approve()`).

What was added instead is a property of the new caller, not the flag: `bin/iterate-story` writes a
full, unredacted record of every `judge-story` and `ltx-movie` call it makes — command, exit code,
and complete captured output, success or failure — to `iterate-story.log` in the story's own
directory. This restores the "a transcript reader can always tell what ran unconfirmed" property
for this caller specifically, which discarding captured output on success had silently lost
(`_log_run()` in `bin/iterate-story`). It does not touch `--danger-auto-approve` itself,
`should_auto_approve()`, or the `[danger-auto]` trace mechanism in `bin/qwen-agent` — those remain
exactly as Section 1.4 describes them.

---

## 2. Complete list of parent-spec revisions

Every deviation from the parents is listed here. Nothing else changes.

| Parent section | Status | Replaced by |
|---|---|---|
| [HARNESS] 1.1, sentence 2 ("**every single tool call requires…**" through "…no `read-only is safe` exemptions.") | **superseded** | Section 3.1 of this spec |
| [HARNESS] 1.2 criterion 3 | **amended** | Section 8 (the per-tool acceptance rows now differ by tier) |
| [HARNESS] 2 (Threat model), whole section | **superseded** | Section 3.3 of this spec (exact replacement prose) |
| [HARNESS] 6.3 (Banner) | **superseded** | Section 6.6 of this spec |
| [HARNESS] 8.2 (dispatcher ordering line) | **amended** | Section 6.2 of this spec (one step inserted, one step conditional) |
| [HARNESS] 10 (Confirmation prompt UX) — 10.1/10.2/10.3/10.4 bodies and strings | **unchanged**, but now reached only for the gated tier | Section 3.4 adds 10.0 (tier table), 10.5 (`[auto]` trace), 10.6 (`[duplicate]` trace) |
| [HARNESS] 11.3 (System message) | **amended** — rules 1–5 verbatim, rule 6 appended | Section 5 of this spec |
| [HARNESS] 12 (Error matrix) | **amended** — two rows added, one row's "Prompt shown?" note revised | Section 7 of this spec |
| [HARNESS] 13 (Manual test script) | **amended** — T1–T8 still run; T2/T3/T5 no longer show a prompt | Section 8 of this spec |
| [HARNESS] 14 must-haves ("confirmation on every call with no exemptions") | **superseded** | Section 9 of this spec |
| [ONESHOT] 1.2 criterion 7 ("banner identical") | **amended** | banner is now Section 6.6's text; byte-identity is asserted against *that* |
| [ONESHOT] 1.3 bullet 1 ("No auto-approval … of any kind") | **superseded** | Section 3 of this spec. The *residual* prohibition (no operator-facing approval-bypass flag) held in Section 1.3 above until 2026-09-12, and is itself **superseded** by Section 1.4. |
| [ONESHOT] 4.2 `outcome` field type and vocabulary table | **amended** — `"duplicate"` added, `"approved"` prose widened | Section 6.3 of this spec |
| [ONESHOT] 6.3 stdout-purity audit table | **amended** — two new writer rows | Section 6.7 of this spec |
| [ONESHOT] 8 (Acceptance tests A1–A10) | **retained in full**, plus B1–B11 | Section 8 of this spec |
| [ONESHOT] 6.0 change map, row for `dispatch()` | **amended** — signature gains `history` | Section 6.1 of this spec |

Everything else in both parents — `TOOLS` and every description string, `resolve_in_workspace`, the
HTML extractor, `validate_args`, every tool-execution semantic and error string in [HARNESS] 9, the
confirmation frame layout and all five bodies in [HARNESS] 10.2, answer parsing in 10.3, the denial
string in 10.4, the wire contract in 11.1, slash commands in 11.2, the envelope in [ONESHOT] 4.1,
`setup()`, `preflight()`, exit codes — is inherited **verbatim and unmodified**.

---

## 3. Part 1 — tiered approval

### 3.1 The tier table (normative)

Approval tier is a function of **the tool's name**, plus — for `write_file` only — the single boolean
"does the target path already exist". Nothing else. Not the command text, not the URL host, not the
file extension, not the content, not any heuristic.

| Tool | Tier | Condition | Prompt shown |
|---|---|---|---|
| `fetch_url` | **auto** | always | never |
| `read_file` | **auto** | always | never |
| `write_file` | **auto** | resolved target does not exist (`NEW file`) | never |
| `write_file` | **gated** | resolved target exists (`OVERWRITES existing file of N bytes`) | always |
| `bash` | **gated** | always | always |
| `run_python` | **gated** | always | always |

Rationale, recorded so it is not relitigated:

- `fetch_url` and `read_file` mutate nothing. `read_file` is additionally confined to the workspace
  by [HARNESS] Section 8, which is enforced *before* the tier decision and is unaffected by it.
  `fetch_url` can leak the fact of a request and can pull hostile text into context, but neither is a
  destructive action in itself — it is one link in a chain whose *dangerous* links (`bash`,
  `run_python`, overwriting a file) all remain gated. Section 3.3 states this as accepted residual
  risk rather than pretending it away.
- `write_file` creating a new file inside the workspace destroys nothing. Overwriting destroys the
  previous contents, which is irreversible, so it stays gated.
- `bash` and `run_python` are general-purpose execution surfaces. There is no reliable way to decide
  from their text whether a given invocation is safe. They stay gated unconditionally, forever.

The tier decision applies **identically in REPL mode and in one-shot (`--user-prompt`) mode.** It is
not mode-dependent, and `ONESHOT` must not appear anywhere in the tier logic.

### 3.2 Forbidden: content-based classification (read this before "improving" the tier table)

A future implementer will be tempted to extend auto-approval to "obviously safe" `bash` commands —
`ls`, `pwd`, `cat`, `wc`, anything without `rm`/`sudo`/`>`/`curl`. **Do not.** It is rejected, and the
reason is not squeamishness:

- The classifier's input is attacker-influenced. `fetch_url` pulls text from the open web into the
  model's context; the model is abliterated and will follow instructions found there. An injected
  instruction can trivially phrase a harmful command so it contains no trigger word —
  `find ~ -name '*.pem' -exec cp {} /tmp/x \;` has no `rm`, no `sudo`, no `curl`; `python3 -c '...'`
  smuggles arbitrary code past any bash-keyword list; `cat ~/.aws/credentials` is pure `cat`.
- Shell metacharacters, command substitution, environment indirection, and base64 make any
  substring-based judgement unsound in principle, not just in practice.
- A gate that is right 95% of the time is worse than no gate, because the human stops reading.

The auto-approve exception is therefore scoped **exclusively by tool name**, to the two read-only
tools plus new-file `write_file`. `should_auto_approve()` (Section 6.4) must never receive, inspect,
tokenise, regex, or otherwise look at `args["command"]` or `args["code"]`. Any patch that makes it do
so is a defect regardless of how careful the pattern list looks.

### 3.3 Replacement for [HARNESS] Section 2 — exact prose

The following text replaces [HARNESS] Section 2 in its entirety. (It lives here; [HARNESS] is not
edited.)

> ## 2. Threat model (why execution is gated and reading is not)
>
> The served model is `Huihui-Qwen3.8-27B-abliterated-mlx-6bit` — safety training removed. The tool
> set combines (a) arbitrary command execution, (b) fetching attacker-controlled text from the open
> web, and (c) writing files. That is a complete prompt-injection kill chain: a fetched page can
> contain hidden text instructing the model to exfiltrate `~/.aws/credentials` or `rm -rf` a volume,
> and an abliterated model has no trained reluctance to comply.
>
> The mitigation is that **the human reads every command that can change something before it runs.**
> The gate is placed at the *effecting* step of the chain, not at every step of it:
>
> - `bash` and `run_python` are gated unconditionally. They are where a prompt-injection chain has to
>   terminate in order to do damage, and their text cannot be safely classified (Section 3.2 of the
>   tiered-approval spec). No content-based, keyword-based, or allowlist-based exemption may ever be
>   added to either tool.
> - `write_file` is gated when and only when it would overwrite an existing file. Creating a new file
>   inside the workspace is not a destructive act; destroying the previous contents of one is.
> - `fetch_url` and `read_file` are auto-approved. Neither mutates any state. `read_file` is confined
>   to the workspace by Section 8, which is enforced before and independently of the approval tier;
>   an out-of-workspace read is still refused outright, without a prompt, as it always was.
>
> **Accepted residual risk, stated plainly.** Auto-approving `fetch_url` means the model can, without
> asking, (i) pull hostile text into its own context and (ii) signal to an external server that this
> machine fetched a given URL — including a URL whose *path* the model chose, which is a low-bandwidth
> exfiltration channel. Auto-approving `read_file` means the model can read any workspace file without
> asking. Both are accepted, for three reasons: `bash` could do either anyway and is gated, so no new
> *capability* is unlocked, only a new *unattended* route to an existing one; the damaging step of any
> injection chain still requires a human keystroke; and gating them in practice produced approval
> fatigue — a stream of low-value prompts on a tool that changes nothing, which measurably degrades
> the attention available for the `bash` prompts that matter. Trading a small unattended
> read/disclosure surface for a human who actually reads the dangerous prompts is the deliberate
> choice made here.
>
> Therefore:
>
> - The set of auto-approved tools is a compile-time constant naming exactly `fetch_url` and
>   `read_file`, plus the new-file case of `write_file`. It is not configurable, not extensible at
>   runtime, and not widenable by any CLI flag.
> - No "approve all for this session" / "always allow this tool" answer exists at the prompt. Do not
>   add one.
> - For gated calls, the confirmation prompt shows the *fully resolved, literal* thing that will
>   happen (the exact command string, the exact absolute path, the exact URL), never a summary or
>   paraphrase.
> - The default answer at every gated prompt is **deny**. Empty input, EOF, and any unrecognised
>   input all deny.
> - Auto-approved calls are never silent: each emits exactly one `[auto]` trace line naming the tool,
>   its key argument, and its outcome (tiered-approval spec Section 3.5), so the human can see what
>   ran without being asked to bless it.

### 3.4 Additions to [HARNESS] Section 10 (confirmation prompt UX)

[HARNESS] 10.1–10.4 are unchanged in content — same frame, same five bodies, same answer parsing,
same denial string — but they are now reached only by the gated tier. Three subsections are added:

**New 10.0 — which calls reach the prompt.** The frame of 10.1 is printed if and only if the call
survived [HARNESS] 7.1 / 8 / 9.5 pre-approval checks **and** the duplicate guard (this spec Section 4)
**and** `should_auto_approve()` returned `False` (Section 6.4). In every other case no frame and no
`Approve?` line is printed at all.

The `write_file` body of 10.2 is unchanged, including its `target:` line — but note that in the gated
case that line's value is now always `OVERWRITES existing file of N bytes`, since `NEW file` is
precisely the auto-approved case. The `NEW file` branch of `build_confirmation_body` therefore becomes
unreachable in practice. **It stays in the code** (Section 6.4): it is the single source of the
existence check that the tier gate consumes, and deleting the branch would make the two decisions
independently computed, which is the bug this design specifically avoids.

**New 10.5 — the `[auto]` trace line.** Exactly one line per auto-approved call, written to `_ui()`
(stdout in REPL mode, stderr in one-shot mode, per [ONESHOT] 6.1 — the existing routing helper, used
unchanged). Format:

```
[auto] {tool} {key} -> {outcome}
```

- No leading indent, no surrounding `RULE` separators, no `TOOL CALL i/n` header, no `Approve?`
  prompt, no `  -> running...` / `  -> denied` verdict line. The whole point is that this is one line
  of log, not a frame demanding attention.
- `{key}`: for `fetch_url`, `args["url"]`; for `read_file` and `write_file`, `str(resolved_paths["path"])`
  — the **resolved absolute** path, matching what the confirmation body would have shown. Passed
  through `_trace_clip()` (Section 6.4).
- `{outcome}`: per `_auto_trace_outcome()` (Section 6.4) — the first line of the result if it is an
  `ERROR:` string, `"ok, N characters"` for a successful `read_file`, otherwise the first line of the
  result (`HTTP 200 <final_url>` for `fetch_url`, `OK: wrote N bytes to <path>` for `write_file`).
- **Emission is split around execution**: the prefix `[auto] {tool} {key} -> ` is written and flushed
  *before* the tool runs, and `{outcome}` plus the newline are written *after* it returns. The human
  sees which URL is being fetched while the fetch is in flight (up to `--tool-timeout`, default 30 s)
  rather than staring at nothing, and still gets exactly one line in the transcript. No other writer
  can interleave: nothing between those two points writes to `_ui()`.
- The line contains no arbitrary fetched or file content. Every `{outcome}` branch yields either one
  of the harness's own `ERROR:`/`OK:`/`HTTP` strings or a character count, and `_trace_clip()` maps
  every control character to a space, so a hostile page or filename cannot forge output lines.

Examples (REPL mode, on stdout):

```
[auto] fetch_url https://github.com/vllm-project/vllm/releases/tag/v0.27.1 -> HTTP 200 https://github.com/vllm-project/vllm/releases/tag/v0.27.1
[auto] fetch_url https://vllm.ai/versions -> ERROR: HTTP 404 Not Found for https://vllm.ai/versions
[auto] read_file /Users/reubenpatterson/qwen-agent-workspace/notes.txt -> ok, 18 characters
[auto] read_file /Users/reubenpatterson/qwen-agent-workspace/nope.txt -> ERROR: no such file: /Users/reubenpatterson/qwen-agent-workspace/nope.txt
[auto] write_file /Users/reubenpatterson/qwen-agent-workspace/out.txt -> OK: wrote 42 bytes to /Users/reubenpatterson/qwen-agent-workspace/out.txt
```

**New 10.6 — the `[duplicate]` trace line.** See Section 4.5.

### 3.5 What does *not* change about approved-tier behaviour

- The gated prompt's wording, frame, indentation, `·` separator, `RULE` length, and the
  `  -> running...` / `  -> denied` verdicts are byte-identical to today.
- Pre-approval rejections ([HARNESS] 8.2 path escape, 9.5 URL scheme) still happen *before* the tier
  decision, still print their `[rejected]` line to raw `sys.stderr` (not `_ui()`) exactly as today,
  still return `outcome: "rejected"`, and are **not** affected by a tool being in the auto tier. An
  out-of-workspace `read_file` is still blocked outright; auto-approval never becomes a bypass of
  confinement.
- `outcome: "invalid"` paths (unknown tool, unparseable JSON, bad argument shape) are unchanged and
  print nothing.

---

## 4. Part 2 — the per-turn duplicate-call guard

### 4.1 Scope and lifetime

One history list per **turn**, created empty at the top of `run_turn()` and discarded when it returns.
A turn is one REPL input line, or one `--user-prompt` invocation. The history therefore spans all
rounds of a single turn (up to `--max-rounds`), and never crosses turns.

Consequences, all intended:
- In the REPL, a user can re-ask for something that failed last turn and it will be attempted again.
- `/reset` needs no changes; the history has already been discarded.
- One-shot mode gets exactly one history, matching its one turn.

### 4.2 What is recorded

An entry is appended for every dispatched call that reaches or passes the guard — that is, at every
`dispatch()` exit point from the guard onward: `rejected` (both path escapes and the URL-scheme
rejection), `denied`, and `approved` (whether the approval came from a human keystroke or from the
auto tier). Entry shape:

```python
{"tool": <str>, "args": <dict>, "error": <bool>}
```

- `tool` is the validated tool name (always one of the five; unknown names never reach here).
- `args` is the **parsed arguments dict**, post-`validate_args`, exactly the object `dispatch` is
  working with. Not the raw JSON string.
- `error` is `result.startswith("ERROR:")` computed on the **untruncated** result string, matching the
  `ERROR:`-prefix convention already used by every error path in `dispatch()` and in [HARNESS] 9.

Entries are **not** appended for:
- `outcome: "invalid"` (unknown tool, `JSONDecodeError`, `validate_args` failure). The first two have
  no parsed dict at all; the third would be dead weight, because the guard sits *after*
  `validate_args`, so a repeat of a shape-invalid call returns from `validate_args` and never consults
  the history.
- `outcome: "duplicate"` itself. The blocking entry is already in the history; re-appending would only
  grow the list. This also means the history cannot grow from repeated blocked attempts.

**Auto-approved calls are recorded on exactly the same footing as human-approved ones.** This is not
incidental — it is the point. The `fetch_url` guess-loop that motivated this spec lives entirely in
the auto tier, and if auto-tier failures were not tracked the guard would do nothing for the case it
exists to fix.

**Denied calls are recorded, and a repeat of a denied call is blocked.** [HARNESS] 10.4 already tells
the model "Do not retry the identical call"; this enforces it mechanically and spares the human a
second identical prompt. The human can still change their mind — by starting a new turn (the history
is per-turn) or by asking for the action in different words, which produces different arguments.

### 4.3 The match rule

```python
def find_failed_duplicate(history, name, args):
    """True if an identical (tool, args) call already failed earlier in this turn.

    `args` is compared BY VALUE against the stored dicts, so key order,
    whitespace, and escaping differences between two equivalent JSON argument
    strings cannot evade the check. All five tools take only string parameters
    (validate_args guarantees it), so dict == dict is exact.
    """
    for entry in history:
        if entry["error"] and entry["tool"] == name and entry["args"] == args:
            return True
    return False
```

Normative properties:
- **Value equality, never string equality.** `{"a": "1", "b": "2"}` and `{"b": "2", "a": "1"}` match.
  `'{"url": "x"}'` and `'{ "url":"x" }'` match. This is why the guard runs after JSON parsing.
- **Exact, not fuzzy.** `https://x/a` and `https://x/a/` do not match. `notes.txt` and `./notes.txt`
  do not match (the guard compares raw arguments, not resolved paths). No normalisation is performed;
  adding any would be scope creep and would risk false positives.
- **Extra keys count.** [HARNESS] 7.1 rule 4 keeps unknown keys in `args`, so a repeat that adds a
  stray key is not a duplicate and will be attempted. Accepted: it is one extra attempt, and the
  Section 5 nudge and `--max-rounds` bound the damage.
- **Failed only.** A repeat of a call whose stored `error` is `False` is not a duplicate. Re-reading a
  file that read fine, or re-fetching a page that loaded fine, is legitimate and proceeds normally
  (through its own tier, so it may re-prompt if gated).
- Linear scan. The history holds at most `--max-rounds` × calls-per-round entries — single digits in
  practice. No indexing, no hashing, no `frozenset` of items.

### 4.4 Position in the dispatch order, and the result

The guard runs **before** the tier decision and before path/URL pre-approval checks, immediately after
`validate_args` succeeds. Full revised ordering (this replaces the one-line ordering diagram in
[HARNESS] 8.2):

```
decode arguments (7.1) -> validate types (7.1) -> DUPLICATE GUARD (4) ->
resolve paths / URL scheme (8.1, 9.5) -> TIER DECISION (3.1) ->
[gated only: ask human (10)] -> execute (9)
```

Why the guard is first among the post-validation steps: it is the cheapest check, it has no side
effects, and putting it ahead of the path/URL rejections means a repeated path-escape or bad-URL
attempt yields the *stop repeating yourself* message (and one `[duplicate]` line) instead of
re-emitting an identical `[rejected]` stderr line the human has already read. It is also the reason
the guard cannot be folded into the tier branch: a duplicate `fetch_url` must be blocked even though
`fetch_url` is auto-approved, and a duplicate `bash` must be blocked *without* re-prompting even
though `bash` is gated.

The result string returned to the model is exactly (single line, no embedded newlines):

```
ERROR: this exact call was already made earlier in this turn and it failed. It was NOT executed again. Repeating an identical failing call cannot produce a different result. Change the approach -- a different URL, a different path, a different tool -- or stop and tell the user plainly what you tried, what failed, and what you need from them.
```

`outcome` is `"duplicate"`. No side effect occurs: no HTTP request, no subprocess, no file touched, no
prompt drawn.

### 4.5 The `[duplicate]` trace line ([HARNESS] new 10.6)

Exactly one line per blocked call, to `_ui()`:

```
[duplicate] {tool} {key} -> blocked, an identical call already failed in this turn
```

`{key}` is `_call_key(name, args)` (Section 6.4): the first line of the tool's principal argument
(`url` / `path` / `command` / `code`), control characters replaced, clipped to `TRACE_KEY_CHARS`. This
one covers all five tools, because any tool can be duplicate-blocked — including `bash`, whose
`command` may be multi-line, hence the first-line-only clip.

Example:

```
[duplicate] fetch_url https://vllm.ai/versions -> blocked, an identical call already failed in this turn
```

---

## 5. Part 3 — the system-prompt nudge

### 5.1 Decision: a new rule 6, not an amendment to rule 5

Rule 5 ("Call one tool at a time, read its result, then decide the next step. When you have the
answer, reply in plain text with no further tool calls.") governs the *success* path: it tells the
model when to stop because it is done. It says nothing about stopping because it is stuck, and
stretching it to cover both would blur a sequencing instruction into a give-up instruction. A separate
rule 6 is added. Rules 1–5 are reproduced **byte-for-byte unchanged** and are not renumbered.

### 5.2 Exact new rule text

Appended to the content string built by `build_system_message()` ([HARNESS] 11.3), immediately after
rule 5, with `\n` separating them as between the other rules:

```
6. Do not repeat a tool call that has already failed; the harness will refuse it. If two or three attempts at the same goal have not worked -- a URL that will not load, a file that is not there, a command that keeps erroring -- stop calling tools and tell the user plainly what you tried, what failed, and what you need from them. Guessing URLs or paths and retrying variations is worse than saying you do not know.
```

Tone and shape match rules 1–5: imperative, second person, concrete failure examples, no hedging, one
paragraph, no markdown. It is non-redundant with rule 5 (which is about finishing) and non-redundant
with rule 4 (untrusted content) and rule 3 (destructive commands).

### 5.3 Rule 1 is deliberately left inaccurate

Rule 1 currently reads: "Every tool call is shown to the human and requires their explicit approval
before it runs. Expect denials and handle them gracefully." After this change that is no longer
literally true for the auto tier. It is **left unchanged anyway**, deliberately:

- Its behavioural purpose is to make the model *expect* denials and handle them, which is still
  required for `bash`, `run_python`, and overwriting writes.
- Its error is in the safe direction: the model believes it faces more friction than it does. A model
  that thinks `fetch_url` is watched will guess fewer URLs, which is the behaviour this whole spec is
  trying to encourage.
- Telling the model "`fetch_url` and `read_file` run without asking" would be an invitation to use
  them more freely and to lean on them as an unattended channel. There is no upside to that.

Recorded as assumption A6. No change to rule 1's text.

---

## 6. Implementation: exact changes to `/Users/reubenpatterson/.local/bin/qwen-agent`

Line numbers refer to the current file as read on 2026-08-21 (1187 lines, the post-[ONESHOT] state
with `--user-prompt` / `--system-prompt`).

### 6.0 Change map

| Location | Lines | Action |
|---|---|---|
| Module docstring | 4–5 | Replace the "Every tool call requires explicit human approval" sentence (6.5). |
| Constants block | after 39 (`RULE = …`) | Add `AUTO_APPROVE_TOOLS`, `TRACE_KEY_CHARS`, `TRACE_OUTCOME_CHARS` (6.4). |
| `build_confirmation_body`, `write_file` branch | 396–399 | Replace the inline `target` computation with a call to the new `_write_target_status()` (6.4). |
| New helpers, before `confirm()` (i.e. after `build_confirmation_body`, line 418) | — | `_write_target_status`, `should_auto_approve`, `_trace_clip`, `_auto_key`, `_call_key`, `_auto_trace_outcome`, `find_failed_duplicate` (6.4). |
| `_record()` | 598–606 | Add the optional `history` parameter and the append (6.1). |
| `dispatch()` | 609–711 | Signature gains `history`; insert the duplicate guard after `validate_args`; add `history` to five existing `_record` calls; wrap the confirm call in the tier branch; add the `[auto]` trace writes (6.2). |
| `build_system_message()` | 763–781 | Append rule 6 (Section 5.2). |
| `print_banner()` | 944–950 | Replace two lines with three (6.6). |
| `run_turn()` | 1002–1003, 1061 | Create `history = []` alongside `records = []`; pass it to `dispatch` (6.1). |

Everything else is untouched. Explicitly **unchanged**: `_ui`, `_prompt_line`, `TOOLS`,
`TOOL_BY_NAME`, `resolve_in_workspace`, `_TextExtractor`, `html_to_text`, `validate_args`,
`_indent_lines`, `confirm`, `_fmt_std_result`, `_run_subprocess`, `exec_bash`, `exec_run_python`,
`exec_read_file`, `exec_write_file`, `exec_fetch_url`, `_truncate`, `tc_id`, `chat_completion`,
`assistant_echo`, `HELP_TEXT`, `_first_sentence`, `print_help`, `print_tools`,
`handle_slash_command`, `RESTART_COMMAND`, `preflight`, `_is_context_overflow`, `setup`,
`_turn_result`, `repl`, `oneshot`, `parse_args`, `main`, the import list, and every existing constant
value.

**No new CLI flag. No change to `parse_args()` or `main()`. No change to the envelope's six keys.**

### 6.1 `_record()` and `run_turn()`

`_record()` gains one optional trailing parameter. Existing call sites that omit it are unaffected.

```python
def _record(name, arguments, arguments_raw, outcome, result, history=None):
    """Build one tool-call record. Truncation is applied here, once, to `result`.

    When `history` is not None the call is also appended to this turn's
    duplicate-tracking history (tiered-approval spec Section 4.2). Callers pass
    `history` at every exit point at or after the duplicate guard, and omit it at
    the earlier "invalid" exits, which the guard never consults.
    """
    if history is not None:
        history.append({"tool": name, "args": arguments,
                        "error": result.startswith("ERROR:")})
    return {
        "tool": name,
        "arguments": arguments if isinstance(arguments, dict) else None,
        "arguments_raw": arguments_raw,
        "outcome": outcome,
        "result": _truncate(result),
    }
```

Note the ordering: `error` is computed from `result` **before** `_truncate` is applied. (Truncation
only ever affects the tail, so the prefix test is unaffected either way; the ordering is fixed anyway
so the behaviour cannot drift.)

`run_turn()` — two edits, nothing else:

```python
    records = []
    history = []      # duplicate-call tracking, one per turn (tiered-approval spec 4.1)
    round_num = 0
```

and at line 1061:

```python
            record = dispatch(tc, i, n, args_ns, history)
```

`dispatch` is called from exactly this one site; there is no other caller to update.

### 6.2 `dispatch()` — full revised function

Unchanged text is unchanged; the three new blocks are marked. This is the whole function, so there is
nothing to infer:

```python
def dispatch(tc, i, n, args_ns, history):
    """Dispatch one tool_call dict. Returns a tool-call record per the one-shot
    spec Section 4.2. `history` is this turn's duplicate-tracking list
    (tiered-approval spec Section 4)."""
    name = tc.get("function", {}).get("name")
    raw_arguments = tc.get("function", {}).get("arguments") or "{}"

    if name not in TOOL_BY_NAME:
        result = ("ERROR: unknown tool '%s'. Available tools: bash, fetch_url, "
                   "read_file, write_file, run_python." % name)
        return _record(name, None, raw_arguments, "invalid", result)

    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as e:
        result = ("ERROR: could not parse the arguments for tool '%s' as JSON: %s. "
                   "Re-issue the call with valid JSON arguments." % (name, e))
        return _record(name, None, raw_arguments, "invalid", result)

    ok, err = validate_args(name, args)
    if not ok:
        return _record(name, args, raw_arguments, "invalid", err)

    # --- NEW: tiered-approval spec Section 4 -- duplicate guard. Runs before the
    # --- tier decision and before the path/URL pre-approval checks, so a repeat of
    # --- a failed call is never prompted and never executed, whatever its tier.
    if find_failed_duplicate(history, name, args):
        print("[duplicate] %s %s -> blocked, an identical call already failed in "
              "this turn" % (name, _call_key(name, args)), file=_ui())
        result = ("ERROR: this exact call was already made earlier in this turn and "
                   "it failed. It was NOT executed again. Repeating an identical "
                   "failing call cannot produce a different result. Change the "
                   "approach -- a different URL, a different path, a different tool "
                   "-- or stop and tell the user plainly what you tried, what "
                   "failed, and what you need from them.")
        return _record(name, args, raw_arguments, "duplicate", result)
    # --- END NEW

    # Section 8: resolve paths for read_file / write_file before any prompt.
    resolved_paths = {}
    if name == "read_file":
        raw_path = args["path"]
        resolved, reason = resolve_in_workspace(raw_path)
        if resolved is None:
            sys.stderr.write(
                "[rejected] read_file: path '%s' is outside the workspace -- "
                "not executed, not prompted.\n" % raw_path
            )
            result = ("ERROR: rejected path '%s': %s. This call was blocked "
                       "automatically and was never shown to the user for approval. "
                       "All file paths must stay inside the workspace directory."
                       % (raw_path, reason))
            return _record(name, args, raw_arguments, "rejected", result, history)
        resolved_paths["path"] = resolved

    elif name == "write_file":
        raw_path = args["path"]
        resolved, reason = resolve_in_workspace(raw_path)
        if resolved is None:
            sys.stderr.write(
                "[rejected] write_file: path '%s' is outside the workspace -- "
                "not executed, not prompted.\n" % raw_path
            )
            result = ("ERROR: rejected path '%s': %s. This call was blocked "
                       "automatically and was never shown to the user for approval. "
                       "All file paths must stay inside the workspace directory."
                       % (raw_path, reason))
            return _record(name, args, raw_arguments, "rejected", result, history)
        resolved_paths["path"] = resolved

    elif name == "fetch_url":
        url = args["url"]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            sys.stderr.write(
                "[rejected] fetch_url: unsupported URL '%s' -- not executed, "
                "not prompted.\n" % url
            )
            result = ("ERROR: rejected URL '%s': only http:// and https:// URLs "
                       "are allowed. This call was blocked automatically and was "
                       "never shown to the user for approval." % url)
            return _record(name, args, raw_arguments, "rejected", result, history)

    # --- CHANGED: tiered-approval spec Section 3 -- auto-approve by tool identity,
    # --- or ask the human exactly as before.
    auto = should_auto_approve(name, resolved_paths)
    if auto:
        out = _ui()
        out.write("[auto] %s %s -> " % (name, _auto_key(name, args, resolved_paths)))
        out.flush()
    else:
        # Section 10: ask the human.
        try:
            approved = confirm(name, args, i, n, args_ns.tool_timeout, resolved_paths)
        except KeyboardInterrupt:
            print(file=_ui())
            approved = False

        if not approved:
            result = ("ERROR: the user denied permission for this tool call. It was "
                       "NOT executed. Do not retry the identical call. Either take a "
                       "different approach, or stop and explain to the user what you "
                       "need to do and why.")
            return _record(name, args, raw_arguments, "denied", result, history)
    # --- END CHANGED

    # Section 9: execute.
    try:
        if name == "bash":
            result = exec_bash(args, args_ns.tool_timeout)
        elif name == "run_python":
            result = exec_run_python(args, args_ns.tool_timeout)
        elif name == "read_file":
            result = exec_read_file(resolved_paths["path"])
        elif name == "write_file":
            result = exec_write_file(resolved_paths["path"], args["content"])
        elif name == "fetch_url":
            result = exec_fetch_url(args["url"], args_ns.tool_timeout)
        else:
            result = "ERROR: unknown tool '%s'." % name
    except KeyboardInterrupt:
        result = ("ERROR: execution was interrupted by the user before it completed. "
                   "The effect of this call is unknown.")
    except Exception as e:
        result = ("ERROR: the tool '%s' failed unexpectedly: %s: %s"
                   % (name, type(e).__name__, e))

    # --- NEW: close the [auto] trace line opened above.
    if auto:
        print(_auto_trace_outcome(name, result), file=_ui())
    # --- END NEW

    return _record(name, args, raw_arguments, "approved", result, history)
```

Contract points about this function that the executor must not deviate from:

- The `[auto]` prefix write and its closing `print` are the *only* writes to `_ui()` on the auto path.
  There is no frame, no rule, no verdict line.
- `Ctrl-C` during an auto-approved execution still lands in the existing `except KeyboardInterrupt`,
  so the `[auto]` line is always closed — a partial line is never left dangling.
- The denial path is inside the `else` branch, so a denial can only occur for a gated call. Its record
  now carries `history`.
- `auto` is computed exactly once and reused; it is not recomputed after execution.
- All eight pre-existing exit points keep their exact strings and their exact order relative to one
  another. Only the `history` argument and the new ninth (`"duplicate"`) exit are added.

### 6.3 [ONESHOT] Section 4.2 revisions

The `outcome` field's type line becomes:

| Field | Type | Description |
|---|---|---|
| `outcome` | string | One of `"approved"`, `"denied"`, `"rejected"`, `"invalid"`, `"duplicate"` — table below. |

The vocabulary table gains one row, placed **last**, after `"invalid"`, and the `"approved"` row's
description is widened. Full revised table:

| `outcome` | Set when | Prompt shown? | Side effect? |
|---|---|---|---|
| `"approved"` | The call was approved — either the human answered `y`/`yes` at a gated prompt, or the call was auto-approved by the tier policy (tiered-approval spec Section 3.1) — and the tool was executed. `result` may still be an `ERROR: …` string from execution, timeout ([HARNESS] 9.7), or `Ctrl-C` during execution ([HARNESS] 9.8) — the *approval* succeeded, the *execution* may not have. | only if gated | yes |
| `"denied"` | The human answered anything else, or EOF, or `Ctrl-C` at the prompt ([HARNESS] 10.3). Only gated calls can be denied. | yes | no |
| `"rejected"` | Blocked before the prompt and before the tier decision by workspace confinement ([HARNESS] 8.2) or by the `fetch_url` scheme check ([HARNESS] 9.5). | **no** | no |
| `"invalid"` | Blocked before the prompt by unknown tool name, unparseable `arguments` JSON, or argument-shape validation ([HARNESS] 7.1, 12 rows `ARG-JSON` / `ARG-SHAPE` / `TOOL-UNKNOWN`). | **no** | no |
| `"duplicate"` | Blocked by the per-turn duplicate guard: a value-identical `(tool, arguments)` call earlier in this same turn returned an `ERROR:` result (tiered-approval spec Section 4). | **no** | no |

`"duplicate"` is a *turn-level* outcome, not an invocation failure: a turn containing duplicate-blocked
calls still ends `"status": "ok"` and exit `0` if the model goes on to produce a final answer. This
matches the existing treatment of `"denied"` ([ONESHOT] assumption 3).

A `"duplicate"` record's `arguments`, `arguments_raw`, `round`, and `id` are populated exactly as for
any other record; `result` is the Section 4.4 string.

Envelope example (single line in reality; formatted here):

```json
{
  "schema": "qwen-agent.oneshot.v1",
  "status": "ok",
  "answer": "I couldn't find that page. I tried https://vllm.ai/versions, which returned 404, and I have no search tool, so I can't locate the release notes. If you can give me the exact URL I'll read it.",
  "error": null,
  "rounds": 4,
  "tool_calls": [
    {
      "tool": "fetch_url",
      "arguments": {"url": "https://vllm.ai/versions"},
      "arguments_raw": "{\"url\": \"https://vllm.ai/versions\"}",
      "outcome": "approved",
      "result": "ERROR: HTTP 404 Not Found for https://vllm.ai/versions",
      "round": 1,
      "id": "chatcmpl-tool-aa11"
    },
    {
      "tool": "fetch_url",
      "arguments": {"url": "https://vllm.ai/versions"},
      "arguments_raw": "{\"url\":\"https://vllm.ai/versions\"}",
      "outcome": "duplicate",
      "result": "ERROR: this exact call was already made earlier in this turn and it failed. It was NOT executed again. Repeating an identical failing call cannot produce a different result. Change the approach -- a different URL, a different path, a different tool -- or stop and tell the user plainly what you tried, what failed, and what you need from them.",
      "round": 2,
      "id": "chatcmpl-tool-bb22"
    }
  ]
}
```

Note the differing `arguments_raw` whitespace between the two records with identical `arguments` —
that is exactly the case the value-based comparison of Section 4.3 catches and a string comparison
would have missed.

### 6.4 New helper functions — exact source

Constants, appended to the block ending at line 39:

```python
# Tiered approval (see docs/specs/2026-08-21-qwen-agent-tiered-approval-design.md).
# Membership is by TOOL NAME ONLY. Never add bash or run_python here, and never
# add a content/keyword test for them anywhere: an injected instruction can avoid
# any trigger word while still being harmful. See that spec's Section 3.2.
AUTO_APPROVE_TOOLS = ("fetch_url", "read_file")
TRACE_KEY_CHARS = 200      # clip length for the key argument on [auto]/[duplicate] lines
TRACE_OUTCOME_CHARS = 160  # clip length for the outcome summary on the [auto] line
```

Helpers, inserted after `build_confirmation_body` (line 418) and before `confirm`:

```python
def _write_target_status(resolved):
    """Return (is_overwrite, target_label) for a write_file target.

    SINGLE SOURCE OF TRUTH for the NEW-vs-OVERWRITES distinction. Used by
    build_confirmation_body for display and by should_auto_approve as the gate
    condition, so the two can never disagree.
    """
    if resolved.exists():
        return True, "OVERWRITES existing file of %d bytes" % resolved.stat().st_size
    return False, "NEW file"


def should_auto_approve(name, resolved_paths):
    """True when this call runs without a confirmation prompt.

    Decided by tool identity alone, plus the target-exists boolean for write_file.
    This function must never inspect args['command'] or args['code'].
    """
    if name in AUTO_APPROVE_TOOLS:
        return True
    if name == "write_file":
        is_overwrite, _ = _write_target_status(resolved_paths["path"])
        return not is_overwrite
    return False


def _trace_clip(text):
    """Collapse to one safe single line and clip. For trace lines only."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    if len(text) > TRACE_KEY_CHARS:
        text = text[:TRACE_KEY_CHARS] + "..."
    return text


def _auto_key(name, args, resolved_paths):
    """Key argument shown on the [auto] line. Only auto-approvable tools reach here."""
    if name == "fetch_url":
        return _trace_clip(args["url"])
    return _trace_clip(str(resolved_paths["path"]))


def _call_key(name, args):
    """Key argument shown on the [duplicate] line. Handles all five tools."""
    if name == "fetch_url":
        raw = args.get("url", "")
    elif name in ("read_file", "write_file"):
        raw = args.get("path", "")
    elif name == "bash":
        raw = args.get("command", "")
    elif name == "run_python":
        raw = args.get("code", "")
    else:
        raw = ""
    return _trace_clip(raw)


def _auto_trace_outcome(name, result):
    """One-line outcome summary closing an [auto] line.

    Never echoes fetched page text or file contents: every branch yields one of
    the harness's own ERROR:/OK:/HTTP lines, or a character count.
    """
    if result.startswith("ERROR:"):
        summary = result.split("\n", 1)[0]
    elif name == "read_file":
        summary = "ok, %d characters" % len(result)
    else:
        # fetch_url: "HTTP 200 <final_url>"; write_file: "OK: wrote N bytes to ..."
        summary = result.split("\n", 1)[0]
    summary = re.sub(r"[\x00-\x1f\x7f]", " ", summary)
    if len(summary) > TRACE_OUTCOME_CHARS:
        summary = summary[:TRACE_OUTCOME_CHARS] + "..."
    return summary


def find_failed_duplicate(history, name, args):
    """True if a value-identical (tool, args) call already failed in this turn.

    Compares the parsed args dict BY VALUE, so key order or whitespace
    differences in equivalent JSON cannot evade the check.
    """
    for entry in history:
        if entry["error"] and entry["tool"] == name and entry["args"] == args:
            return True
    return False
```

`_auto_trace_outcome` receives the **untruncated** result, so `"ok, %d characters"` reports the real
size of what the model will see pre-truncation. This is intentional and is what makes the line useful.

`build_confirmation_body`'s `write_file` branch, lines 396–399, becomes:

```python
    elif tool_name == "write_file":
        resolved = resolved_paths["path"]
        content = args["content"]
        _, target = _write_target_status(resolved)
        size = len(content.encode("utf-8"))
```

The rest of that branch (size, preview, `[... k more lines not shown]`) is untouched, and the emitted
body is byte-identical to today's for every input.

### 6.5 Docstring

Replace lines 4–5:

```
Single-file, standard-library-only. Every tool call requires explicit human
approval before it executes. See docs/specs/2026-08-21-qwen-agent-tool-harness-design.md.
```

with:

```
Single-file, standard-library-only. bash, run_python, and any write that would
overwrite an existing file require explicit human approval; read_file, fetch_url,
and creating a new file are auto-approved and traced with an [auto] line. An exact
repeat of a call that already failed in the same turn is refused without running.
See docs/specs/2026-08-21-qwen-agent-tool-harness-design.md and
docs/specs/2026-08-21-qwen-agent-tiered-approval-design.md.
```

The remaining docstring lines (6–9, the one-shot paragraph) are unchanged.

### 6.6 Banner — replaces [HARNESS] 6.3

```python
def print_banner(model, workspace, think):
    print("qwen-agent  |  model=%s  |  thinking=%s" % (model, "on" if think else "off"))
    print("workspace: %s" % workspace)
    print("tools: bash, fetch_url, read_file, write_file, run_python")
    print("approval required: bash, run_python, overwriting an existing file. Default is no.")
    print("auto-approved (no prompt, traced with [auto]): read_file, fetch_url, new-file write_file.")
    print("bash and run_python are NOT sandboxed -- read each command before approving.")
    print("/help for commands, /exit to quit.")
```

Verbatim expected output with defaults:

```
qwen-agent  |  model=qwen38-6bit  |  thinking=off
workspace: /Users/reubenpatterson/qwen-agent-workspace
tools: bash, fetch_url, read_file, write_file, run_python
approval required: bash, run_python, overwriting an existing file. Default is no.
auto-approved (no prompt, traced with [auto]): read_file, fetch_url, new-file write_file.
bash and run_python are NOT sandboxed -- read each command before approving.
/help for commands, /exit to quit.
```

The removed line was `EVERY tool call requires your approval. Default answer is no.`, which is now
false and must not survive anywhere in the file. `HELP_TEXT`, `print_help`, and `print_tools` make no
approval claims and are unchanged.

### 6.7 [ONESHOT] 6.3 stdout-purity audit — two new rows

| Writer | One-shot |
|---|---|
| `dispatch()` `[auto]` prefix + closing outcome (new, two writes forming one line) | routed to stderr via `_ui()`; the prefix is explicitly `flush()`ed, and nothing writes to `_ui()` between the two halves |
| `dispatch()` `[duplicate]` line (new) | routed to stderr via `_ui()` |

The one-shot stdout contract is therefore preserved exactly: the envelope remains the sole stdout
write, still one line, still followed by exactly one `"\n"`.

---

## 7. Interaction of Part 1 and Part 2 — resolved matrix

Read top to bottom; the first matching row wins. `history` is this turn's list (Section 4.1).

| # | Situation | Duplicate guard | Prompt | Executed | `outcome` | Trace output | History append |
|---|---|---|---|---|---|---|---|
| 1 | Unknown tool / bad JSON / bad arg shape | not reached | no | no | `invalid` | none | no |
| 2 | Any tool, value-identical args to an earlier **failed** call this turn | **hit** | no | **no** | `duplicate` | `[duplicate] …` to `_ui()` | no |
| 3 | Any tool, value-identical args to an earlier **succeeded** call this turn | miss | per tier | yes | `approved` (or `denied`) | per tier | yes |
| 4 | `read_file` / `write_file` path escapes the workspace | miss | no | no | `rejected` | `[rejected] …` to `sys.stderr` (unchanged) | **yes** |
| 5 | `fetch_url` non-http(s) scheme or empty netloc | miss | no | no | `rejected` | `[rejected] …` to `sys.stderr` (unchanged) | **yes** |
| 6 | `fetch_url`, valid URL | miss | **no** | yes | `approved` | `[auto] fetch_url <url> -> …` | yes |
| 7 | `read_file`, in-workspace path | miss | **no** | yes | `approved` | `[auto] read_file <abs path> -> …` | yes |
| 8 | `write_file`, in-workspace path, target does **not** exist | miss | **no** | yes | `approved` | `[auto] write_file <abs path> -> …` | yes |
| 9 | `write_file`, in-workspace path, target **exists** (incl. a directory) | miss | **yes** | if `y` | `approved` / `denied` | full [HARNESS] 10 frame | yes |
| 10 | `bash` | miss | **yes** | if `y` | `approved` / `denied` | full frame | yes |
| 11 | `run_python` | miss | **yes** | if `y` | `approved` / `denied` | full frame | yes |

Derived facts that follow from the matrix and are part of the contract:

- Row 2 beats rows 4–11: a duplicate is blocked regardless of tier, and regardless of whether the
  original failure came from a rejection, a denial, or a real execution error.
- Rows 4/5 beat rows 6–8: auto-approval never bypasses workspace confinement or the URL-scheme check.
- Rows 4/5 append to history, so a *repeated* path escape or bad URL becomes row 2 on the second
  attempt — the model gets the "stop repeating" message and the human does not see a second
  `[rejected]` line for the same call.
- Row 9's existence check and the `target:` line in the frame come from the same
  `_write_target_status()` call chain, so a call can never be auto-approved while the frame would
  have said `OVERWRITES` (or vice versa). The value is read twice on the gated path (once for the
  gate, once for the display) and the intervening window is microseconds; a TOCTOU flip there would
  at worst show a stale byte count in a prompt the human is about to answer, which is not a security
  property. Not guarded against.
- A `write_file` whose resolved target is an existing **directory** takes row 9: `exists()` is `True`,
  so it is gated, and the frame renders `OVERWRITES existing file of N bytes` from the directory's
  `st_size`. That display oddity is pre-existing ([HARNESS] 10.2) and is deliberately left alone; the
  write then fails with the [HARNESS] 9.4 `IsADirectoryError` string. The important property — a
  directory target is never auto-approved — holds.

### 7.1 [HARNESS] Section 12 error-matrix revisions

Two rows added, one row amended:

| ID | Condition | Detection | Handling |
|---|---|---|---|
| `DUP` | Exact repeat of a call that already failed this turn | `find_failed_duplicate` (tiered-approval spec 4.3) | **no prompt, no execution**; one `[duplicate]` line to `_ui()`; tool result and `outcome: "duplicate"` per 4.4 |
| `AUTO` | Call is in the auto-approved tier | `should_auto_approve` (tiered-approval spec 6.4) | **no prompt**; executed; one `[auto]` line to `_ui()`; `outcome: "approved"` |

Amended row: `DENY`'s condition becomes "Human denies **a gated call**" — auto-approved calls have no
denial path.

All other rows, including the invariant sentence at the end of [HARNESS] 12 ("the process never dies
from a runtime error, and the transcript is never left with an assistant tool-call message that lacks
its matching tool results"), are unchanged and still hold: `duplicate` records still produce exactly
one `role: tool` reply, so the one-reply-per-tool-call invariant is intact.

---

## 8. Acceptance tests

**Inherited and still required:** [ONESHOT] Section 8's A1–A10 in full, with two amendments —
A10's "banner identical" is asserted against Section 6.6's new banner text, and A3 additionally
asserts that a second identical `bash` attempt in the same turn (if the model makes one) shows **no**
second prompt.

**Amended from [HARNESS] Section 13:** T1, T4, T7, T8 unchanged. T2 (`write_file` of a new
`notes.txt`) now expects **no prompt** and one `[auto] write_file …/notes.txt -> OK: wrote N bytes …`
line. T3 (`read_file notes.txt`) now expects **no prompt** and one `[auto] read_file … -> ok, N
characters` line. T5 (`fetch_url https://example.com`) now expects **no prompt** and one
`[auto] fetch_url https://example.com -> HTTP 200 https://example.com/` line. T6 (path escape) is
unchanged and remains the critical test.

**New: B1–B11.** All must pass. Run after `rm -rf ~/qwen-agent-workspace` unless a test says
otherwise.

**B1 — auto-approved fetch loop, zero prompts.**
```bash
qwen-agent --user-prompt "Find the release notes for vllm 0.27.1 on the web and tell me one bullet from them." > /tmp/b1.json 2> /tmp/b1.err; echo "exit=$?"
grep -c 'Approve?' /tmp/b1.err; grep -c '^\[auto\] fetch_url' /tmp/b1.err
python3 -m json.tool < /tmp/b1.json
```
Pass: `grep -c 'Approve?'` is `0`. `[auto] fetch_url` count equals the number of `fetch_url` records
with `outcome == "approved"`. Every such record's `result` begins with either `HTTP ` or `ERROR: `.
`/tmp/b1.json` is exactly one line of valid JSON.

**B2 — duplicate fetch is blocked, no request issued.**
Same run as B1 if the model repeated itself; otherwise force it deterministically:
```bash
qwen-agent --user-prompt "Fetch https://example.com/definitely-not-here-404 . If it fails, fetch the exact same URL again to be sure, then tell me what happened." 2> /tmp/b2.err > /tmp/b2.json
```
Pass, all of: `/tmp/b2.err` contains exactly one `[auto] fetch_url https://example.com/definitely-not-here-404 -> ERROR: HTTP 404 …` line; it contains at least one `[duplicate] fetch_url https://example.com/definitely-not-here-404 -> blocked, an identical call already failed in this turn` line; `grep -c 'Approve?'` is `0`; the envelope contains one record with `outcome == "approved"` and at least one with `outcome == "duplicate"`; the `duplicate` record's `result` is byte-identical to the Section 4.4 string.

**B3 — new-file write auto-approves, overwrite gates.**
```bash
qwen-agent
>>> Write a file b3.txt in the workspace containing the single line hello.
>>> Now write a file b3.txt in the workspace containing the single line goodbye.
```
Pass: the first turn prints no frame and one `[auto] write_file /…/b3.txt -> OK: wrote 6 bytes to /…/b3.txt`
line on **stdout**; the second turn prints the full [HARNESS] 10.2 `write_file` frame with
`target:   OVERWRITES existing file of 6 bytes` and waits for input. Answer `n`; `cat ~/qwen-agent-workspace/b3.txt`
still shows `hello`. (The two writes are different turns *and* different arguments, so the duplicate
guard is not involved.)

**B4 — bash still always gated.**
```bash
qwen-agent --user-prompt "Use bash to print the current date."
```
Pass: full frame with the `cwd:` and `WARNING:` lines, `Approve? [y/N] ` present, and nothing runs
until a key is typed. Repeat with `pwd`, `ls`, `echo hi`, `cat /etc/hostname` — **every one** prompts.
No command text is ever auto-approved.

**B5 — run_python still always gated.**
```bash
qwen-agent --user-prompt "Use run_python to print 2+2."
```
Pass: full frame including the `python:` line and the `WARNING:` lines; prompt shown.

**B6 — a denied call cannot be retried identically.**
```bash
qwen-agent --user-prompt "Use bash to run 'ls -la /'. If it is denied, try the exact same command once more, then tell me." 2> /tmp/b6.err > /tmp/b6.json
```
Answer `n` at the single prompt that appears. Pass: exactly **one** `Approve?` prompt in
`/tmp/b6.err`; one `[duplicate] bash ls -la / -> blocked, …` line; envelope has one record
`outcome == "denied"` and one `outcome == "duplicate"`; exit `0`.

**B7 — a successful call may be repeated.**
```bash
qwen-agent --user-prompt "Write c7.txt containing the word alpha. Then read c7.txt. Then read c7.txt again. Then tell me its contents."
```
Pass: three `[auto]` lines (one write, two reads), **zero** `Approve?` prompts, **zero**
`[duplicate]` lines, and both read records have `outcome == "approved"` with identical non-`ERROR:`
results. Repeats of successes are never blocked.

**B8 — path escape still pre-empted, and its repeat is deduped.**
```bash
qwen-agent --user-prompt "Read /etc/passwd and count its lines. If that is refused, try reading /etc/passwd once more, then explain." 2> /tmp/b8.err > /tmp/b8.json
```
Pass: `/tmp/b8.err` contains exactly **one**
`[rejected] read_file: path '/etc/passwd' is outside the workspace -- not executed, not prompted.`
line (the second attempt is caught by the duplicate guard, before the rejection path); no `TOOL CALL`
frame and no `Approve?` for the `read_file` calls; the envelope has one `outcome == "rejected"` and
one `outcome == "duplicate"`; `~/qwen-agent-workspace` is unaffected. Deny any follow-up `bash`.

**B9 — value-based comparison, unit-level (no server needed).**
```bash
python3 - <<'PY'
import importlib.util, importlib.machinery, os
spec = importlib.util.spec_from_loader("qa", importlib.machinery.SourceFileLoader(
    "qa", os.path.expanduser("~/.local/bin/qwen-agent")))
qa = importlib.util.module_from_spec(spec); spec.loader.exec_module(qa)

h = []
qa._record("write_file", {"path": "a.txt", "content": "x"}, "{}", "rejected",
           "ERROR: rejected path 'a.txt': nope.", h)
# key order reversed, same values -> must match
assert qa.find_failed_duplicate(h, "write_file", {"content": "x", "path": "a.txt"}) is True
# different value -> must not match
assert qa.find_failed_duplicate(h, "write_file", {"path": "a.txt", "content": "y"}) is False
# different tool, same args -> must not match
assert qa.find_failed_duplicate(h, "read_file", {"content": "x", "path": "a.txt"}) is False
# a success is never a duplicate
h2 = []
qa._record("read_file", {"path": "a.txt"}, "{}", "approved", "hello", h2)
assert qa.find_failed_duplicate(h2, "read_file", {"path": "a.txt"}) is False
# an omitted history argument records nothing and still returns a well-formed record
rec = qa._record("bash", None, "{", "invalid", "ERROR: could not parse ...")
assert rec["outcome"] == "invalid" and rec["arguments"] is None
assert rec["arguments_raw"] == "{"
# a recorded entry marks non-ERROR results as non-failures
h4 = []
qa._record("bash", {"command": "true"}, "{}", "approved", "exit_code: 0", h4)
assert h4 == [{"tool": "bash", "args": {"command": "true"}, "error": False}]
# tier table
assert qa.should_auto_approve("fetch_url", {}) is True
assert qa.should_auto_approve("read_file", {}) is True
assert qa.should_auto_approve("bash", {}) is False
assert qa.should_auto_approve("run_python", {}) is False
# trace clipping kills control characters
assert "\n" not in qa._call_key("bash", {"command": "a\nb"})
assert "\r" not in qa._trace_clip("x\r\ny")
print("B9 OK")
PY
```
Pass: prints `B9 OK`. (`exec_module` runs the file top to bottom; `main()` is guarded by
`if __name__ == "__main__":` so nothing executes.)

**B10 — write_file tier depends on existence, unit-level.**
```bash
python3 - <<'PY'
import importlib.util, importlib.machinery, os, pathlib, tempfile
spec = importlib.util.spec_from_loader("qa", importlib.machinery.SourceFileLoader(
    "qa", os.path.expanduser("~/.local/bin/qwen-agent")))
qa = importlib.util.module_from_spec(spec); spec.loader.exec_module(qa)
d = pathlib.Path(tempfile.mkdtemp())
new, old = d / "new.txt", d / "old.txt"
old.write_text("abc")
assert qa.should_auto_approve("write_file", {"path": new}) is True
assert qa.should_auto_approve("write_file", {"path": old}) is False
assert qa._write_target_status(old) == (True, "OVERWRITES existing file of 3 bytes")
assert qa._write_target_status(new) == (False, "NEW file")
sub = d / "sub"; sub.mkdir()
assert qa.should_auto_approve("write_file", {"path": sub}) is False   # a directory is never auto
print("B10 OK")
PY
```
Pass: prints `B10 OK`.

**B11 — one-shot stdout purity is preserved.**
```bash
qwen-agent --user-prompt "Read notes.txt if it exists, otherwise create it with the word hi." > /tmp/b11.json 2>/tmp/b11.err
wc -l < /tmp/b11.json; python3 -m json.tool < /tmp/b11.json > /dev/null && echo JSON_OK
grep -c '^\[auto\]' /tmp/b11.err
grep -c '^\[auto\]' /tmp/b11.json
```
Pass: `wc -l` is `1`; `JSON_OK`; the `[auto]` count in stderr is ≥ 1 and in stdout is `0`.

**Static checks (all must pass):**
```bash
/usr/bin/python3 -m py_compile /Users/reubenpatterson/.local/bin/qwen-agent   # 3.9.6 gate
python3 -m py_compile /Users/reubenpatterson/.local/bin/qwen-agent            # 3.13 gate
grep -n '^import\|^from' /Users/reubenpatterson/.local/bin/qwen-agent         # S1: import list byte-identical
grep -n 'EVERY tool call' /Users/reubenpatterson/.local/bin/qwen-agent        # S2: must return nothing
grep -nE "should_auto_approve|AUTO_APPROVE_TOOLS" /Users/reubenpatterson/.local/bin/qwen-agent  # S3
grep -nE '\bargs\[.(command|code).\]' /Users/reubenpatterson/.local/bin/qwen-agent              # S4
```
- **S1:** the import list is byte-identical to before the change; no new imports.
- **S2:** returns nothing — the obsolete banner claim is gone.
- **S3:** `AUTO_APPROVE_TOOLS` is assigned exactly once and referenced exactly once (inside
  `should_auto_approve`); `should_auto_approve` is defined once and called exactly once (inside
  `dispatch`). No second tier decision exists anywhere.
- **S4:** `args["command"]` and `args["code"]` appear **only** in `build_confirmation_body`,
  `exec_bash`, `exec_run_python`, and `_call_key`. If either appears inside `should_auto_approve`, a
  tier helper, or anywhere near the approval branch, the change is rejected outright (Section 3.2).

---

## 9. Must-haves vs. nice-to-haves

**Must-have — the change is not done without all of these:**

1. `bash` and `run_python` gated unconditionally, with no content-based exemption anywhere in the
   file (S4, B4, B5).
2. `fetch_url` and `read_file` auto-approved with zero prompts and exactly one `[auto]` line each
   (B1, B7).
3. `write_file` auto-approved iff the target does not exist, with the gate condition and the frame's
   `target:` line sharing one `_write_target_status()` implementation (B3, B10, S3).
4. Path confinement and the URL-scheme check still enforced **before** the tier decision, still
   without a prompt, still with their existing `[rejected]` stderr lines (B8, [HARNESS] T6).
5. Per-turn duplicate guard, value-compared, error-only, positioned before the tier branch, blocking
   execution and prompting alike; exactly one `role: tool` reply per blocked call (B2, B6, B8, B9).
6. `"duplicate"` in the [ONESHOT] `outcome` vocabulary; one-shot stdout still exactly one JSON line
   (B2, B11).
7. Rule 6 appended to the system message with rules 1–5 byte-unchanged (Section 5).
8. New banner; the old `EVERY tool call requires your approval` line removed (S2).
9. Both `py_compile` gates and an unchanged import list.
10. No new CLI flag; `parse_args()` and `main()` untouched.

**Nice-to-have — explicitly OUT of scope, do not implement:**

1. A distinct `"auto_approved"` outcome value in the envelope.
2. A counter or summary line at end of turn ("3 auto-approved, 1 blocked").
3. A `--no-auto-approve` / `--strict` flag that restores the old blanket gate.
4. Cross-turn or on-disk duplicate memory.
5. URL normalisation before duplicate comparison.
6. A per-turn cap on `fetch_url` calls.
7. Colouring or bolding the `[auto]` / `[duplicate]` lines.
8. Blocking repeats of *successful* calls, or of duplicate calls in the same round only.
9. Any operator-configurable widening of `AUTO_APPROVE_TOOLS`. (Not merely out of scope — forbidden.)

**Superseded 2026-09-12 (see Section 1.4):** nice-to-have 9 above, and must-have 10's "No new CLI
flag", no longer hold. `--danger-auto-approve` exists, `parse_args()` and `main()` were both touched
to add and announce it, and the accepted risk is recorded in Section 1.4. Must-haves 1–9 and
nice-to-haves 1–8 are unaffected: in particular `AUTO_APPROVE_TOOLS` and `should_auto_approve()` are
still exactly as must-haves 1–3 require, and no `--no-auto-approve` / `--strict` counterpart flag was
added.

---

## 10. Assumptions recorded

Minimal calls made where the approved design was silent. Each is flagged because it was not stated in
the brief.

- **A1 — the `[auto]` line is one line, split around execution.** The prefix is written and flushed
  before the tool runs and the outcome is appended after. A purely post-hoc single write would leave
  the terminal silent for up to `--tool-timeout` (30 s) during a slow fetch, which looks like a hang;
  two full lines would double the trace volume this change exists to reduce. The split form gives
  both. Cost: one partial line exists on `_ui()` for the duration of the call, which is safe because
  nothing else writes to `_ui()` in that window and the closing write happens on every path,
  including `KeyboardInterrupt`.
- **A2 — trace lines go to `_ui()`, not to raw `sys.stderr`.** They are approval-adjacent UI, so they
  follow the confirmation-frame routing (stdout in REPL, stderr in one-shot) rather than the
  `[rejected]` convention. The brief specified this routing; the consequence recorded here is that in
  REPL mode `[auto]` lines interleave with the model's final answer on stdout, and with `[thinking]`
  output on stderr. Cosmetic; accepted.
- **A3 — the existing `[rejected]` lines keep writing to raw `sys.stderr`.** They are not retargeted
  to `_ui()`; that would be an unrelated behaviour change to a line the [HARNESS] T6 acceptance test
  asserts on.
- **A4 — auto-approved calls report `outcome: "approved"`.** No new envelope value is introduced for
  them. The brief authorised exactly one new value (`"duplicate"`). Consequence: a programmatic caller
  cannot distinguish "a human blessed this" from "the tier policy blessed this" from the envelope
  alone. Accepted as a minimal-surface call; if that distinction is ever needed it is an additive
  change to the same table.
- **A5 — `denied` results are recorded in the duplicate history, so a repeat of a denied call is
  blocked without a second prompt.** This follows from the brief's rule (denial results are
  `ERROR:`-prefixed) and from [HARNESS] 10.4's existing "Do not retry the identical call". The human
  retains the ability to change their mind by starting a new turn, since the history is per-turn.
- **A6 — system-message rule 1 is left factually stale on purpose.** See Section 5.3. It errs toward
  the model expecting more friction than exists.
- **A7 — `validate_args`-invalid calls are not recorded in the history.** The guard sits after
  `validate_args`, so such entries could never be consulted.
- **A8 — the guard is positioned before the path/URL pre-approval checks**, so a repeated escape
  attempt produces the duplicate message rather than a second identical `[rejected]` line. Either
  ordering satisfies the brief; this one is chosen for output hygiene and is asserted by B8.
- **A9 — `dispatch()` gains a `history` parameter rather than reading a module-level global.** This
  contradicts the file's `WORKSPACE`/`ONESHOT` global convention ([ONESHOT] assumption 11) but is
  preferred here because the value is *per-turn mutable state*, not a process-wide constant: an
  explicit parameter makes the per-turn lifetime structurally enforced and makes B9/B10 testable
  without global setup. `dispatch` has exactly one call site, so the diff cost is one line.
- **A10 — `TRACE_KEY_CHARS = 200` and `TRACE_OUTCOME_CHARS = 160`.** Chosen so a normal URL or
  absolute path is never clipped while a pathological argument cannot flood the terminal. No CLI
  override.
- **A11 — `_trace_clip` maps every control character (`\x00`–`\x1f`, `\x7f`) to a space.** Without it
  a URL or filename containing `\r` could overwrite the visible line, or one containing `\n` could
  forge a second trace line. Applied to the outcome summary too.
- **A12 — the `NEW file` branch of `build_confirmation_body` is retained though unreachable.** It is
  the display half of the single existence check the tier gate consumes; removing it would split one
  decision into two.
- **A13 — no TOCTOU protection on the `write_file` existence check.** The value is read once for the
  gate and, on the gated path only, once more for the display. A flip between the two is not a
  security boundary — the human is about to read the frame and decide.
- **A14 — the history is unbounded in principle.** It is bounded in practice by
  `--max-rounds` × tool-calls-per-response, and duplicate-blocked calls do not append, so a
  loop cannot grow it. No cap is added.

---

## 11. Open questions

None. Every design choice is resolved above. Section 10 lists the fourteen places where the approved
design was silent and a minimal call was made; each is a fact the executor implements as written, not
a question to resolve.
