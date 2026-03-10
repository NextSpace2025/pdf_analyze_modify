"""Optional external API client for filename suggestion."""

from __future__ import annotations

import json
from urllib import error, request
from urllib.parse import urlparse


def suggest_name_with_external_api(
    *,
    api_base_url: str,
    api_key: str,
    api_model: str,
    reason: str,
    current_name: str,
    mcp_server_name: str,
    mcp_server_url: str,
    timeout_sec: int = 10,
) -> tuple[str | None, str | None]:
    """
    Call an external API endpoint and return a suggested filename.
    Expected endpoint: POST {api_base_url}/suggest-name
    Expected JSON response: {"suggested_name": "new_file.pdf"}
    """
    base = (api_base_url or "").strip().rstrip("/")
    if not base:
        return None, "External API base URL is empty."

    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        return None, "External API base URL must start with http:// or https://"

    url = f"{base}/suggest-name"
    payload = {
        "reason": reason or "",
        "current_name": current_name,
        "model": api_model or "",
        "mcp": {
            "name": mcp_server_name or "context7",
            "url": mcp_server_url or "",
        },
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = request.Request(url=url, data=data, headers=headers, method="POST")
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            name = (parsed.get("suggested_name") or "").strip()
            if not name:
                return None, "External API did not return suggested_name."
            return name, None
    except ValueError as e:
        return None, f"Invalid URL: {e}"
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return None, f"HTTP {e.code}: {body[:180]}"
    except error.URLError as e:
        return None, f"Connection failed: {e.reason}"
    except (TimeoutError, json.JSONDecodeError) as e:
        return None, f"External API response error: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return None, f"External API call failed: {e}"
