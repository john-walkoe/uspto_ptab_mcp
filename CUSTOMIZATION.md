# Field Customization Guide

This document provides comprehensive guidance on customizing field sets for the USPTO PTAB MCP Server to optimize context usage and workflow efficiency.

## 🔧 Field Customization

### User-Configurable Field Sets

The MCP server supports user-customizable field sets through YAML configuration at the project root. You can modify field sets that the minimal and balanced searches bring back without changing any code!

**Configuration file:** `field_configs.yaml` (in project root)

### Easy Customization Process

1. **Open** `field_configs.yaml` in the project root directory
2. **Uncomment fields** you want by removing the `#` symbol
3. **Save the file** - changes take effect on next Claude Desktop restart
4. **Use the simplified tools** with your custom field selections

### Available Field Sets (Progressive Workflow)

**Trials (IPR, PGR, CBM):**
- **`trials_minimal`** - Ultra-minimal for trial discovery: **12 essential fields** for high-volume screening (50-100 results)
- **`trials_balanced`** - Comprehensive trial analysis: **30-50 fields** for detailed trial examination
- **`trials_complete`** - Complete trial data: **All fields** for exhaustive analysis

**Appeals (Ex Parte):**
- **`appeals_minimal`** - Ultra-minimal for appeal discovery: **9 essential fields** for appeal screening
- **`appeals_balanced`** - Comprehensive appeal analysis: **25-40 fields** for detailed appeal examination
- **`appeals_complete`** - Complete appeal data: **All fields** for exhaustive analysis

**Interferences:**
- **`interferences_minimal`** - Ultra-minimal for interference discovery: **6 essential fields** for interference screening
- **`interferences_balanced`** - Comprehensive interference analysis: **20-30 fields** for detailed interference examination
- **`interferences_complete`** - Complete interference data: **All fields** for exhaustive analysis

### Professional Field Categories Available

The `field_configs.yaml` file contains comprehensive PTAB proceeding fields organized into the following categories:

#### Trials Field Categories

**Core Identifiers**
- `trialNumber` - Trial number (IPR2024-01353, PGR2025-00009, CBM2020-00029)
- `trialMetaData.accordedFilingDate` - Trial filing date
- `trialMetaData.trialTypeCode` - Trial type (IPR, PGR, CBM)

**Party Information**
- `regularPetitionerData.realPartyInInterestName` - Petitioner name
- `regularPetitionerData.counselName` - Petitioner counsel
- `patentOwnerData.patentOwnerName` - Patent owner name
- `patentOwnerData.realPartyInInterestName` - Patent owner real party in interest
- `patentOwnerData.counselName` - Patent owner counsel

**Patent Data**
- `patentOwnerData.patentNumber` - Challenged patent number
- `patentOwnerData.applicationNumberText` - Application number (cross-reference to PFW)
- `patentOwnerData.grantDate` - Patent grant date
- `patentOwnerData.inventorName` - Inventor name

**Technology Classification**
- `patentOwnerData.technologyCenterNumber` - Technology center
- `patentOwnerData.groupArtUnitNumber` - Art unit number (cross-reference to all MCPs)

**Status and Dates**
- `trialMetaData.trialStatusCategory` - Trial status (Active, Terminated, Settled)
- `trialMetaData.institutionDecisionDate` - Institution decision date
- `trialMetaData.terminationDate` - Final decision date
- `trialMetaData.petitionFilingDate` - Petition filing date
- `trialMetaData.trialLastModifiedDate` - Last modified date

**Advanced Fields**
- `trialMetaData.fileDownloadURI` - Document download URI
- `documentBag` - **WARNING: Can cause 100x token increase - use `PTAB_get_documents` tool instead**

#### Appeals Field Categories

Verified live 2026-09-02 over 50 appeal decision records. Presence counts are
given where a field is not on every record. An appeal record has exactly these
bags: `appealNumber`, `appealDocumentCategory`, `lastModifiedDateTime`,
`appealMetaData`, `appellantData`, `documentData`, `decisionData`,
`requestorData`.

**Core Identifiers**
- `appealNumber` - Appeal number
- `appellantData.applicationNumberText` - Application number (cross-reference to PFW)
- `documentData.documentFilingDate` - Filing date
- `decisionData.decisionIssueDate` - Decision date

**Decision Information**
- `decisionData.decisionTypeCategory` - Decision type
- `decisionData.appealOutcomeCategory` - Outcome (Affirmed, Reversed, Affirmed-in-Part)
- `decisionData.issueTypeBag` - Statutory issues decided, e.g. `["102","103"]`
- `decisionData.statuteAndRuleBag` - e.g. `["35 USC 134"]`

