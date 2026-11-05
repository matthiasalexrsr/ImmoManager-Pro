"""Standalone Qt/Chromium desktop. Qt is imported only for the selected mode.

Qt APIs: https://doc.qt.io/qt-6.11/qwebenginepage.html
https://doc.qt.io/qt-6.11/qwebengineprofile.html
https://doc.qt.io/qt-6.11/qwebengineview.html
"""

from __future__ import annotations

import json
import os
import queue
import sys
from pathlib import Path

from backend.desktop import ROOT, DesktopSession, _data_directory
from backend.desktop_control import acquire_instance_guard, hold_installation_mutex, instance_key, instance_window
from backend.standalone_policy import (
    LocalOrigin,
    external_link,
    profile_paths,
    suggested_filename,
    validate_engine_environment,
)


class StandaloneUnavailable(RuntimeError):
    pass


def configure_runtime(args):
    """Apply an explicit graphics choice before importing Qt/creating QApplication."""
    validate_engine_environment(os.environ)
    if getattr(args, "software_rendering", False):
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--disable-gpu" not in flags.split():
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
        os.environ["QT_OPENGL"] = "software"


def qt_api():
    """Load the packaged engine without changing sandbox or certificate policy."""
    validate_engine_environment(os.environ)
    if getattr(sys, "frozen", False):
        marker = ROOT / "desktop-runtime.json"
        if sys.platform == "darwin" and not marker.is_file():
            marker = Path(sys.executable).resolve().parent.parent / "Resources/desktop-runtime.json"
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            if metadata.get("schema") != "immomanager-desktop-runtime/1" or metadata.get("engine") != "pyside6-qtwebengine":
                raise ValueError("Invalid desktop runtime marker")
            bundle = Path(sys.executable).resolve().parent
            if sys.platform == "darwin" and metadata.get("layout") == "macos-app":
                bundle = bundle.parent
            for relative in metadata["native_required_files"]:
                path = (bundle / relative).resolve()
                if not path.is_relative_to(bundle) or not path.is_file():
                    raise OSError("Missing desktop runtime component")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise StandaloneUnavailable("Die eigenständige Desktop-Komponente fehlt oder ist beschädigt. Bitte ImmoManager Pro erneut installieren.") from error
    try:
        from PySide6 import QtCore, QtGui, QtPdf, QtPrintSupport, QtWebEngineCore, QtWebEngineWidgets, QtWidgets
    except (ImportError, OSError) as error:
        raise StandaloneUnavailable(
            "Die eigenständige Desktop-Oberfläche konnte nicht geladen werden. Bitte die Installation und die Betriebssystemvoraussetzungen prüfen. Der Browsermodus kann ausdrücklich über dessen Startmenüeintrag gewählt werden."
        ) from error
    return QtCore, QtGui, QtWidgets, QtWebEngineCore, QtWebEngineWidgets, QtPrintSupport, QtPdf


def configure_application(application):
    """Use the shipped OFL font, including native controls on minimal systems."""
    if application.property("immomanager-font-ready"):
        return
    _, gui, _, *_ = qt_api()
    application.setApplicationName("ImmoManager Pro")
    application.setOrganizationName("ImmoManager Pro")
    application.setStyle("Fusion")
    family = None
    for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf"):
        file = ROOT / "backend/assets/fonts" / name
        font_id = gui.QFontDatabase.addApplicationFont(str(file))
        if font_id < 0:
            raise StandaloneUnavailable("Die mitgelieferte Desktop-Schrift fehlt oder ist beschädigt. Bitte die Installation reparieren.")
        families = gui.QFontDatabase.applicationFontFamilies(font_id)
        family = family or (families[0] if families else None)
    if not family:
        raise StandaloneUnavailable("Die Desktop-Schrift konnte nicht geladen werden.")
    application.setFont(gui.QFont(family, 10))
    palette = gui.QPalette()
    colors = {"Window": "#F1F6F5", "WindowText": "#173431", "Base": "#FFFFFF", "AlternateBase": "#EAF1EF",
        "Text": "#173431", "Button": "#EAF1EF", "ButtonText": "#173431", "Highlight": "#176B63",
        "HighlightedText": "#FFFFFF", "ToolTipBase": "#FFFFFF", "ToolTipText": "#173431"}
    for role, value in colors.items():
        palette.setColor(getattr(gui.QPalette.ColorRole, role), gui.QColor(value))
    application.setPalette(palette)
    application.setProperty("immomanager-font-ready", True)


