from types import SimpleNamespace

import pytest

from src.core.pipeline import PipelineRunError, StockAnalysisPipeline


def _pipeline_for_run():
    pipeline = object.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        stock_list=[],
        single_stock_notify=False,
        report_type="simple",
        analysis_delay=0,
    )
    pipeline.max_workers = 1
    pipeline.fetcher_manager = SimpleNamespace(prefetch_stock_names=lambda *args, **kwargs: None)
    return pipeline


def test_empty_stock_list_is_explicit_non_success():
    pipeline = _pipeline_for_run()
    with pytest.raises(PipelineRunError, match="NO_STOCK_CODES") as exc_info:
        pipeline.run(stock_codes=[])
    assert exc_info.value.outcome == "NO_STOCK_CODES"


def test_all_failed_analysis_does_not_return_false_success():
    pipeline = _pipeline_for_run()
    pipeline.process_single_stock = lambda *args, **kwargs: None
    with pytest.raises(PipelineRunError, match="NO_REPORT") as exc_info:
        pipeline.run(stock_codes=["000001"], send_notification=False)
    assert exc_info.value.outcome == "NO_REPORT"
    assert exc_info.value.partial_results == []


def test_report_save_failure_propagates_after_partial_results_exist():
    pipeline = object.__new__(StockAnalysisPipeline)
    pipeline._generate_aggregate_report = lambda results, report_type: "report"
    pipeline.notifier = SimpleNamespace(save_report_to_file=lambda report: "")
    results = [SimpleNamespace(success=True)]

    with pytest.raises(PipelineRunError, match="REPORT_SAVE_FAILED") as exc_info:
        pipeline._save_local_report(results)
    assert exc_info.value.outcome == "REPORT_SAVE_FAILED"
    assert exc_info.value.partial_results == results
