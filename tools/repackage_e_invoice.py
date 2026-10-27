"""Deterministic packaging-only replacement of pinned third-party libraries."""
from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

CHANGE = ('Mustang 2.26.0 packaging revision immo1 (2026-10-26): replaced Jackson core/databind '
          '2.22.2 with 2.22.4, AssertJ 2.9.0 with 3.27.7, Byte Buddy 1.12.23 with 1.17.8. '
          'Validator implementation and rule files unchanged. Third-party classes are copied '
          'unchanged from their pinned upstream JARs. See e-invoice inventory, source archives '
          'and component licenses supplied with this product.\n')

def logical(name):
    if name.startswith('META-INF/versions/'):
        return name.split('/', 3)[3] if len(name.split('/', 3)) == 4 else ''
    return name

def derive(base: Path, patches: list[tuple[dict, Path]], output: Path):
    with ZipFile(base) as archive:
        entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    prefixes = tuple(prefix for item, _ in patches for prefix in item['prefixes'])
    prefixes += ('META-INF/maven/net.bytebuddy/byte-buddy-dep/', 'META-INF/maven/cglib/')
    entries = {name: raw for name, raw in entries.items() if not logical(name).startswith(prefixes)}
    for item, path in patches:
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith('/') or logical(name) == 'module-info.class' or name == 'META-INF/MANIFEST.MF':
                    continue
                raw = archive.read(name)
                # Keep all functional resources at their actual classpath. Isolate
                # license/notice texts that would otherwise replace another vendor's.
                basename = name.rsplit('/', 1)[-1].lower()
                is_notice = any(word in basename for word in ('license', 'notice', 'copying')) and not name.endswith('.class')
                key = 'IMMO-PATCH-NOTICES/' + item['artifact'] + '/' + name if is_notice else name
                if key in entries and entries[key] != raw:
                    if name.startswith('META-INF/services/'):
                        raw = b'\n'.join(sorted(set(entries[key].splitlines() + raw.splitlines()))) + b'\n'
                    else:
                        raise RuntimeError('Unreviewed replacement collision: ' + key)
                entries[key] = raw
    manifest = entries['META-INF/MANIFEST.MF'].replace(b'\r\n', b'\n')
    if b'Multi-Release: true' not in manifest:
        manifest = manifest.rstrip(b'\n') + b'\nMulti-Release: true\n\n'
    entries['META-INF/MANIFEST.MF'] = manifest.replace(b'\n', b'\r\n')
    entries['IMMO-PACKAGING-CHANGES.txt'] = CHANGE.encode()
    with ZipFile(output, 'w', compression=ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = ZipInfo(name, (2026, 10, 26, 0, 0, 0))
            info.create_system = 3
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return hashlib.sha256(output.read_bytes()).hexdigest()

def kosit_cli(base: Path, output: Path):
    with ZipFile(base) as archive:
        entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/') and not name.startswith('ui/')}
    entries['IMMO-PACKAGING-CHANGES.txt'] = b'KoSIT 1.6.3 packaging revision immo1 (2026-10-26). Omitted the unused ui/ web application. All validator classes and remaining resources unchanged. The product invokes only the bounded local command line interface, not the HTTP server. Apache-2.0 applies to this packaging adjustment.\n'
    with ZipFile(output, 'w', compression=ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = ZipInfo(name, (2026, 10, 26, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return hashlib.sha256(output.read_bytes()).hexdigest()
