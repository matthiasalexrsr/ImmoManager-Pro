/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { TOUR_STEPS } from '../tutorial/steps';

/**
 * Tutorial mode: a guided tour through the main functions (steps in tutorial/steps.js).
 *
 * New users are asked once whether they want the tour; afterwards it starts from the
 * question mark in the top bar (or in the settings). Progress is kept per user in the
 * browser, so a tour that was closed halfway can be continued.
 */
const TutorialContext = createContext({ start: () => {}, active: false });

export function useTutorial() {
  return useContext(TutorialContext);
}

const storageKey = (userId) => `immo.tutorial.${userId || 'anon'}`;

function readState(userId) {
  try {
    return JSON.parse(localStorage.getItem(storageKey(userId)) || '{}');
  } catch {
    return {};
  }
}

function writeState(userId, state) {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(state));
  } catch {
    // private window or blocked storage: the tour still works, it is only not remembered
  }
}

/** The first visible element of a list of selectors. */
function findTarget(selectors) {
  for (const selector of selectors || []) {
    for (const el of document.querySelectorAll(selector)) {
      const rect = el.getBoundingClientRect();
      // visible and on screen (the navigation is moved off screen on phones)
      if (rect.width > 0 && rect.height > 0 && rect.right > 8 && rect.left < window.innerWidth - 8) return el;
    }
  }
  return null;
}

export function TutorialProvider({ children, steps = TOUR_STEPS }) {
  const { user } = useAuth() || {};
  const userId = user?.id;
  const [index, setIndex] = useState(null);          // null: no tour running
  const [offer, setOffer] = useState(false);          // the one-time question to new users

  useEffect(() => {
    if (!userId) return;
    const state = readState(userId);
    if (!state.offered) setOffer(true);
  }, [userId]);

  const start = useCallback((from = 0) => {
    setOffer(false);
    writeState(userId, { ...readState(userId), offered: true });
    setIndex(from);
  }, [userId]);

  const stop = useCallback((finished) => {
    writeState(userId, { ...readState(userId), offered: true, finished: !!finished, step: finished ? 0 : index });
    setIndex(null);
  }, [userId, index]);

  const dismissOffer = useCallback(() => {
    setOffer(false);
    writeState(userId, { ...readState(userId), offered: true });
  }, [userId]);

  const value = useMemo(() => ({ start, active: index !== null }), [start, index]);

  return (
    <TutorialContext.Provider value={value}>
      {children}
      {offer && index === null && <TourOffer onStart={() => start(0)} onLater={dismissOffer} />}
      {index !== null && (
        <TourStep steps={steps} index={index} setIndex={setIndex} onClose={stop} />
      )}
    </TutorialContext.Provider>
  );
}

function TourOffer({ onStart, onLater }) {
  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-labelledby="tour-offer-title">
      <div className="tour-backdrop" />
      <div className="tour-card tour-card-center">
        <div className="tour-kicker">Einführung</div>
        <h2 id="tour-offer-title" className="tour-title">Kurze Tour durch ImmoManager Pro?</h2>
        <p className="tour-body">
          In etwa fünf Minuten zeigen wir Ihnen die wichtigsten Funktionen: Bestand, Mieter und Verträge,
          Zahlungen, Prüfliste, Nebenkostenabrechnung und Wartung. Die Tour lässt sich jederzeit über das
          Fragezeichen oben rechts starten.
        </p>
        <div className="tour-actions">
          <button className="btn btn-ghost" onClick={onLater}>Später</button>
          <button className="btn btn-primary" onClick={onStart} autoFocus>Tour starten</button>
        </div>
      </div>
    </div>
  );
}

const CARD_WIDTH = 360;
const GAP = 14;

function placeCard(rect) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!rect || vw < 700) return null;               // small screens: card at the bottom (CSS)
  const left = Math.min(Math.max(16, rect.left), vw - CARD_WIDTH - 16);
  const below = rect.bottom + GAP;
  if (below + 220 < vh) return { top: below, left };
  const above = rect.top - GAP - 230;
  if (above > 16) return { top: above, left };
  const right = rect.right + GAP;                    // tall targets (navigation): beside them
  if (right + CARD_WIDTH < vw) return { top: Math.max(16, Math.min(rect.top, vh - 260)), left: right };
  return null;
}

