"""Real Chromium component tests, exclusively with Qt's offscreen platform.

Run with QT_QPA_PLATFORM=offscreen, QT_OPENGL=software and
QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu. No native dialog/external app is opened.
Uses unittest so it also runs in the lean packaging environment without pytest.
"""

import errno
import io
import json
import mimetypes
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch
from urllib.parse import urlsplit


class DialogRecorder:
    def __init__(self, root):
        self.root = root
        self.printed = []
        self.errors = []
        self.external = []
        self.save = str(root / "export.csv")
        self.selected = root / "Auswahl Ä.txt"
        self.selected.write_text("Eigene Dateiauswahl Ä", encoding="utf-8")

    def choose_save_file(self, parent, title, suggested, filters=""):
        return self.save

    def choose_open_files(self, parent, multiple, accepted):
        return [str(self.selected)]

    def confirm_external(self, parent, url):
        self.external.append(url)
        return False

    def confirm_close(self, parent, active_downloads=0):
        return True

    def show_error(self, parent, title, message):
        self.errors.append((title, message))

    def print_document(self, parent, content):
        self.printed.append(content)


@unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0] == "offscreen", "Qt runtime tests require explicit offscreen mode")
class StandaloneRuntimeTests(unittest.TestCase):
    standalone: ClassVar[Any]
    qt: ClassVar[tuple[Any, ...]]
    core: ClassVar[Any]
    gui: ClassVar[Any]
    widgets: ClassVar[Any]
    engine: ClassVar[Any]
    app: ClassVar[Any]
    foreign_requests: ClassVar[list[str]]
    server: ClassVar[ThreadingHTTPServer]
    foreign: ClassVar[ThreadingHTTPServer]
    fixture_pdf: ClassVar[bytes]
    frontend_dist: ClassVar[Path]
    pdfjs_fixture: ClassVar[bytes]

    @classmethod
    def setUpClass(cls):
        from backend import standalone

        cls.standalone = standalone
        cls.qt = standalone.qt_api()
        cls.core, cls.gui, cls.widgets, cls.engine, _, _, _ = cls.qt
        cls.app = cls.widgets.QApplication.instance() or cls.widgets.QApplication([])
        cls.foreign_requests = []
        from reportlab.pdfgen.canvas import Canvas

        pdf = io.BytesIO()
        document = Canvas(pdf, pagesize=(300, 420))
        document.setFillColorRGB(0.09, 0.42, 0.39)
        document.rect(25, 220, 250, 120, fill=1, stroke=0)
        document.setFillColorRGB(1, 1, 1)
        document.setFont("Helvetica-Bold", 18)
        document.drawString(40, 280, "IMMO DESKTOP PDF")
        document.setFillColorRGB(0, 0, 0)
        document.drawString(40, 160, "LOCAL PREVIEW 2026")
        document.showPage()
        document.save()
        cls.fixture_pdf = pdf.getvalue()
        cls.frontend_dist = standalone.ROOT / "frontend/dist"
        renderers = list((cls.frontend_dist / "assets").glob("pdf-*.js"))
        workers = list((cls.frontend_dist / "assets").glob("pdf.worker*.mjs"))
        resources = list((cls.frontend_dist / "pdfjs").glob("*"))
        if len(renderers) == len(workers) == len(resources) == 1:
            module, worker = ("/assets/" + file.name for file in (renderers[0], workers[0]))
            base = "/pdfjs/" + resources[0].name + "/"
            cls.pdfjs_fixture = ('''<!doctype html><meta charset="utf-8"><h1 id="ready">Produktiver PDF-Renderer</h1><canvas id="pdf"></canvas>
                <script type="module">
                import {getDocument,GlobalWorkerOptions} from MODULE;
                GlobalWorkerOptions.workerSrc=WORKER;
                window.renderPdf=async(kind)=>{let task,url;try{
                    url=kind==='blob'?window.URL.createObjectURL(await(await fetch('/fixture.pdf')).blob()):'/fixture.pdf';
                    const base=BASE;
                    task=getDocument({url,withCredentials:false,cMapUrl:base+'cmaps/',cMapPacked:true,standardFontDataUrl:base+'standard_fonts/',
                        wasmUrl:base+'wasm/',iccUrl:base+'iccs/',disableStream:true,disableAutoFetch:true,isEvalSupported:false,canvasMaxAreaInBytes:67108864});
                    const doc=await task.promise,page=await doc.getPage(1),viewport=page.getViewport({scale:1.3});
                    const canvas=document.querySelector('#pdf');canvas.width=viewport.width;canvas.height=viewport.height;
                    const context=canvas.getContext('2d');await page.render({canvasContext:context,viewport,background:'#fff'}).promise;
                    const text=(await page.getTextContent()).items.map(x=>x.str).join(' '),pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
                    let teal=0,dark=0;for(let i=0;i<pixels.length;i+=4){if(pixels[i]<40&&pixels[i+1]>90&&pixels[i+1]<125&&pixels[i+2]>80&&pixels[i+2]<115)teal++;if(pixels[i]<80&&pixels[i+1]<80&&pixels[i+2]<80)dark++;}
                    window.pdfQa={done:true,kind,pages:doc.numPages,text,teal,dark,width:canvas.width,height:canvas.height,nativeWorker:task._worker.port instanceof Worker};
                }catch(e){window.pdfQa={done:true,error:String(e)}}finally{await task?.destroy();if(kind==='blob'&&url)window.URL.revokeObjectURL(url)}};
                </script>'''.replace("MODULE", json.dumps(module)).replace("WORKER", json.dumps(worker)).replace("BASE", json.dumps(base))).encode("utf-8")
        else:
            cls.pdfjs_fixture = b""

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/fixture.pdf":
                    content, media = cls.fixture_pdf, "application/pdf"
                elif path == "/pdfjs-fixture":
                    content, media = cls.pdfjs_fixture, "text/html; charset=utf-8"
                elif path.startswith(("/assets/", "/pdfjs/")):
                    file = (cls.frontend_dist / path.lstrip("/")).resolve()
                    if not file.is_relative_to(cls.frontend_dist.resolve()) or not file.is_file():
                        self.send_error(404)
                        return
                    content = file.read_bytes()
                    media = "text/javascript" if file.suffix in {".js", ".mjs"} else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                elif path == "/font.ttf":
                    content = (standalone.ROOT / "backend/assets/fonts/NotoSans-Regular.ttf").read_bytes()
                    media = "font/ttf"
                else:
                    if self.path == "/foreign":
                        cls.foreign_requests.append(self.path)
                    content = b'''<!doctype html><meta charset="utf-8"><style>@font-face{font-family:NotoTest;src:url(/font.ttf)}body{font-family:NotoTest}</style>
                        <h1 id="ready">Eigene Anwendung</h1>
                        <button id="popup" onclick="let p=window.open('about:blank','_blank'); if(p){p.opener=null;p.location.replace('/popup');}">Dokument</button>
                        <input id="file" type="file">
                        <button id="download" onclick="let a=document.createElement('a');a.href=window.URL.createObjectURL(new Blob(['Betrag;Name\\n12;Pruefung'],{type:'text/csv'}));a.download='Export.csv';a.click();">Export</button>
                        <iframe id="print" srcdoc="<p>Nur Druckrahmen</p>"></iframe>'''
                    media = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", media)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # Renderer-error/close tests deliberately abort requests.
                    pass

            def log_message(self, *_):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.foreign = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        for server in (cls.server, cls.foreign):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.foreign):
            server.shutdown()
            server.server_close()
        cls.app.processEvents()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="immo-qt-offscreen-")
        self.root = Path(self.temp.name)
        self.dialogs = DialogRecorder(self.root)
        self.args = SimpleNamespace(host="127.0.0.1", port=self.server.server_port, no_browser=True,
            mode="standalone", software_rendering=True, seed=False, testversion=False, no_upgrade=True)
        self.open_fixture_window()

    def open_fixture_window(self):
        self.window = self.standalone.create_window(self.args, self.root, dialogs=self.dialogs, start_session=False)
        self.window.show()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        loaded = []
        self.window.web_view.loadFinished.connect(lambda ok: loaded.append(ok))
        self.window.web_view.setUrl(self.core.QUrl(self.url))
        self.spin(lambda: bool(loaded) and loaded[-1] and self.javascript(
            "location.href === " + json.dumps(self.url + "/")
            + " && document.readyState === 'complete' && Boolean(document.querySelector('#ready'))"))
        self.window._ready = True
        self.window.page_loaded(self.window.web_view, True)
        self.assertIs(self.window._stack.currentWidget(), self.window.tabs)
        self.window.activateWindow()
        self.window.web_view.setFocus()
        # Chromium receives the new viewport only after the stack switches.
        # Wait for layout/paint before generating trusted mouse gestures.
        from PySide6.QtTest import QTest
        QTest.qWait(350)
        self.spin(lambda: self.javascript("document.fonts.status === 'loaded'"))

    def close_fixture_window(self):
        profile_destroyed = []
        self.window.profile.destroyed.connect(lambda *_: profile_destroyed.append(True))
        self.window._finish_close()
        self.app.processEvents()
        self.core.QCoreApplication.sendPostedEvents(None, self.core.QEvent.Type.DeferredDelete)
        self.window.deleteLater()
        self.core.QCoreApplication.sendPostedEvents(None, self.core.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.spin(lambda: bool(profile_destroyed), timeout=10)

    def tearDown(self):
        self.close_fixture_window()
        # Chromium flushes persistent preferences asynchronously after profile
        # destruction; confirm the real files unlock instead of ignoring them.
        end = time.monotonic() + 10
        while True:
            try:
                self.temp.cleanup()
                break
            except OSError as error:
                transient = (isinstance(error, PermissionError) or getattr(error, "winerror", None) == 145
                             or error.errno == errno.ENOTEMPTY)
                if not transient or time.monotonic() >= end:
                    raise
                self.core.QCoreApplication.sendPostedEvents(None, self.core.QEvent.Type.DeferredDelete)
                self.app.processEvents()
                time.sleep(0.05)

    def spin(self, predicate, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Qt offscreen condition timed out")

    def javascript(self, code):
        response = []
        self.window.web_view.page().runJavaScript(code, lambda value: response.append(value))
        self.spin(lambda: bool(response))
        return response[0]

    def click(self, selector):
        from PySide6.QtTest import QTest

        point = json.loads(self.javascript("JSON.stringify((()=>{let r=document.querySelector(" + json.dumps(selector) + ").getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};})())"))
        target = self.window.web_view.focusProxy() or self.window.web_view
        QTest.mouseClick(target, self.core.Qt.MouseButton.LeftButton, self.core.Qt.KeyboardModifier.NoModifier,
                         self.core.QPoint(round(point["x"]), round(point["y"])))
        self.app.processEvents()

    def test_profile_settings_native_font_and_remote_request_blocking(self):
        self.assertIn("Noto", self.app.font().family())
        self.assertIn("Noto", self.window.profile.settings().fontFamily(self.engine.QWebEngineSettings.FontFamily.SansSerifFont))
        self.assertFalse(self.window.profile.isOffTheRecord())
        self.assertTrue(Path(self.window.profile.persistentStoragePath()).resolve().is_relative_to(self.root.resolve()))
        attributes = self.engine.QWebEngineSettings.WebAttribute
        self.assertTrue(self.window.profile.settings().testAttribute(attributes.PdfViewerEnabled))
        self.assertFalse(self.window.profile.settings().testAttribute(attributes.LocalContentCanAccessFileUrls))
        before = len(self.foreign_requests)
        foreign = f"http://127.0.0.1:{self.foreign.server_port}/foreign"
        self.javascript("window.blocked=false;fetch(" + json.dumps(foreign) + ").then(()=>window.blocked='bad').catch(()=>window.blocked=true);true")
        self.spin(lambda: self.javascript("window.blocked === true"))
        self.assertEqual(len(self.foreign_requests), before)
        sentinel = self.root.name
        committed = self.javascript("(() => {document.querySelector('#ready').dataset.navigationSentinel="
                                    + json.dumps(sentinel) + ";return location.href;})()")
        denied = []
        statuses = self.engine.QWebEngineLoadingInfo.LoadStatus
        def navigation_finished(info):
            if info.url().toString() == foreign and info.status() != statuses.LoadStartedStatus:
                denied.append({"status": info.status(), "error": info.errorCode()})
        self.window.web_view.page().loadingChanged.connect(navigation_finished)
        self.window.web_view.setUrl(self.core.QUrl(foreign))
        self.spin(lambda: bool(denied) and bool(self.dialogs.external))
        self.assertEqual(self.dialogs.external, [foreign])
        self.assertEqual(denied[-1]["status"], statuses.LoadStoppedStatus, denied)
        retained = json.loads(self.javascript("""JSON.stringify({href:location.href,ready:Boolean(document.querySelector('#ready')),
            sentinel:document.querySelector('#ready')?.dataset.navigationSentinel})"""))
        diagnostic = {"qt_url": self.window.web_view.url().toString(), "committed": retained, "loading": denied}
        self.assertEqual(retained["href"], committed, diagnostic)
        self.assertTrue(self.window.policy.local(retained["href"]), diagnostic)
        self.assertTrue(retained["ready"], diagnostic)
        self.assertEqual(retained["sentinel"], sentinel, diagnostic)
        self.assertEqual(len(self.foreign_requests), before)

    def test_explicit_file_selection_populates_real_html_input(self):
        self.click("#file")
        self.spin(lambda: self.javascript("document.querySelector('#file').files.length === 1"))
        self.assertEqual(self.javascript("document.querySelector('#file').files[0].name"), self.dialogs.selected.name)

    def test_blob_download_requires_save_choice_and_finishes(self):
        requests = []
        self.window.profile.downloadRequested.connect(lambda request: requests.append((request.url().toString(), str(request.state()), request.page() is not None)))
        self.javascript("window.jsErrors=[];window.onerror=m=>window.jsErrors.push(m);document.querySelector('#download').addEventListener('click',()=>window.downloadClicked=true);true")
        self.click("#download")
        file = Path(self.dialogs.save)
        try:
            self.spin(lambda: file.is_file() and file.stat().st_size > 0)
        except AssertionError:
            clicked = self.javascript("Boolean(window.downloadClicked)")
            errors = self.javascript("JSON.stringify(window.jsErrors)")
            handler = self.javascript("String(document.querySelector('#download').onclick)")
            self.fail(f"Download failed: clicked={clicked}; requests={requests}; errors={self.dialogs.errors}; js={errors}; handler={handler}")
        self.assertIn("12;Pruefung", file.read_text(encoding="utf-8"))
        self.assertFalse(self.dialogs.errors)

    def test_user_popup_reserves_blank_and_navigates_to_local_document(self):
        self.click("#popup")
        self.spin(lambda: self.window.tabs.count() == 2)
        popup = self.window.tabs.widget(1)
        self.spin(lambda: popup.url().path() == "/popup")
        self.assertIs(popup.page().profile(), self.window.profile)

    def test_download_cancel_does_not_write_a_file(self):
        self.dialogs.save = ""
        states = []
        self.window.profile.downloadRequested.connect(lambda request: request.stateChanged.connect(lambda state: states.append(state)))
        self.click("#download")
        self.spin(lambda: self.engine.QWebEngineDownloadRequest.DownloadState.DownloadCancelled in states)
        self.assertFalse((self.root / "Export.csv").exists())
        self.assertEqual(self.window._downloads, set())
        self.assertFalse(self.dialogs.errors)

    def test_authentication_storage_persists_after_ordered_window_restart(self):
        self.javascript("localStorage.setItem('desktop-test-session','own-profile');true")
        self.close_fixture_window()
        self.open_fixture_window()
        self.assertEqual(self.javascript("localStorage.getItem('desktop-test-session')"), "own-profile")

    def test_subframe_print_uses_frame_pdf_not_application_page(self):
        self.javascript("document.querySelector('#print').contentWindow.print();true")
        self.spin(lambda: bool(self.dialogs.printed), timeout=30)
        from pypdf import PdfReader

        data = self.dialogs.printed[0]
        self.assertTrue(data.startswith(b"%PDF"))
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
        self.assertIn("Nur Druckrahmen", text)
        self.assertNotIn("Eigene Anwendung", text)
        self.assertFalse(self.dialogs.errors)

    def test_renderer_failure_has_visible_error_and_no_browser_fallback(self):
        self.window.renderer_terminated(self.engine.QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus, 99)
        self.assertIn("Desktop-Oberfläche", self.window.last_error)
        self.assertTrue(self.window._retry.isVisible())
        self.assertEqual(self.dialogs.external, [])

    def test_production_pdfjs_worker_renders_local_and_blob_pdf_to_real_pixels(self):
        if not self.pdfjs_fixture:
            self.skipTest("Build frontend/dist before testing the production PDF.js renderer")
        self.window.web_view.setUrl(self.core.QUrl(self.url + "/pdfjs-fixture"))
        self.spin(lambda: self.javascript("typeof window.renderPdf === 'function'"))
        for kind in ("http", "blob"):
            self.javascript("window.pdfQa=null;window.renderPdf(" + json.dumps(kind) + ");true")
            self.spin(lambda: self.javascript("Boolean(window.pdfQa?.done)"), timeout=30)
            result = json.loads(self.javascript("JSON.stringify(window.pdfQa)"))
            self.assertNotIn("error", result, result)
            self.assertEqual(result["pages"], 1)
            self.assertIn("IMMO DESKTOP PDF", result["text"])
            self.assertIn("LOCAL PREVIEW 2026", result["text"])
            self.assertGreater(result["teal"], 20000, result)
            self.assertGreater(result["dark"], 100, result)
            self.assertTrue(result["nativeWorker"], result)
            print("PDFJS_RENDER_VERIFIED " + json.dumps(result), flush=True)
        self.save_artifact("pdfjs-local-blob-preview.png")
        self.assertFalse(self.dialogs.errors)

    def test_builtin_pdf_viewer_displays_local_iframe_and_blob_object(self):
        self.javascript("""document.body.innerHTML='<iframe id="localpdf" style="width:350px;height:500px" src="/fixture.pdf"></iframe><object id="blobpdf" type="application/pdf" style="width:350px;height:500px"></object>';
            window.nativePdfReady=false;fetch('/fixture.pdf').then(r=>r.blob()).then(b=>{window.previewBlob=window.URL.createObjectURL(b);document.querySelector('#blobpdf').data=window.previewBlob;window.nativePdfReady=true});true""")
        self.spin(lambda: self.javascript("window.nativePdfReady === true"))
        last_geometry = {}
        def teal_pixels(view=None):
            # Contract: render the composed standalone window and inspect
            # each visible PDF region. QWidget.grab actively renders widgets;
            # this does not assert what a passive screen capture would show.
            target = view or self.window.web_view
            geometry = None
            if view is None:
                geometry = json.loads(self.javascript("JSON.stringify({width:innerWidth,height:innerHeight,frames:['localpdf','blobpdf'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom}})})"))
                last_geometry.update(geometry)
            # Resolve DOM geometry before capturing so a later JavaScript
            # callback cannot advance the paint represented by this image.
            offset = target.mapTo(self.window, self.core.QPoint(0, 0))
            image = self.window.grab().toImage()
            # Image pixels may differ from logical widget coordinates (DPR).
            sx, sy = image.width() / self.window.width(), image.height() / self.window.height()
            if geometry is None:
                regions = [(max(0, round(offset.x() * sx)), max(0, round(offset.y() * sy)),
                            min(image.width(), round((offset.x() + target.width()) * sx)),
                            min(image.height(), round((offset.y() + target.height()) * sy)))]
            else:
                cx, cy = target.width() / geometry["width"], target.height() / geometry["height"]
                regions = [(max(0, round((offset.x() + r["left"] * cx) * sx)),
                            max(0, round((offset.y() + r["top"] * cy) * sy)),
                            min(image.width(), round((offset.x() + r["right"] * cx) * sx)),
                            min(image.height(), round((offset.y() + r["bottom"] * cy) * sy)))
                           for r in geometry["frames"]]
                self.assertEqual(len(regions), 2)
            counts = []
            for left, top, right, bottom in regions:
                count = 0
                for y in range(top, bottom, 4):
                    for x in range(left, right, 4):
                        color = image.pixelColor(x, y)
                        if color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115:
                            count += 1
                counts.append(count)
            return counts
        try:
            self.spin(lambda: min(teal_pixels()) > 50, timeout=30)
        except AssertionError:
            print("QT_PDF_PLUGIN_GEOMETRY " + json.dumps(last_geometry), flush=True)
            self.save_artifact("qt-pdf-plugin-timeout.png")
            raise
        print("QT_PDF_PLUGIN_GEOMETRY " + json.dumps(last_geometry), flush=True)
        print("QT_PDF_PLUGIN_PIXELS_VERIFIED " + json.dumps(teal_pixels()), flush=True)
        self.save_artifact("qt-pdf-local-iframe-blob-object.png")
        self.javascript("""let button=document.createElement('button');button.id='pdfpopup';button.textContent='PDF öffnen';button.style='position:fixed;left:8px;top:8px;z-index:9999';button.onclick=()=>{window.popupClicked=true;window.open(window.previewBlob,'_blank')};document.body.append(button);true""")
        from PySide6.QtTest import QTest
        QTest.qWait(350)
        self.click("#pdfpopup")
        self.spin(lambda: self.javascript("window.popupClicked === true"))
        self.spin(lambda: self.window.tabs.count() == 2)
        popup = self.window.tabs.widget(1)
        self.spin(lambda: popup.url().toString().startswith("blob:"))
        self.spin(lambda: sum(teal_pixels(popup)) > 100, timeout=30)
        print("QT_PDF_POPUP_PIXELS_VERIFIED " + json.dumps(teal_pixels(popup)), flush=True)
        self.save_artifact("qt-pdf-blob-document-popup.png")
        self.assertFalse(self.dialogs.errors)

    def save_artifact(self, name):
        output = os.environ.get("IMMO_QT_TEST_ARTIFACTS")
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.grab().save(str(directory / name)))


@unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0] == "offscreen", "Native print tests require explicit offscreen mode")
class NativePrintTests(unittest.TestCase):
    standalone: ClassVar[Any]
    core: ClassVar[Any]
    widgets: ClassVar[Any]
    printing: ClassVar[Any]
    pdf: ClassVar[Any]
    app: ClassVar[Any]

    @classmethod
    def setUpClass(cls):
        from backend import standalone

        cls.standalone = standalone
        cls.core, _, cls.widgets, _, _, cls.printing, cls.pdf = standalone.qt_api()
        cls.app = cls.widgets.QApplication.instance() or cls.widgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="immo-native-print-")
        self.root = Path(self.temp.name)
        self.output = self.root / "own-test-printer-output.pdf"
        self.parent = self.widgets.QWidget()
        self.parent.profile = SimpleNamespace(persistentStoragePath=lambda: str(self.root))
        from reportlab.pdfgen.canvas import Canvas

        data = io.BytesIO()
        document = Canvas(data, pagesize=(300, 420))
        for index, color in enumerate(((0.09, 0.42, 0.39), (0.72, 0.12, 0.30))):
            document.setFillColorRGB(*color)
            document.rect(25, 150, 250, 220, fill=1, stroke=0)
            document.setFillColorRGB(1, 1, 1)
            document.setFont("Helvetica-Bold", 22)
            document.drawString(42, 275, "PAGE " + str(index + 1))
            document.showPage()
        document.save()
        self.content = data.getvalue()

    def tearDown(self):
        self.parent.deleteLater()
        self.core.QCoreApplication.sendPostedEvents(None, self.core.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def pdf_printer(self):
        # This remains a genuine Qt QPrinter/QPainter path. Only its destination
        # is forced to our private PDF file before any dialog or painting call.
        from PySide6.QtPrintSupport import QPrinter
        output = str(self.output)
        class PdfOnlyPrinter(QPrinter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                self.setOutputFileName(output)
        return PdfOnlyPrinter

    def test_real_native_print_rasterizes_every_page_into_pdf_printer(self):
        with patch.object(self.printing, "QPrinter", self.pdf_printer()), patch.object(
            self.printing.QPrintDialog, "exec", return_value=self.widgets.QDialog.DialogCode.Accepted
        ) as decision:
            self.standalone.NativeDialogs().print_document(self.parent, self.content)
        decision.assert_called_once()
        self.assertTrue(self.output.read_bytes().startswith(b"%PDF-"))
        document = self.pdf.QPdfDocument()
        try:
            self.assertEqual(document.load(str(self.output)), self.pdf.QPdfDocument.Error.None_)
            self.assertEqual(document.status(), self.pdf.QPdfDocument.Status.Ready)
            self.assertEqual(document.pageCount(), 2)
            counts = []
            for index in range(2):
                image = document.render(index, self.core.QSize(600, 850))
                self.assertFalse(image.isNull())
                color_count = 0
                wrong_color_count = 0
                for y in range(0, image.height(), 3):
                    for x in range(0, image.width(), 3):
                        color = image.pixelColor(x, y)
                        teal = color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115
                        red = 165 < color.red() < 200 and color.green() < 45 and 55 < color.blue() < 95
                        color_count += bool(teal if index == 0 else red)
                        wrong_color_count += bool(red if index == 0 else teal)
                self.assertGreater(color_count, 5000)
                self.assertEqual(wrong_color_count, 0)
                counts.append(color_count)
            print("NATIVE_PRINT_REAL_PAINTER_VERIFIED " + json.dumps({"pages":2,"page_color_samples":counts,"output_bytes":self.output.stat().st_size}), flush=True)
        finally:
            document.close()
            document.deleteLater()

    def test_real_native_print_rejects_invalid_pdf_before_dialog_or_job(self):
        with patch.object(self.printing, "QPrinter", self.pdf_printer()), patch.object(
            self.printing.QPrintDialog, "exec", return_value=self.widgets.QDialog.DialogCode.Accepted
        ) as decision:
            with self.assertRaisesRegex(ValueError, "PDF-Druckansicht"):
                self.standalone.NativeDialogs().print_document(self.parent, b"This is not a PDF document")
        decision.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_real_native_print_cancel_creates_no_output_job(self):
        with patch.object(self.printing, "QPrinter", self.pdf_printer()), patch.object(
            self.printing.QPrintDialog, "exec", return_value=self.widgets.QDialog.DialogCode.Rejected
        ) as decision:
            self.standalone.NativeDialogs().print_document(self.parent, self.content)
        decision.assert_called_once()
        self.assertFalse(self.output.exists())


def load_tests(loader, tests, pattern):
    # Match the actual app lifecycle: Chromium starts before users can print.
    # Qt's native PDF plugin is not initialized correctly in this offscreen
    # environment when standalone QtPdf rendering precedes the first renderer.
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(StandaloneRuntimeTests),
        loader.loadTestsFromTestCase(NativePrintTests),
    ])


if __name__ == "__main__":
    unittest.main()
