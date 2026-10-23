import { ClipboardList, FileSearch, House, CalendarClock, ReceiptText, MessageSquareText, ChevronDown } from 'lucide-react';

const workflows = [
  { id: 'check', title: 'Unstimmigkeiten prüfen', icon: FileSearch, detail: 'Fristen, fehlende Angaben und widersprüchliche Daten untersuchen.',
    prompt: 'Untersuche Unstimmigkeiten im gewählten Arbeitsbereich. Nutze immo_investigate für Fristen, fehlende Angaben und Konsistenz. Prüfe bei Rechnungen auch die lokale Rechnungsprüfung und Zahlungszuordnung. Suche selbst passende Akten und lies erforderliche Belege und Beziehungen nach. Ordne konkrete Befunde nach Dringlichkeit, verlinke Originale und nenne den untersuchten Umfang sowie nicht geprüfte Teile. Bereite keine doppelten Aufgaben vor.' },
  { id: 'overview', title: 'Akte verstehen', icon: House, detail: 'Mietverhältnisse, Vorgänge und offene Schritte zusammenführen.',
    prompt: 'Erstelle einen verständlichen Aktenüberblick für meinen gewählten Bezug. Finde selbst passende Stammdaten, aktuelle Mietverträge, offene Aufgaben, Schäden und relevante Dokumente. Prüfe die jüngsten Vorgänge und nenne konkrete nächste Schritte mit Quellen. Falls der Bezug nicht eindeutig ist, biete die gefundenen Immobilien oder Parteien mit Anschrift zur Auswahl an.' },
  { id: 'rent', title: 'Zahlungen klären', icon: ReceiptText, detail: 'Forderungen, Zahlungen und Belege nachvollziehbar abgleichen.',
    prompt: 'Hilf mir, Mietzahlungen und offene Forderungen zu klären. Ermittle den passenden Mietvertrag und prüfe Forderungen, Zahlungszuordnungen und Belege für den gewählten Bezug und Zeitraum. Verwende nur geprüfte Fachrechnungen für Summen, unterscheide erfassten Status und tatsächliche Restschuld. Frage nach dem Zeitraum oder Bezug, falls unklar. Keine Mahnung versenden und keine Buchung ausführen.' },
  { id: 'move', title: 'Mieterwechsel vorbereiten', icon: ClipboardList, detail: 'Unterlagen, Übergabe, Zähler und offene Aufgaben durchsehen.',
    prompt: 'Prüfe den anstehenden Mieterwechsel für meinen gewählten Bezug. Suche Vertrag, Einheitsakte, vorhandene Übergabeunterlagen, Wohnungsgeberbestätigung, Zählerbezüge und offene Aufgaben. Unterscheide nachgewiesene Unterlagen von noch zu klärenden Punkten; behaupte bei unvollständiger Suche keine Abwesenheit. Schlage konkrete Schritte vor. Frage nach tatsächlichem Ein- oder Auszugsdatum, wenn benötigt. Bereite gewünschte neue Aufgaben erst nach Prüfung bestehender Aufgaben vor.' },
  { id: 'invoice', title: 'Rechnung vorbereiten', icon: ReceiptText, detail: 'Original prüfen, Zuordnung klären und Rechnungsentwurf erstellen.',
    prompt: 'Prüfe die angehängte Rechnung und vorhandene Rechnungen auf einen möglichen Doppeleintrag. Kläre die Immobilienzuordnung anhand der Belege und bereite einen belegten Rechnungsentwurf vor. Belege alle Beträge im Original und frage fehlende Angaben konkret nach. Noch keine Buchung oder Freigabe ausführen.' },
  { id: 'followup', title: 'Gespräch und Wiedervorlage', icon: MessageSquareText, detail: 'Eine Aktennotiz und eine passende Wiedervorlage vorbereiten.',
    prompt: 'Hilf mir, ein Gespräch als Aktennotiz mit Wiedervorlage festzuhalten. Frage nach Gesprächsinhalt, passender Partei oder Immobilie und gewünschtem Termin, falls diese fehlen. Suche den Aktenbezug selbst. Bereite anschließend eine belegte Aktennotiz und eine getrennte Aufgabe vor; prüfe zuvor passende bestehende Aufgaben.' },
];

export default function AssistantWorkflows({ local, disabled, onChoose }) {
  return <details className="assistant-workflows"><summary><CalendarClock size={15} aria-hidden="true" /> Verwaltungsaufträge<ChevronDown size={15} className="assistant-workflow-chevron" aria-hidden="true" /></summary>
    <p>{local ? 'Die lokale Prüfung untersucht die ausgewählten Akten nach festen Regeln. Für freie Recherche und geführte Abläufe wählen Sie ChatGPT oder Claude.' : 'Wählen Sie einen Auftrag und ergänzen Sie bei Bedarf Bezug oder Zeitraum. Ihre vorhandene Eingabe bleibt erhalten; erst „Senden“ startet den Auftrag.'}</p>
    <div className="assistant-workflow-grid">{(local ? workflows.slice(0, 1) : workflows).map(item => <button key={item.id} type="button" disabled={disabled} onClick={() => onChoose(local ? 'Prüfe meine ausgewählten Akten mit den vorhandenen lokalen Regeln.' : item.prompt)}><item.icon size={19} aria-hidden="true" /><span><strong>{item.title}</strong><small>{local ? 'Fristen, fehlende Angaben und Datumswidersprüche in der Auswahl.' : item.detail}</small></span></button>)}</div>
  </details>;
}
