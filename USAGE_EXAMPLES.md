# Usage Examples & Integration Workflows

This document provides a comprehensive set of examples for using the Patent Trial and Appeal Board (PTAB) MCP, including basic searches, advanced filtering, cross-MCP integration workflows, and progressive disclosure patterns.

## Notes on PTAB MCP Usage

For the most part the LLMs will perform these searches and workflows on their own with minimal guidance from the user. These examples are illustrative to give insight on what the LLMs are doing in the background.

**Best Practice Recommendation:** For complex workflows or when you're unsure about the best approach, start by asking the LLM to use the `PTAB_get_guidance` tool first. This tool provides context-efficient workflow recommendations and helps the LLM choose the most appropriate tools and strategies for your specific use case.

### Sample User Requests by Example

**Example 1 - Basic Trial Searches:**
- "Find all IPR proceedings for Apple Inc filed in 2024"
- "Show me trials involving patent 10701173"
- "Search for IPR proceedings in technology center 2600"
- "Find all granted IPR trials filed by Samsung"

**Example 2 - Progressive Disclosure Workflow:**
- "Research PTAB challenges to Apple's semiconductor patents"
- "Analyze institution rates for wireless technology IPRs"
- "Find precedents for claim construction in software patents"

**Example 3 - Document Retrieval:**
- "Get all documents for trial IPR2024-01353"
- "Download the Final Written Decision for this IPR"
- "Extract text from the Institution Decision"

**Example 4 - Trial Outcome Analysis:**
- "Analyze institution rates in Art Unit 2600"
- "Show success rates for petitioner Apple Inc."
- "Compare outcomes across trial types (IPR vs PGR)"

**Example 5 - Cross-MCP Integration (with PFW):**
- "Research IPR2024-01353 and compare to original prosecution"
- "Analyze patent 10701173's prosecution and PTAB history"
- "Check for IPR challenges on Company XYZ's portfolio"

**Example 6 - Cross-MCP Integration (with PFW + FPD):**
- "Complete due diligence on patent 10701173 - prosecution, petitions, and PTAB"
- "Analyze portfolio risk for Company XYZ across all USPTO databases"

---

