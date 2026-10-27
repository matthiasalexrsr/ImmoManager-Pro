"""Inventory the actual Debian image; never reuse Windows runtime notices."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def generate(output: Path):
    result = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\t${db:Status-Status}\n'],
                            check=True, capture_output=True, text=True)
    folder = output / 'system'
    folder.mkdir(exist_ok=True)
    rows = []
    for line in result.stdout.splitlines():
        package, version, source, source_version, status = line.split('\t')
        if status != 'installed':  # removed packages keep only config files (e.g. dirmngr after purging gnupg)
            continue
        copyright = Path('/usr/share/doc') / package / 'copyright'
        if not copyright.is_file():
            raise RuntimeError('Missing Debian copyright notice: ' + package)
        name = hashlib.sha256(package.encode()).hexdigest()[:24] + '.txt'
        shutil.copyfile(copyright, folder / name)
        rows.append({'ecosystem': 'Debian', 'name': package, 'version': version,
                     'license': 'Siehe unveränderte Debian-Copyrightdatei', 'notice': 'system/' + name,
                     'source_package': source, 'source_version': source_version})
    (folder / 'inventory.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    (folder / 'README.txt').write_text(
        'Actual Debian packages in the operated hosting image. Copyright/license notices are preserved verbatim.\n'
        'The application source delivery is not a redistribution of this OS image. Before distributing a built image,\n'
        'supply corresponding sources/build material for the exact OS package revisions where their licenses require it.\n'
        'The source package names and revisions are recorded in inventory.json.\n', encoding='utf-8')
    return rows
