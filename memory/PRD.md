# FozPay Clone — PRD

## Original problem statement
Clone & deploy https://github.com/maksxu8iowr/wdffd. The merchant Result URL
(https://www.ewex.io/service/merchant/fozpay/url_status/) returned "Не доставлено: HTTP 500"
when sending a test webhook. Find and fix the 500 in the webhook handler.

## Architecture
- Backend: FastAPI (`/app/backend/server.py` + core/catalog/admin_router/aml/hd_wallet/recovery/oneinch)
- Frontend: React (CRACO) cabinet — Dashboard, Wallet, Requests, Checkout, Settings, ApiDocs, Recovery
- DB: MongoDB
- FozPay-compatible merchant API under `/api/v1` (X-Auth-Token / X-Auth-Sign)
- Integrations: Alchemy, TronGrid, 1inch, Binance prices (HD wallet crypto processing)

## Root cause of the webhook HTTP 500 (FIXED — 2026-06)
The receiver (ewex.io) runs the **BoxExchanger** engine. Its FozPay module verifies
`X-Auth-Sign` = `sha256(extractValues(sortObject(body)) + secret)` where JS serializes
values via `Array.join`: bool→"true"/"false", integral number `3.0`→"3", null→"".
The clone's `_concat_values` used bool→"1"/"0" and Python `str(3.0)`→"3.0", so every
signature mismatched → ewex replied `HTTP 500 "Error:Signature is not valid"`.

Fix: `backend/core.py` `_concat_values` now formats scalars exactly like the JS engine
(added `_js_scalar`). Verified byte-for-byte against BoxExchanger's actual JS
(`extractValues`/`sortObject`) via a parity harness and a local mock receiver → 200 OK,
`delivered: true`. Inbound pay-in signature verification also confirmed (200).

Also updated: `backend/tests/test_webhook_delivery.py` helper and `frontend/src/pages/ApiDocs.js`
docs to reflect the corrected signing rules.

## Status
- App cloned & deployed; login page + admin login working.
- Webhook signature bug fixed and verified.

## Backlog / Next
- P1: Obtain the real FozPay merchant `url_status` module to confirm exact field mapping
  after signature passes (status values, amount fields) for full order-completion flow.
- P2: End-to-end on-chain deposit/withdraw verification (needs funded wallets).
