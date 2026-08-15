"""No-retry loopback handoff for canonical InvestmentProposal objects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.investment.contracts.investment_proposal import InvestmentProposal


class ProposalTransportUncertain(RuntimeError):
    """The proposal response is unavailable or untrustworthy; callers must not retry blindly."""


@dataclass(frozen=True)
class AthenaProposalAcknowledgement:
    """Durable handoff ACK, separate from Athena's execution lifecycle state."""

    proposal_id: str
    proposal_hash: str
    acknowledgement_id: str
    acknowledgement_state: str
    lifecycle_state: str
    deduplicated: bool

    LIFECYCLE_STATES = frozenset({
        "ACCEPTED",
        "NO_ACTION",
        "ALLOCATED",
        "BLOCKED",
        "BLOCKED_PRE_SUBMISSION",
        "PENDING_RECONCILIATION",
        "REJECTED",
        "FILLED",
    })

    @classmethod
    def from_payload(
        cls,
        payload: object,
        proposal: InvestmentProposal,
    ) -> "AthenaProposalAcknowledgement":
        if not isinstance(payload, dict):
            raise ProposalTransportUncertain("proposal acknowledgement must be an object")
        if (
            payload.get("status") != "ACCEPTED"
            or payload.get("acknowledgement_state") != "ACCEPTED"
            or payload.get("proposal_id") != proposal.proposal_id
            or payload.get("proposal_hash") != proposal.content_hash
            or payload.get("lifecycle_state") not in cls.LIFECYCLE_STATES
            or not isinstance(payload.get("acknowledgement_id"), str)
            or not payload["acknowledgement_id"].strip()
            or not isinstance(payload.get("deduplicated"), bool)
        ):
            raise ProposalTransportUncertain("proposal acknowledgement contract mismatch")
        return cls(
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.content_hash,
            acknowledgement_id=payload["acknowledgement_id"],
            acknowledgement_state="ACCEPTED",
            lifecycle_state=payload["lifecycle_state"],
            deduplicated=payload["deduplicated"],
        )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ProposalTransportUncertain("proposal endpoint redirect is forbidden")


class CanonicalHttpInvestmentProposalPublisher:
    PATH = "/api/investment-proposals"
    MAX_RESPONSE_BYTES = 1024 * 1024

    def __init__(self, *, url: str, timeout_seconds: float = 5.0, opener=None) -> None:
        parsed = urlsplit(str(url or "").strip())
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path != self.PATH
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("proposal handoff must use the exact loopback Athena endpoint")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("proposal handoff timeout must be in (0, 30]")
        self._url = parsed.geturl()
        self._timeout = float(timeout_seconds)
        self._opener = opener or build_opener(_RejectRedirects()).open

    def publish(self, proposal: InvestmentProposal) -> AthenaProposalAcknowledgement:
        if not isinstance(proposal, InvestmentProposal):
            raise TypeError("canonical InvestmentProposal is required")
        request = Request(
            self._url,
            data=proposal.canonical_json().encode("utf-8"),
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            raw = self._read(request, expected_url=self._url)
            payload = self._decode(raw)
            return AthenaProposalAcknowledgement.from_payload(payload, proposal)
        except ProposalTransportUncertain:
            # The POST may already be durably accepted. Resolve that uncertainty
            # with one read-only lookup; never repeat the POST.
            return self._lookup(proposal)

    def _lookup(
        self,
        proposal: InvestmentProposal,
    ) -> AthenaProposalAcknowledgement:
        parsed = urlsplit(self._url)
        path = f"/api/investment-proposals/{quote(proposal.proposal_id, safe='')}/ack"
        url = f"{parsed.scheme}://{parsed.netloc}{path}"
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            payload = self._decode(self._read(request, expected_url=url))
            return AthenaProposalAcknowledgement.from_payload(payload, proposal)
        except ProposalTransportUncertain as lookup_error:
            raise ProposalTransportUncertain(
                "proposal acknowledgement is unavailable; do not retry blindly"
            ) from lookup_error

    def _read(self, request: Request, *, expected_url: str) -> bytes:
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if (
                    str(response.geturl()) != expected_url
                    or int(getattr(response, "status", 200)) != 200
                ):
                    raise ProposalTransportUncertain(
                        "proposal endpoint response is not authoritative"
                    )
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        except ProposalTransportUncertain:
            raise
        except Exception as exc:
            raise ProposalTransportUncertain("proposal transport is uncertain") from exc
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise ProposalTransportUncertain("proposal acknowledgement exceeds size limit")
        return raw

    @staticmethod
    def _decode(raw: bytes) -> object:
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProposalTransportUncertain("proposal acknowledgement is invalid JSON") from exc
