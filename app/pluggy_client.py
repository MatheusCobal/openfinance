from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings


class PluggyClient:
    def __init__(self) -> None:
        self.base_url = settings.pluggy_base_url
        self._api_key: Optional[str] = None

    def _authenticate(self) -> None:
        response = httpx.post(
            f"{self.base_url}/auth",
            json={
                "clientId": settings.pluggy_client_id,
                "clientSecret": settings.pluggy_client_secret,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        self._api_key = response.json()["apiKey"]

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._api_key is None:
            self._authenticate()
        headers = {"X-API-KEY": self._api_key, **kwargs.pop("headers", {})}
        response = httpx.request(
            method, f"{self.base_url}{path}", headers=headers, timeout=30.0, **kwargs
        )
        # API key expires after 2h — retry once on 401/403.
        if response.status_code in (401, 403):
            self._authenticate()
            headers["X-API-KEY"] = self._api_key
            response = httpx.request(
                method, f"{self.base_url}{path}", headers=headers, timeout=30.0, **kwargs
            )
        response.raise_for_status()
        return response

    def create_connect_token(
        self,
        client_user_id: Optional[str] = None,
        item_id: Optional[str] = None,
    ) -> str:
        # `clientUserId` ties the item to one of your users (Pluggy uses it for analytics + dedup).
        # `itemId` switches the widget into "update mode" to refresh credentials of an existing item.
        body: Dict[str, Any] = {}
        if client_user_id is not None:
            body["clientUserId"] = client_user_id
        if item_id is not None:
            body["itemId"] = item_id
        # Always send a JSON body (even empty {}) so httpx includes
        # Content-Type: application/json — required by Pluggy's API.
        response = self._request("POST", "/connect_token", json=body)
        return response.json()["accessToken"]

    def list_items(self) -> List[Dict[str, Any]]:
        """All Pluggy Items for the current credentials."""
        MAX_PAGES = 20
        results: List[Dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            response = self._request(
                "GET", "/items", params={"pageSize": 100, "page": page}
            )
            body = response.json()
            page_results = body.get("results", []) or []
            results.extend(page_results)
            total_pages = body.get("totalPages", 1)
            if not page_results or page >= total_pages:
                break
            page += 1
        return results

    def get_item(self, item_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/items/{item_id}").json()

    def list_accounts(self, item_id: str) -> List[Dict[str, Any]]:
        response = self._request("GET", "/accounts", params={"itemId": item_id})
        return response.json()["results"]

    def get_account(self, account_id: str) -> Dict[str, Any]:
        """Single-account fetch — same payload shape as a row of list_accounts."""
        return self._request("GET", f"/accounts/{account_id}").json()

    def get_account_balance(self, account_id: str) -> Dict[str, Any]:
        """Real-time balance snapshot for connectors that support it.

        Returns the raw payload (typically ``{"balance": ..., "updatedAt": ...}``).
        Not all connectors expose this endpoint — sync should call it inside a
        try/except and fall back to the value already inside the account row.
        """
        return self._request("GET", f"/accounts/{account_id}/balance").json()

    def list_bills(self, account_id: str) -> List[Dict[str, Any]]:
        """Credit card bills for the given CREDIT account.

        Pluggy paginates this endpoint the same way as transactions. Caller is
        expected to handle ``HTTPStatusError`` (Pluggy returns 404 for
        connectors that don't expose bills, or for non-CREDIT accounts).
        """
        MAX_PAGES = 24  # 2 years of monthly bills — safety net
        results: List[Dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            response = self._request(
                "GET",
                "/bills",
                params={"accountId": account_id, "pageSize": 100, "page": page},
            )
            body = response.json()
            page_results = body.get("results", []) or []
            results.extend(page_results)
            total_pages = body.get("totalPages", 1)
            if not page_results or page >= total_pages:
                break
            page += 1
        return results

    def list_investments(self, item_id: str) -> List[Dict[str, Any]]:
        """All investment positions for the item across providers."""
        MAX_PAGES = 20
        results: List[Dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            response = self._request(
                "GET",
                "/investments",
                params={"itemId": item_id, "pageSize": 100, "page": page},
            )
            body = response.json()
            page_results = body.get("results", []) or []
            results.extend(page_results)
            total_pages = body.get("totalPages", 1)
            if not page_results or page >= total_pages:
                break
            page += 1
        return results

    def list_investment_transactions(
        self,
        investment_id: str,
        from_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Movements (BUY/SELL/TAX/TRANSFER) for the given investment."""
        MAX_PAGES = 50
        results: List[Dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            params: Dict[str, Any] = {
                "investmentId": investment_id,
                "pageSize": 500,
                "page": page,
            }
            if from_date is not None:
                params["from"] = from_date.isoformat()
            response = self._request("GET", "/investments/transactions", params=params)
            body = response.json()
            page_results = body.get("results", []) or []
            results.extend(page_results)
            total_pages = body.get("totalPages", 1)
            if not page_results or page >= total_pages:
                break
            page += 1
        return results

    def list_transactions(
        self,
        account_id: str,
        from_date: Optional[date] = None,
        bill_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # Pluggy caps pageSize at 500. We paginate until we've fetched
        # everything; MAX_PAGES is a safety net against a runaway loop (25k
        # transactions per account is way past any realistic credit card
        # history).
        MAX_PAGES = 50
        all_results: List[Dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            params: Dict[str, Any] = {
                "accountId": account_id,
                "pageSize": 500,
                "page": page,
            }
            if from_date is not None:
                params["from"] = from_date.isoformat()
            if bill_id is not None:
                params["billId"] = bill_id
            response = self._request("GET", "/transactions", params=params)
            body = response.json()
            results = body.get("results", [])
            all_results.extend(results)
            total_pages = body.get("totalPages", 1)
            if not results or page >= total_pages:
                break
            page += 1
        return all_results


pluggy = PluggyClient()
