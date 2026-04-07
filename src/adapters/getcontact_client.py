"""
getcontact_client — Low-level GetContact API v2.8 client with AES+HMAC.

Handles the encrypted request/response protocol used by the GetContact
mobile app backend. Requires GETCONTACT_TOKEN and GETCONTACT_AES_KEY
environment variables (extracted from a rooted device running the app).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import urllib.request
import urllib.error

log = logging.getLogger("hanna.recon.getcontact")

# ── Protocol constants ───────────────────────────────────────────

_API_BASE = "https://pbssrv-centralevents.com"
_API_VERSION = "v2.8"
_APP_VERSION = "5.6.2"
_ANDROID_OS = "android 6.0"
_DEVICE_ID = "8edbe110a4079830"
_COUNTRY = "UA"

_HMAC_KEY = b'y1gY|J%&6V kTi$>_Ali8]/xCqmMMP1$*)I8FwJ,*r_YUM 4h?@7+@#<>+w-e3VW'


# ── AES cipher (ECB, PKCS7 padding) ─────────────────────────────

class _AESCipher:
    """AES-ECB encrypt/decrypt for GetContact wire protocol."""

    def __init__(self, hex_key: str) -> None:
        from Crypto.Cipher import AES as _AES  # type: ignore[import-untyped]
        self._bs = _AES.block_size
        self._key = binascii.unhexlify(hex_key)

    def encrypt(self, plaintext: str) -> bytes:
        from Crypto.Cipher import AES as _AES
        padded = self._pad(plaintext)
        cipher = _AES.new(self._key, _AES.MODE_ECB)
        return base64.b64encode(cipher.encrypt(padded.encode("utf-8")))

    def decrypt(self, ciphertext: str) -> str:
        from Crypto.Cipher import AES as _AES
        raw = base64.b64decode(ciphertext)
        cipher = _AES.new(self._key, _AES.MODE_ECB)
        return self._unpad(cipher.decrypt(raw)).decode("utf-8")

    def _pad(self, s: str) -> str:
        pad_len = self._bs - (len(s) % self._bs)
        return s + chr(pad_len) * pad_len

    @staticmethod
    def _unpad(s: bytes) -> bytes:
        return s[: -s[-1]]


# ── Signature helper ─────────────────────────────────────────────

def _sign(timestamp: str, body_json: str) -> str:
    """HMAC-SHA256 signature as required by GetContact API."""
    message = f"{timestamp}-{body_json}"
    sig = hmac.new(_HMAC_KEY, message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")


# ── Client class ─────────────────────────────────────────────────

class GetContactClient:
    """
    Stateless GetContact API client.

    Usage::

        client = GetContactClient(token="...", aes_key="...")
        info = client.search_phone("+380930075122")
        tags = client.get_tags("+380930075122")
    """

    def __init__(self, token: str, aes_key: str, timeout: float = 10.0) -> None:
        if not token or not aes_key:
            raise ValueError("GetContact requires both TOKEN and AES_KEY")
        self._token = token.strip()
        self._aes = _AESCipher(aes_key.strip())
        self._timeout = timeout

    # ── Public API ───────────────────────────────────────────────

    def search_phone(self, phone: str) -> dict[str, Any] | None:
        """
        Search by phone number — returns profile info (displayName, etc).
        Returns None on error or if the number is not found.
        """
        return self._call("search", phone, "search")

    def get_tags(self, phone: str) -> list[str]:
        """
        Get contact-book tags (how others saved this number).
        Returns list of tag strings, empty list on error.
        """
        result = self._call("number-detail", phone, "details")
        if not result:
            return []
        tags_raw = result.get("result", {}).get("tags", [])
        return [
            t["tag"] if isinstance(t, dict) else str(t)
            for t in tags_raw
            if t
        ]

    def get_full_info(self, phone: str) -> dict[str, Any]:
        """
        Combined search + tags in one call sequence.
        Returns dict with name, displayName, tags, country, remaining_searches, etc.
        """
        info: dict[str, Any] = {
            "phone": phone,
            "displayName": None,
            "name": None,
            "country": None,
            "email": None,
            "is_spam": False,
            "tags": [],
            "remaining_searches": None,
        }

        # 1) Profile search
        search_result = self._call("search", phone, "search")
        if search_result:
            profile = search_result.get("result", {}).get("profile", {})
            info["displayName"] = profile.get("displayName")
            info["name"] = (
                f"{profile.get('name', '') or ''} {profile.get('surname', '') or ''}".strip()
                or None
            )
            info["country"] = profile.get("country") or profile.get("countryCode")
            info["email"] = profile.get("email")
            spam = search_result.get("result", {}).get("spamInfo", {})
            info["is_spam"] = spam.get("degree") == "high" if spam else False
            usage = (
                search_result.get("result", {})
                .get("subscriptionInfo", {})
                .get("usage", {})
                .get("search", {})
            )
            info["remaining_searches"] = usage.get("remainingCount")

        # 2) Tags
        info["tags"] = self.get_tags(phone)

        return info

    # ── Internal ─────────────────────────────────────────────────

    def _call(self, endpoint: str, phone: str, source: str) -> dict[str, Any] | None:
        """Encrypted POST to GetContact API."""
        ts = str(int(time.time()))

        body_dict = {
            "countryCode": _COUNTRY,
            "source": source,
            "token": self._token,
            "phoneNumber": phone,
        }
        body_json = json.dumps(body_dict, separators=(",", ":"))

        sig = _sign(ts, body_json)
        encrypted_body = self._aes.encrypt(body_json)
        payload = json.dumps({"data": encrypted_body.decode("utf-8")}).encode("utf-8")

        url = f"{_API_BASE}/{_API_VERSION}/{endpoint}"
        headers = {
            "X-App-Version": _APP_VERSION,
            "X-Token": self._token,
            "X-Os": _ANDROID_OS,
            "X-Client-Device-Id": _DEVICE_ID,
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "deflate",
            "X-Req-Timestamp": ts,
            "X-Req-Signature": sig,
            "X-Encrypted": "1",
        }

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            raw_body = resp.read().decode("utf-8")
            resp_data = json.loads(raw_body)
            decrypted = self._aes.decrypt(resp_data["data"])
            result = json.loads(decrypted)
            log.debug("GetContact %s → %s", endpoint, json.dumps(result, ensure_ascii=False)[:200])
            return result
        except urllib.error.HTTPError as e:
            log.warning("GetContact API %s HTTP %d", endpoint, e.code)
            return None
        except (json.JSONDecodeError, KeyError, ValueError, binascii.Error) as e:
            log.warning("GetContact API %s decode error: %s", endpoint, e)
            return None
        except Exception as e:
            log.warning("GetContact API %s error: %s", endpoint, e)
            return None
