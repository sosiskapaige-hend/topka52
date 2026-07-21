"""Xrocket Pay API client (production).

Docs: POST /tg-invoices, GET /tg-invoices/{id}
Auth: Rocket-Pay-Key header.
Webhooks: Rocket-Pay-Signature = HMAC-SHA256(body, SHA256(api_token)).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

XROCKET_API_URL = os.getenv("XROCKET_API_URL", "https://pay.xrocket.tg/")
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY")
XROCKET_WEBHOOK_SECRET = os.getenv("XROCKET_WEBHOOK_SECRET")
XROCKET_CURRENCY = os.getenv("XROCKET_CURRENCY", "USDT")


def _headers() -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "quantum-bot/1.0",
    }
    if XROCKET_API_KEY:
        headers["Rocket-Pay-Key"] = XROCKET_API_KEY
    return headers


def _webhook_signing_key() -> bytes | None:
    """Xrocket webhook signing key = SHA256(api_token) per their docs."""
    secret = (XROCKET_WEBHOOK_SECRET or "").strip()
    # Ignore if it looks like a URL (misconfiguration)
    if secret and not secret.startswith(("http://", "https://")):
        return secret.encode("utf-8")
    if not XROCKET_API_KEY:
        return None
    # Per xRocket docs: signing key = SHA256(api_token) as raw bytes
    return hashlib.sha256(XROCKET_API_KEY.encode("utf-8")).digest()


def _http_post_sync(url: str, payload: dict, headers: dict, timeout: int = 20) -> dict:
    insecure = os.getenv("XROCKET_INSECURE", "false").lower() in ("1", "true", "yes")
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
            body_text = resp.text if hasattr(resp, "text") else str(resp)
            logger.error("Xrocket HTTP error %s: %s", resp.status_code, body_text)
            raise RuntimeError(f"HTTP error {resp.status_code}: {body_text}")
        return data if isinstance(data, dict) else {"data": data}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    import ssl

    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            resp_data = resp.read()
            try:
                return json.loads(resp_data.decode("utf-8"))
            except Exception:
                text = resp_data.decode("utf-8", errors="replace")
                logger.error("Non-JSON response from Xrocket: %s", text)
                raise RuntimeError("Non-JSON response from Xrocket: %s" % text)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("Xrocket HTTPError %s: %s", e.code, body)
        raise RuntimeError(f"HTTP error {e.code}: {body}")
    except Exception as e:
        logger.error("Xrocket request failed: %s", e)
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
            logger.error("Xrocket GET error %s: %s", resp.status_code, resp.text)
            raise RuntimeError(f"HTTP error {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except Exception:
            return None

    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    import ssl

    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body = e.read().decode("utf-8", errors="replace")
        logger.error("Xrocket GET HTTPError %s: %s", e.code, body)
        raise RuntimeError(f"HTTP error {e.code}: {body}")
    except Exception as e:
        logger.error("Xrocket GET request failed: %s", e)
        raise RuntimeError(f"Request to Xrocket failed: {e}")


async def create_invoice(
    amount: float,
    currency: str | None = None,
    description: str | None = None,
    payload: str | None = None,
    callback_url: str | None = None,
    num_payments: int = 1,
    expired_in: int = 0,
) -> dict:
    # xRocket Pay API: POST /tg-invoices  (domain: pay.xrocket.tg)
    url = f"{XROCKET_API_URL.rstrip('/')}/tg-invoices"
    body: dict = {
        "minPayment": amount,
        "currency": currency or XROCKET_CURRENCY,
        "numPayments": num_payments,
    }
    if description:
        body["description"] = description[:1000]
    if payload:
        body["payload"] = payload[:4000]
    if expired_in:
        body["expiredIn"] = expired_in

    headers = _headers()

    def _sync_post():
        logger.info("Creating xRocket invoice: url=%s amount=%s currency=%s", url, amount, body["currency"])
        return _http_post_sync(url, body, headers, timeout=20)

    return await asyncio.to_thread(_sync_post)


async def get_invoice(invoice_id: str) -> dict | None:
    url = f"{XROCKET_API_URL.rstrip('/')}/tg-invoices/{invoice_id}"
    headers = _headers()

    def _sync_get():
        return _http_get_sync(url, headers, timeout=15)

    return await asyncio.to_thread(_sync_get)


def verify_webhook_signature(body: bytes, signature_header_value: str | None) -> bool:
    key = _webhook_signing_key()
    if not key:
        logger.warning("Webhook signature verification skipped: no API key configured")
        return True
    if not signature_header_value:
        logger.warning("Webhook missing Rocket-Pay-Signature header — rejecting")
        return False
    try:
        expected = hmac.new(key, body, hashlib.sha256).hexdigest()
        provided = signature_header_value.strip()
        if provided.lower().startswith("sha256="):
            provided = provided.split("=", 1)[1].strip()
        valid = hmac.compare_digest(expected.lower(), provided.lower())
        if not valid:
            logger.warning("Webhook signature mismatch: expected=%s provided=%s", expected[:8], provided[:8])
        return valid
    except Exception as e:
        logger.error("Error verifying webhook signature: %s", e)
        return False
