"""
NetSuite SuiteQL HTTP client with auto-pagination and retry logic.

The SuiteQL endpoint accepts POST requests with a JSON body {"q": "<sql>"}
and pagination via limit/offset URL query parameters.

Important: limit and offset are included in the OAuth signature (they are
URL query parameters, not body parameters).
"""

import time
import requests

from netsuite.auth import NetSuiteAuth


class SuiteQLError(Exception):
    """Raised when a SuiteQL request fails."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"SuiteQL HTTP {status_code}: {message}")


class NetSuiteClient:
    PAGE_SIZE = 1000
    MAX_RETRIES = 3
    RETRY_BACKOFF = [2, 4, 8]  # seconds between retries

    def __init__(self, auth: NetSuiteAuth, account_id: str) -> None:
        self.auth = auth
        # API URL: account_id lowercased, underscores → hyphens
        url_account = account_id.lower().replace("_", "-")
        self.suiteql_url = (
            f"https://{url_account}.suitetalk.api.netsuite.com"
            f"/services/rest/query/v1/suiteql"
        )
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Prefer": "transient",
        })

    def query_all(self, sql: str) -> list[dict]:
        """
        Execute a SuiteQL query and return all results, handling pagination
        transparently.

        Args:
            sql: The SuiteQL query string.

        Returns:
            A list of row dicts, one per result row.

        Raises:
            SuiteQLError: On authentication failure or persistent server error.
        """
        results: list[dict] = []
        offset = 0

        while True:
            page = self._fetch_page(sql, limit=self.PAGE_SIZE, offset=offset)
            results.extend(page.get("items", []))

            if not page.get("hasMore", False):
                break

            offset += self.PAGE_SIZE

        return results

    def _fetch_page(self, sql: str, limit: int, offset: int) -> dict:
        query_params = {"limit": str(limit), "offset": str(offset)}
        url_with_qs = f"{self.suiteql_url}?limit={limit}&offset={offset}"

        for attempt in range(self.MAX_RETRIES + 1):
            auth_header = self.auth.build_auth_header(
                method="POST",
                base_url=self.suiteql_url,
                query_params=query_params,
            )

            try:
                resp = self._session.post(
                    url_with_qs,
                    headers={"Authorization": auth_header},
                    json={"q": sql},
                    timeout=120,
                )
            except requests.exceptions.ConnectionError as exc:
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_BACKOFF[attempt])
                    continue
                raise SuiteQLError(0, f"Connection failed: {exc}") from exc

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 401:
                raise SuiteQLError(
                    401,
                    "Authentication failed — check consumer_key, token_id, and "
                    "account_id in config/settings.yaml. "
                    f"Response: {resp.text[:500]}",
                )

            if resp.status_code == 403:
                raise SuiteQLError(
                    403,
                    "Access denied — the integration token may lack SuiteQL permission. "
                    f"Response: {resp.text[:500]}",
                )

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF[attempt]
                    print(
                        f"  [retry {attempt + 1}/{self.MAX_RETRIES}] "
                        f"HTTP {resp.status_code}, waiting {wait}s..."
                    )
                    time.sleep(wait)
                    continue

            raise SuiteQLError(resp.status_code, resp.text[:500])

        raise SuiteQLError(0, "Max retries exceeded")
