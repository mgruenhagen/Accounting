"""
NetSuite Token-Based Authentication (TBA) — OAuth 1.0a with HMAC-SHA256.

Built from first principles (no requests-oauthlib) because NetSuite's TBA
implementation requires exact RFC 3986 percent-encoding and specific realm
handling that third-party OAuth libraries get wrong.

Key requirements:
- realm in Authorization header = account_id (uppercase, underscores for dashes)
- realm is NOT included in the signature base string
- URL query parameters (limit, offset) ARE included in the signature base string
- Signature method: HMAC-SHA256 (not the OAuth 1.0a default of HMAC-SHA1)
"""

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote


def _pct_encode(value: str) -> str:
    """RFC 3986 percent-encoding — encodes everything except unreserved characters."""
    return quote(str(value), safe="")


class NetSuiteAuth:
    def __init__(
        self,
        account_id: str,
        consumer_key: str,
        consumer_secret: str,
        token_id: str,
        token_secret: str,
    ) -> None:
        # Realm: uppercase with underscores (e.g. "1234567" or "1234567_SB1")
        self.realm = account_id.upper().replace("-", "_")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token_id = token_id
        self.token_secret = token_secret

    def build_auth_header(
        self,
        method: str,
        base_url: str,
        query_params: dict[str, str] | None = None,
    ) -> str:
        """
        Build the OAuth Authorization header for a NetSuite SuiteQL request.

        Args:
            method: HTTP method, e.g. "POST"
            base_url: URL without query string, e.g.
                      "https://1234567.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"
            query_params: URL query parameters that will be appended to the URL
                          (e.g. {"limit": "1000", "offset": "0"}).
                          These participate in the signature.

        Returns:
            The full Authorization header value, e.g. 'OAuth realm="...", ...'
        """
        if query_params is None:
            query_params = {}

        # Step 1: Collect OAuth params (not realm — that goes in header only)
        nonce = secrets.token_hex(16)
        oauth_params: dict[str, str] = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_nonce": nonce,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.token_id,
            "oauth_version": "1.0",
        }

        # Step 2: Combine oauth params + URL query params for signature base string
        all_params = {**oauth_params, **{str(k): str(v) for k, v in query_params.items()}}

        # Step 3: Percent-encode every key and value, sort lexicographically
        encoded_pairs = sorted(
            (_pct_encode(k), _pct_encode(v)) for k, v in all_params.items()
        )
        normalized_params = "&".join(f"{k}={v}" for k, v in encoded_pairs)

        # Step 4: Build signature base string
        # Method (uppercase) & percent_encode(base_url) & percent_encode(normalized_params)
        signature_base_string = "&".join([
            method.upper(),
            _pct_encode(base_url),
            _pct_encode(normalized_params),
        ])

        # Step 5: Build signing key
        signing_key = f"{_pct_encode(self.consumer_secret)}&{_pct_encode(self.token_secret)}"

        # Step 6: Compute HMAC-SHA256 and base64-encode
        raw_signature = hmac.new(
            signing_key.encode("ascii"),
            signature_base_string.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(raw_signature).decode("ascii")

        # Step 7: Add signature to oauth params, build Authorization header
        oauth_params["oauth_signature"] = signature

        # realm comes first; it is NOT percent-encoded and NOT in the signature
        header_parts = [f'realm="{self.realm}"']
        for key in sorted(oauth_params.keys()):
            header_parts.append(f'{key}="{_pct_encode(oauth_params[key])}"')

        return "OAuth " + ", ".join(header_parts)
