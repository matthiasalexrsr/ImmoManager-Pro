"""Observation only: original R4 auth restart/download/PDF/profile sequence in three fresh Qt processes."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import unittest
from pathlib import Path

COMMIT = '73f4498827978aeb3a380aafa6dbb4ad7ab46097'
TEST_SHA256 = '73f97903e0a665663af26cf73c414675415fd6432cc6a76286bc6966da45a5cf'
PDF_NAME = 'test_builtin_pdf_viewer_displays_local_iframe_and_blob_object'
NAMES = ('test_authentication_storage_persists_after_ordered_window_restart',
         'test_blob_download_requires_save_choice_and_finishes', PDF_NAME,
         'test_profile_settings_native_font_and_remote_request_blocking')
CURRENT = None
PROFILES = {}
OBSERVATIONS = []
PROFILE_SEQUENCE = 0
sys.dont_write_bytecode = True


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


class Observation:
    def __init__(self, output, name):
        self.output, self.name = output, name
        output.mkdir()
        self.started = time.monotonic()
        self.events, self.samples, self.original_failures = [], [], []
        self.lock = threading.Lock()
        OBSERVATIONS.append(self)

    def event(self, kind, **data):
        with self.lock:
            self.events.append({'elapsed': round(time.monotonic() - self.started, 6), 'kind': kind, **data})

    def save(self):
        write_json(self.output / 'observations.json', {'test': self.name,
            'original_failures': self.original_failures, 'events': self.events, 'samples': self.samples})


def install_observers(subject):
    original_factory = subject.standalone.create_window

    def create_window(*args, **kwargs):
        global PROFILE_SEQUENCE
        context = CURRENT
        context.event('window-factory-before', active_profiles=[dict(p) for p in PROFILES.values() if p['active']])
        window = original_factory(*args, **kwargs)
        PROFILE_SEQUENCE += 1
        sequence = PROFILE_SEQUENCE
        profile = window.profile
        metadata = {'sequence': sequence, 'name': profile.storageName(), 'storage': profile.persistentStoragePath(),
                    'cache': profile.cachePath(), 'test': context.name, 'active': True}
        PROFILES[sequence] = metadata
        context.event('window-factory-after', profile=dict(metadata))
        def destroyed(*_):
            metadata['active'] = False
            context.event('profile-QObject-destroyed', profile=dict(metadata))
        profile.destroyed.connect(destroyed)
        window.destroyed.connect(lambda *_: context.event('window-QObject-destroyed', sequence=sequence))
        page = window.web_view.page()
        page.destroyed.connect(lambda *_: context.event('page-QObject-destroyed', sequence=sequence))
        window.web_view.destroyed.connect(lambda *_: context.event('view-QObject-destroyed', sequence=sequence))
        page.renderProcessPidChanged.connect(lambda pid: context.event('renderer-pid-changed', sequence=sequence, pid=pid))
        context.event('renderer-pid-initial', sequence=sequence, pid=page.renderProcessPid())
        original_close = window._finish_close
        def close_observed(*close_args, **close_kwargs):
            context.event('finish-close-before', sequence=sequence, profile_active=metadata['active'])
            try:
                return original_close(*close_args, **close_kwargs)
            finally:
                context.event('finish-close-after', sequence=sequence, profile_active=metadata['active'])
        window._finish_close = close_observed
        page.loadingChanged.connect(lambda info: context.event('loadingChanged', url=info.url().toString(),
            status=str(info.status()), error_code=info.errorCode(), error_domain=str(info.errorDomain()), error=info.errorString()))
        window.web_view.loadFinished.connect(lambda ok: context.event('loadFinished', ok=ok,
            qt_url=window.web_view.url().toString()))
        page.urlChanged.connect(lambda url: context.event('urlChanged', url=url.toString()))
        page.renderProcessTerminated.connect(lambda status, code: context.event('renderProcessTerminated', status=str(status), code=code))
        interceptor_type = type(window._interceptor)
        original_intercept = interceptor_type.interceptRequest

        def intercept(self, info):
            url = info.requestUrl().toString()
            allowed = window.policy.resource(url)
            context.event('request-interceptor', url=url, method=bytes(info.requestMethod()).decode('ascii', errors='replace'),
                          resource_type=str(info.resourceType()), policy_allows=allowed)
            result = original_intercept(self, info)
            context.event('request-interceptor-complete', url=url, blocked_by_original_policy=not allowed)
            return result

        interceptor_type.interceptRequest = intercept
        page_type = type(page)
        original_console = page_type.javaScriptConsoleMessage
        def console(self, level, message, line, source):
            context.event('javascript-console', level=str(level), message=message, line=line, source=source)
            return original_console(self, level, message, line, source)
        page_type.javaScriptConsoleMessage = console
        return window

    subject.standalone.create_window = create_window
    original_flush = subject.core.QCoreApplication.sendPostedEvents
    def flush_observed(*args, **kwargs):
        context = CURRENT
        if context:
            context.event('Qt-sendPostedEvents-before', event_type=str(args[1]) if len(args) > 1 else 'all',
                          active_profiles=[dict(p) for p in PROFILES.values() if p['active']])
        try:
            return original_flush(*args, **kwargs)
        finally:
            if context:
                context.event('Qt-sendPostedEvents-after', active_profiles=[dict(p) for p in PROFILES.values() if p['active']])
    try:
        subject.core.QCoreApplication.sendPostedEvents = staticmethod(flush_observed)
    except (AttributeError, TypeError):
        # Keep all original Qt behavior even if this binding disallows the observer.
        subject._diagnostic_flush_hook_error = traceback.format_exc()
    handler = subject.server.RequestHandlerClass
    original_parse, original_response, original_header = handler.parse_request, handler.send_response, handler.send_header

    def parse_request(self):
        result = original_parse(self)
        self._observation = CURRENT
        self._observation.event('fixture-http-request', server='foreign' if self.server is subject.foreign else 'own',
            method=self.command, path=self.path, range=getattr(self, 'headers', {}).get('Range'), request_id=id(self))
        return result

    def send_response(self, code, message=None):
        context = getattr(self, '_observation', CURRENT)
        context.event('fixture-http-response', request_id=id(self), status=code, path=getattr(self, 'path', None))
        return original_response(self, code, message)

    def send_header(self, name, value):
        if name.lower() in {'content-type', 'content-length', 'content-range', 'accept-ranges'}:
            getattr(self, '_observation', CURRENT).event('fixture-http-header', request_id=id(self), name=name, value=value)
        return original_header(self, name, value)

    handler.parse_request, handler.send_response, handler.send_header = parse_request, send_response, send_header


SNAPSHOT = r'''JSON.stringify({href:location.href,state:document.readyState,ready:!!document.querySelector('#ready'),
fonts:document.fonts?.status,nativePdfReady:window.nativePdfReady,width:innerWidth,height:innerHeight,
frames:[...document.querySelectorAll('iframe,object')].map(f=>{let r=f.getBoundingClientRect(),doc;
try{doc={href:f.contentDocument?.location.href,state:f.contentDocument?.readyState}}catch(e){doc={error:String(e)}}
return{id:f.id,url:f.src||f.data,rect:{left:r.left,top:r.top,right:r.right,bottom:r.bottom},document:doc}}),
resources:performance.getEntriesByType('resource').map(r=>({name:r.name,start:r.startTime,duration:r.duration,
status:r.responseStatus,transfer:r.transferSize,encoded:r.encodedBodySize}))})'''


def sample(test, label, screenshot=True):
    context = test.observation
    item = {'label': label, 'elapsed': round(time.monotonic() - context.started, 6),
            'qt_url': test.window.web_view.url().toString(), 'foreign_requests': list(test.foreign_requests),
            'dialog_external': list(test.dialogs.external), 'dialog_errors': list(test.dialogs.errors),
            'renderer_pid': test.window.web_view.page().renderProcessPid(),
            'profile_name': test.window.profile.storageName(), 'profile_storage': test.window.profile.persistentStoragePath(),
            'profiles': [dict(p) for p in PROFILES.values()]}
    response = []
    test.window.web_view.page().runJavaScript(SNAPSHOT, lambda value: response.append(value))
    end = time.monotonic() + 3
    while not response and time.monotonic() < end:
        test.app.processEvents()
        time.sleep(0.01)
    try:
        state = json.loads(response[0]) if response and response[0] else {'callback': 'missing-or-empty'}
        item['document'] = state
        image = test.window.web_view.grab().toImage()
        counts = []
        for frame in state.get('frames', []):
            if frame['id'] not in {'localpdf', 'blobpdf'}:
                continue
            rect = frame['rect']
            sx, sy = image.width() / state['width'], image.height() / state['height']
            count = 0
            for y in range(max(0, round(rect['top'] * sy)), min(image.height(), round(rect['bottom'] * sy)), 4):
                for x in range(max(0, round(rect['left'] * sx)), min(image.width(), round(rect['right'] * sx)), 4):
                    color = image.pixelColor(x, y)
                    if color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115:
                        count += 1
            counts.append({'id': frame['id'], 'teal': count})
        item['actual_pdf_roi_pixels'] = counts
        def frames(frame, depth=0):
            if depth > 5:
                return []
            return [{'depth': depth, 'name': frame.name(), 'url': frame.url().toString()}] + [
                value for child in frame.children() for value in frames(child, depth + 1)]
        try:
            item['native_frames'] = frames(test.window.web_view.page().mainFrame())
        except Exception:
            item['frame_observation_error'] = traceback.format_exc()
        if screenshot:
            image_path = context.output / (label + '.png')
            item['screenshot_saved'] = test.window.grab().save(str(image_path))
    except Exception:
        item['observation_error'] = traceback.format_exc()
    context.samples.append(item)
    context.save()
    return item


def run_child(options):
    global CURRENT
    subject_path = options.subject.resolve(strict=True)
    raw = (subject_path / 'backend/tests/test_standalone_runtime.py').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(raw).hexdigest() != TEST_SHA256:
        raise RuntimeError('The original R4 test bytes changed')
    sys.path.insert(0, str(subject_path))
    module = importlib.import_module('backend.tests.test_standalone_runtime')
    original = module.StandaloneRuntimeTests
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    class Observed(original):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            install_observers(cls)

        def setUp(self):
            global CURRENT
            self.observation = Observation(output / self._testMethodName, self._testMethodName)
            CURRENT = self.observation
            os.environ['IMMO_QT_TEST_ARTIFACTS'] = str(self.observation.output)
            super().setUp()
            sample(self, 'after-original-setup', screenshot=False)

        def tearDown(self):
            try:
                sample(self, 'after-original-test')
                if self.observation.original_failures and self._testMethodName == PDF_NAME:
                    # The original 30-second failure has ALREADY been recorded.
                    # These observations never change its result or retry navigation.
                    until = time.monotonic() + (0 if options.local_single else 90)
                    tick = 0
                    while time.monotonic() < until:
                        next_tick = min(until, time.monotonic() + 10)
                        while time.monotonic() < next_tick:
                            self.app.processEvents()
                            time.sleep(0.02)
                        tick += 1
                        sample(self, 'post-failure-%02d' % tick)
            except Exception:
                self.observation.event('observer-error', traceback=traceback.format_exc())
            finally:
                try:
                    super().tearDown()
                finally:
                    self.observation.save()

    class Result(unittest.TextTestResult):
        def addFailure(self, test, err):
            if hasattr(test, 'observation'):
                test.observation.original_failures.append({'type': 'failure', 'traceback': ''.join(traceback.format_exception(*err))})
                test.observation.event('ORIGINAL-FAILURE-RETAINED')
                test.observation.save()
            super().addFailure(test, err)

        def addError(self, test, err):
            if hasattr(test, 'observation'):
                test.observation.original_failures.append({'type': 'error', 'traceback': ''.join(traceback.format_exception(*err))})
                test.observation.save()
            super().addError(test, err)

    suite = unittest.TestSuite(Observed(name) for name in NAMES)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    for context in OBSERVATIONS:
        context.save()
    receipt = {'subject_commit': COMMIT, 'original_test_sha256': TEST_SHA256, 'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
        'original_tests_successful': result.wasSuccessful(), 'original_case_order': list(NAMES),
        'flush_hook_error': getattr(Observed, '_diagnostic_flush_hook_error', None),
        'final_profiles': [dict(profile) for profile in PROFILES.values()], 'python': sys.version, 'platform': sys.platform,
        'machine': platform.machine(), 'loaded_crypto_modules': sorted(name for name in sys.modules if name.startswith(('cryptography', '_ssl'))),
        'postfailure_observation_changes_result': False, 'additional_observation_seconds': 0 if options.local_single else 90}
    write_json(output / 'process-result.json', receipt)
    return 0 if result.wasSuccessful() and result.testsRun == len(NAMES) and not result.skipped else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--local-single', action='store_true', help='One isolated validation process, never the CI diagnostic')
    options = parser.parse_args()
    if options.child:
        return run_child(options)
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rounds = []
    for number in range(1, (1 if options.local_single else 3) + 1):
        command = [sys.executable, '-u', str(Path(__file__).resolve()), '--child', '--subject', str(options.subject.resolve()),
                   '--output', str(output / ('process-%d' % number))] + (['--local-single'] if options.local_single else [])
        with (output / ('process-%d.log' % number)).open('w', encoding='utf-8') as log:
            try:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=450)
                code, timed_out = completed.returncode, False
            except subprocess.TimeoutExpired:
                log.write('DIAGNOSTIC OWNED PROCESS TIMEOUT: failure retained; no successful exit claimed.\n')
                code, timed_out = None, True
        rounds.append({'process': number, 'actual_exit_code': code, 'timed_out': timed_out, 'command': command})
        write_json(output / 'diagnosis-summary.json', {'subject_commit': COMMIT, 'fixed_process_count': 1 if options.local_single else 3,
            'rounds': rounds, 'original_case_order': list(NAMES), 'original_tests_per_process': len(NAMES),
            'any_original_failure_is_a_diagnostic_failure': True, 'acceptance_gate': False})
    return 0 if all(item['actual_exit_code'] == 0 for item in rounds) else 1


if __name__ == '__main__':
    raise SystemExit(main())
