"""Writing back to the service a feed came from, without knowing which it is.

De-Algo used to hold a YouTube client: four hundred lines that knew every
endpoint, every field name in every answer, and what each call costs against
the day's allowance. None of that was De-Algo's to know. It is YouTube's, and
it lives in the YouTube plugin now.

What is left here is the shape of the conversation. Something can be looked
up, a playlist can be read, added to and removed from; whichever service is
behind it answers in the same words. The plugin builds the request and reads
the answer; the host signs it, charges it, and turns what comes back into
these.

Only a plugin whose source kind is `playlistable` is asked. That is the same
rule that stops a Reddit post being pushed into a YouTube playlist, said from
the other end.
"""

from __future__ import annotations

from .answers import ChannelInfo, PlaylistInfo, PlaylistItem, PublishError, VideoDetails
from .client import Publisher, cost_of

__all__ = [
    "ChannelInfo",
    "PlaylistInfo",
    "PlaylistItem",
    "PublishError",
    "Publisher",
    "VideoDetails",
    "cost_of",
]
