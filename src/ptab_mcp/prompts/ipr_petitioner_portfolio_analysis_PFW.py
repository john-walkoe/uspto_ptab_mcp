"""IPR Petitioner Portfolio Analysis Prompt (Cross-MCP: PTAB + PFW)

Analyze petitioner's IPR filing patterns and target portfolio
"""

from . import mcp


@mcp.prompt(
    name="ipr_petitioner_portfolio_analysis_PFW",
    description="Analyze petitioner's IPR strategy and target patents. petitioner_name: Company name (required). filing_year_from/to: Date range.",
)
async def ipr_petitioner_portfolio_analysis_pfw_prompt(
    petitioner_name: str = "",
    filing_year_from: str = "",
    filing_year_to: str = ""
) -> str:
    """Analyze petitioner's IPR filing patterns and strategies.

    Args:
        petitioner_name: Petitioner company name (required)
        filing_year_from: Start year (YYYY)
        filing_year_to: End year (YYYY)
    """

    if not petitioner_name:
        return """
# IPR PETITIONER PORTFOLIO ANALYSIS

ERROR: Missing Required Parameter

Please provide:
- petitioner_name: Petitioner company name (e.g., 'Apple Inc')

Optional:
- filing_year_from: Start year (YYYY)
- filing_year_to: End year (YYYY)

Example Usage:
```
petitioner_name='Apple Inc'
filing_year_from='2022'
filing_year_to='2024'
```
"""

    return f"""
# IPR PETITIONER PORTFOLIO ANALYSIS

Petitioner: {petitioner_name}
Date Range: {filing_year_from or 'Any'} to {filing_year_to or 'Any'}

## Step 1: Find All Trials Filed by Petitioner

```python
search_params = {{
    'petitioner_name': '{petitioner_name}',
    'limit': 100
}}

if '{filing_year_from}' and '{filing_year_to}':
    search_params['filing_date_from'] = '{filing_year_from}-01-01'
    search_params['filing_date_to'] = '{filing_year_to}-12-31'

trials = PTAB_search_trials_minimal(**search_params)

print(f"=== PETITIONER IPR ACTIVITY ===")
print(f"Total IPRs Filed: {{trials['count']}}")
print(f"Petitioner: {petitioner_name}")
```

## Step 2: Analyze Target Portfolio

```python
from collections import Counter

# Aggregate targets
patent_owners = Counter()
technology_areas = Counter()
trial_outcomes = Counter()
target_patents = []

for trial in trials['results']:
    po_name = trial.get('patentOwnerData', {{}}).get('patentOwnerName', 'Unknown')
    patent_num = trial.get('patentOwnerData', {{}}).get('patentNumber')
    tech_center = trial.get('patentOwnerData', {{}}).get('technologyCenterNumber', 'Unknown')
    status = trial.get('trialMetaData', {{}}).get('trialStatusCategory', 'Unknown')

    patent_owners[po_name] += 1
    technology_areas[tech_center] += 1
    trial_outcomes[status] += 1

    if patent_num:
        target_patents.append({{
            'patent': patent_num,
            'owner': po_name,
            'trial': trial.get('trialNumber'),
            'status': status
        }})

print("\\n=== TARGET ANALYSIS ===")
print(f"Unique Patent Owners Targeted: {{len(patent_owners)}}")
print("\\nTop Targets:")
for owner, count in patent_owners.most_common(5):
    print(f"  {{owner}}: {{count}} trials")

print("\\nTechnology Focus:")
for tc, count in technology_areas.most_common(5):
    print(f"  TC {{tc}}: {{count}} trials")
```

## Step 3: Cross-Reference with PFW (Patent Details)

```python
print("\\n=== TARGET PATENT DETAILS (PFW) ===")

# Sample first 5 patents for detailed analysis
for i, target in enumerate(target_patents[:5]):
    try:
        pfw_data = PFW_search_applications_minimal(
            patent_number=target['patent'],
            limit=1
        )

        if pfw_data.get('count', 0) > 0:
            app = pfw_data['results'][0]
            print(f"\\nPatent {{i+1}}: {{target['patent']}}")
            print(f"  Owner: {{target['owner']}}")
            print(f"  PTAB Trial: {{target['trial']}} ({{target['status']}})")
            print(f"  Issue Date: {{app.get('patentIssueDate', 'N/A')}}")
            print(f"  Art Unit: {{app.get('artUnit', 'N/A')}}")
    except Exception as e:
        print(f"  WARNING: PFW data unavailable for {{target['patent']}}")
```

## Step 4: Success Rate and Strategy Assessment

```python
print("\\n=== PETITIONER SUCCESS METRICS ===")
total = trials['count']
for outcome, count in trial_outcomes.most_common():
    pct = count / total * 100
    print(f"{{outcome}}: {{count}} ({{pct:.1f}}%)")

print("\\n=== STRATEGIC ASSESSMENT ===")
print(f"1. Filing Volume: {{total}} IPRs")
print(f"2. Target Concentration: {{patent_owners.most_common(1)[0][0]}} ({{patent_owners.most_common(1)[0][1]}} trials)")
print(f"3. Technology Focus: TC {{technology_areas.most_common(1)[0][0]}} ({{technology_areas.most_common(1)[0][1]}} trials)")
print(f"4. Institution Rate: {{trial_outcomes.get('Instituted', 0) / total * 100:.1f}}%")
```

## Expected Results

1. Filing Activity - Complete petitioner IPR history
2. Target Analysis - Patent owners and technology areas targeted
3. Patent Details - Cross-referenced with PFW prosecution data
4. Success Metrics - Institution rates and outcome statistics

Cross-MCP Integration: PTAB trial data + PFW patent details for competitive intelligence.
"""
