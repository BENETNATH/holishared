"""Erreurs de formulaire par champ (B018).

Les gabarits interrogent le champ (``errors.has('title')``), jamais le texte du
message. L'objet reste itérable comme une liste de messages (``{% for e in errors %}``).
"""

from __future__ import annotations

from collections.abc import Iterator

from flask import flash


class FormErrors:
    GLOBAL = "__all__"

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def add(self, field: str, message: str) -> None:
        if not field:
            raise ValueError("field must not be empty")
        self._items.append((field, message))

    def add_global(self, message: str) -> None:
        self.add(self.GLOBAL, message)

    def for_field(self, field: str) -> list[str]:
        return [m for f, m in self._items if f == field]

    def text(self, field: str) -> str | None:
        return " ".join(self.for_field(field)) or None

    def has(self, field: str) -> bool:
        return any(f == field for f, _ in self._items)

    @property
    def global_errors(self) -> list[str]:
        return self.for_field(self.GLOBAL)

    def remaining(self, *rendered: str) -> list[str]:
        """Messages des champs non rendus en ligne (erreurs globales incluses)."""
        return [m for f, m in self._items if f not in rendered]

    def as_dict(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f, m in self._items:
            out.setdefault(f, []).append(m)
        return out

    def flash_all(self, category: str = "danger") -> None:
        for _, m in self._items:
            flash(m, category)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[str]:
        return (m for _, m in self._items)

    def __contains__(self, message: object) -> bool:
        return any(m == message for _, m in self._items)
