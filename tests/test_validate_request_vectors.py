"""Before/after correctness baseline for query_api.validate_request.

Loads tests/fixtures/validate_request_vectors.json and asserts the current
hand-written validator's behavior matches it exactly. The fixture is
tool-agnostic by design (plain request/outcome pairs, no reference to
validate_request's internals) so it can also validate any future
replacement -- pydantic, jsonschema, or otherwise -- without being rewritten
first. See CoPlan.md 13.4.2 for the capability gaps (canonical form,
related-field comparison, action-dependent filters) this fixture specifically
covers.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from codess.query_api import QueryContractError, validate_request

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VECTORS = json.loads(
    (FIXTURES / "validate_request_vectors.json").read_text(encoding="utf-8")
)


def _build_request(overrides: dict) -> dict:
    request = copy.deepcopy(VECTORS["base_valid_request"])
    request.update(copy.deepcopy(overrides))
    filters = request.get("filters")
    if isinstance(filters, dict) and filters.get("text") == "x_REPEAT_600":
        filters["text"] = "x" * 600
    return request


@pytest.mark.parametrize(
    "vector", VECTORS["vectors"], ids=[v["name"] for v in VECTORS["vectors"]]
)
def test_validate_request_vector(vector):
    request = _build_request(vector["request"])
    if vector["outcome"] == "accept":
        validate_request(request)  # must not raise
        return
    with pytest.raises(QueryContractError) as excinfo:
        validate_request(request)
    assert vector["message_contains"] in str(excinfo.value)


def test_vectors_cover_every_capability_gap():
    """Guard against silently losing coverage of the three JSON-Schema gaps."""
    capabilities = {
        v.get("capability") for v in VECTORS["vectors"] if v.get("capability")
    }
    assert capabilities == {"canonical_form", "related_fields", "action_dependent"}


def test_vectors_file_is_self_consistent():
    names = [v["name"] for v in VECTORS["vectors"]]
    assert len(names) == len(set(names)), "duplicate vector name"
    for vector in VECTORS["vectors"]:
        assert vector["outcome"] in ("accept", "reject")
        if vector["outcome"] == "reject":
            assert "message_contains" in vector
