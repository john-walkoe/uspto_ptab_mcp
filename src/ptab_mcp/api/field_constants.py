"""
Field name constants for PTAB ODP API

Provides constants for all field names in trials, appeals, and interferences
to enable type-safe field filtering and avoid typos in API requests.

Field sets organized by data type and tier (minimal/balanced/complete).
"""



class TrialFields:
    """Field names for PTAB Trials API (IPR, PGR, CBM proceedings)"""

    # Core identifiers
    TRIAL_NUMBER = "trialNumber"
    PROCEEDING_NUMBER = "proceedingNumber"

    # Trial metadata (trialMetaData.*)
    TRIAL_TYPE_CODE = "trialMetaData.trialTypeCode"  # IPR, PGR, CBM
    TRIAL_STATUS_CATEGORY = "trialMetaData.trialStatusCategory"
    ACCORDED_FILING_DATE = "trialMetaData.accordedFilingDate"
    PETITION_FILING_DATE = "trialMetaData.petitionFilingDate"
    INSTITUTION_DECISION_DATE = "trialMetaData.institutionDecisionDate"
    TERMINATION_DATE = "trialMetaData.terminationDate"
    #: Latest decision DOCKETED in the proceeding, which includes a Federal
    #: Circuit order entered into the PTAB record. Not a final-written-decision
    #: date; there is no such field.
    LATEST_DECISION_DATE = "trialMetaData.latestDecisionDate"
    PANEL_CHAIR = "trialMetaData.panelChair"
    PANEL_MEMBERS = "trialMetaData.panelMembers"
    # REMOVED (verified live 2026-08-30): INSTITUTION_DATE
    # ("trialMetaData.institutionDate") and FINAL_DECISION_DATE
    # ("trialMetaData.finalDecisionDate") name fields the trial payload does
    # not carry; a range filter on either returned HTTP 404 for every window.

    # Petitioner data (regularPetitionerData.*) - CORRECTED
    PETITIONER_PARTY_NAME = "regularPetitionerData.realPartyInInterestName"
    PETITIONER_COUNSEL = "regularPetitionerData.counselName"

    # Patent owner data (patentOwnerData.*) - includes patent info
    PATENT_OWNER_NAME = "patentOwnerData.patentOwnerName"
    PATENT_OWNER_REAL_PARTY = "patentOwnerData.realPartyInInterestName"
    PATENT_OWNER_COUNSEL = "patentOwnerData.counselName"
    TECHNOLOGY_CENTER_NUMBER = "patentOwnerData.technologyCenterNumber"
    GROUP_ART_UNIT_NUMBER = "patentOwnerData.groupArtUnitNumber"

    # Patent/Application data (in patentOwnerData.*) - CORRECTED
    PATENT_NUMBER = "patentOwnerData.patentNumber"
    GRANT_DATE = "patentOwnerData.grantDate"
    APPLICATION_NUMBER_TEXT = "patentOwnerData.applicationNumberText"
    INVENTOR_NAME = "patentOwnerData.inventorName"

    # REMOVED (verified live 2026-07-02, re-confirmed 2026-08-30): the whole
    # decisionData.* block — DECISION_TYPE, DECISION_OUTCOME,
    # CLAIMS_CHALLENGED, CLAIMS_FOUND_UNPATENTABLE. A trial record carries
    # exactly five top-level bags (trialNumber, lastModifiedDateTime,
    # trialMetaData, regularPetitionerData, patentOwnerData); there is no
    # decisionData bag, so those constants were dead code that read like a
    # promise the API cannot keep.
    #
    # NO PTAB TIER CARRIES CLAIM-LEVEL OUTCOMES. Which claims were
    # challenged, instituted, cancelled, amended or upheld appears nowhere in
    # the trials search payload at any tier — minimal, balanced or complete.
    # trialStatusCategory says "Final Written Decision" and stops there. The
    # only source for claim-level results is the text of the decision itself:
    # PTAB_get_documents(document_category='FINAL') then
    # PTAB_get_document_content on that paper.

    # Document metadata
    DOCUMENT_IDENTIFIER = "documentIdentifier"
    DOCUMENT_CODE = "documentCode"
    DOCUMENT_CODE_DESCRIPTION = "documentCodeDescription"
    PAGE_COUNT = "pageCount"
    FILE_DOWNLOAD_URI = "fileDownloadURI"


