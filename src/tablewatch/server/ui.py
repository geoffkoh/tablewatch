"""The web UI bundle, loaded once at startup and served from memory.

The bundle is Vite's output in `tablewatch/webapp/static/`, committed so the
server needs no Node. It is read into a map of URL path → file once, and a
request is answered by exact lookup: no filesystem path is ever built from
a request, so nothing outside the bundle can be reached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

log = logging.getLogger(__name__)

# Fixed, not the host's `mimetypes` table: with `nosniff`, a module script
# served under the wrong type is refused by the browser.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
INDEX = "index.html"
# Client pages whose one segment after the prefix is an id, not a file name:
# an explicit `id:` may hold dots (`sales.orders.volume`, `report.txt`).
# Keep in step with `frontend/src/lib/route.ts`.
PAGE_PREFIXES = ("checks",)


@dataclass(frozen=True)
class Asset:
    body: bytes
    content_type: str


@dataclass(frozen=True)
class Bundle:
    """The UI's files by URL path (`index.html`, `assets/app-3f2a.js`, ...)."""

    assets: dict[str, Asset]

    @property
    def index(self) -> Asset:
        return self.assets[INDEX]

    def lookup(self, path: str) -> Asset | None:
        """The asset for a request path (without its leading "/"), or None.

        Exact files first. Any other path is a page of the app and gets
        `index.html` — unless it names a file (its last segment has an
        extension, or it ends in "/" after one), because a script tag handed
        HTML fails confusingly. `<prefix>/<id>` under `PAGE_PREFIXES` is
        always a page, whatever its id looks like.
        """
        if path == "":
            return self.index
        if asset := self.assets.get(path):
            return asset
        segments = [s for s in path.split("/") if s]
        if len(segments) == 2 and segments[0] in PAGE_PREFIXES:
            return self.index
        if segments and "." in segments[-1]:
            return None
        return self.index


def is_api_path(path: str) -> bool:
    """Whether a request path (without its leading "/") belongs to the API."""
    first = next((s for s in path.split("/") if s), "")
    return first == "api"


def load_bundle(directory: Path | None = None) -> Bundle | None:
    """The installed bundle, or None when this installation has no UI."""
    if directory is None:
        root = files("tablewatch").joinpath("webapp", "static")
        if not isinstance(root, Path):  # e.g. a zip import: no real files
            return None
        directory = root
    directory = directory.resolve()
    if not (directory / INDEX).is_file():
        return None
    assets: dict[str, Asset] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if (
            path.is_symlink()
            or not path.is_file()
            or any(part.startswith(".") for part in relative.parts)
            or path.suffix not in CONTENT_TYPES
            or not path.resolve().is_relative_to(directory)
        ):
            continue
        assets[relative.as_posix()] = Asset(
            path.read_bytes(), CONTENT_TYPES[path.suffix]
        )
    return Bundle(assets)
