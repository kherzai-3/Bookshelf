"""Shared data model for a book's per-chapter plain text, used by every loader."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chapter:
    index: int
    title: str | None
    text: str
