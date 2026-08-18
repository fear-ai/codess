"""Before/after correctness baseline for query_api.validate_request.

Loads tests/fixtures/validate_request_vectors.json and asserts the current
hand-written validator's behavior matches it exactly. The fixture is
tool-agnostic by design (plain request/outcome pairs, no reference to
validate_request's internals) so it can also validate any future
replacement -- pydantic, jsonschema, or otherwise -- without being rewritten
first. It covers three capability gaps a JSON Schema cannot express: canonical
form, related-field comparison, and action-dependent filters.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from codess.query_api import QueryContractError, validate_request

# Every `raise` in `validate_request`, each reachable from a vector below.
# Recorded rather than derived: a derived count cannot tell a path that gained
# a vector from one that never had one.
REJECTION_PATHS = 36

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


def test_every_rejection_path_has_a_vector():
    """No `raise` in `validate_request` may be unreachable from the fixture.

    The vectors are only a contract if they are complete. A validator gains a
    check more easily than a fixture gains a vector, so without this the file
    decays into a sample: the paths it covers stay covered and every new one
    arrives untested, which is indistinguishable from full coverage when
    reading a passing run.

    Asserts against a recorded count rather than a `>=` comparison. Several
    paths carry more than one vector -- a bound has a low and a high case --
    so a comparison would leave slack equal to that surplus and only fail once
    it was used up, which is the ninth new path rather than the first.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "src" / "codess" / "query_api.py"
    ).read_text(encoding="utf-8")
    validator = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "validate_request"
    )
    raises = [n for n in ast.walk(validator) if isinstance(n, ast.Raise)]
    assert len(raises) == REJECTION_PATHS, (
        f"validate_request has {len(raises)} rejection paths, recorded as "
        f"{REJECTION_PATHS}. Add a vector covering the new path and update the "
        "count, or remove the count if the path went away."
    )
