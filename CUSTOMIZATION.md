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
- `trialNumber` - Trial number (IPR2024-00123, PGR2024-00045, CBM2023-00001)
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
- `documentBag` - **WARNING: Can cause 100x token increase - use `ptab_get_documents` tool instead**

#### Appeals Field Categories

**Core Identifiers**
- `appealNumber` - Appeal number
- `applicationNumber` - Application number (cross-reference to PFW)
- `documentData.documentFilingDate` - Filing date
- `documentData.decisionDate` - Decision date

**Decision Information**
- `documentData.decisionTypeCodeDescription` - Decision type (Ex Parte, Remand, etc.)
- `documentData.decisionOutcome` - Outcome (Affirmed, Reversed, Reversed-in-Part)
- `documentData.boardDecisionIndicator` - Board decision indicator (Y/N)

**Appellant Data**
- `appellantData.appellantName` - Appellant name
- `appellantData.technologyCenterNumber` - Technology center
- `appellantData.groupArtUnitNumber` - Art unit number
- `appellantData.appellantAddress` - Appellant address
- `appellantData.appellantCounsel` - Appellant attorney/counsel
- `appellantData.appellantType` - Appellant type

**Examiner Information**
- `examinerData.primaryExaminerName` - Primary examiner
- `examinerData.assistantExaminerName` - Assistant examiner
- `examinerData.examinerArtUnit` - Examiner art unit

**Decision Details**
- `decisionData.claimsAppealed` - Claims appealed
- `decisionData.claimsAffirmed` - Claims affirmed
- `decisionData.claimsReversed` - Claims reversed
- `decisionData.claimsReversedInPart` - Claims reversed in part
- `decisionData.decisionSummary` - Decision summary

**Patent/Application Data**
- `applicationData.inventionTitle` - Invention title
- `applicationData.filingDate` - Application filing date
- `applicationData.patentNumber` - Patent number (if granted)
- `applicationData.uspcClassification` - US Patent Classification
- `applicationData.cpcClassification` - Cooperative Patent Classification

#### Interferences Field Categories

**Core Identifiers**
- `interferenceNumber` - Interference number
- `documentData.documentFilingDate` - Filing date
- `documentData.decisionDate` - Decision date

**Party Information**
- `partyData.seniorParty` - Senior party name
- `partyData.juniorParty` - Junior party name
- `partyData.seniorPartyAddress` - Senior party address
- `partyData.seniorPartyCounsel` - Senior party counsel
- `partyData.juniorPartyAddress` - Junior party address
- `partyData.juniorPartyCounsel` - Junior party counsel

**Decision Information**
- `documentData.decisionType` - Decision type
- `documentData.decisionOutcome` - Decision outcome

**Patent Data**
- `partyData.seniorPartyPatentNumber` - Senior party patent number
- `partyData.seniorPartyApplicationNumber` - Senior party application number
- `partyData.juniorPartyPatentNumber` - Junior party patent number
- `partyData.juniorPartyApplicationNumber` - Junior party application number
- `patentData.inventionTitle` - Invention title

**Decision Details**
- `decisionData.priority` - Priority determination
- `decisionData.claimsInInterference` - Claims in interference
- `decisionData.decisionSummary` - Decision summary

### Example Customization

**File: `field_configs.yaml`**

