import { useTranslation } from '../i18n';
import './DemoMode.css';

const TEXT = {
  de: { region: 'Verwaltung Baden-Württemberg', intro: 'Ihre vorbereitete Verwaltung zum Kennenlernen.',
    access: 'Demozugang', username: 'Benutzername', password: 'Passwort', use: 'Demozugang übernehmen' },
  en: { region: 'Baden-Württemberg portfolio', intro: 'Your prepared workspace to explore.',
    access: 'Demo sign-in', username: 'Username', password: 'Password', use: 'Use demo credentials' },
  es: { region: 'Administración Baden-Württemberg', intro: 'Su administración preparada para conocer las funciones.',
    access: 'Acceso demo', username: 'Usuario', password: 'Contraseña', use: 'Usar acceso demo' },
};

export function DemoIndicator() {
  const { locale } = useTranslation();
  const words = TEXT[locale?.slice(0, 2)] || TEXT.de;
  return <div className="demo-context-bar" aria-label="Demo">
    <span className="demo-mode-pill">Demo</span><span>{words.region}</span>
  </div>;
}

export function DemoLoginCard({ credentials, onUse, disabled }) {
  const { locale } = useTranslation();
  const words = TEXT[locale?.slice(0, 2)] || TEXT.de;
  return <section className="demo-login-card" aria-labelledby="demo-login-heading">
    <div className="demo-login-title"><span className="demo-mode-pill">Demo</span>
      <h2 id="demo-login-heading">{words.region}</h2></div>
    <p>{words.intro}</p>
    {credentials && <>
      <dl aria-label={words.access}>
        <div><dt>{words.username}</dt><dd><code>{credentials.username}</code></dd></div>
        <div><dt>{words.password}</dt><dd><code>{credentials.password}</code></dd></div>
      </dl>
      <button type="button" className="btn btn-secondary btn-block" disabled={disabled}
        onClick={() => onUse(credentials)}>{words.use}</button>
    </>}
  </section>;
}
