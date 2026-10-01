import { inflateSync } from 'node:zlib';

// Test-only reader for the app's standard-font ReportLab PDFs, not a generic PDF
// parser or visual-layout check. Unknown stream filters/indirect lengths fail closed.
export function decodeAscii85(input) {
  const encoded = input.toString('ascii').replace(/\s/g, '').replace(/^<~/, '').replace(/~>$/, '');
  const output = [];
  let group = [];
  const flush = count => {
    let value = 0;
    for (const digit of [...group, ...Array(5 - group.length).fill(84)]) value = value * 85 + digit;
    if (value > 0xffffffff) throw new Error('Invalid ASCII85 group');
    const bytes = Buffer.alloc(4);
    bytes.writeUInt32BE(value);
    output.push(bytes.subarray(0, count));
    group = [];
  };
  for (const character of encoded) {
    if (character === 'z') {
      if (group.length) throw new Error('ASCII85 zero inside a group');
      output.push(Buffer.alloc(4));
      continue;
    }
    const digit = character.charCodeAt(0) - 33;
    if (digit < 0 || digit > 84) throw new Error('Invalid ASCII85 character');
    group.push(digit);
    if (group.length === 5) flush(4);
  }
  if (group.length === 1) throw new Error('Truncated ASCII85 group');
  if (group.length) flush(group.length - 1);
  return Buffer.concat(output);
}

export function extractReportlabText(bytes) {
  if (!bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) throw new Error('Not a PDF attachment');
  if (bytes.length > 2 * 1024 * 1024) throw new Error('Unexpectedly large test PDF');
  const pdf = bytes.toString('latin1');
  const streams = /\b\d+\s+\d+\s+obj\s*<<((?:(?!endobj)[\s\S])*?)>>\s*stream\r?\n/g;
  const texts = [];
  for (const match of pdf.matchAll(streams)) {
    const length = /\/Length\s+(\d+)\b/.exec(match[1]);
    if (!length || /^\s+\d+\s+R\b/.test(match[1].slice(length.index + length[0].length))) {
      throw new Error('Unsupported PDF stream length');
    }
    const start = match.index + match[0].length;
    let content = bytes.subarray(start, start + Number(length[1]));
    const filters = /\/Filter\s*(\[[^\]]+\]|\/\w+)/.exec(match[1])?.[1] || '';
    for (const [, filter] of filters.matchAll(/\/(\w+)/g)) {
      if (filter === 'ASCII85Decode') content = decodeAscii85(content);
      else if (filter === 'FlateDecode') content = inflateSync(content, { maxOutputLength: 2 * 1024 * 1024 });
      else throw new Error(`Unsupported PDF filter: ${filter}`);
    }
    for (const [, literal] of content.toString('latin1').matchAll(/\(((?:\\[\s\S]|[^\\()])*)\)\s*Tj\b/g)) {
      texts.push(literal.replace(/\\(?:\r\n|[\r\n])/g, '').replace(/\\([0-7]{1,3}|[nrtbf()\\])/g,
        (_, escape) => /^[0-7]/.test(escape) ? String.fromCharCode(parseInt(escape, 8))
          : ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f' }[escape] || escape)));
    }
  }
  if (!texts.length) throw new Error('No supported ReportLab text found in PDF');
  return texts.join('\n');
}
