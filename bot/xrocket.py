"""Xrocket integration helper.

This module provides async helpers to create invoices and query their status.
It uses environment variables for configuration:
- XROCKET_API_URL (base API URL)
- XROCKET_API_KEY (secret key for API requests)
- XROCKET_WEBHOOK_SECRET (optional: secret used to verify webhook HMAC)

Note: concrete fields returned by Xrocket API may differ; this implementation is written to be generic and tolerant.
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
    """Create invoice via Xrocket API.

    Returns the parsed JSON response or raises an exception on non-2xx.
    Behavior is generic: expects API to accept POST /invoices and return JSON with invoice id and payment URL.
    """
    if requests is None:
        raise RuntimeError("requests library not available")

    url = f"{XROCKET_API_URL.rstrip('/')}/invoices"
    payload = {
        "amount": amount,
        "currency": currency,
    }
    if description:
        payload["description"] = description
    if metadata:
        payload["metadata"] = metadata
    if return_url:
        payload["return_url"] = return_url

    def _sync_post():
        logger.debug("Creating invoice: %s", payload)
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
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
        resp = requests.get(url, headers=_headers(), timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return None

    return await asyncio.to_thread(_sync_get)


def verify_webhook_signature(body: bytes, signature_header_value: str | None) -> bool:
    """Verify webhook signature if secret present.

    Many providers sign webhook payloads with HMAC-SHA256. We support verification when
    XROCKET_WEBHOOK_SECRET is set. Accepts header values like raw hex HMAC.
    """
    if not XROCKET_WEBHOOK_SECRET or not signature_header_value:
        # If no secret configured, fall back to permissive mode (caller may still apply other checks)
        logger.debug("No webhook secret configured; skipping signature verification")
        return True
    try:
        expected = hmac.new(XROCKET_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        provided = signature_header_value.strip()
        valid = hmac.compare_digest(expected, provided)
        if not valid:
            logger.warning("Webhook signature mismatch: expected %s got %s", expected, provided)
        return valid
    except Exception as e:
        logger.error("Error verifying webhook signature: %s", e)
        return False
