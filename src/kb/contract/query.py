"""Pydantic schemas for the Contract's query/search operation.

Per kb-contract/spec.md's Query and Search requirement, the Query request and hit shapes
are defined here as part of the typed, versioned Contract.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel


class QueryFilter(BaseModel):
    field: str
    op: Literal["=", "!=", ">=", "<=", ">", "<", "contains"]
    value: Any


class QueryRequest(BaseModel):
    text: str | None = None
    filters: list[QueryFilter] = []
    collections: list[str] = []
    related_to: str | None = None
    relationship: str | None = None
    limit: int | None = None


class QueryHit(BaseModel):
    ref: str
    collection: str
    snippet: str
    matched_in: str
    related_refs: list[str] = []


class QueryResult(BaseModel):
    hits: list[QueryHit]
    total: int
    truncated: bool
