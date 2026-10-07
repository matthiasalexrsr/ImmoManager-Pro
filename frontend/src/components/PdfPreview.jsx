import { useEffect, useRef, useState } from 'react';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { usePartyText } from '../features/partyWorkspace/text';
import { isOwnUploadUrl, prepareUploadAccess } from '../utils/uploadAccess';

const MAX_PIXELS = 16_777_216;
const MAX_DIMENSION = 8192;
const LOAD_TIMEOUT = 30_000;

export default function PdfPreview({ url, title }) {
  const { text } = usePartyText();
  const [pdf, setPdf] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [zoom, setZoom] = useState('fit');
  const [width, setWidth] = useState(0);
  const [drawing, setDrawing] = useState(false);
  const [pageText, setPageText] = useState(null);
  const [showText, setShowText] = useState(false);
  const viewportRef = useRef(null);
  const canvasHostRef = useRef(null);

  useEffect(() => { setPageInput(String(pageNumber)); }, [pageNumber]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    let destroyed = false;
    let task;
    setPdf(null);
    setError(null);
    const destroy = () => {
      if (destroyed || !task) return;
      destroyed = true;
      void task.destroy().catch(() => {});
    };
    const fail = kind => {
      if (!active) return;
      active = false;
      controller.abort();
      setError(kind);
      destroy();
    };
    const timer = setTimeout(() => fail('timeout'), LOAD_TIMEOUT);
    // Keep the large renderer out of the application startup bundle. Import
    // failures use the same retry path as network/parse failures.
    (async () => {
      try {
        await prepareUploadAccess(url, { signal: controller.signal });
        const { getDocument, GlobalWorkerOptions } = await import('pdfjs-dist');
        if (!active) return;
        GlobalWorkerOptions.workerSrc = workerUrl;
        const base = new URL(import.meta.env.PDFJS_ASSET_PATH, window.location.href).href;
        task = getDocument({
          url, withCredentials: isOwnUploadUrl(url), cMapUrl: `${base}cmaps/`, cMapPacked: true,
          standardFontDataUrl: `${base}standard_fonts/`, wasmUrl: `${base}wasm/`, iccUrl: `${base}iccs/`,
          // Load only the required ranges when the source supports byte ranges.
          disableStream: true, disableAutoFetch: true,
          canvasMaxAreaInBytes: MAX_PIXELS * 4,
        });
        task.onPassword = () => { clearTimeout(timer); fail('password'); };
        const document = await task.promise;
        if (!active) return;
        if (!Number.isInteger(document.numPages) || document.numPages < 1) throw new Error('Empty PDF');
        setPdf(document);
        setPageNumber(current => Math.min(current, document.numPages));
      } catch (reason) {
        fail(reason?.name === 'PasswordException' ? 'password' : reason?.name === 'InvalidPDFException' ? 'invalid' : 'load');
      } finally { clearTimeout(timer); }
    })();
    return () => { active = false; controller.abort(); clearTimeout(timer); destroy(); };
  }, [url, attempt]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const measure = () => setWidth(Math.max(1, viewport.clientWidth - 16));
    measure();
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    observer?.observe(viewport);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  useEffect(() => {
    if (!pdf || !width) return;
    const host = canvasHostRef.current;
    let active = true;
    let page;
    let renderTask;
    setDrawing(true);
    setPageText(null);
    setError(null);
    host.replaceChildren();
    const timer = setTimeout(() => {
      if (!active) return;
      active = false;
      renderTask?.cancel();
      host.replaceChildren();
      setDrawing(false);
      setError('timeout');
    }, LOAD_TIMEOUT);
    (async () => {
      try {
        page = await pdf.getPage(pageNumber);
        if (!active) { page.cleanup(); return; }
        const original = page.getViewport({ scale: 1 });
        if (!(original.width > 0) || !(original.height > 0) || !Number.isFinite(original.width + original.height)) throw new Error('Invalid page size');
        const scale = zoom === 'fit' ? width / original.width : Number(zoom) / 100;
        const css = page.getViewport({ scale });
        const pixelScale = Math.min(scale * (window.devicePixelRatio || 1), MAX_DIMENSION / original.width, MAX_DIMENSION / original.height, Math.sqrt(MAX_PIXELS / original.width / original.height));
        const viewport = page.getViewport({ scale: pixelScale });
        const canvas = window.document.createElement('canvas');
        canvas.width = Math.max(1, Math.floor(viewport.width));
        canvas.height = Math.max(1, Math.floor(viewport.height));
        canvas.style.width = `${css.width}px`;
        canvas.style.height = `${css.height}px`;
        canvas.className = 'pdf-preview-canvas';
        canvas.style.visibility = 'hidden';
        host.replaceChildren(canvas);
        const canvasContext = canvas.getContext('2d');
        if (!canvasContext) throw new Error('Canvas unavailable');
        renderTask = page.render({ canvasContext, viewport, background: '#ffffff' });
        await renderTask.promise;
        if (!active) return;
        canvas.style.visibility = 'visible';
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${title} – ${text.pdfPage} ${pageNumber} ${text.pdfOf} ${pdf.numPages}`);
        setDrawing(false);
        void page.getTextContent().then(content => {
          if (active) setPageText(content.items.map(item => typeof item.str === 'string' ? `${item.str}${item.hasEOL ? '\n' : ' '}` : '').join('').trim());
        }).catch(() => { if (active) setPageText(''); });
      } catch {
        if (!active) return;
        host.replaceChildren();
        setDrawing(false);
        setError('render');
      } finally {
        clearTimeout(timer);
        if (!active) page?.cleanup();
      }
    })();
    return () => { active = false; clearTimeout(timer); renderTask?.cancel(); page?.cleanup(); host.replaceChildren(); };
  }, [pdf, pageNumber, zoom, width, title, text]);

  const goTo = number => {
    if (!pdf || !Number.isInteger(number) || number < 1 || number > pdf.numPages) return;
    setPageNumber(number);
    setPageInput(String(number));
  };
  const errors = { password: text.pdfPassword, invalid: text.pdfInvalid, load: text.pdfLoadFailed, render: text.pdfRenderFailed, timeout: text.pdfTimeout };

  return <section className="pdf-preview" aria-label={text.pdfPreview}>
    {pdf && <div className="pdf-preview-toolbar">
      <button type="button" className="btn btn-sm btn-secondary" disabled={pageNumber <= 1} onClick={() => goTo(pageNumber - 1)} aria-label={text.pdfPrevious}>←</button>
      <form className="pdf-preview-page-form" onSubmit={event => { event.preventDefault(); goTo(Number(pageInput)); }}>
        <label>{text.pdfPage}<input type="number" inputMode="numeric" min="1" max={pdf.numPages} step="1" value={pageInput} onChange={event => setPageInput(event.target.value)} /></label>
        <span>{text.pdfOf} {pdf.numPages}</span>
        <button type="submit" className="btn btn-sm btn-secondary">{text.pdfGo}</button>
      </form>
      <button type="button" className="btn btn-sm btn-secondary" disabled={pageNumber >= pdf.numPages} onClick={() => goTo(pageNumber + 1)} aria-label={text.pdfNext}>→</button>
      <label className="pdf-preview-zoom">{text.pdfZoom}<select value={zoom} onChange={event => setZoom(event.target.value)}>
        <option value="fit">{text.pdfFit}</option>
        {[25, 50, 75, 100, 125, 150, 200, 300].map(value => <option key={value} value={value}>{value} %</option>)}
      </select></label>
      <button type="button" className="btn btn-sm btn-secondary" aria-pressed={showText} onClick={() => setShowText(value => !value)}>{text.pdfText}</button>
    </div>}
    {!error && (!pdf || drawing) && <p className="pdf-preview-message" role="status">{text.pdfLoading}</p>}
    {error && <div className="pdf-preview-message" role="alert"><p>{errors[error]}</p><p>{text.pdfOriginalHelp}</p><button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>{text.retry}</button></div>}
    <div className="pdf-preview-viewport" ref={viewportRef}>
      <div ref={canvasHostRef} hidden={showText || Boolean(error)} />
      {showText && !error && <pre className="pdf-preview-text">{pageText === null ? text.pdfLoading : pageText || text.pdfNoText}</pre>}
    </div>
  </section>;
}
