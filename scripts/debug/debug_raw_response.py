"""Debug: Check raw API response before filtering"""

import asyncio
import json
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.settings import Settings

async def debug_raw_api():
    """Get raw API responses to see what we're actually getting"""

    settings = Settings()
    client = PTABClient(api_key=settings.uspto_api_key)

    print("=" * 80)
    print("RAW API RESPONSE DEBUGGING")
    print("=" * 80)
    print()

    # Test 1: Get raw trial data
    print("TEST 1: Raw API response for IPR2015-01700")
    print("-" * 80)
    try:
        raw_response = await client.search_trials(
            filters=[{"name": "trialNumber", "value": ["IPR2015-01700"]}],
            pagination={"offset": 0, "limit": 1}
        )

        print(f"Response keys: {list(raw_response.keys())}")
        print(f"Count: {raw_response.get('count', 0)}")

        if raw_response.get("patentTrialProceedingDataBag"):
            trial = raw_response["patentTrialProceedingDataBag"][0]
            print(f"Trial keys: {list(trial.keys())}")
            print()

            # Check for petitionerData
            if 'petitionerData' in trial:
                print("petitionerData EXISTS in raw API response:")
                print(f"  Keys: {list(trial['petitionerData'].keys())}")
                if 'petitionerPartyName' in trial['petitionerData']:
                    print(f"  petitionerPartyName: {trial['petitionerData']['petitionerPartyName']}")
            else:
                print("ERROR: petitionerData NOT in raw API response!")
                print("This means API itself isn't returning petitioner data")

            # Check what's actually in the response
            print()
            print("Full trial structure (first level keys):")
            for key, value in trial.items():
                if isinstance(value, dict):
                    print(f"  {key}: {{dict with {len(value)} keys}}")
                elif isinstance(value, list):
                    print(f"  {key}: [list with {len(value)} items]")
                else:
                    print(f"  {key}: {value}")

    except Exception as e:
        print(f"ERROR: {e}")
    print()

    # Test 2: Raw documents API
    print("TEST 2: Raw API response for documents IPR2015-01700")
    print("-" * 80)
    try:
        raw_response = await client.get_trial_documents("IPR2015-01700")

        print(f"Response keys: {list(raw_response.keys())}")
        print(f"Count: {raw_response.get('count', 0)}")

        if raw_response.get("count", 0) > 0:
            print(f"Documents found: {raw_response['count']}")
            if raw_response.get("documents"):
                print(f"Document array length: {len(raw_response['documents'])}")
                print("First document:")
                doc = raw_response['documents'][0]
                print(f"  Keys: {list(doc.keys())}")
                print(f"  ID: {doc.get('documentIdentifier')}")
                print(f"  Description: {doc.get('documentDescription')}")
        else:
            print("No documents in raw API response")
            print("This means API itself returns no documents for this trial")
            print("Possible reasons:")
            print("  1. Documents endpoint is different")
            print("  2. Trial data not fully migrated to new API")
            print("  3. Need different API endpoint for old trials")

    except Exception as e:
        print(f"ERROR: {e}")
    print()

    # Test 3: Search for Apple with exact string
    print("TEST 3: Search for 'Apple, Inc.' (exact match)")
    print("-" * 80)
    try:
        raw_response = await client.search_trials(
            filters=[{"name": "petitionerData.petitionerPartyName", "value": ["Apple, Inc."]}],
            pagination={"offset": 0, "limit": 5}
        )

        print(f"Count: {raw_response.get('count', 0)}")
        if raw_response.get('count', 0) > 0:
            print("SUCCESS: Found trials with 'Apple, Inc.'")
        else:
            print("No matches for 'Apple, Inc.'")

    except Exception as e:
        print(f"ERROR: {e}")
    print()

    # Test 4: Try partial match or wildcards
    print("TEST 4: Try searching with partial match 'Apple'")
    print("-" * 80)
    try:
        raw_response = await client.search_trials(
            filters=[{"name": "petitionerData.petitionerPartyName", "value": ["Apple"]}],
            pagination={"offset": 0, "limit": 5}
        )

        print(f"Count: {raw_response.get('count', 0)}")
    except Exception as e:
        print(f"ERROR: {e}")
    print()

    await client.close()

if __name__ == "__main__":
    asyncio.run(debug_raw_api())
