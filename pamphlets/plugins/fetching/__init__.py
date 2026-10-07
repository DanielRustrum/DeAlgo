"""Taking a plugin from a git repository.

Over HTTPS, as the archive a git host publishes for a branch or a tag —
GitHub, GitLab, Codeberg and anything else running Gitea all serve one at a
predictable address, and a direct link to a ``.tar.gz`` works too.

Not by running git, and not only because there is no git in the image. A
clone runs hooks, reads config out of the repository, and can be pointed at
a transport that does considerably more than fetch; an archive is a file
somebody else's server hands over, and nothing in it is ever executed here.
What comes out is read exactly as an uploaded file is: judged first, put to
somebody for consent, and only then written to disk.

Everything about the archive is treated as hostile, because it is somebody
else's: how big it says it is, how big it turns out to be, how many files
are in it, what they are called and where they say they want to go.
"""

from __future__ import annotations

from .addresses import USUAL_REFS, archives, repository_name
from .download import fetch

__all__ = [
    "archives",
    "fetch",
    "repository_name",
    "USUAL_REFS",
]
