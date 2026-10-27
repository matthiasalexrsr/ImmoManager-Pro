"""Small path-style S3 SigV4 transport for original-object operations.

No credential discovery, proxy inheritance, redirects, public URLs or bucket actions.
Only the configured endpoint receives signed requests. No optional SDK is required.
"""
import hashlib
import hmac
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import safe_xml


class S3ProtocolError(RuntimeError):
    def __init__(self, code):
        self.response = {"Error": {"Code": str(code)}}
        super().__init__("S3 request failed")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class S3Client:
    def __init__(self, endpoint, access_key, secret_key, region, *, clock=None, session_token=""):
        self.endpoint = (endpoint or f"https://s3.{region}.amazonaws.com").rstrip("/")
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("S3-Endpunkt muss eine HTTP(S)-Adresse ohne Zugangsdaten sein")
        if not access_key or not secret_key or any(char in access_key for char in "\r\n/"):
            raise ValueError("S3-Zugangsdaten fehlen oder sind ungültig")
        self.access_key, self.secret_key, self.region = access_key, secret_key, region
        self.session_token = session_token
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, method, bucket, key, *, body=b"", headers=None):
        path = urlsplit(self.endpoint).path + "/" + quote(bucket, safe="-_.~") + "/" + quote(key, safe="/-_.~")
        host = urlsplit(self.endpoint).netloc
        url = urlsplit(self.endpoint)._replace(path=path).geturl()
        now = self.clock().astimezone(timezone.utc)
        timestamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        digest = hashlib.sha256(body).hexdigest()
        signed = {"host": host, "x-amz-date": timestamp, "x-amz-content-sha256": digest,
                  **{name.lower(): str(value).strip() for name, value in (headers or {}).items()}}
        if self.session_token:
            signed["x-amz-security-token"] = self.session_token
        if any("\n" in value or "\r" in value for value in signed.values()):
            raise S3ProtocolError("InvalidHeader")
        names = ";".join(sorted(signed))
        canonical_headers = "".join(name + ":" + " ".join(signed[name].split()) + "\n" for name in sorted(signed))
        canonical = "\n".join((method, path, "", canonical_headers, names, digest))
        scope = f"{day}/{self.region}/s3/aws4_request"
        to_sign = "AWS4-HMAC-SHA256\n" + timestamp + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
        def mac(key, value):
            return hmac.new(key, value.encode(), hashlib.sha256).digest()
        signing = ("AWS4" + self.secret_key).encode()
        for value in (day, self.region, "s3", "aws4_request"):
            signing = mac(signing, value)
        signature = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
        signed["authorization"] = f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, SignedHeaders={names}, Signature={signature}"
        request = Request(url, data=body if method == "PUT" else None, headers=signed, method=method)
        try:
            return self.opener.open(request, timeout=30)
        except HTTPError as exc:
            try:
                raw = exc.read(8192)
                code = safe_xml.fromstring(raw).findtext("Code") or str(exc.code)
            except (ValueError, ET.ParseError):
                code = str(exc.code)
            finally:
                exc.close()
            raise S3ProtocolError(code) from None
        except (URLError, OSError):
            raise S3ProtocolError("TransportUnavailable") from None

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch=None):
        headers = {"content-type": ContentType, **{"x-amz-meta-" + name: value for name, value in Metadata.items()}}
        if IfNoneMatch:
            headers["if-none-match"] = IfNoneMatch
        with self._request("PUT", Bucket, Key, body=Body, headers=headers):
            return {}

    def get_object(self, *, Bucket, Key, Range=None):
        response = self._request("GET", Bucket, Key, headers={"range": Range} if Range else {})
        metadata = {name.lower().removeprefix("x-amz-meta-"): value for name, value in response.headers.items()
                    if name.lower().startswith("x-amz-meta-")}
        return {"Body": response, "Metadata": metadata}

    def head_object(self, *, Bucket, Key):
        with self._request("HEAD", Bucket, Key):
            return {}

    def delete_object(self, *, Bucket, Key):
        with self._request("DELETE", Bucket, Key):
            return {}
