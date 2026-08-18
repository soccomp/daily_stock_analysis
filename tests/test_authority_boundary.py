"""Gate 3: authority-boundary markers lock the canonical path.

The canonical path is DSA proposal -> Athena Investment Authority -> Athena
execution.  The M3 direct-execution bypass must stay marked NON_CANONICAL so no
future operator mistakes it for the production main line.
"""

import src.investment.m3 as m3_module


def test_m3_path_is_marked_non_canonical():
    assert m3_module.PATH_CLASSIFICATION == "NON_CANONICAL_LEGACY_EXPERIMENTAL"


def test_m3_module_docstring_states_non_canonical():
    doc = (m3_module.__doc__ or "").upper()
    assert "NON_CANONICAL" in doc
