"""Pure XML inspection for provided exports; no vendor schema or import adapter.

Names are compared by expanded namespace URI, not prefix. Paths are positional:
each sibling QName has its own 1-based index; '/' and '~' inside a QName use
JSON-pointer escaping. Leaf/mixed text is retained except XML-whitespace-only
formatting. XML's normal line-ending/attribute normalization still applies.
Comments and processing instructions are ignored. Declared namespace URIs are
reported separately; unused declarations do not produce semantic differences.
Neither function performs file I/O, networking or modifies its input.
"""

import codecs
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, TypedDict
from xml.etree import ElementTree as ET


class XMLProbeError(ValueError):
    """A readable failure with a stable machine code, never raw XML content."""

    code = "xml_probe_error"


class XMLEncodingError(XMLProbeError):
    code = "xml_encoding_error"


class XMLParseError(XMLProbeError):
    code = "xml_parse_error"

    def __init__(self, line: int, column: int):
        super().__init__(f"Invalid XML at line {line}, column {column}.")
        self.line, self.column = line, column


class XMLForbiddenDeclarationError(XMLProbeError):
    code = "xml_forbidden_declaration"


class SignatureEntry(TypedDict):
    path: str
    kind: Literal["element", "attribute", "tail"]
    name: str
    value: str
    position: int
    leaf: bool


class ExportSignature(TypedDict):
    sha256: str
    root_name: str
    root_expanded_name: str
    root_namespace_uri: str | None
    namespace_uris: list[str]
    declared_namespace_uris: list[str]
    entries: list[SignatureEntry]


class ChangedEntry(TypedDict):
    path: str
    before: SignatureEntry
    after: SignatureEntry


class ExportComparison(TypedDict):
    before_sha256: str
    after_sha256: str
    semantic_equal: bool
    added: list[SignatureEntry]
    removed: list[SignatureEntry]
    changed: list[ChangedEntry]


_DECLARATION = re.compile(r"\A<\?xml\s+.*?\?>", re.DOTALL)
_ENCODING = re.compile(r"\bencoding\s*=\s*(['\"])([A-Za-z][A-Za-z0-9._-]*)\1")
_MARKUP = re.compile(r"<!--|<!\[CDATA\[|<\?|<!DOCTYPE\b|<!ENTITY\b", re.IGNORECASE)
_XML_WHITESPACE = frozenset(" \t\r\n")


def _declared_encoding(text: str) -> str | None:
    declaration = _DECLARATION.match(text)
    if declaration is None:
        return None
    encoding = _ENCODING.search(declaration.group())
    return encoding.group(2) if encoding else None


def _decode(data: bytes) -> str:
    detected: str | None = None
    for bom, encoding in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                          (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
                          (codecs.BOM_UTF8, "utf-8-sig")):
        if data.startswith(bom):
            detected = encoding
            break
    if detected is None:
        for prefix, encoding in ((b"\x00\x00\x00<", "utf-32-be"), (b"<\x00\x00\x00", "utf-32-le"),
                                 (b"\x00<", "utf-16-be"), (b"<\x00", "utf-16-le")):
            if data.startswith(prefix):
                detected = encoding
                break
    # The declaration uses ASCII syntax in compatible single-byte encodings.
    # Latin-1 here only reads its encoding name; actual bytes are decoded strictly.
    declared = _declared_encoding(data.decode("latin-1")) if detected is None else None
    encoding = detected or declared or "utf-8"
    try:
        text = data.decode(encoding, errors="strict")
        declared = _declared_encoding(text)
        if declared:
            canonical = codecs.lookup(declared).name
            if detected:
                actual = "utf-8" if detected == "utf-8-sig" else detected
                if actual in {"utf-16", "utf-32"}:
                    little = data.startswith(codecs.BOM_UTF16_LE if actual == "utf-16" else codecs.BOM_UTF32_LE)
                    actual += "-le" if little else "-be"
                family = actual.rsplit("-", 1)[0] if actual.endswith(("-le", "-be")) else actual
                if canonical not in {actual, family, "utf-8-sig" if actual == "utf-8" else actual}:
                    raise XMLEncodingError("XML declaration conflicts with its byte order mark or encoding.")
        return text
    except (LookupError, UnicodeError) as error:
        raise XMLEncodingError("XML bytes cannot be decoded with their declared or detected encoding.") from error


