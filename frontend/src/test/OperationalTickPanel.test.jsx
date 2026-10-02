import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import OperationalTickPanel from '../components/OperationalTickPanel';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), auth: { user: { role: 'eigentuemer' } } }));
vi.mock('../api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
const result = { tasks_created: 1, calendar_events_created: 2, notifications_generated: 3, warnings: [] };

beforeEach(() => {
  mocks.auth = { user: { role: 'eigentuemer' } };
  mocks.get.mockReset().mockResolvedValue({ automatic_enabled: false, automatic_running: false });
  mocks.post.mockReset().mockResolvedValue(result);
});

it('shows the actual disabled worker and retries a failed status request', async () => {
  mocks.get.mockRejectedValueOnce(new Error('Status unavailable'));
  render(<OperationalTickPanel />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Status unavailable');
  fireEvent.click(screen.getByRole('button', { name: 'operational.retry' }));
  expect(await screen.findByText('operational.automaticDisabled')).toBeVisible();
  expect(mocks.get).toHaveBeenCalledTimes(2);
});

it('keeps the failed window and limit draft, then reports only the successful run', async () => {
  mocks.post.mockRejectedValueOnce(new Error('Catch-up budget exceeded'));
  const completed = vi.fn();
  render(<OperationalTickPanel onCompleted={completed} />);
  fireEvent.click(screen.getByRole('button', { name: 'operational.run' }));
  fireEvent.change(screen.getByLabelText('operational.asOf *'), { target: { value: '2026-03-31' } });
  fireEvent.change(screen.getByLabelText('operational.limit *'), { target: { value: '100' } });
  fireEvent.change(screen.getByLabelText('operational.catchUp *'), { target: { value: 'true' } });
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Catch-up budget exceeded');
  expect(screen.getByLabelText('operational.asOf *')).toHaveValue('2026-03-31');
  expect(screen.getByLabelText('operational.limit *')).toHaveValue(100);
  expect(completed).not.toHaveBeenCalled();
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(mocks.post).toHaveBeenLastCalledWith('/tasks/operational-tick', {
    as_of: '2026-03-31', max_items: 100, lookback_days: 366, full_catch_up: true,
  });
  expect(completed).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('status')).toHaveTextContent('operational.result');
});

it.each(['readonly', 'buchhaltung', 'unknown'])('offers no operation to %s accounts', async role => {
  mocks.auth = { user: { role } };
  render(<OperationalTickPanel />);
  await screen.findByText('operational.automaticDisabled');
  expect(screen.queryByRole('button', { name: 'operational.run' })).not.toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalled();
});

it('closes the draft when current grants disappear instead of using stale role controls', async () => {
  const { rerender } = render(<OperationalTickPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'operational.run' }));
  expect(screen.getByRole('dialog')).toBeVisible();
  mocks.auth = { user: { role: 'eigentuemer', write_permissions: [] } };
  rerender(<OperationalTickPanel />);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(mocks.post).not.toHaveBeenCalled();
});

it('shows invalid response as a retryable error without claiming completion', async () => {
  mocks.post.mockResolvedValue({});
  const completed = vi.fn();
  render(<OperationalTickPanel onCompleted={completed} />);
  fireEvent.click(screen.getByRole('button', { name: 'operational.run' }));
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  expect(await screen.findByRole('alert')).toHaveTextContent('operational.invalidResult');
  expect(completed).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog')).toBeVisible();
});
