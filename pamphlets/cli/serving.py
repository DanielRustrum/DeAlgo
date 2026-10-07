"""`pamphlets serve`: run the web app."""

from __future__ import annotations

import argparse

from ..config import CONFIG


def cmd_serve(args: argparse.Namespace) -> int:
    """`pamphlets serve`: run the web app under uvicorn until stopped."""
    import uvicorn

    uvicorn.run(
        "pamphlets.web.app:app",
        host=args.host,
        port=args.port,
        log_level=CONFIG.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0
