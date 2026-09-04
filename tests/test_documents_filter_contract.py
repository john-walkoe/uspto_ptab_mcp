"""The PTAB_get_documents contract: what the parameter descriptions promise,
what filter_semantics_note reports, and what the docstring must not say.
Four defects from the 2026-09-03 skill QA ledger.

3. document_category's parameter description has to name the whole live
   vocabulary AND the sealed-docket case where a final written decision is
   FINAL and OTHER.
4. document_title's parameter description claimed a substring match on
   documentTypeDescriptionText; the live behaviour is a server-side PHRASE
   match on documentTitleText, and a substring over both fields under
   page_all. filter_semantics_note now says which one ran.
7. Docket documentNumber can disagree with the paper's printed caption
   (86 versus "Paper 85" on IPR2024-00864).
8. The docstring framed paging as token usage rather than as capability.

The Args block is the copy under test because it is the parameter description
the MCP client actually renders; a reader who never sees the tool's long
description sees only this.
"""

from src.ptab_mcp.config.filter_field_mapping import TRIAL_DOCUMENT_CATEGORIES
from src.ptab_mcp.tools.documents import _filter_semantics_note, ptab_get_documents

def _arg_description(name: str) -> str:
    """The Args entry for `name`. This is the parameter description the MCP
    client actually renders, so it is the copy that has to be true."""
    doc = ptab_get_documents.__doc__ or ""
    body = doc.split("    Args:\n", 1)[1]
    lines, capturing = [], False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}:"):
            capturing = True
            lines.append(stripped)
            continue
        if capturing:
            if line.startswith("            ") or line.startswith("\t"):
                lines.append(stripped)
                continue
            break
    assert lines, f"no Args entry for {name}"
    return " ".join(lines)


class TestDocumentCategoryDescription:
    def test_every_live_category_is_named(self):
        description = _arg_description("document_category")

        for value in TRIAL_DOCUMENT_CATEGORIES:
            assert value in description, value

    def test_the_sealed_docket_case_is_named(self):
        """A final written decision carries FINAL and, on a sealed docket,
        OTHER, the case that makes an empty FINAL result unreadable."""
        description = _arg_description("document_category")

        assert "OTHER" in description
        assert "IPR2024-00864" in description
        assert "coverage_note" in description

    def test_final_is_still_distinguished_from_decision(self):
        description = _arg_description("document_category")

        assert "institution decision" in description


class TestDocumentTitleDescription:
    def test_the_stale_substring_claim_is_gone(self):
        description = _arg_description("document_title")

        assert "substring match on documentTypeDescriptionText" not in description

    def test_it_describes_the_live_phrase_match(self):
        description = _arg_description("document_title")

        assert "PHRASE match on documentTitleText" in description
        assert "SERVER-side" in description

    def test_it_describes_the_page_all_substring_mode(self):
        description = _arg_description("document_title")

        assert "page_all" in description
        assert "SUBSTRING" in description
        assert "documentTypeDescriptionText" in description
        assert "filter_semantics_note" in description


class TestFilterSemanticsNoteSaysWhichMatchRan:
    def test_pushed_title_is_reported_as_a_phrase_match(self):
        note = _filter_semantics_note(
            pushed=["document_title"], client_side=[], page_all=False
        )

        assert "PHRASE match over documentTitleText" in note
        # The server-side mode is described as "not a substring"; the
        # client-side SUBSTRING sentence must not be attached to it.
        assert "SUBSTRING match" not in note

    def test_page_all_title_is_reported_as_a_substring_match(self):
        note = _filter_semantics_note(
            pushed=[], client_side=["document_title"], page_all=True
        )

        assert "SUBSTRING match" in note
        assert "documentTypeDescriptionText" in note
        assert "page_all=True" in note

    def test_a_client_side_category_says_nothing_about_titles(self):
        note = _filter_semantics_note(
            pushed=[], client_side=["document_category"], page_all=True
        )

        assert "SUBSTRING" not in note


class TestDocketNumberVersusCaption:
    def test_the_note_is_in_the_docstring(self):
        doc = ptab_get_documents.__doc__ or ""

        assert "docket_number_versus_caption" in doc
        assert "documentNumber" in doc
        assert "IPR2024-00864" in doc
        assert "Paper 85" in doc

    def test_it_says_which_number_to_cite(self):
        doc = ptab_get_documents.__doc__ or ""
        section = doc.split("docket_number_versus_caption", 1)[1]

        assert "Cite `documentNumber`" in section
        # Not a systemic offset: the counter-example keeps a reader from
        # "correcting" every paper number by one.
        assert "IPR2024-01353" in section


class TestNoTokenUsageFraming:
    def test_the_docstring_does_not_frame_paging_as_token_cost(self):
        doc = (ptab_get_documents.__doc__ or "").lower()

        for phrase in ("token usage", "token cost", "massive token",
                       "excessive token"):
            assert phrase not in doc, phrase

    def test_it_still_says_why_to_filter(self):
        doc = ptab_get_documents.__doc__ or ""

        assert "ALWAYS use filtering parameters" in doc
        assert "slimmed" in doc
