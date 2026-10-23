"""SMTP envelope/MIME transport and read-only UID based IMAP protocol adapter."""
import base64
import imaplib
import smtplib
import ssl


class SMTPTransport:
    def __init__(self):
        self.server = None
        self.receipt = None
        self.recipient_results = []

    def prepare(self, config, sender, recipients):
        context = ssl.create_default_context()
        options = dict(host=config['smtp_host'], port=config.get('smtp_port') or 587,
                       timeout=min(120, max(1, config.get('smtp_timeout') or 10)))
        self.server = smtplib.SMTP_SSL(**options, context=context) if config.get('smtp_use_ssl') else smtplib.SMTP(**options)
        self.server.ehlo_or_helo_if_needed()
        if config.get('smtp_use_tls', True) and not config.get('smtp_use_ssl'):
            self.server.starttls(context=context)
            self.server.ehlo()
        if config.get('smtp_user'):
            self.server.login(config['smtp_user'], config.get('smtp_password') or '')
        code, _ = self.server.mail(sender)
        if not 200 <= code < 300:
            raise smtplib.SMTPSenderRefused(code, b'MAIL rejected', sender)
        for recipient in recipients:
            code, _ = self.server.rcpt(recipient)
            self.recipient_results.append(dict(recipient=recipient, code=code))
            if not 200 <= code < 300:
                # No DATA at all when any RCPT is rejected. No silent partial send.
                raise smtplib.SMTPRecipientsRefused({recipient: (code, b'RCPT rejected')})

    def data(self, raw):
        assert self.server is not None
        try:
            code, response = self.server.data(raw)
        except smtplib.SMTPDataError as exc:
            reply = exc.smtp_error if isinstance(exc.smtp_error, bytes) else exc.smtp_error.encode('utf-8')
            self.receipt = dict(code=exc.smtp_code, response_b64=base64.b64encode(reply).decode('ascii'))
            return 'rejected'
        self.receipt = dict(code=code, response_b64=base64.b64encode(response).decode('ascii'))
        return 'accepted' if 200 <= code < 300 else 'rejected'

    def close(self):
        if self.server is not None:
            try:
                self.server.quit()
            except Exception:
                # A QUIT failure cannot undo an acknowledged DATA acceptance.
                try:
                    self.server.close()
                except Exception:
                    pass


class IMAPReadonly:
    def __init__(self, config):
        self.config = config
        self.server = None

    def __enter__(self):
        config = self.config
        self.server = imaplib.IMAP4_SSL(config['imap_host'], int(config.get('imap_port') or 993),
                                       ssl_context=ssl.create_default_context(), timeout=30)
        try:
            self.server.login(config['imap_user'], config['imap_password'])
            status, _ = self.server.select(config.get('imap_mailbox') or 'INBOX', readonly=True)
            if status != 'OK':
                raise OSError('IMAP mailbox selection failed')
            _, next_values = self.server.response('UIDNEXT')
            if not next_values or not next_values[0] or not bytes(next_values[0]).isdigit():
                raise OSError('Missing IMAP UIDNEXT')
            self.uidnext = int(next_values[0])
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def uidvalidity(self):
        assert self.server is not None
        _, values = self.server.response('UIDVALIDITY')
        if not values or not values[0] or not bytes(values[0]).isdigit():
            raise OSError('Missing IMAP UIDVALIDITY')
        return int(values[0])

    def next_uids(self, after, limit=50):
        assert self.server is not None
        # UID FETCH on a bounded numeric window avoids an unbounded SEARCH result.
        start, end = after + 1, min(after + 1000, self.uidnext - 1)
        if start > end:
            return [], after, False
        status, values = self.server.uid('FETCH', f'{start}:{end}', '(UID)')
        if status != 'OK':
            raise OSError('IMAP UID FETCH failed')
        import re
        uids = sorted({int(match) for value in values if isinstance(value, bytes)
                       for match in re.findall(rb'\bUID (\d+)\b', value) if start <= int(match) <= end})
        return uids[:limit], (uids[limit-1] if len(uids) > limit else end), len(uids) > limit or end < self.uidnext - 1

    def raw(self, uid, maximum):
        assert self.server is not None
        status, sizes = self.server.uid('FETCH', str(uid), '(UID RFC822.SIZE)')
        import re
        entries = [value for value in sizes if isinstance(value, bytes)] if status == 'OK' else []
        observed = [int(match) for value in entries for match in re.findall(rb'RFC822.SIZE (\d+)', value)]
        if len(observed) != 1:
            raise OSError('IMAP original size unavailable')
        if observed[0] > maximum:
            raise ValueError('IMAP original exceeds bounded receive step')
        status, values = self.server.uid('FETCH', str(uid), '(UID BODY.PEEK[])')
        parts = [value[1] for value in values if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], bytes)]
        if status != 'OK' or len(parts) != 1 or len(parts[0]) != observed[0]:
            raise OSError('IMAP original incomplete')
        return parts[0]

    def __exit__(self, *args):
        if self.server:
            try:
                # logout never EXPUNGEs; CLOSE would expunge even a selected mailbox.
                self.server.logout()
            except Exception:
                pass
