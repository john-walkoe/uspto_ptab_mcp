"""
Filter Field Mappings - Centralized field name constants for USPTO API filters.

Provides type-safe, autocomplete-friendly field name constants for building
filters in search operations. Single source of truth for API field names.

Benefits:
- IDE autocomplete support
- Type safety (typos caught at development time)
- Easy to update if API field names change
- Documentation of available filter fields in one place

PROVENANCE
----------
Not every constant below carries the same evidential weight. Some were
confirmed by an actual request against the live USPTO ODP API; others are
transcriptions from USPTO's mapping documentation that no one has exercised.
FIELD_PROVENANCE (bottom of this module) records which is which, with the
verification date and method, so a future reader can tell a probed fact from
an assumed one instead of trusting the whole file equally.
"""


class TrialFilterFields:
    """
    Field name mappings for PTAB trial proceeding searches.

    Used by PTAB_search_trials_minimal, PTAB_search_trials_balanced, and PTAB_search_trials_complete.
    Maps intuitive constant names to exact USPTO API field names.
    """

    # Core Trial Identifiers
    TRIAL_NUMBER = "trialNumber"

    # Patent Owner Data
    PATENT_NUMBER = "patentOwnerData.patentNumber"
    #: The patent owner's name as the live payload actually carries it. The
    #: name this constant used to hold, "patentOwnerData.patentOwnerName",
    #: IS NOT POPULATED — a trial record's patent-owner bag carries
    #: realPartyInInterestName and no patentOwnerName at all (verified live
    #: 2026-08-30 on IPR2025-01083; a filter on the dead field returned HTTP
    #: 404 "no matching records" for 'Orca', whose proceedings the corpus
    #: certainly holds). Every patent_owner_name search therefore returned
    #: zero, which reads as "never challenged".
    PATENT_OWNER_NAME = "patentOwnerData.realPartyInInterestName"
    #: Kept as a fallback: patent-owner searches OR it with the populated
    #: field, so nothing has to change if USPTO ever populates it.
    PATENT_OWNER_NAME_LEGACY = "patentOwnerData.patentOwnerName"
    PATENT_OWNER_COUNSEL = "patentOwnerData.counselName"  # NOT "patentOwnerCounsel" (404) — verified live 2026-07-02

    # Petitioner Data
    #: ⚠️ Naming this field in `filters` does NOT restrict the match to the
    #: petitioner side — the endpoint matches either party's name against
    #: either party field (verified live 2026-08-30). Role scoping is done
    #: through the endpoint's `q` parameter instead; see
    #: util/party_scope.py, which both trial party filters route through.
    PETITIONER_NAME = "regularPetitionerData.realPartyInInterestName"
    PETITIONER_COUNSEL = "regularPetitionerData.counselName"  # NOT "petitionerData.petitionerCounsel" (404) — verified live 2026-07-02

    # Trial Metadata
    TRIAL_TYPE = "trialMetaData.trialTypeCode"  # IPR, PGR, CBM, DER
    TRIAL_STATUS = "trialMetaData.trialStatusCategory"
    FILING_DATE = "trialMetaData.accordedFilingDate"  # Range filter

    # Date range filters — the field names below are the ones the payload
    # actually carries. Verified live 2026-08-30: a trialMetaData bag holds
    # accordedFilingDate, petitionFilingDate, institutionDecisionDate,
    # terminationDate, latestDecisionDate, trialLastModifiedDate. The names
    # this module used to carry, "trialMetaData.institutionDate" and
    # "trialMetaData.finalDecisionDate", DO NOT EXIST — a range filter on
    # either returned HTTP 404 "no matching records" for every window, so
    # every institution/final-decision date search silently returned nothing.
    INSTITUTION_DECISION_DATE = "trialMetaData.institutionDecisionDate"  # Range filter
    #: The most recent decision DOCKETED IN THE PROCEEDING. That includes a
    #: Federal Circuit order entered into the PTAB record, so it is NOT
    #: necessarily the Board's final-written-decision date (IPR2024-00990
    #: reads 2026-07-21, the date a Fed. Cir. dismissal was docketed, while
    #: the FWD issued 2025-12-09). There is no final-decision-date field.
    LATEST_DECISION_DATE = "trialMetaData.latestDecisionDate"  # Range filter
    TERMINATION_DATE = "trialMetaData.terminationDate"  # Range filter

    # Backward-compatible aliases for the two constants whose VALUES were
    # wrong. The names are kept so existing imports resolve; they now point
    # at fields that exist.
    INSTITUTION_DATE = INSTITUTION_DECISION_DATE
    FINAL_DECISION_DATE = LATEST_DECISION_DATE

    # Patent Owner / USPTO Data
    # Note: technologyCenterNumber lives under patentOwnerData per ODP API mapping doc
    TECH_CENTER = "patentOwnerData.technologyCenterNumber"

    # REMOVED (verified live 2026-07-02): trial records contain only 5 top-level
    # bags (trialNumber, lastModifiedDateTime, trialMetaData,
    # regularPetitionerData, patentOwnerData). respondentData.* and
    # decisionData.* filters (examinerName, artUnit, assigneeName,
    # decisionOutcome) always returned 404 "no matching records". The appeals
    # AppealFilterFields equivalents below are valid — do not confuse them.


