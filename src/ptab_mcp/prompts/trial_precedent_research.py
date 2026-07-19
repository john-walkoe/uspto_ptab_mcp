"""Trial Precedent Research Prompt

Find similar PTAB trial precedents for strategy development
"""

from . import mcp


@mcp.prompt(
    name="trial_precedent_research",
    description="Find similar PTAB precedents based on technology, parties, or claims. tech_area: Technology area (required). party_name: Optional party filter. filing_year_from/to: Optional date range.",
)
async def trial_precedent_research_prompt(
    tech_area: str = "",
    party_name: str = "",
    filing_year_from: str = "",
    filing_year_to: str = ""
) -> str:
    """Find similar PTAB precedents for strategy development.

    Args:
        tech_area: Technology area or classification (e.g., '2600' for communications)
        party_name: Optional party name filter (petitioner or patent owner)
        filing_year_from: Optional start year (YYYY)
        filing_year_to: Optional end year (YYYY)
    """

    if not tech_area:
        return """
# TRIAL PRECEDENT RESEARCH

ERROR: Missing Required Parameter

Please provide:
- tech_area: Technology area or classification (e.g., '2600' for communications)

Optional Parameters:
- party_name: Filter by party name (petitioner or patent owner)
- filing_year_from: Start year (YYYY)
- filing_year_to: End year (YYYY)

Example Usage:
```
tech_area='2600'
party_name='Apple Inc'
filing_year_from='2022'
filing_year_to='2024'
```
"""

    return f"""
# TRIAL PRECEDENT RESEARCH

Technology Area: {tech_area}
Party Filter: {party_name or 'None'}
Date Range: {filing_year_from or 'Any'} to {filing_year_to or 'Any'}

## Step 1: Search for Similar Trials

```python
# Build search criteria
search_params = {{
    'tech_center': '{tech_area}',
    'limit': 50
}}

if '{party_name}':
    search_params['petitioner_name'] = '{party_name}'

if '{filing_year_from}' and '{filing_year_to}':
    search_params['filing_date_from'] = '{filing_year_from}-01-01'
    search_params['filing_date_to'] = '{filing_year_to}-12-31'

# Search with minimal tier for discovery
trials = search_trials_minimal(**search_params)

print(f"Found {{trials['count']}} trials in technology area {tech_area}")
```

## Step 2: Analyze Trial Outcomes

```python
from collections import Counter

# Categorize by outcome
outcomes = Counter()
trial_types = Counter()

for trial in trials['results']:
    status = trial.get('trialMetaData', {{}}).get('trialStatusCategory', 'Unknown')
    trial_type = trial.get('trialMetaData', {{}}).get('trialTypeCode', 'Unknown')

    outcomes[status] += 1
    trial_types[trial_type] += 1

print("\\nTrial Outcomes:")
for outcome, count in outcomes.most_common():
    print(f"  {{outcome}}: {{count}} ({{count/trials['count']*100:.1f}}%)")

print("\\nTrial Types:")
for t_type, count in trial_types.most_common():
    print(f"  {{t_type}}: {{count}}")
```

## Step 3: Get Detailed Analysis of Key Trials

```python
# Select top 5-10 trials for detailed analysis
key_trials = trials['results'][:10]

for i, trial in enumerate(key_trials):
    trial_num = trial.get('trialNumber')

    # Get balanced tier for detailed data
    detailed = search_trials_balanced(
        trial_number=trial_num,
        limit=1
    )

    if detailed['count'] > 0:
        t = detailed['results'][0]

        print(f"\\nTrial {{i+1}}: {{trial_num}}")
        print(f"  Petitioner: {{t.get('regularPetitionerData', {{}}).get('realPartyInInterestName', 'N/A')}}")
        print(f"  Patent Owner: {{t.get('patentOwnerData', {{}}).get('patentOwnerName', 'N/A')}}")
        print(f"  Patent Number: {{t.get('patentOwnerData', {{}}).get('patentNumber', 'N/A')}}")
        print(f"  Status: {{t.get('trialMetaData', {{}}).get('trialStatusCategory', 'N/A')}}")

        # Get decision documents
        docs = ptab_get_documents(identifier=trial_num, identifier_type='trial')

        fwd_docs = [d for d in docs.get('documents', [])
                    if 'Final Written Decision' in d.get('documentTypeDescriptionText', '')]

        if fwd_docs:
            print(f"  Decision Available: Yes ({{len(fwd_docs)}} documents)")
```

## Step 4: Strategic Intelligence Summary

```python
# Aggregate insights
print("\\n=== STRATEGIC INTELLIGENCE SUMMARY ===")
print(f"Total Precedents Analyzed: {{trials['count']}}")
print(f"Technology Area: {tech_area}")
print(f"\\nKey Insights:")
print(f"1. Institution Rate: {{outcomes.get('Instituted', 0) / trials['count'] * 100:.1f}}%")
print(f"2. Most Common Outcome: {{outcomes.most_common(1)[0][0]}}")
print(f"3. Dominant Trial Type: {{trial_types.most_common(1)[0][0]}}")
print(f"\\nRecommendation: Review Final Written Decisions from top {{len(key_trials)}} precedents")
```

## Expected Results

1. Precedent Database - 50-100 similar trials in technology area
2. Outcome Statistics - Institution rates, decision patterns, success rates
3. Key Precedents - Detailed analysis of 5-10 most relevant trials
4. Strategic Intelligence - Data-driven recommendations for trial strategy

Cross-Tool Integration: Combines minimal discovery with balanced analysis for efficient precedent research.
"""
