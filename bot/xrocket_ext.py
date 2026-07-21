"""Xrocket integration helper (extended).

Provides create_invoice, get_invoice, verify_webhook_signature.
This implementation uses requests and sets Authorization: Bearer <API_KEY>.
"""
from __future__ import annotations

import os
import hmac
import hashlib
import logging
import asyncio

try:
    import requests
except Exception:
    requests = None

logger = logging.getLogger(__name__)

XROCKET_API_URL = os.getenv("XROCKET_API_URL", "https://pay.api.xrocket.exchange/")
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY")
XROCKET_WEBHOOK_SECRET = os.getenv("XROCKET_WEBHOOK_SECRET")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if XROCKET_API_KEY:
        headers["Authorization"] = f"Bearer {XROCKET_API_KEY}"
    return headers


async def create_invoice(amount: float, currency: str = "USD", description: str | None = None, metadata: dict | None = None, return_url: str | None = None) -> dict:
    """Create invoice via Xrocket API. Returns parsed JSON response."""
    if requests is None:
        raise RuntimeError("requests library not available")

    url = f"{XROCKET_API_URL.rstrip('/')}/invoices"
    payload = {"amount": amount, "currency": currency}
    if description:
        payload["description"] = description
    if metadata:
        payload["metadata"] = metadata
    if return_url:
        payload["return_url"] = return_url

    def _sync_post():
        logger.debug("Creating invoice (ext): %s", payload)
        resp = requests.post(url, headers=_headers(), json=payload, timeout=20)
        try:
            data = resp.json()
        except Exception:
            logger.error("Xrocket create_invoice non-json response: %s", resp.text)
            resp.raise_for_status()
        if not resp.ok:
            logger.error("Xrocket create_invoice error: %s", data)
            resp.raise_for_status()
        return data

    return await asyncio.to_thread(_sync_post)


async def get_invoice(invoice_id: str) -> dict | None:
    if requests is None:
        raise RuntimeError("requests library not available")
    url = f"{XROCKET_API_URL.rstrip('/')}/invoices/{invoice_id}"

    def _sync_get():
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return None

    return await asyncio.to_thread(_sync_get)


def verify_webhook_signature(body: bytes, signature_header_value: str | None) -> bool:
    if not XROCKET_WEBHOOK_SECRET or not signature_header_value:
        logger.debug("No webhook secret configured; skipping signature verification (ext)")
        return True
    try:
        expected = hmac.new(XROCKET_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        provided = signature_header_value.strip()
        valid = hmac.compare_digest(expected, provided)
        if not valid:
            logger.warning("Webhook signature mismatch (ext)")
        return valid
    except Exception as e:
        logger.error("Error verifying webhook signature (ext): %s", e)
        return False
