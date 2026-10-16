import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import PdfPreview from '../../components/PdfPreview';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import AnnotationSurface from './AnnotationSurface';
import DocxEditor from './DocxEditor';
import InvoiceTakeover from './InvoiceTakeover';
import PlainTextEditor from './PlainTextEditor';
import { blobBase64, downloadVersion, pageNumbers, sourceCommand } from './documentWorkApi';
import './documentWork.css';

const kinds = { highlight: 'Hervorhebung', comment: 'Kommentar', text: 'Textnotiz', freehand: 'Freihand',
  stamp: 'Stempel', drawn_signature: 'Gezeichnete Unterschrift', image_signature: 'Bildunterschrift' };
const tools = { copy: 'Originalgetreue Kopie', flatten: 'Anmerkungen einbetten', rotate: 'Seiten drehen',
  pages: 'Seiten ordnen / entnehmen', insert: 'Seiten einfügen', merge: 'PDFs zusammenführen', split: 'PDF teilen',
  crop: 'Zuschneiden (Ansicht)', forms: 'Formularfelder ausfüllen', redact: 'Inhalt endgültig schwärzen',
  edit_content: 'Inhalt im Rechteck ersetzen', optimize: 'Größe verlustfrei optimieren', ocr: 'OCR-Textschicht', docx_pdf: 'DOCX als PDF ausgeben' };

