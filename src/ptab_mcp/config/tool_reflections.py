"""
Tool reflections and LLM guidance for USPTO PTAB MCP.

This module provides sectioned guidance for context-efficient access.
Each section is 1-15KB instead of 70KB+ for all content.

CRITICAL: Returns clean markdown strings, NOT dict/JSON.
NO json.dumps() - causes escaping issues in Claude Desktop.
"""


def _get_overview_section() -> str:
    """Overview section with available sections and quick reference"""
    return """## Available Sections and Quick Reference

### Quick Reference Chart - What section for your question?

- **"Find IPR/PGR/CBM proceedings by patent/party"** → `tools`
- **"Document selection and download formatting"** → `documents`
- **"PFW integration for citations/prosecution"** → `workflows_pfw`
- **"FPD integration for petition analysis"** → `workflows_fpd`
- **"Citations integration for prior art"** → `workflows_citations`
- **"Pinecone RAG for semantic search"** → `workflows_pinecone`
- **"Complete lifecycle tracking across all MCPs"** → `workflows_complete`
- **"Field customization and YAML config"** → `fields`
- **"Search errors or query issues"** → `errors`
- **"Reduce API costs and optimize context"** → `cost`

### Available Sections:
- **overview**: Available sections and tool summary (this section)
- **fields**: Field configuration and customization
- **documents**: Document operations and download formatting
- **workflows_pfw**: Cross-MCP integration with Patent File Wrapper
- **workflows_fpd**: Cross-MCP integration with Filing & Petition Data
- **workflows_citations**: Cross-MCP integration with Enriched Citations
- **workflows_pinecone**: Cross-MCP integration with Pinecone RAG
- **workflows_complete**: Complete prosecution lifecycle tracking
- **tools**: Tool usage and progressive disclosure
- **errors**: Common error patterns and troubleshooting
- **cost**: Cost optimization strategies

### Context Efficiency Benefits:
- **90-95% token reduction** (1-15KB per section vs 70KB+ total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Consistent experience** across all USPTO MCPs"""


def _get_fields_section() -> str:
    """Field configuration and customization"""
    return """## Field Configuration and Customization

### YAML Configuration Location

**File**: `field_configs.yaml` (project root)

### Predefined Field Sets

**trials_minimal (10-15 fields):**
- Trial core identifiers (trialNumber)
- Filing and status metadata
- Party names (petitioner, patent owner)
- Patent information
- **Context Reduction**: 68% vs balanced

**trials_balanced (30-50 fields):**
- All minimal fields
- Complete party metadata
- Decision information
- Institution details
- Counsel information
- **Context Reduction**: 13.5% vs complete

**trials_complete (~80-120 fields):**
- All available fields from API
- Complete metadata for archival
- **Use sparingly**: High token cost

### Custom Field Selection

All search tools support `fields` parameter for ultra-minimal queries:

```python
# Ultra-minimal: Only 2 fields (99% reduction)
search_trials_minimal(
    patent_number='8524787',
    fields=['trialNumber', 'trialMetaData.trialStatusCategory'],
    limit=50
)
```

**Field Naming Convention**:
- Dot notation for nested fields
- Examples:
  - `trialNumber` (top-level)
  - `trialMetaData.accordedFilingDate` (nested)
  - `patentOwnerData.patentOwnerName` (nested)

### Editing Field Configurations

**To customize predefined sets**:

1. Edit `field_configs.yaml`
2. Add/remove fields from minimal/balanced/complete tiers
3. Use wildcard patterns (e.g., `trialMetaData.*`)
4. Restart MCP server

**Example YAML**:
```yaml
predefined_sets:
  trials_minimal:
    description: "Ultra-minimal trial discovery"
    fields:
      - trialNumber
      - trialMetaData.accordedFilingDate
      - trialMetaData.trialTypeCode
      - patentOwnerData.patentNumber
```

### Forbidden Fields

**documentBag fields**: NOT allowed in custom fields parameter.
- Reason: Documents are heavy and require separate tools
- Use: `ptab_get_documents()` instead

### Progressive Disclosure Strategy

**Stage 1: Discovery (Minimal)**
- Use `search_trials_minimal` with predefined or custom fields
- High volume (50-100 results)
- Identify candidates

**Stage 2: Analysis (Balanced)**
- Use `search_trials_balanced` for selected trials
- Medium volume (10-20 results)
- Detailed analysis

**Stage 3: Documents (Document Tools)**
- Use `ptab_get_documents` for document lists
- Use `ptab_get_document_download` for browser access
- Use `ptab_get_document_content` for LLM analysis"""