**Appellant Data**
- `appellantData.realPartyInInterestName` - Appellant name
- `appellantData.patentOwnerName` - Patent owner name (48/50)
- `appellantData.inventorName` - Inventor name
- `appellantData.counselName` - Appellant attorney/counsel
- `appellantData.technologyCenterNumber` - Technology center
- `appellantData.groupArtUnitNumber` - Art unit number
- `appellantData.patentNumber` - Patent number, reexam appeals (16/50)
- `appellantData.publicationNumber` / `appellantData.publicationDate` (32/50)

**Appeal Metadata**
- `appealMetaData.appealFilingDate` - Appeal filing date
- `appealMetaData.applicationTypeCategory` - UTILITY, REEXAM, etc.
- `appealMetaData.appealLastModifiedDate`
- `appealMetaData.fileDownloadURI` - Whole-appeal zip URI

**Document Metadata**
- `documentData.documentIdentifier` - Document ID for `PTAB_get_document_content`
- `documentData.documentName`, `documentData.documentTypeDescriptionText`,
  `documentData.documentSizeQuantity`, `documentData.fileDownloadURI`
- `documentData.documentOCRText` - about 500 chars of decision text per record

**Third-Party Requester**
- `requestorData.thirdPartyName` - Reexam requester (1/50)

**Not available in the appeals payload at any tier.** These names appeared in
earlier versions of this document and of `field_configs.yaml`; the API has
never sent them, and a field set naming one returns nothing for it:
`applicationNumber` (root level), `documentData.decisionDate`,
`documentData.decisionOutcome`, `documentData.decisionTypeCodeDescription`,
`documentData.boardDecisionIndicator`, `appellantData.appellantName`,
`appellantData.appellantAddress`, `appellantData.appellantCounsel`,
`appellantData.appellantType`, the whole `examinerData` bag (so no examiner
name), the whole `applicationData` bag (so no invention title or
classification), and any claim-level breakdown
(`decisionData.claimsAffirmed`, `claimsReversed`, `decisionSummary`). Which
claims were affirmed or reversed is only in the decision text: use
`PTAB_get_documents` then `PTAB_get_document_content`.

#### Interferences Field Categories

Verified live 2026-09-02 over 50 interference decision records. An
interference record has exactly these bags: `interferenceNumber`,
`lastModifiedDateTime`, `interferenceMetaData`, `seniorPartyData` (48/50),
`juniorPartyData` (44/50), `additionalPartyDataBag` (12/50), `documentData`.

**Core Identifiers**
- `interferenceNumber` - Interference number
- `interferenceMetaData.interferenceStyleName` - "SENIOR v. JUNIOR" caption (50/50)
- `documentData.documentFilingDate` - Filing date
- `documentData.decisionIssueDate` - Decision date
- `interferenceMetaData.declarationDate` - Declaration date (48/50)

**Party Information**

Senior and junior are separate bags carrying the SAME field names, not a
suffix on one bag.
- `seniorPartyData.realPartyInInterestName` / `juniorPartyData.realPartyInInterestName`
- `seniorPartyData.patentOwnerName` (42/50) / `juniorPartyData.patentOwnerName` (40/50)
- `seniorPartyData.inventorName` / `juniorPartyData.inventorName`
- `seniorPartyData.counselName` / `juniorPartyData.counselName` (27/50 each)
- `seniorPartyData.technologyCenterNumber` / `.groupArtUnitNumber` (and the junior equivalents)
- `additionalPartyDataBag` - extra parties beyond the two principals (12/50)

**Decision Information**

The decision fields sit INSIDE `documentData`; there is no `decisionData` bag.
- `documentData.interferenceOutcomeCategory` - Outcome (Judgment, etc.)
- `documentData.decisionTypeCategory` - Decision type, read "Decision" on all 50 probed records
- `documentData.documentTitleText` - e.g. "Judgment 37 C.F.R. § 41.127(a)"
- `documentData.statuteAndRuleBag` (35/50), `documentData.issueTypeBag` (6/50)

**Patent Data**
- `seniorPartyData.patentNumber` (33/50) / `juniorPartyData.patentNumber` (30/50)
- `seniorPartyData.applicationNumberText` / `juniorPartyData.applicationNumberText`
- `seniorPartyData.publicationNumber`, `.publicationDate`, `.grantDate` (and the junior equivalents)

