"""Read-only canonical PortfolioSnapshot ingress for Single Brain M2."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


class SnapshotIngressError(RuntimeError):
    """The authoritative snapshot could not be read or validated."""


class PortfolioSnapshotSource(Protocol):
    """Narrow observation-only boundary; intentionally exposes one GET fact."""

    def capture_snapshot(self) -> PortfolioSnapshot: ...


class _RejectRedirects(HTTPRedirectHandler):
    """Stop redirects before urllib contacts a second location."""

    def redirect_request(self, *_args, **_kwargs):  # noqa: D401 - urllib hook
        raise SnapshotIngressError("snapshot endpoint redirect is forbidden")


class CanonicalHttpPortfolioSnapshotSource:
    """Read canonical snapshot JSON from a same-host, read-only HTTP endpoint."""

    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    CANONICAL_PATH = "/v1/simulation/portfolio-snapshot"

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float = 5.0,
        opener: Callable[..., object] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        parsed = urlsplit(str(url or "").strip())
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path != self.CANONICAL_PATH
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "M2 snapshot ingress must use the exact loopback canonical snapshot GET endpoint"
            )
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("M2 snapshot ingress timeout must be in (0, 30]")
        self._url = parsed.geturl()
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(_RejectRedirects()).open
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or monotonic
        self._last_response_received_at: datetime | None = None
        self._last_transport_elapsed_ms: float | None = None

    @property
    def last_response_received_at(self) -> datetime | None:
        """Consumer receipt time sampled only after the full HTTP response."""

        return self._last_response_received_at

    @property
    def last_transport_elapsed_ms(self) -> float | None:
        """Elapsed GET/read time only; never part of the canonical contract."""

        return self._last_transport_elapsed_ms

    def capture_snapshot(self) -> PortfolioSnapshot:
        self._last_response_received_at = None
        self._last_transport_elapsed_ms = None
        request = Request(
            self._url,
            method="GET",
            headers={"Accept": "application/json"},
        )
        started_at = self._monotonic_clock()
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                final_url = str(getattr(response, "geturl", lambda: self._url)())
                if final_url != self._url:
                    raise SnapshotIngressError("snapshot endpoint redirect is forbidden")
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise SnapshotIngressError(f"snapshot endpoint returned HTTP {status}")
                payload = response.read(self.MAX_RESPONSE_BYTES + 1)
            self._last_transport_elapsed_ms = max(
                0.0, (self._monotonic_clock() - started_at) * 1000.0
            )
            received_at = self._clock()
            if (
                not isinstance(received_at, datetime)
                or received_at.tzinfo is None
                or received_at.utcoffset() is None
            ):
                raise SnapshotIngressError(
                    "snapshot response receipt clock must be timezone-aware"
                )
            self._last_response_received_at = received_at.astimezone(timezone.utc)
        except SnapshotIngressError:
            raise
        except Exception as exc:
            raise SnapshotIngressError("authoritative snapshot ingress unavailable") from exc
        if len(payload) > self.MAX_RESPONSE_BYTES:
            raise SnapshotIngressError("authoritative snapshot response exceeds size limit")
        try:
            return PortfolioSnapshot.model_validate_json(payload)
        except Exception as exc:
            raise SnapshotIngressError("invalid canonical PortfolioSnapshot response") from exc
