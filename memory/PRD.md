# FozPay Clone — PRD

## Original problem statement
Clone & deploy https://github.com/maksxu8iowr/wdffd. The merchant Result URL
(https://www.ewex.io/service/merchant/fozpay/url_status/, BoxExchanger engine) returned
"Не доставлено: HTTP 500" on test webhook. Then: add an API IP-whitelist in the merchant
cabinet (e.g. 72.60.34.27) so nobody else can withdraw funds.

## Architecture
- Backend: FastAPI (`backend/server.py` + core/catalog/admin_router/aml/hd_wallet/recovery/oneinch)
- Frontend: React (CRACO) merchant cabinet
- DB: MongoDB; FozPay-compatible merchant API under `/api/v1` (X-Auth-Token/X-Auth-Sign)
- Integrations: Alchemy, TronGrid, 1inch, Binance prices, HD wallet

## FIXES (verified 9/9 backend tests, iteration 1 report)
### 1. Webhook HTTP 500 "Signature is not valid" (ROOT CAUSE)
The receiver is the BoxExchanger `fozpay` module (confirmed from uploaded OkiPays module).
Its `url_status` handler:
  - reads HTTP headers **`sign`** and **`token`** (lowercase) — NOT `X-Auth-*`
  - verifies `sha256(extractValues(sortObject(body)) + apiSecret)` where JS `join` serializes
    bool→"true"/"false", integral float `3.0`→"3", null→"".
The clone sent `X-Auth-Sign`/`X-Auth-Token` and used bool→"1"/"0", `str(3.0)`→"3.0" → every
signature mismatched → HTTP 500.
Fix:
  - `core.py`: `_js_scalar` + `_concat_values` now match JS exactly.
  - `server.py`: `webhook_headers()` sends lowercase `token`+`sign` (keeps X-Auth-* for compat);
    `send_webhook` maps status to fozpay vocab (Completed→Paid, Cancelled→Canceled,
    In Process→Partially) and sets `total_sum_price`=crypto amount (the field the receiver
    compares against the order amount).
Accepted receiver statuses (lowercased): paid, overpayment, canceled, deleted, error,
expired, partially.

### 2. Merchant API IP whitelist
  - Merchant field `allowed_ips` (cabinet → Settings → Merchant tab, testid merchant-allowed-ips).
  - `auth_merchant()` enforces it via `client_ip_of()` (X-Forwarded-For / X-Real-IP). If list is
    non-empty and the caller IP isn't listed → HTTP 403. Empty list = open.

## Status: deployed, both fixes verified.

## Backlog / Next
- P2: trust only the last proxy hop for X-Forwarded-For (defense-in-depth).
- P2: end-to-end on-chain deposit/withdraw verification (needs funded wallets).
- P2: webhook delivery log in the cabinet.
