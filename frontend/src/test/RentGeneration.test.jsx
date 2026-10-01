import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import RentGenerationModal from '../components/RentGenerationModal';

const mocks = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
const translate = key => key.split('.').at(-1);
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: translate }) }));
const contracts = [{ id: 'one', contract_number: 'V-1', status: 'active' }, { id: 'ended', contract_number: 'V-2', status: 'ended' }];
const preview = { policy: 'full_month', preview_hash: 'snapshot', total_amount: 750,
  candidates: [{ contract_id: 'one', contract_number: 'V-1', month: '2026-09', due_date: '2026-09-03', total_amount: 750, partial_month: true }],
  existing: [{ contract_id: 'one', month: '2026-08' }], skipped_contracts: [] };
const generated = vi.fn();
const closed = vi.fn();
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
const selectRange = () => {
  fireEvent.change(screen.getByLabelText(/startMonth/), { target: { value: '2026-08' } });
  fireEvent.change(screen.getByLabelText(/endMonth/), { target: { value: '2026-09' } });
};
beforeEach(() => { mocks.post.mockReset().mockResolvedValue(structuredClone(preview)); generated.mockClear(); closed.mockClear(); });

describe('Monthly rent generation', () => {
  it('previews the chosen contracts and sends the snapshot hash only after confirmation', async () => {
    render(<RentGenerationModal contracts={contracts} onGenerated={generated} onClose={closed} />);
    selectRange();
    expect(screen.queryByRole('option', { name: 'V-2' })).not.toBeInTheDocument();
    screen.getByLabelText(/contracts/).options[0].selected = true;
    fireEvent.change(screen.getByLabelText(/contracts/));
    submit();
    await screen.findByRole('button', { name: 'generate' });
    expect(mocks.post).toHaveBeenCalledWith('/rent-charges/preview', { start_month: '2026-08', end_month: '2026-09', contract_ids: ['one'] });
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(closed).not.toHaveBeenCalled();
    expect(generated).not.toHaveBeenCalled();
    mocks.post.mockResolvedValue({ created_count: 1, skipped_count: 1 });
    submit();
    await waitFor(() => expect(generated).toHaveBeenCalledWith({ created_count: 1, skipped_count: 1 }));
    expect(mocks.post).toHaveBeenLastCalledWith('/rent-charges/generate', { start_month: '2026-08', end_month: '2026-09', contract_ids: ['one'], preview_hash: 'snapshot' });
  });

  it('omits an empty contract filter, and retains the range when returning to selection', async () => {
    render(<RentGenerationModal contracts={contracts} onGenerated={generated} onClose={closed} />);
    selectRange(); submit();
    await screen.findByRole('button', { name: 'changeSelection' });
    expect(mocks.post).toHaveBeenCalledWith('/rent-charges/preview', { start_month: '2026-08', end_month: '2026-09' });
    fireEvent.click(screen.getByRole('button', { name: 'changeSelection' }));
    expect(screen.getByLabelText(/startMonth/)).toHaveValue('2026-08');
    expect(screen.getByLabelText(/endMonth/)).toHaveValue('2026-09');
  });

  it('preserves the preview and parameters after a failed confirmation for a safe retry', async () => {
    render(<RentGenerationModal contracts={contracts} onGenerated={generated} onClose={closed} />);
    selectRange(); submit(); await screen.findByRole('button', { name: 'generate' });
    mocks.post.mockRejectedValueOnce(new Error('snapshot changed'));
    submit(); await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('snapshot changed');
    expect(closed).not.toHaveBeenCalled();
    mocks.post.mockResolvedValue({ created_count: 0, skipped_count: 2 });
    submit(); await waitFor(() => expect(generated).toHaveBeenCalled());
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[2][1]);
  });

  it('rejects inverted ranges before sending a request', async () => {
    render(<RentGenerationModal contracts={contracts} onGenerated={generated} onClose={closed} />);
    selectRange(); fireEvent.change(screen.getByLabelText(/endMonth/), { target: { value: '2026-07' } });
    submit(); await screen.findByRole('alert');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('refuses an incomplete preview and disables generation when every month exists', async () => {
    render(<RentGenerationModal contracts={contracts} onGenerated={generated} onClose={closed} />);
    selectRange(); mocks.post.mockResolvedValueOnce({ ...preview, preview_hash: undefined });
    submit(); await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'generate' })).not.toBeInTheDocument();
    mocks.post.mockResolvedValue({ ...preview, candidates: [], total_amount: 0 });
    submit(); expect(await screen.findByRole('button', { name: 'generate' })).toBeDisabled();
  });
});
