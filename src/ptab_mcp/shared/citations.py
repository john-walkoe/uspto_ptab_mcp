"""Shared USPTO MCP citation helpers (stdlib-only).

VENDORED MODULE, intended to be byte-identical across `uspto_ptab_mcp` and
`uspto_fpd_mcp`, exactly like `response_bounds.py` and
`uspto_shared_rate_limiter.py`: **stdlib imports only, zero package-relative
imports, no repo-specific constants**. Everything repo-specific (how a row is
labelled, which bag carries the patent number or the serial) stays in the
calling repo's `util/citations.py`. Do not add project imports here.

WHY
---
A tool result that names a PTAB proceeding or a petition decision and carries
no URL leaves the reader nothing to click. The assistant then writes
"IPR2019-00416" into a memo as if that were a citation, and whoever reads the
memo has to go and find the record themselves. Every row therefore carries
`cite_as`: a ready-made markdown link whose label says what the record is and
whose target is the public record it concerns.

THE ONLY TWO TARGET FORMS THIS MODULE BUILDS
--------------------------------------------
Google Patents   https://patents.google.com/patent/US8539047
Patent Center    https://patentcenter.uspto.gov/applications/12950321

Both were probed on 2026-09-05 with
``curl -s -o /dev/null -w "%{http_code}" -L <url>`` and answered 200, as did
the publication form ``https://patents.google.com/patent/US20010056539``.
They are the same two forms the MCP App panels already build client-side
(``ui/views.py``), so a link in the tool JSON and a button in the panel lead
to the same page.

Do not invent a third form. In particular there is NO verified public
per-proceeding URL for a PTAB trial: P-TACTS is a JavaScript application and
its deep-link shape is unknown, so a proceeding is cited through the patent
it challenges (or the application it arose from) rather than through a
guessed URL. If a further form is ever wanted, probe it with the curl line
above first and record the probe here; an unverified URL must not be emitted.

NEVER CITE A DELIVERY LINK
--------------------------
The download proxy's ``/download/persistent/{hash}`` and
``/document/persistent/{hash}`` links are credentials: the hash IS the
authorization (Lesson 43). They are addressed to the person who asked, they
expire, and they are not a public record, so :func:`cite_as_link` refuses to
build a citation on one.
"""

import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# The note every citation-bearing envelope carries
# ---------------------------------------------------------------------------

#: Patent Center is not a public page: it renders an application only to a
#: signed-in reader. A reader handed a bare patentcenter.uspto.gov link with no
#: account lands on the site's own front page and concludes the citation was
#: wrong, so the note that hands out such a link says so, and says that Google
#: Patents carries no such condition.
PATENT_CENTER_SIGN_IN_RULE = (
    " Patent Center shows an application only to a signed-in reader: without a "
    "free USPTO.gov account the link lands on its own front page rather than on "
    "the desired application. So whenever you paste a cite_as whose target is "
    "patentcenter.uspto.gov, say in the same breath that opening it needs a "
    "free USPTO.gov account; a Google Patents link needs no account and needs "
    "no such warning."
)

CITATION_NOTE = (
    "CITATIONS ARE LINKS. Every record in this response carries `cite_as`, a "
    "ready-made markdown link: its label names the record, its target is the "
    "public patent or application record the matter concerns. When you quote "
    "or rely on a record in an answer, a table or a memo, paste its cite_as "
    "after the sentence. A proceeding number, a petition date or an "
    "application serial with no link is not a citation here: the reader has "
    "to be able to click through to a public record. Build no links of your "
    "own, and never present a /download/persistent/ or /document/persistent/ "
    "link from this server as a citation. Those are private delivery links "
    "for the person who asked, not public records."
) + PATENT_CENTER_SIGN_IN_RULE

# ---------------------------------------------------------------------------
# Delivery links (never a citation target)
# ---------------------------------------------------------------------------

#: Path fragments that mark a download-proxy delivery URL. The hash in these
#: paths is the credential, so they are never a citation target.
DELIVERY_LINK_MARKERS = (
    "/document/persistent/",
    "/download/persistent/",
    "/download/",
    "/api/recent-downloads",
)


def is_delivery_link(url: Any) -> bool:
    """True when ``url`` is one of this server's own delivery links."""
    if not url:
        return False
    text = str(url)
    return any(marker in text for marker in DELIVERY_LINK_MARKERS)


# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------

#: Separators USPTO payloads and user input put inside a number.
_SEPARATORS = re.compile(r"[\s,/\-]")

