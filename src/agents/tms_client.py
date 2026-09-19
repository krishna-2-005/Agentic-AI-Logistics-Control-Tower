"""One typed client for the mock TMS (execution plan W6).

Week 5's Order Entry Agent posted an order with a hand-built `httpx.post` and learned
the hard way that a payload assembled at the call site can carry a value the contract
has never heard of (P-41). Week 6 has four things talking to the TMS -- the Exception
Agent, the Invoice Auditor, the orchestrator and the MCP tool server -- so the call
site becomes one place, here, the same reasoning D-007 gives for `get_llm()`.

    client = TMSClient()
    shipments = client.list_shipments(limit=200)
    ticket = client.create_exception("SHP-000001", "high", "predicted 3.2x plan")

Every method returns parsed JSON and raises `TMSError` on a non-2xx, with the server's
own `detail` in the message. Nothing here retries: a mock TMS on localhost that fails
is a bug to read, not a blip to paper over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.tms_client")


class TMSError(RuntimeError):
    """A non-2xx from the TMS, carrying the server's own explanation."""

    def __init__(self, status_code: int, detail: str, path: str) -> None:
        super().__init__(f"{path} -> HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass
class TMSClient:
    base_url: str = field(default_factory=lambda: config.TMS_BASE_URL)
    api_key: str = field(default_factory=lambda: config.TMS_API_KEY)
    timeout: float = 15.0

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = httpx.request(method, url, headers=self._headers(), timeout=self.timeout, **kwargs)
        except httpx.HTTPError as exc:
            # A refused or timed-out connection is `httpx.ConnectError`, which is an
            # `httpx.HTTPError` and *not* an `OSError`. Every caller in Week 6 caught
            # `(TMSError, OSError)`, so a TMS that was down crashed them instead of being
            # handled -- including `tms_health`, whose whole job is to report exactly
            # that. Found by driving the MCP server from a real stdio client (P-54).
            # Status 0 means "no HTTP response at all", distinct from any real code.
            raise TMSError(0, f"transport failure: {type(exc).__name__}: {exc}", path) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text[:300])
            except ValueError:
                detail = response.text[:300]
            raise TMSError(response.status_code, str(detail), path)
        return response.json() if response.content else None

    # ── meta ────────────────────────────────────────────────────────────────
    def health(self) -> dict:
        return self._request("GET", "/health")

    def is_up(self) -> bool:
        """True if the TMS answers. Used by callers that must degrade rather than die."""
        try:
            self.health()
        except (httpx.HTTPError, TMSError):
            return False
        return True

    # ── orders ──────────────────────────────────────────────────────────────
    def create_order(self, payload: dict) -> dict:
        return self._request("POST", "/orders", json=payload)

    def list_orders(self, limit: int = 50, **params: Any) -> list[dict]:
        return self._request("GET", "/orders", params={"limit": limit, **params})

    def get_order(self, order_ref: str) -> dict:
        return self._request("GET", f"/orders/{order_ref}")

    # ── shipments ───────────────────────────────────────────────────────────
    def create_shipment(self, order_ref: str, **payload: Any) -> dict:
        return self._request("POST", "/shipments", json={"order_ref": order_ref, **payload})

    def list_shipments(self, limit: int = 50, **params: Any) -> list[dict]:
        return self._request("GET", "/shipments", params={"limit": limit, **params})

    def get_shipment(self, shipment_ref: str) -> dict:
        return self._request("GET", f"/shipments/{shipment_ref}")

    def shipments_on_corridor(self, corridor_id: str, limit: int = 200) -> list[dict]:
        """Every shipment on one corridor, filtered here rather than server-side.

        The TMS's `GET /shipments` takes no corridor filter, and adding one is a change
        to Mounika's module for a caller's convenience. At this scale (tens of
        shipments) a client-side filter costs nothing; if the TMS ever holds enough
        shipments for that to matter, the filter belongs in the API and this method
        becomes a passthrough.
        """
        return [s for s in self.list_shipments(limit=limit) if s.get("corridor_id") == corridor_id]

    # ── exception tickets ───────────────────────────────────────────────────
    def create_exception(self, shipment_ref: str, severity: str, reason: str, notes: str | None = None) -> dict:
        return self._request("POST", "/exceptions", json={
            "shipment_ref": shipment_ref, "severity": severity, "reason": reason, "notes": notes,
        })

    def list_exceptions(self, limit: int = 50, **params: Any) -> list[dict]:
        return self._request("GET", "/exceptions", params={"limit": limit, **params})

    # ── invoices ────────────────────────────────────────────────────────────
    def create_invoice(self, shipment_ref: str, **payload: Any) -> dict:
        return self._request("POST", "/invoices", json={"shipment_ref": shipment_ref, **payload})

    def list_invoices(self, limit: int = 50, **params: Any) -> list[dict]:
        return self._request("GET", "/invoices", params={"limit": limit, **params})

    def set_invoice_status(self, invoice_ref: str, status: str, dispute_reason: str | None = None) -> dict:
        payload: dict[str, Any] = {"status": status}
        if dispute_reason is not None:
            payload["dispute_reason"] = dispute_reason
        return self._request("PATCH", f"/invoices/{invoice_ref}", json=payload)
