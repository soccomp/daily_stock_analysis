"""Single Brain M3 simulation-execution orchestration.

NON_CANONICAL / LEGACY / EXPERIMENTAL: the canonical investment path is
``DSA proposal -> Athena Investment Authority -> Athena execution``.  M3 was the
former DSA-direct-execution bypass (DSA -> trading spine).  Issue #9 retired it
as a production path: ``M2ShadowLoopService.from_config`` raises when
``single_brain_execution_mode`` is ``SIMULATION_EXECUTION`` and mandates
``PROPOSAL_HANDOFF``.  This module is retained for audit/history only and must
never be treated as the production main line.
"""

PATH_CLASSIFICATION = "NON_CANONICAL_LEGACY_EXPERIMENTAL"
