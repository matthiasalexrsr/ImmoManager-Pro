// An e-mail address breaks only after its "@" when its column is narrow, never at a hyphen of the domain.
export default function EmailText({ value }) {
  const text = String(value);
  const at = text.lastIndexOf('@');
  if (at <= 0) return text;
  return <span className="cell-email"><span>{text.slice(0, at + 1)}</span><wbr /><span>{text.slice(at + 1)}</span></span>;
}