def _get_documents_section() -> str:
    """Document operations and download formatting"""
    return """## Document Operations Guidance

### CRITICAL Download Link Format

**Always format download links with BOTH clickable markdown AND raw URL:**

```
**[Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`
```

**Why Both Formats?**
- Clickable markdown links work in Claude Desktop and most clients
- Raw URLs enable copy/paste in Msty and other clients where links aren't clickable
- Ensures maximum compatibility across different MCP clients

### Document Discovery Workflow

**Step 1: Get Document List (with Filtering and Pagination)**
```python
# Trials use POST search endpoint — returns true total count and next_offset hint
# A heavily-litigated IPR may have 100+ documents; response shows total_documents
docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_category='DECISION',  # Filter to Board decisions only
    limit=10
)
# Response includes: total_documents (true count), returned_count, next_offset
```

### Pagination — Accessing the Full Docket (Trials)

Trials use a POST search endpoint that supports true server-side pagination. The response
always includes `total_documents` (e.g. 105) and `next_offset` when more pages exist.

```python
# Page 1 — oldest documents first (Petition, POPR, early exhibits)
page1 = ptab_get_documents(
    identifier='IPR2024-01353',
    sort_order='asc',   # oldest first
    offset=0, limit=25
)
# Response: total_documents=105, returned_count=25, next_offset=25

# Page 2 — next 25 documents
page2 = ptab_get_documents(
    identifier='IPR2024-01353',
    sort_order='asc',
    offset=25, limit=25
)
# Continue with offset=50, 75, 100... until next_offset is absent
```

**sort_order parameter**:
- `'asc'` — oldest first; surfaces Petition, POPR, Institution Decision, early exhibits
- `'desc'` — newest first (default); surfaces FWD, Sur-Reply, hearing transcripts

**Known API limitation**: The Petition (Paper 1) and Institution Decision may not appear
in the search endpoint results for some proceedings. If they are missing after paginating
through all results, use the trial ZIP download (from `search_trials_balanced` →
`fileDownloadURI`) which contains the complete docket.

Appeals/Interferences use a GET endpoint with no server-side pagination.

### Selective Filtering (Client-Side, Applied to Each Page)

**Available Filters (All Case-Insensitive)**:

**1. document_title** (All Types — most precise)
- Substring match on `documentTypeDescriptionText` (the description field, e.g. "Final Written Decision")
- More precise than document_category — targets a single document type
- Examples:
  - `document_title='Final Written Decision'` → just the FWD
  - `document_title='Institution Decision'` → institution decision
  - `document_title='Patent Owner Response'` → POR filings
  - `document_title='Oral Hearing'` → hearing transcripts and demonstratives
- Note: matches the description field, not the title field; short substrings cast a wider net

**2. document_category** (Trials Only — coarser)
- Exact match on the category field
- Key categories: `PETITION`, `RESPONSE`, `ORDER`, `DECISION`, `FINAL`, `MOTION`, `EXHIBIT`

**3. filing_party** (Trials Only)
- `BOARD`: Board documents (orders, decisions)
- `PETITIONER`: Petitioner submissions (petitions, replies, exhibits)
- `PATENT OWNER`: Patent owner submissions (responses, sur-replies)

**4. outcome_category** (Appeals/Interferences Only)
- Appeals: `Affirmed`, `Reversed`, `Rehearing Decision Denied`
- Interferences: `Final Decision`, `Judgment`, etc.

**Filtering Examples**:

```python
# Example 1: Get Final Written Decision by description (most precise)
fwd = ptab_get_documents(
    identifier='IPR2024-00123',
    document_title='Final Written Decision',
    limit=5
)

# Example 2: All Board orders (coarse category filter)
orders = ptab_get_documents(
    identifier='IPR2024-00123',
    filing_party='BOARD',
    limit=20
)

# Example 3: Patent owner responses only
responses = ptab_get_documents(
    identifier='IPR2024-00123',
    filing_party='PATENT OWNER',
    document_category='RESPONSE',
    limit=10
)

# Example 4: Full docket scan for a specific document across all pages
fwd = ptab_get_documents(
    identifier='IPR2024-00123',
    document_title='Final Written Decision',
    offset=0, limit=100   # fetch full page (API max) then filter
)

# Example 5: Appeals with specific outcome
appeal_docs = ptab_get_documents(
    identifier='2025000943',
    identifier_type='appeal',
    outcome_category='Affirmed',
    limit=10
)
```

**Token Reduction Benefits**:
| Scenario | Without Filtering | With Filtering | Reduction |
|----------|------------------|----------------|-----------|
| Large IPR (105 docs) | ~350KB response | ~15KB response | **96%** |
| Medium IPR (50 docs) | ~165KB response | ~25KB response | **85%** |
| Appeals (30 docs) | ~100KB response | ~20KB response | **80%** |

**Best Practices**:
- ✅ Use `document_title` for precise single-document targeting (FWD, Institution Decision, etc.)
- ✅ Use `sort_order='asc'` + pagination to access early docket (Petition, POPR)
- ✅ Use `filing_party='BOARD'` to get all official Board documents
- ✅ Combine `filing_party` + `document_category` for maximum precision
- ❌ **AVOID** `limit=100` without any filter — fetches full page unnecessarily

**Step 2: Select Documents for Download**
```python
# Priority documents for different use cases:

# IPR Response Strategy
- Final Written Decision
- Institution Decision
- Patent Owner Preliminary Response

# Prior Art Research
- Petition documents
- Petitioner exhibits
- Expert declarations

# Litigation Preparation
- Final Written Decision
- All decisions and orders
- Complete docket
```

**Step 3: Generate Download Links**
```python
# For browser access (user downloads directly)
download = ptab_get_document_download(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id='171141394'
)

# Format with BOTH clickable and raw URL:
response = f"**[Download Final Written Decision (45 pages)]({download['proxy_url']})** | Raw URL: `{download['proxy_url']}`"
```

**Step 4: Extract Content for LLM Analysis**
```python
# When user asks: "What did the Board say about claim 1?"
content = ptab_get_document_content(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id='171141394'
)

# Analyze extracted text and answer question
# Note: OCR costs apply (~$0.15 per 1M input tokens)
```

### Multi-Document Workflow Example

```python
# Step 1: Get filtered documents
docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_title='Final Written Decision',  # precise description match
    limit=5
)
# Response includes total_documents (true count from API) and returned_count

# Step 2: Parse response
import json
docs_data = json.loads(docs)

# Step 3: Generate download links for filtered documents
download_links = []
for doc in docs_data['documents']:
    download = ptab_get_document_download(
        identifier='IPR2024-00123',
        identifier_type='trial',
        document_id=doc['documentIdentifier']
    )

    link_text = f"**[Download {doc.get('documentTypeDescriptionText', 'Document')} ({doc.get('pageCount', 'N/A')} pages)]({download['proxy_url']})** | Raw URL: `{download['proxy_url']}`"
    download_links.append(link_text)

# Step 4: Present to user
print("Board Decisions:\\n" + "\\n".join(download_links))
```

### Combined Filtering Example (Maximum Precision)

```python
# Scenario: Get ONLY Patent Owner's Response documents (not petitioner replies or exhibits)
responses = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial',
    filing_party='PATENT OWNER',      # Filter 1: Only patent owner filings
    # Or use document_title for even finer targeting:
    document_category='RESPONSE',      # Filter 2: Only response documents
    limit=10
)

# Result: Highly targeted document list (typically 1-3 documents)
# Token reduction: 95-98% vs unfiltered request
# Perfect for focused analysis without noise from other parties/document types
```

### Expected Filename Formats

**Pattern**: `PTAB-{date}_{trial}_{patent}_{description}.pdf`

**Examples**:
- `PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf`
- `PTAB-2024-03-20_PGR2025-00045_PAT-9876543_INSTITUTION_DECISION.pdf`
- `PTAB-2024-01-10_IPR2024-00123_PAT-8524787_PATENT_OWNER_RESPONSE.pdf`

### Browser Compatibility

**Proxy Integration**:
- Centralized PFW proxy (port 8080) - preferred
- Local PTAB proxy (port 8083) - automatic fallback
- Always-on mode: Links work immediately
- 7-day persistent links: Links remain valid after proxy restart

**Supported Browsers**:
- Chrome, Firefox, Edge (all versions)
- Safari (macOS)
- Any browser with PDF viewer

### Document Prioritization by Use Case

**Patent Owner Response Preparation**:
1. Final Written Decision (outcome analysis)
2. Institution Decision (claims instituted)
3. Petitioner exhibits (prior art)

**Prior Art Mining**:
1. Petition documents (petitioner's case)
2. Petitioner exhibits (cited references)
3. Expert declarations (technical analysis)

**Litigation Strategy**:
1. Final Written Decision (estoppel analysis)
2. All decisions and orders (procedural history)
3. Patent Owner Response (arguments used)

**Technology Landscape Research**:
1. Multiple petition documents (different challenges)
2. Final Written Decisions (Board's technical analysis)
3. Expert declarations (technical explanations)"""


