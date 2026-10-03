"""Absolute paths out of text that leaves this machine.

Error messages from a database driver name files: `Cannot open database
"/home/ana/projects/x/missing.duckdb"`. Served over HTTP, that tells a
reader the server's user name and layout. Inside the project the path is
shown relative to it; anywhere else only its last segment remains.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

OUTSIDE = "<outside the project>"

# An absolute path: POSIX `/a/b`, `~` or `~user/…`, Windows `C:\` or `C:/`,
# UNC `\\host\share`, or a `file://` URL. It runs to whitespace or a quote.
_ABSOLUTE = re.compile(
    r"""(?x)
    (?:
        file://[^\s"'`]+                      # file:///a/b
      |
        (?<![\w.:/])/[^\s"'`/][^\s"'`]*     # /a/b  (not part of a URL or a/b)
      | ~[\w.-]*/[^\s"'`]*                   # ~/a, ~user/a
      | \b[A-Za-z]:[\\/][^\s"'`]*            # C:\a, C:/a
      | \\\\[^\s"'`\\]+\\[^\s"'`]*           # \\host\share\a
    )
    """
)


def root_forms(root: Path) -> list[str]:
    """The spellings of `root` a message can contain, longest first."""
    given = {str(root), str(root.resolve())}
    # macOS reports /var/… paths as /private/var/… and the reverse.
    private = {f.removeprefix("/private") for f in given if f.startswith("/private/")}
    public = {
        "/private" + f for f in given if f.startswith(("/var/", "/tmp/", "/etc/"))
    }
    forms = given | private | public
    return sorted(forms, key=len, reverse=True)


def scrub_paths(text: str, roots: Iterable[str]) -> str:
    """`text` with project paths made relative and every other absolute path cut.

    `roots` are the project root's spellings (`root_forms`). The result names
    no directory outside the project.
    """
    for root in roots:
        prefix = root.rstrip("/\\")
        if not prefix:
            continue
        text = text.replace(prefix + "/", "").replace(prefix + os.sep, "")
    return _ABSOLUTE.sub(_outside, text)


def _outside(match: re.Match[str]) -> str:
    path = match.group(0).removeprefix("file://").rstrip("/\\")
    last = re.split(r"[\\/]", path)[-1]
    return f"{OUTSIDE}/{last}" if last and last != "~" else OUTSIDE
