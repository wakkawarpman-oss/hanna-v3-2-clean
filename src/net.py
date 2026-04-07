"""Network helpers with centralized proxy policy enforcement."""
from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from config import MAX_BODY_BYTES, REQUIRE_PROXY


def proxy_aware_request(
    url: str,
    method: str = "GET",
    timeout: float = 5.0,
    proxy: str | None = None,
    headers: dict[str, str] | None = None,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> tuple[int, dict[str, str], str]:
    """Execute HTTP request with optional proxy and capped body read."""
    if REQUIRE_PROXY and not proxy:
        raise RuntimeError("HANNA_REQUIRE_PROXY=1 but no proxy provided for HTTP request")

    req = urllib.request.Request(url, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    ) if proxy else urllib.request.build_opener()

    try:
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            hdrs = {k: v for k, v in resp.headers.items()}
            body = ""
            if method.upper() != "HEAD":
                body = resp.read(max_body_bytes).decode("utf-8", errors="replace")
            return status, hdrs, body
    except urllib.error.HTTPError as exc:
        return int(exc.code), {}, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, {}, ""
