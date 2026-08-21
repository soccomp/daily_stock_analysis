"""Immutable provenance for the object that caused DSA research."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, model_validator
from typing_extensions import Self

from .base import CanonicalDecimal, FrozenValue


class CandidateProvenance(FrozenValue):
    """The durable source lineage attached to research and proposal artifacts."""

    candidate_source: Literal[
        "SCREENING", "HOLDING", "MANUAL_SYMBOL_OVERRIDE", "EXTERNAL_EVENT"
    ]
    screening_run_id: StrictStr | None = Field(default=None, min_length=1, max_length=160)
    screening_strategy: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    screening_rank: StrictInt | None = Field(default=None, ge=1)
    screening_score: CanonicalDecimal | None = None
    screening_selected_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _source_fields_are_consistent(self) -> Self:
        screening_fields = (
            self.screening_run_id,
            self.screening_strategy,
            self.screening_rank,
            self.screening_score,
            self.screening_selected_at,
        )
        if self.candidate_source == "SCREENING":
            if any(value is None for value in screening_fields):
                raise ValueError("SCREENING provenance requires complete screening lineage")
        elif any(value is not None for value in screening_fields):
            raise ValueError("non-SCREENING provenance cannot carry screening lineage")
        return self
