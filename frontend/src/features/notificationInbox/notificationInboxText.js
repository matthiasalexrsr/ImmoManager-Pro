const COPY = {
  de: {
    title: 'Benachrichtigungen',
    loading: 'Benachrichtigungen werden geprüft …',
    empty: 'Keine ungelesenen Benachrichtigungen.',
    unread: count => `${count} ungelesen insgesamt`,
    loadMore: 'Weitere laden',
    markRead: 'Als gelesen markieren',
    retry: 'Erneut prüfen',
    reload: 'Inbox neu laden',
    changed: 'Die Benachrichtigungen haben sich während des Ladens geändert. Bitte die erste Seite neu laden.',
    unavailable: 'Benachrichtigungen konnten nicht aktualisiert werden.',
    access: 'Der Zugriff auf Benachrichtigungen hat sich geändert.',
    invalid: 'Die Benachrichtigungsantwort ist ungültig. Bitte neu laden.',
    request: 'Benachrichtigungen konnten nicht geladen werden.',
    unknownDate: 'Historischer Zeitpunkt unbekannt',
  },
  en: {
    title: 'Notifications',
    loading: 'Checking notifications …',
    empty: 'No unread notifications.',
    unread: count => `${count} unread in total`,
    loadMore: 'Load more',
    markRead: 'Mark as read',
    retry: 'Check again',
    reload: 'Reload inbox',
    changed: 'Notifications changed while loading. Reload the first page.',
    unavailable: 'Notifications could not be refreshed.',
    access: 'Your access to notifications has changed.',
    invalid: 'The notification response is invalid. Please reload.',
    request: 'Notifications could not be loaded.',
    unknownDate: 'Historical time unavailable',
  },
  es: {
    title: 'Notificaciones',
    loading: 'Comprobando notificaciones …',
    empty: 'No hay notificaciones sin leer.',
    unread: count => `${count} sin leer en total`,
    loadMore: 'Cargar más',
    markRead: 'Marcar como leída',
    retry: 'Comprobar de nuevo',
    reload: 'Recargar bandeja',
    changed: 'Las notificaciones cambiaron durante la carga. Vuelva a cargar la primera página.',
    unavailable: 'No se pudieron actualizar las notificaciones.',
    access: 'Ha cambiado su acceso a las notificaciones.',
    invalid: 'La respuesta de notificaciones no es válida. Vuelva a cargar.',
    request: 'No se pudieron cargar las notificaciones.',
    unknownDate: 'Hora histórica no disponible',
  },
};

export function inboxText(locale, key, params) {
  const lang = String(locale || 'de').toLowerCase().startsWith('en')
    ? 'en'
    : String(locale || 'de').toLowerCase().startsWith('es') ? 'es' : 'de';
  const value = COPY[lang][key] ?? COPY.de[key] ?? key;
  return typeof value === 'function' ? value(params?.count ?? params ?? 0) : value;
}
