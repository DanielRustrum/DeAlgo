"""Every outgoing request checks certificates — against the public
authorities, and those in PAMPHLETS_EXTRA_CA as well when it names a file."""

from __future__ import annotations

import ssl

import certifi
import pytest

from pamphlets import outgoing


def test_the_public_authorities_are_trusted_and_nothing_is_switched_off(monkeypatch):
    monkeypatch.delenv("PAMPHLETS_EXTRA_CA", raising=False)
    assert outgoing._trusting("") is True
    with outgoing.client() as http:
        assert http is not None


def test_an_extra_authority_is_trusted_beside_the_public_ones(monkeypatch):
    # Any PEM bundle stands in for a home network's own authority.
    monkeypatch.setenv("PAMPHLETS_EXTRA_CA", certifi.where())
    context = outgoing._trusting(certifi.where())
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    with outgoing.client() as http:
        assert http is not None


def test_an_extra_authority_that_is_not_there_says_so(tmp_path):
    with pytest.raises(OSError):
        outgoing._trusting(str(tmp_path / "missing.pem"))
