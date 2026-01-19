"""Complete Trial Litigation Package Prompt

Download complete PTAB trial docket for litigation preparation
"""

from . import mcp


@mcp.prompt(
    name="complete_trial_litigation_package",
    description="Download complete PTAB trial docket with all documents. trial_number: PTAB trial number (required, e.g., 'IPR2024-00123').",
)
async def complete_trial_litigation_package_prompt(trial_number: str = "") -> str:
    """Download complete PTAB trial docket for litigation preparation.

    Args:
        trial_number: PTAB trial number (e.g., 'IPR2024-00123')
    """

    if not trial_number:
        return """
# COMPLETE TRIAL LITIGATION PACKAGE

ERROR: Missing Required Parameter

Please provide:
- trial_number: PTAB trial number (e.g., 'IPR2024-00123', 'PGR2025-00045')

Example Usage:
```
trial_number='IPR2024-00123'
```
"""

    return f"""
# COMPLETE TRIAL LITIGATION PACKAGE

Trial Number: {trial_number}

## Step 1: Get Trial Overview

```python
# Get comprehensive trial data
trial_data = search_trials_balanced(
    trial_number='{trial_number}',
    limit=1
)

if trial_data['count'] == 0:
    print("ERROR: Trial number not found")
else:
    trial = trial_data['results'][0]

    print("=== TRIAL OVERVIEW ===")
    print(f"Trial Number: {{trial.get('trialNumber')}}")
    print(f"Type: {{trial.get('trialMetaData', {{}}).get('trialTypeCode')}}")
    print(f"Status: {{trial.get('trialMetaData', {{}}).get('trialStatusCategory')}}")
    print(f"\\nPetitioner: {{trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName')}}")
    print(f"Patent Owner: {{trial.get('patentOwnerData', {{}}).get('patentOwnerName')}}")
    print(f"Patent Number: {{trial.get('patentOwnerData', {{}}).get('patentNumber')}}")
    print(f"Filing Date: {{trial.get('trialMetaData', {{}}).get('accordedFilingDate')}}")
```

## Step 2: Get Complete Document List

```python
# Retrieve all documents in trial
docs_result = ptab_get_documents(
    identifier='{trial_number}',
    identifier_type='trial'
)

documents = docs_result.get('documents', [])
print(f"\\n=== DOCUMENT INVENTORY ===")
print(f"Total Documents: {{len(documents)}}")

# Group by document type
from collections import defaultdict
docs_by_type = defaultdict(list)

for doc in documents:
    doc_type = doc.get('documentDescription', 'Unknown')
    # Categorize
    if 'Petition' in doc_type:
        category = 'Petitions'
    elif 'Response' in doc_type or 'Reply' in doc_type:
        category = 'Responses'
    elif 'Decision' in doc_type or 'Order' in doc_type:
        category = 'Decisions/Orders'
    elif 'Motion' in doc_type:
        category = 'Motions'
    elif 'Exhibit' in doc_type:
        category = 'Exhibits'
    else:
        category = 'Other'

    docs_by_type[category].append(doc)

# Display inventory
for category, cat_docs in sorted(docs_by_type.items()):
    print(f"\\n{{category}}: {{len(cat_docs)}} documents")
    for doc in cat_docs[:5]:  # Show first 5
        print(f"  - {{doc.get('documentDescription')}} ({{doc.get('filingDate', 'N/A')}})")
```

## Step 3: Generate Download Links for All Documents

```python
# Priority documents for litigation
priority_types = [
    'Final Written Decision',
    'Institution Decision',
    'Patent Owner Preliminary Response',
    'Patent Owner Response',
    'Petitioner Reply',
    'Petition'
]

print("\\n=== PRIORITY DOCUMENT DOWNLOADS ===")

for doc in documents:
    doc_desc = doc.get('documentDescription', '')

    # Check if priority document
    is_priority = any(ptype in doc_desc for ptype in priority_types)

    if is_priority:
        doc_id = doc.get('documentIdentifier')
        page_count = doc.get('pageCount', 'Unknown')

        # Generate download link
        download = ptab_get_document_download(
            document_id=doc_id,
            identifier='{trial_number}',
            identifier_type='trial'
        )

        proxy_url = download.get('proxy_url') or download.get('download_url')

        # Format with BOTH clickable link and raw URL
        print(f"**[Download {{doc_desc}} ({{page_count}} pages)]({{proxy_url}})** | Raw URL: `{{proxy_url}}`")

print("\\n=== ALL DOCUMENT DOWNLOADS ===")
print(f"Total documents available: {{len(documents)}}")
print("Note: Request individual downloads for non-priority documents to manage download volume")
```

## Step 4: Litigation Package Summary

```python
print("\\n=== LITIGATION PACKAGE SUMMARY ===")
print(f"Trial: {trial_number}")
print(f"Total Documents: {{len(documents)}}")
print(f"Priority Downloads: {{sum(1 for d in documents if any(p in d.get('documentDescription', '') for p in priority_types))}}")
print("\\nPackage Contents:")
print("1. Trial Overview - Complete metadata")
print("2. Document Inventory - All filings categorized")
print("3. Priority Downloads - Key decisions and responses")
print("4. Download Links - Browser-accessible PDFs")
print("\\nAll download links valid for 7 days - review in any browser")
```

## Expected Results

1. Trial Overview - Complete trial metadata and party information
2. Document Inventory - All documents categorized by type
3. Priority Downloads - Clickable links for key litigation documents
4. Complete Docket - Full access to all trial filings

Use Case: Litigation preparation, estoppel analysis, strategic review of PTAB proceedings.
"""