**Not available in the interference payload at any tier.** The entire
`partyData` bag (`partyData.seniorParty`, `partyData.juniorParty`,
`partyData.seniorPartyPatentNumber`, `partyData.juniorPartyCounsel` and the
rest), the entire `decisionData` bag (`decisionData.priority`,
`claimsInInterference`, `decisionSummary`), `documentData.decisionDate`,
`documentData.decisionType`, `documentData.decisionOutcome` and
`patentData.inventionTitle`. There is no invention title anywhere in the
payload and no per-count priority breakdown; which count each party won is
only in the judgment text.

### Example Customization

**File: `field_configs.yaml`**

```yaml
predefined_sets:
  trials_minimal:
    description: "Essential fields for trial discovery (95-99% context reduction)"
    fields:
      # === CROSS-MCP INTEGRATION FIELDS ===
      - trialNumber                                    # Trial number (IPR2024-01353)
      - patentOwnerData.applicationNumberText          # → Patent File Wrapper MCP
      - patentOwnerData.patentNumber                   # → PTAB challenges
      - patentOwnerData.groupArtUnitNumber            # → All USPTO MCPs

      # === TRIAL CORE FIELDS ===
      - trialMetaData.accordedFilingDate              # Filing date
      - trialMetaData.trialTypeCode                   # IPR, PGR, CBM
      - trialMetaData.trialStatusCategory             # Status
      - regularPetitionerData.realPartyInInterestName # Petitioner
      - patentOwnerData.patentOwnerName               # Patent owner
      - trialMetaData.institutionDecisionDate         # Institution date
      - trialMetaData.terminationDate                 # Final decision date
      - regularPetitionerData.counselName             # Petitioner counsel

  appeals_minimal:
    description: "Essential fields for appeal discovery (95-99% context reduction)"
    fields:
      # === CORE IDENTIFIERS ===
      - appealNumber                             # Appeal number
      - appellantData.applicationNumberText      # Application number
      - documentData.documentFilingDate          # Filing date
      - decisionData.decisionIssueDate           # Decision date

      # === DECISION INFORMATION ===
      - decisionData.decisionTypeCategory        # Decision type
      - decisionData.appealOutcomeCategory       # Outcome
      - appellantData.technologyCenterNumber     # Technology center
      - appellantData.groupArtUnitNumber         # Art unit
      - appellantData.realPartyInInterestName    # Appellant name
```

### Context Reduction Strategies

#### Token Efficiency by Field Set

| Data Type | Field Set | Field Count | Token Usage (50 results) | Reduction | Use Case |
|-----------|-----------|------------|--------------------------|-----------|----------|
| **Trials** | Minimal | 12 | ~20KB | 95-99% | Discovery, user selection |
| **Trials** | Balanced | 30-50 | ~60KB | 85-95% | Detailed analysis, cross-MCP |
| **Trials** | Complete | All | ~120KB | 80-90% | Exhaustive research |
| **Appeals** | Minimal | 9 | ~15KB | 95-99% | Discovery, screening |
| **Appeals** | Balanced | 25-40 | ~50KB | 85-95% | Detailed analysis |
| **Appeals** | Complete | All | ~100KB | 80-90% | Exhaustive research |
| **Interferences** | Minimal | 8 | ~10KB | 95-99% | Discovery, screening |
| **Interferences** | Balanced | 20-30 | ~40KB | 85-95% | Detailed analysis |
| **Interferences** | Complete | All | ~80KB | 80-90% | Exhaustive research |

### Best Practices for Field Customization

#### Progressive Workflow Design

1. **Start Minimal**: Use 6-12 field preset for discovery (95-99% reduction)
2. **User Selection**: Present results for user/attorney to choose promising proceedings
3. **Targeted Analysis**: Use balanced preset or complete tier for detailed analysis
4. **Document Extraction**: Use targeted document tools only when needed

#### Token Budget Management

**High-Volume Workflows (100+ results)**:
- Use minimal field sets (6-12 fields)
- Extract only essential fields for initial filtering
- Progress to detailed analysis only for selected results

**Analysis Workflows (10-20 results)**:
- Use preset minimal or balanced configurations
- Include classification and party fields for pattern analysis
- Add counsel and decision fields for outcome analysis

**Cross-MCP Integration**:
- Use balanced preset to include cross-reference fields
- Include `patentOwnerData.applicationNumberText` for PFW integration
- Include `patentOwnerData.groupArtUnitNumber` for art unit matching
- Add `patentOwnerData.patentNumber` for Citations integration

#### Common Field Selection Patterns

**PTAB Challenge History**:
```yaml
fields: ['trialNumber', 'patentOwnerData.patentNumber', 'trialMetaData.trialTypeCode', 'trialMetaData.trialStatusCategory']
# Purpose: Track IPR/PGR/CBM challenges for specific patents
```

