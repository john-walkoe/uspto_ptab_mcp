"""
Filter Field Mappings - Centralized field name constants for USPTO API filters.

Provides type-safe, autocomplete-friendly field name constants for building
filters in search operations. Single source of truth for API field names.

Benefits:
- IDE autocomplete support
- Type safety (typos caught at development time)
- Easy to update if API field names change
- Documentation of available filter fields in one place
"""


class TrialFilterFields:
    """
    Field name mappings for PTAB trial proceeding searches.

    Used by search_trials_minimal, search_trials_balanced, and search_trials_complete.
    Maps intuitive constant names to exact USPTO API field names.
    """

    # Core Trial Identifiers
    TRIAL_NUMBER = "trialNumber"

    # Patent Owner Data
    PATENT_NUMBER = "patentOwnerData.patentNumber"
    PATENT_OWNER_NAME = "patentOwnerData.patentOwnerName"
    PATENT_OWNER_COUNSEL = "patentOwnerData.patentOwnerCounsel"

    # Petitioner Data
    PETITIONER_NAME = "regularPetitionerData.realPartyInInterestName"
    PETITIONER_COUNSEL = "petitionerData.petitionerCounsel"

    # Trial Metadata
    TRIAL_TYPE = "trialMetaData.trialTypeCode"  # IPR, PGR, CBM, DER
    TRIAL_STATUS = "trialMetaData.trialStatusCategory"
    FILING_DATE = "trialMetaData.accordedFilingDate"  # Range filter
    INSTITUTION_DATE = "trialMetaData.institutionDate"  # Range filter
    FINAL_DECISION_DATE = "trialMetaData.finalDecisionDate"  # Range filter

    # Respondent/USPTO Data
    TECH_CENTER = "respondentData.technologyCenterNumber"
    EXAMINER_NAME = "respondentData.examinerName"
    ART_UNIT = "respondentData.artUnit"
    ASSIGNEE_NAME = "respondentData.assigneeName"

    # Decision Data
    DECISION_OUTCOME = "decisionData.decisionOutcome"


class AppealFilterFields:
    """
    Field name mappings for PTAB ex parte appeal searches.

    Used by search_appeals_minimal, search_appeals_balanced, and search_appeals_complete.

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

    Used by search_interferences_minimal, search_interferences_balanced, and search_interferences_complete.

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


# Export all field mapping classes
__all__ = ['TrialFilterFields', 'AppealFilterFields', 'InterferenceFilterFields']
