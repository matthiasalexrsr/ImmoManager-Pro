// Render a small, safe Markdown subset without interpreting HTML or fetching
// provider-supplied images. Research links open only after an explicit click.
import { Link } from 'react-router-dom';
import { safeLocalHref } from './assistantLinks';

function Inline({ text }) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\))/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(part);
    if (link) {
      const local = safeLocalHref(link[2]);
      if (local) return <Link key={index} to={local}>{link[1]}</Link>;
      try {
        const url = new URL(link[2]);
        if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return <a key={index} href={url.href} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
      } catch { /* Keep unsupported references visible as plain text. */ }
    }
    return part;
  });
}

export default function AssistantMessageContent({ content }) {
  return <div className="assistant-message-body">{String(content || '').split(/(```[\s\S]*?(?:```|$))/g).filter(Boolean).map((block, index) => {
    if (block.startsWith('```')) return <pre key={index}><code>{block.replace(/^```[^\n]*\n?/, '').replace(/```$/, '')}</code></pre>;
    return block.split(/\n\s*\n/).filter(value => value.trim()).map((paragraph, part) => {
      const lines = paragraph.trim().split('\n');
      const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
      if (lines.length >= 2 && lines[0].includes('|') && cells(lines[1]).every(cell => /^:?-{3,}:?$/.test(cell))) {
        const headers = cells(lines[0]);
        return <div className="assistant-table-scroll" key={`${index}:${part}`}><table><caption className="sr-only">Tabelle aus der Antwort</caption><thead><tr>{headers.map((header, column) => <th key={column} scope="col"><Inline text={header} /></th>)}</tr></thead><tbody>{lines.slice(2).map((line, row) => { const values = cells(line); return <tr key={row}>{headers.map((_, column) => <td key={column}><Inline text={values[column] || ''} /></td>)}</tr>; })}</tbody></table></div>;
      }
      if (lines.every(line => /^\s*[-*]\s+/.test(line))) return <ul key={`${index}:${part}`}>{lines.map((line, row) => <li key={row}><Inline text={line.replace(/^\s*[-*]\s+/, '')} /></li>)}</ul>;
      if (lines.length === 1 && /^#{1,4}\s+/.test(paragraph.trim())) return <h3 key={`${index}:${part}`}><Inline text={paragraph.trim().replace(/^#{1,4}\s+/, '')} /></h3>;
      return <p key={`${index}:${part}`}><Inline text={paragraph} /></p>;
    });
  })}</div>;
}