export default function DocumentWorkbench({ documentId, onClose }) {
  const base = `/documents/${encodeURIComponent(documentId)}/work`;
  const dialog = useRef(null);
  const pending = useRef(null);
  const busyRef = useRef(false);
  const active = useRef(true);
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('work');
  const [session, setSession] = useState(null);
  const [annotations, setAnnotations] = useState([]);
  const [layerRevision, setLayerRevision] = useState(0);
  const [kind, setKind] = useState('highlight');
  const [note, setNote] = useState('');
  const [image, setImage] = useState(null);
  const [area, setArea] = useState(null);
  const [manualArea, setManualArea] = useState('1; 20; 20; 180; 80; 0');
  const [operation, setOperation] = useState('copy');
  const [pages, setPages] = useState('1');
  const [rotation, setRotation] = useState('90');
  const [groups, setGroups] = useState('1;2');
  const [insertAt, setInsertAt] = useState('1');
  const [extraIds, setExtraIds] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [compared, setCompared] = useState(false);
  const [job, setJob] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [versions, setVersions] = useState(null);
  const [history, setHistory] = useState(null);
  const [protocolId, setProtocolId] = useState('');
  const [evidencePurpose, setEvidencePurpose] = useState('original_photo');
  const [protocol, setProtocol] = useState(null);
  const [choices, setChoices] = useState(null);
  const choiceKind = tab === 'evidence' ? 'protocols' : ['insert', 'merge'].includes(operation) ? 'pdfs' : null;
  const canWrite = useCanWrite('/documents');
  const canInvoice = useCanWrite('/invoices');
  useModalDialog(dialog, onClose, true);

  const load = useCallback(async () => {
    const current = api.captureSession();
    const [next, list, log] = await Promise.all([api.get(`${base}/source`), api.get(`${base}/versions`), api.get(`${base}/history`)]);
    current();
    if (!active.current) return;
    setSource(next); setVersions(list); setHistory(log);
    return next;
  }, [base]);

  useEffect(() => {
    active.current = true;
    load().then(next => { if (next) { setAnnotations(next.annotations); setLayerRevision(next.layer_revision); } })
      .catch(failure => { if (active.current) setError(failure.message); });
    const close = () => onClose();
    window.addEventListener('workspace-logout', close);
    return () => { active.current = false; window.removeEventListener('workspace-logout', close); };
  }, [load, onClose]);

  const send = useCallback(async request => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    const current = api.captureSession();
    try {
      const result = await api.post(request.path, request.payload);
      current();
      if (!active.current) return;
      pending.current = null;
      request.success?.(result);
    } catch (failure) { if (active.current) setError(failure.message); }
    finally { busyRef.current = false; if (active.current) setBusy(false); }
  }, []);

  const perform = useCallback((path, payload, success) => {
    if (pending.current || busyRef.current) return;
    const request = { path, payload, success };
    pending.current = request;
    void send(request);
  }, [send]);

  useEffect(() => {
    let live = true;
    setChoices(null);
    if (!choiceKind || !source) return;
    const current = api.captureSession();
    api.get(`${base}/choices/${choiceKind}`).then(result => { current(); if (live) setChoices(result); })
      .catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [base, choiceKind, source]);

  const moreChoices = async () => {
    try {
      const current = api.captureSession();
      const result = await api.get(`${base}/choices/${choiceKind}?after=${encodeURIComponent(choices.next_after)}`); current();
      if (active.current) setChoices(previous => ({ ...result, items: [...previous.items, ...result.items] }));
    } catch (failure) { if (active.current) setError(failure.message); }
  };

  const refresh = useCallback(() => { void load().catch(failure => { if (active.current) setError(failure.message); }); }, [load]);
  const recover = async sessionId => {
    try {
      const current = api.captureSession();
      const restored = await api.get(`${base}/sessions/${sessionId}`); current();
      if (active.current) setSession(restored);
    } catch (failure) { if (active.current) setError(failure.message); }
  };
  const getMore = async (collection, cursor) => {
    try {
      const current = api.captureSession();
      const result = await api.get(`${base}/${collection}?${collection === 'versions' ? 'before' : 'after'}=${encodeURIComponent(cursor)}`);
      current();
      if (active.current) (collection === 'versions' ? setVersions : setHistory)(previous => ({ ...result, items: [...previous.items, ...result.items] }));
    } catch (failure) { if (active.current) setError(failure.message); }
  };
  const startExport = async () => {
    setError(null);
    try {
      const current = api.captureSession();
      let options = {};
      if (['rotate', 'pages'].includes(operation)) options.pages = pageNumbers(pages);
      if (operation === 'rotate') options.degrees = Number(rotation);
      if (operation === 'insert') options.at = Number(insertAt) - 1;
      if (operation === 'split') options.groups = groups.split(';').map(pageNumbers);
      if (['crop', 'redact', 'edit_content'].includes(operation)) {
        if (!area) throw new Error('Bitte einen Bereich auf der PDF-Seite aufziehen oder Koordinaten übernehmen.');
        options.regions = [{ page: area.page, rect: area.rect, text: note }];
      }
      if (operation === 'edit_content') options.explicit_content_mode = confirmed;
      if (operation === 'redact' && !confirmed) throw new Error('Bitte die irreversible Schwärzung bestätigen.');
      if (operation === 'forms') options.fields = (inspection?.forms || []).filter(field => !field.read_only).map(field => ({
        page: field.page, name: field.name, xref: field.xref,
        value: formValues[`${field.page}:${field.xref ?? field.name}`] ?? field.value }));
      const sources = [];
      if (['insert', 'merge'].includes(operation)) {
        for (const identifier of extraIds.split(',').map(value => value.trim()).filter(Boolean)) {
          const extra = await api.get(`/documents/${encodeURIComponent(identifier)}/work/source`);
          current();
          if (!extra.version) throw new Error('Zusatz-PDF bitte zuerst archivieren.');
          sources.push({ document_id: identifier, version_id: extra.version.id, sha256: extra.sha256 });
        }
      }
      current();
      perform(`${base}/exports`, { ...sourceCommand(source), operation, options, sources }, result => { setJob(result); refresh(); });
    } catch (failure) { setError(failure.message); }
  };
  const versionDownload = (id, versionId, name) => {
    void downloadVersion(id, versionId, name).catch(failure => { if (active.current) setError(failure.message); });
  };
  const chooseArea = () => {
    const parts = manualArea.split(';').map(value => Number(value.trim()));
    if (parts.length !== 6 || parts.some(value => !Number.isFinite(value)) || parts[0] < 1 || ![0, 90, 180, 270].includes(parts[5])) {
      setError('Bitte Seite; links; oben; rechts; unten; Rotation angeben.'); return;
    }
    const selection = { page: parts[0] - 1, rect: parts.slice(1, 5), rotation: parts[5] };
    setArea(selection);
    setAnnotations(previous => [...previous, { ...selection, kind, text: note,
      points: ['freehand', 'drawn_signature'].includes(kind) ? [selection.rect.slice(0, 2), selection.rect.slice(2)] : [],
      image_base64: kind === 'image_signature' ? image : null }]);
  };
  const inspectPdf = async (nextPage = null) => {
    try {
      const current = api.captureSession();
      const result = await api.get(`${base}/pdf-inspection${nextPage === null ? '' : `?start_page=${nextPage}`}`); current();
      if (active.current) setInspection(previous => nextPage === null ? result : { ...result,
        pages: [...previous.pages, ...result.pages], forms: [...previous.forms, ...result.forms],
        signatures: [...previous.signatures, ...result.signatures] });
    } catch (failure) { if (active.current) setError(failure.message); }
  };
  const inspectProtocol = async () => {
    try {
      const current = api.captureSession();
      const result = await api.get(`${base}/evidence-protocol/${encodeURIComponent(protocolId)}`); current();
      if (active.current) setProtocol(result);
    } catch (failure) { if (active.current) setError(failure.message); }
  };

  const disabled = !canWrite || busy || Boolean(pending.current);
  const isPdf = source?.inspection.format === 'pdf';
  const isDocx = source?.inspection.format === 'docx';
  return createPortal(<div className="document-work-backdrop"><section className="document-work" role="dialog" aria-modal="true"
    aria-labelledby="document-work-title" tabIndex={-1} ref={dialog}>
    <header><div><h2 id="document-work-title">Dokumentwerkzeuge{source ? ` – ${source.document.title}` : ''}</h2>
      <p>Original bewahren · Änderungen als neue Fassung speichern</p></div><button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button></header>
    {error && <div role="alert"><p>{error}</p><div className="document-work-toolbar">
      {pending.current && <><button className="btn btn-secondary" disabled={busy} onClick={() => send(pending.current)}>Denselben Auftrag wiederholen</button>
        <button className="btn btn-secondary" disabled={busy} onClick={() => { pending.current = null; setError(null); }}>Auftrag verwerfen, Eingaben behalten</button></>}
      <button className="btn btn-secondary" onClick={refresh}>Aktuelle Quelle laden</button></div></div>}
    {!source ? <p role="status">{error ? 'Dokument konnte nicht geladen werden.' : 'Dokument wird geladen …'}</p> : <>
      <p>Datei: {source.filename} · {source.version ? `Archivfassung ${source.version.number}` : 'Noch nicht archiviert'}</p>
      {source.inspection.signature_parts > 0 && <p className="document-work-notice">Das DOCX enthält Signaturteile. Ihre kryptografische Gültigkeit ist nicht geprüft. Eine inhaltlich veränderte Fassung kann diese Signaturen beeinträchtigen; das Original bleibt unverändert.</p>}
      <details><summary>Prüfsumme und Quellbindung</summary><p>SHA-256 <code>{source.sha256}</code></p><p>Dokumentrevision <code>{source.document_revision}</code></p></details>
      <button className="btn btn-secondary" onClick={refresh}>Quelle und Fassungen aktualisieren</button>
      {session && ['docx', 'text'].includes(session.mode) && source.version && (session.version_id !== source.version.id || session.document_revision !== source.document_revision) && <section className="document-work-notice" aria-label="Bearbeitungskonflikt vergleichen">
        <h3>Eine andere Fassung wurde gespeichert</h3><p>Ihr Zwischenstand bleibt in Ihrer Sitzung erhalten. Vergleichen Sie beide Fassungen, bevor Sie ihn auf der aktuellen Basis fortsetzen.</p>
        <div className="document-work-toolbar"><button className="btn btn-secondary" onClick={() => versionDownload(documentId, session.version_id, session.filename)}>Meine Ausgangsfassung herunterladen</button>
          <button className="btn btn-secondary" onClick={() => versionDownload(documentId, source.version.id, source.filename)}>Aktuelle Fassung herunterladen</button></div>
        <label><input type="checkbox" checked={compared} onChange={event => setCompared(event.target.checked)} />Ich habe die Fassungen verglichen und möchte meine Bearbeitung auf der aktuellen Basis fortsetzen.</label>
        <button className="btn btn-primary" disabled={disabled || !compared} onClick={() => perform(`${base}/sessions/${session.session_id}/rebase`, {
          ...sourceCommand(source), session_revision: session.revision, confirmed_comparison: true,
        }, result => { setSession(result); setCompared(false); })}>Nach Vergleich auf aktueller Basis fortsetzen</button>
      </section>}
      {!source.version && <p className="document-work-notice">Die Eingangsdatei muss vor Bearbeitung und Übernahme als unveränderliches Original archiviert werden.
        <button className="btn btn-primary" disabled={disabled} onClick={() => perform(`${base}/archive`, sourceCommand(source), refresh)}>Original jetzt archivieren</button></p>}
      <nav className="document-work-toolbar" aria-label="Dokumentbereiche">{[['work', 'Bearbeiten'], ['invoice', 'Rechnung übernehmen'], ['evidence', 'Übergabenachweis'], ['history', 'Fassungen und Wiederanlauf']].map(([value, label]) =>
        <button type="button" className="btn btn-secondary" aria-pressed={tab === value} key={value} onClick={() => setTab(value)}>{label}</button>)}</nav>
      {tab === 'work' && <>
        {source.inspection.format === 'text' && <>{session?.mode === 'text' ? <PlainTextEditor documentId={documentId} session={session}
          onSession={setSession} onPublished={refresh} disabled={!canWrite} /> : <button className="btn btn-primary" disabled={disabled || !source.version}
          onClick={() => perform(`${base}/sessions`, { ...sourceCommand(source), mode: 'text' }, setSession)}>Text bearbeiten</button>}</>}
        {isDocx && <>{session?.mode === 'docx' ? <DocxEditor key={session.session_id} documentId={documentId} session={session}
          onSession={setSession} onPublished={refresh} disabled={!canWrite} /> : <button className="btn btn-primary" disabled={disabled || !source.version}
          onClick={() => perform(`${base}/sessions`, { ...sourceCommand(source), mode: 'docx' }, setSession)}>DOCX im lokalen Editor öffnen</button>}
          <p>DOCX-Vorlagen können als normale Datei hochgeladen, archiviert und als neue Fassung bearbeitet werden. PDF-Ausgabe benötigt das separat eingerichtete lokale LibreOffice.</p></>}
        {isPdf && <div className="document-work-grid"><div>
          <PdfPreview url={source.document.file_url} title={source.document.title} renderOverlay={surface => <AnnotationSurface
            surface={surface} annotations={annotations} kind={kind} text={note} image={image} disabled={disabled || !session}
            onArea={setArea} onAdd={item => setAnnotations(previous => [...previous, item])} />} />
          <p>Koordinaten: unrotierte PDF-Punkte, Ursprung links oben. Handschrift und Bildunterschriften sind keine kryptografisch geprüfte digitale Signatur.</p>
        </div><aside>
          <h3>Anmerkungen</h3>
          {!session && <button className="btn btn-primary" disabled={disabled || !source.version} onClick={() => perform(`${base}/sessions`, { ...sourceCommand(source), mode: 'annotations' }, setSession)}>Anmerkungen beginnen</button>}
          <label>Anmerkungswerkzeug<select aria-label="Anmerkungswerkzeug" value={kind} onChange={event => setKind(event.target.value)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Text / Stempel<textarea value={note} onChange={event => setNote(event.target.value)} /></label>
          {kind === 'image_signature' && <label>Bildunterschrift (PNG/JPEG)<input type="file" accept="image/png,image/jpeg" onChange={async event => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 5_000_000) { setError('Die Bildunterschrift ist zu groß.'); return; }
            try { const current = api.captureSession(); const encoded = await blobBase64(file); current(); if (active.current) setImage(encoded); }
            catch (failure) { if (active.current) setError(failure.message); }
          }} /></label>}
          <label>Bereich per Tastatur: Seite; links; oben; rechts; unten; Rotation<input value={manualArea} onChange={event => setManualArea(event.target.value)} /></label>
          <button className="btn btn-secondary" disabled={disabled || !session} onClick={chooseArea}>Bereich übernehmen</button>
          <ol>{annotations.map((item, index) => <li key={index}>{kinds[item.kind]} · Seite {item.page + 1} {item.text}
            <button type="button" disabled={disabled} aria-label={`Anmerkung ${index + 1} entfernen`} onClick={() => setAnnotations(previous => previous.filter((_, position) => position !== index))}>Entfernen</button></li>)}</ol>
          <button className="btn btn-primary" disabled={disabled || !session} onClick={() => perform(`${base}/sessions/${session.session_id}/annotations`, {
            ...sourceCommand(source), session_revision: layerRevision,
            annotations: annotations.map(item => Object.fromEntries(Object.entries(item).filter(([key]) => !['author_id', 'created_at', 'modified_by', 'modified_at'].includes(key)))),
          }, result => { setAnnotations(result.annotations); setLayerRevision(result.layer_revision); refresh(); })}>Anmerkungsebene speichern</button>
          <p>„Anmerkungen einbetten“ exportiert die zuletzt gespeicherte Ebene.</p>
          {source.layer_revision !== layerRevision && <section className="document-work-notice"><h4>Die gemeinsame Anmerkungsebene wurde geändert</h4>
            <ul>{source.annotations.map((item, index) => <li key={item.id || index}>Seite {item.page + 1}: {kinds[item.kind]} {item.text}</li>)}</ul>
            <button className="btn btn-secondary" onClick={() => { setAnnotations(source.annotations); setLayerRevision(source.layer_revision); }}>Serverebene übernehmen</button>
            <button className="btn btn-secondary" onClick={() => setLayerRevision(source.layer_revision)}>Eigene Ebene nach Vergleich zur neuen Speicherung vorbereiten</button></section>}
          <button className="btn btn-secondary" onClick={() => inspectPdf()}>Formulare und Signaturen prüfen</button>
          {inspection && <><p>{inspection.signatures.length} Signaturfelder · Gültigkeit: nicht kryptografisch geprüft.</p>
            {inspection.next_page !== null && <button className="btn btn-secondary" onClick={() => inspectPdf(inspection.next_page)}>Weitere Seitenfelder und Signaturen prüfen</button>}
            {inspection.forms.map(field => {
              const key = `${field.page}:${field.xref ?? field.name}`;
              const value = formValues[key] ?? field.value;
              const update = value => setFormValues(previous => ({ ...previous, [key]: value }));
              return <label key={key}>{field.name} (Seite {field.page + 1}){field.read_only && ' · schreibgeschützt'}
                {field.on_value !== undefined ? <input type="checkbox" disabled={disabled || field.read_only}
                  checked={value === true || value === field.on_value || value === String(field.on_value)}
                  onChange={event => update(event.target.checked ? field.on_value : 'Off')} />
                  : field.choices?.length ? <select disabled={disabled || field.read_only} value={value} onChange={event => update(event.target.value)}>
                    <option value="">Bitte auswählen …</option>{field.choices.map(choice => <option key={choice}>{choice}</option>)}</select>
                    : <input disabled={disabled || field.read_only} value={value} onChange={event => update(event.target.value)} />}
              </label>;
            })}</>}
        </aside></div>}
        <h3>Neue Ausgabe erstellen</h3><div className="document-work-toolbar"><label>Ausgabewerkzeug<select aria-label="Ausgabewerkzeug" value={operation} onChange={event => { setOperation(event.target.value); setConfirmed(false); }}>
          {Object.entries(tools).filter(([value]) => isPdf ? value !== 'docx_pdf' : value === 'copy' || (isDocx && value === 'docx_pdf')).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {['rotate', 'pages'].includes(operation) && <label>Seitenfolge (z. B. 3,1-2)<input value={pages} onChange={event => setPages(event.target.value)} /></label>}
          {operation === 'rotate' && <label>Drehung<select value={rotation} onChange={event => setRotation(event.target.value)}>{[90, 180, 270].map(value => <option key={value}>{value}</option>)}</select></label>}
          {operation === 'split' && <label>Teile durch ; trennen (z. B. 1-3;4-6)<input value={groups} onChange={event => setGroups(event.target.value)} /></label>}
          {['insert', 'merge'].includes(operation) && <fieldset><legend>Zusätzliche archivierte PDFs auswählen</legend>
            {choices?.items.map(item => <label key={item.id}><input type="checkbox" checked={extraIds.split(',').includes(item.id)} onChange={event => {
              const selected = extraIds.split(',').filter(Boolean).filter(id => id !== item.id);
              if (event.target.checked) selected.push(item.id); setExtraIds(selected.join(','));
            }} />{item.label}</label>)}
            {choices?.items.length === 0 && <p>Keine weiteren archivierten PDFs vorhanden.</p>}
            {choices?.next_after && <button type="button" className="btn btn-secondary" onClick={moreChoices}>Weitere PDFs laden</button>}
          </fieldset>}
          {operation === 'insert' && <label>Vor Seite<input type="number" min="1" value={insertAt} onChange={event => setInsertAt(event.target.value)} /></label>}
        </div>
        {['crop', 'redact', 'edit_content'].includes(operation) && <p>Ausgewählter Bereich: {area ? `Seite ${area.page + 1}, ${area.rect.map(value => value.toFixed(1)).join(' / ')}` : 'Bitte auf der Seite auswählen.'}</p>}
        {operation === 'crop' && <p>Zuschneiden verändert den sichtbaren Ausschnitt. Es entfernt keine vertraulichen Inhalte.</p>}
        {operation === 'redact' && <p className="document-work-notice">Die neue Ausgabe entfernt den Inhalt im Bereich und baut alle Seiten aus sichtbaren Pixeln neu auf. Textsuche, Formulare, Kommentare und Signaturen werden dabei entfernt. Das archivierte Original bleibt erhalten.</p>}
        {operation === 'edit_content' && <p>Dieser Modus entfernt Inhalt im gewählten Rechteck und setzt den eingegebenen Text ein. Kein automatischer Absatzumbruch des restlichen Dokuments.</p>}
        {['redact', 'edit_content'].includes(operation) && <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Ich bestätige diesen Bearbeitungsmodus für eine neue Ausgabe.</label>}
        <button className="btn btn-primary" disabled={disabled || !source.version} onClick={startExport}>Ausgabeauftrag anlegen</button>
        {job && <div role="status"><p>Ausgabe: {job.state === 'completed' ? 'Fertig' : job.state === 'failed' ? 'Fehlgeschlagen, wiederholbar' : 'Bereit zur Verarbeitung'}{job.error && ` · ${job.error}`}</p>
          {job.state !== 'completed' && <button className="btn btn-secondary" disabled={disabled} onClick={() => perform(`${base}/exports/${job.job_id}/run`, undefined, result => { setJob(result); refresh(); })}>Verarbeiten / fortsetzen</button>}
          {job.outputs.map(output => <button className="btn btn-secondary" key={output.version_id} onClick={() => versionDownload(output.document_id, output.version_id, output.filename)}>Ausgabe herunterladen: {output.filename}</button>)}</div>}
      </>}
      {tab === 'invoice' && <>
        {isPdf && <details><summary>Originalbeleg zum Vergleich anzeigen</summary><PdfPreview url={source.document.file_url} title={source.document.title} /></details>}
        <div className="document-work-toolbar"><button className="btn btn-secondary" disabled={disabled || !source.version}
          onClick={() => perform(`${base}/analysis`, sourceCommand(source), setAnalysis)}>Beleg lokal erkennen</button>
          {analysis && analysis.state !== 'completed' && <button className="btn btn-secondary" disabled={disabled}
            onClick={() => perform(`${base}/analysis/${analysis.job_id}/run`, undefined, result => { setAnalysis(result); setProposal(null); refresh(); })}>Erkennung ausführen / fortsetzen</button>}</div>
        {analysis && <p role="status">{analysis.state === 'completed' ? 'Erkennung gespeichert; bitte alle Angaben prüfen.' : analysis.error || 'Erkennungsauftrag gespeichert.'}</p>}
        {!proposal ? <button className="btn btn-primary" disabled={disabled || !source.version || !canInvoice}
        onClick={() => perform(`${base}/invoice-proposal`, sourceCommand(source), setProposal)}>Erkannte Angaben zur Prüfung öffnen</button>
        : <InvoiceTakeover source={source} proposal={proposal} perform={perform} disabled={disabled || !canInvoice} base={base} />}</>}
      {tab === 'evidence' && <section><h3>Unveränderlichen Übergabenachweis verknüpfen</h3>
        <p>Das Originalfoto oder der unterschriebene Rückscan erhält eine eigene Archividentität und bleibt dem geprüften Protokoll zugeordnet.</p>
        <label>Übergabeprotokoll<select value={protocolId} onChange={event => { setProtocolId(event.target.value); setProtocol(null); }}>
          <option value="">Bitte auswählen …</option>{choices?.items.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        {choices?.next_after && <button type="button" className="btn btn-secondary" onClick={moreChoices}>Weitere Protokolle laden</button>}
        <button className="btn btn-secondary" onClick={inspectProtocol} disabled={!protocolId}>Protokoll prüfen</button>
        {protocol && <><p>Protokoll vom {protocol.protocol.protocol_date} · Vertrag {protocol.protocol.contract_id}</p>
          <label>Nachweisart<select value={evidencePurpose} onChange={event => setEvidencePurpose(event.target.value)}><option value="original_photo">Originalfoto</option><option value="signed_return">Unterschriebene Rückfassung</option></select></label>
          <button className="btn btn-primary" disabled={disabled || !source.version} onClick={() => {
            perform(`${base}/evidence`, { ...sourceCommand(source), protocol_id: protocol.protocol.id,
              expected_protocol_revision: protocol.revision, purpose: evidencePurpose }, refresh);
          }}>Geprüften Nachweis verknüpfen</button></>}
      </section>}
      {tab === 'history' && <>
        <h3>Archivfassungen</h3><ul className="document-work-history">{versions?.items.map(version => <li key={version.id}>Fassung {version.number} · {version.filename} · {version.created_at}
          <p><code>{version.sha256}</code></p><button className="btn btn-secondary" onClick={() => versionDownload(documentId, version.id, version.filename)}>Diese Fassung herunterladen</button></li>)}</ul>
        {versions?.next_before && <button className="btn btn-secondary" onClick={() => getMore('versions', versions.next_before)}>Ältere Fassungen laden</button>}
        <h3>Verlauf und Wiederanlauf</h3><ul className="document-work-history">{history?.items.map(event => <li key={event.id}>
          {({ archive: 'Original archiviert', session: 'Bearbeitungssitzung', export: 'Ausgabeauftrag', analysis: 'Erkennungsauftrag', annotations: 'Anmerkungsebene', invoice_proposal: 'Erkennung geprüft', invoice_taken: 'Rechnung übernommen', evidence: 'Übergabenachweis' })[event.kind]} · {event.created_at}
          {event.kind === 'session' && <button className="btn btn-secondary" disabled={disabled} onClick={() => { void recover(event.resource_id); setTab('work'); }}>Sitzung / Zwischenstand wieder öffnen</button>}
          {event.kind === 'export' && <button className="btn btn-secondary" onClick={() => { setJob(event.payload); setTab('work'); }}>Ausgabeauftrag öffnen</button>}
          {event.kind === 'analysis' && <button className="btn btn-secondary" onClick={() => { setAnalysis(event.payload); setTab('invoice'); }}>Erkennungsauftrag öffnen</button>}
          {event.kind === 'evidence' && <p>{event.payload.purpose === 'signed_return' ? 'Unterschriebene Rückfassung' : 'Originalfoto'} · Protokoll {event.payload.protocol_id} · <code>{event.payload.sha256}</code></p>}
        </li>)}</ul>
        {history?.next_after && <button className="btn btn-secondary" onClick={() => getMore('history', history.next_after)}>Weiteren Verlauf laden</button>}
      </>}
    </>}
  </section></div>, document.body);
}
