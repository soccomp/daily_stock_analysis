import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  DecisionScorecardDetail,
  DecisionScorecardListParams,
  DecisionScorecardListResponse,
  SingleBrainReadiness,
} from '../types/investmentDecisions';

function queryParams(params: DecisionScorecardListParams): Record<string, unknown> {
  return {
    page: params.page,
    page_size: params.pageSize,
    symbol: params.symbol || undefined,
    action: params.action,
    mode: params.mode,
    source_report_id: params.sourceReportId,
  };
}

export const investmentDecisionsApi = {
  async list(params: DecisionScorecardListParams = {}): Promise<DecisionScorecardListResponse> {
    const { data } = await apiClient.get('/api/v1/decision-scorecards', {
      params: queryParams(params),
    });
    return toCamelCase<DecisionScorecardListResponse>(data);
  },

  async get(decisionId: string): Promise<DecisionScorecardDetail> {
    const { data } = await apiClient.get(`/api/v1/decision-scorecards/${encodeURIComponent(decisionId)}`);
    const response = toCamelCase<{ item: DecisionScorecardDetail }>(data);
    return response.item;
  },

  async readiness(): Promise<SingleBrainReadiness> {
    const { data } = await apiClient.get('/api/v1/single-brain/m2/readiness');
    const response = toCamelCase<{ item: SingleBrainReadiness }>(data);
    return response.item;
  },
};
