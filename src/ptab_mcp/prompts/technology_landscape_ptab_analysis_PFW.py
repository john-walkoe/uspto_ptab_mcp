"""Technology Landscape PTAB Analysis Prompt (Cross-MCP: PTAB + PFW)

Technology area PTAB trends combined with prosecution data
"""

from . import mcp


@mcp.prompt(
    name="technology_landscape_ptab_analysis_PFW",
    description="Analyze PTAB trends in technology area. tech_center: Technology center (required). filing_year_from/to: Date range.",
)
async def technology_landscape_ptab_analysis_pfw_prompt(
    tech_center: str = "",
    filing_year_from: str = "",
    filing_year_to: str = ""
) -> str:
    """Analyze PTAB activity trends in technology area.

    Args:
        tech_center: Technology center number (required)
        filing_year_from: Start year (YYYY)
        filing_year_to: End year (YYYY)
    """

    if not tech_center:
        return """
# TECHNOLOGY LANDSCAPE PTAB ANALYSIS

ERROR: Missing Required Parameter

Please provide:
- tech_center: Technology center number (e.g., '2600')

Optional:
- filing_year_from: Start year (YYYY)
- filing_year_to: End year (YYYY)

Example Usage:
```
tech_center='2600'
filing_year_from='2022'
filing_year_to='2024'
```
"""

    return f"""
# TECHNOLOGY LANDSCAPE PTAB ANALYSIS

Technology Center: {tech_center}
Date Range: {filing_year_from or 'Any'} to {filing_year_to or 'Any'}

## Step 1: Aggregate PTAB Activity in Technology Area

```python
search_params = {{
    'tech_center': '{tech_center}',
    'limit': 100
}}

if '{filing_year_from}' and '{filing_year_to}':
    search_params['filing_date_from'] = '{filing_year_from}-01-01'
    search_params['filing_date_to'] = '{filing_year_to}-12-31'

trials = search_trials_minimal(**search_params)

print(f"=== TECHNOLOGY AREA ACTIVITY ===")
print(f"Technology Center: {tech_center}")
print(f"Total Trials: {{trials['count']}}")
```

## Step 2: Trend Analysis

```python
from collections import Counter
from datetime import datetime

# Aggregate by year, type, outcome
by_year = Counter()
by_type = Counter()
by_outcome = Counter()
top_petitioners = Counter()
top_owners = Counter()

for trial in trials['results']:
    filing_date = trial.get('trialMetaData', {{}}).get('accordedFilingDate', '')
    if filing_date:
        year = filing_date[:4]
        by_year[year] += 1

    trial_type = trial.get('trialMetaData', {{}}).get('trialTypeCode', 'Unknown')
    by_type[trial_type] += 1

    status = trial.get('trialMetaData', {{}}).get('trialStatusCategory', 'Unknown')
    by_outcome[status] += 1

    petitioner = trial.get('regularPetitionerData', {{}}).get('realPartyInInterestName', 'Unknown')
    top_petitioners[petitioner] += 1

    owner = trial.get('patentOwnerData', {{}}).get('patentOwnerName', 'Unknown')
    top_owners[owner] += 1

print("\\n=== FILING TRENDS ===")
for year in sorted(by_year.keys()):
    print(f"{{year}}: {{by_year[year]}} trials")

print("\\n=== MOST ACTIVE PETITIONERS ===")
for petitioner, count in top_petitioners.most_common(10):
    print(f"{{petitioner}}: {{count}} trials")

print("\\n=== MOST CHALLENGED PATENT OWNERS ===")
for owner, count in top_owners.most_common(10):
    print(f"{{owner}}: {{count}} trials")
```

## Step 3: Prosecution Context (PFW)

```python
print("\\n=== PROSECUTION INTELLIGENCE (PFW) ===")

# Sample patents from PTAB trials for prosecution analysis
sample_patents = []
for trial in trials['results'][:10]:
    patent = trial.get('patentOwnerData', {{}}).get('patentNumber')
    if patent and patent not in sample_patents:
        sample_patents.append(patent)

print(f"Analyzing {{len(sample_patents)}} sample patents...")

avg_prosecution_time = []
art_units = Counter()

for patent in sample_patents:
    try:
        pfw_data = pfw_search_applications_balanced(
            patent_number=patent,
            limit=1
        )

        if pfw_data.get('count', 0) > 0:
            app = pfw_data['results'][0]
            art_unit = app.get('artUnit', 'Unknown')
            art_units[art_unit] += 1

            # Calculate prosecution time
            filing_date = app.get('filingDate')
            issue_date = app.get('patentIssueDate')
            if filing_date and issue_date:
                filing_dt = datetime.fromisoformat(filing_date)
                issue_dt = datetime.fromisoformat(issue_date)
                days = (issue_dt - filing_dt).days
                avg_prosecution_time.append(days)
    except Exception as e:
        pass

if avg_prosecution_time:
    avg_days = sum(avg_prosecution_time) / len(avg_prosecution_time)
    print(f"\\nAverage Prosecution Time: {{avg_days/365:.1f}} years")

print(f"\\nTop Art Units:")
for art_unit, count in art_units.most_common(5):
    print(f"  {{art_unit}}: {{count}} patents")
```

## Step 4: Technology Landscape Summary

```python
print("\\n=== TECHNOLOGY LANDSCAPE SUMMARY ===")
print(f"Technology Center: {tech_center}")
print(f"Time Period: {filing_year_from or 'All'} to {filing_year_to or 'Present'}")
print(f"\\nKey Metrics:")
print(f"1. Total PTAB Trials: {{trials['count']}}")
print(f"2. Dominant Trial Type: {{by_type.most_common(1)[0][0]}} ({{by_type.most_common(1)[0][1]}} trials)")
print(f"3. Institution Rate: {{by_outcome.get('Instituted', 0) / trials['count'] * 100:.1f}}%")
print(f"4. Most Active Petitioner: {{top_petitioners.most_common(1)[0][0]}}")
print(f"5. Most Challenged Owner: {{top_owners.most_common(1)[0][0]}}")
```

## Expected Results

1. Activity Metrics - Filing trends, trial types, outcomes
2. Party Analysis - Top petitioners and patent owners
3. Prosecution Context - Art unit distribution, prosecution times
4. Strategic Intelligence - Technology area competitive landscape

Cross-MCP Integration: PTAB trial trends + PFW prosecution patterns for technology intelligence.
"""
