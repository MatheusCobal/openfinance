from datetime import date
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import MissingPluggyCredentialsError, get_pluggy_settings


PluggyCredentialError = MissingPluggyCredentialsError


class PluggyClient:
    def __init__(self, http_client: Optional[httpx.Client] = None) -> None:
        self.base_url = get_pluggy_settings().pluggy_base_url
        self._api_key: Optional[str] = None
        self._api_key_lock = Lock()
        self._http_client = http_client or httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            transport=httpx.HTTPTransport(retries=2),
        )
        self._owns_http_client = http_client is None

    def _credentials(self) -> Tuple[str, str]:
        pluggy_settings = get_pluggy_settings().require_credentials()
        return pluggy_settings.pluggy_client_id, pluggy_settings.pluggy_client_secret

    def _authenticate_locked(self) -> None:
        client_id, client_secret = self._credentials()
        response = self._http_client.post(
            "/auth",
            json={
                "clientId": client_id,
                "clientSecret": client_secret,
            },
        )
        response.raise_for_status()
        self._api_key = response.json()["apiKey"]

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._api_key is None:
            with self._api_key_lock:
                if self._api_key is None:
                    self._authenticate_locked()
        api_key = self._api_key
        headers = {**kwargs.pop("headers", {}), "X-API-KEY": api_key}
        response = self._http_client.request(method, path, headers=headers, **kwargs)
        # API key expires after 2h — retry once on 401/403.
        if response.status_code in (401, 403):
            with self._api_key_lock:
                if self._api_key == api_key:
                    self._authenticate_locked()
                headers["X-API-KEY"] = self._api_key
            response = self._http_client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _list_paginated(
        self,
        path: str,
        params: Dict[str, Any],
        *,
        page_size: int,
        max_pages: int,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            response = self._request(
                "GET",
                path,
                params={**params, "pageSize": page_size, "page": page},
            )
            body = response.json()
            page_results = body.get("results", []) or []
            results.extend(page_results)
            if not page_results or page >= body.get("totalPages", 1):
                break
        return results

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
        return self._list_paginated("/items", {}, page_size=100, max_pages=20)

    def get_item(self, item_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/items/{item_id}").json()

    def list_accounts(self, item_id: str) -> List[Dict[str, Any]]:
        response = self._request("GET", "/accounts", params={"itemId": item_id})
        return response.json()["results"]

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
        return self._list_paginated(
            "/bills",
            {"accountId": account_id},
            page_size=100,
            max_pages=24,
        )

    def list_investments(self, item_id: str) -> List[Dict[str, Any]]:
        """All investment positions for the item across providers."""
        return self._list_paginated(
            "/investments",
            {"itemId": item_id},
            page_size=100,
            max_pages=20,
        )

    def list_investment_transactions(
        self,
        investment_id: str,
        from_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Movements (BUY/SELL/TAX/TRANSFER) for the given investment."""
        params: Dict[str, Any] = {"investmentId": investment_id}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        return self._list_paginated(
            "/investments/transactions",
            params,
            page_size=500,
            max_pages=50,
        )

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
        params: Dict[str, Any] = {"accountId": account_id}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if bill_id is not None:
            params["billId"] = bill_id
        return self._list_paginated(
            "/transactions",
            params,
            page_size=500,
            max_pages=50,
        )


pluggy = PluggyClient()