**Technology Area Analysis**:
```yaml
fields: ['trialNumber', 'patentOwnerData.technologyCenterNumber', 'patentOwnerData.groupArtUnitNumber', 'regularPetitionerData.realPartyInInterestName', 'trialMetaData.institutionDecisionDate']
# Purpose: Analyze PTAB activity by technology area
```

**Petitioner Portfolio Research**:
```yaml
fields: ['trialNumber', 'regularPetitionerData.realPartyInInterestName', 'patentOwnerData.patentNumber', 'trialMetaData.trialStatusCategory', 'trialMetaData.terminationDate']
# Purpose: Track petitioner success rates and patterns
```

**Appeal Reversal Analysis**:
```yaml
fields: ['appealNumber', 'appellantData.applicationNumberText', 'decisionData.appealOutcomeCategory', 'appellantData.groupArtUnitNumber', 'appellantData.technologyCenterNumber']
# Purpose: Analyze reversal patterns at PTAB by art unit and technology center.
# The examiner's NAME is not in the appeals payload; art unit is the closest
# available proxy. For the examiner, take appellantData.applicationNumberText
# across to PFW_search_applications_minimal.
```

**Cross-MCP Lifecycle Tracking**:
```yaml
fields: ['trialNumber', 'patentOwnerData.applicationNumberText', 'patentOwnerData.patentNumber', 'patentOwnerData.groupArtUnitNumber', 'trialMetaData.trialStatusCategory', 'regularPetitionerData.realPartyInInterestName']
# Purpose: Complete patent lifecycle from prosecution (PFW) through challenges (PTAB)
```

### Field Configuration Validation

#### Testing Your Configuration

After modifying `field_configs.yaml`:

1. **Restart Claude Desktop** - Changes only take effect after restart
2. **Test minimal search** - Run a small test search to verify fields
3. **Check token usage** - Monitor context consumption in your workflows

#### Common Configuration Issues

**Missing Required Fields**:
- Always include trial/appeal/interference number field (required for all workflows)
- Include descriptive fields for user-readable results (party names, decision outcomes)

**Token Explosion**:
- Never include `documentBag` in field configurations
- Use `PTAB_get_documents` tool for targeted document access instead

**Cross-MCP Integration Issues**:
- Include `patentOwnerData.applicationNumberText` for PFW cross-reference
- Include `patentOwnerData.groupArtUnitNumber` for art unit analysis
- Include `appellantData.applicationNumberText` in appeals for PFW integration

**Paths that do not exist**:
- A configured path the API never sends is dropped by the field filter and
  the response reports it under `fields_absent`. That is the first thing to
  check when a field set looks narrower than configured: compare the paths
  against the verified lists above rather than against intuition.
- A wildcard whose prefix does not exist expands to nothing and is silent.
  `examinerData.*` (appeals) and `partyData.*` (interferences) both did this.

#### Field Performance Notes

**Fast Fields** (minimal processing overhead):
- `trialNumber`, `appealNumber`, `interferenceNumber`
- `patentOwnerData.patentNumber`, `appellantData.applicationNumberText`
- `trialMetaData.trialTypeCode`, `trialMetaData.trialStatusCategory`
- `decisionData.appealOutcomeCategory`

**Medium Fields** (moderate processing):
- `regularPetitionerData.*`, `patentOwnerData.*`
- `appellantData.*`, `seniorPartyData.*`, `juniorPartyData.*`
- `decisionData.*` (appeals only)

**Expensive Fields** (heavy processing - use sparingly):
- `documentBag` (NEVER use - 100x token explosion - use `PTAB_get_documents` instead)

### Advanced Customization

#### Creating Custom Field Sets

You can create entirely new field sets beyond the default minimal/balanced/complete:

```yaml
predefined_sets:
  trials_litigation_research:
    description: "Litigation research field set (90% reduction)"
    fields:
      - trialNumber
      - patentOwnerData.patentNumber
      - patentOwnerData.applicationNumberText
      - regularPetitionerData.realPartyInInterestName
      - regularPetitionerData.counselName
      - patentOwnerData.patentOwnerName
      - patentOwnerData.counselName
      - trialMetaData.trialTypeCode
      - trialMetaData.trialStatusCategory
      - trialMetaData.institutionDecisionDate
      - trialMetaData.terminationDate

  appeals_art_unit_quality:
    description: "Art unit reversal analysis (90% reduction)"
    fields:
      - appealNumber
      - appellantData.applicationNumberText
      - appellantData.groupArtUnitNumber
      - appellantData.technologyCenterNumber
      - decisionData.appealOutcomeCategory
      - decisionData.issueTypeBag
      - decisionData.decisionIssueDate

  interferences_priority_disputes:
    description: "Priority dispute analysis (90% reduction)"
    fields:
      - interferenceNumber
      - interferenceMetaData.interferenceStyleName
      - seniorPartyData.realPartyInInterestName
      - juniorPartyData.realPartyInInterestName
      - seniorPartyData.patentNumber
      - juniorPartyData.patentNumber
      - documentData.interferenceOutcomeCategory
      - documentData.decisionIssueDate
```

