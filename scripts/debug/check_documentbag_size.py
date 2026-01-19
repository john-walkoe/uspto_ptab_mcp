"""Check documentBag context usage"""

import asyncio
import json
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.settings import Settings

async def check_documentbag():
    settings = Settings()
    client = PTABClient(api_key=settings.uspto_api_key)

    # Get trial WITHOUT documentBag (our current approach)
    print("=" * 80)
    print("DOCUMENTBAG CONTEXT ANALYSIS")
    print("=" * 80)
    print()

    # Test 1: Trial data WITHOUT documentBag
    print("TEST 1: Trial data WITHOUT documentBag (current approach)")
    print("-" * 80)
    response_no_docs = await client.search_trials(
        filters=[{"name": "trialNumber", "value": ["IPR2015-01700"]}],
        pagination={"offset": 0, "limit": 1},
        fields=["trialNumber", "trialMetaData.*", "regularPetitionerData.*", "patentOwnerData.*"]
    )

    trial_no_docs = response_no_docs["patentTrialProceedingDataBag"][0]
    json_no_docs = json.dumps(trial_no_docs, indent=2)
    size_no_docs = len(json_no_docs)

    print(f"Size WITHOUT documentBag: {size_no_docs:,} characters")
    print(f"Keys: {list(trial_no_docs.keys())}")
    print()

    # Test 2: Trial data WITH documentBag (if available)
    print("TEST 2: Trial data WITH documentBag (if API returns it)")
    print("-" * 80)
    response_with_docs = await client.search_trials(
        filters=[{"name": "trialNumber", "value": ["IPR2015-01700"]}],
        pagination={"offset": 0, "limit": 1},
        fields=["*"]  # Request all fields
    )

    trial_with_docs = response_with_docs["patentTrialProceedingDataBag"][0]
    json_with_docs = json.dumps(trial_with_docs, indent=2)
    size_with_docs = len(json_with_docs)

    print(f"Size WITH all fields: {size_with_docs:,} characters")
    print(f"Keys: {list(trial_with_docs.keys())}")

    # Check if documentBag exists
    if "documentBag" in trial_with_docs or "patentTrialDocumentBag" in trial_with_docs:
        doc_key = "documentBag" if "documentBag" in trial_with_docs else "patentTrialDocumentBag"
        doc_count = len(trial_with_docs.get(doc_key, []))
        print(f"DocumentBag found with {doc_count} documents")

        # Calculate size impact
        increase = size_with_docs - size_no_docs
        percent_increase = (increase / size_no_docs * 100) if size_no_docs > 0 else 0

        print()
        print("IMPACT ANALYSIS:")
        print(f"  Size increase: {increase:,} characters ({percent_increase:.1f}% increase)")
        print(f"  Documents: {doc_count}")
        print(f"  Avg per document: {increase // doc_count if doc_count > 0 else 0:,} characters")
    else:
        print("No documentBag in API response (API may not include it)")
    print()

    # Test 3: Separate documents tool (our current approach - GOOD!)
    print("TEST 3: Separate ptab_get_documents() tool (current approach)")
    print("-" * 80)
    docs_response = await client.get_trial_documents("IPR2015-01700")
    docs_json = json.dumps(docs_response, indent=2)
    size_docs = len(docs_json)
    doc_count = len(docs_response.get("patentTrialDocumentDataBag", []))

    print(f"Separate documents endpoint: {doc_count} documents")
    print(f"Size: {size_docs:,} characters")
    print(f"Avg per document: {size_docs // doc_count if doc_count > 0 else 0:,} characters")
    print()

    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print("CURRENT APPROACH (CORRECT - SAME AS PFW):")
    print("  1. NEVER include documentBag in field configs")
    print("  2. Use separate ptab_get_documents() tool")
    print("  3. Warn users in field_configs.yaml about documentBag")
    print()
    print("PFW PATTERN:")
    print("  - PFW excludes documentBag from field sets")
    print("  - PFW has pfw_get_application_documents() for metadata only")
    print("  - PFW has pfw_get_document_download() for content")
    print()
    print("PTAB PATTERN (ALREADY IMPLEMENTED):")
    print("  - We exclude documentBag from field sets ✓")
    print("  - We have ptab_get_documents() for metadata ✓")
    print("  - We have ptab_get_document_download() for downloads ✓")
    print("  - We have ptab_get_document_content() for OCR text ✓")
    print()
    print("ACTION: Ensure field_configs.yaml warns about documentBag")
    print("        Add validation to prevent documentBag in custom fields")

if __name__ == "__main__":
    asyncio.run(check_documentbag())
