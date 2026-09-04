# PTAB MCP — End-to-End Test Suite

Manual test suite for the FastMCP 4.0 + MCP Apps stack (FastMCP 4.0.1 on MCP Python SDK 2.x, protocol revision 2026-07-28). **19 tests covering the 14 tools registered by default**, run against the **live USPTO API** via Claude Desktop (STDIO) — both STDIO and HTTP transport modes should pass. The 15th tool, `ptab_manage_users`, is registration-gated by `PTAB_ENABLE_USER_MANAGEMENT` (default off) and is not exercised here.

- Branch: `master`
- Reference proceedings: **IPR2024-01353** (108 documents as of 2026-09-03, pagination-validated; a live docket, so see the drift note in T6) and **IPR2023-01035** (Petition doc `170603095`, 75 pages, pypdf-extractable, ~100k chars)
- Prereqs: `USPTO_API_KEY` configured (env/.env/DPAPI); `MISTRAL_API_KEY` for T14; `DOCLING_SERVE_URL` for T15
- ⭐ marks tests that emit IDs used by later tests

Run order matters: T6 ⭐ feeds T7–T8; T9 ⭐ feeds T10–T12.

> **⚠ Identifier formats (suite audited 2026-09-02):** `patent_number` means the
> GRANTED PATENT and `application_number` (appeals) means the APPLICATION serial.
> They are separate namespaces, and since patent numbers passed 10,000,000 in
> mid-2018 an 8-digit value is valid in both. **This server does not lane-resolve
> between them:** the wrong kind of number returns a clean empty result that reads
> as "no proceedings exist", not an error. The PFW MCP is the crosswalk
> (`PFW_search_applications_minimal` with `query='patentNumber:<n>'` or
> `query='applicationNumberText:<n>'`). Appeal numbers are 10 digits and validated,
> so an 8-digit value there fails loudly instead of returning nothing. **No fixture
> in this suite depends on an 8-digit interpretation:** the tests key on trial
> numbers, art units, party names and the 9-digit document id `170603095`. If you
> add a patent-number test, use a 7-digit number such as `7883848` (the patent at
> issue in IPR2024-01353) or state which namespace you mean.

---

## Section 1 — Search (6 tests)

### T1 ⭐ PTAB_search_trials_minimal — known IPR lookup
```
PTAB_search_trials_minimal
{"trial_number": "IPR2024-01353"}
```
**Expect:** `count: 1`; result has `trialNumber`, `trialMetaData.trialStatusCategory`, petitioner + patent owner names, `patentOwnerData.patentNumber`. Search-results MCP App renders one card with an IPR type badge.

### T2 PTAB_search_trials_balanced — party search
```
PTAB_search_trials_balanced
{"petitioner_name": "Samsung", "limit": 10}
```
**Expect:** ≤10 results with full `trialMetaData.*` fields, every one of them with Samsung as the PETITIONER. MCP App shows filter pills (Type/Status) when values vary; sort bar (Number/Filed) works.

> **Fixture corrected 2026-09-02.** This test used to pass `party_name`, which
> is not a parameter of any trial search tool and never has been; the call
> fails schema validation before it reaches the server. The two party
> parameters are `petitioner_name` and `patent_owner_name`, and they are
> role-scoped (2026-08-30): `petitioner_name` returns proceedings where the
> named party petitioned, not proceedings that merely mention it. Run the
> `patent_owner_name` side too if you want both.

### T2b Trial date filters and the tier contract (added 2026-09-03)
```
PTAB_search_trials_minimal
{"tech_center": "2400", "institution_date_from": "2025-01-01", "institution_date_to": "2025-12-31", "limit": 5}
```
**Expect:** a normal result envelope. Before 2026-09-03 this call was rejected at the schema with a raw pydantic "Unexpected keyword argument" because the minimal tier did not declare the parameter, even though `trialMetaData.institutionDecisionDate` is in the minimal FIELD SET and comes back in every row. `query_info.range_filters` names `trialMetaData.institutionDecisionDate`.

