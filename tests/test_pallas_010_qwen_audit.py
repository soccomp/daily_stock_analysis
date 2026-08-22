from tools.pallas010_qwen_audit import _profiles, _validate_content


def test_qwen_audit_profiles_use_real_pallas_parameters_and_controls():
    profiles = {item["name"]: item for item in _profiles(2)}
    assert profiles["market_review"]["max_tokens"] == 8192
    assert profiles["market_review"]["temperature"] == 0.7
    assert profiles["screening_json"]["max_tokens"] == 2048
    assert profiles["screening_json"]["response_format"] == {"type": "json_object"}
    assert profiles["non_thinking_comparison"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert profiles["thinking_comparison"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert profiles["research_bundle"]["validator"] == "research_bundle"


def test_qwen_audit_requires_strict_json_instead_of_brace_detection():
    assert _validate_content('{"status":"ok","summary":"bounded","risk_flags":[]} ', "comparison")["schema_valid"] is True
    assert _validate_content("prefix {\"status\":\"ok\"}", "comparison")["json_parse"] is False
    assert _validate_content('{"status":"ok","summary":"bounded","risk_flags":"not-a-list"}', "comparison")["schema_valid"] is False
