"""Apple verification contract tests; mocked commands are not signing acceptance."""
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from scripts import verify_macos_customer as verifier


def app_fixture(tmp_path):
    app=tmp_path/'ImmoManager Pro.app'
    info=app/'Contents/Info.plist'
    info.parent.mkdir(parents=True)
    info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'de.immomanagerpro.desktop',
                                    'CFBundleShortVersionString':'2.0.0','CFBundleVersion':'2.0.0b1'}))
    return app


def runner_fixture(fault=None):
    calls=[]
    def run(command):
        calls.append(command)
        value=b''
        code=0
        if '--display' in command:
            value=b'Authority=Developer ID Application: Synthetic Publisher\nTeamIdentifier=TESTTEAM01\nTimestamp=synthetic\nflags=0x10000(runtime)\n'
            if fault=='adhoc':
                value=b'Signature=adhoc\nflags=0x2(adhoc)\n'
            elif fault=='team':
                value=value.replace(b'TESTTEAM01',b'OTHERTEAM1')
            elif fault=='timestamp':
                value=value.replace(b'Timestamp=synthetic\n',b'')
            elif fault=='runtime':
                value=value.replace(b'flags=0x10000(runtime)',b'flags=0x0(none)')
        elif '--assess' in command:
            value=b'package: accepted\nsource=Notarized Developer ID\n'
            if fault=='notarization':
                value=b'package: accepted\nsource=Developer ID\n'
        if fault=='failed-tool' and 'stapler' in command:
            code=1
        return subprocess.CompletedProcess(command,code,stdout=b'',stderr=value)
    return run,calls


def test_apple_checks_cover_app_image_expected_team_runtime_and_both_tickets(tmp_path):
    app=app_fixture(tmp_path)
    runner,calls=runner_fixture()
    value=verifier.native_checks(app,tmp_path/'package.dmg',version='2.0.0-beta.1',team_id='TESTTEAM01',runner=runner)
    assert value['notarization_status']=='Accepted' and len(calls)==8
    assert sum('stapler' in command for command in calls)==2
    assert any(command[0]=='/usr/sbin/spctl' and 'context:primary-signature' in command for command in calls)
    assert all(isinstance(command,list) for command in calls)


@pytest.mark.parametrize('fault',['adhoc','team','timestamp','runtime','notarization','failed-tool'])
def test_missing_or_failed_apple_protection_never_creates_an_accepted_proof(tmp_path,fault):
    runner,_=runner_fixture(fault)
    with pytest.raises(ValueError):
        verifier.native_checks(app_fixture(tmp_path),tmp_path/'package.dmg',version='2.0.0-beta.1',
                               team_id='TESTTEAM01',runner=runner)


def test_an_unexpected_app_is_rejected_before_any_apple_command(tmp_path):
    app=app_fixture(tmp_path)
    with pytest.raises(ValueError,match='identity/version'):
        verifier.native_checks(app,tmp_path/'package.dmg',version='9.0.0',team_id='TESTTEAM01',
                               runner=lambda _:pytest.fail('No command before identity validation'))


def test_another_beta_with_the_same_short_version_is_not_the_expected_product(tmp_path):
    app=app_fixture(tmp_path)
    with pytest.raises(ValueError,match='identity/version'):
        verifier.native_checks(app,tmp_path/'package.dmg',version='2.0.0-beta.2',team_id='TESTTEAM01',
                               runner=lambda _:pytest.fail('No command before full version validation'))


def test_non_native_host_does_not_mount_or_write_a_package(tmp_path,monkeypatch):
    monkeypatch.setattr(verifier,'sys',SimpleNamespace(platform='linux'))
    output=tmp_path/'never-written'
    with pytest.raises(ValueError,match='native macOS'):
        verifier.verify(tmp_path/'package.dmg',receipt=tmp_path/'receipt.json',output=output,version='2.0.0',
                        commit='a'*40,architecture='x64',team_id='TESTTEAM01',reports=tmp_path/'reports')
    assert not output.exists()