## Table of Contents
1. [Basic Trial Searches](#example-1-basic-trial-searches)
2. [Progressive Disclosure Workflow](#example-2-progressive-disclosure-workflow)
3. [Document Retrieval and Downloads](#example-3-document-retrieval-and-downloads)
4. [Trial Outcome Analysis](#example-4-trial-outcome-analysis)
5. [Precedent Research](#example-5-precedent-research)
6. [Cross-MCP Integration: PFW](#example-6-cross-mcp-integration-with-pfw)
7. [Cross-MCP Integration: PFW + FPD](#example-7-cross-mcp-integration-with-pfw-fpd)
8. [Cross-MCP Integration: Complete Lifecycle](#example-8-complete-lifecycle-tracking)
9. [Known Trials for Testing](#known-trials-for-testing)
10. [Full Tool Reference](#full-tool-reference)

---

## Example 1: Basic Trial Searches

The PTAB MCP provides three tiers of search tools for progressive disclosure. **It is highly recommended to use the `_minimal` search tier for discovery to save tokens (95-99% context reduction).**

### Available Search Parameters

All search tools (`PTAB_search_trials_minimal/balanced/complete`) support these parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `trial_number` | PTAB trial number | `'IPR2024-01353'` |
| `patent_number` | Patent number | `'10701173'` |
| `petitioner_name` | Petitioner party name | `'Apple Inc'` |
| `patent_owner_name` | Patent owner name | `'Samsung Electronics'` |
| `trial_type` | Trial type code | `'IPR'`, `'PGR'`, `'CBM'` |
| `trial_status` | Trial status category | `'Institution Granted'`, `'Final Written Decision'` |
| `tech_center` | Technology center | `'2600'`, `'3600'` |
| `filing_date_from` | Filing date range start | `'2024-01-01'` |
| `filing_date_to` | Filing date range end | `'2024-12-31'` |
| `limit` | Max results | `50` (default), `100` (max) |

### Search by Patent Number

```python
# Find all PTAB proceedings for a specific patent (minimal tier - efficient)
PTAB_search_trials_minimal(
    patent_number='10701173',
    limit=50
)

# Get detailed information (balanced tier - if needed after discovery)
PTAB_search_trials_balanced(
    patent_number='10701173',
    limit=10
)
```

### Search by Party Name

```python
# Find all IPR proceedings filed by Apple Inc in 2024
PTAB_search_trials_minimal(
    petitioner_name='Apple Inc',
    trial_type='IPR',
    filing_date_from='2024-01-01',
    filing_date_to='2024-12-31',
    limit=50
)

# Find all trials where Samsung is the patent owner
PTAB_search_trials_minimal(
    patent_owner_name='Samsung Electronics',
    limit=50
)
```

### Search by Technology Area

```python
# Find all IPR proceedings in wireless communications (TC 2600)
PTAB_search_trials_minimal(
    tech_center='2600',
    trial_type='IPR',
    limit=50
)

# Find granted institutions in semiconductor technology
PTAB_search_trials_minimal(
    tech_center='2800',
    trial_status='Institution Granted',
    limit=50
)
```

### Search by Trial Type and Status

```python
# Find all Post Grant Review (PGR) proceedings
PTAB_search_trials_minimal(
    trial_type='PGR',
    limit=50
)

# Find all trials with Final Written Decisions
PTAB_search_trials_minimal(
    trial_status='Final Written Decision',
    limit=50
)

# Find recently instituted IPR proceedings
PTAB_search_trials_minimal(
    trial_type='IPR',
    trial_status='Institution Granted',
    filing_date_from='2024-01-01',
    limit=50
)
```

---

## Example 2: Progressive Disclosure Workflow

The PTAB MCP is designed for progressive disclosure - start broad with minimal searches, then drill down with balanced/complete tiers.

### Workflow Pattern: Discovery → Analysis → Documents

```python
# Step 1: Discovery (minimal tier - 95-99% context reduction)
trials = PTAB_search_trials_minimal(
    petitioner_name='Apple Inc',
    tech_center='2600',
    filing_date_from='2023-01-01',
    limit=50
)

print(f"Found {trials['count']} trials")

# Step 2: User/LLM selects interesting trials for deeper analysis

# Step 3: Detailed Analysis (balanced tier - 85-95% context reduction)
for trial_number in selected_trials:
    detailed = PTAB_search_trials_balanced(
        trial_number=trial_number,
        limit=1
    )

    print(f"Trial: {trial_number}")
    print(f"  Status: {detailed['results'][0]['trialMetaData']['trialStatusCategory']}")
    print(f"  Patent: {detailed['results'][0]['respondentData']['patentNumber']}")

# Step 4: Document Retrieval (only for relevant trials)
documents = PTAB_get_documents(
    identifier=trial_number,
    identifier_type='trial'
)

print(f"Found {len(documents['documents'])} documents")

# Step 5: Document Download/Extraction (only for key documents)
for doc in priority_documents:
    download_url = PTAB_get_document_download(
        document_id=doc['document_id'],
        identifier=trial_number,
        identifier_type='trial'
    )
```

### Why Progressive Disclosure Matters

- **Token Efficiency**: Minimal tier uses 10-15 fields vs 80-120 fields (95-99% reduction)
- **User Experience**: Present manageable results for selection
- **Targeted Retrieval**: Only pull detailed data for the items that matter
- **Response Speed**: Faster initial responses, detailed analysis on demand

---

## Example 3: Document Retrieval and Downloads

PTAB document operations work for all identifier types (trials, appeals, interferences).

### Get Document List

```python
# Get all documents for an IPR proceeding
documents = PTAB_get_documents(
    identifier='IPR2024-01353',
    identifier_type='trial'
)

print(f"Total documents: {len(documents['documents'])}")

# Documents include metadata:
# - document_id (for downloads/extraction)
# - documentDescription (e.g., "Final Written Decision")
# - fileDownloadURI (original USPTO URL)
# - pageCount
# - filingDate
```

### Download Documents (Browser Access)

```python
# Get browser-accessible download URL for a document
download = PTAB_get_document_download(
    document_id='171303338',
    identifier='IPR2024-01353',
    identifier_type='trial'
)

# Returns clickable markdown link + raw URL:
# [Download Final Written Decision](http://localhost:8083/download/...) | Raw URL: http://localhost:8083/...

# Features:
# - Secure browser downloads (API key never exposed)
# - Enhanced filenames: PTAB-2024-08-23_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf
# - Automatic rate limiting (USPTO compliance)
# - Centralized proxy integration (if PFW MCP detected)
```

### Document Content Extraction (for LLM Analysis)

```python
# Extract text from document for LLM reading
content = PTAB_get_document_content(
    document_id='171303338',
    identifier='IPR2024-01353',
    identifier_type='trial'
)

# Three-tier extraction, ordered by capability:
# 1. PyPDF2 reads the PDF's native text layer (no OCR needed)
# 2. Mistral OCR handles scanned pages with no text layer (requires MISTRAL_API_KEY)
# 3. Docling, a self-hosted OCR backend, handles short scanned filings
#    (requires DOCLING_SERVE_URL; gated to DOCLING_MAX_PAGES, default 20)
# Returns text plus extraction metadata (extraction_method, page_count)

# Use for:
# - LLM analysis of Final Written Decisions
# - Institution Decision review
# - Claim construction extraction
# - Prior art identification
```

---

## Example 4: Trial Outcome Analysis

### Analyze Institution Rates by Technology

```python
# Get all IPR proceedings in technology center 2600
trials = PTAB_search_trials_minimal(
    tech_center='2600',
    trial_type='IPR',
    limit=100
)

# Analyze outcomes
from collections import Counter
outcomes = Counter()

for trial in trials['results']:
    status = trial['trialMetaData']['trialStatusCategory']
    outcomes[status] += 1

print(f"Total Trials: {trials['count']}")
print(f"Institution Rate: {outcomes['Institution Granted'] / trials['count'] * 100:.1f}%")
print(f"Denials: {outcomes['Institution Denied']} ({outcomes['Institution Denied'] / trials['count'] * 100:.1f}%)")
```

### Compare Success Rates by Party

```python
# Analyze petitioner success rates
petitioner = 'Apple Inc'

trials = PTAB_search_trials_minimal(
    petitioner_name=petitioner,
    limit=100
)

instituted = sum(1 for t in trials['results']
                 if t['trialMetaData']['trialStatusCategory'] == 'Institution Granted')

print(f"{petitioner} Institution Rate: {instituted / trials['count'] * 100:.1f}%")
```

### Precedent Research by Outcome

```python
# Find successful IPR challenges with Final Written Decisions
successful_iprs = PTAB_search_trials_minimal(
    trial_type='IPR',
    trial_status='Final Written Decision',
    tech_center='2600',
    limit=50
)

# Analyze decision patterns
for trial in successful_iprs['results'][:10]:
    trial_num = trial['trialNumber']

    # Get documents
    docs = PTAB_get_documents(identifier=trial_num, identifier_type='trial')

    # Find Final Written Decision
    fwd = [d for d in docs['documents']
           if 'Final Written Decision' in d['documentDescription']]

    if fwd:
        print(f"{trial_num}: FWD available ({fwd[0]['pageCount']} pages)")
```

---

## Example 5: Precedent Research

### Find Similar Trials for Strategy Development

```python
# Research precedents in specific technology area
precedents = PTAB_search_trials_minimal(
    tech_center='3600',  # Software/business methods
    trial_type='IPR',
    filing_date_from='2022-01-01',
    limit=100
)

# Filter for trials with Final Written Decisions
completed_trials = [t for t in precedents['results']
                    if 'Final Written Decision' in t['trialMetaData']['trialStatusCategory']]

print(f"Found {len(completed_trials)} completed trials for precedent analysis")

# Get detailed analysis for top precedents
for trial in completed_trials[:5]:
    detailed = PTAB_search_trials_balanced(
        trial_number=trial['trialNumber'],
        limit=1
    )

    # Extract strategic insights
    # - Claim construction patterns
    # - Prior art effectiveness
    # - Decision rationale
```

---

## Example 6: Cross-MCP Integration with PFW

Combine PTAB data with Patent File Wrapper prosecution history for comprehensive analysis.

### IPR Defense Strategy

```python
# Step 1: Get IPR trial details (PTAB MCP)
trial = PTAB_search_trials_balanced(
    trial_number='IPR2024-01353',
    limit=1
)

# The patent number lives on the patent-owner bag. A trial record carries
# exactly five bags (trialNumber, lastModifiedDateTime, trialMetaData,
# regularPetitionerData, patentOwnerData) - there is no respondent bag.
patent_number = trial['results'][0]['patentOwnerData']['patentNumber']

# Step 2: Get prosecution file wrapper (PFW MCP)
prosecution = PFW_search_applications_balanced(
    patent_number=patent_number,
    limit=1
)

# Step 3: Compare prior art
# - IPR prior art vs examiner-considered references
# - Identify new references vs known art
# - Extract prosecution arguments for defense

# Step 4: Get IPR documents (PTAB MCP)
ipr_docs = PTAB_get_documents(
    identifier='IPR2024-01353',
    identifier_type='trial'
)

# Step 5: Strategic Analysis
print(f"Patent: {patent_number}")
print(f"IPR Status: {trial['results'][0]['trialMetaData']['trialStatusCategory']}")
print(f"Examiner: {prosecution['results'][0]['applicationMetaData']['examinerNameText']}")
print(f"Prosecution Documents: {len(prosecution['results'][0].get('documentBag', []))}")
print(f"IPR Documents: {len(ipr_docs['documents'])}")
```

### Portfolio PTAB Risk Assessment

```python
# Step 1: Get company's patent portfolio (PFW MCP)
portfolio = PFW_search_applications_minimal(
    applicant_name='Company XYZ',
    status_code='150',  # Granted patents
    limit=100
)

# Step 2: Check each patent for PTAB challenges (PTAB MCP)
for patent in portfolio['results']:
    patent_number = patent['applicationMetaData']['patentNumber']

    # Search for PTAB proceedings on this patent
    ptab_challenges = PTAB_search_trials_minimal(
        patent_number=patent_number,
        limit=10
    )

    if ptab_challenges['count'] > 0:
        print(f"Patent {patent_number}: {ptab_challenges['count']} PTAB challenges")

        # Analyze challenge outcomes
        for trial in ptab_challenges['results']:
            status = trial['trialMetaData']['trialStatusCategory']
            print(f"  {trial['trialNumber']}: {status}")
```

---

## Example 7: Cross-MCP Integration with PFW + FPD

Combine PTAB, prosecution history, and petition data for comprehensive risk assessment.

### Complete Patent Risk Analysis

```python
# Step 1: Get prosecution history (PFW MCP)
# Write the serial with its slash. A bare 8-digit number is ambiguous:
# PFW's identifier resolution reads it as a PATENT number and takes the
# patent lane, so `16682059` would resolve to the wrong record.
prosecution = PFW_search_applications_balanced(
    application_number='16/682,059',
    limit=1
)

patent_number = prosecution['results'][0]['applicationMetaData']['patentNumber']

# Step 2: Check for petition issues (FPD MCP)
petitions = FPD_Search_petitions_by_application(
    application_number='16/682,059'
)

# Step 3: Check for PTAB challenges (PTAB MCP)
ptab_challenges = PTAB_search_trials_minimal(
    patent_number=patent_number,
    limit=10
)

# Step 4: Comprehensive Risk Assessment
print("=== RISK ASSESSMENT ===")
print(f"Patent: {patent_number}")
print(f"Examiner: {prosecution['results'][0]['applicationMetaData']['examinerNameText']}")
print(f"Petition History: {len(petitions['results'])} petitions")

if ptab_challenges['count'] > 0:
    print(f"PTAB Challenges: {ptab_challenges['count']} proceedings")
    for trial in ptab_challenges['results']:
        print(f"  {trial['trialNumber']}: {trial['trialMetaData']['trialStatusCategory']}")
else:
    print("No PTAB Challenges")

# Risk factors:
# - Petition grant rates (indicates prosecution issues)
# - PTAB challenge frequency (indicates valuable/vulnerable patent)
# - Examiner patterns (correlates with petition/PTAB risk)
```

---

## Example 8: Complete Lifecycle Tracking

Track patent from filing through PTAB challenges using all USPTO MCPs.

### Complete Patent Intelligence Package

```python
# Step 1: Prosecution History (PFW MCP)
prosecution = PFW_get_patent_or_application_xml(
    patent_or_application_number='10701173',
    include_raw_xml=False
)

# Step 2: Citation Analysis (Citations MCP) - RUN BOTH LANES
# Neither lane is a superset of the other; union the results.
enriched_citations = Citations_search_citations_minimal(
    patent_number='10701173'
)
# The OA lane has no publicationNumber/patent_number field (HTTP 400) - resolve
# the patent to its application via PFW first, then search by application.
oa_citations = Citations_search_oa_citations_minimal(
    application_number='<application number from PFW>'
)

# Step 3: Petition History (FPD MCP)
petitions = FPD_Search_petitions_by_application(
    application_number='<application number from PFW>'
)

# Step 4: PTAB Proceedings (PTAB MCP)
ptab_proceedings = PTAB_search_trials_minimal(
    patent_number='10701173',
    limit=10
)

# Step 5: Comprehensive Timeline
print("=== COMPLETE PATENT LIFECYCLE ===")
print(f"Patent: 10701173")
print(f"\nFiling Date: {prosecution['filing_date']}")
print(f"Grant Date: {prosecution['grant_date']}")
print(f"Examiner Citations: {len(citations['results'])}")
print(f"Petitions Filed: {len(petitions['results'])}")
print(f"PTAB Proceedings: {ptab_proceedings['count']}")

# Strategic Intelligence:
# - Prosecution quality (citation effectiveness, petition rate)
# - Post-grant vulnerability (PTAB challenge frequency)
# - Litigation risk (combination of all factors)
```

---

## Known Trials for Testing

Use these real trial numbers for testing:

| Trial Number | Type | Patent Number | Status | Description |
|--------------|------|---------------|--------|-------------|
| `IPR2024-01353` | IPR | 7883848 | Final Written Decision - Appealed | 108-document docket; FWD is Paper 40 (document 171303338), issued 2026-03-04 |
| `IPR2023-01035` | IPR | 10995048 | Final Written Decision | Terminated 2024-11-01 |
| `IPR2024-00070` | IPR | 8207363 | Institution Denied | Denial decision 2024-04-18 |
| `IPR2023-01234` | IPR | 6588260 | Terminated-Settled | Instituted 2024-01-26, settled 2024-07-01 |
| `PGR2025-00009` | PGR | 12123035 | Final Written Decision | Post-grant review example |
| `CBM2020-00029` | CBM | 10467585 | Final Written Decision | The CBM program has sunset; CBM2020 is the last series |

Ex parte appeal and interference examples:

| Identifier | Type | Look up with | Notes |
|------------|------|--------------|-------|
| `17/888,602` | appeal | `PTAB_search_appeals_minimal(application_number='17/888,602')` | Appeal 2026002482, TC 3900 / AU 3992, Affirmed 2026-08-12 |
| `106,130` | interference | `PTAB_search_interferences_minimal(interference_number='106,130')` | Judgment 2025-01-28; returns 2 rows, one per decision document |

Verified against the live USPTO ODP API on 2026-09-03.

---

## Full Tool Reference

### Search Tools (Trials)

| Tool | Context Reduction | Use Case |
|------|------------------|----------|
| `PTAB_search_trials_minimal` | 95-99% | Ultra-fast discovery (10-15 fields) |
| `PTAB_search_trials_balanced` | 85-95% | Detailed analysis (30-50 fields) |
| `PTAB_search_trials_complete` | 80-90% | Complete data (all fields) |

### Document Tools (Shared)

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `PTAB_get_documents` | List all documents for identifier | USPTO_API_KEY |
| `PTAB_get_document_download` | Get browser-accessible download URL | USPTO_API_KEY |
| `PTAB_get_document_content` | Extract text for LLM analysis | USPTO_API_KEY (+ MISTRAL_API_KEY or DOCLING_SERVE_URL to OCR scanned pages) |

### Guidance Tool

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `PTAB_get_guidance` | Context-efficient selective guidance (95-99% reduction) | None |

**Available Guidance Sections**:
- `overview` - Server overview and orientation
- `fields` - Field configuration and customization
- `documents` - Document operations and downloads
- `workflows_pfw` - PFW integration patterns
- `workflows_fpd` - FPD integration patterns
- `workflows_citations` - Citations integration patterns
- `workflows_pinecone` - Pinecone RAG integration
- `workflows_complete` - Complete lifecycle workflows
- `tools` - Tool usage and progressive disclosure
- `errors` - Error handling and troubleshooting
- `cost` - Context optimization (token reduction, targeted extraction)
- `limits` - Live response-size budgets and the `_bounds` / `_window` marker contract

### Utility Tools

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `PTAB_get_field_configs` | View current field configuration | None |

---

## Best Practices

### 1. Always Start with Minimal Tier
```python
# ✅ CORRECT: Start broad with minimal
trials = PTAB_search_trials_minimal(petitioner_name='Apple Inc', limit=50)

# ❌ WRONG: Starting with complete wastes tokens
trials = PTAB_search_trials_complete(petitioner_name='Apple Inc', limit=50)
```

### 2. Use Progressive Disclosure
```python
# Discovery → Selection → Analysis → Documents
# Only escalate detail level as needed
```

### 3. Request Guidance First for Complex Workflows
```python
# For cross-MCP workflows, get guidance first
guidance = PTAB_get_guidance(section='workflows_pfw')
```

### 4. Optimize Document Retrieval
```python
# Only retrieve documents for relevant trials
# Use document filtering to reduce context
```

### 5. Leverage Cross-MCP Integration
```python
# Combine PTAB + PFW + FPD + Citations for complete intelligence
# Each MCP provides complementary data
```

---

## Next Steps

1. **Try the prompt templates**: See [PROMPTS.md](PROMPTS.md) for 11 pre-built workflows
2. **Set up cross-MCP integration**: Install PFW, FPD, Citations MCPs
3. **Customize field configurations**: Edit `field_configs.yaml` for your needs
4. **Review security guidelines**: See [SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md)

---

**Last Updated**: 2026-01-11
**Version**: 1.0.0
**Status**: Production Ready ✅
