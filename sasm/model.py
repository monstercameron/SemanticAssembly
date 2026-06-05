"""Core data model: a program is a set of named entities, each a bag of facts.

A fact is a row:  <subject> <predicate> <arg>...
The special predicate `is` sets the entity's type.

Everything downstream (validation, emission) reads this model. The model itself
carries no RISC-V knowledge -- that lives in isa.py.
"""

from __future__ import annotations


class Entity:
    def __init__(self, name: str):
        self.name = name
        self.type: str | None = None
        # predicate -> list of arg-lists (predicates may repeat, e.g. multiple `effect`)
        self.facts: dict[str, list[list[str]]] = {}
        self.order: int = 0          # source order, used for sequencing
        self.lineno: int = 0

    def add(self, predicate: str, args: list[str]) -> None:
        self.facts.setdefault(predicate, []).append(args)

    def all(self, predicate: str) -> list[list[str]]:
        """Every row for this predicate (each row is a list of args)."""
        return self.facts.get(predicate, [])

    def values(self, predicate: str) -> list[str]:
        """First token of every row for this predicate -- the common case."""
        return [row[0] for row in self.facts.get(predicate, []) if row]

    def row(self, predicate: str) -> list[str] | None:
        rows = self.facts.get(predicate)
        return rows[0] if rows else None

    def scalar(self, predicate: str, default: str | None = None) -> str | None:
        row = self.row(predicate)
        if not row:
            return default
        return row[0]

    def has(self, predicate: str) -> bool:
        return predicate in self.facts

    def __repr__(self) -> str:
        return f"<{self.name}:{self.type}>"


class Program:
    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.order: list[str] = []

    def ensure(self, name: str) -> Entity:
        e = self.entities.get(name)
        if e is None:
            e = Entity(name)
            e.order = len(self.order)
            self.entities[name] = e
            self.order.append(name)
        return e

    def get(self, name: str) -> Entity | None:
        return self.entities.get(name)

    def of_type(self, t: str) -> list[Entity]:
        return [self.entities[n] for n in self.order if self.entities[n].type == t]

    def members_of(self, container: str, t: str | None = None) -> list[Entity]:
        """Entities whose `in` points at `container`, in source order."""
        out = []
        for n in self.order:
            e = self.entities[n]
            if e.scalar("in") == container and (t is None or e.type == t):
                out.append(e)
        return out
