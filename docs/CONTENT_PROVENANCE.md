# Content provenance and retrieved-text handling

This document is the written answer to the security-questionnaire line that asks
"how do you sanitize retrieved content before passing it to an AI model?" It
records what the USPTO PTAB MCP does, what it deliberately does not do, and why.
(The labeling implementation lives in `src/ptab_mcp/shared/injection_scan.py`
(`RETRIEVED_TEXT_NOTE` and the detection-only scanner) and the server
instructions' provenance-posture paragraph in `src/ptab_mcp/main.py`.)

## Source corpus

Every document served by this system originates from the USPTO Patent Trial and
Appeal Board via the Open Data Portal PTAB API: trial (IPR/PGR/CBM), appeal, and
interference proceedings — party-filed petitions, briefs, responses, exhibits,
and Board-authored decisions. Filers are identified parties in adversarial legal
proceedings and filings carry legal effect. This is a curated regulatory corpus,
not the open web: there is no anonymous user-generated content in the retrieval
path. But "curated" is not "trusted": a petition, brief, or exhibit can embed
literally any text a party drafted, including exhibits reproducing arbitrary
third-party documents.

## What we deliberately do NOT do: strip or rewrite document text

Legal research depends on verbatim fidelity. A "sanitization" pass that removes
or rewrites token sequences from a Board decision, petition, or exhibit would
corrupt the exact language attorneys are retrieving — claim constructions,
obviousness reasoning, quoted prior art. Document text is therefore served
verbatim (or as faithful OCR of image-filed documents via the PyPDF2 -> Mistral
OCR -> Docling extraction chain), with provenance attached, and is never mutated
in the name of injection defense.

## What we do instead: structured, provenance-aware interfaces

1. **Data/instruction separation by labeling.** The document-content tool
   (`ptab_get_document_content`) — the one tool that returns retrieved document
   text — carries a machine-readable `provenance_note` stating that the text is
   quoted data, not instructions, and the server-level instructions direct the
   consuming model to report instruction-like language found inside retrieved
   text rather than act on it. Party-drafted characterizations are to be
   presented as attributed advocacy, not established fact.
2. **Detection-only injection scanning at tool-call time.** Extracted text is
   scanned for injection-shaped content (instruction-override, prompt-extraction,
   encoding-evasion language, and invisible-Unicode steganography density). On a
   hit, the response carries an `injection_scan` annotation naming the flagged
   document by identifier and kind labels only — never the matched text — and
   the annotation is absent entirely when the text is clean. The text itself is
   returned untouched (`src/ptab_mcp/shared/injection_scan.py`).
3. **Structured metadata everywhere else.** The nine search tools
   (`search_trials_*`, `search_appeals_*`, `search_interferences_*`) and the
   document-list tool return structured field records from the PTAB API (trial
   numbers, party names, dates, status codes, document metadata) — no free-text
   document passages flow through them.
4. **No generative step in the retrieval path.** The only model in the content
   path is OCR (Mistral OCR or a self-hosted Docling instance), used strictly
   for faithful text extraction of image-filed PDFs; there is no LLM
   summarization or rewriting between the USPTO document and the tool response.
5. **Content-minimizing logging.** Logs record operational flow metadata only —
   tool, status, counts, public PTAB identifiers — never query values, document
   or OCR text, headers/tokens, or link hashes. A sink-level `SanitizingFilter`
   (`src/ptab_mcp/shared/log_sanitizer.py`) is attached to every handler in
   `setup_logging()` (`src/ptab_mcp/config/log_config.py`) as the guarantee, and
   the injection scanner's kind-labels-only contract means scan results are safe
   to relay without content leaking through the logging pipeline.
6. **Codebase-hygiene scanning, separately.** A commit-time prompt-injection
   detector (`.security/ptab_prompt_injection_detector.py`, wired through
   pre-commit) scans this repository's own source tree. It is complementary to,
   and distinct from, the runtime annotation of retrieved corpus content
   described above.

## Residual-risk statement

Prompt-injection risk in this product reduces to: a PTAB filing or exhibit
contains text crafted to influence a downstream AI assistant. The controls above
ensure such text (a) reaches the assistant clearly labeled as quoted document
content with a provenance note, (b) is annotated with detection-only kind labels
when it is injection-shaped, and (c) can always be verified against the primary
source document via the download tools. We consider stripping-based defenses
inappropriate for a corpus whose value is verbatim legal text, and
labeling-plus-detection the correct control for this threat model.