def _get_workflows_pfw_section() -> str:
    """PFW integration workflows"""
    return """## PTAB + PFW Integration Workflows

### Use Case 1: IPR Challenge Defense Strategy

**Scenario**: Patent owner needs to defend against IPR petition

**Workflow**:
```python
# STEP 1: PTAB - Get IPR proceedings for patent
ptab_trials = search_trials_balanced(
    patent_number='8524787',
    trial_type='IPR',
    limit=20
)

# STEP 2: PFW - Get prosecution history
pfw_apps = pfw_search_applications_minimal(
    query='patentNumber:8524787',
    fields=['applicationNumberText'],
    limit=1
)
app_number = pfw_apps['applications'][0]['applicationNumberText']

# STEP 3: PFW - Get key prosecution documents
noa_docs = pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',  # Notice of Allowance
    limit=5
)

rejection_docs = pfw_get_application_documents(
    app_number=app_number,
    document_code='CTFR|CTNF',  # Office actions
    limit=10
)

# STEP 4: Compare PTAB challenges to prosecution history
# - Identify arguments already addressed during prosecution
# - Find examiner's reasoning from NOA for patent owner response
# - Locate prior art comparison in rejection documents
```

### Use Case 2: IPR Petitioner Portfolio Analysis

**Scenario**: Identify patents vulnerable to IPR challenges

**Workflow**:
```python
# STEP 1: PFW - Get portfolio applications
pfw_portfolio = pfw_search_applications_minimal(
    query='assigneeEntityName:"Company X" AND filingDate:[2015-01-01 TO *]',
    fields=['applicationNumberText', 'patentNumber', 'applicationMetaData.filingDate'],
    limit=100
)

# STEP 2: PTAB - Check for existing challenges
vulnerable_patents = []
for app in pfw_portfolio['applications']:
    if app.get('patentNumber'):
        ptab_results = search_trials_minimal(
            patent_number=app['patentNumber'],
            limit=10
        )

        if ptab_results.get('count', 0) > 0:
            vulnerable_patents.append({
                'patent': app['patentNumber'],
                'app': app['applicationNumberText'],
                'ipr_count': ptab_results['count']
            })

# STEP 3: PFW - Analyze prosecution history for vulnerability
for patent_info in vulnerable_patents[:10]:  # Limit to top 10
    # Get examiner's search strategy
    search_docs = pfw_get_application_documents(
        app_number=patent_info['app'],
        document_code='892',  # Examiner's search
        limit=1
    )

    # Analyze citation thoroughness
    # Low citation count = higher IPR vulnerability
```

### Use Case 3: Cross-MCP Field Mapping

**Application Number Correlation**:
```python
# PFW → PTAB: applicationNumberText → patentNumber
pfw_app = pfw_search_applications_minimal(
    application_number='14171705',
    fields=['applicationNumberText', 'patentNumber']
)

patent_num = pfw_app['applications'][0]['patentNumber']

# Use patent number in PTAB
ptab_trials = search_trials_minimal(
    patent_number=patent_num,
    limit=20
)
```

**Date Field Mapping**:
- PFW `filingDate` → PTAB `accordedFilingDate` (2-3 year lag typical)
- PFW `patentIssueDate` → PTAB filing (IPRs filed post-grant)

### Document Integration Patterns

**Pattern 1: Prosecution Estoppel Analysis**
```python
# Get PTAB Final Written Decision
ptab_docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial'
)

fwd_download = ptab_get_document_download(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id='171141394'
)

# Get PFW prosecution history
pfw_docs = pfw_get_application_documents(
    app_number='14171705',
    document_code='NOA|CTFR',
    limit=20
)

# Compare claim amendments and arguments
# Identify prosecution estoppel issues for litigation
```

**Pattern 2: Prior Art Validation**
```python
# Get PTAB petition exhibits
ptab_petition = ptab_get_document_content(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id='petition_doc_id'
)

# Get PFW examiner citations
pfw_892 = pfw_get_document_content(
    app_number='14171705',
    document_identifier='892_doc_id'
)

# Compare:
# - Was prior art considered during prosecution?
# - Did examiner address same arguments?
# - Patent owner estoppel based on prosecution?
```

### Token Efficiency for Cross-MCP Workflows

**Without Optimization**:
- PFW: 100 apps × full metadata = ~500KB
- PTAB: 50 trials × full metadata = ~250KB
- Total: ~750KB

**With Optimization**:
- PFW: 100 apps × 3 custom fields = ~15KB
- PTAB: 50 trials × minimal preset = ~40KB
- Total: ~55KB (93% reduction)"""


def _get_workflows_fpd_section() -> str:
    """FPD integration workflows"""
    return """## PTAB + FPD Integration Workflows

### Use Case 1: Petition Filing Pattern Analysis

**Scenario**: Correlate FPD petition activity with PTAB challenge vulnerability

**Workflow**:
```python
# STEP 1: FPD - Get petitions for technology area
fpd_petitions = fpd_search_petitions_minimal(
    art_unit='2854',
    decision_type='GRANTED',
    limit=100
)

# STEP 2: PTAB - Check for IPR challenges on petitioned patents
petition_apps = [p['applicationNumber'] for p in fpd_petitions['results']]

for app_num in petition_apps[:20]:  # Limit to top 20
    # Get patent number (may need PFW for correlation)
    pfw_app = pfw_search_applications_minimal(
        application_number=app_num,
        fields=['patentNumber'],
        limit=1
    )

    if pfw_app['applications'] and pfw_app['applications'][0].get('patentNumber'):
        patent_num = pfw_app['applications'][0]['patentNumber']

        # Check PTAB challenges
        ptab_trials = search_trials_minimal(
            patent_number=patent_num,
            limit=10
        )

        if ptab_trials.get('count', 0) > 0:
            print(f"Petition + PTAB: {app_num} / {patent_num}")
```

### Use Case 2: Art Unit Quality Assessment

**Scenario**: Evaluate prosecution quality using petition + PTAB correlation

**Workflow**:
```python
# STEP 1: FPD - Get petition statistics for art unit
fpd_stats = fpd_search_petitions_minimal(
    art_unit='2854',
    limit=100
)

granted_petitions = [p for p in fpd_stats['results']
                     if p.get('decision_type') == 'GRANTED']

# STEP 2: PTAB - Get IPR proceedings for same art unit
ptab_stats = search_trials_minimal(
    tech_center='2800',  # Art unit 2854 maps to tech center 2800
    limit=100
)

# STEP 3: Calculate quality metrics
petition_rate = len(granted_petitions) / fpd_stats.get('count', 1)
ipr_rate = ptab_stats.get('count', 0) / 100  # Per 100 patents

if petition_rate > 0.15 and ipr_rate > 0.10:
    print(f"Art unit 2854: High petition (15%+) and IPR (10%+) rates")
    print("Potential prosecution quality issues")
```

### Use Case 3: Examiner-Specific Vulnerability Analysis

**Scenario**: Identify examiner patterns leading to petition/PTAB challenges

**Workflow**:
```python
# STEP 1: FPD - Get petitions by examiner
fpd_examiner = fpd_search_petitions_minimal(
    examiner_name='SMITH',
    limit=50
)

# STEP 2: Get application numbers from petitions
petition_apps = [p['applicationNumber'] for p in fpd_examiner['results']]

# STEP 3: PFW - Get patent numbers for those applications
patent_numbers = []
for app_num in petition_apps[:20]:
    pfw_app = pfw_search_applications_minimal(
        application_number=app_num,
        fields=['patentNumber'],
        limit=1
    )

    if pfw_app['applications']:
        patent_num = pfw_app['applications'][0].get('patentNumber')
        if patent_num:
            patent_numbers.append(patent_num)

# STEP 4: PTAB - Check IPR challenges
ipr_count = 0
for patent_num in patent_numbers:
    ptab_trials = search_trials_minimal(
        patent_number=patent_num,
        limit=1
    )
    ipr_count += ptab_trials.get('count', 0)

# STEP 5: Calculate vulnerability score
examiner_vulnerability_score = (len(granted_petitions) + ipr_count) / len(petition_apps)
print(f"Examiner SMITH vulnerability score: {examiner_vulnerability_score:.2f}")
```

### Cross-Reference Fields

**FPD → PTAB**:
- `applicationNumber` → Need PFW for patent number → `patent_number`
- `art_unit` → `tech_center` (first 2 digits, e.g., 2854 → 2800)

**PTAB → FPD**:
- `patentNumber` → Need PFW for application number → `applicationNumber`
- `tech_center` → Art units in that range (2800 → 2800-2899)

### Token Efficiency

**Without Optimization**:
- FPD: 100 petitions × full metadata = ~200KB
- PTAB: 50 trials × full metadata = ~250KB
- PFW: 50 apps × full metadata = ~250KB
- Total: ~700KB

**With Optimization**:
- FPD: 100 petitions × 3 custom fields = ~15KB
- PTAB: 50 trials × minimal preset = ~40KB
- PFW: 50 apps × 2 custom fields = ~10KB
- Total: ~65KB (91% reduction)"""


