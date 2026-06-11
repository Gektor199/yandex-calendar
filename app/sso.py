from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings


class SSOError(RuntimeError):
    pass


@dataclass(frozen=True)
class SSOProfile:
    email: str
    name: str


class SSOClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None) -> None:
        self.settings = settings
        self.http_client = http_client

    def authorization_url(self, *, state: str, redirect_uri: str, code_verifier: str = "") -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.sso_client_id,
            "redirect_uri": redirect_uri,
            "scope": self.settings.sso_scopes,
            "state": state,
        }
        if code_verifier:
            params["code_challenge_method"] = "S256"
            params["code_challenge"] = self._pkce_challenge(code_verifier)
        return f"{self.settings.sso_authorization_url}?{urlencode(params)}"

    async def profile_from_code(self, *, code: str, redirect_uri: str, code_verifier: str = "") -> SSOProfile:
        token_payload = await self._exchange_code(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        profile = await self._load_userinfo(token_payload)
        email = str(profile.get("email") or profile.get("preferred_username") or "").strip().lower()
        if not email:
            raise SSOError("SSO не вернул email пользователя.")
        name = str(profile.get("name") or email).strip()
        return SSOProfile(email=email, name=name)

    async def _exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str = "") -> dict[str, Any]:
        if self.http_client is None:
            raise SSOError("SSO HTTP client не настроен.")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.settings.sso_client_id,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        auth = None
        if self.settings.sso_client_auth_method == "basic":
            auth = (self.settings.sso_client_id, self.settings.sso_client_secret)
        else:
            data["client_secret"] = self.settings.sso_client_secret
        try:
            response = await self.http_client.post(
                self.settings.sso_token_url,
                data=data,
                headers={"Accept": "application/json"},
                auth=auth,
            )
        except httpx.HTTPError as exc:
            raise SSOError("Не удалось обменять SSO code на token.") from exc
        if response.status_code >= 400:
            raise SSOError(
                f"SSO token endpoint вернул HTTP {response.status_code}: "
                f"{self._error_excerpt(response)}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise SSOError("SSO token endpoint вернул некорректный ответ.")
        return payload

    async def _load_userinfo(self, token_payload: dict[str, Any]) -> dict[str, Any]:
        access_token = str(token_payload.get("access_token") or "")
        if not self.settings.sso_userinfo_url or not access_token:
            raise SSOError("SSO token не содержит access_token для запроса userinfo.")
        if self.http_client is None:
            raise SSOError("SSO HTTP client не настроен.")
        try:
            response = await self.http_client.get(
                self.settings.sso_userinfo_url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise SSOError("Не удалось получить профиль SSO пользователя.") from exc
        if response.status_code >= 400:
            raise SSOError(
                f"SSO userinfo endpoint вернул HTTP {response.status_code}: "
                f"{self._error_excerpt(response)}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise SSOError("SSO userinfo endpoint вернул некорректный ответ.")
        return payload

    def _error_excerpt(self, response: httpx.Response) -> str:
        text = response.text.strip()
        if self.settings.sso_client_secret:
            text = text.replace(self.settings.sso_client_secret, "[secret]")
        return text[:500] or "пустой ответ"

    def _pkce_challenge(self, code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