function TourStep({ steps, index, setIndex, onClose }) {
  const step = steps[index];
  const navigate = useNavigate();
  const location = useLocation();
  const [rect, setRect] = useState(null);
  const [searching, setSearching] = useState(true);
  const cardRef = useRef(null);
  const last = index === steps.length - 1;

  useEffect(() => {
    if (step.route && location.pathname !== step.route) {
      navigate(step.route);
      window.scrollTo(0, 0);                         // each page starts at its top
    }
  }, [step.route, location.pathname, navigate]);

  // find the target once the page has loaded it; keep the highlight on it while the page settles
  useLayoutEffect(() => {
    let cancelled = false;
    let tries = 0;
    let element = null;
    setRect(null);
    setSearching(Boolean(step.target));
    const measure = () => {
      if (cancelled) return;
      if (!element || !element.isConnected) element = findTarget(step.target);
      if (element) {
        let r = element.getBoundingClientRect();
        const tall = r.height > window.innerHeight * 0.6;
        if (!element.dataset.tourScrolled) {
          // short targets come fully into view; tall ones (navigation, long lists) only when far below
          if (!tall || r.top > window.innerHeight * 0.6) element.scrollIntoView({ block: tall ? 'start' : 'nearest' });
          element.dataset.tourScrolled = '1';
          r = element.getBoundingClientRect();
        }
        // highlight the visible part, below the sticky top bar
        const barBottom = document.querySelector('.top-bar')?.getBoundingClientRect().bottom || 0;
        const inside = element.closest('.sidebar') ? 0 : barBottom;
        const top = Math.max(r.top, inside + 8);
        const bottom = Math.min(r.bottom, window.innerHeight - 8);
        setRect({ top, left: r.left, width: r.width, height: Math.max(bottom - top, 24), bottom, right: r.right });
        setSearching(false);
      } else if (tries > 25) {
        setSearching(false);                         // not on this page (or screen too small): centred card
      }
      tries += 1;
    };
    if (!step.target) return undefined;
    measure();
    const timer = setInterval(measure, 200);
    window.addEventListener('resize', measure);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener('resize', measure);
      if (element) delete element.dataset.tourScrolled;
    };
  }, [step]);

  const next = useCallback(() => (last ? onClose(true) : setIndex(i => i + 1)), [last, onClose, setIndex]);
  const back = useCallback(() => setIndex(i => Math.max(0, i - 1)), [setIndex]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose(false);
      else if (event.key === 'ArrowRight' || event.key === 'Enter') next();
      else if (event.key === 'ArrowLeft') back();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, back, onClose]);

  useEffect(() => { cardRef.current?.focus(); }, [index]);

  const position = placeCard(rect);
  const centred = !rect && !searching;
  const pad = 6;

  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-labelledby="tour-step-title">
      {rect ? (
        <div className="tour-spotlight" style={{
          top: rect.top - pad, left: rect.left - pad, width: rect.width + 2 * pad, height: rect.height + 2 * pad,
        }} />
      ) : <div className="tour-backdrop" />}
      <div
        ref={cardRef}
        tabIndex={-1}
        className={`tour-card ${centred ? 'tour-card-center' : ''} ${!position && !centred ? 'tour-card-dock' : ''}`}
        style={position ? { top: position.top, left: position.left, width: CARD_WIDTH } : undefined}
        aria-live="polite"
      >
        <div className="tour-kicker">Schritt {index + 1} von {steps.length}</div>
        <h2 id="tour-step-title" className="tour-title">{step.title}</h2>
        <p className="tour-body">{step.body}</p>
        <div className="tour-progress" aria-hidden="true">
          <span style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
        </div>
        <div className="tour-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => onClose(false)}>Beenden</button>
          <span className="tour-spacer" />
          {index > 0 && <button className="btn btn-secondary btn-sm" onClick={back}>Zurück</button>}
          <button className="btn btn-primary btn-sm" onClick={next}>{last ? 'Fertig' : 'Weiter'}</button>
        </div>
      </div>
    </div>
  );
}
