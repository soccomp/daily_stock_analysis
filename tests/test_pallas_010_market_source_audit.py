from tools.pallas010_market_source_audit import _classify_failure


def test_market_source_audit_classifies_provider_failure_layers():
    assert _classify_failure("Tushare token 已过期") == "AUTH_OR_PERMISSION"
    assert _classify_failure("RemoteDisconnected from eastmoney") == "TRANSPORT"
    assert _classify_failure("No module named efinance") == "NOT_INSTALLED"
    assert _classify_failure("response has no required column") == "SCHEMA"
