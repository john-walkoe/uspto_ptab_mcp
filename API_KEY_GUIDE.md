# Obtaining USPTO PTAB MCP Server API Keys

Several tools require API keys to function. For the USPTO PTAB MCP Server:

- **USPTO API Key**: Required and free
- **Mistral API Key**: Optional. Adds an OCR extraction tier for scanned documents that carry no native text layer. Without it, the server still extracts text from documents that have a text layer, and a self-hosted Docling backend can be configured instead (see `DOCLING_SERVE_URL` in [INSTALL.md](INSTALL.md))

Follow these steps to obtain your API keys:

---

## USPTO.gov API Key

### Step 1: Create USPTO.gov Account

1. Visit: https://account.uspto.gov/profile/create-account
2. Fill out form and create a USPTO.gov account

---

### Step 2: Link ID.me Verification

3. Go to https://data.uspto.gov/myodp/landing
4. Choose which option fits your situation:

**Option A:** I have a USPTO.gov account, but... **"I need to link my ID.me account"**

**Option B:** I have a USPTO.gov account, but... **"I don't have an ID.me account"**

**About ID.me:**
- ID.me is a non-government account provider that contracts with government and non-government organizations
- You will need to have identification documents ready
- Verification options: Self-service or Video Call
- See: https://help.id.me/hc/en-us/articles/360051696334-Upload-your-ID-documents-to-ID-me

![ID.me Verification Options](documentation_photos/USPTO-API_1.jpg)

---

### Step 3: Access Your API Key

5. Once both your USPTO.gov account and ID.me verification are complete, return to https://data.uspto.gov/myodp/landing
6. Click the button **"Log in using USPTO.gov account"** in the section "I have a USPTO.gov account, and it's verified with ID.me"

![USPTO Login Button](documentation_photos/USPTO-API_2.jpg)

7. Once logged in, you should see your API Key displayed on the dashboard

![USPTO API Key Dashboard](documentation_photos/USPTO-API_3.jpg)

---

### Step 4: Secure Storage

8. Record the API key in a secure location
   - **Important**: USPTO does not provide a way to change your API key
   - Safeguard this key carefully - treat it like a password

9. When running the deployment script, paste the API key when prompted:
   ```
   Enter your USPTO API key:
   ```

---

## Mistral API Key (for OCR)

### Step 1: Create Account

1. Visit: https://v2.auth.mistral.ai/login
2. Sign up using one of these methods:

   **Option A:** Link to your existing Apple, Google, or Microsoft account

   **OR**

   **Option B:** Enter an email address:
   - Fill out the registration form
   - Receive verification email
   - Enter the code from the email

![Mistral Login Options](documentation_photos/Mistral_API_1.jpg)

---

### Step 2: Organization Setup

3. Go to https://admin.mistral.ai/ and login
4. Create your organization
5. Read and accept the Terms of Service and Privacy Policy

![Mistral Organization Setup](documentation_photos/Mistral_API_2.jpg)

---

### Step 3: Choose a Plan

6. Navigate to API Keys section
7. Click **"Choose a plan"**

![Choose Plan Button](documentation_photos/Mistral_API_3.jpg)

8. Review available plans and select the one that fits your needs

![Mistral Plans](documentation_photos/Mistral_API_4.jpg)

9. Read and accept the Terms of Service and Privacy Policy (only if you agree)

---

**Important Information Governance Note:**

The USPTO PTAB MCP server (and all of the author's USPTO MCP servers) only use Mistral OCR to have the LLM read **publicly available USPTO documents**. This usage should not raise information governance concerns.

However, if you use the API key separately outside the scope of the USPTO PTAB MCP to:
- Scan and OCR client documents
- Use other Mistral API endpoints (e.g., chat API)

Then review the plan you selected against its terms of service. Mistral's entry-level plan states: **"API requests may be used to improve our services"**, which may not be appropriate for client material.

---

### Step 4: Verify Phone Number

10. Verify your phone number

![Phone Verification](documentation_photos/Mistral_API_5.jpg)

---

### Step 5: Generate API Key

11. Return to API Keys section - the **"Create new key"** button should now be clickable

![Create New Key Button](documentation_photos/Mistral_API_6.jpg)

12. Fill out the key creation form:
    - **Key name**: Descriptive name (e.g., "USPTO PTAB MCP OCR")
    - **Workspace**: Select appropriate workspace (e.g., "Default Workspace")
    - **Expiration**: Optional but recommended for security

![Key Creation Form](documentation_photos/Mistral_API_7.jpg)

13. Click **"Create new key"**

---

### Step 6: Secure Storage

14. Copy your API Key immediately - **it is only displayed once**

![API Key Display](documentation_photos/Mistral_API_8.jpg)

15. Store the key in a secure location

16. When running the deployment script, paste the API key when prompted:
    ```
    Enter your Mistral API key (or press Enter to skip):
    ```
    - You can press Enter to skip if you want to set this up later via the `deploy/manage_api_keys.ps1` script

---

## Summary

✅ **USPTO API Key**: Required, free, no rotation available - safeguard carefully

✅ **Mistral API Key**: Optional. Enables the OCR tier for scanned documents. A self-hosted Docling backend (`DOCLING_SERVE_URL`) is an alternative

Both keys are stored securely by the deployment script:
- **Windows**: Using Windows DPAPI encryption
- **Linux/macOS**: Using restrictive file permissions (chmod 600)

For troubleshooting or key management after installation, use the API key management script:
```powershell
# Windows
C:\Users\[USERNAME]\uspto_ptab_mcp\deploy\manage_api_keys.ps1

# Linux/macOS (future enhancement)
./deploy/manage_api_keys.sh
```

---

## Next Steps

After obtaining your API keys:

1. Run the appropriate deployment script:
   - **Windows**: `.\deploy\windows_setup.ps1`
   - **Linux/macOS**: `./deploy/linux_setup.sh`

2. See **[INSTALL.md](INSTALL.md)** for complete installation instructions

3. See **[USAGE_EXAMPLES.md](USAGE_EXAMPLES.md)** for example workflows

---

**Last Updated**: 2026-01-11
**Version**: 1.0.0
**Status**: Production Ready ✅
