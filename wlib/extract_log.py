"""The log of an `extract` run: which lines report a problem, the run's `log`
callable, and the WARNING lines written by helpers that take no log argument.

`push(log)` makes `log` the target of `warn` for the run in progress and
`pop()` ends that; without a run `warn` prints to stdout.
"""

import sys

#: the `log` of the extract run in progress (pushed by the extract driver), for
#: the few WARNING lines written by helpers that take no log argument
_RUN_LOG = []


def push(log):
    """Send `warn` lines to `log` until the matching pop()."""
    _RUN_LOG.append(log)


def pop():
    """End the run `push` started."""
    _RUN_LOG.pop()


def warn(line):
    """One WARNING line from a helper that takes no log argument: through the
    running extract's log (to stderr under --quiet), else stdout."""
    (_RUN_LOG[-1] if _RUN_LOG else print)(line)


def is_warning_line(text):
    """True for a log line of `extract` that reports a problem: one whose text
    starts with '!' (an asset or a step that failed) or that carries
    'WARNING:' (content not decoded, or not decoded completely)."""
    for ln in str(text).splitlines():
        t = ln.lstrip()
        if t.startswith("!") or "WARNING:" in t:
            return True
    return False


def extract_logger(quiet=False, out=None, err=None):
    """The `log` of an extract run: every line to stdout (`out`), as print()
    writes it; with `quiet` only the warning lines (is_warning_line), and those
    to stderr (`err`), so --quiet never hides a problem."""

    def log(*x):
        if not quiet:
            print(*x, file=out if out is not None else sys.stdout)
        elif is_warning_line(" ".join(str(v) for v in x)):
            print(*x, file=err if err is not None else sys.stderr)

    return log
