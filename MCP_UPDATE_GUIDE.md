# USPTO MCP Update Guide - January 2026 API Transition

Complete guide for updating existing USPTO MCP installations to support PTAB integration and API migration.

---

## Table of Contents

- [Why This Update Matters](#why-this-update-matters)
- [What Changed](#what-changed)
- [Which MCPs Need Updating](#which-mcps-need-updating)
- [Update Benefits](#update-benefits)
- [How to Update - Git Method](#how-to-update---git-method)
- [How to Update - Manual ZIP Method](#how-to-update---manual-zip-method)
- [Troubleshooting](#troubleshooting)

---

## Why This Update Matters

The USPTO **decommissioned the PTAB API on the Developer Hub on January 6, 2026**, requiring this PTAB MCP to be completely rebuilt using the **Open Data Portal (ODP) API**. During development of the original PTAB MCP (which used the now-defunct Developer Hub API), the author's other MCPs included cross-integration features referencing PTAB tool names and descriptions from that draft version.

**The API transition forced a complete PTAB rewrite**, which resulted in:
- Changed tool names and descriptions
- New architectural patterns
- Enhanced centralized proxy integration

**Bottom line**: If you installed the author's other USPTO MCPs before January 19, 2026, their PTAB integration features reference the old draft PTAB MCP that never went live. Updating ensures accurate cross-MCP workflows.

**⚠️ CRITICAL RECOMMENDATION**: If you plan to install the PTAB MCP, **install (or update if previously installed) Patent File Wrapper (PFW) MCP FIRST** before installing PTAB. The updated PFW includes essential centralized proxy enhancements that enable PTAB to use PFW's unified proxy server for document downloads, providing 7-day persistent links and unified rate limiting.

---

## What Changed

### PTAB MCP (This MCP)

This is a **completely new implementation** built for the ODP API with:

- **New API Endpoints**: Two new endpoint families introduced during USPTO's transition:
  - **Appeals API** (`/api/v1/patent/appeals/*`) - Ex parte appeals to PTAB
  - **Interferences API** (`/api/v1/patent/interferences/*`) - Interference proceedings
- **Enhanced Data Structure**: Improved field organization and response formats
- **Modern Authentication**: Requires X-API-KEY header (get free key from [data.uspto.gov](https://data.uspto.gov/myodp/))

### Patent File Wrapper MCP (PFW)

**Most Important Update** - Enhanced centralized proxy to support PTAB:

- **Centralized Proxy Enhancements**: PTAB document downloads can now use PFW's unified proxy (port 8080)
- **7-Day Persistent Links**: Download URLs remain valid for 7 days across all USPTO MCPs
- **Unified Rate Limiting**: Single rate limiter for all USPTO document downloads
- **Updated Guidance**: Corrected PTAB tool references in cross-MCP workflow prompts

### Final Petition Decisions MCP (FPD)

- **Updated Prompt Templates**: Cross-MCP workflows now reference correct PTAB tool names
- **Corrected Guidance Sections**: Integration examples reflect final PTAB architecture
- **Enhanced Integration**: Seamless workflows combining FPD pre-grant decisions with PTAB post-grant challenges

### Enriched Citation API v3 MCP (Citations)

- **Updated Cross-References**: Citation analysis workflows now reference correct PTAB tools
- **Improved Integration Examples**: Patent relationship analysis combined with PTAB challenge data
- **Note**: Citations MCP still uses Developer Hub API and will migrate to ODP in a future update

---

## Which MCPs Need Updating

| MCP Server | Repository | Update Priority | Reason |
|------------|------------|----------------|---------|
| **USPTO Patent File Wrapper** | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp) | **HIGH** ⚠️ | Centralized proxy support for PTAB downloads |
| **USPTO Final Petition Decisions** | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp) | Medium | Updated prompt templates and tool references |
| **USPTO Enriched Citation API v3** | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp) | Low | Updated integration examples |

**Note**: Your existing MCPs will continue to function without updates. However, updating (especially PFW) is **highly recommended** for optimal PTAB integration.

**⚠️ Installing PTAB MCP for the First Time?** Update PFW **BEFORE** installing PTAB to ensure the centralized proxy is ready to handle PTAB document downloads.

---

## Update Benefits

### Centralized Proxy Support (PFW MCP) - Most Important

- 🔗 **Unified Document Downloads**: PTAB PDFs available through PFW's centralized proxy
- 📅 **7-Day Persistent Links**: Download URLs remain valid for a week (vs. on-demand generation)
- ⚡ **Better Rate Limiting**: Single rate limiter across all USPTO MCPs prevents API throttling
- 🎯 **One Port for All**: All USPTO MCPs share port 8080 (no port conflicts)

### Accurate Cross-MCP Workflows

- 🎯 **Correct Tool Names**: Prompt templates reference actual PTAB tool names (not draft versions)
- 📚 **Updated Examples**: Guidance sections reflect final PTAB MCP architecture
- ⚡ **Seamless Integration**: Tools work together as designed for complete patent lifecycle analysis

### Example Cross-MCP Workflows That Now Work Correctly

**Before Update** (broken references):
```
LLM tries to call: "ptab_search_proceedings_minimal" (doesn't exist - from draft)
```

**After Update** (correct references):
```
LLM calls: "search_trials_minimal" (actual tool in final PTAB MCP)
```

---

## How to Update - Git Method

**Use this method if you originally installed using `git clone`**

### Windows (PowerShell)

```powershell
# Navigate to the MCP directory
cd $env:USERPROFILE\uspto_pfw_mcp

# Pull latest changes from GitHub
git pull origin master

# Update dependencies
uv sync

# Restart Claude Desktop to load updates
# (Close Claude Desktop completely, then reopen)
```

### Linux/macOS (Bash)

```bash
# Navigate to the MCP directory
cd ~/uspto_pfw_mcp

# Pull latest changes from GitHub
git pull origin master

# Update dependencies
uv sync

# Restart Claude Code/Desktop to load updates
```

### Important Notes

- ✅ Your API keys will **NOT** be affected (stored in secure storage, not in repo)
- ✅ Your `field_configs.yaml` customizations will **NOT** be overwritten
- ✅ Your Claude Desktop config remains unchanged
- ✅ Only source code and dependencies are updated

---

## How to Update - Manual ZIP Method

**Use this method if you originally downloaded as a ZIP file**

### Step 1: Download Latest Version

1. Go to the MCP repository (e.g., [https://github.com/john-walkoe/uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp))
2. Click green **"Code"** button
3. Select **"Download ZIP"**
4. Extract to a **temporary location** (e.g., `C:\Temp\uspto_pfw_mcp-master`)

### Step 2: Backup Your Configuration (Optional but Recommended)

**Windows (PowerShell):**
```powershell
# Backup field configurations
copy $env:USERPROFILE\uspto_pfw_mcp\field_configs.yaml $env:USERPROFILE\field_configs_backup.yaml
```

**Linux/macOS (Bash):**
```bash
# Backup field configurations
cp ~/uspto_pfw_mcp/field_configs.yaml ~/field_configs_backup.yaml
```

### Step 3: Selective File Copy

**Copy these files/folders** (overwrites old files):

- ✅ `src/` folder (entire directory)
- ✅ `pyproject.toml`
- ✅ `uv.lock`
- ✅ `deploy/` folder (if updating deployment scripts)
- ✅ `tests/` folder (if you run tests)

**DO NOT COPY** (keeps your settings):

- ❌ `field_configs.yaml` (unless you want to reset to defaults)
- ❌ `.env` (if present - contains custom settings)
- ❌ Any files you've customized

**Windows Example (PowerShell):**
```powershell
# Navigate to your installation directory
cd $env:USERPROFILE\uspto_pfw_mcp

# Copy updated source code
xcopy /E /Y C:\Temp\uspto_pfw_mcp-master\src .\src\

# Copy dependency files
copy /Y C:\Temp\uspto_pfw_mcp-master\pyproject.toml .\
copy /Y C:\Temp\uspto_pfw_mcp-master\uv.lock .\
```

**Linux/macOS Example (Bash):**
```bash
# Navigate to your installation directory
cd ~/uspto_pfw_mcp

# Copy updated source code
cp -r /tmp/uspto_pfw_mcp-master/src/* ./src/

# Copy dependency files
cp /tmp/uspto_pfw_mcp-master/pyproject.toml ./
cp /tmp/uspto_pfw_mcp-master/uv.lock ./
```

### Step 4: Update Dependencies and Restart

**Windows (PowerShell):**
```powershell
cd $env:USERPROFILE\uspto_pfw_mcp
uv sync

# Close Claude Desktop completely, then reopen
```

**Linux/macOS (Bash):**
```bash
cd ~/uspto_pfw_mcp
uv sync

# Restart Claude Code/Desktop
```

---

## Troubleshooting

### Issue: `git pull` fails with "uncommitted changes"

**Cause**: You modified files in the repository (like `field_configs.yaml`)

**Solution 1** - Stash changes temporarily:
```bash
git stash
git pull origin master
git stash pop
```

**Solution 2** - Backup and reset:
```bash
# Backup your customizations
cp field_configs.yaml field_configs_backup.yaml

# Reset to clean state
git reset --hard origin/master

# Restore your customizations
cp field_configs_backup.yaml field_configs.yaml
```

### Issue: `uv sync` fails with dependency errors

**Solution**: Delete virtual environment and reinstall:

**Windows:**
```powershell
Remove-Item .venv -Recurse -Force
uv sync
```

**Linux/macOS:**
```bash
rm -rf .venv
uv sync
```

### Issue: MCP not showing up in Claude Desktop after update

**Solution**:
1. Verify `uv sync` completed successfully
2. Restart Claude Desktop **completely** (quit, don't just close window)
3. Check Claude Desktop logs:
   - **Windows**: `%APPDATA%\Claude\logs\`
   - **Linux/macOS**: `~/.config/Claude/logs/`

### Issue: API keys not working after update

**Cause**: API keys stored in secure storage, not in repository

**Solution**: Your keys should still work. Test with:

**Windows:**
```powershell
cd $env:USERPROFILE\uspto_pfw_mcp
.\deploy\manage_api_keys.ps1
```

**Linux/macOS:**
```bash
cd ~/uspto_pfw_mcp
uv run python -c "from patent_filewrapper_mcp.shared_secure_storage import get_uspto_api_key; print('Key configured' if get_uspto_api_key() else 'No key found')"
```

### Issue: Cross-MCP workflows still reference old tool names

**Solution**:
1. Verify you updated **all** MCPs (especially PFW)
2. Restart Claude Desktop after updating each MCP
3. Clear conversation and start fresh (LLM may cache old context)

---

## Verification

After updating, verify the update was successful:

### Check Installed Version

**Any MCP:**
```bash
cd ~/uspto_pfw_mcp  # or fpd_mcp, citations_mcp
git log -1 --date=short --pretty=format:"%h - %ad : %s"
```

This shows the latest commit. Compare with GitHub repository to confirm you're up to date.

### Test Cross-MCP Integration

Ask Claude:
```
Use search_trials_minimal to find IPR proceedings for Apple Inc filed in 2024
```

If Claude successfully calls `search_trials_minimal` (and doesn't complain about unknown tools), your update is working.

---

## Need Help?

- **Installation Issues**: See main [INSTALL.md](INSTALL.md) troubleshooting section
- **PTAB MCP Issues**: [GitHub Issues](https://github.com/john-walkoe/uspto_ptab_mcp/issues)
- **PFW MCP Issues**: [GitHub Issues](https://github.com/john-walkoe/uspto_pfw_mcp/issues)
- **FPD MCP Issues**: [GitHub Issues](https://github.com/john-walkoe/uspto_fpd_mcp/issues)
- **Citations MCP Issues**: [GitHub Issues](https://github.com/john-walkoe/uspto_enriched_citation_mcp/issues)

---

**Last Updated**: January 18, 2026
**Applies to**: MCPs installed before January 19, 2026