#: Utility grant numbers and the lettered series. The MCP App panels gate
#: their Google Patents button on ``^(RE)?\d{6,8}$``; this is one digit wider
#: on the reissue arm because reissue numbers are five digits (RE45123,
#: RE46123) and that gate rejects every one of them. Both were probed on
#: 2026-09-05 with ``curl -s -o /dev/null -w "%{http_code}" -L
#: https://patents.google.com/patent/USRE45123`` and answered 200.
#:
#: D (design), PP (plant), H (statutory invention registration) and T
#: (defensive publication) were added 2026-09-20. Before that a design or
#: plant number matched nothing and the row came back with NO ``cite_as`` at
#: all -- the safe failure, but still a hole in a product promise that says
#: every row carries a link, and design patents are cited as prior art
#: constantly in design prosecution. Each arm was probed the same way on
#: 2026-09-20 and answered 200: USD618677, USRE45123, USPP12345, USH1234,
#: UST100001. ``AI`` (Additional Improvement, 1838-1861) is deliberately
#: ABSENT: USAI00001 answers 404, so a link built for it would be exactly the
#: dead citation this module exists to avoid.
_PATENT_NUMBER_RE = re.compile(
    r"^(RE\d{5,8}|D\d{5,7}|PP\d{4,6}|H\d{3,6}|T\d{5,7}|\d{6,8})$", re.IGNORECASE
)

#: Pre-grant publication numbers (YYYY + 7 digits), e.g. 20010056539.
_PUBLICATION_NUMBER_RE = re.compile(r"^\d{11}$")

#: US application serials are eight digits (series code + six).
_APPLICATION_NUMBER_RE = re.compile(r"^\d{8}$")


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return _SEPARATORS.sub("", str(value)).strip()


def normalize_patent_number(value: Any) -> Optional[str]:
    """A Google-Patents-ready US patent or publication number, else None.

    Accepts the shapes the USPTO payloads and callers actually use
    (``8539047``, ``8,539,047``, ``US8539047``, ``RE45123``,
    ``20010056539``). Anything else returns None rather than producing a link
    that 404s.
    """
    cleaned = _strip(value).upper()
    if cleaned.startswith("US"):
        cleaned = cleaned[2:]
    # A kind code (B2, A1, ...) is optional on the Google Patents URL and the
    # payloads do not carry one; drop it so a stray suffix still resolves.
    # S and P joined A and B on 2026-09-20 with the lettered series: a design
    # patent's kind code is S1 and a plant patent's is P2/P3, so "D618677S1"
    # used to survive the strip, match nothing and yield no link at all. The
    # lookbehind keeps the leading letters safe -- the P of "PP12345" is not
    # preceded by a digit, so only a trailing kind code is ever removed.
    cleaned = re.sub(r"(?<=\d)[ABSP]\d?$", "", cleaned)
    if not cleaned:
        return None
    if _PATENT_NUMBER_RE.match(cleaned) or _PUBLICATION_NUMBER_RE.match(cleaned):
        return cleaned
    return None


def normalize_application_number(value: Any) -> Optional[str]:
    """An eight-digit US application serial, else None."""
    cleaned = _strip(value)
    if _APPLICATION_NUMBER_RE.match(cleaned):
        return cleaned
    return None


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

GOOGLE_PATENTS_BASE = "https://patents.google.com/patent/US"
PATENT_CENTER_BASE = "https://patentcenter.uspto.gov/applications/"


def google_patents_url(patent_number: Any) -> Optional[str]:
    """Google Patents page for a US patent or publication number, else None."""
    normalized = normalize_patent_number(patent_number)
    if not normalized:
        return None
    return f"{GOOGLE_PATENTS_BASE}{normalized}"


def patent_center_url(application_number: Any) -> Optional[str]:
    """Patent Center page for a US application serial, else None."""
    normalized = normalize_application_number(application_number)
    if not normalized:
        return None
    return f"{PATENT_CENTER_BASE}{normalized}"


# ---------------------------------------------------------------------------
# Display forms + the link itself
# ---------------------------------------------------------------------------

def format_patent_display(patent_number: Any) -> Optional[str]:
    """A patent number as a reader expects to see it: ``US 8,539,047``.

    None when the number is not one this module would link to, so a label can
    never claim a patent the target does not point at.
    """
    normalized = normalize_patent_number(patent_number)
    if not normalized:
        return None
    if normalized.isdigit() and len(normalized) <= 8:
        return f"US {int(normalized):,}"
    return f"US {normalized}"


def format_application_display(application_number: Any) -> Optional[str]:
    """An application serial as a reader expects to see it: ``12/950,321``."""
    normalized = normalize_application_number(application_number)
    if not normalized:
        return None
    # String slicing, never int(): a serial's digits after the series code keep
    # their leading zeros ("19058716" is 19/058,716, not 19/58,716).
    return f"{normalized[:2]}/{normalized[2:5]},{normalized[5:]}"


def cite_as_link(label: Any, url: Any) -> Optional[str]:
    """A markdown citation link, or None without a citable URL.

    Square brackets in the label would close the link text early, so they are
    replaced. A delivery link is refused outright (see the module docstring):
    the caller gets None and emits no citation rather than handing the model a
    credential to publish.
    """
    if not url or is_delivery_link(url):
        return None
    text = " ".join(str(label or "source").split()).replace("[", "(").replace("]", ")")
    if not text:
        return None
    return f"[{text}]({url})"
