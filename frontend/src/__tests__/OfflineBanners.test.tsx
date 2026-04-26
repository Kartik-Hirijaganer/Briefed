import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OfflineBanners } from '../features/offline/OfflineBanners';

const onlineMock = vi.hoisted(() => ({ value: true }));
const installPromptMock = vi.hoisted(() => ({
  show: false,
  dismiss: vi.fn(),
}));
const pendingMock = vi.hoisted(() => ({ pendingMutations: [] as unknown[] }));
const syncMock = vi.hoisted(() => ({ lastReplayError: null as string | null }));
const storageMock = vi.hoisted(() => ({ usageRatio: null as number | null }));

vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => onlineMock.value }));
vi.mock('../hooks/usePendingMutations', () => ({
  usePendingMutations: () => ({
    pendingMutations: pendingMock.pendingMutations,
    refreshPendingMutations: vi.fn(),
  }),
}));
vi.mock('../hooks/useSyncQueueDrain', () => ({
  useSyncQueueDrain: () => ({
    lastReplayError: syncMock.lastReplayError,
    drainNow: vi.fn(),
    draining: false,
  }),
}));
vi.mock('../hooks/useStorageEstimate', () => ({
  useStorageEstimate: () => ({ usageRatio: storageMock.usageRatio }),
}));
vi.mock('../hooks/useInstallPrompt', () => ({
  useInstallPrompt: () => ({
    showIOSInstallPrompt: installPromptMock.show,
    dismissIOSInstallPrompt: installPromptMock.dismiss,
  }),
}));

const renderBanners = (): void => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <OfflineBanners />
    </QueryClientProvider>,
  );
};

describe('<OfflineBanners>', () => {
  beforeEach(() => {
    onlineMock.value = true;
    installPromptMock.show = false;
    installPromptMock.dismiss.mockReset();
    pendingMock.pendingMutations = [];
    syncMock.lastReplayError = null;
    storageMock.usageRatio = null;
  });

  afterEach(() => {
    onlineMock.value = true;
  });

  it('renders nothing when everything is healthy', () => {
    const { container } = render(<OfflineBanners />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the offline alert with queue count when offline with pending mutations', () => {
    onlineMock.value = false;
    pendingMock.pendingMutations = [{ id: '1' }];
    renderBanners();
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByText(/1 queued action/)).toBeInTheDocument();
  });

  it('renders the sync-failed danger alert', () => {
    syncMock.lastReplayError = 'Some queued actions could not sync.';
    renderBanners();
    expect(screen.getByText(/queued action sync failed/i)).toBeInTheDocument();
  });

  it('renders the storage-pressure warning when usage > 80%', () => {
    storageMock.usageRatio = 0.92;
    renderBanners();
    expect(screen.getByText(/storage almost full/i)).toBeInTheDocument();
    expect(screen.getByText(/92%/)).toBeInTheDocument();
  });

  it('renders the iOS install prompt when applicable', () => {
    installPromptMock.show = true;
    renderBanners();
    expect(screen.getByText(/install briefed on your iphone/i)).toBeInTheDocument();
  });
});