def _get_workflows_citations_section() -> str:
    """Citations integration workflows"""
    return """## PTAB + Citations Integration Workflows

### Use Case 1: Prior Art Validation for PTAB Challenges

**Scenario**: Validate prior art cited in IPR petition against prosecution history

**Workflow**:
```python
# STEP 1: PTAB - Get IPR proceedings for patent
ptab_trials = search_trials_balanced(
    patent_number='9049188',
    trial_type='IPR',
    limit=20
)

# STEP 2: PTAB - Get petition documents to extract prior art
ptab_docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial'
)

petition_download = ptab_get_document_download(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id='petition_doc_id'
)

# STEP 3: Citations - Get prosecution citations
citations = search_citations_balanced(
    criteria=f'publicationNumber:9049188 AND officeActionDate:[2017-10-01 TO *]',
    rows=100
)

# STEP 4: Compare prior art sets
# Extract cited references from petition (manual or OCR)
# Compare against citations['response']['docs']
# Identify:
#   - New prior art (not cited during prosecution)
#   - Examiner-considered art (cited during prosecution)
#   - Applicant-disclosed art (IDS filings)
```

### Use Case 2: PTAB Vulnerability Assessment via Citation Patterns

**Scenario**: Identify patents vulnerable to post-grant challenges

**Workflow**:
```python
# STEP 1: Get patent portfolio
pfw_portfolio = pfw_search_applications_minimal(
    query='assigneeEntityName:"Company X" AND patentNumber:*',
    fields=['patentNumber', 'applicationNumberText'],
    limit=100
)

# STEP 2: For each patent, analyze citation patterns
vulnerability_scores = []

for app in pfw_portfolio['applications'][:20]:  # Limit to 20
    patent_num = app.get('patentNumber')
    if not patent_num:
        continue

    # Get prosecution citations
    citations = search_citations_minimal(
        criteria=f'publicationNumber:{patent_num} AND officeActionDate:[2017-10-01 TO *]',
        fields=['examinerCitedReferenceIndicator', 'citationCategoryCode'],
        rows=100
    )

    # Calculate vulnerability indicators
    total_citations = citations.get('response', {}).get('numFound', 0)

    examiner_cites = sum(
        1 for c in citations.get('response', {}).get('docs', [])
        if c.get('examinerCitedReferenceIndicator') == 'true'
    )

    npl_cites = sum(
        1 for c in citations.get('response', {}).get('docs', [])
        if c.get('citationCategoryCode') == 'NPL'
    )

    # Vulnerability scoring
    score = 0
    if total_citations < 5:
        score += 3  # Low citation count
    if examiner_cites < 3:
        score += 2  # Minimal examiner search
    if npl_cites == 0:
        score += 1  # No NPL (narrow search)

    # STEP 3: Check for existing PTAB challenges
    ptab_trials = search_trials_minimal(
        patent_number=patent_num,
        limit=1
    )

    vulnerability_scores.append({
        'patent': patent_num,
        'citation_score': score,
        'ptab_challenged': ptab_trials.get('count', 0) > 0
    })

# STEP 4: Prioritize high-vulnerability patents
high_risk = [v for v in vulnerability_scores if v['citation_score'] >= 4]
print(f"High PTAB vulnerability: {len(high_risk)} patents")
```

### Use Case 3: Examiner Citation Patterns vs PTAB Outcomes

**Scenario**: Correlate examiner citation behavior with PTAB challenge success

**Workflow**:
```python
# STEP 1: Get PTAB trials with outcomes
ptab_trials = search_trials_balanced(
    trial_type='IPR',
    final_decision_date_from='2023-01-01',
    limit=50
)

# STEP 2: For each trial, analyze prosecution citations
for trial in ptab_trials['results'][:20]:
    patent_num = trial.get('patentOwnerData', {}).get('patentNumber')
    if not patent_num:
        continue

    # Get prosecution citations
    citations = search_citations_minimal(
        criteria=f'publicationNumber:{patent_num} AND officeActionDate:[2017-10-01 TO *]',
        fields=['examinerCitedReferenceIndicator', 'citationCategoryCode'],
        rows=100
    )

    # Extract PTAB outcome
    outcome = trial.get('decisionData', {}).get('finalDecisionOutcome')

    # Correlate citation patterns with outcome
    examiner_cite_count = sum(
        1 for c in citations.get('response', {}).get('docs', [])
        if c.get('examinerCitedReferenceIndicator') == 'true'
    )

    print(f"Patent {patent_num}: {examiner_cite_count} examiner cites → {outcome}")
```

### Cross-Reference Fields

**Citations → PTAB**:
- `publicationNumber` → `patentNumber`
- Use for: PTAB challenge research for cited patents

**PTAB → Citations**:
- `patentNumber` → `publicationNumber`
- Use for: Prosecution citation analysis for challenged patents

### Token Efficiency

**Without Optimization**:
- Citations: 100 results × 18 fields = ~200KB
- PTAB: 50 trials × full metadata = ~250KB
- Total: ~450KB

**With Optimization**:
- Citations: 100 results × 3 custom fields = ~30KB
- PTAB: 50 trials × minimal preset = ~40KB
- Total: ~70KB (84% reduction)"""