class AppealFilterFields:
    """
    Field name mappings for PTAB ex parte appeal searches.

    Used by PTAB_search_appeals_minimal, PTAB_search_appeals_balanced, and PTAB_search_appeals_complete.

    Based on actual ODP API structure (verified 2026-01-11):
    - appealNumber (root level)
    - appealMetaData.* (appeal metadata)
    - appellantData.* (appellant/applicant information)
    - documentData.* (document information)
    - decisionData.* (decision information)
    """

    # Core Appeal Identifiers
    APPEAL_NUMBER = "appealNumber"  # Root level field
    APPLICATION_NUMBER = "appellantData.applicationNumberText"  # NOT "applicationNumber"!

    # Appellant/Applicant Data
    APPELLANT_NAME = "appellantData.realPartyInInterestName"
    PATENT_OWNER_NAME = "appellantData.patentOwnerName"
    INVENTOR_NAME = "appellantData.inventorName"
    COUNSEL_NAME = "appellantData.counselName"
    PUBLICATION_NUMBER = "appellantData.publicationNumber"
    PUBLICATION_DATE = "appellantData.publicationDate"

    # Note: Appeals are typically for applications, not granted patents
    # Some appeals may have patent numbers if the application was granted
    # This field may not exist in all appeals records

    # Appeal Metadata
    APPEAL_FILING_DATE = "appealMetaData.appealFilingDate"  # Range filter
    APPEAL_LAST_MODIFIED_DATE = "appealMetaData.appealLastModifiedDate"  # Range filter
    APPLICATION_TYPE = "appealMetaData.applicationTypeCategory"

    # USPTO Data
    TECH_CENTER = "appellantData.technologyCenterNumber"
    ART_UNIT = "appellantData.groupArtUnitNumber"

    # Document Data
    DOCUMENT_FILING_DATE = "documentData.documentFilingDate"  # Range filter
    DOCUMENT_TYPE = "documentData.documentTypeDescriptionText"
    DOCUMENT_NAME = "documentData.documentName"

    # Decision Data
    DECISION_DATE = "decisionData.decisionIssueDate"  # Range filter - CORRECT FIELD!
    DECISION_TYPE = "decisionData.decisionTypeCategory"  # NOT "decisionType"!
    DECISION_OUTCOME = "decisionData.appealOutcomeCategory"  # NOT "decisionOutcome"!
    ISSUE_TYPES = "decisionData.issueTypeBag"  # Array of issue types (102, 103, etc.)


