# Usage Examples & Integration Workflows

This document provides a comprehensive set of examples for using the Patent Trial and Appeal Board (PTAB) MCP, including basic searches, advanced filtering, cross-MCP integration workflows, and progressive disclosure patterns.

## Notes on PTAB MCP Usage

For the most part the LLMs will perform these searches and workflows on their own with minimal guidance from the user. These examples are illustrative to give insight on what the LLMs are doing in the background.

**Best Practice Recommendation:** For complex workflows or when you're unsure about the best approach, start by asking the LLM to use the `ptab_get_guidance` tool first. This tool provides context-efficient workflow recommendations and helps the LLM choose the most appropriate tools and strategies for your specific use case.

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
- "Get all documents for trial IPR2024-00123"
- "Download the Final Written Decision for this IPR"
- "Extract text from the Institution Decision"

**Example 4 - Trial Outcome Analysis:**
- "Analyze institution rates in Art Unit 2600"
- "Show success rates for petitioner Apple Inc."
- "Compare outcomes across trial types (IPR vs PGR)"

**Example 5 - Cross-MCP Integration (with PFW):**
- "Research IPR2024-00123 and compare to original prosecution"
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

All search tools (`search_trials_minimal/balanced/complete`) support these parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `trial_number` | PTAB trial number | `'IPR2024-00123'` |
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
search_trials_minimal(
    patent_number='10701173',
    limit=50
)

# Get detailed information (balanced tier - if needed after discovery)
search_trials_balanced(
    patent_number='10701173',
    limit=10
)
```

### Search by Party Name

```python
# Find all IPR proceedings filed by Apple Inc in 2024
search_trials_minimal(
    petitioner_name='Apple Inc',
    trial_type='IPR',
    filing_date_from='2024-01-01',
    filing_date_to='2024-12-31',
    limit=50
)

# Find all trials where Samsung is the patent owner
search_trials_minimal(
    patent_owner_name='Samsung Electronics',
    limit=50
)
```

### Search by Technology Area

```python
# Find all IPR proceedings in wireless communications (TC 2600)
search_trials_minimal(
    tech_center='2600',
    trial_type='IPR',
    limit=50
)

# Find granted institutions in semiconductor technology
search_trials_minimal(
    tech_center='2800',
    trial_status='Institution Granted',
    limit=50
)
```

### Search by Trial Type and Status

```python
# Find all Post Grant Review (PGR) proceedings
search_trials_minimal(
    trial_type='PGR',
    limit=50
)

# Find all trials with Final Written Decisions
search_trials_minimal(
    trial_status='Final Written Decision',
    limit=50
)

