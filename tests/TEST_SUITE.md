# PTAB MCP — End-to-End Test Suite

Manual test suite for the FastMCP 3.0 + MCP Apps migration. **18 tests covering all 14 tools**, run against the **live USPTO API** via Claude Desktop (STDIO) — both STDIO and HTTP transport modes should pass.

- Branch: `feature/fastmcp-3.0-migration`
- Reference proceedings: **IPR2024-01353** (105 documents, pagination-validated) and **IPR2023-01035** (Petition doc `170603095`, PyPDF2-extractable, ~98k chars)
- Prereqs: `USPTO_API_KEY` configured (env/.env/DPAPI); `MISTRAL_API_KEY` for T14; `DOCLING_SERVE_URL` for T15
- ⭐ marks tests that emit IDs used by later tests

Run order matters: T6 ⭐ feeds T7–T8; T9 ⭐ feeds T10–T12.

---

## Section 1 — Search (5 tests)

### T1 ⭐ search_trials_minimal — known IPR lookup
```
search_trials_minimal
{"trial_number": "IPR2024-01353"}
```
**Expect:** `count: 1`; result has `trialNumber`, `trialMetaData.trialStatusCategory`, petitioner + patent owner names, `patentOwnerData.patentNumber`. Search-results MCP App renders one card with an IPR type badge.

### T2 search_trials_balanced — party search
```
search_trials_balanced
{"party_name": "Samsung", "limit": 10}
```
**Expect:** ≤10 results with full `trialMetaData.*` fields. MCP App shows filter pills (Type/Status) when values vary; sort bar (Number/Filed) works.

### T3 search_appeals_minimal — examiner/art-unit discovery
```
search_appeals_minimal
{"art_unit": "2128", "limit": 10}
```
**Expect:** Appeals with `appealNumber`, `documentData.decisionOutcome`, `appellantData.groupArtUnitNumber = 2128`. Cards show green **Appeal** badges; Appellant column populated.

### T4 search_interferences_minimal — basic discovery
```
search_interferences_minimal
{"limit": 5}
```
**Expect:** Interferences with `interferenceNumber`, senior/junior party fields. Cards show gray **Interference** badges with Senior/Junior Party labels.

### T5 Search view interactions (uses T1 or T2 results)
Manual, in the rendered iframe:
- **Google Patents →** button appears only on cards with a plain 6-8 digit (or RE) patent number and opens `patents.google.com/patent/US{n}` in the system browser (via `app.openLink`).
- **Patent Center →** opens `patentcenter.uspto.gov/applications/{n}`.
- Filter pill click narrows cards; **× Clear** restores; counter shows "N of M shown".

**Expect:** All buttons open the system browser (no blank iframe navigation); filters/sort behave.

## Section 2 — Documents (3 tests)

### T6 ⭐ ptab_get_documents — full document list (POST search endpoint)
```
ptab_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "limit": 50}
```
**Expect:** `total_documents: 105` (NOT capped at 25 — proves the POST search endpoint), `next_offset` hint present, documents carry `documentIdentifier` values for T9.

### T7 ptab_get_documents — title filter
```
ptab_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "document_title": "decision"}
```
**Expect:** Only documents whose type/title text contains "decision" (case-insensitive, client-side filter).

### T8 ptab_get_documents — pagination
```
ptab_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "limit": 20, "offset": 100}
```
**Expect:** 5 documents (105 total, offset 100), no `next_offset`.

## Section 3 — Downloads & Elicitation (4 tests)

### T9 ⭐ ptab_get_document_download — persistent link (Lesson 43)
```
ptab_get_document_download
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial"}
```
**Expect:** `download_url` matches `http://localhost:8083/download/persistent/{24-hex}` in local mode (or a PFW URL in centralized mode); `download_id` present; `enhanced_filename` ends `.pdf`. This document is NOT in the search index — the fileDownloadURI pattern fallback must kick in.

### T10 Browser download — token-in-path auth
Manual: paste the T9 `download_url` into a browser tab (or click the markdown link).
**Expect:** Chrome shows ERR_ABORTED / the tab closes and the **PDF lands in Downloads** (~1.2 MB). No 401, no headers needed — the hash is the credential.

### T11 URL-mode elicitation + /downloads page
Run T9 in Claude Desktop and watch for the elicitation prompt ("Open the PTAB downloads page…").
- **Accept:** browser opens `http://localhost:8083/downloads?highlight={download_id}`; the matching row is highlighted and scrolled into view; its **Download PDF** button works; page auto-refreshes (5s).
- **Decline/no support:** the normal JSON response still returns (`downloads_page_opened: false`).

**Expect:** Both paths leave the tool response intact — elicitation is best-effort.

