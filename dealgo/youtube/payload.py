"""The shape of what YouTube sends back.

Every response here is JSON that somebody else's service decides, so it is
`Any` inside by necessity: strict typing at the boundary means being honest
that the contents are unchecked, not pretending to know them. The name says
which values have been through no validation of ours.
"""

from __future__ import annotations

from typing import Any

# One decoded JSON object. Keys are strings; nothing about the values is known
# until the code that reads them checks.
JsonDict = dict[str, Any]
