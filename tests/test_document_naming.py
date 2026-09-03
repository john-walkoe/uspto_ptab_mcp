"""One derivation of a document description, shared by both download routes.

`proxy/server.py` and `tools/documents.py` each derived a human-readable
description from the same USPTO fields in the same priority order, and the
copies had drifted on the substantive point: the proxy read
`appealDocumentCategory` off the PARENT bag item while the tool read it off the
FLATTENED document. The same appeal paper fetched through
PTAB_get_document_download and through /download/{type}/{id}/{doc} could
therefore come back with two different filenames.

`generate_enhanced_filename` moving out of the ASGI server module is the other
half: importing a pure string function from `proxy/server.py` pulled FastAPI,
uvicorn plumbing and module-level proxy state into every tool import.
"""

from src.ptab_mcp.util.document_naming import (
    derive_document_description,
    generate_enhanced_filename,
    sanitize_description,
)


class TestDeriveDocumentDescription:
    def test_the_trial_title_wins_over_everything(self):
        assert derive_document_description(
            {"documentTitleText": "Final Written Decision",
             "documentCategory": "FINAL"}) == "Final Written Decision"

    def test_the_appeal_category_is_read_from_the_parent_bag(self):
        """The tool copy read this off the flattened document and got the
        generic type instead."""
        assert derive_document_description(
            {"documentTypeDescriptionText": "Paper"},
            {"appealDocumentCategory": "Decision"},
        ) == "Decision"

    def test_the_appeal_category_on_the_flattened_document_also_works(self):
        """The proxy copy read this only off the parent and got "Paper"."""
        assert derive_document_description(
            {"appealDocumentCategory": "Decision",
             "documentTypeDescriptionText": "Paper"}) == "Decision"

    def test_both_routes_agree_on_the_same_appeal_paper(self):
        parent = {"appealDocumentCategory": "Decision"}
        flattened = {"appealDocumentCategory": "Decision",
                     "documentTypeDescriptionText": "Paper"}

        assert (derive_document_description(flattened, parent)
                == derive_document_description(flattened))

    def test_the_document_name_stem_is_the_last_resort(self):
        assert derive_document_description(
            {"documentName": "Decision_2025000943_09-18-2025.pdf"}) == "Decision"

    def test_a_name_without_underscores_keeps_its_whole_stem(self):
        assert derive_document_description({"documentName": "Petition.pdf"}) == "Petition"

    def test_nothing_matching_returns_empty_so_callers_pick_their_sentinel(self):
        assert derive_document_description({}) == ""


class TestGenerateEnhancedFilename:
    def test_the_whole_assembled_name_is_sanitized(self):
        """filing_date and patent_number are interpolated from API data and
        land in Content-Disposition and X-Enhanced-Filename, where a CR/LF or a
        quote is header injection."""
        name = generate_enhanced_filename(
            filing_date='2024-05-15"\r\nX-Injected: yes',
            identifier="IPR2024-01353",
            patent_number="788/3848",
            document_description="Final Written Decision",
        )

        assert "\r" not in name and "\n" not in name and '"' not in name
        assert "/" not in name
        assert name.endswith(".pdf")

    def test_a_normal_record_is_unchanged_in_substance(self):
        # Re-baselined to the live IPR2024-01353 record so the fixture matches
        # the example filename in generate_enhanced_filename's docstring.
        name = generate_enhanced_filename(
            filing_date="2024-08-23",
            identifier="IPR2024-01353",
            patent_number="7883848",
            document_description="Final Written Decision",
        )

        assert name == "PTAB-2024-08-23_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf"

    def test_an_all_punctuation_name_still_yields_a_usable_filename(self):
        # sanitize_description strips the description to empty; the surviving
        # components still make a valid, safe filename.
        name = generate_enhanced_filename("", "", None, "///")

        assert name.startswith("PTAB-UNKNOWN_UNKNOWN")
        assert name.endswith(".pdf")
        assert "/" not in name


def test_the_proxy_still_re_exports_the_moved_names():
    """Out-of-repo importers and tests/test_proxy_server.py import these from
    proxy.server."""
    from src.ptab_mcp.proxy import server

    assert server.generate_enhanced_filename is generate_enhanced_filename
    assert server.sanitize_description is sanitize_description