#### Wildcard Patterns

For efficiency, use wildcard patterns to include all fields from a category:

```yaml
# Include all trial metadata fields
fields:
  - trialMetaData.*

# Include all petitioner data
fields:
  - regularPetitionerData.*

# Include all patent owner data
fields:
  - patentOwnerData.*

# Include all fields (complete tier)
fields:
  - "*"
```

### Troubleshooting Field Configuration

#### Common Error Messages

**"Field not found in mapping"**:
- Check spelling of field names in your YAML file
- Verify field exists in USPTO PTAB API schema
- Use full API path if abbreviated mapping doesn't exist

**"Empty results with custom fields"**:
- Ensure trial/appeal/interference number field is always included
- Check that your search criteria are valid
- Test with default fields first, then add custom fields

**"High token usage despite minimal configuration"**:
- Remove `documentBag` from your field list immediately
- Limit results with appropriate `limit` parameter
- Use ultra-minimal mode for discovery workflows

#### Performance Validation

To validate your configuration efficiency:

```bash
# Test your custom configuration
uv run python tests/test_basic.py

# Check for field configuration loading
uv run python -c "from ptab_mcp.config.field_manager import FieldManager; fm = FieldManager('field_configs.yaml'); print(fm.get_fields('trials_minimal'))"
```

#### Field Availability Reference

**Always Available**:
- Proceeding identifiers: `trialNumber`, `appealNumber`, `interferenceNumber`
- Application numbers: `patentOwnerData.applicationNumberText` (trials),
  `appellantData.applicationNumberText` (appeals),
  `seniorPartyData.applicationNumberText` (interferences)
- Party names: `regularPetitionerData.realPartyInInterestName` and
  `patentOwnerData.realPartyInInterestName` (trials),
  `appellantData.realPartyInInterestName` (appeals),
  `seniorPartyData.realPartyInInterestName` and
  `juniorPartyData.realPartyInInterestName` (interferences)

**Proceeding-Dependent**:
- `trialMetaData.institutionDecisionDate` (only if institution occurred)
- `trialMetaData.terminationDate` (only if proceeding terminated)
- `decisionData.*` (appeals only, and only if a decision issued)
- `seniorPartyData` / `juniorPartyData` (present on 48/50 and 44/50
  interference records; a missing bag is why
  `interferenceMetaData.interferenceStyleName` is in the minimal set)

**Document-Dependent**:
- `documentBag` (only if documents exist - **NEVER USE** - use `PTAB_get_documents` instead)

### Cross-MCP Field Mapping

When integrating PTAB with other USPTO MCPs, use these field mappings:

| PTAB Field | PFW Field | Purpose |
|------------|-----------|---------|
| `patentOwnerData.applicationNumberText` | `applicationNumberText` | Link trial to prosecution history |
| `patentOwnerData.patentNumber` | `applicationMetaData.patentNumber` | Link patent to file wrapper |
| `patentOwnerData.groupArtUnitNumber` | `applicationMetaData.groupArtUnitNumber` | Art unit matching |
| `appellantData.applicationNumberText` (appeals) | `applicationNumberText` | Link appeal to prosecution |
| `seniorPartyData.applicationNumberText` (interferences) | `applicationNumberText` | Link interference to prosecution |

| PTAB Field | FPD Field | Purpose |
|------------|-----------|---------|
| `patentOwnerData.applicationNumberText` | `applicationNumber` | Link trial to petition history |
| `patentOwnerData.groupArtUnitNumber` | `groupArtUnit` | Art unit correlation |

| PTAB Field | Citations Field | Purpose |
|------------|-----------------|---------|
| `patentOwnerData.patentNumber` | `patentNumber` | Citation quality analysis |
| `patentOwnerData.groupArtUnitNumber` | `artUnit` | Examiner citation patterns |

This comprehensive field customization system allows you to optimize the PTAB MCP server for your specific PTAB research workflows while maintaining the flexibility to adjust as your needs evolve.
