import { beforeEach, describe, expect, it, vi } from 'vitest';
import { portfolioApi } from '../portfolio';

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

describe('portfolioApi connected account', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads the canonical account through one GET and preserves decimal strings', async () => {
    get.mockResolvedValueOnce({
      data: {
        item: {
          snapshot_id: 'snapshot-1',
          account_id: 'private-account',
          source: 'ATHENA_RUNTIME',
          authoritative: true,
          read_only: true,
          simulation_only: true,
          currency: 'HKD',
          cash: '400000.120000',
          positions: [{ market: 'CN', symbol: '600519', avg_cost: '90.120000' }],
          active_orders: [],
        },
      },
    });

    const snapshot = await portfolioApi.getConnectedSnapshot();

    expect(get).toHaveBeenCalledWith('/api/v1/portfolio/connected-snapshot');
    expect(snapshot.readOnly).toBe(true);
    expect(snapshot.cash).toBe('400000.120000');
    expect(snapshot.positions[0].avgCost).toBe('90.120000');
    expect(post).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
    expect(deleteRequest).not.toHaveBeenCalled();
  });
});
