"""
Minimal .env loading for local runs.

The API service reads provider credentials from the process environment, which
is the right boundary: keys never reach the browser and never appear in a
request. But nothing was putting a local `.env` into that environment, so a
developer who filled the file in still got a service that behaved as though no
key existed - silently, because every optional capability degrades quietly by
design.

Deliberately not python-dotenv. This needs to read `KEY=value` lines and stop,
and a dependency for that is a dependency to keep current for no gain.

The real environment always wins. A value exported in the shell, injected by a
container runtime, or set by a secret manager is authoritative; the file only
fills gaps.
"""

import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def load_env_file(path: Path | str = ".env") -> List[str]:
    """
    Populate os.environ from a `.env` file, without overriding what is set.

    Returns the names of the variables it set, never the values, so this can be
    logged safely.
    """
    file = Path(path)
    if not file.is_file():
        return []

    applied: List[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()

        name, separator, value = line.partition("=")
        if not separator:
            continue

        name = name.strip()
        if not name or name in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        os.environ[name] = value
        applied.append(name)

    if applied:
        logger.info("Loaded %d variable(s) from %s: %s", len(applied), file, ", ".join(sorted(applied)))
    return applied
