"""OAuth login for HTTP upstreams that require it (MCP authorization spec: dynamic client registration,
authorization code with PKCE, refresh tokens).

The first connection opens the browser for the login; a small local HTTP server receives the redirect.
Tokens and the registered client are kept in a JSON file per upstream outside the repository
(``~/.openanonymizer/oauth`` by default), so later starts need no browser as long as the refresh token
is valid.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth import oauth2 as _oauth2
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

log = logging.getLogger("anonymizer.proxy")


def _issuer_check_ignoring_trailing_slash(oauth_metadata, expected_issuer: str) -> None:
    """Some servers name their authorization server ``https://host/`` in the resource metadata but
    ``https://host`` as issuer. Same origin, so accept that one difference; everything else stays strict."""
    if str(oauth_metadata.issuer).rstrip("/") == expected_issuer.rstrip("/"):
        return
    _strict_issuer_check(oauth_metadata, expected_issuer)


_strict_issuer_check = _oauth2.validate_metadata_issuer
_oauth2.validate_metadata_issuer = _issuer_check_ignoring_trailing_slash

DEFAULT_DIR = Path.home() / ".openanonymizer" / "oauth"
LOGIN_TIMEOUT = 300.0


class FileTokenStorage:
    """Tokens and client registration of one upstream in one JSON file."""

    def __init__(self, path: Path, redirect_uri: str) -> None:
        self.path = path
        self.redirect_uri = redirect_uri

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, key: str, value: dict) -> None:
        data = self._read()
        data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._read().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write("tokens", tokens.model_dump(mode="json", exclude_none=True))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._read().get("client")
        if not raw:
            return None
        info = OAuthClientInformationFull.model_validate(raw)
        # Registered for another callback port: register again.
        if info.redirect_uris and self.redirect_uri not in [str(u) for u in info.redirect_uris]:
            return None
        return info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write("client", client_info.model_dump(mode="json", exclude_none=True))


class _CallbackServer:
    """Receives one OAuth redirect on 127.0.0.1:port. Bound before the browser opens, so a fast
    (already signed-in) login cannot reach a closed port."""

    def __init__(self, port: int) -> None:
        self.result: dict[str, str] = {}
        self.done = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                query = parse_qs(urlparse(self.path).query)
                if "code" not in query and "error" not in query:
                    self.send_response(404)
                    self.end_headers()
                    return
                outer.result.update({k: v[0] for k, v in query.items()})
                ok = "code" in query
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = ("Login erfolgreich. Du kannst dieses Fenster schliessen." if ok
                       else "Login fehlgeschlagen.")
                self.wfile.write(f"<!doctype html><title>OpenAnonymizer</title><p>{msg}</p>".encode())
                outer.done.set()

            def log_message(self, *args) -> None:  # keep codes out of the console
                pass

        self.server = HTTPServer(("127.0.0.1", port), Handler)
        self.server.timeout = 1.0

    def wait(self, timeout: float) -> AuthorizationCodeResult:
        """Blocking; runs in a worker thread."""
        try:
            waited = 0.0
            while not self.done.is_set() and waited < timeout:
                self.server.handle_request()
                waited += self.server.timeout
        finally:
            self.server.server_close()
        if "code" not in self.result:
            raise TimeoutError(self.result.get("error") or "OAuth login not completed")
        return AuthorizationCodeResult(code=self.result["code"], state=self.result.get("state"),
                                       iss=self.result.get("iss"))


def oauth_provider(name: str, url: str, port: int, directory: str | Path | None = None) -> OAuthClientProvider:
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    storage = FileTokenStorage(Path(directory or DEFAULT_DIR) / f"{name}-{digest}.json", redirect_uri)

    pending: list[_CallbackServer] = []

    async def redirect(auth_url: str) -> None:
        pending.append(_CallbackServer(port))
        log.warning("upstream %s needs a login: opening the browser (%s)", name, auth_url)
        webbrowser.open(auth_url)

    async def callback() -> AuthorizationCodeResult:
        return await anyio.to_thread.run_sync(pending.pop().wait, LOGIN_TIMEOUT)

    metadata = OAuthClientMetadata(client_name=f"OpenAnonymizer proxy ({name})", redirect_uris=[redirect_uri],
                                   grant_types=["authorization_code", "refresh_token"], response_types=["code"],
                                   token_endpoint_auth_method="none")
    return OAuthClientProvider(url, metadata, storage, redirect_handler=redirect, callback_handler=callback)
