//
// Skript für den Mietvertrag‑Wizard
//
// Dieses Skript steuert die Navigation zwischen den einzelnen Schritten,
// sammelt die eingegebenen Daten in einem Objekt und generiert daraus
// den Vertragstext. Zudem ermöglicht es den Export des Vertrags als
// herunterladbare Textdatei.

document.addEventListener('DOMContentLoaded', () => {
    const steps = Array.from(document.querySelectorAll('.step'));
    const progressItems = Array.from(document.querySelectorAll('.progressbar li'));

    // LocalStorage Key
    const STORAGE_KEY = 'mietvertragWizardFormState_v2';

    // ---------- Eingabe-Hilfen (de-DE) ----------
    const DATE_RE = /^\d{2}\.\d{2}\.\d{4}$/;

    function parseDeMoney(str) {
        const s = (str || '').toString().trim();
        if (!s) return '';
        const cleaned = s.replace(/\s/g, '').replace(/€/g, '');
        const raw = cleaned.replace(/\./g, '').replace(/,/g, '.');
        if (!/^[-+]?\d*(\.\d+)?$/.test(raw)) return '';
        return raw;
    }

    function formatDeMoney(numStr) {
        if (numStr === '' || numStr == null) return '';
        const n = Number(numStr);
        if (!isFinite(n)) return '';
        return new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
    }

    function attachMoneyBehavior(el) {
        el.addEventListener('blur', () => {
            const parsed = parseDeMoney(el.value);
            if (!parsed) return;
            el.value = formatDeMoney(parsed);
        });
    }

    function attachDateMask(el) {
        el.addEventListener('input', () => {
            let v = el.value.replace(/[^0-9]/g, '');
            if (v.length > 8) v = v.slice(0, 8);
            const parts = [];
            if (v.length >= 2) parts.push(v.slice(0,2));
            if (v.length >= 4) parts.push(v.slice(2,4));
            if (v.length > 4) parts.push(v.slice(4));
            el.value = parts.join('.');
        });
        el.addEventListener('blur', () => {
            const v = el.value.trim();
            if (!v) return el.setCustomValidity('');
            if (!DATE_RE.test(v)) el.setCustomValidity('Bitte Datum im Format TT.MM.JJJJ eingeben.');
            else el.setCustomValidity('');
        });
    }

    function initInputBehaviors(root = document) {
        root.querySelectorAll('.money-input').forEach(attachMoneyBehavior);
        root.querySelectorAll('.date-input').forEach(attachDateMask);
    }

    initInputBehaviors();

    // Nach dem Laden: Versuche, gespeicherte Eingaben zu laden und Expertenmodus zu setzen
    try {
        const savedRaw = localStorage.getItem(STORAGE_KEY);
        if (savedRaw) {
            const savedState = JSON.parse(savedRaw);
            applyFormState(savedState);
        }
    } catch (err) {
        console.warn('Konnte gespeicherte Eingaben nicht laden:', err);
    }

    // Expertenmodus-Toggle verdrahten
    const expertToggle = document.getElementById('toggle-expert-mode');
    if (expertToggle) {
        expertToggle.addEventListener('change', (e) => {
            setExpertMode(e.target.checked);
        });
    }

    // Speicher-/Lade-Buttons verdrahten
    const btnSaveLocal = document.getElementById('btn-save-local');
    const btnLoadLocal = document.getElementById('btn-load-local');
    const btnClearLocal = document.getElementById('btn-clear-local');
    const btnExportJson = document.getElementById('btn-export-json');
    const inputImportJson = document.getElementById('input-import-json');

    if (btnSaveLocal) {
        btnSaveLocal.addEventListener('click', () => {
            const state = serializeFormState();
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
                alert('Eingaben wurden lokal im Browser gespeichert.');
            } catch (e) {
                alert('Speichern nicht möglich: ' + e.message);
            }
        });
    }
    if (btnLoadLocal) {
        btnLoadLocal.addEventListener('click', () => {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                alert('Es sind keine gespeicherten Daten vorhanden.');
                return;
            }
            try {
                const state = JSON.parse(raw);
                applyFormState(state);
                alert('Gespeicherte Eingaben wurden geladen.');
            } catch (e) {
                alert('Die gespeicherten Daten konnten nicht gelesen werden.');
            }
        });
    }
    if (btnClearLocal) {
        btnClearLocal.addEventListener('click', () => {
            localStorage.removeItem(STORAGE_KEY);
            alert('Gespeicherte Formulardaten wurden gelöscht.');
        });
    }
    if (btnExportJson) {
        btnExportJson.addEventListener('click', () => {
            const state = serializeFormState();
            const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'mietvertrag-eingaben.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }
    if (inputImportJson) {
        inputImportJson.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (evt) => {
                try {
                    const state = JSON.parse(evt.target.result);
                    applyFormState(state);
                    alert('JSON-Datei wurde geladen und angewendet.');
                } catch (err) {
                    alert('Die JSON-Datei konnte nicht verarbeitet werden.');
                }
            };
            reader.readAsText(file, 'utf-8');
            // Reset, damit dieselbe Datei erneut gewählt werden kann
            e.target.value = '';
        });
    }

    /**
     * Versetzt die Anwendung in den Expertenmodus oder zurück.
     * Wenn persist = true, wird die Einstellung im localStorage gespeichert.
     * @param {boolean} enabled
     * @param {boolean} persist
     */
    function setExpertMode(enabled, persist = true) {
        if (enabled) {
            document.body.classList.add('expert-mode');
        } else {
            document.body.classList.remove('expert-mode');
        }
        const toggleEl = document.getElementById('toggle-expert-mode');
        if (toggleEl) {
            toggleEl.checked = !!enabled;
        }
        if (persist) {
            // Speichere das Flag im State, ohne andere Felder zu überschreiben
            try {
                const raw = localStorage.getItem(STORAGE_KEY);
                let state = raw ? JSON.parse(raw) : { fields: {} };
                state.expertMode = !!enabled;
                localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
            } catch (e) {
                console.warn('Konnte Expertenmodus nicht speichern:', e);
            }
        }
    }

    /**
     * Erfasst alle Eingabefelder des Formulars und gibt ein State‑Objekt zurück.
     * Dieses Objekt enthält die Werte der Felder sowie den Expertenmodus.
     */
    function serializeFormState() {
        const state = { fields: {}, expertMode: document.body.classList.contains('expert-mode'), meta: {} };
        state.meta.vermieterCount = document.querySelectorAll('#vermieter-list .vermieter-block').length;
        state.meta.mieterCount = document.querySelectorAll('#mieter-list .mieter-block').length;
        state.meta.staffelCount = document.querySelectorAll('#staffel-list .staffel-row').length;

        const elements = document.querySelectorAll('input, select, textarea');
        elements.forEach(el => {
            const key = el.id || el.name;
            if (!key) return;
            const entry = (el.type === 'checkbox' || el.type === 'radio')
                ? { type: el.type, checked: el.checked }
                : { type: el.type || 'text', value: el.value };

            const cur = state.fields[key];
            if (cur === undefined) state.fields[key] = entry;
            else if (Array.isArray(cur)) cur.push(entry);
            else state.fields[key] = [cur, entry];
        });
        return state;
    }

    /**
     * Stellt zuvor gespeicherte Eingaben wieder im Formular her.
     * @param {Object} state
     */
    function applyFormState(state) {
        if (!state || !state.fields) return;

        const meta = state.meta || {};
        const ensure = (btnId, selector, target) => {
            const btn = document.getElementById(btnId);
            if (!btn) return;
            while (document.querySelectorAll(selector).length < target) btn.click();
        };
        ensure('add-vermieter', '#vermieter-list .vermieter-block', meta.vermieterCount || 1);
        ensure('add-mieter', '#mieter-list .mieter-block', meta.mieterCount || 1);
        if (document.getElementById('staffel-list')) ensure('add-staffel', '#staffel-list .staffel-row', meta.staffelCount || 1);

        Object.keys(state.fields).forEach(key => {
            const val = state.fields[key];
            const byId = document.getElementById(key);
            const byName = document.getElementsByName(key);
            const targets = [];
            if (byId) targets.push(byId);
            else if (byName && byName.length) targets.push(...byName);
            if (!targets.length) return;

            const applyEntry = (el, entry) => {
                if (entry.type === 'checkbox' || entry.type === 'radio') el.checked = !!entry.checked;
                else el.value = entry.value != null ? entry.value : '';
            };

            if (Array.isArray(val)) {
                val.forEach((entry, i) => { if (targets[i]) applyEntry(targets[i], entry); });
            } else {
                applyEntry(targets[0], val);
            }
        });

        if (typeof state.expertMode === 'boolean') setExpertMode(state.expertMode, false);
        initInputBehaviors();

        // Conditional UI refresh
        const mt = document.getElementById('mietzeit-art');
        if (mt) mt.dispatchEvent(new Event('change'));
        const mh = document.getElementById('mieterhoehung');
        if (mh) mh.dispatchEvent(new Event('change'));
        const ka = document.getElementById('kuendigungsausschluss-check');
        if (ka) ka.dispatchEvent(new Event('change'));
    }

    // Hilfsfunktion zum Anzeigen eines bestimmten Schritts
    function showStep(index) {
        steps.forEach((step, i) => {
            step.classList.toggle('active', i === index);
        });
        progressItems.forEach((item, i) => {
            if (i <= index) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    }

    // Speichert die Formulardaten
    const formData = {};

    // Dynamische Personenfelder hinzufügen
    // Vermieter hinzufügen
    const addVermieterBtn = document.getElementById('add-vermieter');
    if (addVermieterBtn) {
        addVermieterBtn.addEventListener('click', () => {
            const list = document.getElementById('vermieter-list');
            const firstBlock = list.querySelector('.vermieter-block');
            const clone = firstBlock.cloneNode(true);
            // Berechne neuen Index (nicht unbedingt genutzt, aber für eventuelle zukünftige Logik)
            const newIndex = list.querySelectorAll('.vermieter-block').length + 1;
            clone.setAttribute('data-index', newIndex);
            // Leere alle Eingabefelder im Clone
            clone.querySelectorAll('input').forEach(input => {
                input.value = '';
            });
            list.appendChild(clone);
            initInputBehaviors(clone);
        });
    }
    // Mieter hinzufügen
    const addMieterBtn = document.getElementById('add-mieter');
    if (addMieterBtn) {
        addMieterBtn.addEventListener('click', () => {
            const list = document.getElementById('mieter-list');
            const firstBlock = list.querySelector('.mieter-block');
            const clone = firstBlock.cloneNode(true);
            const newIndex = list.querySelectorAll('.mieter-block').length + 1;
            clone.setAttribute('data-index', newIndex);
            clone.querySelectorAll('input').forEach(input => {
                input.value = '';
            });
            list.appendChild(clone);
            initInputBehaviors(clone);
        });
    }

    // Verarbeitung der Buttons
    document.querySelectorAll('button.next').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const nextStep = parseInt(e.target.getAttribute('data-next'), 10) - 1;
            // Bei Wechsel zur Zusammenfassung (letzter Schritt) Daten sammeln und Vertrag generieren.
            // In der neuen Struktur ist die Zusammenfassung die 8. Etappe (Index 7).
            if (nextStep === 7) {
                collectFormData();
                generateContract();
            }
            showStep(nextStep);
        });
    });
    document.querySelectorAll('button.prev').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const prevStep = parseInt(e.target.getAttribute('data-prev'), 10) - 1;
            showStep(prevStep);
        });
    });

    // Mietvertragsart steuert zusätzliche Felder
    const mietzeitArtSelect = document.getElementById('mietzeit-art');
    mietzeitArtSelect.addEventListener('change', () => {
        document.getElementById('befristet-field').style.display = mietzeitArtSelect.value === 'befristet' ? 'block' : 'none';
        // Kündigungsausschluss ist nur bei unbefristet relevant
        document.getElementById('kuendigungsausschluss-field').style.display = mietzeitArtSelect.value === 'unbefristet' ? 'block' : 'none';
    });

    // Befristungsgrund: Auswahl "Sonstiges" zeigt Textfeld
    const grundSelect = document.getElementById('befristet-grund-option');
    const grundText = document.getElementById('befristet-grund-text');
    if (grundSelect && grundText) {
        grundSelect.addEventListener('change', () => {
            if (grundSelect.value === 'Sonstiges') {
                grundText.style.display = 'block';
            } else {
                grundText.style.display = 'none';
                grundText.value = '';
            }
        });
    }

    // Kündigungsausschluss Checkbox
    const kuendigungCheck = document.getElementById('kuendigungsausschluss-check');
    kuendigungCheck.addEventListener('change', () => {
        document.getElementById('kuendigungsausschluss-details').style.display = kuendigungCheck.checked ? 'block' : 'none';
    });

    // Mieterhöhungsart steuert Staffelmiete/Indexmiete Felder
    const mieterhoehungSelect = document.getElementById('mieterhoehung');
    mieterhoehungSelect.addEventListener('change', () => {
        document.getElementById('staffel-details').style.display = mieterhoehungSelect.value === 'staffel' ? 'block' : 'none';
        document.getElementById('index-details').style.display = mieterhoehungSelect.value === 'index' ? 'block' : 'none';
    });

    // Dynamische Staffelmieten verwalten
    const staffelList = document.getElementById('staffel-list');
    const addStaffelBtn = document.getElementById('add-staffel');
    if (addStaffelBtn) {
        addStaffelBtn.addEventListener('click', () => {
            // Erstelle eine neue Reihe basierend auf der ersten Vorlage
            const template = staffelList.querySelector('.staffel-row');
            const clone = template.cloneNode(true);
            // Leere die Eingabefelder im neuen Clone
            clone.querySelectorAll('input').forEach(inp => {
                inp.value = '';
            });
            // Aktualisiere die data-index
            const currentCount = staffelList.querySelectorAll('.staffel-row').length;
            clone.setAttribute('data-index', currentCount + 1);
            staffelList.appendChild(clone);
        });
    }
    // Event-Delegation zum Entfernen einer Staffelmiete
    if (staffelList) {
        staffelList.addEventListener('click', (e) => {
            if (e.target && e.target.classList.contains('remove-staffel')) {
                const rows = staffelList.querySelectorAll('.staffel-row');
                if (rows.length > 1) {
                    const row = e.target.closest('.staffel-row');
                    row.remove();
                } else {
                    // Wenn nur eine Zeile vorhanden ist, Felder einfach leeren
                    const row = e.target.closest('.staffel-row');
                    row.querySelectorAll('input').forEach(inp => inp.value = '');
                }
            }
        });
    }

        // Hilfsfunktion: HTML‑Vertrag mit einfacher Formatierung erstellen
        function generateContractHTML() {
            const v = formData;
            // Hilfsfunktionen zum Formatieren
            const parseDate = (dateStr) => {
                if (!dateStr) return null;
                // Unterstützt deutsches Format TT.MM.JJJJ
                if (dateStr.includes('.')) {
                    const parts = dateStr.split('.');
                    if (parts.length === 3) {
                        const day = parseInt(parts[0], 10);
                        const month = parseInt(parts[1], 10) - 1;
                        const year = parseInt(parts[2], 10);
                        return new Date(year, month, day);
                    }
                }
                // Fallback auf Date-Konstruktor (für ISO-Formate)
                return new Date(dateStr);
            };
            const formatDate = (dateStr) => {
                const d = parseDate(dateStr);
                if (!d || isNaN(d)) return '';
                return d.toLocaleDateString('de-DE');
            };
            const formatCurrency = (val) => {
                if (!val || isNaN(parseFloat(val))) return '';
                return parseFloat(val).toFixed(2).replace('.', ',');
            };
            // Beginne mit einem HTML‑Grundgerüst und professionellen Layout‑Angaben
            let html = '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">';
            html += '<title>Mietvertrag</title>';
            html += '<style>\n';
            // Serifenbetonte Schrift und neutrales Hintergrunddesign
            html += 'body { font-family: "Times New Roman", Times, serif; line-height: 1.5; background: #fdfdfd; color: #000; }\n';
            // Container zentriert mit Rahmen und Schatten für professionellen Eindruck
            html += '.contract-container { max-width: 800px; margin: 0 auto; padding: 40px; background: #fff; border: 1px solid #ddd; box-shadow: 0 0 5px rgba(0,0,0,0.1); }\n';
            // Überschriftenformatierung
            html += 'h1 { text-align: center; font-size: 26px; font-weight: bold; margin-bottom: 30px; }\n';
            html += 'h2 { font-size: 20px; font-weight: bold; margin-top: 25px; margin-bottom: 10px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }\n';
            // Absatzformatierung
            html += 'p { margin: 8px 0; text-align: justify; }\n';
            // Listenformatierung
            html += 'ul { margin: 5px 0 10px 20px; }\n';
            // Partien im oberen Bereich in zwei Spalten
            html += '.party-info { display: flex; justify-content: space-between; margin-bottom: 20px; }\n';
            html += '.party { width: 48%; }\n';
            // Unterschriftenbereiche
            html += '.signature { margin-top: 50px; display: flex; justify-content: space-between; }\n';
            html += '.signature div { width: 30%; text-align: center; }\n';
            html += '.signature-line { margin-top: 60px; border-top: 1px solid #000; }\n';
            html += '</style></head><body><div class="contract-container">';
            html += '<h1>Wohnraum‑Mietvertrag</h1>';
            // Parteien
            html += '<p>Zwischen folgenden Parteien wird folgender Mietvertrag geschlossen:</p>';
            // Darstellung der Parteien in zwei nebeneinander stehenden Blöcken
            html += '<div class="party-info">';
            // Vermieterblock(e)
            html += '<div class="party">';
            html += '<strong>Vermieter:</strong><br>';
            v.vermieter.forEach((ver, idx) => {
                html += '<strong>' + ver.name + '</strong>';
                if (ver.vertreter && ver.vertreter.trim().length > 0) {
                    html += ', vertreten durch ' + ver.vertreter.trim();
                }
                html += '<br>' + ver.strasse + ', ' + ver.plz + ' ' + ver.ort;
                if (ver.telefon) html += '<br>Tel.: ' + ver.telefon;
                if (ver.email) html += '<br>E‑Mail: ' + ver.email;
                if (idx < v.vermieter.length - 1) html += '<br><br>';
            });
            html += '</div>';
            // Mieterblock(e)
            html += '<div class="party">';
            html += '<strong>Mieter:</strong><br>';
            v.mieter.forEach((mi, idx) => {
                html += '<strong>' + mi.name + '</strong>';
                if (mi.geburtsdatum) html += ' (geb. ' + formatDate(mi.geburtsdatum) + ')';
                if (mi.vertreter && mi.vertreter.trim().length > 0) {
                    html += ', vertreten durch ' + mi.vertreter.trim();
                }
                html += '<br>' + mi.strasse + ', ' + mi.plz + ' ' + mi.ort;
                if (mi.telefon) html += '<br>Tel.: ' + mi.telefon;
                if (mi.email) html += '<br>E‑Mail: ' + mi.email;
                if (idx < v.mieter.length - 1) html += '<br><br>';
            });
            html += '</div>';
            html += '</div>';
            // §1
            html += '<div class="section"><h2>§ 1 Mieträume</h2>';
            html += '<p>Der Vermieter vermietet dem Mieter zu Wohnzwecken folgendes Objekt: ' + v.objekt.art + '.</p>';
            html += '<p>Adresse: ' + v.objekt.strasse + ', ' + v.objekt.plz + ' ' + v.objekt.ort + '</p>';
            if (v.objekt.wohnflaeche) html += '<p>Wohnfläche: ca. ' + v.objekt.wohnflaeche + ' m²</p>';
            if (v.objekt.geschoss) html += '<p>Geschoss: ' + v.objekt.geschoss + '</p>';
            if (v.objekt.zimmer) html += '<p>Zimmer: ' + v.objekt.zimmer + '</p>';
            // Weitere Räume
            const raeume = [];
            const pluralize = (num, singular, plural) => (num > 1 ? plural : singular);
            if (parseInt(v.objekt.kueche) > 0) raeume.push(v.objekt.kueche + ' ' + pluralize(v.objekt.kueche, 'Küche', 'Küchen'));
            if (parseInt(v.objekt.bad) > 0) raeume.push(v.objekt.bad + ' ' + pluralize(v.objekt.bad, 'Bad', 'Bäder'));
            if (parseInt(v.objekt.wc) > 0) raeume.push(v.objekt.wc + ' WC' + (v.objekt.wc > 1 ? 's' : ''));
            if (parseInt(v.objekt.keller) > 0) raeume.push(v.objekt.keller + ' Keller');
            if (parseInt(v.objekt.boden) > 0) raeume.push(v.objekt.boden + ' Bodenraum' + (v.objekt.boden > 1 ? 'e' : ''));
            if (parseInt(v.objekt.abstell) > 0) raeume.push(v.objekt.abstell + ' Abstellraum' + (v.objekt.abstell > 1 ? 'e' : ''));
            if (parseInt(v.objekt.balkon) > 0) raeume.push(v.objekt.balkon + ' Balkon/Terrasse');
            if (parseInt(v.objekt.sonstige) > 0) raeume.push(v.objekt.sonstige + ' sonstige Räume');
            if (parseInt(v.objekt.garage) > 0) raeume.push(v.objekt.garage + ' Garage/Einstellplatz');
            if (parseInt(v.objekt.hofraum) > 0) raeume.push(v.objekt.hofraum + ' Hofraum');
            html += '<p>Weitere Räume: ' + (raeume.length > 0 ? raeume.join(', ') : 'Keine weiteren') + '</p>';
            if (v.objekt.nutzung) html += '<p>Nutzungszweck: ' + v.objekt.nutzung + '</p>';
            // Schlüssel
            const keys = [];
            if (parseInt(v.objekt.schluessel.haus) > 0) keys.push(v.objekt.schluessel.haus + ' Hausschlüssel');
            if (parseInt(v.objekt.schluessel.wohnung) > 0) keys.push(v.objekt.schluessel.wohnung + ' Wohnungsschlüssel');
            if (parseInt(v.objekt.schluessel.zimmer) > 0) keys.push(v.objekt.schluessel.zimmer + ' Zimmerschlüssel');
            if (parseInt(v.objekt.schluessel.boden) > 0) keys.push(v.objekt.schluessel.boden + ' Bodenraumschlüssel');
            if (parseInt(v.objekt.schluessel.keller) > 0) keys.push(v.objekt.schluessel.keller + ' Kellerschlüssel');
            if (parseInt(v.objekt.schluessel.briefkasten) > 0) keys.push(v.objekt.schluessel.briefkasten + ' Briefkastenschlüssel');
            if (v.objekt.schluessel.sonstige) keys.push(v.objekt.schluessel.sonstige);
            html += '<p>Übergebene Schlüssel: ' + (keys.length > 0 ? keys.join(', ') : 'keine') + '</p>';
            html += '</div>';
            // §2 Mietzeit
            html += '<div class="section"><h2>§ 2 Mietzeit</h2>';
            if (v.mietzeit.art === 'unbefristet') {
                html += '<p>Das Mietverhältnis beginnt am ' + formatDate(v.mietzeit.beginn) + ' und läuft auf unbestimmte Zeit.</p>';
                if (v.mietzeit.kuendigungAusschluss && v.mietzeit.kuendigungBis) {
                    html += '<p>Die Vertragsparteien verzichten bis zum ' + formatDate(v.mietzeit.kuendigungBis) + ' wechselseitig auf das Recht zur ordentlichen Kündigung. Eine Kündigung ist erstmals zu diesem Datum mit gesetzlicher Frist zulässig.</p>';
                } else {
                    html += '<p>Die ordentliche Kündigung richtet sich nach den gesetzlichen Fristen (vgl. §§ 573a–573c BGB).</p>';
                }
            } else {
                html += '<p>Das Mietverhältnis beginnt am ' + formatDate(v.mietzeit.beginn) + ' und endet am ' + formatDate(v.mietzeit.ende) + '.</p>';
                if (v.mietzeit.grund) html += '<p>Befristungsgrund: ' + v.mietzeit.grund + '.</p>';
                html += '<p>Ein Anspruch auf Fortsetzung des Mietverhältnisses besteht nicht.</p>';
            }
            html += '</div>';
            // §3 Miete
            html += '<div class="section"><h2>§ 3 Miete</h2>';
            html += '<p>Die monatliche Grundmiete beträgt ' + formatCurrency(v.miete.grund) + ' Euro/Monat.</p>';
            if (v.miete.betrieb && parseFloat(v.miete.betrieb) > 0) html += '<p>Vorauszahlung für Betriebskosten: ' + formatCurrency(v.miete.betrieb) + ' Euro/Monat.</p>';
            if (v.miete.heizung && parseFloat(v.miete.heizung) > 0) html += '<p>Vorauszahlung für Heizkosten: ' + formatCurrency(v.miete.heizung) + ' Euro/Monat.</p>';
            if (v.miete.kaution && parseFloat(v.miete.kaution) > 0) html += '<p>Der Mieter leistet eine Kaution in Höhe von ' + formatCurrency(v.miete.kaution) + ' Euro. Diese wird getrennt vom Vermögen des Vermieters verzinslich angelegt und nach Ende des Mietverhältnisses abzüglich offener Forderungen zurückerstattet (vgl. § 551 BGB).</p>';
            // Staffelmiete oder Indexmiete
            if (v.miete.erhoehung === 'staffel' && v.miete.staffeln.length > 0) {
                html += '<p>Es wird eine Staffelmiete gemäß § 557a BGB vereinbart: Die Miete erhöht sich wie folgt:</p>';
                html += '<ul>';
                v.miete.staffeln.forEach((st, idx) => {
                    html += '<li>Stufe ' + (idx + 1) + ': ab Monat ' + st.ab + ' beträgt die Miete ' + formatCurrency(st.betrag) + ' Euro/Monat.</li>';
                });
                html += '</ul>';
                html += '<p>Während der Laufzeit der Staffelmiete ist eine Mieterhöhung nach §§ 558–559b BGB ausgeschlossen.</p>';
            } else if (v.miete.erhoehung === 'index') {
                html += '<p>Es wird eine Indexmiete gemäß § 557b BGB vereinbart. Die Miete richtet sich nach dem vom Statistischen Bundesamt veröffentlichten Verbraucherpreisindex. Ausgangsindex: ' + (v.miete.indexAusgang || 'n. n.') + '.</p>';
            }
            html += '</div>';
            // §4 Betriebskosten
            html += '<div class="section"><h2>§ 4 Betriebskosten</h2>';
            html += '<p>Neben der Grundmiete trägt der Mieter die Betriebskosten gemäß Betriebskostenverordnung, soweit sie tatsächlich anfallen, insbesondere für öffentliche Lasten des Grundstücks, Wasserversorgung, Entwässerung, Müllabfuhr, Straßenreinigung, Schnee‑ und Eisbeseitigung, Schornsteinreinigung, Beleuchtung, Versicherungen, Hausreinigung, Ungezieferbekämpfung, Hauswart, Gartenpflege, Aufzug, Gemeinschaftsantennenanlage, Breitbandkabel usw.</p>';
            html += '</div>';
            // §5 Zahlung der Miete
            html += '<div class="section"><h2>§ 5 Zahlung der Miete</h2>';
            if (v.zahlung && (v.zahlung.faelligkeit || v.zahlung.iban || v.zahlung.bic)) {
                html += '<p>Die Miete ist monatlich im Voraus ';
                if (v.zahlung.faelligkeit) {
                    html += 'spätestens ' + v.zahlung.faelligkeit + ' ';
                } else {
                    html += 'bis zum dritten Werktag eines jeden Monats ';
                }
                html += 'auf folgendes Konto des Vermieters zu zahlen:</p>';
                if (v.zahlung.iban) html += '<p>IBAN: ' + v.zahlung.iban + '</p>';
                if (v.zahlung.bic) html += '<p>BIC: ' + v.zahlung.bic + '</p>';
            } else {
                html += '<p>Die Miete ist monatlich im Voraus bis zum dritten Werktag eines jeden Monats zu entrichten. Die Bankverbindung des Vermieters wird separat mitgeteilt.</p>';
            }
            html += '</div>';
            // §6 Weitere Vereinbarungen
            html += '<div class="section"><h2>§ 6 Weitere Vereinbarungen</h2>';
            // Zusammenstellung der ausgewählten Klauseln
            const clauseParagraphs = [];
            if (v.clauses) {
                if (v.clauses.schoenheits) clauseParagraphs.push('Der Mieter übernimmt die regelmäßigen Schönheitsreparaturen (z. B. das Streichen und Tapezieren von Wänden und Decken, Lackieren von Türen und Fenstern) auf eigene Kosten.');
                if (v.clauses.klein) clauseParagraphs.push('Der Mieter trägt die Kosten für Kleinreparaturen bis zu einem Betrag von 100 Euro pro Einzelfall, maximal 300 Euro pro Jahr.');
                if (v.clauses.tierhaltung) clauseParagraphs.push('Die Haltung von Kleintieren (z. B. Zierfische, Hamster, Vögel) ist zulässig. Die Haltung von Hunden und Katzen bedarf der vorherigen Zustimmung des Vermieters. Blindenführhunde sind hiervon ausgenommen.');
                if (v.clauses.untervermietung) clauseParagraphs.push('Eine Untervermietung des Mietobjekts oder von Teilen davon bedarf der schriftlichen Zustimmung des Vermieters.');
                if (v.clauses.besichtigung) clauseParagraphs.push('Der Vermieter ist berechtigt, die Mieträume nach vorheriger Ankündigung während der üblichen Tageszeiten zu besichtigen, um deren Zustand zu überprüfen oder sie Interessenten vorzuführen.');
                if (v.clauses.modernisierung) clauseParagraphs.push('Der Mieter hat Modernisierungsmaßnahmen und bauliche Veränderungen, die der Vermieter zur Erhaltung oder Verbesserung der Mietsache vornimmt, zu dulden. Eine Mieterhöhung nach gesetzlichen Vorschriften bleibt vorbehalten.');
                if (v.clauses.garten) clauseParagraphs.push('Der Mieter darf vorhandene Gartenflächen mitbenutzen und verpflichtet sich zu deren ordnungsgemäßer Pflege und Instandhaltung.');
                if (v.clauses.mehrere) clauseParagraphs.push('Mehrere Mieter haften für die Verpflichtungen aus diesem Mietvertrag als Gesamtschuldner. Erklärungen, die einem Mieter gegenüber abgegeben werden, wirken für und gegen alle Mieter.');
                if (v.clauses.hausordnung) clauseParagraphs.push('Der Mieter verpflichtet sich, die Hausordnung des Hauses einzuhalten.');
                if (v.clauses.umbauten) clauseParagraphs.push('Bauliche Veränderungen und Einbauten dürfen nur mit vorheriger schriftlicher Zustimmung des Vermieters durchgeführt werden. Der Vermieter kann bei Auszug den Rückbau verlangen.');
                // Weitere optionale Klauseln
                if (v.clauses.haftung) clauseParagraphs.push('Der Mieter haftet für alle von ihm, seinen Familienangehörigen, Mitmietern oder Besuchern schuldhaft verursachten Schäden an der Mietsache und hat diese Schäden unverzüglich dem Vermieter anzuzeigen.');
                if (v.clauses.rauchmelder) clauseParagraphs.push('Der Mieter ist verpflichtet, die gesetzlichen Rauchmelder in der Mietsache in funktionsfähigem Zustand zu halten und regelmäßig zu prüfen; Batterien sind rechtzeitig auszutauschen.');
                if (v.clauses.schriftform) clauseParagraphs.push('Änderungen und Ergänzungen dieses Vertrages bedürfen zu ihrer Wirksamkeit der Schriftform. Mündliche Nebenabreden bestehen nicht.');
                if (v.clauses.ruhezeiten) clauseParagraphs.push('Der Mieter verpflichtet sich, die üblichen Ruhezeiten (werktags zwischen 22:00 und 6:00 Uhr sowie an Sonn- und Feiertagen ganztägig) einzuhalten.');
                if (v.clauses.instandhaltung) clauseParagraphs.push('Der Mieter verpflichtet sich, die Mietsache pfleglich zu behandeln und kleinere Instandhaltungsmaßnahmen, insbesondere das Austauschen von Leuchtmitteln, Sicherungen und das Ölen von Scharnieren, selbst durchzuführen.');
            }
            // Füge die Klauseln als Paragraphen ein
            clauseParagraphs.forEach(text => {
                html += '<p>' + text + '</p>';
            });
            // Sonstige freie Vereinbarungen hinzufügen
            if (v.sonstigeVereinbarungen && v.sonstigeVereinbarungen.length > 0) {
                const lines = v.sonstigeVereinbarungen.split(/\n+/).map(l => l.trim()).filter(Boolean);
                lines.forEach(line => {
                    html += '<p>' + line + '</p>';
                });
            }
            // SEPA-Lastschriftmandat des Mieters
            if (v.mandat && (v.mandat.inhaber || v.mandat.iban || v.mandat.bic)) {
                html += '<p>Der Mieter erteilt dem Vermieter ein SEPA-Lastschriftmandat zur Einziehung der monatlichen Miete und Nebenkosten. Kontoinhaber: ' + (v.mandat.inhaber || '–') + ', IBAN: ' + (v.mandat.iban || '–') + ', BIC: ' + (v.mandat.bic || '–') + '.</p>';
            }
            html += '<p>Im Übrigen gelten die gesetzlichen Bestimmungen des Bürgerlichen Gesetzbuches (BGB) und – soweit vorhanden – die Hausordnung.</p>';
            html += '</div>';
            // Unterschriften
            html += '<div class="signature">';
            html += '<div>Ort, Datum: ______________________________</div>';
            html += '<div>Unterschrift Vermieter: ______________________________</div>';
            html += '<div>Unterschrift Mieter: ______________________________</div>';
            html += '</div>';
            // Schließe Container und Dokument
            html += '</div></body></html>';
            return html;
        }

        // Download des Vertrages
        document.getElementById('download').addEventListener('click', () => {
            // Zuerst sicherstellen, dass die neueste Version des Vertrags generiert wird
            generateContract();
            const contractHTML = generateContractHTML();
            const blob = new Blob([contractHTML], { type: 'text/html;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            // Datei als .html speichern
            link.download = 'mietvertrag.html';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        });

        // PDF-Export (serverseitig, FastAPI): sendet Wizard-Daten als JSON und lädt PDF.
        // Fallback: falls Endpoint nicht erreichbar ist, nutzt clientseitiges pdfMake.
        const apiBase = (document.querySelector('meta[name="mw-api-base"]') || {}).content || '';

        async function downloadPdfServerSide() {
            if (!apiBase) return false;
            try {
                collectFormData();
                const res = await fetch(apiBase.replace(/\/$/, '') + '/pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                if (!res.ok) return false;
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = 'mietvertrag.pdf';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url);
                return true;
            } catch (e) {
                console.warn('Server-PDF nicht verfügbar:', e);
                return false;
            }
        }

        document.getElementById('download-pdf').addEventListener('click', async () => {
            const ok = await downloadPdfServerSide();
            if (ok) return;
            // Fallback: clientseitig
            try {
                collectFormData();
                generateContractPDF();
            } catch (err) {
                alert('Fehler bei der PDF-Erstellung: ' + err);
                console.error(err);
            }
        });

    // Formulardaten sammeln
    function collectFormData() {
        // Vermieter: mehrere Einträge sammeln
        formData.vermieter = [];
        document.querySelectorAll('#vermieter-list .vermieter-block').forEach(block => {
            const data = {
                name: block.querySelector('input[name="vermieter-name"]').value.trim(),
                vertreter: block.querySelector('input[name="vermieter-vertreter"]').value.trim(),
                strasse: block.querySelector('input[name="vermieter-strasse"]').value.trim(),
                plz: block.querySelector('input[name="vermieter-plz"]').value.trim(),
                ort: block.querySelector('input[name="vermieter-ort"]').value.trim(),
                telefon: block.querySelector('input[name="vermieter-telefon"]').value.trim(),
                email: block.querySelector('input[name="vermieter-email"]').value.trim()
            };
            // nur hinzufügen, wenn Name ausgefüllt ist
            if (data.name) formData.vermieter.push(data);
        });
        // Mieter: mehrere Einträge sammeln
        formData.mieter = [];
        document.querySelectorAll('#mieter-list .mieter-block').forEach(block => {
            const data = {
                name: block.querySelector('input[name="mieter-name"]').value.trim(),
                geburtsdatum: block.querySelector('input[name="mieter-geburtsdatum"]').value,
                vertreter: block.querySelector('input[name="mieter-vertreter"]').value.trim(),
                strasse: block.querySelector('input[name="mieter-strasse"]').value.trim(),
                plz: block.querySelector('input[name="mieter-plz"]').value.trim(),
                ort: block.querySelector('input[name="mieter-ort"]').value.trim(),
                telefon: block.querySelector('input[name="mieter-telefon"]').value.trim(),
                email: block.querySelector('input[name="mieter-email"]').value.trim()
            };
            if (data.name) formData.mieter.push(data);
        });
        // Mietobjekt
        formData.objekt = {
            art: document.getElementById('objektart').value,
            strasse: document.getElementById('objekt-strasse').value.trim(),
            plz: document.getElementById('objekt-plz').value.trim(),
            ort: document.getElementById('objekt-ort').value.trim(),
            wohnflaeche: document.getElementById('objekt-wohnflaeche').value,
            geschoss: document.getElementById('objekt-geschoss').value.trim(),
            zimmer: document.getElementById('objekt-zimmer').value,
            kueche: document.getElementById('objekt-kueche').value,
            bad: document.getElementById('objekt-bad').value,
            wc: document.getElementById('objekt-wc').value,
            keller: document.getElementById('objekt-keller').value,
            boden: document.getElementById('objekt-boden').value,
            abstell: document.getElementById('objekt-abstell').value,
            balkon: document.getElementById('objekt-balkon').value,
            sonstige: document.getElementById('objekt-sonstige').value,
            garage: document.getElementById('objekt-garage').value,
            hofraum: document.getElementById('objekt-hofraum').value,
            nutzung: document.getElementById('objekt-nutzung').value.trim(),
            schluessel: {
                haus: document.getElementById('schluessel-haus').value,
                wohnung: document.getElementById('schluessel-wohnung').value,
                zimmer: document.getElementById('schluessel-zimmer').value,
                boden: document.getElementById('schluessel-boden').value,
                keller: document.getElementById('schluessel-keller').value,
                briefkasten: document.getElementById('schluessel-briefkasten').value,
                sonstige: document.getElementById('schluessel-sonstige').value.trim()
            }
        };
        // Mietzeit
        // Befristungsgrund aus Auswahl ermitteln
        let grundValue = '';
        const grundSelectEl = document.getElementById('befristet-grund-option');
        const grundTextEl = document.getElementById('befristet-grund-text');
        if (grundSelectEl) {
            const selected = grundSelectEl.value;
            if (selected === 'Sonstiges') {
                grundValue = grundTextEl ? grundTextEl.value.trim() : '';
            } else {
                grundValue = selected;
            }
        } else {
            // Fallback falls altes Feld existiert
            const grundInput = document.getElementById('befristet-grund');
            grundValue = grundInput ? grundInput.value.trim() : '';
        }
        formData.mietzeit = {
            art: document.getElementById('mietzeit-art').value,
            beginn: document.getElementById('mietbeginn').value,
            ende: document.getElementById('mietende').value,
            grund: grundValue,
            kuendigungAusschluss: document.getElementById('kuendigungsausschluss-check').checked,
            kuendigungBis: document.getElementById('kuendigungsausschluss-bis').value
        };
        // Hilfsfunktion zur Extraktion von Währungswerten (entfernt Punkte/Kommas)
        const convCurrency = (val) => parseDeMoney(val);
        // Miete & Kosten
        formData.miete = {
            grund: convCurrency(document.getElementById('miete-grund').value),
            betrieb: convCurrency(document.getElementById('miete-betrieb').value),
            heizung: convCurrency(document.getElementById('miete-heizung').value),
            kaution: convCurrency(document.getElementById('kaution').value),
            erhoehung: document.getElementById('mieterhoehung').value,
            staffeln: [],
            indexAusgang: document.getElementById('index-ausgang').value
        };
        if (formData.miete.erhoehung === 'staffel') {
            const rows = document.querySelectorAll('#staffel-list .staffel-row');
            rows.forEach(row => {
                const betragInput = row.querySelector('input.staffel-betrag');
                const abInput = row.querySelector('input.staffel-ab');
                const betrag = betragInput ? convCurrency(betragInput.value) : '';
                const ab = abInput ? abInput.value : '';
                if (betrag && ab) {
                    formData.miete.staffeln.push({ betrag, ab });
                }
            });
        }

        // Zahlungsinformationen
        formData.zahlung = {
            iban: document.getElementById('zahlung-iban') ? document.getElementById('zahlung-iban').value.trim() : '',
            bic: document.getElementById('zahlung-bic') ? document.getElementById('zahlung-bic').value.trim() : '',
            faelligkeit: document.getElementById('zahlung-faelligkeit') ? document.getElementById('zahlung-faelligkeit').value.trim() : ''
        };
        // Zusatzklauseln (Checkboxes)
        formData.clauses = {
            schoenheits: document.getElementById('clause-schoenheits') ? document.getElementById('clause-schoenheits').checked : false,
            klein: document.getElementById('clause-klein') ? document.getElementById('clause-klein').checked : false,
            tierhaltung: document.getElementById('clause-tierhaltung') ? document.getElementById('clause-tierhaltung').checked : false,
            untervermietung: document.getElementById('clause-untervermietung') ? document.getElementById('clause-untervermietung').checked : false,
            besichtigung: document.getElementById('clause-besichtigung') ? document.getElementById('clause-besichtigung').checked : false,
            modernisierung: document.getElementById('clause-modernisierung') ? document.getElementById('clause-modernisierung').checked : false,
            garten: document.getElementById('clause-garten') ? document.getElementById('clause-garten').checked : false,
            mehrere: document.getElementById('clause-mehrere') ? document.getElementById('clause-mehrere').checked : false,
            hausordnung: document.getElementById('clause-hausordnung') ? document.getElementById('clause-hausordnung').checked : false,
            umbauten: document.getElementById('clause-umbauten') ? document.getElementById('clause-umbauten').checked : false
            ,
            // Neue Klauseln
            haftung: document.getElementById('clause-haftung') ? document.getElementById('clause-haftung').checked : false,
            rauchmelder: document.getElementById('clause-rauchmelder') ? document.getElementById('clause-rauchmelder').checked : false,
            schriftform: document.getElementById('clause-schriftform') ? document.getElementById('clause-schriftform').checked : false,
            ruhezeiten: document.getElementById('clause-ruhezeiten') ? document.getElementById('clause-ruhezeiten').checked : false,
            instandhaltung: document.getElementById('clause-instandhaltung') ? document.getElementById('clause-instandhaltung').checked : false
        };
        // Weitere/sonstige Vereinbarungen (Freitext)
        const sonst = document.getElementById('sonstige-vereinbarungen');
        formData.sonstigeVereinbarungen = sonst ? sonst.value.trim() : '';

        // SEPA-Lastschriftmandat des Mieters (optional)
        formData.mandat = {
            inhaber: document.getElementById('mandat-inhaber') ? document.getElementById('mandat-inhaber').value.trim() : '',
            iban: document.getElementById('mandat-iban') ? document.getElementById('mandat-iban').value.trim() : '',
            bic: document.getElementById('mandat-bic') ? document.getElementById('mandat-bic').value.trim() : ''
        };
    }

    /**
     * Erzeugt mit der Bibliothek pdfMake ein professionell gestaltetes PDF
     * basierend auf den im Wizard eingegebenen Daten. Die Optik orientiert sich
     * am bereitgestellten Muster: ein farbiger Kopfbereich, klar strukturierte
     * Abschnitte und gut lesbare Schrift.
     */
    function generateContractPDF() {
        const v = formData;
        // Hilfsfunktionen für Datums- und Währungsformat
        const parseDate = (dateStr) => {
            if (!dateStr) return null;
            if (dateStr.includes('.')) {
                const parts = dateStr.split('.');
                if (parts.length === 3) {
                    const day = parseInt(parts[0], 10);
                    const month = parseInt(parts[1], 10) - 1;
                    const year = parseInt(parts[2], 10);
                    return new Date(year, month, day);
                }
            }
            return new Date(dateStr);
        };
        const formatDate = (dateStr) => {
            const d = parseDate(dateStr);
            if (!d || isNaN(d)) return '';
            return d.toLocaleDateString('de-DE');
        };
        const formatCurrency = (val) => {
            if (!val || isNaN(parseFloat(val))) return '';
            return parseFloat(val).toFixed(2).replace('.', ',');
        };
        // Listeneinträge für weitere Räume
        const raeume = [];
        const pluralize = (num, singular, plural) => (num > 1 ? plural : singular);
        if (parseInt(v.objekt.kueche) > 0) raeume.push(v.objekt.kueche + ' ' + pluralize(v.objekt.kueche, 'Küche', 'Küchen'));
        if (parseInt(v.objekt.bad) > 0) raeume.push(v.objekt.bad + ' ' + pluralize(v.objekt.bad, 'Bad', 'Bäder'));
        if (parseInt(v.objekt.wc) > 0) raeume.push(v.objekt.wc + ' WC' + (v.objekt.wc > 1 ? 's' : ''));
        if (parseInt(v.objekt.keller) > 0) raeume.push(v.objekt.keller + ' Keller');
        if (parseInt(v.objekt.boden) > 0) raeume.push(v.objekt.boden + ' Bodenraum' + (v.objekt.boden > 1 ? 'e' : ''));
        if (parseInt(v.objekt.abstell) > 0) raeume.push(v.objekt.abstell + ' Abstellraum' + (v.objekt.abstell > 1 ? 'e' : ''));
        if (parseInt(v.objekt.balkon) > 0) raeume.push(v.objekt.balkon + ' Balkon/Terrasse');
        if (parseInt(v.objekt.sonstige) > 0) raeume.push(v.objekt.sonstige + ' sonstige Räume');
        if (parseInt(v.objekt.garage) > 0) raeume.push(v.objekt.garage + ' Garage/Einstellplatz');
        if (parseInt(v.objekt.hofraum) > 0) raeume.push(v.objekt.hofraum + ' Hofraum');
        const raeumeText = raeume.length > 0 ? raeume.join(', ') : 'Keine weiteren';
        // Schlüssel
        const keys = [];
        if (parseInt(v.objekt.schluessel.haus) > 0) keys.push(v.objekt.schluessel.haus + ' Hausschlüssel');
        if (parseInt(v.objekt.schluessel.wohnung) > 0) keys.push(v.objekt.schluessel.wohnung + ' Wohnungsschlüssel');
        if (parseInt(v.objekt.schluessel.zimmer) > 0) keys.push(v.objekt.schluessel.zimmer + ' Zimmerschlüssel');
        if (parseInt(v.objekt.schluessel.boden) > 0) keys.push(v.objekt.schluessel.boden + ' Bodenraumschlüssel');
        if (parseInt(v.objekt.schluessel.keller) > 0) keys.push(v.objekt.schluessel.keller + ' Kellerschlüssel');
        if (parseInt(v.objekt.schluessel.briefkasten) > 0) keys.push(v.objekt.schluessel.briefkasten + ' Briefkastenschlüssel');
        if (v.objekt.schluessel.sonstige) keys.push(v.objekt.schluessel.sonstige);
        const keysText = keys.length > 0 ? keys.join(', ') : 'keine';
        // Staffelmieten
        let staffelList = [];
        if (v.miete.erhoehung === 'staffel' && v.miete.staffeln.length > 0) {
            staffelList = v.miete.staffeln.map((st, idx) => ({
                text: [
                    { text: 'Stufe ' + (idx + 1) + ': ', bold: true },
                    'ab Monat ' + st.ab + ' beträgt die Miete ' + formatCurrency(st.betrag) + ' Euro/Monat.'
                ]
            }));
        }

        // Weitere Vereinbarungen in ein Array von Absätzen umwandeln
        let weitereParagraphs = [];
        // Freitext für sonstige Vereinbarungen einfügen
        if (v.sonstigeVereinbarungen && v.sonstigeVereinbarungen.length > 0) {
            const lines = v.sonstigeVereinbarungen.split(/\n+/).map(l => l.trim()).filter(Boolean);
            weitereParagraphs = lines.map(line => ({ text: line, margin: [0, 0, 0, 2] }));
        }
        // Erstellen der Parteistacks für Vermieter und Mieter (Unterstützung mehrerer Personen)
        const vermieterStack = [];
        // Überschrift für Vermieter
        vermieterStack.push({ text: 'Vermieter', style: 'subheading' });
        v.vermieter.forEach((ver) => {
            // Name ggf. mit Vertreter
            let nameLine = ver.name;
            if (ver.vertreter && ver.vertreter.trim().length > 0) {
                nameLine += ', vertreten durch ' + ver.vertreter.trim();
            }
            vermieterStack.push({ text: nameLine, bold: true });
            vermieterStack.push({ text: ver.strasse + ', ' + ver.plz + ' ' + ver.ort });
            if (ver.telefon) vermieterStack.push({ text: 'Tel.: ' + ver.telefon });
            if (ver.email) vermieterStack.push({ text: 'E‑Mail: ' + ver.email });
            // Leerzeile zwischen mehreren Vermietern
            vermieterStack.push({ text: ' ' });
        });
        const mieterStack = [];
        mieterStack.push({ text: 'Mieter', style: 'subheading' });
        v.mieter.forEach((mi) => {
            let nameLine = mi.name;
            if (mi.geburtsdatum) nameLine += ' (geb. ' + formatDate(mi.geburtsdatum) + ')';
            if (mi.vertreter && mi.vertreter.trim().length > 0) {
                nameLine += ', vertreten durch ' + mi.vertreter.trim();
            }
            mieterStack.push({ text: nameLine, bold: true });
            mieterStack.push({ text: mi.strasse + ', ' + mi.plz + ' ' + mi.ort });
            if (mi.telefon) mieterStack.push({ text: 'Tel.: ' + mi.telefon });
            if (mi.email) mieterStack.push({ text: 'E‑Mail: ' + mi.email });
            mieterStack.push({ text: ' ' });
        });

        // Dokumentdefinition für pdfMake
        const docDefinition = {
            pageSize: 'A4',
            // Großzügige Ränder für professionelles Layout
            pageMargins: [50, 90, 50, 70],
            // Kopfbereich: dunkler Balken mit weißer Schrift – gut lesbar auch in Schwarz‑Weiß
            header: {
                margin: [0, 0, 0, 0],
                stack: [
                    {
                        canvas: [
                            { type: 'rect', x: 0, y: 0, w: 515, h: 60, color: '#333333' }
                        ]
                    },
                    {
                        text: 'Wohnraum‑Mietvertrag',
                        color: '#FFFFFF',
                        fontSize: 22,
                        bold: true,
                        absolutePosition: { x: 50, y: 18 }
                    }
                ]
            },
            // Fußbereich: Seitenzahlen in kleinerer Schrift
            footer: function(currentPage, pageCount) {
                return {
                    columns: [
                        { text: '', width: '*' },
                        { text: currentPage.toString() + ' / ' + pageCount, width: 'auto', fontSize: 8 }
                    ],
                    margin: [50, 10, 50, 10]
                };
            },
            // Schrift und Farbe – Roboto ist in pdfMake eingebettet
            defaultStyle: {
                font: 'Roboto',
                fontSize: 10,
                color: '#000000'
            },
            styles: {
                heading: { fontSize: 13, bold: true, margin: [0, 15, 0, 5] },
                subheading: { fontSize: 11, bold: true, margin: [0, 8, 0, 3] }
            },
            // Inhalt des PDF
            content: [
                { text: 'Zwischen den nachstehend genannten Vertragsparteien wird folgender Mietvertrag geschlossen:', margin: [0, 0, 0, 10] },
                {
                    columns: [
                        { width: '50%', stack: vermieterStack, margin: [0, 0, 10, 0] },
                        { width: '50%', stack: mieterStack, margin: [10, 0, 0, 0] }
                    ],
                    columnGap: 10,
                    margin: [0, 0, 0, 20]
                },
                { text: '§ 1 Mieträume', style: 'heading' },
                // Trennlinie unter der Überschrift
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                { text: 'Der Vermieter vermietet dem Mieter zu Wohnzwecken folgendes Objekt: ' + v.objekt.art + '.', margin: [0, 0, 0, 2] },
                { text: 'Adresse: ' + v.objekt.strasse + ', ' + v.objekt.plz + ' ' + v.objekt.ort, margin: [0, 0, 0, 2] },
                v.objekt.wohnflaeche ? { text: 'Wohnfläche: ca. ' + v.objekt.wohnflaeche + ' m²', margin: [0, 0, 0, 2] } : {},
                v.objekt.geschoss ? { text: 'Geschoss: ' + v.objekt.geschoss, margin: [0, 0, 0, 2] } : {},
                v.objekt.zimmer ? { text: 'Zimmer: ' + v.objekt.zimmer, margin: [0, 0, 0, 2] } : {},
                { text: 'Weitere Räume: ' + raeumeText, margin: [0, 0, 0, 2] },
                v.objekt.nutzung ? { text: 'Nutzungszweck: ' + v.objekt.nutzung + '.', margin: [0, 0, 0, 2] } : {},
                { text: 'Übergebene Schlüssel: ' + keysText + '.', margin: [0, 0, 0, 8] },
                { text: '§ 2 Mietzeit', style: 'heading' },
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                (function() {
                    if (v.mietzeit.art === 'unbefristet') {
                        let arr = [];
                        arr.push({ text: 'Das Mietverhältnis beginnt am ' + formatDate(v.mietzeit.beginn) + ' und läuft auf unbestimmte Zeit.', margin: [0, 0, 0, 2] });
                        if (v.mietzeit.kuendigungAusschluss && v.mietzeit.kuendigungBis) {
                            arr.push({ text: 'Die Vertragsparteien verzichten bis zum ' + formatDate(v.mietzeit.kuendigungBis) + ' wechselseitig auf das Recht zur ordentlichen Kündigung. Eine Kündigung ist erstmals zu diesem Datum mit gesetzlicher Frist zulässig.', margin: [0, 0, 0, 2] });
                        } else {
                            arr.push({ text: 'Die ordentliche Kündigung richtet sich nach den gesetzlichen Fristen (vgl. §§ 573a–573c BGB).', margin: [0, 0, 0, 2] });
                        }
                        return arr;
                    } else {
                        let arr = [];
                        arr.push({ text: 'Das Mietverhältnis beginnt am ' + formatDate(v.mietzeit.beginn) + ' und endet am ' + formatDate(v.mietzeit.ende) + '.', margin: [0, 0, 0, 2] });
                        if (v.mietzeit.grund) arr.push({ text: 'Befristungsgrund: ' + v.mietzeit.grund + '.', margin: [0, 0, 0, 2] });
                        arr.push({ text: 'Ein Anspruch auf Fortsetzung des Mietverhältnisses besteht nicht.', margin: [0, 0, 0, 2] });
                        return arr;
                    }
                })(),
                { text: '§ 3 Miete', style: 'heading' },
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                { text: 'Die monatliche Grundmiete beträgt ' + formatCurrency(v.miete.grund) + ' Euro/Monat.', margin: [0, 0, 0, 2] },
                v.miete.betrieb && parseFloat(v.miete.betrieb) > 0 ? { text: 'Vorauszahlung für Betriebskosten: ' + formatCurrency(v.miete.betrieb) + ' Euro/Monat.', margin: [0, 0, 0, 2] } : {},
                v.miete.heizung && parseFloat(v.miete.heizung) > 0 ? { text: 'Vorauszahlung für Heizkosten: ' + formatCurrency(v.miete.heizung) + ' Euro/Monat.', margin: [0, 0, 0, 2] } : {},
                v.miete.kaution && parseFloat(v.miete.kaution) > 0 ? { text: 'Der Mieter leistet eine Kaution in Höhe von ' + formatCurrency(v.miete.kaution) + ' Euro. Diese wird getrennt vom Vermögen des Vermieters verzinslich angelegt und nach Ende des Mietverhältnisses abzüglich offener Forderungen zurückerstattet (vgl. § 551 BGB).', margin: [0, 0, 0, 2] } : {},
                v.miete.erhoehung === 'staffel' && staffelList.length > 0 ? { text: 'Es wird eine Staffelmiete gemäß § 557a BGB vereinbart. Die Miete erhöht sich wie folgt:', margin: [0, 2, 0, 2] } : {},
                v.miete.erhoehung === 'staffel' && staffelList.length > 0 ? { ul: staffelList, margin: [0, 0, 0, 2] } : {},
                v.miete.erhoehung === 'staffel' && staffelList.length > 0 ? { text: 'Während der Laufzeit der Staffelmiete ist eine Mieterhöhung nach §§ 558–559b BGB ausgeschlossen.', margin: [0, 0, 0, 2] } : {},
                v.miete.erhoehung === 'index' ? { text: 'Es wird eine Indexmiete gemäß § 557b BGB vereinbart. Die Miete richtet sich nach dem vom Statistischen Bundesamt veröffentlichten Verbraucherpreisindex. Ausgangsindex: ' + (v.miete.indexAusgang || 'n. n.') + '.', margin: [0, 0, 0, 2] } : {},
                { text: '§ 4 Betriebskosten', style: 'heading' },
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                { text: 'Neben der Grundmiete trägt der Mieter die Betriebskosten gemäß Betriebskostenverordnung, soweit sie tatsächlich anfallen, insbesondere für öffentliche Lasten des Grundstücks, Wasserversorgung, Entwässerung, Müllabfuhr, Straßenreinigung, Schnee‑ und Eisbeseitigung, Schornsteinreinigung, Beleuchtung, Versicherungen, Hausreinigung, Ungezieferbekämpfung, Hauswart, Gartenpflege, Aufzug, Gemeinschaftsantennenanlage, Breitbandkabel usw.', margin: [0, 0, 0, 8] },
                // §5 Zahlung der Miete
                { text: '§ 5 Zahlung der Miete', style: 'heading' },
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                (function() {
                    const arr = [];
                    if (v.zahlung && (v.zahlung.faelligkeit || v.zahlung.iban || v.zahlung.bic)) {
                        let line = 'Die Miete ist monatlich im Voraus ';
                        if (v.zahlung.faelligkeit) {
                            line += 'spätestens ' + v.zahlung.faelligkeit + ' ';
                        } else {
                            line += 'bis zum dritten Werktag eines jeden Monats ';
                        }
                        line += 'auf folgendes Konto des Vermieters zu zahlen.';
                        arr.push({ text: line, margin: [0, 0, 0, 2] });
                        if (v.zahlung.iban) arr.push({ text: 'IBAN: ' + v.zahlung.iban, margin: [0, 0, 0, 2] });
                        if (v.zahlung.bic) arr.push({ text: 'BIC: ' + v.zahlung.bic, margin: [0, 0, 0, 2] });
                        // Wenn ein SEPA-Lastschriftmandat des Mieters vorliegt, dieses angeben
                        if (v.mandat && (v.mandat.inhaber || v.mandat.iban || v.mandat.bic)) {
                            let sepaText = 'Der Mieter erteilt dem Vermieter ein SEPA-Lastschriftmandat';
                            const details = [];
                            if (v.mandat.inhaber) details.push('Kontoinhaber: ' + v.mandat.inhaber);
                            if (v.mandat.iban) details.push('IBAN: ' + v.mandat.iban);
                            if (v.mandat.bic) details.push('BIC: ' + v.mandat.bic);
                            if (details.length > 0) sepaText += ' (' + details.join(', ') + ')';
                            sepaText += '.';
                            arr.push({ text: sepaText, margin: [0, 0, 0, 2] });
                        }
                    } else {
                        arr.push({ text: 'Die Miete ist monatlich im Voraus bis zum dritten Werktag eines jeden Monats zu entrichten. Die Bankverbindung des Vermieters wird separat mitgeteilt.', margin: [0, 0, 0, 2] });
                    }
                    return arr;
                })(),
                // §6 Weitere Vereinbarungen
                { text: '§ 6 Weitere Vereinbarungen', style: 'heading' },
                { canvas: [ { type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, color: '#666666' } ], margin: [0, 0, 0, 5] },
                (function() {
                    const para = [];
                    // Texte für gewählte Klauseln
                    if (v.clauses) {
                        if (v.clauses.schoenheits) para.push({ text: 'Der Mieter übernimmt die regelmäßigen Schönheitsreparaturen (z. B. das Streichen und Tapezieren von Wänden und Decken, Lackieren von Türen und Fenstern) auf eigene Kosten.', margin: [0, 0, 0, 2] });
                        if (v.clauses.klein) para.push({ text: 'Der Mieter trägt die Kosten für Kleinreparaturen bis zu einem Betrag von 100 Euro pro Einzelfall, maximal 300 Euro pro Jahr.', margin: [0, 0, 0, 2] });
                        if (v.clauses.tierhaltung) para.push({ text: 'Die Haltung von Kleintieren (z. B. Zierfische, Hamster, Vögel) ist zulässig. Die Haltung von Hunden und Katzen bedarf der vorherigen Zustimmung des Vermieters. Blindenführhunde sind hiervon ausgenommen.', margin: [0, 0, 0, 2] });
                        if (v.clauses.untervermietung) para.push({ text: 'Eine Untervermietung des Mietobjekts oder von Teilen davon bedarf der schriftlichen Zustimmung des Vermieters.', margin: [0, 0, 0, 2] });
                        if (v.clauses.besichtigung) para.push({ text: 'Der Vermieter ist berechtigt, die Mieträume nach vorheriger Ankündigung während der üblichen Tageszeiten zu besichtigen, um deren Zustand zu überprüfen oder sie Interessenten vorzuführen.', margin: [0, 0, 0, 2] });
                        if (v.clauses.modernisierung) para.push({ text: 'Der Mieter hat Modernisierungsmaßnahmen und bauliche Veränderungen, die der Vermieter zur Erhaltung oder Verbesserung der Mietsache vornimmt, zu dulden. Eine Mieterhöhung nach gesetzlichen Vorschriften bleibt vorbehalten.', margin: [0, 0, 0, 2] });
                        if (v.clauses.garten) para.push({ text: 'Der Mieter darf vorhandene Gartenflächen mitbenutzen und verpflichtet sich zu deren ordnungsgemäßer Pflege und Instandhaltung.', margin: [0, 0, 0, 2] });
                        if (v.clauses.mehrere) para.push({ text: 'Mehrere Mieter haften für die Verpflichtungen aus diesem Mietvertrag als Gesamtschuldner. Erklärungen, die einem Mieter gegenüber abgegeben werden, wirken für und gegen alle Mieter.', margin: [0, 0, 0, 2] });
                        if (v.clauses.hausordnung) para.push({ text: 'Der Mieter verpflichtet sich, die Hausordnung des Hauses einzuhalten.', margin: [0, 0, 0, 2] });
                        if (v.clauses.umbauten) para.push({ text: 'Bauliche Veränderungen und Einbauten dürfen nur mit vorheriger schriftlicher Zustimmung des Vermieters durchgeführt werden. Der Vermieter kann bei Auszug den Rückbau verlangen.', margin: [0, 0, 0, 2] });
                    // Neue optionale Klauseln
                    if (v.clauses.haftung) para.push({ text: 'Der Mieter haftet für alle von ihm, seinen Familienangehörigen, Mitmietern oder Besuchern schuldhaft verursachten Schäden an der Mietsache und hat diese Schäden unverzüglich dem Vermieter anzuzeigen.', margin: [0, 0, 0, 2] });
                    if (v.clauses.rauchmelder) para.push({ text: 'Der Mieter ist verpflichtet, die gesetzlichen Rauchmelder in der Mietsache in funktionsfähigem Zustand zu halten und regelmäßig zu prüfen; Batterien sind rechtzeitig auszutauschen.', margin: [0, 0, 0, 2] });
                    if (v.clauses.schriftform) para.push({ text: 'Änderungen und Ergänzungen dieses Vertrages bedürfen zu ihrer Wirksamkeit der Schriftform. Mündliche Nebenabreden bestehen nicht.', margin: [0, 0, 0, 2] });
                    if (v.clauses.ruhezeiten) para.push({ text: 'Der Mieter verpflichtet sich, die üblichen Ruhezeiten (werktags zwischen 22:00 und 6:00 Uhr sowie an Sonn- und Feiertagen ganztägig) einzuhalten.', margin: [0, 0, 0, 2] });
                    if (v.clauses.instandhaltung) para.push({ text: 'Der Mieter verpflichtet sich, die Mietsache pfleglich zu behandeln und kleinere Instandhaltungsmaßnahmen, insbesondere das Austauschen von Leuchtmitteln, Sicherungen und das Ölen von Scharnieren, selbst durchzuführen.', margin: [0, 0, 0, 2] });
                    }
                    // Sonstige Vereinbarungen des Nutzers
                    if (v.sonstigeVereinbarungen && v.sonstigeVereinbarungen.length > 0) {
                        const lines = v.sonstigeVereinbarungen.split(/\n+/).map(l => l.trim()).filter(Boolean);
                        lines.forEach(line => para.push({ text: line, margin: [0, 0, 0, 2] }));
                    }
                    return para.length > 0 ? para : [];
                })(),
                { text: 'Im Übrigen gelten die gesetzlichen Bestimmungen des Bürgerlichen Gesetzbuches (BGB) und – soweit vorhanden – die Hausordnung.', margin: [0, 0, 0, 8] },
                {
                    columns: [
                        { text: 'Ort, Datum: ______________________________', width: '33%', margin: [0, 20, 0, 0] },
                        { text: 'Unterschrift Vermieter: ______________________________', width: '33%', margin: [0, 20, 0, 0] },
                        { text: 'Unterschrift Mieter: ______________________________', width: '33%', margin: [0, 20, 0, 0] }
                    ]
                }
            ]
        };
        // Erzeugt und lädt das PDF herunter
        // Öffnen Sie das PDF zunächst in einem neuen Tab. Der Benutzer kann von dort drucken oder speichern.
        const pdfDoc = pdfMake.createPdf(docDefinition);
        // Erst öffnen, dann herunterladen als Fallback
        pdfDoc.open();
        pdfDoc.download('mietvertrag.pdf');
    }

    // Vertragstext generieren
    function generateContract() {
        const v = formData;
        // Datum formatieren. Akzeptiert deutsche Schreibweise TT.MM.JJJJ oder ISO‑Format JJJJ‑MM‑TT.
        function formatDate(dateStr) {
            if (!dateStr) return '';
            // Wenn der Benutzer das Datum im Format TT.MM.JJJJ eingibt, splitten und bauen wir ein Datum.
            let parts;
            if (/^\d{2}\.\d{2}\.\d{4}$/.test(dateStr)) {
                parts = dateStr.split('.');
                const day = parseInt(parts[0], 10);
                const month = parseInt(parts[1], 10) - 1; // Monat ist 0‑basiert
                const year = parseInt(parts[2], 10);
                const d = new Date(year, month, day);
                return d.toLocaleDateString('de-DE');
            }
            // ISO‑Format JJJJ‑MM‑TT
            if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
                const d = new Date(dateStr);
                return d.toLocaleDateString('de-DE');
            }
            // fallback: versuchen direkt zu parsen
            const d = new Date(dateStr);
            if (!isNaN(d)) {
                return d.toLocaleDateString('de-DE');
            }
            return dateStr;
        }
        // Hilfsfunktion zur Währungsformatierung (Euro mit zwei Dezimalstellen)
        function formatCurrency(val) {
            const num = parseFloat(val);
            if (isNaN(num)) return val;
            return num.toFixed(2).replace('.', ',');
        }

        let contract = '';
        contract += 'Wohnraum‑Mietvertrag\n\n';
        contract += 'Zwischen folgenden Parteien wird folgender Mietvertrag geschlossen:\n\n';
        contract += 'Vermieter:\n';
        v.vermieter.forEach((ver) => {
            contract += `  ${ver.name}`;
            if (ver.vertreter && ver.vertreter.trim().length > 0) {
                contract += `, vertreten durch ${ver.vertreter.trim()}`;
            }
            contract += '\n';
            contract += `  ${ver.strasse}, ${ver.plz} ${ver.ort}\n`;
            if (ver.telefon) contract += `  Tel.: ${ver.telefon}\n`;
            if (ver.email) contract += `  E‑Mail: ${ver.email}\n`;
            contract += '\n';
        });
        contract += 'Mieter:\n';
        v.mieter.forEach((mi) => {
            contract += `  ${mi.name}`;
            if (mi.geburtsdatum) contract += ` (geb. ${formatDate(mi.geburtsdatum)})`;
            if (mi.vertreter && mi.vertreter.trim().length > 0) {
                contract += `, vertreten durch ${mi.vertreter.trim()}`;
            }
            contract += '\n';
            contract += `  ${mi.strasse}, ${mi.plz} ${mi.ort}\n`;
            if (mi.telefon) contract += `  Tel.: ${mi.telefon}\n`;
            if (mi.email) contract += `  E‑Mail: ${mi.email}\n`;
            contract += '\n';
        });

        contract += '\n§ 1 Mieträume\n';
        contract += `Der Vermieter vermietet dem Mieter zu Wohnzwecken folgendes Objekt: ${v.objekt.art}.\n`;
        contract += `Adresse: ${v.objekt.strasse}, ${v.objekt.plz} ${v.objekt.ort}\n`;
        if (v.objekt.wohnflaeche) contract += `Wohnfläche: ca. ${v.objekt.wohnflaeche} m²\n`;
        if (v.objekt.geschoss) contract += `Geschoss: ${v.objekt.geschoss}\n`;
        if (v.objekt.zimmer) contract += `Zimmer: ${v.objekt.zimmer}\n`;
        contract += 'Weitere Räume: ';
        const raeume = [];
        if (parseInt(v.objekt.kueche) > 0) raeume.push(`${v.objekt.kueche} Küche` + (v.objekt.kueche > 1 ? 'n' : ''));
        if (parseInt(v.objekt.bad) > 0) raeume.push(`${v.objekt.bad} Bad` + (v.objekt.bad > 1 ? 'e' : ''));
        if (parseInt(v.objekt.wc) > 0) raeume.push(`${v.objekt.wc} WC` + (v.objekt.wc > 1 ? 's' : ''));
        if (parseInt(v.objekt.keller) > 0) raeume.push(`${v.objekt.keller} Keller`);
        if (parseInt(v.objekt.boden) > 0) raeume.push(`${v.objekt.boden} Bodenraum` + (v.objekt.boden > 1 ? 'e' : ''));
        if (parseInt(v.objekt.abstell) > 0) raeume.push(`${v.objekt.abstell} Abstellraum` + (v.objekt.abstell > 1 ? 'e' : ''));
        if (parseInt(v.objekt.balkon) > 0) raeume.push(`${v.objekt.balkon} Balkon/Terrasse`);
        if (parseInt(v.objekt.sonstige) > 0) raeume.push(`${v.objekt.sonstige} sonstige Räume`);
        if (parseInt(v.objekt.garage) > 0) raeume.push(`${v.objekt.garage} Garage/Einstellplatz`);
        if (parseInt(v.objekt.hofraum) > 0) raeume.push(`${v.objekt.hofraum} Hofraum`);
        contract += (raeume.length > 0 ? raeume.join(', ') : 'Keine weiteren') + '\n';
        if (v.objekt.nutzung) contract += `Nutzungszweck: ${v.objekt.nutzung}\n`;
        contract += '\nÜbergebene Schlüssel: ';
        const keys = [];
        if (parseInt(v.objekt.schluessel.haus) > 0) keys.push(`${v.objekt.schluessel.haus} Hausschlüssel`);
        if (parseInt(v.objekt.schluessel.wohnung) > 0) keys.push(`${v.objekt.schluessel.wohnung} Wohnungsschlüssel`);
        if (parseInt(v.objekt.schluessel.zimmer) > 0) keys.push(`${v.objekt.schluessel.zimmer} Zimmerschlüssel`);
        if (parseInt(v.objekt.schluessel.boden) > 0) keys.push(`${v.objekt.schluessel.boden} Bodenraumschlüssel`);
        if (parseInt(v.objekt.schluessel.keller) > 0) keys.push(`${v.objekt.schluessel.keller} Kellerschlüssel`);
        if (parseInt(v.objekt.schluessel.briefkasten) > 0) keys.push(`${v.objekt.schluessel.briefkasten} Briefkastenschlüssel`);
        if (v.objekt.schluessel.sonstige) keys.push(v.objekt.schluessel.sonstige);
        contract += (keys.length > 0 ? keys.join(', ') : 'keine') + '\n';

        contract += '\n§ 2 Mietzeit\n';
        if (v.mietzeit.art === 'unbefristet') {
            contract += `Das Mietverhältnis beginnt am ${formatDate(v.mietzeit.beginn)} und läuft auf unbestimmte Zeit.\n`;
            if (v.mietzeit.kuendigungAusschluss && v.mietzeit.kuendigungBis) {
                contract += `Die Vertragsparteien verzichten bis zum ${formatDate(v.mietzeit.kuendigungBis)} wechselseitig auf das Recht zur ordentlichen Kündigung. Eine Kündigung ist erstmals zu diesem Datum mit gesetzlicher Frist zulässig.\n`;
            } else {
                contract += 'Die ordentliche Kündigung richtet sich nach den gesetzlichen Fristen (vgl. §§ 573a–573c BGB).\n';
            }
        } else {
            contract += `Das Mietverhältnis beginnt am ${formatDate(v.mietzeit.beginn)} und endet am ${formatDate(v.mietzeit.ende)}.\n`;
            if (v.mietzeit.grund) contract += `Befristungsgrund: ${v.mietzeit.grund}.\n`;
            contract += 'Ein Anspruch auf Fortsetzung des Mietverhältnisses besteht nicht.\n';
        }

        contract += '\n§ 3 Miete\n';
        contract += `Die monatliche Grundmiete beträgt ${formatCurrency(v.miete.grund)} Euro.\n`;
        if (v.miete.betrieb && parseFloat(v.miete.betrieb) > 0) contract += `Vorauszahlung für Betriebskosten: ${formatCurrency(v.miete.betrieb)} Euro/Monat.\n`;
        if (v.miete.heizung && parseFloat(v.miete.heizung) > 0) contract += `Vorauszahlung für Heizkosten: ${formatCurrency(v.miete.heizung)} Euro/Monat.\n`;
        if (v.miete.kaution && parseFloat(v.miete.kaution) > 0) contract += `Der Mieter leistet eine Kaution in Höhe von ${formatCurrency(v.miete.kaution)} Euro. Diese wird getrennt vom Vermögen des Vermieters verzinslich angelegt und nach Ende des Mietverhältnisses abzüglich offener Forderungen zurückerstattet (vgl. § 551 BGB).\n`;
        // Mieterhöhungen
        if (v.miete.erhoehung === 'staffel' && v.miete.staffeln.length > 0) {
            contract += 'Es wird eine Staffelmiete gemäß § 557a BGB vereinbart: Die Miete erhöht sich wie folgt:\n';
            v.miete.staffeln.forEach((st, idx) => {
                contract += `  Stufe ${idx + 1}: ab Monat ${st.ab} beträgt die Miete ${formatCurrency(st.betrag)} Euro/Monat.\n`;
            });
            contract += 'Während der Laufzeit der Staffelmiete ist eine Mieterhöhung nach §§ 558–559b BGB ausgeschlossen.\n';
        } else if (v.miete.erhoehung === 'index') {
            contract += 'Es wird eine Indexmiete gemäß § 557b BGB vereinbart. Die Miete richtet sich nach dem vom Statistischen Bundesamt veröffentlichten Verbraucherpreisindex. Ausgangsindex: ' + (v.miete.indexAusgang || 'n. n.') + '.\n';
        }

        contract += '\n§ 4 Betriebskosten\n';
        contract += 'Neben der Grundmiete trägt der Mieter die Betriebskosten gemäß Betriebskostenverordnung, soweit sie tatsächlich anfallen, insbesondere für öffentliche Lasten des Grundstücks, Wasserversorgung, Entwässerung, Müllabfuhr, Straßenreinigung, Schnee‑ und Eisbeseitigung, Schornsteinreinigung, Beleuchtung, Versicherungen, Hausreinigung, Ungezieferbekämpfung, Hauswart, Gartenpflege, Aufzug, Gemeinschaftsantennenanlage, Breitbandkabel usw.\n';

        // §5 Zahlung der Miete
        contract += '\n§ 5 Zahlung der Miete\n';
        if (v.zahlung && (v.zahlung.faelligkeit || v.zahlung.iban || v.zahlung.bic)) {
            contract += 'Die Miete ist monatlich im Voraus ';
            if (v.zahlung.faelligkeit) {
                contract += 'spätestens ' + v.zahlung.faelligkeit + ' ';
            } else {
                contract += 'bis zum dritten Werktag eines jeden Monats ';
            }
            contract += 'auf folgendes Konto des Vermieters zu zahlen.\n';
            if (v.zahlung.iban) contract += 'IBAN: ' + v.zahlung.iban + '\n';
            if (v.zahlung.bic) contract += 'BIC: ' + v.zahlung.bic + '\n';
        } else {
            contract += 'Die Miete ist monatlich im Voraus bis zum dritten Werktag eines jeden Monats zu entrichten. Die Bankverbindung des Vermieters wird separat mitgeteilt.\n';
        }

        // Füge gegebenenfalls SEPA-Lastschriftmandat des Mieters nach den Zahlungsinformationen an
        if (v.mandat && (v.mandat.inhaber || v.mandat.iban || v.mandat.bic)) {
            contract += 'Der Mieter erteilt dem Vermieter ein SEPA-Lastschriftmandat';
            const details = [];
            if (v.mandat.inhaber) details.push('Kontoinhaber: ' + v.mandat.inhaber);
            if (v.mandat.iban) details.push('IBAN: ' + v.mandat.iban);
            if (v.mandat.bic) details.push('BIC: ' + v.mandat.bic);
            if (details.length > 0) contract += ' (' + details.join(', ') + ')';
            contract += '.\n';
        }

        // §6 Weitere Vereinbarungen
        contract += '\n§ 6 Weitere Vereinbarungen\n';
        if (v.clauses) {
            if (v.clauses.schoenheits) contract += 'Der Mieter übernimmt die regelmäßigen Schönheitsreparaturen (z. B. das Streichen und Tapezieren von Wänden und Decken, Lackieren von Türen und Fenstern) auf eigene Kosten.\n';
            if (v.clauses.klein) contract += 'Der Mieter trägt die Kosten für Kleinreparaturen bis zu einem Betrag von 100 Euro pro Einzelfall, maximal 300 Euro pro Jahr.\n';
            if (v.clauses.tierhaltung) contract += 'Die Haltung von Kleintieren (z. B. Zierfische, Hamster, Vögel) ist zulässig. Die Haltung von Hunden und Katzen bedarf der vorherigen Zustimmung des Vermieters. Blindenführhunde sind hiervon ausgenommen.\n';
            if (v.clauses.untervermietung) contract += 'Eine Untervermietung des Mietobjekts oder von Teilen davon bedarf der schriftlichen Zustimmung des Vermieters.\n';
            if (v.clauses.besichtigung) contract += 'Der Vermieter ist berechtigt, die Mieträume nach vorheriger Ankündigung während der üblichen Tageszeiten zu besichtigen, um deren Zustand zu überprüfen oder sie Interessenten vorzuführen.\n';
            if (v.clauses.modernisierung) contract += 'Der Mieter hat Modernisierungsmaßnahmen und bauliche Veränderungen, die der Vermieter zur Erhaltung oder Verbesserung der Mietsache vornimmt, zu dulden. Eine Mieterhöhung nach gesetzlichen Vorschriften bleibt vorbehalten.\n';
            if (v.clauses.garten) contract += 'Der Mieter darf vorhandene Gartenflächen mitbenutzen und verpflichtet sich zu deren ordnungsgemäßer Pflege und Instandhaltung.\n';
            if (v.clauses.mehrere) contract += 'Mehrere Mieter haften für die Verpflichtungen aus diesem Mietvertrag als Gesamtschuldner. Erklärungen, die einem Mieter gegenüber abgegeben werden, wirken für und gegen alle Mieter.\n';
            if (v.clauses.hausordnung) contract += 'Der Mieter verpflichtet sich, die Hausordnung des Hauses einzuhalten.\n';
            if (v.clauses.umbauten) contract += 'Bauliche Veränderungen und Einbauten dürfen nur mit vorheriger schriftlicher Zustimmung des Vermieters durchgeführt werden. Der Vermieter kann bei Auszug den Rückbau verlangen.\n';
        // Weitere optionale Klauseln
        if (v.clauses.haftung) contract += 'Der Mieter haftet für alle von ihm, seinen Familienangehörigen, Mitmietern oder Besuchern schuldhaft verursachten Schäden an der Mietsache und hat diese Schäden unverzüglich dem Vermieter anzuzeigen.\n';
        if (v.clauses.rauchmelder) contract += 'Der Mieter ist verpflichtet, die gesetzlichen Rauchmelder in der Mietsache in funktionsfähigem Zustand zu halten und regelmäßig zu prüfen; Batterien sind rechtzeitig auszutauschen.\n';
        if (v.clauses.schriftform) contract += 'Änderungen und Ergänzungen dieses Vertrages bedürfen zu ihrer Wirksamkeit der Schriftform. Mündliche Nebenabreden bestehen nicht.\n';
        if (v.clauses.ruhezeiten) contract += 'Der Mieter verpflichtet sich, die üblichen Ruhezeiten (werktags zwischen 22:00 und 6:00 Uhr sowie an Sonn- und Feiertagen ganztägig) einzuhalten.\n';
        if (v.clauses.instandhaltung) contract += 'Der Mieter verpflichtet sich, die Mietsache pfleglich zu behandeln und kleinere Instandhaltungsmaßnahmen, insbesondere das Austauschen von Leuchtmitteln, Sicherungen und das Ölen von Scharnieren, selbst durchzuführen.\n';
        }
        if (v.sonstigeVereinbarungen && v.sonstigeVereinbarungen.length > 0) {
            const lines = v.sonstigeVereinbarungen.split(/\n+/).map(l => l.trim()).filter(Boolean);
            lines.forEach(line => {
                contract += line + '\n';
            });
        }
        contract += 'Im Übrigen gelten die gesetzlichen Bestimmungen des Bürgerlichen Gesetzbuches (BGB) und – soweit vorhanden – die Hausordnung.\n';

        contract += '\nOrt, Datum: ______________________________\n\n';
        contract += 'Unterschrift Vermieter: ______________________________\n';
        contract += 'Unterschrift Mieter: ______________________________\n';

        // Vertragstext anzeigen
        // Vertrag als formatierte HTML-Vorschau anzeigen (analog zum HTML-Export)
        try {
            const htmlDoc = generateContractHTML();
            const styleMatch = htmlDoc.match(/<style>([\s\S]*?)<\/style>/i);
            const bodyMatch = htmlDoc.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
            const styleTag = styleMatch ? `<style>${styleMatch[1]}</style>` : '';
            const bodyHtml = bodyMatch ? bodyMatch[1] : htmlDoc;
            document.getElementById('vertragstext').innerHTML = styleTag + bodyHtml;
        } catch (e) {
            // Fallback: Plain-Text
            document.getElementById('vertragstext').innerText = contract;
        }
    }

    // Initialisierung
    showStep(0);
});
