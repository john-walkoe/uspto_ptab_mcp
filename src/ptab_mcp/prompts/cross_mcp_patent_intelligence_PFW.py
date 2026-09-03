"""Cross-MCP Patent Intelligence Prompt (PTAB + PFW)

Complete patent intelligence package combining PTAB and prosecution data
"""

from . import mcp


@mcp.prompt(
    name="cross_mcp_patent_intelligence_PFW",
    description="Complete intelligence package for patent. patent_number: Patent number (required). include_family: Include related trials (true/false).",
)
async def cross_mcp_patent_intelligence_pfw_prompt(
    patent_number: str = "",
    include_family: str = "false"
) -> str:
    """Complete patent intelligence combining PTAB and prosecution.

    Args:
        patent_number: Patent number (required)
        include_family: Include related patent trials ('true'/'false')
    """

    if not patent_number:
        return """
# CROSS-MCP PATENT INTELLIGENCE

ERROR: Missing Required Parameter

Please provide:
- patent_number: Patent number (e.g., '7883848')

Optional:
- include_family: Include related patent trials ('true'/'false', default 'false')

Example Usage:
```
patent_number='7883848'
include_family='true'
```
"""

    return f"""
# CROSS-MCP PATENT INTELLIGENCE

Patent Number: {patent_number}
Include Family Trials: {include_family}

## Step 1: Prosecution History (PFW)

```python
print("=== PROSECUTION HISTORY (PFW) ===")

pfw_data = PFW_search_applications_balanced(
    patent_number='{patent_number}',
    limit=1
)

if pfw_data.get('count', 0) > 0:
    app = pfw_data['results'][0]
    print(f"Application Number: {{app.get('applicationNumber')}}")
    print(f"Filing Date: {{app.get('filingDate')}}")
    print(f"Issue Date: {{app.get('patentIssueDate')}}")
    print(f"Assignee: {{app.get('assigneeName', 'N/A')}}")
    print(f"Examiner: {{app.get('examinerName', 'N/A')}}")
    print(f"Art Unit: {{app.get('artUnit', 'N/A')}}")

    # Document inventory only. For office-action SUBSTANCE use the direct OA
    # tools instead: PFW_get_oa_rejections (structured, OAs mailed Oct 1 2017 to
    # ~30 days ago) then PFW_get_oa_text (the examiner's words, OAs mailed
    # roughly 2008 onward — a decade deeper, so an empty rejections result is
    # not evidence the text is missing). The bag can return HTTP 403 on some
    # older applications; that is not a reason to stop.
    docs = PFW_get_application_documents(
        app_number=app.get('applicationNumber'),
        limit=20
    )
    print(f"\\nProsecution Documents: {{docs.get('count', 0)}}")
```

## Step 2: PTAB Challenge History

```python
print("\\n=== PTAB CHALLENGE HISTORY ===")

trials = PTAB_search_trials_minimal(
    patent_number='{patent_number}',
    limit=50
)

print(f"PTAB Trials: {{trials['count']}}")

if trials['count'] > 0:
    for i, trial in enumerate(trials['results']):
        print(f"\\nTrial {{i+1}}: {{trial.get('trialNumber')}}")
        print(f"  Petitioner: {{trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName')}}")
        print(f"  Status: {{trial.get('trialMetaData', {{}}).get('trialStatusCategory')}}")
        print(f"  Filing: {{trial.get('trialMetaData', {{}}).get('accordedFilingDate')}}")

        # Get key documents
        trial_docs = PTAB_get_documents(
            identifier=trial.get('trialNumber'),
            identifier_type='trial'
        )

        fwd_count = sum(1 for d in trial_docs.get('documents', [])
                        if 'Final Written Decision' in d.get('documentTypeDescriptionText', ''))
        print(f"  Documents: {{trial_docs.get('document_count', 0)}} (FWDs: {{fwd_count}})")
```

## Step 3: Download Package

```python
print("\\n=== INTELLIGENCE PACKAGE DOWNLOADS ===")

# PFW Documents
if pfw_data.get('count', 0) > 0:
    app_num = pfw_data['results'][0].get('applicationNumber')

    # Get Notice of Allowance
    noa_docs = PFW_get_application_documents(
        app_number=app_num,
        document_code='NOA',
        limit=1
    )

    if noa_docs.get('count', 0) > 0:
        noa = noa_docs['documentBag'][0]
        download = PFW_get_document_download(
            app_number=app_num,
            document_id=noa.get('documentIdentifier')
        )
        url = download.get('proxy_url') or download.get('download_url')
        print(f"\\n**[Download Notice of Allowance (PFW)]({{url}})** | Raw URL: `{{url}}`")

# PTAB Documents
if trials['count'] > 0:
    trial_num = trials['results'][0].get('trialNumber')
    trial_docs = PTAB_get_documents(identifier=trial_num, identifier_type='trial')

    for doc in trial_docs.get('documents', [])[:3]:
        if 'Decision' in doc.get('documentTypeDescriptionText', ''):
            download = PTAB_get_document_download(
                document_id=doc.get('documentIdentifier'),
                identifier=trial_num,
                identifier_type='trial'
            )
            url = download.get('proxy_url') or download.get('download_url')
            desc = doc.get('documentTypeDescriptionText')
            pages = doc.get('pageCount', 'Unknown')
            print(f"\\n**[Download {{desc}} (PTAB, {{pages}} pages)]({{url}})** | Raw URL: `{{url}}`")
```

## Step 4: Intelligence Summary

```python
print("\\n=== INTELLIGENCE SUMMARY ===")
print(f"Patent: {patent_number}")
print(f"\\nProsecution Status:")
print(f"  - Application: {{pfw_data['results'][0].get('applicationNumber') if pfw_data.get('count', 0) > 0 else 'N/A'}}")
print(f"  - Status: Patented")
print(f"\\nPTAB Status:")
print(f"  - Total Challenges: {{trials['count']}}")
if trials['count'] > 0:
    from collections import Counter
    statuses = Counter(t.get('trialMetaData', {{}}).get('trialStatusCategory') for t in trials['results'])
    print(f"  - Active Trials: {{statuses.get('Instituted', 0)}}")
    print(f"  - Terminated: {{statuses.get('Terminated', 0)}}")
print(f"\\nRecommendation: Review all downloaded documents for complete intelligence package")
```

## Expected Results

1. Prosecution Intelligence - Complete application history from PFW
2. PTAB Challenge Status - All trials and current status
3. Document Package - Key documents from both prosecution and PTAB
4. Strategic Summary - Complete patent lifecycle intelligence

Cross-MCP Integration: Complete intelligence from PFW prosecution + PTAB challenges.
"""
