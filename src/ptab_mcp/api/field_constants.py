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
    INSTITUTION_DATE = "trialMetaData.institutionDate"
    INSTITUTION_DECISION_DATE = "trialMetaData.institutionDecisionDate"
    FINAL_DECISION_DATE = "trialMetaData.finalDecisionDate"
    PANEL_CHAIR = "trialMetaData.panelChair"
    PANEL_MEMBERS = "trialMetaData.panelMembers"

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

    # Decision data (decisionData.*)
    DECISION_TYPE = "decisionData.decisionType"
    DECISION_OUTCOME = "decisionData.decisionOutcome"
    CLAIMS_CHALLENGED = "decisionData.claimsChallenged"
    CLAIMS_FOUND_UNPATENTABLE = "decisionData.claimsFoundUnpatentable"

    # Document metadata
    DOCUMENT_IDENTIFIER = "documentIdentifier"
    DOCUMENT_CODE = "documentCode"
    DOCUMENT_CODE_DESCRIPTION = "documentCodeDescription"
    PAGE_COUNT = "pageCount"
    FILE_DOWNLOAD_URI = "fileDownloadURI"


class AppealFields:
    """Field names for PTAB Appeals API (ex parte appeals)"""

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
    """Field names for PTAB Interferences API"""

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