def _get_workflows_pinecone_section() -> str:
    """Pinecone RAG integration workflows"""
    return """## PTAB + Pinecone RAG Integration Workflows

### Use Case 1: Semantic PTAB Decision Search

**Scenario**: Find similar PTAB decisions using natural language queries

**Workflow**:
```python
# STEP 1: Pinecone - Semantic search for similar decisions
pinecone_results = pinecone_query(
    query="claim construction for means-plus-function limitations",
    namespace="ptab_decisions",
    top_k=10
)

# STEP 2: PTAB - Get detailed metadata for similar decisions
trial_numbers = [r['metadata']['trial_number'] for r in pinecone_results['matches']]

for trial_num in trial_numbers[:5]:
    trial_details = search_trials_balanced(
        trial_number=trial_num,
        limit=1
    )

    # Get full decision document
    docs = ptab_get_documents(
        identifier=trial_num,
        identifier_type='trial'
    )

    fwd_docs = [d for d in docs['documents']
                if 'Final Written Decision' in d.get('description', '')]

    if fwd_docs:
        download = ptab_get_document_download(
            identifier=trial_num,
            identifier_type='trial',
            document_id=fwd_docs[0]['documentIdentifier']
        )
        print(f"Similar decision: {trial_num}")
        print(f"Download: {download['proxy_url']}")
```

### Use Case 2: PTAB Decision Embedding Pipeline

**Scenario**: Index PTAB decisions in Pinecone for semantic search

**Workflow**:
```python
# STEP 1: PTAB - Get recent final decisions
recent_trials = search_trials_minimal(
    final_decision_date_from='2024-01-01',
    limit=100
)

# STEP 2: Extract decision text for embedding
for trial in recent_trials['results'][:20]:
    trial_num = trial.get('trialNumber')

    # Get Final Written Decision
    docs = ptab_get_documents(
        identifier=trial_num,
        identifier_type='trial'
    )

    fwd_docs = [d for d in docs['documents']
                if 'Final Written Decision' in d.get('description', '')]

    if fwd_docs:
        # Extract text
        content = ptab_get_document_content(
            identifier=trial_num,
            identifier_type='trial',
            document_id=fwd_docs[0]['documentIdentifier']
        )

        # STEP 3: Create embedding and upsert to Pinecone
        # (Implementation depends on Pinecone MCP capabilities)
        # pinecone_upsert(
        #     vectors=[{
        #         'id': trial_num,
        #         'values': embedding,  # From embedding model
        #         'metadata': {
        #             'trial_number': trial_num,
        #             'patent_number': trial.get('patentOwnerData', {}).get('patentNumber'),
        #             'text': content['text'][:1000]
        #         }
        #     }],
        #     namespace='ptab_decisions'
        # )
```

### Use Case 3: Hybrid Search (Metadata + Semantic)

**Scenario**: Combine PTAB metadata filtering with semantic similarity

**Workflow**:
```python
# STEP 1: PTAB - Filter by metadata
tech_filtered = search_trials_minimal(
    tech_center='2100',
    trial_type='IPR',
    final_decision_date_from='2023-01-01',
    fields=['trialNumber', 'patentOwnerData.patentNumber'],
    limit=100
)

trial_numbers = [t['trialNumber'] for t in tech_filtered['results']]

# STEP 2: Pinecone - Semantic search within metadata-filtered set
# (Requires Pinecone metadata filtering)
semantic_results = pinecone_query(
    query="anticipation rejection based on single reference",
    filter={'trial_number': {'$in': trial_numbers}},
    top_k=10
)

# STEP 3: Retrieve full details for top semantic matches
for match in semantic_results['matches'][:5]:
    trial_num = match['metadata']['trial_number']

    trial_details = search_trials_balanced(
        trial_number=trial_num,
        limit=1
    )

    print(f"Hybrid match: {trial_num} (score: {match['score']:.2f})")
```

### Integration Benefits

**Metadata Search (PTAB MCP)**:
- Structured queries (patent number, party names, dates)
- Fast exact matching
- Field-specific filtering

**Semantic Search (Pinecone)**:
- Natural language queries
- Similarity ranking
- Concept-based discovery

**Combined Power**:
- Filter by structured criteria → Semantic rank results
- Find similar decisions → Get structured metadata
- Discover precedents → Retrieve full documents

### Token Efficiency

**Pinecone Integration**:
- Pinecone returns vector IDs and metadata (small payload)
- PTAB minimal search for metadata (~40KB for 50 trials)
- Only download full documents for top matches
- Total: ~50KB vs ~500KB for full-text search"""