@pytest.mark.parametrize('bound',[True,False])
def test_real_verifier_requires_signed_runtime_binding_and_always_unmounts_owned_path(tmp_path,monkeypatch,bound):
    from scripts.release_artifacts import row
    monkeypatch.setattr(verifier,'sys',SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(verifier,'platform',SimpleNamespace(machine=lambda:'arm64'))
    package=tmp_path/'ImmoManager-Pro-2.0.0-beta.1-macOS-arm64.dmg'
    package.write_bytes(b'controlled signed image fixture; not a native signing claim')
    receipt=package.with_suffix('.dmg.json')
    value={'source_commit':'a'*40,'version':'2.0.0-beta.1','platform':'darwin','architecture':'arm64',
           'workspaces':['own','demo-bw'],**row(package)}
    import json
    receipt.write_text(json.dumps(value))
    calls=[]
    mount=[]
    def checked(command):
        calls.append(command)
        if 'attach' in command:
            point=command[command.index('-mountpoint')+1]
            mount.append(verifier.Path(point))
            return subprocess.CompletedProcess(command,0,stdout=plistlib.dumps({'system-entities':[{'mount-point':point}]}),stderr=b'')
        return subprocess.CompletedProcess(command,0,stdout=b'',stderr=b'')
    monkeypatch.setattr(verifier,'checked',checked)
    monkeypatch.setattr(verifier,'native_checks',lambda *a,**k:{'developer_id_verified':True})
    monkeypatch.setattr(verifier,'acceptance',lambda *a:{'environment':{
        'customer_signed_runtime':True,'customer_package_sha256':row(package)['sha256'] if bound else 'f'*64}})
    output=tmp_path/'verified'
    arguments=dict(receipt=receipt,output=output,version='2.0.0-beta.1',commit='a'*40,
                   architecture='arm64',team_id='TESTTEAM01',reports=tmp_path/'reports')
    if bound:
        proof=verifier.verify(package,**arguments)
        assert proof['customer_signing']['signed_runtime_verified'] is True
        assert (output/package.name).read_bytes()==package.read_bytes()
    else:
        with pytest.raises(ValueError,match='signed runtime acceptance'):
            verifier.verify(package,**arguments)
        assert not output.exists()
    assert len(calls)==2 and calls[-1][1]=='detach'
    assert not mount[0].exists() and not mount[0].parent.exists()


@pytest.mark.parametrize('detach_fails', [False, True])
def test_partial_attach_timeout_attempts_only_owned_detach_and_preserves_original_error(tmp_path, monkeypatch, detach_fails):
    """Fault injection exercises cleanup ordering, without mounting any image."""
    import json

    from scripts.release_artifacts import row

    monkeypatch.setattr(verifier, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(verifier, 'platform', SimpleNamespace(machine=lambda: 'arm64'))
    package = tmp_path / 'ImmoManager-Pro-2.0.0-beta.1-macOS-arm64.dmg'
    package.write_bytes(b'synthetic partial-attach fixture')
    receipt = package.with_suffix('.dmg.json')
    receipt.write_text(json.dumps({'source_commit': 'a' * 40, 'version': '2.0.0-beta.1',
        'platform': 'darwin', 'architecture': 'arm64', 'workspaces': ['own', 'demo-bw'], **row(package)}))
    private = tmp_path / 'owned-verifier'

    def new_temp(**kwargs):
        private.mkdir()
        return str(private)

    monkeypatch.setattr(verifier.tempfile, 'mkdtemp', new_temp)
    calls = []

    def checked(command):
        calls.append(command)
        if 'attach' in command:
            (private / 'image' / 'synthetic-mount-sentinel').write_bytes(b'owned fixture')
            raise subprocess.TimeoutExpired(command, 120)
        assert command == ['/usr/bin/hdiutil', 'detach', str(private / 'image')]
        if detach_fails:
            raise subprocess.CalledProcessError(1, command)
        (private / 'image' / 'synthetic-mount-sentinel').unlink()
        return subprocess.CompletedProcess(command, 0, stdout=b'', stderr=b'')

    monkeypatch.setattr(verifier, 'checked', checked)
    output = tmp_path / 'never-published'
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        verifier.verify(package, receipt=receipt, output=output, version='2.0.0-beta.1', commit='a' * 40,
            architecture='arm64', team_id='TESTTEAM01', reports=tmp_path / 'reports')
    assert len(calls) == 2 and not output.exists()
    assert caught.value.cmd == calls[0] and caught.value.timeout == 120
    if detach_fails:
        assert (private / 'image' / 'synthetic-mount-sentinel').read_bytes() == b'owned fixture'
        assert any('cleanup' in note for note in caught.value.__notes__)
    else:
        assert not private.exists()
