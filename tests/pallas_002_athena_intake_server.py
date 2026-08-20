"""Isolated Athena InvestmentAuthorityService loopback for PALLAS-002 tests."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.investment_authority.contracts import InvestmentProposalEnvelope
from src.investment_authority.service import InvestmentAuthorityService


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    port = int(sys.argv[1])
    journal_path = Path(sys.argv[2])
    result_path = Path(sys.argv[3])
    root = Path(os.environ["PALLAS_ATHENA_ROOT"])
    portfolio = json.loads(os.environ["PALLAS_ATHENA_PORTFOLIO"])
    clock_value = os.environ["PALLAS_TEST_NOW"]
    from datetime import datetime

    authority = InvestmentAuthorityService(
        clock=lambda: datetime.fromisoformat(clock_value),
        policy_path=root / "config/investment_authority_risk_policy.json",
        journal_path=journal_path,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _write(self, payload: object, *, status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write({"status": "READY", "simulation_only": True, "LIVE_TRADING": False})
                return
            prefix = "/api/investment-proposals/"
            if self.path.startswith(prefix) and self.path.endswith("/ack"):
                proposal_id = self.path[len(prefix):-4]
                acknowledgement = authority.acknowledgement(proposal_id)
                if acknowledgement is not None:
                    self._write(acknowledgement)
                    return
            self._write({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            if self.path != "/api/investment-proposals":
                self._write({"error": "not found"}, status=404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                proposal = InvestmentProposalEnvelope.from_json(self.rfile.read(length))
                result = authority.process(proposal, portfolio=portfolio, execute=False)
                result_path.write_text(
                    json.dumps(result, ensure_ascii=False, default=str, sort_keys=True),
                    encoding="utf-8",
                )
                acknowledgement = result["acknowledgement"]
                self._write({
                    "status": "ACCEPTED",
                    "acknowledgement_id": acknowledgement["acknowledgement_id"],
                    "acknowledgement_state": acknowledgement["acknowledgement_state"],
                    "proposal_id": proposal.proposal_id,
                    "proposal_hash": proposal.content_hash,
                    "lifecycle_state": result["status"],
                    "deduplicated": False,
                })
            except Exception as exc:
                self._write({"error": f"{type(exc).__name__}: {exc}"}, status=400)

    _Server(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