def _get_workflows_complete_section() -> str:
    """Complete lifecycle workflows across all MCPs"""
    return """## Complete Prosecution Lifecycle Tracking

### Four-MCP Integration: PTAB + PFW + FPD + Citations

**Use Case**: Comprehensive patent intelligence from filing through post-grant

**Complete Workflow**:

```python
# ============================================================================
# PHASE 1: Patent Identification
# ============================================================================

patent_number = '9049188'

# PTAB - Check for post-grant challenges
ptab_proceedings = search_trials_balanced(
    patent_number=patent_number,
    limit=10
)

print(f"PTAB Proceedings: {ptab_proceedings.get('count', 0)}")

# ============================================================================
# PHASE 2: Prosecution History (PFW)
# ============================================================================

# Get application number from patent
pfw_search = pfw_search_applications_minimal(
    query=f'patentNumber:{patent_number}',
    fields=['applicationNumberText'],
    limit=1
)

app_number = pfw_search['applications'][0]['applicationNumberText']

# Get key prosecution documents
noa_docs = pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',  # Notice of Allowance
    limit=5
)

rejection_docs = pfw_get_application_documents(
    app_number=app_number,
    document_code='CTFR|CTNF',  # Office actions
    limit=10
)

print(f"Prosecution: {noa_docs['count']} allowances, {rejection_docs['count']} rejections")

# ============================================================================
# PHASE 3: Citation Intelligence
# ============================================================================

citations = search_citations_balanced(
    criteria=f'publicationNumber:{patent_number} AND officeActionDate:[2017-10-01 TO *]',
    rows=100
)

examiner_citations = [
    c for c in citations['response']['docs']
    if c['examinerCitedReferenceIndicator'] == 'true'
]

print(f"Citations: {citations['response']['numFound']} total, {len(examiner_citations)} examiner")

# ============================================================================
# PHASE 4: Petition Analysis (FPD)
# ============================================================================

petitions = fpd_search_petitions_minimal(
    application_number=app_number,
    limit=10
)

print(f"Petitions: {petitions['response']['numFound']}")

# ============================================================================
# PHASE 5: Comprehensive Intelligence Report
# ============================================================================

print(\"\"\"
COMPLETE LIFECYCLE INTELLIGENCE
================================

Patent: {{patent_number}}
Application: {{app_number}}

PROSECUTION HISTORY (PFW):
  - Allowances: {{noa_docs['count']}}
  - Rejections: {{rejection_docs['count']}}
  - Status: Granted

CITATION INTELLIGENCE:
  - Total citations: {{citations['response']['numFound']}}
  - Examiner citations: {{len(examiner_citations)}}
  - Citation thoroughness: {{'Strong' if len(examiner_citations) > 10 else 'Weak'}}

PETITION HISTORY (FPD):
  - Total petitions: {{petitions['response']['numFound']}}
  - Quality indicator: {{'Red flag' if petitions['response']['numFound'] > 2 else 'Normal'}}

PTAB STATUS:
  - Active proceedings: {{ptab_proceedings.get('count', 0)}}
  - PTAB vulnerability: {{'High' if ptab_proceedings.get('count', 0) > 0 else 'Low'}}

STRATEGIC ASSESSMENT:
\"\"\")

# Calculate composite risk score
risk_score = 0
if len(examiner_citations) < 5:
    risk_score += 2
if petitions['response']['numFound'] > 1:
    risk_score += 2
if ptab_proceedings.get('count', 0) > 0:
    risk_score += 3

print(f"  - Overall risk score: {risk_score}/7")
print(f"  - Risk level: {'HIGH' if risk_score >= 5 else 'MEDIUM' if risk_score >= 3 else 'LOW'}")
```

### Five-MCP Integration: Add Pinecone RAG

**Enhanced with Semantic Search**:

```python
# After PTAB proceedings identified, find similar cases

for trial in ptab_proceedings['results'][:5]:
    trial_num = trial['trialNumber']

    # Get decision text
    docs = ptab_get_documents(
        identifier=trial_num,
        identifier_type='trial'
    )

    # Semantic search for similar decisions
    similar = pinecone_query(
        query="claim construction and anticipation analysis",
        filter={'tech_center': trial.get('techCenter')},
        top_k=5
    )

    print(f"Similar cases for {trial_num}: {len(similar['matches'])}")
```

### Strategic Intelligence Outputs

**1. Invalidity Analysis**
- Comprehensive prior art from prosecution citations
- PTAB prior art comparison
- Citation gap analysis for potential invalidity arguments

**2. Prosecution Quality Assessment**
- Citation thoroughness vs petition filing correlation
- Examiner search quality indicators
- Art unit citation norms comparison

**3. PTAB Vulnerability Scoring**
- Citation patterns indicating search quality
- Prior art gaps exploitable in IPR
- Examiner citation selectivity metrics

**4. Claim Construction Intelligence**
- Examiner's interpretation from NOA documents
- Citation context for claim amendments
- Prosecution estoppel evidence from file history

**5. Litigation Strategy**
- Complete prosecution history for expert analysis
- PTAB estoppel implications
- Prior art mapping for invalidity contentions

### Token Efficiency for Complete Workflow

**Without Optimization**:
- PTAB: 10 proceedings × full metadata = ~100KB
- PFW: 50 docs × full metadata = ~500KB
- Citations: 100 results × full metadata = ~200KB
- FPD: 10 petitions × full metadata = ~100KB
- **Total: ~900KB**

**With Ultra-Minimal Optimization**:
- PTAB: 10 proceedings × minimal = ~15KB
- PFW: 50 docs × 3 custom fields = ~10KB
- Citations: 100 results × 3 custom fields = ~30KB
- FPD: 10 petitions × 3 custom fields = ~10KB
- **Total: ~65KB (93% reduction)**"""


def _get_tools_section() -> str:
    """Tool usage and progressive disclosure"""
    return """## Core Tools Overview

### Search Tools (Progressive Disclosure)

**Trials Search (3 tiers)**:

**search_trials_minimal** - Trial Discovery
- **Purpose**: Fast trial discovery with essential fields (68% context reduction)
- **Use Cases**: Initial research, portfolio screening, patent-to-trial mapping
- **Fields**: 10-15 core identifiers and metadata
- **Recommended**: 50-100 results for discovery workflow
- **Custom Fields**: Supports ultra-minimal mode (2-3 fields, 99% reduction)

**search_trials_balanced** - Detailed Analysis
- **Purpose**: Comprehensive trial analysis after selection (13.5% context reduction)
- **Use Cases**: Strategy development, claim mapping, outcome analysis
- **Fields**: 30-50 fields with complete party/decision data
- **Recommended**: 10-20 results for detailed analysis
- **Custom Fields**: Supports ultra-minimal mode (2-3 fields, 99% reduction)

**search_trials_complete** - Full Metadata
- **Purpose**: Complete trial data for archival or export
- **Use Cases**: Data export, comprehensive archival, full metadata needs
- **Fields**: ~80-120 fields (all available)
- **Use Sparingly**: High token cost
- **Custom Fields**: Supports ultra-minimal mode (2-3 fields, 99% reduction)

**Appeals Search (3 tiers)**:
- search_appeals_minimal (discovery)
- search_appeals_balanced (analysis)
- search_appeals_complete (full metadata)

**Interferences Search (3 tiers)**:
- search_interferences_minimal (discovery)
- search_interferences_balanced (analysis)
- search_interferences_complete (full metadata)

### Document Tools

**ptab_get_documents** - Document List
- **Purpose**: Get list of all documents for trial/appeal/interference
- **Use Cases**: Document discovery, selective download planning
- **Returns**: Grouped by type (Petitions, Responses, Decisions, Motions, Exhibits)
- **Supports**: trials, appeals, interferences (via identifier_type parameter)

**ptab_get_document_download** - Browser Access
- **Purpose**: Generate secure browser-accessible download URLs
- **Use Cases**: User downloads documents directly in browser
- **Format**: **[Download {Type} ({Pages} pages)]({url})** | Raw URL: `{url}`
- **Proxy**: Centralized (8080) or local (8083) with automatic fallback

**ptab_get_document_content** - LLM Analysis
- **Purpose**: Extract text from documents for LLM analysis
- **Use Cases**: Answer questions about decisions, analyze reasoning
- **Method**: Hybrid extraction (PyPDF2 → Mistral OCR → Docling for short docs)
- **Cost**: ~$0.15 per 1M input tokens (Mistral OCR); PyPDF2 and Docling are free
- **Docling gate**: only documents ≤ DOCLING_MAX_PAGES (default 20) use Docling

### Utility Tools

**ptab_get_field_configs** - View Configuration
- **Purpose**: View current field configuration from YAML
- **Use Cases**: Understand available fields, customize configuration

**ptab_get_guidance** - Selective Guidance
- **Purpose**: Get targeted guidance (90-95% context reduction)
- **Sections**: fields, documents, workflows_pfw, workflows_fpd, workflows_citations,
               workflows_pinecone, workflows_complete, tools, errors, cost

### Progressive Disclosure Strategy

**Stage 1: Discovery (Minimal Search)**
- Use `search_trials_minimal` for broad exploration
- 10-15 preset fields OR 2-3 custom fields
- Present top results to user for selection
- ~40KB for 50 trials (preset) or ~5KB (custom)

**Stage 2: Analysis (Balanced Search)**
- Use `search_trials_balanced` for selected trials
- 30-50 comprehensive fields
- Detailed analysis for critical trials
- ~25KB for 20 trials

**Stage 3: Documents (Document Tools)**
- Use `ptab_get_documents` for document lists
- Use `ptab_get_document_download` for browser access
- Use `ptab_get_document_content` for LLM analysis
- Only download/extract documents as needed

### Tool Selection Decision Tree

```
User Query → Broad discovery?
    ├─ YES → search_trials_minimal (50-100 results)
    │         Present to user → User selects → search_trials_balanced
    │
    └─ NO → Specific trial known?
            ├─ YES → search_trials_balanced (trial_number='IPR2024-00123')
            │         Need documents? → ptab_get_documents
            │
            └─ NO → Need documents only?
                    └─ YES → ptab_get_documents → ptab_get_document_download
```

### Common Query Patterns

**Portfolio Screening**:
```python
search_trials_minimal(
    petitioner_name='Apple Inc',
    filing_date_from='2024-01-01',
    fields=['trialNumber', 'patentOwnerData.patentNumber', 'trialMetaData.trialStatusCategory'],
    limit=100
)
```

**Specific Trial Analysis**:
```python
search_trials_balanced(
    trial_number='IPR2024-00123',
    limit=1
)
```

**Patent Challenge Research**:
```python
search_trials_minimal(
    patent_number='8524787',
    limit=20
)
```"""


