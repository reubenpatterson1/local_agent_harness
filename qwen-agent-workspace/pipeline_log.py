"""Append one record per pipeline-tool run to <story_dir>/iterate-story.log.

Same record layout as bin/iterate-story's _log_run, labelled "stage: <tool>" instead of
"round N: <tool>". Skipped when STORY_PIPELINE_LOGGED is set (bin/iterate-story sets it
for its children, whose output it already logs) or when the story directory does not
exist when the run ends (a tool that creates it, such as ltx-movie on a new story id, is
logged). Only output written through sys.stdout/sys.stderr is captured; subprocesses that
inherit the file descriptors bypass it.
"""

import datetime
import os
import sys
import traceback

ENV_FLAG = "STORY_PIPELINE_LOGGED"
LOG_FILE_NAME = "iterate-story.log"


def argv_value(argv, flag):
    """The value of flag in argv ("--flag v" or "--flag=v"); the last occurrence wins.
    None when absent."""
    value = None
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith(flag + "="):
            value = arg[len(flag) + 1:]
    return value


def collapse_cr(text):
    """Keep only the text after the last carriage return on each line, so progress bars
    are logged in their final state."""
    return "\n".join(line.rstrip("\r").rsplit("\r", 1)[-1] for line in text.split("\n"))


class _Tee(object):
    def __init__(self, stream, buf):
        self._stream = stream
        self._buf = buf

    def write(self, s):
        self._buf.append(s)
        return self._stream.write(s)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def format_record(label, cmd, exit_code, output, now):
    parts = ["=== stage: %s === %s\n" % (label, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
             "cmd: %r\n" % (cmd,),
             "exit: %d\n" % exit_code,
             "--- output ---\n",
             output]
    if output and not output.endswith("\n"):
        parts.append("\n")
    parts.append("--- end ---\n\n")
    return "".join(parts)


def _exit_code(code):
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _append(story_dir, record):
    path = os.path.join(story_dir, LOG_FILE_NAME)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(record)
    except OSError as e:
        sys.stderr.write("warning: could not append to %s: %s\n" % (path, e))


def run_logged(label, story_dir, main_fn, argv):
    """Call main_fn() and return its result, appending a record of the run to
    story_dir/iterate-story.log. Exceptions (SystemExit included) are re-raised
    unchanged after the record is written; a log-write failure only warns."""
    if os.environ.get(ENV_FLAG) or story_dir is None:
        return main_fn()
    buf = []
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Tee(old_out, buf), _Tee(old_err, buf)
    exit_code = 1
    try:
        rc = main_fn()
        exit_code = _exit_code(rc)
        return rc
    except SystemExit as e:
        exit_code = _exit_code(e.code)
        if e.code is not None and not isinstance(e.code, int):
            buf.append("%s\n" % (e.code,))
        raise
    except BaseException:
        buf.append(traceback.format_exc())
        exit_code = 1
        raise
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        if os.path.isdir(story_dir):
            _append(story_dir, format_record(
                label, list(argv), exit_code, collapse_cr("".join(buf)),
                datetime.datetime.now(datetime.timezone.utc)))
