# Clean start and stop for every pipeline phase

Date: 2026-10-21. Status: built.

## 1. Problem

Every GPU phase (character create's Z-Image or Qwen-Image-Edit child, character and action
training, movie renders) stops the story server for memory and runs its model in a worker
process in its own session. Only Ctrl-C cleaned up:

- **kill / movie-ui Cancel** (SIGTERM) ended bin/character before its `finally` ran: the image
  worker kept running (holding ~54 GB) and the story server stayed down.
- **The restarted server could be killed with the job.** The train wrappers and the create's
  cleanup ran `bin/story-server mlx-vision`, which `nohup ... &`s the server inside the caller's
  process group; a movie-ui Cancel signals every process group of the job and SIGKILLs them after
  15 s, taking a just-restarted server down too. A blocking restart (up to 840 s) also outlives
  the 15 s grace.
- **An orphaned worker** (its parent SIGKILLed) ran to the end of its batch.
- **movie-ui started from a non-login shell** had no Homebrew PATH, so render jobs failed with
  "ffmpeg not found".

## 2. Decisions

S1. `bin/story-server-restore [MODE] [--wait]` starts `bin/story-server MODE` (default
    mlx-vision) with `start_new_session`, so no job's group signal reaches it. Without --wait it
    returns at once. A no-op when MODE is already serving or a start is in progress. Every
    "bring the VLM back" path uses it.
S2. bin/character and bin/action map SIGTERM and SIGHUP to KeyboardInterrupt, so a kill, a Cancel
    and a closed terminal take the Ctrl-C path: run_logged kills the worker's group and the
    create's `finally` restores the story server.
S3. On an interrupt the create's `finally` restores the story server detached (S1, no wait), so
    the job exits well inside the Cancel grace; on success and on ordinary errors it restores and
    waits as before.
S4. The train wrappers (character-train-vlm, action-train-vlm) restore through S1: `--wait` on a
    normal exit, detached on a signal.
S5. The zimage and qwenedit workers exit (status 3) within 2 s of their parent dying.
S6. `bin/pipeline-stop [--grace S] [--no-restore] [--dry-run]` stops everything: SIGINT to every
    pipeline job (bin/character/bin/action create|train, the train wrappers, bin/ltx-movie,
    bin/iterate-story) and up to --grace (180 s) for their cleanup; then SIGTERM to every job,
    worker and descendant still running, SIGKILL after 10 s; then story-server-restore --wait; then
    a summary (left processes, story server state, available memory). It never signals the story
    server or movie-ui.
S7. `bin/movie-ui-start` starts movie-ui detached with the login shell's PATH plus
    /opt/homebrew/bin, logs to ~/.local/share/qwen-agent/movie-ui/server.log and prints the URL
    (reprints it when already running); `bin/movie-ui-stop` stops the server (jobs keep running,
    as with Ctrl-C).
S8. busy_process (the render/training guard) also matches the qwenedit worker.

## 3. Tests

tests/test_clean_stop.py CS1-CS7 (classification, descendants, the restore's own session, no-op
and detached start); tests/test_character_tool.py K21 (an interrupt restores detached) and
tests/test_character_dataset.py D17 (qwenedit is busy), D47 (the parent watchdog).