class InterferenceFilterFields:
    """
    Field name mappings for PTAB interference proceeding searches.

    Used by PTAB_search_interferences_minimal, PTAB_search_interferences_balanced, and PTAB_search_interferences_complete.

    Based on actual ODP API structure (verified 2026-01-11):
    - interferenceNumber (root level)
    - interferenceMetaData.* (interference metadata)
    - seniorPartyData.* (senior party information)
    - juniorPartyData.* (junior party information)
    - additionalPartyDataBag[] (additional parties)
    - documentData.* (document information)
    """

    # Core Interference Identifiers
    INTERFERENCE_NUMBER = "interferenceNumber"  # Root level field
    INTERFERENCE_STYLE_NAME = "interferenceMetaData.interferenceStyleName"

    # Interference Metadata
    DECLARATION_DATE = "interferenceMetaData.declarationDate"  # Range filter
    INTERFERENCE_LAST_MODIFIED_DATE = "interferenceMetaData.interferenceLastModifiedDate"  # Range filter

    # Senior Party Data
    SENIOR_APPLICATION_NUMBER = "seniorPartyData.applicationNumberText"
    SENIOR_PATENT_NUMBER = "seniorPartyData.patentNumber"
    SENIOR_PARTY_NAME = "seniorPartyData.patentOwnerName"
    SENIOR_INVENTOR_NAME = "seniorPartyData.inventorName"
    SENIOR_COUNSEL_NAME = "seniorPartyData.counselName"
    SENIOR_TECH_CENTER = "seniorPartyData.technologyCenterNumber"
    SENIOR_ART_UNIT = "seniorPartyData.groupArtUnitNumber"
    SENIOR_PUBLICATION_NUMBER = "seniorPartyData.publicationNumber"
    SENIOR_PUBLICATION_DATE = "seniorPartyData.publicationDate"
    SENIOR_RPI_NAME = "seniorPartyData.realPartyInInterestName"

    # Junior Party Data
    JUNIOR_APPLICATION_NUMBER = "juniorPartyData.applicationNumberText"
    JUNIOR_PATENT_NUMBER = "juniorPartyData.patentNumber"
    JUNIOR_PARTY_NAME = "juniorPartyData.patentOwnerName"
    JUNIOR_INVENTOR_NAME = "juniorPartyData.inventorName"
    JUNIOR_COUNSEL_NAME = "juniorPartyData.counselName"
    JUNIOR_TECH_CENTER = "juniorPartyData.technologyCenterNumber"
    JUNIOR_ART_UNIT = "juniorPartyData.groupArtUnitNumber"
    JUNIOR_PUBLICATION_NUMBER = "juniorPartyData.publicationNumber"
    JUNIOR_PUBLICATION_DATE = "juniorPartyData.publicationDate"
    JUNIOR_GRANT_DATE = "juniorPartyData.grantDate"
    JUNIOR_RPI_NAME = "juniorPartyData.realPartyInInterestName"

    # Document Data
    DOCUMENT_NAME = "documentData.documentName"


class TrialDocumentFilterFields:
    """Filter field names for the trials/documents/search endpoint.

    These make PTAB_get_documents' title / category / filing-party filters
    SERVER-side, i.e. docket-wide, instead of client-side over one page.
    Verified live 2026-08-30 against IPR2024-00990 and IPR2024-00864.
    """

    TRIAL_NUMBER = "trialNumber"
    #: Exact match on one paper's own identifier, so a single document's
    #: metadata can be resolved in ONE request instead of walking the docket
    #: (verified live 2026-09-03). This is what
    #: PTAB_get_document_download / PTAB_get_document_content look the paper up
    #: with before they fall back to the constructed ptab-files URI, which
    #: carries no metadata at all.
    DOCUMENT_IDENTIFIER = "documentData.documentIdentifier"
    #: Exact match, case-insensitive ('EXHIBIT' and 'Exhibit' return the same
    #: rows). Vocabulary: TRIAL_DOCUMENT_CATEGORIES below.
    DOCUMENT_CATEGORY = "documentData.documentCategory"
    #: Phrase match on the paper's own title, case-insensitive. It matches
    #: whole words in order, NOT arbitrary substrings: 'Final Written
    #: Decision' matches, 'Instit' does not.
    DOCUMENT_TITLE = "documentData.documentTitleText"
    DOCUMENT_TYPE_DESCRIPTION = "documentData.documentTypeDescriptionText"
    #: BOARD | PETITIONER | PATENT OWNER
    FILING_PARTY = "documentData.filingPartyCategory"
    DOCUMENT_FILING_DATE = "documentData.documentFilingDate"  # Range filter


