"""What the admin decided about one plugin."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owned_unique, owner_column
from .times import utcnow


class PluginState(Base):
    """Whether a plugin is switched on. One row per plugin that has ever
    been switched off.

    No owner: a plugin is code in this process, and it is either loaded or it
    is not. Pausing one per account would mean the same file both running and
    not running, which is not a thing a process can do — and it is why this
    lives under Admin rather than in Settings.

    Only the switch is stored. Everything else about a plugin — what it is
    called, what it offers, whether it loads — is read from the file, because
    the file is the truth and a second copy could only disagree with it.
    """

    __tablename__ = "plugin_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The name of the folder it lives in, which is what the registry calls it.
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: The permissions a person granted it, as a JSON list of names. Stored
    #: rather than inferred, because a grant is a decision somebody made and
    #: a plugin editing its own manifest must not be able to widen it.
    granted: Mapped[Optional[str]] = mapped_column(Text)
    #: The repository it was fetched from, and which branch or tag. Here
    #: rather than in the folder because it is a record of what this install
    #: did, not part of the plugin: a plugin that could write its own origin
    #: could point an update at somewhere else.
    origin: Mapped[Optional[str]] = mapped_column(Text)
    origin_ref: Mapped[Optional[str]] = mapped_column(String(120))
    fetched_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class PluginAppSetting(Base):
    """One of a plugin's install-wide settings, as the admin left it.

    No owner: these are the admin's, for everyone, and set under Admin →
    Plugins. Kept apart from the per-account ones rather than told apart by a
    NULL owner, which already means "the implicit owner" everywhere else.
    """

    __tablename__ = "plugin_app_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: `<plugin id>:<setting name>`: one key, so it can be unique on its own.
    key: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PluginUserSetting(Base):
    """One of a plugin's settings, as one account left it for itself."""

    __tablename__ = "plugin_user_setting"
    __table_args__ = (owned_unique("plugin_user_setting", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: `<plugin id>:<setting name>`, unique per account.
    key: Mapped[str] = mapped_column(String(140))
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
