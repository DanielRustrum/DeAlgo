"""Why an item was set aside, in the words the Raw list shows."""

from __future__ import annotations

# Why an item a published playlist cannot hold was turned away. Named rather
# than written twice: wiring the source to a feed that *can* hold it looks for
# exactly this, so the two must not drift apart.
WRONG_KIND_OF_FEED = "not something that feed's playlist can hold"


# Why something the feed still lists was passed over on the first check. Named
# so that reaching back can find exactly what it set aside and nothing else.
TOO_OLD = "predates the backfill window"
