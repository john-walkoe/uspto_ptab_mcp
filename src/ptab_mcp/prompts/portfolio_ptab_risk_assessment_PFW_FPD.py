"""Portfolio PTAB Risk Assessment Prompt (Cross-MCP: PTAB + PFW + FPD)

Assess PTAB challenge risk across patent portfolio using prosecution and family data
"""

from . import mcp


@mcp.prompt(
    name="portfolio_ptab_risk_assessment_PFW_FPD",
    description="Assess PTAB risk for patent portfolio. assignee_name: Portfolio owner (required). tech_center: Optional technology filter.",
)
async def portfolio_ptab_risk_assessment_pfw_fpd_prompt(
    assignee_name: str = "",
    tech_center: str = ""
) -> str:
    """Assess PTAB challenge risk across patent portfolio.

    Args:
        assignee_name: Portfolio owner/assignee name (required)
        tech_center: Optional technology center filter
    """

    if not assignee_name:
        return """
# PORTFOLIO PTAB RISK ASSESSMENT

ERROR: Missing Required Parameter

Please provide:
- assignee_name: Portfolio owner/assignee name (e.g., 'Samsung Electronics')

Optional:
- tech_center: Technology center filter (e.g., '2600')

Example Usage:
```
assignee_name='Samsung Electronics'
tech_center='2600'
```
"""

    return f"""
# PORTFOLIO PTAB RISK ASSESSMENT

Portfolio Owner: {assignee_name}
Technology Filter: {tech_center or 'All'}

## Step 1: Find All PTAB Challenges to Portfolio

```python
# Search PTAB for all trials against this assignee
trials = PTAB_search_trials_minimal(
    patent_owner_name='{assignee_name}',
    limit=100
)

print(f"=== PTAB CHALLENGE LANDSCAPE ===")
print(f"Total Challenges Found: {{trials['count']}}")
print(f"Portfolio Owner: {assignee_name}")

challenged_patents = set()
for trial in trials['results']:
    patent = trial.get('patentOwnerData', {{}}).get('patentNumber')
    if patent:
        challenged_patents.add(patent)

print(f"Unique Patents Challenged: {{len(challenged_patents)}}")
```

## Step 2: Get Portfolio from PFW

```python
# Get complete patent portfolio from PFW
print("\\n=== PORTFOLIO ANALYSIS (PFW) ===")

try:
    portfolio = PFW_search_applications_minimal(
        assignee_name='{assignee_name}',
        patent_status='Patented',
        limit=100
    )

    print(f"Total Patents in Portfolio: {{portfolio.get('count', 0)}}")

    # Calculate challenge rate
    if portfolio.get('count', 0) > 0:
        challenge_rate = len(challenged_patents) / portfolio['count'] * 100
        print(f"Challenge Rate: {{challenge_rate:.1f}}%")
except Exception as e:
    print(f"WARNING: Could not retrieve portfolio from PFW: {{e}}")
```

## Step 3: Analyze Patent Families (FPD Integration)

```python
print("\\n=== PATENT FAMILY ANALYSIS (FPD) ===")

# Sample first 5 challenged patents for family analysis
for i, patent in enumerate(list(challenged_patents)[:5]):
    try:
        family_data = fpd_search_patent_families_minimal(
            patent_number=patent,
            limit=10
        )

        family_size = family_data.get('count', 0)
        print(f"\\nPatent {{i+1}}: {{patent}}")
        print(f"  Family Members: {{family_size}}")

        if family_size > 0:
            print(f"  Jurisdictions: ", end='')
            countries = set()
            for member in family_data.get('results', [])[:5]:
                country = member.get('country', 'Unknown')
                countries.add(country)
            print(', '.join(countries))
    except Exception as e:
        print(f"  WARNING: Family data unavailable")
```

## Step 4: Risk Assessment and Recommendations

```python
from collections import Counter

# Analyze challenge outcomes
outcomes = Counter()
petitioners = Counter()

for trial in trials['results']:
    status = trial.get('trialMetaData', {{}}).get('trialStatusCategory', 'Unknown')
    petitioner = trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName', 'Unknown')

    outcomes[status] += 1
    petitioners[petitioner] += 1

print("\\n=== RISK ASSESSMENT ===")
print(f"\\nChallenge Outcomes:")
for outcome, count in outcomes.most_common():
    pct = count / trials['count'] * 100
    print(f"  {{outcome}}: {{count}} ({{pct:.1f}}%)")

print(f"\\nTop Petitioners:")
for petitioner, count in petitioners.most_common(5):
    print(f"  {{petitioner}}: {{count}} challenges")

print("\\n=== RECOMMENDATIONS ===")
print(f"1. High-Risk Patents: {{len([o for o in outcomes if 'Terminated' in o])}} trials terminated")
print(f"2. Active Threats: {{outcomes.get('Instituted', 0)}} instituted trials")
print(f"3. Portfolio Monitoring: Track {{petitioners.most_common(1)[0][0]}} filings")
print(f"4. Family Protection: Review international coverage for challenged patents")
```

## Expected Results

1. Challenge Landscape - All PTAB trials against portfolio
2. Portfolio Analysis - Complete patent portfolio from PFW
3. Family Coverage - International protection via FPD
4. Risk Metrics - Challenge rates, outcomes, active petitioners

Cross-MCP Integration: PTAB + PFW + FPD for comprehensive portfolio risk assessment.
"""
