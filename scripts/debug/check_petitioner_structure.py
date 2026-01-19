"""Check regularPetitionerData structure"""

import asyncio
import json
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.settings import Settings

async def check_structure():
    settings = Settings()
    client = PTABClient(api_key=settings.uspto_api_key)

    response = await client.search_trials(
        filters=[{"name": "trialNumber", "value": ["IPR2015-01700"]}],
        pagination={"offset": 0, "limit": 1}
    )

    trial = response["patentTrialProceedingDataBag"][0]

    print("=" * 80)
    print("PETITIONER DATA STRUCTURE")
    print("=" * 80)
    print()
    print("regularPetitionerData contents:")
    print(json.dumps(trial["regularPetitionerData"], indent=2))
    print()

    # Check if it has petitionerPartyName
    if "petitionerData" in trial["regularPetitionerData"]:
        print("regularPetitionerData.petitionerData exists!")
        print(json.dumps(trial["regularPetitionerData"]["petitionerData"], indent=2))

if __name__ == "__main__":
    asyncio.run(check_structure())
