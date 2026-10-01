import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Building2, CircleAlert, FileText, KeyRound, LoaderCircle, ShieldCheck, Smartphone, Wallet } from 'lucide-react';
import { getSetupStatus, login, setupOwner } from '../api';
import { useTranslation } from '../i18n';
import './Login.css';

export default function Login() {
  const { t } = useTranslation();
  const [setup, setSetup] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [requiresTwoFactor, setRequiresTwoFactor] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const submitting = useRef(false);
  const usernameInput = useRef(null);
  const codeInput = useRef(null);
  const errorMessage = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    setSetup(null);
    setStatusError(null);
    getSetupStatus({ signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (typeof result?.setup_required !== 'boolean' || typeof result?.setup_allowed !== 'boolean') throw new Error(t('auth.setup.invalidStatus'));
        setSetup(result);
      })
      .catch(err => { if (!controller.signal.aborted) setStatusError(err.message); });
    return () => controller.abort();
  }, [revision, t]);

  const isSetup = setup?.setup_required && setup?.setup_allowed;
  const blocked = setup?.setup_required && !setup?.setup_allowed;
  const ready = Boolean(setup);

  useEffect(() => {
    if (!ready || blocked) return;
    if (requiresTwoFactor) codeInput.current?.focus();
    else if (error) errorMessage.current?.focus();
    else usernameInput.current?.focus();
  }, [ready, blocked, requiresTwoFactor, error]);

  const handleSubmit = async event => {
    event.preventDefault();
    if (submitting.current || !ready || blocked) return;
    submitting.current = true;
    setLoading(true);
    setError(null);
    try {
      if (isSetup) {
        await setupOwner(username, email, fullName, password);
        // Setup is committed before login. A login failure must not create another owner.
        setSetup({ ...setup, setup_required: false });
      }
      await login(username, password, totpCode);
      navigate('/');
    } catch (err) {
      if (err.requiresTwoFactor) setRequiresTwoFactor(true);
      if (isSetup && err.statusCode === 409) setRevision(value => value + 1);
      setError(err.message);
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  };

  const title = isSetup ? t('auth.setup.title') : requiresTwoFactor ? t('auth.twoFactor.title') : t('auth.login.title');
  const TitleIcon = isSetup ? ShieldCheck : requiresTwoFactor ? Smartphone : KeyRound;

  return (
    <main className="login-access">
      <div className="login-access-shell">
        <section className="login-access-story" aria-label={t('brand.productName')}>
          <div className="login-access-brand">
            <span className="login-access-mark" aria-hidden="true"><Building2 size={25} strokeWidth={1.5} /></span>
            <span>ImmoManager <span className="login-access-pro">Pro</span></span>
          </div>
          <div className="login-access-intro">
            <h2>{t('brand.slogan')}</h2>
            <div className="login-access-topics">
              <span><Building2 size={16} aria-hidden="true" />{t('navigation.main.properties')}</span>
              <span><Wallet size={16} aria-hidden="true" />{t('navigation.main.finance')}</span>
              <span><FileText size={16} aria-hidden="true" />{t('navigation.main.documents')}</span>
            </div>
          </div>
          <svg className="login-access-city" viewBox="0 0 460 310" fill="none" aria-hidden="true">
            <path d="M24 278H436" stroke="currentColor" strokeOpacity=".23" />
            <path d="M54 277V174L116 145L177 174V277" fill="#223c4e" stroke="#567383" />
            <path d="M164 277V82L276 44L362 91V277" fill="#2c4b5d" stroke="#77909b" />
            <path d="M276 44V277M164 82L276 121L362 91" stroke="#77909b" />
            <path d="M340 277V193L396 175L428 198V277" fill="#223c4e" stroke="#567383" />
            <path d="M184 121L209 130V155L184 146ZM228 137L253 146V171L228 162ZM184 169L209 178V203L184 194ZM228 185L253 194V219L228 210ZM184 217L209 226V251L184 242Z" fill="#78949a" />
            <path d="M294 134L318 126V151L294 159ZM330 122L344 117V142L330 147ZM294 180L318 172V197L294 205ZM330 168L344 163V188L330 193ZM294 226L318 218V243L294 251Z" fill="#9ab5b1" />
            <path d="M228 233L253 242V277H228ZM77 190H96V211H77ZM128 190H147V211H128ZM77 231H96V252H77ZM128 231H147V252H128Z" fill="#ceb892" />
            <path d="M367 218H382V239H367ZM398 218H413V239H398Z" fill="#78949a" />
            <path d="M32 278V240M20 247L32 234L44 247M32 255L47 243M32 263L17 251" stroke="#79a9a2" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div className="login-access-story-rule" aria-hidden="true"><span /></div>
        </section>

        <section className="login-access-panel" aria-labelledby="login-access-title">
          <header className="login-access-heading">
            <span className="login-access-heading-icon" aria-hidden="true"><TitleIcon size={24} strokeWidth={1.6} /></span>
            <h1 id="login-access-title">{title}</h1>
            {isSetup && <p>{t('auth.setup.description')}</p>}
            {requiresTwoFactor && <p id="login-code-hint">{t('auth.twoFactor.description')}</p>}
          </header>
          {!setup && !statusError && <div className="login-access-status" role="status"><LoaderCircle className="login-access-spinner" size={20} aria-hidden="true" />{t('ui.table.loading')}</div>}
          {statusError && <div className="login-access-notice" role="alert">
            <CircleAlert size={19} aria-hidden="true" />
            <div><p>{statusError}</p><button type="button" className="login-access-retry" onClick={() => setRevision(value => value + 1)}>{t('ui.buttons.retry')}<ArrowRight size={15} aria-hidden="true" /></button></div>
          </div>}
          {blocked && <div className="login-access-notice" role="alert"><ShieldCheck size={20} aria-hidden="true" /><p>{t('auth.setup.localOnly')}</p></div>}
          {setup && !blocked && <form onSubmit={handleSubmit} aria-busy={loading} aria-labelledby="login-access-title">
            {error && <div className="login-access-notice" role="alert" ref={errorMessage} tabIndex={-1}><CircleAlert size={19} aria-hidden="true" /><p>{error}</p></div>}
            <fieldset className="login-access-fields" disabled={loading}>
              <div className="login-access-field">
                <label htmlFor="login-username">{t('auth.login.username')}</label>
                <input ref={usernameInput} id="login-username" name="username" type="text" value={username} onChange={event => { setUsername(event.target.value); setRequiresTwoFactor(false); setTotpCode(''); if (requiresTwoFactor) setError(null); }} required autoComplete="username" autoCapitalize="none" spellCheck={false} />
              </div>
              {isSetup && <>
                <div className="login-access-field">
                  <label htmlFor="setup-email">{t('auth.register.email')}</label>
                  <input id="setup-email" name="email" type="email" value={email} onChange={event => setEmail(event.target.value)} required autoComplete="email" autoCapitalize="none" spellCheck={false} />
                </div>
                <div className="login-access-field">
                  <label htmlFor="setup-name">{t('auth.setup.fullName')}</label>
                  <input id="setup-name" name="name" type="text" value={fullName} onChange={event => setFullName(event.target.value)} required autoComplete="name" />
                </div>
              </>}
              <div className="login-access-field">
                <label htmlFor="login-password">{t('auth.login.password')}</label>
                <input id="login-password" name="password" type="password" value={password} onChange={event => setPassword(event.target.value)} required minLength={8} autoComplete={isSetup ? 'new-password' : 'current-password'} aria-describedby={isSetup ? 'login-password-hint' : undefined} />
                {isSetup && <small id="login-password-hint">{t('auth.password.requirements')}</small>}
              </div>
              {requiresTwoFactor && <div className="login-access-field login-access-code">
                <label htmlFor="login-totp">{t('auth.twoFactor.code')}</label>
                <input ref={codeInput} id="login-totp" name="totp" type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" aria-describedby="login-code-hint" value={totpCode} onChange={event => setTotpCode(event.target.value.replace(/\D/g, '').slice(0, 6))} required />
              </div>}
              <button type="submit" className="login-access-submit" disabled={loading}>
                {loading && <LoaderCircle className="login-access-spinner" size={18} aria-hidden="true" />}
                <span aria-live="polite">{loading ? t('ui.table.loading') : isSetup ? t('auth.setup.submit') : t('auth.login.submit')}</span>
                {!loading && <ArrowRight size={18} aria-hidden="true" />}
              </button>
            </fieldset>
            {!isSetup && <p className="login-access-account-note"><ShieldCheck size={17} aria-hidden="true" /><span>{t('auth.setup.approvedOnly')}</span></p>}
          </form>}
        </section>
      </div>
    </main>
  );
}
