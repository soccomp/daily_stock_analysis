import { beforeEach, describe, expect, it, vi } from 'vitest';
import { investmentDecisionsApi } from '../investmentDecisions';

const { get, post, put, patch, deleteRequest } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  deleteRequest: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
    put,
    patch,
    delete: deleteRequest,
  },
}));

describe('investmentDecisionsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses GET-only canonical list, detail, and readiness surfaces', async () => {
    get
      .mockResolvedValueOnce({
        data: {
          items: [{
            decision_id: 'decision-1',
            created_at: '2026-08-09T03:00:00Z',
            source_report_id: 42,
            account_id: 'account',
            symbol: '600519',
            market: 'CN',
            action: 'ADD',
            current_quantity: 300,
            target_quantity: 500,
            delta_quantity: 200,
            confidence: '0.84',
            rationale: 'reason',
            mode: 'SIMULATION_EXECUTION',
            execution_status: 'BLOCKED',
            reconciliation_status: 'RECONCILED',
            requested_quantity: 200,
            submitted_quantity: 0,
            filled_quantity: 0,
            remaining_quantity: 200,
            snapshot_b_available: true,
          }],
          total: 1,
          page: 1,
          page_size: 10,
        },
      })
      .mockResolvedValueOnce({ data: { item: { scorecard_hash: 'hash' } } })
      .mockResolvedValueOnce({
        data: {
          item: {
            feature_enabled: true,
            execution_mode: 'SIMULATION_EXECUTION',
            execution_authorization: 'ON',
            recurring_scheduler: { enabled: true, authority_count: 1 },
            latest_cycle_diagnostics: {
              decision_cycle_id: 'cycle-1',
              status: 'FAILED_CLOSED',
              failure_stage: 'RESEARCH',
              failure_code: 'AI_QUOTA_EXHAUSTED',
              failure_summary: 'AI 分析额度不足',
              expected_symbol_count: 1,
              research_completed_count: 0,
              research_completed: false,
              decision_count: 0,
              decision_created: false,
              mandate_count: 0,
              mandate_created: false,
              dispatch_attempt_count: 0,
              broker_submission_state: 'NONE',
              recorded_submitted_quantity: 0,
            },
          },
        },
      });

    const list = await investmentDecisionsApi.list({
      page: 1,
      pageSize: 10,
      symbol: '600519',
      action: 'ADD',
      mode: 'SIMULATION_EXECUTION',
      sourceReportId: 42,
    });
    await investmentDecisionsApi.get('decision/1');
    const readiness = await investmentDecisionsApi.readiness();

    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/decision-scorecards', {
      params: {
        page: 1,
        page_size: 10,
        symbol: '600519',
        action: 'ADD',
        mode: 'SIMULATION_EXECUTION',
        source_report_id: 42,
      },
    });
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/decision-scorecards/decision%2F1');
    expect(get).toHaveBeenNthCalledWith(3, '/api/v1/single-brain/m2/readiness');
    expect(list.items[0].submittedQuantity).toBe(0);
    expect(list.items[0].filledQuantity).toBe(0);
    expect(readiness.recurringScheduler.authorityCount).toBe(1);
    expect(readiness.latestCycleDiagnostics?.failureSummary).toBe('AI 分析额度不足');
    expect(readiness.latestCycleDiagnostics?.decisionCreated).toBe(false);
    expect(post).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
    expect(deleteRequest).not.toHaveBeenCalled();
  });
});