def _reject_declarations(text: str) -> None:
    """Inspect decoded markup before any parser, including UTF-16 declarations."""
    position = 0
    while match := _MARKUP.search(text, position):
        token = match.group()
        if token.upper() in {"<!DOCTYPE", "<!ENTITY"}:
            raise XMLForbiddenDeclarationError("DTD and ENTITY declarations are not allowed in analysis exports.")
        closing = "-->" if token == "<!--" else "]]>" if token == "<![CDATA[" else "?>"
        end = text.find(closing, match.end())
        if end < 0:
            return  # The parser reports malformed comments/CDATA/PI as XML errors.
        position = end + len(closing)


def _name_parts(name: str) -> tuple[str | None, str]:
    if name.startswith("{"):
        namespace, local = name[1:].rsplit("}", 1)
        return namespace, local
    return None, name


def _path_name(name: str) -> str:
    return name.replace("~", "~0").replace("/", "~1")


def _text(value: str | None) -> str:
    return value if value and any(character not in _XML_WHITESPACE for character in value) else ""


class _NamespaceBuilder(ET.TreeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.uris: set[str] = set()

    def start_ns(self, _prefix: str | None, uri: str) -> None:
        if uri:
            self.uris.add(uri)


@dataclass(slots=True)
class _Frame:
    node: ET.Element
    path: str
    position: int
    children: Iterator[ET.Element]
    indexes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visited: bool = False
    next_position: int = 0


def _entries(root: ET.Element) -> Iterator[SignatureEntry]:
    # Iterator frames use O(depth) traversal storage and no Python recursion.
    stack = [_Frame(root, f"/{_path_name(root.tag)}[1]", 1, iter(root))]
    while stack:
        current = stack[-1]
        if not current.visited:
            current.visited = True
            yield SignatureEntry(path=current.path, kind="element", name=current.node.tag,
                                 value=_text(current.node.text), position=current.position, leaf=len(current.node) == 0)
            for name, value in sorted(current.node.attrib.items()):
                yield SignatureEntry(path=f"{current.path}/@{_path_name(name)}", kind="attribute", name=name,
                                     value=value, position=0, leaf=False)
        child = next(current.children, None)
        if child is None:
            stack.pop()
            tail = _text(current.node.tail)
            if stack and tail:
                yield SignatureEntry(path=f"{current.path}/#tail", kind="tail", name="", value=tail,
                                     position=0, leaf=False)
            continue
        current.indexes[child.tag] += 1
        current.next_position += 1
        stack.append(_Frame(child, f"{current.path}/{_path_name(child.tag)}[{current.indexes[child.tag]}]",
                            current.next_position, iter(child)))


def extract_signature(data: bytes) -> ExportSignature:
    """Inspect immutable bytes with generic XML semantics, without vendor claims."""
    if not isinstance(data, bytes):
        raise TypeError("extract_signature expects original XML bytes.")
    text = _decode(data)
    _reject_declarations(text)
    builder = _NamespaceBuilder()
    try:
        root = ET.fromstring(text, parser=ET.XMLParser(target=builder))
    except ET.ParseError as error:
        raise XMLParseError(*error.position) from error
    entries = list(_entries(root))
    namespace, local = _name_parts(root.tag)
    namespaces = {_name_parts(entry["name"])[0] for entry in entries if entry["name"]}
    return ExportSignature(sha256=hashlib.sha256(data).hexdigest(), root_name=local, root_expanded_name=root.tag,
                           root_namespace_uri=namespace, namespace_uris=sorted(uri for uri in namespaces if uri),
                           declared_namespace_uris=sorted(builder.uris),
                           entries=entries)


def compare_exports(before: bytes, after: bytes) -> ExportComparison:
    """Compare positional content; reordered siblings remain meaningful changes."""
    old, new = extract_signature(before), extract_signature(after)
    old_paths = {entry["path"]: entry for entry in old["entries"]}
    new_paths = {entry["path"]: entry for entry in new["entries"]}
    added = [new_paths[path] for path in sorted(new_paths.keys() - old_paths.keys())]
    removed = [old_paths[path] for path in sorted(old_paths.keys() - new_paths.keys())]
    changed = [ChangedEntry(path=path, before=old_paths[path], after=new_paths[path])
               for path in sorted(old_paths.keys() & new_paths.keys()) if old_paths[path] != new_paths[path]]
    return ExportComparison(before_sha256=old["sha256"], after_sha256=new["sha256"],
                            semantic_equal=not (added or removed or changed), added=added, removed=removed, changed=changed)
