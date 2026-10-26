"""Pinned GPA tag/identifier registry. Unknown GUIDs remain valid extensions.

Generated constants use the upstream names with the trailing ``Tag`` removed and
converted to UPPER_SNAKE_CASE. The registry includes source provenance and SHA-256.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from uuid import UUID

from ._tag_constants import *  # noqa: F403


@dataclass(frozen=True)
class TagInfo:
    id: UUID
    name: str
    standard_name: str
    element_type: str
    physical_type: str
    required: bool
    description: str


_metadata: dict[str, Any] = json.loads(
    files("pqdif").joinpath("data/registry.json").read_text("utf-8")
)
PROVENANCE: dict[str, str] = _metadata["provenance"]
IDENTIFIERS: dict[str, dict[str, dict[str, str]]] = _metadata["identifiers"]
BY_NAME: dict[str, TagInfo] = {
    row["name"]: TagInfo(
        UUID(row["id"]),
        row["name"],
        row["standardName"],
        row["elementType"],
        row["physicalType"],
        row["required"] == "True",
        row["description"],
    )
    for row in _metadata["tags"]
}
BY_ID: dict[UUID, TagInfo] = {tag.id: tag for tag in BY_NAME.values()}
