"""Prior Art Board Decision Mining Prompt

Extract prior art references from Final Written Decisions
"""

from . import mcp


@mcp.prompt(
    name="prior_art_board_decision_mining",
    description="Extract prior art from PTAB Final Written Decisions in technology area. tech_center: Technology center (required). filing_year_from/to: Optional date range. limit: Max trials (default 20).",
)
async def prior_art_board_decision_mining_prompt(
    tech_center: str = "",
    filing_year_from: str = "",
    filing_year_to: str = "",
    limit: str = "20"
) -> str:
    """Extract prior art references from Final Written Decisions.

    Args:
        tech_center: Technology center number (e.g., '2600')
        filing_year_from: Start year (YYYY)
        filing_year_to: End year (YYYY)
        limit: Maximum trials to analyze (default 20)
    """

    if not tech_center:
        return """
# PRIOR ART BOARD DECISION MINING

ERROR: Missing Required Parameter

Please provide:
- tech_center: Technology center number (e.g., '2600' for communications)

Optional Parameters:
- filing_year_from: Start year (YYYY)
- filing_year_to: End year (YYYY)
- limit: Maximum trials to analyze (default 20)

Example Usage:
```
tech_center='2600'
filing_year_from='2022'
filing_year_to='2024'
limit='20'
```
"""

    return f"""
# PRIOR ART BOARD DECISION MINING

Technology Center: {tech_center}
Date Range: {filing_year_from or 'Any'} to {filing_year_to or 'Any'}
Analysis Limit: {limit} trials

## Step 1: Find Trials with Final Written Decisions

```python
# Search for trials in technology area
search_params = {{
    'tech_center': '{tech_center}',
    'trial_status': 'Terminated',  # FWDs only issued for terminated trials
    'limit': {limit}
}}

if '{filing_year_from}' and '{filing_year_to}':
    search_params['filing_date_from'] = '{filing_year_from}-01-01'
    search_params['filing_date_to'] = '{filing_year_to}-12-31'

trials = PTAB_search_trials_minimal(**search_params)

print(f"Found {{trials['count']}} terminated trials in TC {tech_center}")
```

## Step 2: Extract Final Written Decisions

```python
# Collect FWDs from each trial
fwd_documents = []

for trial in trials['results'][:int('{limit}')]:
    trial_num = trial.get('trialNumber')

    # Get documents for this trial
    docs = PTAB_get_documents(
        identifier=trial_num,
        identifier_type='trial'
    )

    # Find Final Written Decisions
    for doc in docs.get('documents', []):
        if 'Final Written Decision' in doc.get('documentTypeDescriptionText', ''):
            fwd_documents.append({{
                'trial_number': trial_num,
                'document_id': doc.get('documentIdentifier'),
                'filing_date': doc.get('filingDate'),
                'page_count': doc.get('pageCount'),
                'patent_number': trial.get('patentOwnerData', {{}}).get('patentNumber')
            }})

print(f"\\nExtracted {{len(fwd_documents)}} Final Written Decisions")
```

## Step 3: Extract Text and Mine Prior Art (Selective)

```python
# SAFETY RAIL: Limit OCR to first 5 documents (keeps extraction time
# and context size manageable — each FWD is ~45 pages of full text)

from collections import Counter
prior_art_refs = []

for i, fwd in enumerate(fwd_documents[:5]):  # LIMIT TO 5 (SAFETY RAIL)
    print(f"\\nAnalyzing FWD {{i+1}}/5: {{fwd['trial_number']}}")

    # Extract text content
    content = PTAB_get_document_content(
        document_id=fwd['document_id'],
        identifier=fwd['trial_number'],
        identifier_type='trial'
    )

    text = content.get('text', '')
    method = content.get('extraction_method')

    print(f"  Extraction: {{method}}")

    # Simple prior art extraction (look for common patterns)
    # NOTE: This is simplified - production would use LLM for better extraction
    lines = text.split('\\n')
    for line in lines:
        if 'U.S. Patent' in line or 'Publication' in line:
            # Extract patent/publication numbers
            import re
            patents = re.findall(r'\\b\\d{{1,2}},\\d{{3}},\\d{{3}}\\b', line)
            for patent in patents:
                prior_art_refs.append({{
                    'patent_number': patent.replace(',', ''),
                    'trial': fwd['trial_number'],
                    'context': line[:100]
                }})

print(f"\\nTotal prior art references extracted: {{len(prior_art_refs)}}")
```

## Step 4: Prior Art Summary and Downloads

```python
# Aggregate results
from collections import Counter
patent_citations = Counter([ref['patent_number'] for ref in prior_art_refs])

print("\\n=== PRIOR ART INTELLIGENCE ===")
print(f"Total FWDs Analyzed: {{len(fwd_documents)}}")
print(f"Text Extracted from: 5 FWDs (safety limit)")
print(f"Prior Art References Found: {{len(prior_art_refs)}}")
print(f"\\nMost Cited Patents:")
for patent, count in patent_citations.most_common(10):
    print(f"  {{patent}}: {{count}} citations")

print("\\n=== FWD DOWNLOAD LINKS ===")
for fwd in fwd_documents[:10]:  # Provide links to first 10
    download = PTAB_get_document_download(
        document_id=fwd['document_id'],
        identifier=fwd['trial_number'],
        identifier_type='trial'
    )
    url = download.get('proxy_url') or download.get('download_url')
    print(f"**[Download {{fwd['trial_number']}} FWD ({{fwd['page_count']}} pages)]({{url}})** | Raw URL: `{{url}}`")
```

## Expected Results

1. Final Written Decisions - 10-20 FWDs from technology area
2. Prior Art References - Extracted patent numbers and context
3. Citation Analysis - Most frequently cited patents
4. Download Links - Access to all FWDs for manual review

Use Case: Prior art landscape research, competitive intelligence, examiner citation patterns.

SAFETY NOTE: OCR limited to 5 documents per run. For larger analysis, download PDFs and use external tools.
"""
