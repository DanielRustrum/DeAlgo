"""A submission to a Form leaflet, waiting in its queue."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owner_column
from .times import utcnow


class FormSubmission(Base):
    """One form, filled in and sent, waiting for an Input source to take it.

    A Form leaflet on a pamphlet and an Input source on the canvas agree on a
    queue by name, the way a Deposit and a Withdraw box agree on a repository
    (services/graph/forms.py). What is sent waits here until the Input source
    is next polled, which takes it — once — and sends it down its paths as
    an item. It is kept afterwards, so the source's data still lists it.
    """

    __tablename__ = "form_submission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: The queue it went into: the name the form and the source share.
    queue: Mapped[str] = mapped_column(String(80), index=True)
    #: The Form leaflet it was sent from.
    form_pk: Mapped[Optional[int]] = mapped_column(Integer)
    #: What was filled in, by field name, as JSON.
    fields: Mapped[str] = mapped_column(Text, default="{}")
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    #: When an Input source took it. None while it waits.
    taken_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
