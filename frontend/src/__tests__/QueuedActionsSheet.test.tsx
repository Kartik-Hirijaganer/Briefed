import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueuedActionsSheet } from '../features/offline/QueuedActionsSheet';
import type { PendingMutationRecord } from '../offline/db';

const onlineMock = vi.hoisted(() => ({ value: true }));
const pendingMock = vi.hoisted(() => ({ pendingMutations: [] as PendingMutationRecord[] }));
const replayMock = vi.hoisted(() => vi.fn());
const removeMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => onlineMock.value }));
vi.mock('../hooks/usePendingMutations', () => ({
  usePendingMutations: () => ({
    pendingMutations: pendingMock.pendingMutations,
    refreshPendingMutations: vi.fn(),
  }),
}));
vi.mock('../offline/mutations', () => ({
  replayPendingMutations: replayMock,
  removePendingMutation: removeMock,
}));

const sample = (overrides: Partial<PendingMutationRecord> = {}): PendingMutationRecord => ({
  id: 'm1',
  type: 'preferences_patch',
  payload: { type: 'preferences_patch', body: { redact_pii: true } },
  createdAt: 1745524800000,
  attempts: 0,
  ...overrides,
});

const renderSheet = (): void => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <QueuedActionsSheet />
    </QueryClientProvider>,
  );
};

describe('<QueuedActionsSheet>', () => {
  beforeEach(() => {
    onlineMock.value = true;
    pendingMock.pendingMutations = [];
    replayMock.mockReset();
    removeMock.mockReset();
  });

  afterEach(() => {
    onlineMock.value = true;
  });

  it('renders nothing when the queue is empty', () => {
    const client = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <QueuedActionsSheet />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the floating queue count button when there are pending rows', () => {
    pendingMock.pendingMutations = [sample(), sample({ id: 'm2' })];
    renderSheet();
    expect(screen.getByRole('button', { name: /2 queued/i })).toBeInTheDocument();
  });

  it('opens the sheet, lists rows, and triggers a sync when online', async () => {
    pendingMock.pendingMutations = [sample({ attempts: 2, lastError: 'last err' })];
    replayMock.mockResolvedValue({ replayed: 1, failed: 0 });
    const user = userEvent.setup();
    renderSheet();
    await user.click(screen.getByRole('button', { name: /1 queued/i }));
    expect(screen.getByText('Preferences update')).toBeInTheDocument();
    expect(screen.getByText(/2 attempts/)).toBeInTheDocument();
    expect(screen.getByText('last err')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /sync now/i }));
    await waitFor(() => expect(replayMock).toHaveBeenCalled());
  });

  it('disables the sync button when offline', async () => {
    onlineMock.value = false;
    pendingMock.pendingMutations = [sample()];
    const user = userEvent.setup();
    renderSheet();
    await user.click(screen.getByRole('button', { name: /1 queued/i }));
    expect(screen.getByRole('button', { name: /sync now/i })).toBeDisabled();
  });

  it('cancels a queue row via removePendingMutation', async () => {
    pendingMock.pendingMutations = [sample({ id: 'mX' })];
    const user = userEvent.setup();
    renderSheet();
    await user.click(screen.getByRole('button', { name: /1 queued/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(removeMock).toHaveBeenCalledWith('mX');
  });
});