class NativeDialogs:
    """Explicit user decisions; tests may supply a noninteractive adapter."""

    def choose_save_file(self, parent, title: str, suggested: str, filters: str = "Alle Dateien (*)") -> str:
        _, _, widgets, *_ = qt_api()
        return widgets.QFileDialog.getSaveFileName(parent, title, suggested, filters)[0]

    def choose_open_files(self, parent, multiple: bool, accepted: list[str]) -> list[str]:
        _, _, widgets, *_ = qt_api()
        if multiple:
            return widgets.QFileDialog.getOpenFileNames(parent, "Dateien auswählen", "", "Alle Dateien (*)")[0]
        file = widgets.QFileDialog.getOpenFileName(parent, "Datei auswählen", "", "Alle Dateien (*)")[0]
        return [file] if file else []

    def confirm_external(self, parent, url: str) -> bool:
        _, _, widgets, *_ = qt_api()
        return widgets.QMessageBox.question(parent, "Externen Link öffnen?",
            "Dieser Link wird außerhalb von ImmoManager Pro im zugeordneten Programm geöffnet:\n\n" + url,
            widgets.QMessageBox.StandardButton.Yes | widgets.QMessageBox.StandardButton.No,
            widgets.QMessageBox.StandardButton.No) == widgets.QMessageBox.StandardButton.Yes

    def confirm_close(self, parent, active_downloads: int = 0) -> bool:
        _, _, widgets, *_ = qt_api()
        text = "ImmoManager Pro wird vollständig beendet. Bitte schließen Sie vorher Ihre Bearbeitung ab."
        if active_downloads:
            text += f"\n\nNoch laufende Downloads: {active_downloads}. Diese werden abgebrochen."
        return widgets.QMessageBox.question(parent, "ImmoManager Pro beenden?", text,
            widgets.QMessageBox.StandardButton.Yes | widgets.QMessageBox.StandardButton.No,
            widgets.QMessageBox.StandardButton.No) == widgets.QMessageBox.StandardButton.Yes

    def show_error(self, parent, title: str, message: str):
        _, _, widgets, *_ = qt_api()
        widgets.QMessageBox.warning(parent, title, message)

    def print_document(self, parent, content: bytes):
        core, gui, widgets, _, _, printing, pdf = qt_api()
        if not content or len(content) > 100 * 1024 * 1024:
            raise ValueError("Die Druckansicht ist leer oder überschreitet die Dateigrenze.")
        document = pdf.QPdfDocument(parent)
        buffer = core.QBuffer(document)
        buffer.setData(core.QByteArray(content))
        buffer.open(core.QIODevice.OpenModeFlag.ReadOnly)
        printer = printing.QPrinter(printing.QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        dialog = printing.QPrintDialog(printer, parent)
        try:
            # The seekable in-memory device loads synchronously. Unlike the
            # filename overload, load(QIODevice) returns void, not an Error.
            document.load(buffer)
            if document.status() != pdf.QPdfDocument.Status.Ready or document.error() != pdf.QPdfDocument.Error.None_:
                raise ValueError("Die PDF-Druckansicht konnte nicht geöffnet werden.")
            if dialog.exec() != widgets.QDialog.DialogCode.Accepted:
                return
            painter = gui.QPainter()
            if not painter.begin(printer):
                raise OSError("Der ausgewählte Drucker konnte nicht geöffnet werden.")
            progress = widgets.QProgressDialog("Dokument wird gedruckt …", "Abbrechen", 0, document.pageCount(), parent)
            progress.setWindowModality(core.Qt.WindowModality.WindowModal)
            try:
                for index in range(document.pageCount()):
                    progress.setValue(index)
                    core.QCoreApplication.processEvents()
                    if progress.wasCanceled():
                        printer.abort()
                        break
                    if index and not printer.newPage():
                        raise OSError("Der Drucker hat den Auftrag abgebrochen.")
                    size = document.pagePointSize(index)
                    pixels = core.QSize(max(1, round(size.width() * 300 / 72)), max(1, round(size.height() * 300 / 72)))
                    if pixels.width() * pixels.height() > 40_000_000:
                        raise ValueError("Die Druckseite überschreitet die Größenbegrenzung.")
                    image = document.render(index, pixels)
                    if image.isNull():
                        raise ValueError("Eine PDF-Seite konnte nicht gerendert werden.")
                    viewport = painter.viewport()
                    scale = min(viewport.width() / image.width(), viewport.height() / image.height())
                    rect = core.QRectF(viewport.x(), viewport.y(), image.width() * scale, image.height() * scale)
                    painter.drawImage(rect, image)
                progress.setValue(document.pageCount())
            finally:
                painter.end()
                progress.close()
        finally:
            document.close()
            buffer.close()
            document.deleteLater()


def create_window(args, data_dir: Path, *, session_factory=DesktopSession, dialogs=None, start_session=True):
    """Create an embedded window; QApplication must already exist.

    serviceReady(str) means only that our privately owned server is ready.
    contentReady(bool) and web_view.loadFinished report Chromium's page result.
    """
    core, gui, widgets, engine, web, _, _ = qt_api()
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
    from PySide6.QtWidgets import QMainWindow
    if widgets.QApplication.instance() is None:
        raise RuntimeError("QApplication muss vor dem Desktopfenster angelegt werden.")
    configure_application(widgets.QApplication.instance())
    origin = LocalOrigin.from_url(f"http://{args.host}:{args.port}")
    storage, cache = profile_paths(data_dir, origin)
    decisions = dialogs or NativeDialogs()

    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            if not origin.resource(info.requestUrl().toString()):
                info.block(True)

    class LocalPage(QWebEnginePage):
        def __init__(self, window, *, popup=False):
            super().__init__(window.profile, window)
            self.window, self.popup = window, popup
            self.permissionRequested.connect(lambda permission: permission.deny())
            self.certificateError.connect(lambda error: error.rejectCertificate())
            self.fileSystemAccessRequested.connect(lambda request: request.reject())
            self.fullScreenRequested.connect(lambda request: request.reject())
            self.registerProtocolHandlerRequested.connect(lambda request: request.reject())

        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            target = url.toString()
            if origin.document(target, blank=self.popup or not is_main_frame):
                return True
            if is_main_frame and external_link(target):
                core.QTimer.singleShot(0, lambda: self.window.open_external(target))
            return False

        def createWindow(self, window_type):
            return self.window.add_document().page()

        def chooseFiles(self, mode, old_files, accepted):
            if not origin.document(self.url().toString(), blank=self.popup):
                return []
            if mode not in (engine.QWebEnginePage.FileSelectionMode.FileSelectOpen,
                            engine.QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple):
                return []
            return decisions.choose_open_files(self.window, mode == engine.QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple, list(accepted))

    class StandaloneWindow(QMainWindow):
        serviceReady = core.Signal(str)
        contentReady = core.Signal(bool)

        def __init__(self):
            super().__init__()
            self.policy, self.dialogs = origin, decisions
            self.session = None
            self.last_error = ""
            self._ready, self._closing, self._closed, self._printing = False, False, False, False
            self._downloads = set()
            self._instance_guard = acquire_instance_guard(data_dir)
            self._install_guard = hold_installation_mutex()
            if self._instance_guard.existed:
                self._instance_guard.close()
                self._install_guard.close()
                instance_window(instance_key(data_dir))
                raise StandaloneUnavailable("ImmoManager Pro läuft für diesen Datenordner bereits. Bitte das vorhandene Fenster verwenden.")
            self.setWindowTitle("ImmoManager Pro")
            screen = widgets.QApplication.primaryScreen().availableGeometry()
            self.resize(min(1440, screen.width() - 40), min(920, screen.height() - 60))
            self.setMinimumSize(min(980, screen.width() - 40), min(650, screen.height() - 60))
            icon = ROOT / "assets/immomanager.ico"
            if icon.is_file():
                self.setWindowIcon(gui.QIcon(str(icon)))
            self.profile = engine.QWebEngineProfile("ImmoManager-" + origin.key, self)
            self.profile.setPersistentStoragePath(str(storage))
            self.profile.setCachePath(str(cache))
            self.profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
            self.profile.setPersistentCookiesPolicy(engine.QWebEngineProfile.PersistentCookiesPolicy.OnlyPersistentCookies)
            self.profile.setPersistentPermissionsPolicy(engine.QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
            self.profile.setPushServiceEnabled(False)
            self._interceptor = Interceptor(self.profile)
            self.profile.setUrlRequestInterceptor(self._interceptor)
            settings = self.profile.settings()
            fonts = engine.QWebEngineSettings.FontFamily
            for family in (fonts.StandardFont, fonts.SansSerifFont):
                settings.setFontFamily(family, widgets.QApplication.font().family())
            attributes = engine.QWebEngineSettings.WebAttribute
            for name, value in (("PdfViewerEnabled", True), ("PluginsEnabled", True),
                ("LocalContentCanAccessRemoteUrls", False), ("LocalContentCanAccessFileUrls", False),
                ("JavascriptCanOpenWindows", False), ("JavascriptCanAccessClipboard", True),
                ("JavascriptCanPaste", False), ("ScreenCaptureEnabled", False)):
                settings.setAttribute(getattr(attributes, name), value)
            settings.setUnknownUrlSchemePolicy(engine.QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
            self.profile.downloadRequested.connect(self._download)
            self._stack = widgets.QStackedWidget(self)
            self.setCentralWidget(self._stack)
            self._status_page = widgets.QWidget(self)
            status_layout = widgets.QVBoxLayout(self._status_page)
            status_layout.setContentsMargins(64, 64, 64, 64)
            status_layout.addStretch()
            self._title = widgets.QLabel("ImmoManager Pro wird gestartet …")
            self._title.setStyleSheet("font-size:25px;font-weight:600;color:#176B63;")
            status_layout.addWidget(self._title)
            self._description = widgets.QLabel("Ihre lokale Anwendung wird vorbereitet.")
            self._description.setWordWrap(True)
            status_layout.addWidget(self._description)
            self._progress = widgets.QProgressBar()
            self._progress.setRange(0, 0)
            status_layout.addWidget(self._progress)
            self._retry = widgets.QPushButton("Oberfläche erneut laden")
            self._retry.setVisible(False)
            self._retry.clicked.connect(self.reload_content)
            status_layout.addWidget(self._retry)
            status_layout.addStretch()
            self._stack.addWidget(self._status_page)
            self.tabs = widgets.QTabWidget(self)
            self.tabs.setTabsClosable(True)
            self.tabs.tabCloseRequested.connect(self.close_document)
            self._stack.addWidget(self.tabs)
            self.web_view = self.add_document(main=True)
            self._build_menu()
            self.statusBar().showMessage("Anwendung wird vorbereitet …")
            self._poll_timer = core.QTimer(self)
            self._poll_timer.setInterval(150)
            self._poll_timer.timeout.connect(self.poll_session)
            self._poll_timer.start()
            if start_session:
                core.QTimer.singleShot(0, self.start_backend)

        def _build_menu(self):
            file_menu = self.menuBar().addMenu("Datei")
            for label, shortcut, callback in (("Drucken …", "Ctrl+P", self.print_current),
                ("Als PDF speichern …", "Ctrl+Shift+S", self.save_current_pdf),
                ("Startprotokoll öffnen", "", self.open_log), ("Beenden", "Ctrl+Q", self.close)):
                action = file_menu.addAction(label)
                action.triggered.connect(callback)
                if shortcut:
                    action.setShortcut(gui.QKeySequence(shortcut))
            view_menu = self.menuBar().addMenu("Ansicht")
            for label, shortcut, callback in (("Zurück", "Alt+Left", lambda: self.current_view().back()),
                ("Vorwärts", "Alt+Right", lambda: self.current_view().forward()),
                ("Neu laden", "Ctrl+R", self.reload_content),
                ("Vergrößern", "Ctrl++", lambda: self.zoom(0.1)),
                ("Verkleinern", "Ctrl+-", lambda: self.zoom(-0.1)),
                ("Originalgröße", "Ctrl+0", lambda: self.current_view().setZoomFactor(1.0))):
                action = view_menu.addAction(label)
                action.setShortcut(gui.QKeySequence(shortcut))
                action.triggered.connect(callback)

        def current_view(self):
            return self.tabs.currentWidget() or self.web_view

        def zoom(self, amount):
            view = self.current_view()
            view.setZoomFactor(max(0.5, min(2.5, view.zoomFactor() + amount)))

        def add_document(self, *, main=False):
            view = web.QWebEngineView(self.tabs)
            page = LocalPage(self, popup=not main)
            view.setPage(page)
            index = self.tabs.addTab(view, "ImmoManager Pro" if main else "Dokument")
            self.tabs.setCurrentIndex(index)
            view.titleChanged.connect(lambda title: self.tabs.setTabText(self.tabs.indexOf(view), (title or "Dokument")[:80]))
            view.printRequested.connect(lambda: self.print_frame(page.mainFrame()))
            view.printRequestedByFrame.connect(self.print_frame)
            view.renderProcessTerminated.connect(self.renderer_terminated)
            page.windowCloseRequested.connect(lambda: self.close_document(self.tabs.indexOf(view)))
            view.loadFinished.connect(lambda ok: self.page_loaded(view, ok))
            return view

        def close_document(self, index):
            if index <= 0:
                if index == 0:
                    self.close()
                return
            view = self.tabs.widget(index)
            self.tabs.removeTab(index)
            view.page().deleteLater()
            view.deleteLater()

        def start_backend(self):
            if self.session is not None:
                return
            try:
                self.session = session_factory(args, data_dir, instance_guard=self._instance_guard)
                self.session.start()
            except Exception as error:
                self.fail("Die Anwendung konnte nicht gestartet werden.", str(error))

        def poll_session(self):
            if self.session is None or self.session.process is None:
                return
            code = self.session.process.poll()
            if code is not None:
                if self._closing:
                    self._finish_close()
                elif not self._closed:
                    self.fail("Die lokale Anwendung wurde beendet.", "Bitte das Startprotokoll prüfen und ImmoManager Pro erneut starten.")
                return
            while True:
                try:
                    event = self.session.events.get_nowait()
                except queue.Empty:
                    break
                if event == "ready" and not self._closing and not self._ready:
                    self._ready = True
                    self.web_view.setUrl(core.QUrl(self.session.url))
                    self.serviceReady.emit(self.session.url)

        def page_loaded(self, view, ok):
            if view is not self.web_view:
                return
            if ok and self._ready and origin.local(view.url().toString()):
                self._stack.setCurrentWidget(self.tabs)
                self.statusBar().showMessage("Anwendung bereit.")
                if self.session is not None:
                    self.session.logger.info("Eigenständige Oberfläche geladen.")
            elif not ok and self._stack.currentWidget() is self._status_page and self._ready:
                self.fail("Die Oberfläche konnte nicht geladen werden.", "Der lokale Dienst läuft. Sie können die Oberfläche erneut laden.")
            self.contentReady.emit(ok)

        def fail(self, title, detail):
            self.last_error = title + " " + detail
            self._title.setText(title)
            self._description.setText(detail)
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._retry.setVisible(self._ready and not self._closing)
            self._stack.setCurrentWidget(self._status_page)
            self.statusBar().showMessage(title)

        def renderer_terminated(self, status, code):
            if self._closing or self._closed:
                return
            if self.session is not None:
                self.session.logger.error("Desktop-Renderer beendet (Status=%s, Code=%s).", status, code)
            self.fail("Die Desktop-Oberfläche wurde beendet.", "Der lokale Dienst bleibt erreichbar. Bitte die Oberfläche erneut laden oder ImmoManager Pro geordnet beenden.")

        def reload_content(self):
            if self._ready and not self._closing:
                self.web_view.setUrl(core.QUrl(origin.url))

        def open_external(self, target):
            if external_link(target) and decisions.confirm_external(self, target):
                if not gui.QDesktopServices.openUrl(core.QUrl(target)):
                    decisions.show_error(self, "Link konnte nicht geöffnet werden", "Für diesen Link ist kein passendes Programm verfügbar.")

        def open_log(self):
            if self.session is not None and self.session.log_path.is_file():
                if not gui.QDesktopServices.openUrl(core.QUrl.fromLocalFile(str(self.session.log_path))):
                    decisions.show_error(self, "Startprotokoll", "Bitte das Startprotokoll im Datenordner unter logs öffnen.")

        def _download(self, request):
            if request.page() is None or not origin.document(request.url().toString()) or self._closing:
                request.cancel()
                return
            try:
                name = suggested_filename(request.downloadFileName())
                destination = decisions.choose_save_file(self, "Datei speichern", name)
                if not destination:
                    request.cancel()
                    return
                path = Path(destination).expanduser().absolute()
                request.setDownloadDirectory(str(path.parent))
                request.setDownloadFileName(path.name)
                self._downloads.add(request)
                request.stateChanged.connect(lambda state: self._download_state(request, state))
                request.accept()
                self.statusBar().showMessage("Datei wird gespeichert …")
            except Exception as error:
                request.cancel()
                decisions.show_error(self, "Datei speichern", str(error))

        def _download_state(self, request, state):
            states = engine.QWebEngineDownloadRequest.DownloadState
            if state in (states.DownloadCompleted, states.DownloadCancelled, states.DownloadInterrupted):
                self._downloads.discard(request)
                if state == states.DownloadCompleted:
                    self.statusBar().showMessage("Datei gespeichert.", 10000)
                elif state == states.DownloadInterrupted and not self._closing:
                    decisions.show_error(self, "Download unterbrochen", request.interruptReasonString())

        def print_current(self):
            self.print_frame(self.current_view().page().mainFrame())

        def print_frame(self, frame):
            if self._printing or self._closing or not origin.document(frame.url().toString(), blank=True):
                return
            self._printing = True

            def prepared(content):
                try:
                    decisions.print_document(self, bytes(content))
                except Exception as error:
                    decisions.show_error(self, "Drucken", str(error))
                finally:
                    self._printing = False

            frame.printToPdf(prepared)

        def save_current_pdf(self):
            frame = self.current_view().page().mainFrame()
            if not self._ready or not origin.document(frame.url().toString()):
                return
            destination = decisions.choose_save_file(self, "Druckansicht als PDF speichern", "Dokument.pdf", "PDF (*.pdf)")
            if destination and not self._printing:
                self._printing = True

                def prepared(content):
                    try:
                        data = bytes(content)
                        if not data:
                            raise ValueError("Die PDF-Druckansicht konnte nicht erzeugt werden.")
                        file = core.QSaveFile(str(Path(destination).absolute()))
                        if not file.open(core.QIODevice.OpenModeFlag.WriteOnly) or file.write(data) != len(data) or not file.commit():
                            raise OSError("Die PDF-Datei konnte nicht gespeichert werden.")
                        self.statusBar().showMessage("PDF-Datei gespeichert.", 10000)
                    except Exception as error:
                        decisions.show_error(self, "PDF speichern", str(error))
                    finally:
                        self._printing = False

                frame.printToPdf(prepared)

        def closeEvent(self, event):
            if self._closed:
                event.accept()
                return
            event.ignore()
            if self._printing:
                decisions.show_error(self, "Druckvorgang läuft", "Bitte den Druckvorgang abschließen oder im Druckdialog abbrechen.")
                return
            running = self.session is not None and self.session.process is not None and self.session.process.poll() is None
            if running:
                if self._closing or not decisions.confirm_close(self, len(self._downloads)):
                    return
                self._closing = True
                for request in list(self._downloads):
                    request.cancel()
                self.fail("ImmoManager Pro wird beendet …", "Laufende Vorgänge werden abgeschlossen. Dieses Fenster schließt sich anschließend automatisch.")
                assert self.session is not None
                self.session.stop()
            else:
                self._finish_close()

        def _finish_close(self):
            if self._closed:
                return
            self._closed = True
            self._poll_timer.stop()
            while self.tabs.count():
                view = self.tabs.widget(0)
                self.tabs.removeTab(0)
                view.stop()
                view.page().deleteLater()
                view.deleteLater()
            self.profile.deleteLater()
            if self.session is not None:
                self.session.close()
            self._instance_guard.close()
            self._install_guard.close()
            self.close()

    return StandaloneWindow()


def main(args):
    configure_runtime(args)
    core, _, widgets, *_ = qt_api()
    application = widgets.QApplication.instance() or widgets.QApplication(sys.argv[:1])
    configure_application(application)
    window = create_window(args, _data_directory(args))
    instance_window(instance_key(_data_directory(args)), int(window.winId()))
    window.show()
    # The parent pipe closes automatically if this process crashes, so its
    # private backend still performs the same graceful EOF shutdown.
    result = application.exec()
    window._finish_close()
    core.QCoreApplication.sendPostedEvents(None, core.QEvent.Type.DeferredDelete)
    window.deleteLater()
    core.QCoreApplication.sendPostedEvents(None, core.QEvent.Type.DeferredDelete)
    return result