#: Every `documentData.documentCategory` value observed on the live trials
#: document index (probed 2026-08-30: each value below was filtered for
#: server-side and returned rows; the counts are corpus-wide at that date).
#: An unlisted value returns HTTP 404 "no matching records", which is
#: indistinguishable from a real empty result — so guess nothing.
#:
#: TWO ERAS, and this is the trap. Papers filed from roughly 2023 onward
#: carry a per-paper category (the "modern" block). Older dockets carry only
#: the legacy catch-alls: IPR2015-00040's 172 papers are 48 'Paper' + 52
#: 'Exhibits' and nothing else, so document_category='FINAL' cannot find a
#: 2015 final written decision. The earliest 'FINAL' observed is 2021-08-31;
#: the latest 'Paper' is 2022-12-23.
TRIAL_DOCUMENT_CATEGORIES = {
    # --- modern, per-paper (roughly 2023 onward) ---
    "PETITION": "The petition itself",
    "POPR": "Patent owner's preliminary response",
    "RESPONSE": "Patent owner response, and discretionary-denial briefing",
    "REPLY": "Reply in support of a motion",
    "REPLYTOOPP": "Petitioner's reply to the patent owner response",
    "SURREPLY": "Sur-reply (rare as a category; usually filed as RESPONSE)",
    "MOTION": "Motions, oppositions to Director Review, motions to seal",
    "OPPOSITION": "Opposition to a motion",
    "ORDER": "Board orders (conduct of proceeding, panel change, hearing)",
    "DECISION": "Institution decision (grant or deny) — NOT the FWD",
    "FINAL": "FINAL WRITTEN DECISION. The FWD's category is FINAL, not "
             "DECISION. DECISION is the institution decision.",
    "REHEARING": "Rehearing and Director Review decisions and orders",
    "REQUEST": "Requests for rehearing / Director Review / oral argument",
    "NOTICE": "Notices (filing date, deposition, appeal, refund, exhibit lists)",
    "TERMINATE": "Termination decisions (settlement, adverse judgment)",
    "PWR ATTY": "Powers of attorney",
    "Exhibit": "Exhibits (mixed case in the payload; the filter is "
               "case-insensitive). The bulk of any docket.",
    "OTHER": "Catch-all. Includes party-filed public/redacted copies of "
             "sealed Board papers — on a sealed docket the only Final "
             "Written Decision row can be an OTHER filed by a PARTY.",
    # --- legacy catch-alls (dockets up to roughly 2022) ---
    "Paper": "LEGACY. Every non-exhibit paper on a pre-2023 docket, whatever "
             "it is: petition, POPR, orders, the FWD.",
    "Exhibits": "LEGACY. Every exhibit on a pre-2023 docket.",
}


# ---------------------------------------------------------------------------
# Provenance record
# ---------------------------------------------------------------------------
# Only facts this repo actually established by probing the live USPTO ODP API
# are listed as verified. Everything else is explicitly recorded as NOT probed
# — including things that look authoritative because they sit in a constant.
#
# `method` values:
#   live_probe   - a real request was issued and its response observed
#   live_measure - a real response was measured (sizes, counts)
#   doc_transcription - copied from USPTO's field-mapping documentation; the
#                       field name has never been exercised against the API
#
# Dates are the date of the observation, not the date this record was written.

