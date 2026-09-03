"""PTAB Prior Art Validation Prompt (Cross-MCP: PTAB + PFW + Citations)

Validate prior art across PTAB petitions, prosecution, and citation databases
"""

from . import mcp


@mcp.prompt(
    name="ptab_prior_art_validation_PFW_CITATIONS",
    description="Validate prior art across MCPs. trial_number: PTAB trial (required). application_number: Optional prosecution context.",
)
async def ptab_prior_art_validation_pfw_citations_prompt(
    trial_number: str = "",
    application_number: str = ""
) -> str:
    """Validate prior art across PTAB, PFW, and Citations.

    Args:
        trial_number: PTAB trial number (required)
        application_number: Application number for prosecution comparison (optional)
    """

    if not trial_number:
        return """
# PTAB PRIOR ART VALIDATION

ERROR: Missing Required Parameter

Please provide:
- trial_number: PTAB trial number (e.g., 'IPR2024-01353')

Optional:
- application_number: Application number for prosecution comparison

Example Usage:
```
trial_number='IPR2024-01353'
application_number='14/171,705'
```
"""

    return f"""
# PTAB PRIOR ART VALIDATION

Trial Number: {trial_number}
Application Number: {application_number or 'Will search'}

## Step 1: Extract PTAB Petition References

```python
# Get trial data to find patent number
trial_data = PTAB_search_trials_balanced(
    trial_number='{trial_number}',
    limit=1
)

if trial_data['count'] == 0:
    print("ERROR: Trial not found")
else:
    trial = trial_data['results'][0]
    patent_num = trial.get('patentOwnerData', {{}}).get('patentNumber')

    print("=== TRIAL INFORMATION ===")
    print(f"Trial: {{trial.get('trialNumber')}}")
    print(f"Patent: {{patent_num}}")
    print(f"Petitioner: {{trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName')}}")

    # Get petition documents
    docs = PTAB_get_documents(
        identifier='{trial_number}',
        identifier_type='trial'
    )

    petition_docs = [d for d in docs.get('documents', [])
                     if 'Petition' in d.get('documentTypeDescriptionText', '')]

    print(f"\\nPetition Documents: {{len(petition_docs)}}")
    print("Note: Manual review needed to extract cited references from petition")
```

## Step 2: Get Prosecution Citations (PFW + Citations)

```python
app_num = '{application_number}'

if not app_num and patent_num:
    # Search for application number
    try:
        pfw_result = PFW_search_applications_minimal(
            patent_number=patent_num,
            limit=1
        )
        if pfw_result.get('count', 0) > 0:
            app_num = pfw_result['results'][0].get('applicationNumber')
            print(f"\\nFound application: {{app_num}}")
    except Exception as e:
        print(f"WARNING: Could not find application number")

if app_num:
    print("\\n=== PROSECUTION CITATIONS (Citations MCP) ===")

    try:
        # Get all citations for this application from BOTH lanes and union.
        # Neither is a superset of the other, and classifying a petition
        # reference as "new" off one lane is how a 325(d) analysis goes wrong.
        # No date clause on either: officeActionDate 400s on the OA lane, and a
        # 2017 floor on the enriched lane discards records it holds.
        citations_result = Citations_search_citations_balanced(
            criteria=f'patentApplicationNumber:{{app_num}}',
            rows=50
        )
        oa_result = Citations_search_oa_citations_balanced(
            application_number=app_num,
            rows=50
        )

        citations = citations_result.get('response', {{}}).get('docs', [])
        oa_citations = oa_result.get('response', {{}}).get('docs', [])
        # Union on citedDocumentIdentifier (enriched) / parsedReferenceIdentifier (OA)
        print(f"Citations — enriched: {{len(citations)}}, OA 892/1449: {{len(oa_citations)}}")

        # Categorize citations
        from collections import Counter
        examiner_cites = []
        applicant_cites = []

        for cite in citations:
            if cite.get('examinerCitedReferenceIndicator') == 'true':
                examiner_cites.append(cite.get('citedDocumentIdentifier', 'Unknown'))
            else:
                applicant_cites.append(cite.get('citedDocumentIdentifier', 'Unknown'))

        print(f"\\nExaminer Citations: {{len(examiner_cites)}}")
        print(f"Applicant Citations: {{len(applicant_cites)}}")

        if examiner_cites:
            print(f"\\nTop Examiner Citations:")
            for ref in examiner_cites[:10]:
                print(f"  - {{ref}}")
    except Exception as e:
        print(f"ERROR retrieving citations: {{e}}")
```

## Step 3: Cross-Reference Analysis

```python
print("\\n=== PRIOR ART VALIDATION ===")

# Manual comparison note
print("\\nValidation Steps:")
print("1. Download petition documents from PTAB (above)")
print("2. Extract petitioner's cited references")
print("3. Compare with examiner citations from prosecution")
print("4. Identify:")
print("   - New art (not considered during prosecution)")
print("   - Previously cited art (potential estoppel defense)")
print("   - Similar but different references")

if app_num and len(examiner_cites) > 0:
    print(f"\\nProsecution Record Available:")
    print(f"  - Application: {{app_num}}")
    print(f"  - Examiner Citations: {{len(examiner_cites)}} references")
    print(f"  - Applicant Citations: {{len(applicant_cites)}} references")
    print("\\n  Action: Compare petition references against prosecution citations")
    print("  Defense Opportunity: Any petition art already cited by examiner")
```

## Step 4: Download Package for Review

```python
print("\\n=== VALIDATION PACKAGE ===")

# Download petition
if petition_docs:
    doc = petition_docs[0]
    download = PTAB_get_document_download(
        document_id=doc.get('documentIdentifier'),
        identifier='{trial_number}',
        identifier_type='trial'
    )
    url = download.get('proxy_url') or download.get('download_url')
    pages = doc.get('pageCount', 'Unknown')
    print(f"**[Download Petition ({{pages}} pages)]({{url}})** | Raw URL: `{{url}}`")

# Get prosecution documents
if app_num:
    try:
        # Office-action PDFs for the download package. For the office action
        # TEXT (did the examiner APPLY the reference or merely receive it?) use
        # PFW_get_oa_text(action_type='CTFR', section='103') instead — one call,
        # no OCR, covering OAs mailed roughly 2008 onward. The bag below is for
        # attorney-shareable PDFs and for pre-~2008 prosecution, and can return
        # HTTP 403 on some older applications.
        oa_docs = PFW_get_application_documents(
            app_number=app_num,
            document_code='CTFR',
            limit=3
        )

        if oa_docs.get('count', 0) > 0:
            print(f"\\nOffice Actions Available: {{oa_docs['count']}}")
            for oa in oa_docs.get('documentBag', [])[:1]:
                download = PFW_get_document_download(
                    app_number=app_num,
                    document_id=oa.get('documentIdentifier')
                )
                url = download.get('proxy_url') or download.get('download_url')
                print(f"\\n**[Download Office Action (PFW)]({{url}})** | Raw URL: `{{url}}`")
    except Exception as e:
        pass
```

## Expected Results

1. PTAB References - Petition documents for manual extraction
2. Prosecution Citations - Complete citation record from prosecution
3. Cross-Reference Analysis - Comparison framework
4. Validation Package - All documents for detailed review

Cross-MCP Integration: PTAB petitions + PFW prosecution + Citations database for prior art validation.
"""
