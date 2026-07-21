"""Fixed Xrocket client.

Uses urllib fallback and ensures Authorization and X-API-KEY headers are sent.
Supports XROCKET_INSECURE env to skip TLS verification for local testing.
"""
from __future__ import annotations

import os
import hmac
import hashlib
import json
import logging
import asyncio
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

XROCKET_API_URL = os.getenv("XROCKET_API_URL", "https://pay.api.xrocket.exchange/")
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY")
XROCKET_WEBHOOK_SECRET = os.getenv("XROCKET_WEBHOOK_SECRET")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if XROCKET_API_KEY:
        headers["Authorization"] = f"Bearer {XROCKET_API_KEY}"
        headers["X-API-KEY"] = XROCKET_API_KEY
    return headers


def _http_post_sync(url: str, payload: dict, headers: dict, timeout: int = 20) -> dict:
    insecure = os.getenv("XROCKET_INSECURE", "false").lower() in ("1", "true", "yes")
    # Prefer requests if available for better TLS control
    try:
        import requests
    except Exception:
        requests = None

    if requests is not None:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout, verify=not insecure)
        try:
            data = resp.json()
        except Exception:
            data = None
        if not resp.ok:
            body_text = resp.text if hasattr(resp, 'text') else str(resp)
            raise RuntimeError(f"HTTP error {resp.status_code}: {body_text}")
        return data

    # urllib fallback
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    import ssl
    context = None
    if insecure:
        context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            resp_data = resp.read()
            try:
                return json.loads(resp_data.decode("utf-8"))
            except Exception:
                raise RuntimeError("Non-JSON response from Xrocket: %s" % resp_data.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP error {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"Request to Xrocket failed: {e}")


def _http_get_sync(url: str, headers: dict, timeout: int = 15) -> dict | None:
    insecure = os.getenv("XROCKET_INSECURE", "false").lower() in ("1", "true", "yes")
    try:
        import requests
    except Exception:
        requests = None

    if requests is not None:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=not insecure)
        if resp.status_code == 404:
            return None
        if not resp.ok:
            raise RuntimeError(f"HTTP error {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except Exception:
            return None

    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    import ssl
    context = None
    if insecure:
        context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            data = resp.read()
            try:
                return json.loads(data.decode("utf-8"))
            except Exception:
                return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"HTTP error {e.code}: {e.read().decode('utf-8', errors='replace')}")
    except Exception as e:
        raise RuntimeError(f"Request to Xrocket failed: {e}")


async def create_invoice(amount: float, currency: str = "USD", description: str | None = None, metadata: dict | None = None, return_url: str | None = None) -> dict:
    url = f"{XROCKET_API_URL.rstrip('/')}/invoices"
    payload = {"amount": amount, "currency": currency}
    if description:
        payload["description"] = description
    if metadata:
        payload["metadata"] = metadata
    if return_url:
        payload["return_url"] = return_url

    headers = _headers()

    def _sync_post():
        logger.debug("Creating invoice (fixed client): %s", payload)
        return _http_post_sync(url, payload, headers, timeout=20)

    return await asyncio.to_thread(_sync_post)


async def get_invoice(invoice_id: str) -> dict | None:
    url = f"{XROCKET_API_URL.rstrip('/')}/invoices/{invoice_id}"
    headers = _headers()
    def _sync_get():
        return _http_get_sync(url, headers, timeout=15)
    return await asyncio.to_thread(_sync_get)


def verify_webhook_signature(body: bytes, signature_header_value: str | None) -> bool:
    if not XROCKET_WEBHOOK_SECRET or not signature_header_value:
        logger.debug("No webhook secret configured; skipping signature verification")
        return True
    try:
        expected = hmac.new(XROCKET_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        provided = signature_header_value.strip()
        valid = hmac.compare_digest(expected, provided)
        if not valid:
            logger.warning("Webhook signature mismatch")
        return valid
    except Exception as e:
        logger.error("Error verifying webhook signature: %s", e)
        return False
