"""Customer promotion must reject missing native evidence and unsigned macOS."""
import json
import subprocess

import pytest

from backend.tests.test_release_artifacts import COMMIT, VERSION, write
from backend.tests.test_release_artifacts import inputs as inputs
from scripts import release_artifacts as release


def signed_windows(inputs, tmp_path):
    release.stage_native(**inputs)
    signed, metadata = tmp_path / 'signed', tmp_path / 'metadata'
    signed.mkdir()
    metadata.mkdir()
    setup = signed / f'ImmoManager-Pro-{VERSION}-Setup-x64.exe'
    setup.write_bytes(b'controlled signed Windows test fixture')
    write(setup.with_suffix('.build.json'), {'version': VERSION, 'signature_status': 'Valid',
          'installer_sha256': release.digest(setup)})
    setup.with_suffix('.sha256').write_text(release.digest(setup)+'  '+setup.name+'\n')
    portable = signed / f'ImmoManager-Pro-{VERSION}-Windows.zip'
    portable.write_bytes(b'controlled portable test fixture')
    write(metadata / 'sbom-python.cdx.json', {'bomFormat': 'CycloneDX'})
    return dict(staged=inputs['output'], installer=setup, portable=portable, metadata=metadata,
                output=tmp_path/'customer', version=VERSION, commit=COMMIT)


def test_customer_finalize_refuses_the_unsigned_macos_test_packages(inputs, tmp_path):
    options = signed_windows(inputs, tmp_path)
    with pytest.raises(ValueError, match='notariz|Developer.ID'):
        release.finalize_signed(**options)
    assert not options['output'].exists()


def test_missing_ai_worker_receipts_cannot_pass_native_release_acceptance(inputs):
    (inputs['reports']/'Desktop-macos-arm64-reports/frozen-runtime/ai-image-worker-smoke.json').unlink()
    with pytest.raises(ValueError, match='AI|worker'):
        release.stage_native(**inputs)


def rewrite_manifest(folder, value):
    (folder/'release-assets.json').write_text(json.dumps(value, indent=2)+'\n')
    (folder/'SHA256SUMS.txt').write_text('\n'.join(
        f'{release.digest(path)}  {path.name}' for path in sorted(folder.iterdir())
        if path.name!='SHA256SUMS.txt')+'\n', encoding='ascii')


def test_even_explicit_beta_requires_every_native_package_before_remote_actions(inputs, monkeypatch):
    release.stage_native(**inputs)
    folder=inputs['output']
    missing=f'ImmoManager-Pro-{VERSION}-macOS-arm64.dmg'
    (folder/missing).unlink()
    value=release.read_json(folder/'release-assets.json')
    value['files']=[entry for entry in value['files'] if entry['file']!=missing]
    rewrite_manifest(folder,value)
    calls=[]
    def remote_target(*args, **kwargs):
        calls.append('remote')
        return True
    monkeypatch.setattr(release,'check_release_target',remote_target)
    monkeypatch.setattr(release.subprocess,'run',lambda command,**k:subprocess.CompletedProcess(command,0))
    with pytest.raises(ValueError,match='required|Missing|complete'):
        release.publish_release(folder,version=VERSION,commit=COMMIT,tag='v'+VERSION,
                                repository='owner/repo',allow_unsigned=True)
    assert calls==[]


@pytest.mark.parametrize('stage',['source-runtime','frozen-runtime','qt-demo-ui'])
@pytest.mark.parametrize('fault',['failed-text','wrong-runtime','missing-docx','bad-image','wrong-document'])
def test_failed_or_mismatched_ai_evidence_never_becomes_release_eligible(inputs,stage,fault):
    folder=inputs['reports']/'Desktop-linux-arm64-reports'/stage
    path=folder/'ai-image-worker-smoke.json'
    worker=release.read_json(path)
    if fault=='failed-text':
        observation=release.read_json(folder/'ai-text-worker-observation.json')
        observation['failed']=True
        write(folder/'ai-text-worker-observation.json',observation)
    elif fault=='wrong-runtime':
        worker['packaged_runtime']=stage=='source-runtime'
    elif fault=='missing-docx':
        worker['assistant_attachments'].pop('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    elif fault=='bad-image':
        worker['cases']['application/pdf']['pixels']=[1,1]
    else:
        worker['text_worker']['input_sha256']='f'*64
    write(path,worker)
    with pytest.raises(ValueError,match='AI.*worker'):
        release.stage_native(**inputs)
    assert not (inputs['output']/'release-assets.json').exists()


@pytest.mark.parametrize('arch',['x64','arm64'])
@pytest.mark.parametrize('field',['developer_id_verified','hardened_runtime_verified','notarization_status',
                                 'stapler_validated','gatekeeper_accepted','accepted_package_sha256',
                                 'signed_runtime_verified','signed_runtime_package_sha256'])
def test_customer_macos_proof_cannot_be_partial_or_bound_to_other_bytes(inputs,tmp_path,arch,field):
    from backend.tests.test_release_artifacts import customer_macos_fixture
    options=signed_windows(inputs,tmp_path)
    customer_macos_fixture(inputs['output'])
    path=inputs['output']/f'ImmoManager-Pro-{VERSION}-macOS-{arch}.dmg.json'
    value=release.read_json(path)
    value['customer_signing'].pop(field)
    write(path,value)
    with pytest.raises(ValueError,match='Developer.ID.*notariz'):
        release.finalize_signed(**options)
    assert not options['output'].exists()


@pytest.mark.parametrize('hardening_run',[0,-1,123,456])
def test_release_requires_its_own_successful_hardening_run_identity(inputs,hardening_run):
    inputs['hardening_run']=hardening_run
    with pytest.raises(ValueError,match='distinct successful'):
        release.stage_native(**inputs)
    assert not inputs['output'].exists()
