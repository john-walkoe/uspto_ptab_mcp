"""IPR Challenge Defense Strategy Prompt (Cross-MCP: PTAB + PFW)

IPR defense strategy combining PTAB trial data with prosecution history
"""

from . import mcp


@mcp.prompt(
    name="ipr_challenge_defense_PFW",
    description="IPR defense strategy with prosecution history. patent_number: Patent being challenged (required). application_number: Optional prosecution context.",
)
async def ipr_challenge_defense_pfw_prompt(
    patent_number: str = "",
    application_number: str = ""
) -> str:
    """IPR defense strategy combining PTAB and prosecution history.

    Args:
        patent_number: Patent number being challenged (required)
        application_number: Application number for prosecution context (optional)
    """

    if not patent_number:
        return """
# IPR CHALLENGE DEFENSE STRATEGY

ERROR: Missing Required Parameter

Please provide:
- patent_number: Patent number being challenged (e.g., '7883848')

Optional:
- application_number: Application number for prosecution history (e.g., '14/171,705')

Example Usage:
```
patent_number='7883848'
application_number='14/171,705'
```
"""

    return f"""
# IPR CHALLENGE DEFENSE STRATEGY

Patent Number: {patent_number}
Application Number: {application_number or 'Not provided - will search'}

## Step 1: Find All PTAB Challenges to This Patent

```python
# Search for all IPR/PGR trials involving this patent
trials = PTAB_search_trials_minimal(
    patent_number='{patent_number}',
    limit=50
)

print(f"=== PTAB CHALLENGE LANDSCAPE ===")
print(f"Total Challenges Found: {{trials['count']}}")

if trials['count'] == 0:
    print("No PTAB challenges found for this patent")
else:
    for i, trial in enumerate(trials['results']):
        print(f"\\nChallenge {{i+1}}:")
        print(f"  Trial: {{trial.get('trialNumber')}}")
        print(f"  Petitioner: {{trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName')}}")
        print(f"  Status: {{trial.get('trialMetaData', {{}}).get('trialStatusCategory')}}")
        print(f"  Filing Date: {{trial.get('trialMetaData', {{}}).get('accordedFilingDate')}}")
```

## Step 2: Get Prosecution History (PFW Integration)

```python
# If application number not provided, try to find it
app_num = '{application_number}'

if not app_num:
    # Search PFW by patent number
    try:
        pfw_results = PFW_search_applications_minimal(
            patent_number='{patent_number}',
            limit=1
        )
        if pfw_results.get('count', 0) > 0:
            app_num = pfw_results['results'][0].get('applicationNumber')
            print(f"\\n Found application number from PFW: {{app_num}}")
    except Exception as e:
        print(f"\\nWARNING: Could not retrieve prosecution history: {{e}}")

# Get prosecution history if available
if app_num:
    print("\\n=== PROSECUTION HISTORY ===")
    try:
        app_data = PFW_search_applications_balanced(
            application_number=app_num,
            limit=1
        )

        if app_data.get('count', 0) > 0:
            app = app_data['results'][0]
            print(f"Application: {{app.get('applicationNumber')}}")
            print(f"Filing Date: {{app.get('filingDate')}}")
            print(f"Patent Issue Date: {{app.get('patentIssueDate')}}")
            print(f"Examiner: {{app.get('examinerName', 'N/A')}}")
            print(f"Art Unit: {{app.get('artUnit', 'N/A')}}")

            # Office actions: read them DIRECTLY, no document bag / PDF / OCR.
            # PFW_get_oa_rejections: structured 101/102/103/112 + Alice flags,
            #   OAs mailed Oct 1 2017 to ~30 days ago.
            # PFW_get_oa_text: the examiner's words, OAs mailed roughly 2008
            #   onward — an empty rejections result says NOTHING about text
            #   availability. The document bag + PFW_get_document_content_with_ocr
            #   is the FALLBACK (pre-~2008 OAs, non-OA papers, an actual PDF, or
            #   num_found=0), and it can itself 403 on older applications.
            rejections = PFW_get_oa_rejections(application_number=app_num)
            final_oa = PFW_get_oa_text(
                application_number=app_num,
                action_type='CTFR',
                latest_only=True
            )
            print(f"\\nFinal Rejection text retrieved: {{final_oa.get('num_found', 0)}}")
    except Exception as e:
        print(f"ERROR retrieving prosecution history: {{e}}")
```

## Step 3: Analyze Challenge Arguments vs Prosecution

```python
# Get detailed data on most recent/active trial
if trials['count'] > 0:
    primary_trial = trials['results'][0]
    trial_num = primary_trial.get('trialNumber')

    print(f"\\n=== PRIMARY CHALLENGE ANALYSIS ===")
    print(f"Trial: {{trial_num}}")

    # Get trial documents
    trial_docs = PTAB_get_documents(
        identifier=trial_num,
        identifier_type='trial'
    )

    # Find petition and Patent Owner Response
    petition_docs = [d for d in trial_docs.get('documents', [])
                     if 'Petition' in d.get('documentTypeDescriptionText', '') and 'Corrected' not in d.get('documentTypeDescriptionText', '')]
    po_response_docs = [d for d in trial_docs.get('documents', [])
                        if 'Patent Owner Response' in d.get('documentTypeDescriptionText', '')]

    print(f"\\nKey Documents:")
    print(f"  Petitions: {{len(petition_docs)}}")
    print(f"  Patent Owner Responses: {{len(po_response_docs)}}")

    # Provide download links
    if petition_docs:
        for doc in petition_docs[:1]:
            download = PTAB_get_document_download(
                document_id=doc.get('documentIdentifier'),
                identifier=trial_num,
                identifier_type='trial'
            )
            url = download.get('proxy_url') or download.get('download_url')
            pages = doc.get('pageCount', 'Unknown')
            print(f"\\n**[Download Petition ({{pages}} pages)]({{url}})** | Raw URL: `{{url}}`")
```

## Step 4: Defense Strategy Recommendations

```python
print("\\n=== DEFENSE STRATEGY RECOMMENDATIONS ===")
print("\\n1. Prosecution History Analysis:")
print("   - Review examiner's prior art from office actions")
print("   - Identify arguments already considered during prosecution")
print("   - Prepare estoppel arguments if petitioner's art was cited")

print("\\n2. Claim Construction:")
print("   - Review prosecution history for claim construction guidance")
print("   - Identify any amendments made during prosecution")
print("   - Check if petitioner's interpretation conflicts with prosecution")

print("\\n3. Prior Art Comparison:")
print("   - Compare petition references to examiner's cited art")
print("   - Identify any new art vs previously considered references")
print("   - Prepare secondary considerations if available")

print("\\n4. Recommended Actions:")
print(f"   - Review petition documents above")
print(f"   - Compare with prosecution history in PFW")
print(f"   - Identify strongest arguments from prosecution")
print(f"   - Total PTAB challenges: {{trials['count']}} (monitor all)")
```

## Expected Results

1. Challenge Landscape - All PTAB trials involving patent
2. Prosecution History - Complete application data from PFW
3. Key Documents - Petition and response downloads
4. Strategic Recommendations - Defense strategy based on prosecution

Cross-MCP Integration: Combines PTAB challenge data with PFW prosecution history for comprehensive defense strategy.
"""
