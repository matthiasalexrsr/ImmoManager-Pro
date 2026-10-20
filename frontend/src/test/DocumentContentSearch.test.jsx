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
});
