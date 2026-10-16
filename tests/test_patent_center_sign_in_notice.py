"""Patent Center is only readable signed in, and every surface says so.

A Patent Center link handed to a reader with no USPTO.gov account does not
error: it silently renders the site's own front page. The reader then believes
the citation was wrong. So both surfaces that hand out such a link carry the
same sentence — the JSON `citation_note` the model reads, and the MCP App
search-results panel that renders a "Patent Center" button.

The sentence lives once in `shared/citations.py`, the module vendored
byte-identical into uspto_fpd_mcp; it is asserted verbatim here so a reworded
copy in the panel cannot drift away from it.
"""

from ptab_mcp.shared import citations as shared_citations
from ptab_mcp.ui.views import SEARCH_RESULTS_HTML

SIGN_IN_SENTENCE = (
    "Patent Center shows an application only to a signed-in reader: without a "
    "free USPTO.gov account the link lands on its own front page rather than "
    "on the desired application."
)


def test_the_envelope_note_carries_the_sign_in_sentence():
    assert SIGN_IN_SENTENCE in shared_citations.CITATION_NOTE
    assert (
        shared_citations.PATENT_CENTER_SIGN_IN_RULE
        in shared_citations.CITATION_NOTE
    )
    # No em dashes in new prose (repo rule).
    assert "—" not in shared_citations.PATENT_CENTER_SIGN_IN_RULE


def test_the_rule_tells_the_model_what_to_do_with_each_target():
    rule = shared_citations.PATENT_CENTER_SIGN_IN_RULE
    assert "patentcenter.uspto.gov" in rule
    assert "Google Patents" in rule
    assert "no account" in rule


def test_the_search_results_panel_shows_the_notice():
    assert SIGN_IN_SENTENCE in SEARCH_RESULTS_HTML
    assert 'class="pc-note"' in SEARCH_RESULTS_HTML
    assert ".pc-note {" in SEARCH_RESULTS_HTML


def test_the_existing_button_text_is_untouched():
    assert "Patent Center →" in SEARCH_RESULTS_HTML