FIELD_PROVENANCE = {
    "verified": [
        {
            "fact": "TrialFilterFields.PETITIONER_COUNSEL is "
                    "'regularPetitionerData.counselName' and "
                    "PATENT_OWNER_COUNSEL is 'patentOwnerData.counselName'",
            "baseline": "the intuitive names 'petitionerData.petitionerCounsel' "
                        "and 'patentOwnerCounsel' both returned HTTP 404",
            "method": "live_probe",
            "date": "2026-07-02",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "A trial record carries exactly 5 top-level bags: trialNumber, "
                    "lastModifiedDateTime, trialMetaData, regularPetitionerData, "
                    "patentOwnerData",
            "baseline": "respondentData.* and decisionData.* filters "
                        "(examinerName, artUnit, assigneeName, decisionOutcome) "
                        "always returned 404 'no matching records'; those "
                        "constants were removed as a result. The AppealFilterFields "
                        "equivalents are a DIFFERENT endpoint and remain valid.",
            "method": "live_probe",
            "date": "2026-07-02",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "The PTAB search endpoints signal 'zero matching records' with "
                    "HTTP 404 rather than an empty result set",
            "baseline": "PTAB_search_trials_minimal(patent_owner_name='Broadcom') "
                        "returned a 404 error envelope, not count: 0. "
                        "util/search_runner.py maps it back to an empty success.",
            "method": "live_probe",
            "date": "2026-08-16",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "The POST search endpoints reject a page limit above 100 with "
                    "HTTP 400 'Requested page limit exceeds allowed limit 100'",
            "baseline": "api/ptab_client.py clamps to 100 because of this; the "
                        "tool layer accepts up to 200 and the `paging.limit_applied` "
                        "block reports the clamped value.",
            "method": "live_probe",
            "date": "2026-07-02",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "Trial document entries carry a documentOCRText excerpt of "
                    "roughly 1K characters each",
            "baseline": "a limit=100 page on a decision-heavy trial breached the "
                        "~40K client response cap; a default limit=50 docket lands "
                        "near 12K. This sizing is why documentOCRText is the first "
                        "field the response guard sheds.",
            "method": "live_measure",
            "date": "2026-08-16",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "trials/documents/search honors a non-zero pagination.offset "
                    "(true server-side paging, with the API's own total in `count`)",
            "baseline": "PTAB_get_documents pages a docket with offset/limit and "
                        "api/ptab_client.search_all_trial_documents walks a docket "
                        "100 rows at a time using it.",
            "method": "live_probe",
            "date": "2026-08-16",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "trialMetaData carries institutionDecisionDate, "
                    "latestDecisionDate and terminationDate. It does NOT carry "
                    "institutionDate or finalDecisionDate.",
            "baseline": "A rangeFilter on trialMetaData.institutionDate or "
                        "trialMetaData.finalDecisionDate returned HTTP 404 'no "
                        "matching records' for 2024-01-01..2024-12-31, while the "
                        "same window returned 1046 (institutionDecisionDate), "
                        "1385 (latestDecisionDate) and 1177 (terminationDate). "
                        "Confirmed against the raw IPR2024-00990 record, whose "
                        "trialMetaData holds accordedFilingDate, petitionFilingDate, "
                        "institutionDecisionDate, terminationDate, latestDecisionDate, "
                        "trialLastModifiedDate, trialStatusCategory, trialTypeCode, "
                        "fileDownloadURI.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "A rangeFilter with only one bound is rejected with HTTP 400 "
                    "Bad Request — the API requires both valueFrom and valueTo",
            "baseline": "{'field': 'trialMetaData.accordedFilingDate', "
                        "'valueFrom': '2024-01-01', 'valueTo': None} -> 400, and "
                        "the mirror image with only valueTo -> 400. "
                        "util/filter_builder.add_range_if now defaults the missing "
                        "bound (DEFAULT_RANGE_FROM / today) instead of emitting a "
                        "null.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "trials/documents/search accepts documentData.documentCategory, "
                    "documentData.documentTitleText and "
                    "documentData.filingPartyCategory as SERVER-side filters",
            "baseline": "On IPR2024-00990: documentCategory=FINAL -> count 1 (the "
                        "FWD, Paper 38); documentTitleText='Final Written Decision' "
                        "-> count 4; filingPartyCategory=BOARD -> count 17. The "
                        "counts are docket-wide, not page-wide. An unqualified "
                        "'documentCategory' (no documentData. prefix) 404s, as does "
                        "an unknown field — so a 404 here means 'no rows', not "
                        "'bad field', and the two are indistinguishable.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "trials/documents/search accepts "
                    "documentData.documentIdentifier as a SERVER-side filter, so "
                    "one paper's metadata is one request",
            "baseline": "IPR2024-01353 + documentIdentifier 171303338 -> count 1 "
                        "(Final Written Decision, Paper 40, filed 2026-03-04) and "
                        "IPR2023-01035 + 170603095 -> count 1 (the Petition), both "
                        "carrying the same parent bag as an unfiltered page. The "
                        "unprefixed 'documentIdentifier' 404s, as does an id the "
                        "docket does not hold. This is the lookup "
                        "PTAB_get_document_download / PTAB_get_document_content try "
                        "FIRST: before it existed, the only path to a paper's "
                        "metadata was the whole-docket walk, and any miss (upstream "
                        "failure, the 500-document safety cap) fell through to the "
                        "constructed ptab-files URI, which names the file from the "
                        "PROCEEDING's filing date and the word 'Document'.",
            "method": "live_probe",
            "date": "2026-09-03",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "The documentCategory vocabulary is TRIAL_DOCUMENT_CATEGORIES "
                    "(20 values), and the final written decision's category is "
                    "FINAL, not DECISION",
            "baseline": "Each value was filtered for server-side and returned rows "
                        "(corpus-wide counts 2026-08-30: NOTICE 64052, OTHER 24051, "
                        "MOTION 18582, ORDER 17190, RESPONSE 8734, PETITION 6437, "
                        "DECISION 5482, OPPOSITION 3851, REPLY 3737, POPR 3680, "
                        "REQUEST 2525, FINAL 2020, TERMINATE 1780, REHEARING 1235, "
                        "PWR ATTY 5071, SURREPLY 3, Exhibit 430227, plus the legacy "
                        "Paper 316712 and Exhibits 613608). JUDGMENT, TRANSCRIPT, "
                        "BRIEF, HEARING, CERTIFICATE and a dozen other plausible "
                        "guesses all 404. Matching is case-insensitive.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "A docket can omit the Board's own paper entirely",
            "baseline": "IPR2024-00864 (305 documents, sealed trial): "
                        "documentCategory=FINAL returns 404, filingParty=BOARD "
                        "never returns an FWD, and the only Final Written Decision "
                        "rows are Paper 86 'Final Written Decision (Public)' and "
                        "Paper 87, both category OTHER and both filed by "
                        "PETITIONER. The Board's Paper 85 is not a docket row. "
                        "PTAB_get_documents reports this as `coverage_note`.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/documents/search",
        },
        {
            "fact": "A party-name `filters` entry is NOT role-scoped — it matches "
                    "either party's name against either party's field — while the "
                    "same endpoint's `q` parameter IS field-scoped",
            "baseline": "filters regularPetitionerData.realPartyInInterestName="
                        "'WIZ' -> 17 records, five of them (IPR2025-01083..-01087) "
                        "with 'Orca Security Ltd.' as petitioner and Wiz as patent "
                        "owner; filters patentOwnerData.realPartyInInterestName="
                        "'Orca' -> the SAME 17. q='regularPetitionerData."
                        "realPartyInInterestName:(\"WIZ\")' -> 12, the Wiz-as-"
                        "petitioner set only. At scale: 'Apple AND Inc.' as "
                        "petitioner is 1029 through q against 1055 through "
                        "filters. `q` intersects with filters, rangeFilters and "
                        "pagination.offset, and still 404s on zero matches. "
                        "util/party_scope.py builds the scoped clause.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/proceedings/search",
        },
        {
            "fact": "patentOwnerData.patentOwnerName is UNPOPULATED; the patent "
                    "owner's name lives in patentOwnerData.realPartyInInterestName",
            "baseline": "The raw IPR2025-01083 record's patentOwnerData holds "
                        "patentNumber, grantDate, realPartyInInterestName "
                        "('Wiz, Inc.'), technologyCenterNumber, groupArtUnitNumber, "
                        "applicationNumberText, inventorName, counselName — and no "
                        "patentOwnerName key at all. A filter or q clause on "
                        "patentOwnerData.patentOwnerName='Orca' 404s, while the "
                        "same value on realPartyInInterestName returns 12. "
                        "TrialFilterFields.PATENT_OWNER_NAME was remapped; the "
                        "dead name survives as PATENT_OWNER_NAME_LEGACY and is "
                        "OR-ed in so the search self-heals if it ever populates.",
            "method": "live_probe",
            "date": "2026-08-30",
            "endpoint": "trials/proceedings/search",
        },
    ],
    "not_probed": [
        {
            "fact": "Every AppealFilterFields and InterferenceFilterFields constant",
            "status": "doc_transcription, dated 2026-01-11 against USPTO's ODP "
                      "structure documentation. The bag SHAPES were checked; the "
                      "individual field names were not each exercised, so a 404 "
                      "from one of them is a plausible field-name error rather "
                      "than proof of no matching records.",
        },
        {
            "fact": "trials/proceedings/search, appeals and interferences search "
                    "with a non-zero pagination.offset",
            "status": "NOT probed. The request body is byte-identical in shape to "
                      "trials/documents/search (api/ptab_client._search builds all "
                      "four), and that endpoint's offset paging IS verified, so "
                      "the search tools now plumb offset through. If a proceeding "
                      "endpoint turns out to ignore offset, `paging.returned` and "
                      "`paging.total` will show it (page 2 repeating page 1).",
        },
        {
            "fact": "The trials endpoint OR-matches unquoted multi-word values, "
                    "which is why validators.build_and_query AND-joins tokens",
            "status": "Asserted in tools/trials.py without a recorded probe date. "
                      "Treat the behavior as likely but undated.",
        },
        {
            "fact": "'interferenceOutcomeCategory' — the field "
                    "tools/documents.py:_filter_documents matches on for the "
                    "outcome_category filter on interferences",
            "status": "NOT probed, and SUSPECT: api/proceedings.py's interference "
                      "adapter does not populate that key when it flattens "
                      "documents (the appeal adapter does populate "
                      "appealOutcomeCategory), so the filter likely matches "
                      "nothing. Deliberately left as-is — establishing the right "
                      "field name needs a live probe.",
        },
    ],
}


# Export all field mapping classes
__all__ = [
    'TrialFilterFields',
    'TrialDocumentFilterFields',
    'TRIAL_DOCUMENT_CATEGORIES',
    'AppealFilterFields',
    'InterferenceFilterFields',
    'FIELD_PROVENANCE',
]
