from __future__ import annotations

import pytest

from dealgo.youtube.api import parse_channel_reference, parse_duration

CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (CHANNEL_ID, ("id", CHANNEL_ID)),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}", ("id", CHANNEL_ID)),
        (f"youtube.com/channel/{CHANNEL_ID}/videos", ("id", CHANNEL_ID)),
        ("@GoogleDevelopers", ("handle", "@GoogleDevelopers")),
        ("https://www.youtube.com/@GoogleDevelopers", ("handle", "@GoogleDevelopers")),
        ("https://www.youtube.com/user/GoogleDevelopers", ("username", "GoogleDevelopers")),
        ("https://www.youtube.com/c/GoogleDevelopers", ("search", "GoogleDevelopers")),
        ("Google Developers", ("search", "Google Developers")),
    ],
)
def test_parse_channel_reference(raw, expected):
    assert parse_channel_reference(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
def test_parse_channel_reference_rejects_non_channels(raw):
    with pytest.raises(ValueError):
        parse_channel_reference(raw)


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("PT4M13S", 253), ("PT1H2M3S", 3723), ("PT45S", 45), ("P1DT2H", 93600), ("PT0S", 0), (None, None), ("junk", None)],
)
def test_parse_duration(raw, seconds):
    assert parse_duration(raw) == seconds
