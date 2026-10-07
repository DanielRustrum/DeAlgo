"""`pamphlets export`: a JSON backup of the setup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..db import init_db, session_scope
from ..services import backup as backup_service


def cmd_export(args: argparse.Namespace) -> int:
    """The same JSON the Settings page downloads, for scripted backups."""
    init_db()
    with session_scope() as session:
        data = backup_service.build_export(session)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        counts = data["counts"]
        print(f"wrote {args.output}: {counts['feeds']} feed(s), {counts['channels']} channel(s)")
    else:
        print(text)
    return 0