def _get_errors_section() -> str:
    """Common error patterns and troubleshooting"""
    return """## Common Errors and Troubleshooting

### Validation Errors

**Error**: "Invalid trial number format"

**Cause**: Trial number doesn't match expected pattern

**Solution**:
```python
# Valid formats:
# - IPR2024-00123 (Inter Partes Review)
# - PGR2025-00045 (Post-Grant Review)
# - CBM2023-00001 (Covered Business Method)
# - DER2024-00001 (Derivation)
```

**Error**: "Invalid patent number format"

**Cause**: Patent number format not recognized

**Solution**:
```python
# Valid formats:
# - 8524787 (numeric only)
# - US8524787 (with country code)
# - US-8524787-B2 (full format)

# Remove extra characters:
patent_num = patent_num.replace('US', '').replace('-', '').replace('B2', '')
```

**Error**: "Invalid date range"

**Cause**: Date format incorrect or end date before start date

**Solution**:
```python
# Use YYYY-MM-DD format:
search_trials_minimal(
    filing_date_from='2024-01-01',  # ✅ Correct
    filing_date_to='2024-12-31'
)

# NOT:
# filing_date_from='01/01/2024'  # ❌ Wrong format
# filing_date_from='2024-12-31', filing_date_to='2024-01-01'  # ❌ Reversed
```

### API Errors

**Error**: "API rate limit exceeded"

**Cause**: Too many requests in short period

**Solution**:
- Reduce request frequency
- Use batch queries instead of individual lookups
- Implement exponential backoff for retries

**Error**: "No results found"

**Causes**:
1. Trial/patent doesn't exist
2. Filters too restrictive
3. Date range outside data coverage

**Debugging**:
```python
# Start broad, then narrow:

# Step 1: Check if trial exists
result1 = search_trials_minimal(
    trial_number='IPR2024-00123',
    limit=1
)

# Step 2: If no results, check patent
result2 = search_trials_minimal(
    patent_number='8524787',
    limit=10
)

# Step 3: If still no results, check date range
result3 = search_trials_minimal(
    patent_number='8524787',
    filing_date_from='2020-01-01',  # Broaden date range
    limit=10
)
```

### Document Errors

**Error**: "Document not found"

**Cause**: Invalid document_id or identifier

**Solution**:
```python
# ALWAYS use ptab_get_documents first:
docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial'
)

# Then use document_id from response:
download = ptab_get_document_download(
    identifier='IPR2024-00123',
    identifier_type='trial',
    document_id=docs['documents'][0]['documentIdentifier']  # From response
)
```

**Error**: "Proxy not responding"

**Cause**: Proxy server not started or port conflict

**Solution**:
- Check PTAB_PROXY_PORT environment variable
- Verify no port conflicts (ports 8080, 8083)
- Check ENABLE_ALWAYS_ON_PROXY setting
- Review proxy logs for errors

### Field Configuration Errors

**Error**: "Invalid field name"

**Cause**: Field doesn't exist in API schema

**Solution**:
```python
# Check available fields:
configs = ptab_get_field_configs()

# Use dot notation for nested fields:
fields=['trialNumber', 'trialMetaData.accordedFilingDate']  # ✅ Correct
fields=['trialNumber', 'accordedFilingDate']  # ❌ Wrong (missing parent)
```

**Error**: "documentBag fields forbidden"

**Cause**: Trying to request document fields in search

**Solution**:
```python
# ❌ WRONG:
search_trials_minimal(
    trial_number='IPR2024-00123',
    fields=['trialNumber', 'documentBag.documentIdentifier']  # Forbidden!
)

# ✅ CORRECT:
search_trials_minimal(
    trial_number='IPR2024-00123',
    fields=['trialNumber']
)

# Get documents separately:
docs = ptab_get_documents(
    identifier='IPR2024-00123',
    identifier_type='trial'
)
```

### Cross-MCP Integration Errors

**Error**: "Application number not found" (PFW integration)

**Cause**: Patent issued before PFW data coverage or format mismatch

**Solution**:
```python
# Try multiple formats:
formats = ['14171705', '14/171,705', '14171705']

for app_num in formats:
    result = pfw_search_applications_minimal(
        application_number=app_num,
        limit=1
    )
    if 'error' not in result and result['count'] > 0:
        break
```

**Error**: "Citation data not available" (Citations integration)

**Cause**: Office action dates before 2017-10-01

**Solution**:
```python
# Citations API only has data from 2017-10-01 onward
# For older patents, rely on PFW prosecution history

# Check filing date first:
if filing_date < '2015-01-01':
    print("Patent likely too old for citation data (2017+ coverage)")
    # Use PFW prosecution history instead
```

### Empty Results Debugging

**Step 1**: Verify identifier exists
```python
result = search_trials_minimal(trial_number='IPR2024-00123', limit=1)
if result['count'] == 0:
    print("Trial not found - check number format")
```

**Step 2**: Broaden search criteria
```python
# Remove date filters
result = search_trials_minimal(patent_number='8524787', limit=10)
```

**Step 3**: Check data type
```python
# Maybe it's an appeal or interference, not trial?
result = search_appeals_minimal(appeal_number='2024-001234', limit=1)
```"""


