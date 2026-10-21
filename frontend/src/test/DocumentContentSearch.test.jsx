import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DocumentContentSearch from '../features/documentSearch/DocumentContentSearch';

vi.mock('../api', () => ({ api: {} }));
afterEach(() => cleanup());

const hit = { id: 'd1', title: 'Protokoll 2026', document_type: 'Protokoll', property_id: 'p1', document_date: '2026-03-02',
  file_url: '/uploads/documents/p.pdf', snippet: '…Wartungsprotokoll Rauchwarnmelder, alle Melder geprüft…' };

describe('search in document contents', () => {
  it('shows how much is searchable, finds documents with a highlighted snippet and opens them', async () => {
    const service = {
      status: vi.fn().mockResolvedValue({ documents: 5, indexed: 3, unreadable: 1 }),
      refresh: vi.fn().mockResolvedValue({ documents: 5, indexed: 5, unreadable: 1 }),
      search: vi.fn().mockResolvedValue({ items: [hit], total: 1, index: { documents: 5, indexed: 5, unreadable: 1 } }),
    };
    const onOpen = vi.fn();
    render(<DocumentContentSearch service={service} onOpen={onOpen} places={{ p1: 'Bautzner Straße 61' }} canWrite />);
    expect(await screen.findByText(/3 von 5 Dokumenten im Inhalt durchsuchbar, 1 ohne lesbaren Text/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Jetzt lesen' }));
    await waitFor(() => expect(service.refresh).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText('Im Dokumentinhalt suchen'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: /Suchen/ }));
    expect(screen.getByRole('alert')).toHaveTextContent('mindestens zwei Zeichen');
    fireEvent.change(screen.getByLabelText('Im Dokumentinhalt suchen'), { target: { value: 'Rauchwarnmelder' } });
    fireEvent.click(screen.getByRole('button', { name: /Suchen/ }));
    expect(await screen.findByText('1 Dokument enthält „Rauchwarnmelder“.')).toBeInTheDocument();
    expect(service.search).toHaveBeenCalledWith('Rauchwarnmelder', expect.anything());
    expect(screen.getByText('Rauchwarnmelder', { selector: 'mark' })).toBeInTheDocument();
    expect(screen.getByText(/Protokoll · Bautzner Straße 61 · 02\.03\.2026/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Protokoll 2026' }));
    expect(onOpen).toHaveBeenCalledWith(hit);
  });

  it('keeps index, refresh and search in the chosen file context and can reach later results after a retry', async () => {
    const scope = { unit_id: 'u1' };
    const older = { ...hit, id: 'd2', title: 'Älteres Protokoll' };
    const service = {
      status: vi.fn().mockResolvedValue({ documents: 2, indexed: 1, unreadable: 0 }),
      refresh: vi.fn().mockResolvedValue({ documents: 2, indexed: 2, unreadable: 0 }),
      search: vi.fn().mockResolvedValueOnce({ items: [hit], total: 2, has_more: true, next_skip: 1 })
        .mockRejectedValueOnce(new Error('Verbindung unterbrochen'))
        .mockResolvedValueOnce({ items: [older], total: 2, has_more: false, next_skip: null }),
    };
    const onOpen = vi.fn();
    render(<DocumentContentSearch scope={scope} service={service} canWrite onOpen={onOpen} />);
    expect(await screen.findByText(/1 von 2 Dokumenten im Inhalt durchsuchbar/)).toBeInTheDocument();
    expect(service.status).toHaveBeenCalledWith(expect.objectContaining({ scope }));
    fireEvent.click(screen.getByRole('button', { name: 'Jetzt lesen' }));
    await screen.findByText(/2 von 2 Dokumenten im Inhalt durchsuchbar/);
    expect(service.refresh).toHaveBeenCalledWith(expect.objectContaining({ scope }));
    fireEvent.change(screen.getByLabelText('Im Dokumentinhalt suchen'), { target: { value: 'Rauchwarnmelder' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suchen' }));
    await screen.findByText(/2 Dokumente enthalten „Rauchwarnmelder“ – 1 werden gezeigt/);
    expect(service.search).toHaveBeenLastCalledWith('Rauchwarnmelder', expect.objectContaining({ scope, skip: 0 }));
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Suchergebnisse laden' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung unterbrochen');
    expect(screen.getByRole('button', { name: hit.title })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Suchergebnisse laden' }));
    await screen.findByRole('button', { name: older.title });
    expect(screen.queryByRole('button', { name: 'Weitere Suchergebnisse laden' })).not.toBeInTheDocument();
    expect(service.search).toHaveBeenLastCalledWith('Rauchwarnmelder', expect.objectContaining({ scope, skip: 1 }));
    fireEvent.click(screen.getByRole('button', { name: older.title }));
    expect(onOpen).toHaveBeenCalledWith(older);
  });

  it('clears the old query and aborts late search answers when changing files', async () => {
    let answer;
    const service = {
      status: vi.fn().mockResolvedValue({ documents: 1, indexed: 1, unreadable: 0 }),
      search: vi.fn().mockImplementation(() => new Promise(resolve => { answer = resolve; })),
    };
    const { rerender } = render(<DocumentContentSearch scope={{ property_id: 'p1' }} service={service} />);
    fireEvent.change(screen.getByLabelText('Im Dokumentinhalt suchen'), { target: { value: 'Rauchwarnmelder' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suchen' }));
    const request = service.search.mock.calls[0][1];
    rerender(<DocumentContentSearch scope={{ property_id: 'p2' }} service={service} />);
    expect(request.signal.aborted).toBe(true);
    answer({ items: [hit], total: 1 });
    await waitFor(() => expect(service.status).toHaveBeenLastCalledWith(expect.objectContaining({ scope: { property_id: 'p2' } })));
    expect(screen.getByLabelText('Im Dokumentinhalt suchen')).toHaveValue('');
    expect(screen.queryByRole('button', { name: hit.title })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Suchen' })).toBeEnabled();
  });
});