### T12 Recent Downloads MCP App panel
After T9, the downloads panel iframe renders from the tool result.
**Expect:** Card with enhanced filename, `trial` badge, IPR2023-01035, working **Download PDF** button (opens via `app.openLink`); **↻ Refresh** merges `/api/recent-downloads` entries when reachable.

## Section 4 — Content Extraction (3 tests)

### T13 ptab_get_document_content — free PyPDF2 tier
```
ptab_get_document_content
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial"}
```
**Expect:** `extraction_method: "pypdf2"`, `character_count: ~98,382`, `ocr_cost_usd: 0.0`. Progress notifications appear during download/extraction (Claude Desktop shows the messages).

### T14 ptab_get_document_content — forced Mistral OCR
```
ptab_get_document_content
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial", "use_ocr": true}
```
**Expect:** `extraction_method: "mistral_ocr"`, nonzero `ocr_cost_usd` (~$0.001/page, ≤50 pages), progress messages "Uploading … to Mistral OCR" and "Running Mistral OCR…".

### T15 Docling tier — page gate
With `MISTRAL_API_KEY` unset (or invalid) and `DOCLING_SERVE_URL=https://docling.example.com`:
- Run T13's call on a **≤20-page** scanned document → **Expect:** `extraction_method: "docling"`, `ocr_cost_usd: 0.0`.
- Run on a >20-page document → **Expect:** Docling skipped (log: "exceeds DOCLING_MAX_PAGES"), error JSON with `docling_configured: true` guidance.

## Section 5 — Guidance, Config, Prompts, HTTP (3 tests)

### T16 Utility tools
```
ptab_get_guidance
{"section": "tools"}
```
```
ptab_get_field_configs
{}
```
**Expect:** Guidance returns the tools section markdown; field configs show trials/appeals/interferences minimal/balanced/complete sets. Guidance must reference 14 tools (no `validate_identifiers`).

### T17 Prompt template
Invoke the `trial_precedent_research` prompt from Claude Desktop's prompt picker.
**Expect:** Prompt renders with its argument slots; 11 prompts listed in total.

### T18 HTTP transport mode
```powershell
$env:FASTMCP_TRANSPORT = "http"; $env:FASTMCP_PORT = "8765"; uv run ptab-mcp
```
**Expect:**
- `GET /health` → `200 OK` (no auth)
- `GET|POST /mcp` without `text/event-stream` in Accept → `401` (probe middleware)
- `POST /mcp` with `X-API-KEY: {INTERNAL_AUTH_SECRET}` + proper Accept → reaches MCP handler (not 401)
- Download proxy answers on `http://localhost:8083/` (daemon thread)
- Without `INTERNAL_AUTH_SECRET` anywhere → server refuses to start (SystemExit)

---

## Reference Data

### Anchor proceedings
| Proceeding | Why | Verified facts |
|---|---|---|
| IPR2024-01353 | Pagination + document listing | 105 documents via POST search endpoint |
| IPR2023-01035 | Download + extraction | Petition doc `170603095`, ~98,382 chars via PyPDF2, ~1.19 MB PDF; NOT in search index (URI-pattern fallback) |

### Tool coverage matrix
| Tool | Tests |
|---|---|
| search_trials_minimal / balanced / complete | T1, T2 (complete: run T1 args with complete tier as a spot check) |
| search_appeals_minimal / balanced / complete | T3 (balanced/complete: same args, higher tier) |
| search_interferences_minimal / balanced / complete | T4 (higher tiers: same args) |
| ptab_get_documents | T6, T7, T8 |
| ptab_get_document_download | T9–T12 |
| ptab_get_document_content | T13–T15 |
| ptab_get_guidance / ptab_get_field_configs | T16 |

### Environment variables exercised
`USPTO_API_KEY`, `MISTRAL_API_KEY`, `MISTRAL_OCR_MODEL`, `DOCLING_SERVE_URL`, `DOCLING_TIMEOUT`, `DOCLING_MAX_PAGES`, `PTAB_PROXY_PORT`, `PTAB_PROXY_BASE_URL`, `CENTRALIZED_PROXY_URL`, `CENTRALIZED_PROXY_PORT`, `INTERNAL_AUTH_SECRET`, `FASTMCP_TRANSPORT`, `FASTMCP_HOST`, `FASTMCP_PORT`, `CORS_EXTRA_ORIGIN`, `PROXY_ALLOWED_IPS`, `MCP_APP_EXTRA_DOMAINS`

**Last validated:** 2026-07-02 (T1, T6, T9, T10-equivalent, T13, T18 verified programmatically during migration; iframe/elicitation tests require Claude Desktop)
