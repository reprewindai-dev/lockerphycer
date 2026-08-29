from __future__ import annotations

import pytest

from core.execution_cells.predator_contract import (
    CANONICAL_IDS,
    CASE_BY_ID,
    PredatorID,
    assert_canonical_result_ids,
)


def test_canonical_matrix_is_exactly_a00_through_a19() -> None:
    assert CANONICAL_IDS == tuple(f"A{i:02d}" for i in range(20))


def test_high_risk_ids_cannot_drift_semantically() -> None:
    assert CASE_BY_ID[PredatorID.A05].property_name == "tenant/workspace substitution"
    assert CASE_BY_ID[PredatorID.A06].property_name == "audience/runtime-instance substitution"
    assert CASE_BY_ID[PredatorID.A07].property_name == "effect/image/request-digest mutation"
    assert CASE_BY_ID[PredatorID.A08].property_name == "nonce/lease replay"
    assert CASE_BY_ID[PredatorID.A09].property_name == "target-state TOCTOU"
    assert CASE_BY_ID[PredatorID.A10].property_name == "credential extraction"
    assert CASE_BY_ID[PredatorID.A15].property_name == "kill / post-dispatch ambiguity"
    assert CASE_BY_ID[PredatorID.A17].property_name == "exact PGL consequence binding"
    assert CASE_BY_ID[PredatorID.A19].property_name == "fan-in / synthesis creates no authority"


def test_unknown_or_duplicate_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="non-canonical"):
        assert_canonical_result_ids(["A00", "A20"])
    with pytest.raises(ValueError, match="duplicate"):
        assert_canonical_result_ids(["A00", "A00"])


def test_complete_profile_cannot_be_claimed_from_subset() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        assert_canonical_result_ids(["A00", "A01", "A17"], require_complete=True)
    assert assert_canonical_result_ids(CANONICAL_IDS, require_complete=True) == CANONICAL_IDS
