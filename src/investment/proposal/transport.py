"""No-retry loopback handoff for canonical InvestmentProposal objects."""

from __future__ import annotations

import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.investment.contracts.investment_proposal import InvestmentProposal


class ProposalTransportUncertain(RuntimeError):
    """The proposal response is unavailable or untrustworthy; callers must not retry blindly."""


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

    def publish(self, proposal: InvestmentProposal) -> dict:
        if not isinstance(proposal, InvestmentProposal):
            raise TypeError("canonical InvestmentProposal is required")
        request = Request(
            self._url,
            data=proposal.canonical_json().encode("utf-8"),
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if str(response.geturl()) != self._url or int(getattr(response, "status", 200)) != 200:
                    raise ProposalTransportUncertain("proposal endpoint response is not authoritative")
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        except ProposalTransportUncertain:
            raise
        except Exception as exc:
            raise ProposalTransportUncertain(
                "proposal acknowledgement is unavailable; do not retry blindly"
            ) from exc
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise ProposalTransportUncertain("proposal acknowledgement exceeds size limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProposalTransportUncertain("proposal acknowledgement is invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("proposal_id") != proposal.proposal_id:
            raise ProposalTransportUncertain("proposal acknowledgement lineage mismatch")
        return payload