```yaml
predefined_sets:
  trials_minimal:
    description: "Essential fields for trial discovery (95-99% context reduction)"
    fields:
      # === CROSS-MCP INTEGRATION FIELDS ===
      - trialNumber                                    # Trial number (IPR2024-00123)
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
      - applicationNumber                        # Application number
      - documentData.documentFilingDate          # Filing date
      - documentData.decisionDate                # Decision date

      # === DECISION INFORMATION ===
      - documentData.decisionTypeCodeDescription # Decision type
      - documentData.decisionOutcome             # Outcome
      - appellantData.technologyCenterNumber     # Technology center
      - appellantData.groupArtUnitNumber         # Art unit
      - appellantData.appellantName              # Appellant name
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
| **Interferences** | Minimal | 6 | ~10KB | 95-99% | Discovery, screening |
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
fields: ['appealNumber', 'applicationNumber', 'documentData.decisionOutcome', 'appellantData.groupArtUnitNumber', 'examinerData.primaryExaminerName']
# Purpose: Analyze examiner reversal patterns at PTAB
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
- Use `ptab_get_documents` tool for targeted document access instead

**Cross-MCP Integration Issues**:
- Include `patentOwnerData.applicationNumberText` for PFW cross-reference
- Include `patentOwnerData.groupArtUnitNumber` for art unit analysis
- Include `applicationNumber` in appeals for PFW integration

#### Field Performance Notes

**Fast Fields** (minimal processing overhead):
- `trialNumber`, `appealNumber`, `interferenceNumber`
- `patentOwnerData.patentNumber`, `applicationNumber`
- `trialMetaData.trialTypeCode`, `trialMetaData.trialStatusCategory`
- `documentData.decisionOutcome`

**Medium Fields** (moderate processing):
- `regularPetitionerData.*`, `patentOwnerData.*`
- `appellantData.*`, `partyData.*`
- `decisionData.*`

**Expensive Fields** (heavy processing - use sparingly):
- `documentBag` (NEVER use - 100x token explosion - use `ptab_get_documents` instead)

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

  appeals_examiner_quality:
    description: "Examiner quality analysis (90% reduction)"
    fields:
      - appealNumber
      - applicationNumber
      - examinerData.primaryExaminerName
      - appellantData.groupArtUnitNumber
      - appellantData.technologyCenterNumber
      - documentData.decisionOutcome
      - decisionData.claimsAffirmed
      - decisionData.claimsReversed
      - documentData.decisionDate

  interferences_priority_disputes:
    description: "Priority dispute analysis (90% reduction)"
    fields:
      - interferenceNumber
      - partyData.seniorParty
      - partyData.juniorParty
      - partyData.seniorPartyPatentNumber
      - partyData.juniorPartyPatentNumber
      - documentData.decisionOutcome
      - decisionData.priority
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
- Trial identifiers: `trialNumber`, `appealNumber`, `interferenceNumber`
- Patent numbers: `patentOwnerData.patentNumber`, `applicationNumber`
- Party names: `regularPetitionerData.realPartyInInterestName`, `appellantData.appellantName`

**Proceeding-Dependent**:
- `trialMetaData.institutionDecisionDate` (only if institution occurred)
- `trialMetaData.terminationDate` (only if proceeding terminated)
- `decisionData.*` (only if decision issued)

**Document-Dependent**:
- `documentBag` (only if documents exist - **NEVER USE** - use `ptab_get_documents` instead)

### Cross-MCP Field Mapping

When integrating PTAB with other USPTO MCPs, use these field mappings:

| PTAB Field | PFW Field | Purpose |
|------------|-----------|---------|
| `patentOwnerData.applicationNumberText` | `applicationNumberText` | Link trial to prosecution history |
| `patentOwnerData.patentNumber` | `applicationMetaData.patentNumber` | Link patent to file wrapper |
| `patentOwnerData.groupArtUnitNumber` | `applicationMetaData.groupArtUnitNumber` | Art unit matching |
| `applicationNumber` (appeals) | `applicationNumberText` | Link appeal to prosecution |

| PTAB Field | FPD Field | Purpose |
|------------|-----------|---------|
| `patentOwnerData.applicationNumberText` | `applicationNumber` | Link trial to petition history |
| `patentOwnerData.groupArtUnitNumber` | `groupArtUnit` | Art unit correlation |

| PTAB Field | Citations Field | Purpose |
|------------|-----------------|---------|
| `patentOwnerData.patentNumber` | `patentNumber` | Citation quality analysis |
| `patentOwnerData.groupArtUnitNumber` | `artUnit` | Examiner citation patterns |

This comprehensive field customization system allows you to optimize the PTAB MCP server for your specific PTAB research workflows while maintaining the flexibility to adjust as your needs evolve.