```
PTAB_search_trials_minimal
{"trial_number": "IPR2024-00990", "final_decision_date_from": "2026-01-01"}
```
**Expect:** `query_info.deprecated_alias_used: ["final_decision_date_from"]`, `query_info.deprecated_alias_ranged_on: "trialMetaData.latestDecisionDate"`, and a `deprecated_alias_note` naming IPR2024-00990 (where that field reads 2026-07-21, the date a Federal Circuit dismissal was docketed, while the Board's final written decision issued 2025-12-09). The same three keys appear on `PTAB_search_trials_balanced`. Passing `latest_decision_date_from` instead must carry NONE of them.

```
PTAB_search_trials_balanced
{"trial_number": ["IPR2024-01353", "IPR2024-00864"]}
```
**Expect:** a `VALIDATION_ERROR` envelope whose message names `PTAB_search_trials_minimal` as the tier that takes a list. It used to be the bare internal message "'list' object has no attribute 'strip'". The same list on `PTAB_search_trials_minimal` succeeds with `query_info.bulk_lookup: true` and `input_count: 2`.

### T3 PTAB_search_appeals_minimal — art-unit discovery
```
PTAB_search_appeals_minimal
{"art_unit": "2128", "limit": 10}
```
**Expect:** 9 fields per appeal: `appealNumber`, `appellantData.applicationNumberText`, `appellantData.realPartyInInterestName`, `appellantData.technologyCenterNumber`, `appellantData.groupArtUnitNumber = 2128`, `documentData.documentFilingDate`, `decisionData.decisionIssueDate`, `decisionData.decisionTypeCategory`, `decisionData.appealOutcomeCategory` (Affirmed / Reversed / Affirmed-in-Part). Cards show green **Appeal** badges with the Appellant column, an outcome status badge and a Decided date, all populated.

> **Expectation corrected 2026-09-02.** This test previously expected
> `documentData.decisionOutcome`, which the appeals payload has never carried:
> `appeals_minimal` named 9 fields and a live response returned 4 of them
> because the config's dotted paths did not match the API's nesting. The
> outcome lives at `decisionData.appealOutcomeCategory`, the decision date at
> `decisionData.decisionIssueDate`, the appellant at
> `appellantData.realPartyInInterestName`, and the application number at
> `appellantData.applicationNumberText` (there is no root-level
> `applicationNumber`). **The EXAMINER is not served by this tool at any
> tier**: the appeals payload has no `examinerData` bag at all, which is why
> this test is no longer titled "examiner/art-unit discovery". To get the
> examiner, carry `appellantData.applicationNumberText` across to
> `PFW_search_applications_minimal`.

### T4 PTAB_search_interferences_minimal — basic discovery
```
PTAB_search_interferences_minimal
{"limit": 5}
```
**Expect:** 8 fields per interference: `interferenceNumber`, `interferenceMetaData.interferenceStyleName` (the "SENIOR v. JUNIOR" caption), `seniorPartyData.realPartyInInterestName`, `juniorPartyData.realPartyInInterestName`, `documentData.documentFilingDate`, `documentData.decisionIssueDate`, `documentData.decisionTypeCategory`, `documentData.interferenceOutcomeCategory`. Cards show gray **Interference** badges with both Senior and Junior Party labels filled in.

> **Expectation corrected 2026-09-02.** Four of the six configured fields
> named a `partyData` bag and a `documentData.decisionDate` / `decisionType`
> pair that do not exist, so a live response carried `interferenceNumber` and
> `documentFilingDate` and nothing else. The parties are two sibling bags,
> `seniorPartyData` and `juniorPartyData`, carrying the same field names; the
> decision fields sit INSIDE `documentData`; there is no `decisionData` bag.
> `decisionTypeCategory` mostly reads "Decision" (a "Motion Decision" also
> appears; observed in the 2026-09-03 re-run), so
> `interferenceOutcomeCategory` ("Judgment", etc.) is the informative one.
> **Two sparse-data notes, both expected, neither a failure:** the party bags
> are missing on a minority of records (48/50 and 44/50 in the 2026-09-02
> probe), which is why the always-present style-name caption is in the set;
> and when a configured field is missing from every record in a result, the
> response now says so in a `fields_absent` block instead of letting it
> vanish.

### T5 Search view interactions (uses T1 or T2 results)
Manual, in the rendered iframe:
- **Google Patents →** button appears only on cards with a plain 6-8 digit (or RE) patent number and opens `patents.google.com/patent/US{n}` in the system browser (via `app.openLink`).
- **Patent Center →** opens `patentcenter.uspto.gov/applications/{n}`.
- Filter pill click narrows cards; **× Clear** restores; counter shows "N of M shown".

**Expect:** All buttons open the system browser (no blank iframe navigation); filters/sort behave.

## Section 2 — Documents (3 tests)

### T6 ⭐ PTAB_get_documents — full document list (POST search endpoint)
```
PTAB_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "limit": 50}
```
**Expect:** `total_documents: 108` (NOT capped at 25 — proves the POST search endpoint), 50 documents returned, `paging.has_more: true` with `next_offset: 50`, documents carry `documentIdentifier` values for T9.

> **⚠ Live docket, re-anchored 2026-09-02: 108 documents (was 105).** An FWD,
> a Notice of Appeal and updated notices were filed between 2026-03 and
> 2026-05. **A count that no longer matches is docket movement, not a
> failure.** IPR2024-01353 is a real proceeding and papers keep landing in it.
> What this test actually proves is that the total is well above the 25-record
> cap of the GET endpoint and that `paging.total` agrees with
> `total_documents`; treat the exact number as a snapshot. If it has moved
> again, re-anchor this line and T8's arithmetic rather than filing a bug, and
> only investigate if the total DROPS or the cap reappears at 25.

### T7 PTAB_get_documents — title filter
```
PTAB_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "document_title": "decision"}
```
**Expect:** Only documents whose `documentTitleText` matches the phrase "decision" (case-insensitive, whole words in order). The filter runs SERVER-side across the whole docket, so `matched_total` and `total_documents` are docket-wide counts and `filter_semantics_note` says "ran SERVER-side" and names the phrase match.

> **Semantics corrected 2026-09-03.** This test used to expect a client-side
> substring over type/title text, which is what the parameter's own Args
> description claimed. The live behaviour is the server-side phrase match on
> `documentTitleText` alone; a partial word ('Instit') matches nothing here.
> Re-run with `"page_all": true` for the substring mode over
> `documentTitleText` AND `documentTypeDescriptionText`, and expect
> `filter_semantics_note` to say "ran client-side" and to name the SUBSTRING
> match. Which of the two ran is the thing under test, and the note is where
> the answer is.

### T8 PTAB_get_documents — pagination
```
PTAB_get_documents
{"identifier": "IPR2024-01353", "identifier_type": "trial", "limit": 20, "offset": 100}
```
**Expect:** 8 documents, `paging.total: 108`, `paging.has_more: false`, `next_offset: null`.

> **Arithmetic, re-anchored 2026-09-02:** the expected row count is
> `total - offset` whenever `total - offset` is less than `limit`, so 108 - 100
> = 8 (it was 5 when the docket held 105). The invariant under test is the tail
> behaviour, not the number: a short final page with `has_more: false` and no
> next cursor. Recompute from T6's live `total_documents` before calling this
> a failure, and keep the offset at 100 so the page stays a partial one.

## Section 3 — Downloads (4 tests)

### T9 ⭐ PTAB_get_document_download — persistent link (Lesson 43)
```
PTAB_get_document_download
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial"}
```
**Expect:** `download_url` matches `http://localhost:8083/download/persistent/{24-hex}` in local mode (or a PFW URL in centralized mode); `download_id` present; `enhanced_filename` is `PTAB-2023-06-15_IPR2023-01035_PAT-10995048_IPR2023-01035_-_PETITION.pdf` — the paper's OWN filing date and title, taken from the document index.

> **Re-anchored 2026-09-03.** This test used to read "This document is NOT in
> the search index — the fileDownloadURI pattern fallback must kick in", and
> that is no longer true: `documentData.documentIdentifier` 170603095 returns
> count 1 from trials/documents/search (the Petition, filed 2023-06-15), so the
> tool now names the file from real metadata. The lookup order is targeted
> documentIdentifier query -> full docket walk -> URI pattern, and **a generic
> `_DOCUMENT.pdf` name with the PROCEEDING's filing date is now a FAILURE
> signal, not the expected result** (that was the prod defect fixed on
> 2026-09-03: IPR2024-01353's Final Written Decision came back as
> `PTAB-2024-08-23_IPR2024-01353_PAT-7883848_DOCUMENT.pdf`). To exercise the
> fallback itself, call the tool with an id the docket does not carry — e.g.
> `{"document_id": "171303339", "identifier": "IPR2024-01353"}` — and expect a
> working persistent link with `document_description: "Document"`,
> `page_count: "Unknown"` and the trial's own 2024-08-23 date. The hermetic
> version of both halves is `tests/test_document_lookup_order.py`.

### T10 Browser download — token-in-path auth
Manual: paste the T9 `download_url` into a browser tab (or click the markdown link).
**Expect:** Chrome shows ERR_ABORTED / the tab closes and the **PDF lands in Downloads** (~1.2 MB). No 401, no headers needed — the hash is the credential.

### T11 /downloads page
After T9, open `http://localhost:8083/downloads?highlight={download_id}` in a browser.
**Expect:** the matching row is highlighted and scrolled into view; its **Download PDF** button works; page auto-refreshes (5s).

### T12 Recent Downloads MCP App panel
After T9, the downloads panel iframe renders from the tool result.
**Expect:** Card with enhanced filename, `trial` badge, IPR2023-01035, working **Download PDF** button (opens via `app.openLink`); **↻ Refresh** merges `/api/recent-downloads` entries when reachable.

## Section 4 — Content Extraction (3 tests)

### T13 PTAB_get_document_content — pypdf tier
```
PTAB_get_document_content
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial", "max_chars": 200000}
```
**Expect:** `extraction_method: "pypdf2"`, `page_count: 75`, `character_count` of at least 95,000 (99,647 on staging 2026-09-02; 99,649 on prod 2026-09-03 under pypdf 6.16.2), and no `_window` key. The payload carries extraction metadata only. Progress notifications appear during download/extraction (Claude Desktop shows the messages).

> **`max_chars` added to this call 2026-09-03, and it is load-bearing.** The
> FIRST read of a document is now windowed by DEFAULT: with no `max_chars` the
> window is the server's `USPTO_MAX_RESPONSE_CHARS` budget (40,000 by default),
> shrunk further if the serialized envelope would still exceed it. Before that,
> an unwindowed first read of a 59,619-character decision returned a
> 72,283-character envelope that the client replaced with a truncation error
> the server never saw (measured on prod 2026-09-03, IPR2024-00864 document
> 171263180). The 95,000 floor below is a floor on the WHOLE document, so this
> call has to ask for the whole document. Run the same call **without**
> `max_chars` as the second half of this test and expect a first window under
> the response budget with `_window.has_more: true`, `_window.total` at or
> above 95,000, `_window.next_offset` set, and `character_count` equal to the
> length of the returned `text` (the window), not of the document.

> **Loosened to a floor 2026-09-02.** This was pinned at ~98,382 and drifted to
> 99,647 on staging. pypdf's text output moves with the library version and
> with how the page-header insertion lands, so an exact character count is a
> version pin wearing a content assertion's clothes. What matters is that the
> pypdf tier ran (not OCR), that all 75 pages came through, and that the
> extraction is a full document rather than the sub-100-char stub that used to
> be silently discarded. Investigate a count BELOW the floor or a
> `extraction_method` that is not `pypdf2`; ignore drift above it.
>
> **Floor NOT re-baselined for the pypdf migration (2026-09-03).** The
> `PyPDF2>=3.0.0` dependency was replaced with `pypdf>=5.1.0` (PyPDF2 3.0.1
> is the terminal release of a renamed, end-of-life project and receives no
> security fixes; it parses party-authored exhibit bytes twice per request).
> `PdfReader` and `extract_text()` are source-compatible and the
> `extraction_method` value stays `"pypdf2"` because the eval suite pins it,
> but the extracted character count is exactly the thing that moves with the
> library version. Confirming the new count needs a live fetch of
> IPR2023-01035 doc 170603095, which the offline fix pass could not make.
> **Verified 2026-09-03 on prod after the pypdf migration: 99,649 characters,
> 75 pages** (claude.ai run against the deployed build), so the 95,000 floor
> stands as a confirmed number; a count below it is now a regression.

### T14 PTAB_get_document_content — forced Mistral OCR
```
PTAB_get_document_content
{"document_id": "170603095", "identifier": "IPR2023-01035", "identifier_type": "trial", "use_ocr": true}
```
**Expect:** `extraction_method: "mistral_ocr"`, extraction metadata only in the payload, progress messages "Uploading … to Mistral OCR" and "Running Mistral OCR…".

### T15 Docling tier — page gate
With `MISTRAL_API_KEY` unset (or invalid) and `DOCLING_SERVE_URL=https://docling.example.com`:
- Run T13's call on a **≤20-page** scanned document → **Expect:** `extraction_method: "docling"`, extraction metadata only in the payload.
- Run on a >20-page document → **Expect:** Docling skipped (log: "exceeds DOCLING_MAX_PAGES"), error JSON with `docling_configured: true` guidance.

## Section 5 — Guidance, Config, Prompts, HTTP (3 tests)

### T16 Utility tools
```
PTAB_get_guidance
{"section": "tools"}
```
```
PTAB_get_field_configs
{}
```
**Expect:** Guidance returns the tools section markdown; field configs show trials/appeals/interferences minimal/balanced/complete sets, and every path in them matches the API's real nesting (see T3/T4). Guidance must reference 14 tools (no `validate_identifiers`).

> **What this test pins is the SERVER's contract, verified live in the staging
> container 2026-09-02:** `tools/list` returns 14 tools, and
> `PTAB_get_guidance` is among them with `defer_loading: false` (the three
> eager tools are `PTAB_search_trials_minimal`, `PTAB_get_documents` and
> `PTAB_get_guidance`).
>
> **Whether any given client SURFACES it is client policy, not a server
> defect.** `defer_loading` is advisory metadata each client applies by its
> own rules: the Anthropic API honours it per-toolset config, Claude Code
> defers everything reached through a claude.ai connector behind its own tool
> search no matter what the annotation says, and the claude.ai connector
> runtime makes its own bucketing decisions. An eager annotation therefore
> guarantees nothing about visibility in a particular environment, and
> reconnecting the connector may change nothing.
>
> A tester who cannot see the tool should record **"not surfaced in this
> client (server contract verified)"**, not "tool missing", and should reach
> it by name or through the client's tool search. This is also why the
> load-bearing workflow content deliberately rides in the tool docstrings and
> in the tools' own return payloads as well as in `PTAB_get_guidance`: no
> instruction that matters is allowed to depend on one tool being surfaced.

### T17 Prompt template (requires `PTAB_ENABLE_PROMPTS=true`)
Prompts are registration-gated (default off): with `PTAB_ENABLE_PROMPTS` unset, the prompt picker shows no PTAB prompts. Start the server with `PTAB_ENABLE_PROMPTS=true`, then invoke the `trial_precedent_research` prompt from Claude Desktop's prompt picker.
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
| IPR2024-01353 | Pagination + document listing | 108 documents via POST search endpoint (live 2026-09-03); patent 7,883,848; Petition doc `170873668`, Final Written Decision doc `171303338` (Paper 40, 2026-03-04) |
| IPR2023-01035 | Download + extraction | Petition doc `170603095`, ~98,382 chars via pypdf, ~1.19 MB PDF; NOT in search index (URI-pattern fallback) |

### Tool coverage matrix
| Tool | Tests |
|---|---|
| PTAB_search_trials_minimal / balanced / complete | T1, T2, T2b (complete: run T1 args with complete tier as a spot check; T2b's bulk-list case covers the complete tier too) |
| PTAB_search_appeals_minimal / balanced / complete | T3 (balanced/complete: same args, higher tier) |
| PTAB_search_interferences_minimal / balanced / complete | T4 (higher tiers: same args) |
| PTAB_get_documents | T6, T7, T8 |
| PTAB_get_document_download | T9–T12 |
| PTAB_get_document_content | T13–T15 |
| PTAB_get_guidance / PTAB_get_field_configs | T16 |

### Environment variables exercised
`USPTO_API_KEY`, `MISTRAL_API_KEY`, `MISTRAL_OCR_MODEL`, `DOCLING_SERVE_URL`, `DOCLING_TIMEOUT`, `DOCLING_MAX_PAGES`, `PTAB_PROXY_PORT`, `PTAB_PROXY_BASE_URL`, `CENTRALIZED_PROXY_URL`, `CENTRALIZED_PROXY_PORT`, `INTERNAL_AUTH_SECRET`, `FASTMCP_TRANSPORT`, `FASTMCP_HOST`, `FASTMCP_PORT`, `CORS_EXTRA_ORIGIN`, `PROXY_ALLOWED_IPS`, `MCP_APP_EXTRA_DOMAINS`

**Last validated:** 2026-07-02 (T1, T6, T9, T10-equivalent, T13, T18 verified programmatically during migration; iframe/browser-page tests require Claude Desktop)