def _get_cost_section() -> str:
    """Cost optimization strategies"""
    return """## Cost Optimization Strategies

### Token Efficiency Hierarchy

**Level 1: Ultra-Minimal Mode (99% reduction)**
```python
# 2-3 custom fields for frequency/discovery
search_trials_minimal(
    petitioner_name='Apple Inc',
    fields=['trialNumber', 'patentOwnerData.patentNumber'],
    limit=100
)
# Token cost: ~5KB (vs ~40KB preset minimal, ~500KB full data)
```

**Level 2: Preset Minimal (68% reduction)**
```python
# 10-15 preset fields for discovery
search_trials_minimal(
    petitioner_name='Apple Inc',
    limit=100
)
# Token cost: ~40KB (vs ~125KB balanced)
```

**Level 3: Preset Balanced (13.5% reduction)**
```python
# 30-50 preset fields for analysis
search_trials_balanced(
    trial_number='IPR2024-00123',
    limit=20
)
# Token cost: ~25KB (vs ~29KB complete)
```

**Level 4: Complete (0% reduction)**
```python
# ~80-120 fields for archival
search_trials_complete(
    trial_number='IPR2024-00123',
    limit=1
)
# Token cost: ~29KB per trial
# Use sparingly!
```

### Progressive Disclosure Workflow

**Stage 1: Discovery (Ultra-Minimal)**
- Use 2-3 custom fields
- High volume (50-100 results)
- Identify candidates
- Cost: ~5-10KB

**Stage 2: Selection (Preset Minimal)**
- Use preset minimal (10-15 fields)
- Present to user for selection
- Cost: ~40KB

**Stage 3: Analysis (Preset Balanced)**
- Use preset balanced (30-50 fields)
- Medium volume (10-20 results)
- Detailed analysis of selections
- Cost: ~25KB

**Stage 4: Documents (On-Demand)**
- Only download/extract as needed
- Cost: OCR ~$0.15 per 1M tokens

**Total Cost: ~70KB vs 500KB+ without optimization (86% savings)**

### Cross-MCP Optimization

**PTAB + PFW Integration**:
```python
# Ultra-efficient workflow
# STEP 1: PTAB discovery (2 fields only)
ptab_trials = search_trials_minimal(
    petitioner_name='Apple Inc',
    fields=['trialNumber', 'patentOwnerData.patentNumber'],
    limit=50
)
# Cost: ~5KB

# STEP 2: PFW correlation (1 field only)
for trial in ptab_trials['results'][:20]:  # Limit to top 20
    patent_num = trial['patentOwnerData']['patentNumber']

    pfw_app = pfw_search_applications_minimal(
        query=f'patentNumber:{patent_num}',
        fields=['applicationNumberText'],
        limit=1
    )
# Cost: ~2KB for 20 lookups

# Total: ~7KB vs ~300KB without optimization (98% savings)
```

**PTAB + Citations Integration**:
```python
# STEP 1: PTAB minimal search
ptab_trials = search_trials_minimal(
    patent_number='8524787',
    fields=['trialNumber', 'patentOwnerData.patentNumber'],
    limit=10
)
# Cost: ~1KB

# STEP 2: Citations ultra-minimal
citations = search_citations_minimal(
    criteria='publicationNumber:8524787 AND officeActionDate:[2017-10-01 TO *]',
    fields=['citationCategoryCode', 'examinerCitedReferenceIndicator'],
    rows=100
)
# Cost: ~10KB

# Total: ~11KB vs ~250KB without optimization (96% savings)
```

### Document Cost Optimization

**Download vs Extract Decision Tree**:

```
User needs document → User will read it themselves?
    ├─ YES → ptab_get_document_download (browser access)
    │         Cost: Free (proxy only)
    │
    └─ NO → LLM needs to analyze?
            └─ YES → ptab_get_document_content (OCR extraction)
                      Cost: ~$0.15 per 1M tokens (Mistral OCR)

                      → Extract only if absolutely necessary
                      → Limit to 1-3 documents per query
                      → Use download for user review instead
```

**OCR Cost Examples**:
- Final Written Decision (45 pages): ~$0.01-0.02
- Petition (100 pages): ~$0.02-0.04
- Complete docket (500 pages): ~$0.10-0.15

**Cost Savings Strategy**:
- Download for user review (free)
- Extract only for LLM analysis (paid)
- Limit extractions to 1-3 critical documents

### Result Limiting Best Practices

**Discovery Queries**:
- Minimal tier: limit=50-100
- Balanced tier: limit=10-20
- Complete tier: limit=1-5

**Cross-MCP Integration**:
- Limit to top 20 items to prevent token explosion
- Use pagination for large datasets

**Document Operations**:
- List all documents (free)
- Download links for all (free)
- Extract content for 1-3 only (paid)

### Query Optimization

**Efficient Query Patterns**:
```python
# ✅ GOOD: Specific filters with custom fields
search_trials_minimal(
    trial_number='IPR2024-00123',
    fields=['trialNumber', 'trialMetaData.trialStatusCategory'],
    limit=1
)

# ⚠️ OKAY: Broader search with preset minimal
search_trials_minimal(
    petitioner_name='Apple Inc',
    limit=50
)

# ❌ AVOID: Broad search with balanced/complete
search_trials_balanced(
    trial_type='IPR',
    limit=100
)  # Expensive!
```

### Summary

**Token Reduction Potential**:
- Ultra-minimal mode: **99% reduction** (2-3 custom fields)
- Preset minimal: **68% reduction** (10-15 fields)
- Preset balanced: **13.5% reduction** (30-50 fields)

**Cost Optimization Formula**:
1. Start with ultra-minimal discovery (2-3 custom fields)
2. Filter results to top candidates
3. Escalate to preset minimal for presentation (10-15 fields)
4. Use preset balanced only for final selections (30-50 fields)
5. Download documents for user review (free)
6. Extract content only when LLM analysis required (paid)

**Typical Workflow Costs**:
- Without optimization: ~500KB-1MB tokens
- With optimization: ~50-100KB tokens
- **Savings: 90-95%**"""


def get_guidance_section(section: str) -> str:
    """
    Get specific guidance section for context-efficient access.

    Returns clean markdown string (NOT dict/JSON).
    CRITICAL: NO json.dumps() - causes escaping issues.

    Args:
        section: One of: overview, fields, documents, workflows_pfw, workflows_fpd,
                workflows_citations, workflows_pinecone, workflows_complete,
                tools, errors, cost

    Returns:
        str: Markdown-formatted guidance for requested section only
    """
    sections = {
        "overview": _get_overview_section,
        "fields": _get_fields_section,
        "documents": _get_documents_section,
        "workflows_pfw": _get_workflows_pfw_section,
        "workflows_fpd": _get_workflows_fpd_section,
        "workflows_citations": _get_workflows_citations_section,
        "workflows_pinecone": _get_workflows_pinecone_section,
        "workflows_complete": _get_workflows_complete_section,
        "tools": _get_tools_section,
        "errors": _get_errors_section,
        "cost": _get_cost_section,
    }

    if section not in sections:
        available = ", ".join(sorted(sections.keys()))
        return f"""## Error: Unknown Section

**Requested**: {section}

**Available sections**: {available}

**Usage**: ptab_get_guidance(section='workflows_pfw')

**Quick reference**: Use ptab_get_guidance(section='overview') to see available sections and quick reference chart."""

    # Return markdown directly (NO json.dumps!)
    return sections[section]()


def get_all_guidance() -> str:
    """
    Get complete tool reflections and guidance (legacy compatibility).

    DEPRECATION NOTICE: This function returns all guidance at once (~70KB).
    For 90-95% token reduction, use ptab_get_guidance(section) instead.

    Returns:
        str: Complete guidance markdown
    """
    return """# USPTO PTAB MCP - Complete Tool Guidance

⚠️ DEPRECATION NOTICE: This function returns all guidance at once (~70KB).
For 90-95% token reduction, use `ptab_get_guidance(section)` instead.

Use `ptab_get_guidance("overview")` to see available sections and quick reference chart.

""" + _get_overview_section()
