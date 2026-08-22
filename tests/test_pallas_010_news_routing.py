from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.search_service import BochaSearchProvider, SearchResponse, SearchResult, SearchService, SearXNGSearchProvider
from src.services.dependency_health import DependencyHealthStore


def _response(provider, *, success=True):
    return SearchResponse(
        query="新能源 A股 最新消息 催化",
        provider=provider,
        success=success,
        results=(
            [SearchResult("新能源最新公告", "行业消息", "https://example.com/news", "example.com", datetime.now(timezone.utc).isoformat())]
            if success else []
        ),
        error_message=None if success else "provider down",
    )


def test_bocha_is_primary_and_searxng_is_only_canonical_fallback(tmp_path):
    store = DependencyHealthStore(tmp_path / "health.json", transition_cooldown_seconds=0)
    service = SearchService(
        bocha_keys=["redacted-test-key"],
        searxng_base_urls=["http://127.0.0.1:18080"],
        dependency_health_store=store,
    )
    assert [provider.name for provider in service._providers[:2]] == ["Bocha", "SearXNG"]
    bocha, searxng = service._providers[:2]
    bocha.search = MagicMock(return_value=_response("Bocha", success=False))
    searxng.search = MagicMock(return_value=_response("SearXNG"))

    response = service.search_topic_news("新能源", max_results=1)

    assert response.success is True
    assert response.provider == "SearXNG"
    assert response.fallback_used is True
    assert response.fallback_from == "Bocha"
    assert "fallback_from=Bocha" in response.to_context()
    assert searxng.search.call_count == 1
    snapshot = store.snapshot()
    assert snapshot["dependencies"]["bocha"]["status"] == "FAILED"
    assert snapshot["dependencies"]["searxng"]["fallback_from"] == "Bocha"


def test_bocha_success_does_not_call_searxng(tmp_path):
    service = SearchService(
        bocha_keys=["redacted-test-key"],
        searxng_base_urls=["http://127.0.0.1:18080"],
        dependency_health_store=DependencyHealthStore(tmp_path / "health.json"),
    )
    bocha, searxng = service._providers[:2]
    bocha.search = MagicMock(return_value=_response("Bocha"))
    searxng.search = MagicMock()

    response = service.search_topic_news("新能源", max_results=1)

    assert response.provider == "Bocha"
    assert response.fallback_used is False
    searxng.search.assert_not_called()


def test_all_news_sources_failed_is_explicitly_unavailable(tmp_path):
    service = SearchService(
        bocha_keys=["redacted-test-key"],
        searxng_base_urls=["http://127.0.0.1:18080"],
        dependency_health_store=DependencyHealthStore(tmp_path / "health.json"),
    )
    for provider in service._providers[:2]:
        provider.search = MagicMock(return_value=_response(provider.name, success=False))

    response = service.search_topic_news("新能源", max_results=1)

    assert response.success is False
    assert response.error_message == "所有搜索引擎都不可用或搜索失败"


def test_public_searxng_discovery_requires_explicit_opt_in():
    assert not any(provider.name == "SearXNG" for provider in SearchService()._providers)
    assert any(
        provider.name == "SearXNG" and getattr(provider, "_use_public_instances", False)
        for provider in SearchService(searxng_public_instances_enabled=True)._providers
    )
