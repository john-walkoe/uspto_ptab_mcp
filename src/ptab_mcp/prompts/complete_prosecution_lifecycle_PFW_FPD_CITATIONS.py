"""Complete Prosecution Lifecycle Prompt (Cross-MCP: PTAB + PFW + FPD + Citations)

Complete patent lifecycle tracking across all USPTO MCPs
"""

from . import mcp


@mcp.prompt(
    name="complete_prosecution_lifecycle_PFW_FPD_CITATIONS",
    description="Complete patent lifecycle analysis. patent_number: Patent number (required). include_family: Include family data (true/false).",
)
async def complete_prosecution_lifecycle_pfw_fpd_citations_prompt(
    patent_number: str = "",
    include_family: str = "false"
) -> str:
    """Complete patent lifecycle across all USPTO MCPs.

    Args:
        patent_number: Patent number (required)
        include_family: Include patent family data ('true'/'false')
    """

    if not patent_number:
        return """
# COMPLETE PROSECUTION LIFECYCLE

ERROR: Missing Required Parameter

Please provide:
- patent_number: Patent number (e.g., '7883848')

Optional:
- include_family: Include patent family data ('true'/'false', default 'false')

Example Usage:
```
patent_number='7883848'
include_family='true'
```
"""

    return f"""
# COMPLETE PROSECUTION LIFECYCLE

Patent Number: {patent_number}
Include Family: {include_family}

## Step 1: Prosecution History (PFW)

```python
print("=== PHASE 1: PROSECUTION (PFW) ===")

pfw_data = PFW_search_applications_balanced(
    patent_number='{patent_number}',
    limit=1
)

app_num = None
if pfw_data.get('count', 0) > 0:
    app = pfw_data['results'][0]
    app_num = app.get('applicationNumber')

    print(f"Application: {{app_num}}")
    print(f"Filing Date: {{app.get('filingDate')}}")
    print(f"Issue Date: {{app.get('patentIssueDate')}}")
    print(f"Assignee: {{app.get('assigneeName', 'N/A')}}")
    print(f"Examiner: {{app.get('examinerName', 'N/A')}}")
    print(f"Art Unit: {{app.get('artUnit', 'N/A')}}")

    # Get document counts
    docs = PFW_get_application_documents(
        app_number=app_num,
        limit=100
    )
    print(f"\\nProsecution Documents: {{docs.get('count', 0)}}")
```

## Step 2: Citation Intelligence (Citations MCP)

```python
print("\\n=== PHASE 2: CITATIONS (Citations MCP) ===")

if app_num:
    try:
        # RUN BOTH LANES — neither is a superset of the other. The OA lane is
        # usually broader in bulk, but on a given application the enriched lane
        # can return more. No date clause on either call: officeActionDate 400s
        # on the OA lane, and a 2017 floor on the enriched lane discards records
        # it holds. publicationNumber also 400s on the OA lane.
        citations_result = Citations_search_citations_balanced(
            criteria=f'patentApplicationNumber:{{app_num}}',
            rows=100
        )
        oa_result = Citations_search_oa_citations_balanced(
            application_number=app_num,
            rows=100
        )

        citations = citations_result.get('response', {{}}).get('docs', [])
        oa_citations = oa_result.get('response', {{}}).get('docs', [])
        # Union on the normalized reference id — enriched:
        # citedDocumentIdentifier / publicationNumber; OA: parsedReferenceIdentifier
        print(f"Citations — enriched: {{len(citations)}}, OA 892/1449: {{len(oa_citations)}}")

        # Analyze citations
        from collections import Counter
        sources = Counter()
        categories = Counter()

        for cite in citations:
            if cite.get('examinerCitedReferenceIndicator') == 'true':
                sources['Examiner'] += 1
            else:
                sources['Applicant'] += 1

            category = cite.get('citationCategoryCode', 'Unknown')
            categories[category] += 1

        print(f"\\nCitation Sources:")
        for source, count in sources.items():
            print(f"  {{source}}: {{count}}")

        print(f"\\nCitation Categories:")
        for category, count in categories.most_common(5):
            print(f"  {{category}}: {{count}}")
    except Exception as e:
        print(f"WARNING: Citations unavailable: {{e}}")
```

## Step 3: PTAB Challenge History

```python
print("\\n=== PHASE 3: PTAB CHALLENGES ===")

trials = PTAB_search_trials_minimal(
    patent_number='{patent_number}',
    limit=50
)

print(f"PTAB Trials: {{trials['count']}}")

if trials['count'] > 0:
    from collections import Counter
    outcomes = Counter()

    for trial in trials['results']:
        status = trial.get('trialMetaData', {{}}).get('trialStatusCategory', 'Unknown')
        outcomes[status] += 1

        print(f"\\nTrial: {{trial.get('trialNumber')}}")
        print(f"  Petitioner: {{trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName')}}")
        print(f"  Status: {{status}}")
        print(f"  Filing: {{trial.get('trialMetaData', {{}}).get('accordedFilingDate')}}")

    print(f"\\nPTAB Outcomes:")
    for outcome, count in outcomes.most_common():
        print(f"  {{outcome}}: {{count}}")
```

## Step 4: Patent Family (FPD)

```python
if '{include_family}' == 'true':
    print("\\n=== PHASE 4: PATENT FAMILY (FPD) ===")

    try:
        family_data = fpd_search_patent_families_minimal(
            patent_number='{patent_number}',
            limit=50
        )

        print(f"Family Members: {{family_data.get('count', 0)}}")

        if family_data.get('count', 0) > 0:
            countries = Counter()
            statuses = Counter()

            for member in family_data.get('results', []):
                country = member.get('country', 'Unknown')
                status = member.get('status', 'Unknown')

                countries[country] += 1
                statuses[status] += 1

            print(f"\\nGeographic Coverage:")
            for country, count in countries.most_common(10):
                print(f"  {{country}}: {{count}} applications")

            print(f"\\nFamily Status:")
            for status, count in statuses.most_common():
                print(f"  {{status}}: {{count}}")
    except Exception as e:
        print(f"WARNING: Family data unavailable: {{e}}")
```

## Step 5: Complete Lifecycle Summary

```python
print("\\n=== COMPLETE LIFECYCLE SUMMARY ===")
print(f"Patent: {patent_number}")

if app_num:
    print(f"Application: {{app_num}}")

    # Calculate lifecycle duration
    from datetime import datetime
    if pfw_data.get('count', 0) > 0:
        filing = pfw_data['results'][0].get('filingDate')
        issue = pfw_data['results'][0].get('patentIssueDate')

        if filing and issue:
            filing_dt = datetime.fromisoformat(filing)
            issue_dt = datetime.fromisoformat(issue)
            prosecution_days = (issue_dt - filing_dt).days

            print(f"\\nLifecycle Metrics:")
            print(f"  Prosecution Time: {{prosecution_days}} days (~{{prosecution_days/365:.1f}} years)")
            print(f"  Citations Received: {{len(citations) if 'citations' in locals() else 'N/A'}}")
            print(f"  PTAB Challenges: {{trials['count']}}")

            if '{include_family}' == 'true' and family_data.get('count', 0) > 0:
                print(f"  Family Size: {{family_data['count']}} applications")

print("\\n=== STRATEGIC INTELLIGENCE ===")
print("1. Prosecution complete - patent granted")
print(f"2. Citation landscape analyzed - {{len(citations) if 'citations' in locals() else 0}} references")
print(f"3. PTAB exposure: {{trials['count']}} challenges")
if '{include_family}' == 'true':
    print(f"4. International protection: {{family_data.get('count', 0) if 'family_data' in locals() else 0}} jurisdictions")
print("\\nComplete patent lifecycle intelligence package generated")
```

## Expected Results

1. Prosecution History - Complete PFW application data
2. Citation Intelligence - All citations with categorization
3. PTAB Challenge Status - Post-grant challenges and outcomes
4. Patent Family - International coverage and status
5. Lifecycle Summary - Complete timeline from filing to current status

Cross-MCP Integration: PFW + Citations + PTAB + FPD for complete patent lifecycle tracking.
"""