# Find recently instituted IPR proceedings
search_trials_minimal(
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
trials = search_trials_minimal(
    petitioner_name='Apple Inc',
    tech_center='2600',
    filing_date_from='2023-01-01',
    limit=50
)

print(f"Found {trials['count']} trials")

# Step 2: User/LLM selects interesting trials for deeper analysis

# Step 3: Detailed Analysis (balanced tier - 85-95% context reduction)
for trial_number in selected_trials:
    detailed = search_trials_balanced(
        trial_number=trial_number,
        limit=1
    )

    print(f"Trial: {trial_number}")
    print(f"  Status: {detailed['results'][0]['trialMetaData']['trialStatusCategory']}")
    print(f"  Patent: {detailed['results'][0]['respondentData']['patentNumber']}")

# Step 4: Document Retrieval (only for relevant trials)
documents = ptab_get_documents(
    identifier=trial_number,
    identifier_type='trial'
)

print(f"Found {len(documents['documents'])} documents")

# Step 5: Document Download/Extraction (only for key documents)
for doc in priority_documents:
    download_url = ptab_get_document_download(
        document_id=doc['document_id'],
        identifier=trial_number,
        identifier_type='trial'
    )
```

### Why Progressive Disclosure Matters

- **Token Efficiency**: Minimal tier uses 10-15 fields vs 80-120 fields (95-99% reduction)
- **User Experience**: Present manageable results for selection
- **Cost Optimization**: Only retrieve detailed data for relevant items
- **Response Speed**: Faster initial responses, detailed analysis on demand

---

## Example 3: Document Retrieval and Downloads

PTAB document operations work for all identifier types (trials, appeals, interferences).

### Get Document List

```python
# Get all documents for an IPR proceeding
documents = ptab_get_documents(
    identifier='IPR2024-00123',
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
download = ptab_get_document_download(
    document_id='171141394',
    identifier='IPR2024-00123',
    identifier_type='trial'
)

# Returns clickable markdown link + raw URL:
# [Download Final Written Decision (45 pages)](http://localhost:8083/download/...) | Raw URL: http://localhost:8083/...

# Features:
# - Secure browser downloads (API key never exposed)
# - Enhanced filenames: PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf
# - Automatic rate limiting (USPTO compliance)
# - Centralized proxy integration (if PFW MCP detected)
```

### Document Content Extraction (for LLM Analysis)

```python
# Extract text from document for LLM reading
content = ptab_get_document_content(
    document_id='171141394',
    identifier='IPR2024-00123',
    identifier_type='trial'
)

# Hybrid extraction:
# 1. Tries PyPDF2 first (free, fast)
# 2. Falls back to Mistral OCR if needed (requires MISTRAL_API_KEY)
# 3. Returns text + metadata + cost transparency

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
trials = search_trials_minimal(
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

trials = search_trials_minimal(
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
successful_iprs = search_trials_minimal(
    trial_type='IPR',
    trial_status='Final Written Decision',
    tech_center='2600',
    limit=50
)

# Analyze decision patterns
for trial in successful_iprs['results'][:10]:
    trial_num = trial['trialNumber']

    # Get documents
    docs = ptab_get_documents(identifier=trial_num, identifier_type='trial')

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
precedents = search_trials_minimal(
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
    detailed = search_trials_balanced(
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
trial = search_trials_balanced(
    trial_number='IPR2024-00123',
    limit=1
)

patent_number = trial['results'][0]['respondentData']['patentNumber']

# Step 2: Get prosecution file wrapper (PFW MCP)
prosecution = pfw_search_applications_balanced(
    patent_number=patent_number,
    limit=1
)

# Step 3: Compare prior art
# - IPR prior art vs examiner-considered references
# - Identify new references vs known art
# - Extract prosecution arguments for defense

# Step 4: Get IPR documents (PTAB MCP)
ipr_docs = ptab_get_documents(
    identifier='IPR2024-00123',
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
portfolio = pfw_search_applications_minimal(
    applicant_name='Company XYZ',
    status_code='150',  # Granted patents
    limit=100
)

# Step 2: Check each patent for PTAB challenges (PTAB MCP)
for patent in portfolio['results']:
    patent_number = patent['applicationMetaData']['patentNumber']

    # Search for PTAB proceedings on this patent
    ptab_challenges = search_trials_minimal(
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
prosecution = pfw_search_applications_balanced(
    application_number='16123456',
    limit=1
)

patent_number = prosecution['results'][0]['applicationMetaData']['patentNumber']

# Step 2: Check for petition issues (FPD MCP)
petitions = fpd_search_petitions(
    application_number='16123456'
)

# Step 3: Check for PTAB challenges (PTAB MCP)
ptab_challenges = search_trials_minimal(
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
prosecution = pfw_get_patent_or_application_xml(
    patent_or_application_number='10701173',
    include_raw_xml=False
)

# Step 2: Citation Analysis (Citations MCP)
citations = citations_search_citations(
    patent_number='10701173'
)

# Step 3: Petition History (FPD MCP)
petitions = fpd_search_petitions(
    patent_number='10701173'
)

# Step 4: PTAB Proceedings (PTAB MCP)
ptab_proceedings = search_trials_minimal(
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
| `IPR2024-00070` | IPR | 10701173 | Active | Recent IPR for testing |
| `IPR2023-01234` | IPR | 9876543 | Completed | Example with FWD |
| `PGR2024-00001` | PGR | 11234567 | Active | Post Grant Review example |

---

## Full Tool Reference

### Search Tools (Trials)

| Tool | Context Reduction | Use Case |
|------|------------------|----------|
| `search_trials_minimal` | 95-99% | Ultra-fast discovery (10-15 fields) |
| `search_trials_balanced` | 85-95% | Detailed analysis (30-50 fields) |
| `search_trials_complete` | 80-90% | Complete data (all fields) |

### Document Tools (Shared)

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `ptab_get_documents` | List all documents for identifier | USPTO_API_KEY |
| `ptab_get_document_download` | Get browser-accessible download URL | USPTO_API_KEY |
| `ptab_get_document_content` | Extract text for LLM analysis | USPTO_API_KEY (+ MISTRAL_API_KEY for OCR) |

### Guidance Tool

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `ptab_get_guidance` | Context-efficient selective guidance (95-99% reduction) | None |

**Available Guidance Sections**:
- `fields` - Field configuration and customization
- `documents` - Document operations and downloads
- `workflows_pfw` - PFW integration patterns
- `workflows_fpd` - FPD integration patterns
- `workflows_citations` - Citations integration patterns
- `workflows_pinecone` - Pinecone RAG integration
- `workflows_complete` - Complete lifecycle workflows
- `tools` - Tool usage and progressive disclosure
- `errors` - Error handling and troubleshooting
- `cost` - OCR cost optimization

### Utility Tools

| Tool | Purpose | Requirements |
|------|---------|--------------|
| `ptab_get_field_configs` | View current field configuration | None |

---

## Best Practices

### 1. Always Start with Minimal Tier
```python
# ✅ CORRECT: Start broad with minimal
trials = search_trials_minimal(petitioner_name='Apple Inc', limit=50)

# ❌ WRONG: Starting with complete wastes tokens
trials = search_trials_complete(petitioner_name='Apple Inc', limit=50)
```

### 2. Use Progressive Disclosure
```python
# Discovery → Selection → Analysis → Documents
# Only escalate detail level as needed
```

### 3. Request Guidance First for Complex Workflows
```python
# For cross-MCP workflows, get guidance first
guidance = ptab_get_guidance(section='workflows_pfw')
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
