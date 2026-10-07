import { describe, expect, it } from 'vitest';
import { resolveFileUrl, fileKind } from './files';

describe('safe document URLs', () => {
  it.each(['javascript:alert(1)', 'data:text/html,<script>', '//outside.example/file.pdf', 's3://bucket/key', '/uploads/../private.txt', '/uploads/%2e%2e/private.txt'])('blocks unsafe file references: %s', value => {
    expect(resolveFileUrl(value)).toBe('');
  });

  it('resolves uploaded files against the API host and preserves signed query strings', () => {
    expect(resolveFileUrl('/uploads/documents/lease.pdf', 'https://api.example/api/v1')).toBe('https://api.example/uploads/documents/lease.pdf');
    expect(resolveFileUrl('https://storage.example/lease.pdf?signature=abc')).toBe('https://storage.example/lease.pdf?signature=abc');
  });

  it('recognizes file extensions without mistaking a query string for the file type', () => {
    expect(fileKind('https://storage.example/lease.PDF?signature=abc')).toBe('pdf');
    expect(fileKind('/uploads/photo.jpg?version=1')).toBe('image');
    expect(fileKind('/uploads/page.html?name=lease.pdf')).toBe('other');
  });
});