class AppealFields:
    """Bare leaf labels for appeals. NOT the wire schema, and not usable as
    response field paths.

    These names predate the live probes and several of them (decisionDate,
    decisionOutcome, appellantName, examinerName, applicationNumber,
    claimsAffirmed) do not exist in the appeals payload under any nesting;
    copying one into a field set or a `fields` argument returns nothing.
    The verified paths live in config/filter_field_mapping.AppealFilterFields
    and in field_configs.yaml. Nothing in the request path reads this class.
    """

    # Core identifiers
    APPEAL_NUMBER = "appealNumber"
    APPLICATION_NUMBER = "applicationNumber"

    # Appeal metadata
    FILING_DATE = "filingDate"
    DECISION_DATE = "decisionDate"
    DECISION_TYPE = "decisionType"
    DECISION_OUTCOME = "decisionOutcome"

    # Appellant data
    APPELLANT_NAME = "appellantName"
    APPELLANT_COUNSEL = "appellantCounsel"

    # Technical data
    ART_UNIT = "artUnit"
    TECHNOLOGY_CENTER = "technologyCenter"
    EXAMINER_NAME = "examinerName"

    # Decision data
    CLAIMS_AFFIRMED = "claimsAffirmed"
    CLAIMS_REVERSED = "claimsReversed"
    CLAIMS_NEW_GROUNDS = "claimsNewGrounds"

    # Document metadata
    DOCUMENT_IDENTIFIER = "documentIdentifier"
    DOCUMENT_CODE = "documentCode"
    DOCUMENT_CODE_DESCRIPTION = "documentCodeDescription"
    PAGE_COUNT = "pageCount"
    FILE_DOWNLOAD_URI = "fileDownloadURI"


class InterferenceFields:
    """Bare leaf labels for interferences. NOT the wire schema, and not usable
    as response field paths.

    Same caveat as AppealFields: seniorParty/juniorParty/decisionDate/
    decisionType/decisionSummary do not exist in the interference payload.
    The parties are seniorPartyData.* and juniorPartyData.*, and the decision
    fields sit inside documentData. See
    config/filter_field_mapping.InterferenceFilterFields.
    """

    # Core identifiers
    INTERFERENCE_NUMBER = "interferenceNumber"

    # Interference metadata
    FILING_DATE = "filingDate"
    DECISION_DATE = "decisionDate"
    DECISION_TYPE = "decisionType"

    # Party data
    SENIOR_PARTY = "seniorParty"
    JUNIOR_PARTY = "juniorParty"

    # Decision data
    DECISION_SUMMARY = "decisionSummary"

    # Document metadata
    DOCUMENT_IDENTIFIER = "documentIdentifier"
    DOCUMENT_CODE = "documentCode"
    DOCUMENT_CODE_DESCRIPTION = "documentCodeDescription"
    PAGE_COUNT = "pageCount"
    FILE_DOWNLOAD_URI = "fileDownloadURI"


class QueryFieldNames:
    """Field names for query parameters (for building search queries) - CORRECTED"""

    # Trials
    TRIAL_NUMBER = "trialNumber"
    TRIAL_TYPE = "trialMetaData.trialTypeCode"
    PETITIONER_NAME = "regularPetitionerData.realPartyInInterestName"  # CORRECTED
    PATENT_OWNER_NAME = "patentOwnerData.patentOwnerName"
    PATENT_NUMBER = "patentOwnerData.patentNumber"  # CORRECTED

    # Appeals
    APPEAL_NUMBER = "appealNumber"
    APPLICATION_NUMBER = "applicationNumber"
    APPELLANT_NAME = "appellantName"

    # Interferences
    INTERFERENCE_NUMBER = "interferenceNumber"


# NOTE: Predefined field sets are now managed in field_configs.yaml
# The TrialFieldSets, AppealFieldSets, and InterferenceFieldSets classes
# have been removed. All field configuration is now done via the YAML file.
# This allows users to customize field sets without modifying code.
