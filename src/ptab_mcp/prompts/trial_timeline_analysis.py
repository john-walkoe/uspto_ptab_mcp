"""Trial Timeline Analysis Prompt

Timeline analysis of PTAB proceeding milestones
"""

from . import mcp


@mcp.prompt(
    name="trial_timeline_analysis",
    description="Analyze PTAB trial timeline and milestones. trial_number: PTAB trial number (required, e.g., 'IPR2024-00123').",
)
async def trial_timeline_analysis_prompt(trial_number: str = "") -> str:
    """Analyze PTAB trial timeline and key milestones.

    Args:
        trial_number: PTAB trial number (e.g., 'IPR2024-00123')
    """

    if not trial_number:
        return """
# TRIAL TIMELINE ANALYSIS

ERROR: Missing Required Parameter

Please provide:
- trial_number: PTAB trial number (e.g., 'IPR2024-00123')

Example Usage:
```
trial_number='IPR2024-00123'
```
"""

    return f"""
# TRIAL TIMELINE ANALYSIS

Trial Number: {trial_number}

## Step 1: Get Trial Metadata with Dates

```python
# Get comprehensive trial data with all dates
trial_data = search_trials_balanced(
    trial_number='{trial_number}',
    limit=1
)

if trial_data['count'] == 0:
    print("ERROR: Trial not found")
else:
    trial = trial_data['results'][0]
    metadata = trial.get('trialMetaData', {{}})

    print("=== TRIAL TIMELINE ===")
    print(f"Trial: {{trial.get('trialNumber')}}")
    print(f"Type: {{metadata.get('trialTypeCode')}}")
    print(f"Status: {{metadata.get('trialStatusCategory')}}")
```

## Step 2: Extract Key Milestone Dates

```python
# Collect all date milestones
milestones = []

filing_date = metadata.get('accordedFilingDate')
if filing_date:
    milestones.append(('Petition Filed', filing_date))

institution_date = metadata.get('institutionDecisionDate')
if institution_date:
    milestones.append(('Institution Decision', institution_date))

fwd_date = metadata.get('finalWrittenDecisionDate')
if fwd_date:
    milestones.append(('Final Written Decision', fwd_date))

termination_date = metadata.get('terminationDate')
if termination_date:
    milestones.append(('Termination', termination_date))

# Sort by date
from datetime import datetime
milestones_sorted = sorted(milestones, key=lambda x: datetime.fromisoformat(x[1]) if x[1] else datetime.min)

print("\\nKey Milestones:")
for milestone, date in milestones_sorted:
    print(f"  {{date}}: {{milestone}}")
```

## Step 3: Calculate Duration Metrics

```python
# Calculate time between milestones
from datetime import datetime

if filing_date and institution_date:
    filing_dt = datetime.fromisoformat(filing_date)
    institution_dt = datetime.fromisoformat(institution_date)
    institution_duration = (institution_dt - filing_dt).days

    print(f"\\nTiming Metrics:")
    print(f"  Filing to Institution: {{institution_duration}} days")

if institution_date and fwd_date:
    fwd_dt = datetime.fromisoformat(fwd_date)
    trial_duration = (fwd_dt - institution_dt).days
    print(f"  Institution to FWD: {{trial_duration}} days")

if filing_date and fwd_date:
    total_duration = (fwd_dt - filing_dt).days
    print(f"  Total Duration: {{total_duration}} days (~{{total_duration/30:.1f}} months)")
```

## Step 4: Document Timeline

```python
# Get all documents and their filing dates
docs = ptab_get_documents(
    identifier='{trial_number}',
    identifier_type='trial'
)

# Create timeline of filings
doc_timeline = []
for doc in docs.get('documents', []):
    doc_date = doc.get('filingDate')
    if doc_date:
        doc_timeline.append({{
            'date': doc_date,
            'description': doc.get('documentTypeDescriptionText', 'Unknown'),
            'pages': doc.get('pageCount', 0)
        }})

# Sort by date
doc_timeline_sorted = sorted(doc_timeline, key=lambda x: x['date'])

print("\\n=== COMPLETE DOCUMENT TIMELINE ===")
for doc in doc_timeline_sorted:
    print(f"{{doc['date']}}: {{doc['description']}} ({{doc['pages']}} pages)")
```

## Expected Results

1. Key Milestones - All major proceeding dates extracted
2. Duration Metrics - Time between filing, institution, and final decision
3. Document Timeline - Chronological view of all filings
4. Strategic Insights - Identify unusual delays or expedited processing

Use Case: Procedural analysis, expectation management for pending trials, strategic timing analysis.
"""
