"""Check all field names in API response"""

import asyncio
import json
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.settings import Settings

async def check_all_fields():
    settings = Settings()
    client = PTABClient(api_key=settings.uspto_api_key)

    # Get full response with all fields
    response = await client.search_trials(
        filters=[{"name": "trialNumber", "value": ["IPR2015-01700"]}],
        pagination={"offset": 0, "limit": 1},
        fields=["*"]  # Request ALL fields
    )

    trial = response["patentTrialProceedingDataBag"][0]

    print("=" * 80)
    print("COMPLETE API FIELD STRUCTURE")
    print("=" * 80)
    print()
    print("Top-level keys:")
    for key in trial.keys():
        print(f"  - {key}")
    print()

    # Show each section
    sections = ["trialMetaData", "regularPetitionerData", "patentOwnerData", "respondentData"]

    for section in sections:
        if section in trial:
            print(f"{section}:")
            if isinstance(trial[section], dict):
                for key in trial[section].keys():
                    print(f"  - {section}.{key}")
            else:
                print(f"  Type: {type(trial[section])}")
            print()

if __name__ == "__main__":
    asyncio.run(check_all_fields())
