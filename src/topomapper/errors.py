"""Error type and process exit codes shared by the toolbox."""

from __future__ import annotations

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2


class NetopsError(Exception):
    """Base class for expected, user-facing failures.

    The CLI turns these exceptions into a one-line message on stderr and exit
    code 1 instead of a traceback.
    """
