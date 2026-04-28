[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/john-walkoe-uspto-ptab-mcp-badge.png)](https://mseep.ai/app/john-walkoe-uspto-ptab-mcp)

# USPTO PTAB MCP Server

A high-performance Model Context Protocol (MCP) server for the USPTO Patent Trial and Appeal Board (PTAB) Open Data Portal API with token-saving **context reduction** capabilities, **hybrid document extraction**, and **seamless cross-MCP integration** for complete patent lifecycle analysis.

[![Platform Support](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![API](https://img.shields.io/badge/API-USPTO%20PTAB%20Open%20Data%20Portal-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[📥 Installation Guide](INSTALL.md)** | Complete cross-platform setup with automated scripts |
| **[🔑 API Key Guide](API_KEY_GUIDE.md)** | Step-by-step instructions for obtaining USPTO and Mistral API keys with screenshots |
| **[📖 Usage Examples](USAGE_EXAMPLES.md)** | Function examples, workflows, and integration patterns |
| **[🎯 Prompt Templates](PROMPTS.md)** | Detailed guide to sophisticated prompt templates for legal & research workflows |
| **[⚙️ Field Customization](CUSTOMIZATION.md)** | Comprehensive guide to customizing field sets for optimal context reduction |
| **[🔒 Security Guidelines](SECURITY_GUIDELINES.md)** | Comprehensive security best practices |
| **[🛡️ Security Scanning](SECURITY_SCANNING.md)** | Automated secret detection and prompt injection protection guide |
| **[🧪 Testing Guide](tests/README.md)** | Test suite documentation and API key setup |
| **[🔄 MCP Update Guide](MCP_UPDATE_GUIDE.md)** | Instructions for updating existing USPTO MCPs for PTAB integration |
| **[⚖️ License](LICENSE)** | MIT License terms and conditions |

---

## 📢 Important: API Transition Update (January 2026)

**Why This PTAB MCP Was Delayed**

The release of this USPTO PTAB MCP was delayed due to a major API transition by the USPTO. The original version in development used the **USPTO Developer Hub API's PTAB Endpoints** (developer.uspto.gov), which were **officially decommissioned on January 6, 2026**. See the official [USPTO PTAB Transition Guide](https://data.uspto.gov/apis/transition-guide/ptab) for details.

**Action Required: Update Other USPTO MCPs**

If you installed any of the author's other USPTO MCP servers **before January 19, 2026**, you should update them to benefit from enhanced PTAB integration. While the existing MCPs will continue to work without updates, updating (especially **Patent File Wrapper MCP**) is highly recommended for optimal centralized proxy support and cross USPTO Workflows involving PTAB.

**⚠️ IMPORTANT**: If you plan to install this PTAB MCP, it is **highly recommended to install (or update if previously installed) Patent File Wrapper (PFW) MCP first** before installing PTAB. The updated PFW includes essential centralized proxy enhancements that enable PTAB document downloads through PFW's unified proxy server.

**📖 See the complete [MCP Update Guide](MCP_UPDATE_GUIDE.md) for:**

- What changed in each MCP
- Step-by-step update instructions (Git and manual ZIP methods)
- Benefits of updating (centralized proxy, corrected tool references)
- Troubleshooting common update issues

---

## ⚡ Quick Start

### Windows Install

**Run PowerShell as Administrator**, then:

```powershell
# Navigate to your user profile
cd $env:USERPROFILE

# If git is installed:
git clone https://github.com/john-walkoe/uspto_ptab_mcp.git
cd uspto_ptab_mcp

# If git is NOT installed:
# Download and extract the repository to C:\Users\YOUR_USERNAME\uspto_ptab_mcp
# Then navigate to the folder:
# cd C:\Users\YOUR_USERNAME\uspto_ptab_mcp

# The script detects if uv is installed and if it is not it will install uv - https://docs.astral.sh/uv

# Run setup script (sets execution policy for this session only):
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
.\deploy\windows_setup.ps1

# View INSTALL.md for sample script output.
# Close Powershell Window.
# If choose option to "configure Claude Desktop integration" during the script then restart Claude Desktop
```

The PowerShell script will:

- ✅ Check for and auto-install uv (via winget or PowerShell script)
- ✅ Install dependencies and create executable
- ✅ Prompt for USPTO API key (required) and Mistral API key (optional) or Detect if you had installed the developer's other USPTO MCPs and ask if want to use existing keys from those installation.
- 🔒 **If entering in API keys, the script will automatically store API keys securely using Windows DPAPI encryption**
- ✅ Ask if you have [USPTO PFW MCP](https://github.com/john-walkoe/uspto_pfw_mcp) already installed, and if so will used the USPTO PFW MCP's default centralized proxy
- ✅ Ask if you want Claude Desktop integration configured
- 🔒 **Offer secure configuration method (recommended) or traditional method (API keys in plain text in the MCP JSON file)**
- ✅ Backups and then automatically merge with existing Claude Desktop config (preserves other MCP servers)
- ✅ Provide installation summary and next steps

### Claude Desktop Configuration - Manual installs

```json
{
  "mcpServers": {
    "uspto_ptab": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/Users/YOUR_USERNAME/uspto_ptab_mcp",
        "run",
        "ptab-mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_USPTO_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "CENTRALIZED_PROXY_PORT": "none",
        "PTAB_PROXY_PORT": "8083"
      }
    }
  }
}
```

**Proxy Configuration Notes:**

- **CENTRALIZED_PROXY_PORT**:
  - Set to `"none"` for standalone use (not recommended)
  - Set to 8080 When USPTO PFW MCP is installed and PFW is using its default port for the local proxy. (If PFW is not using its default port change this value to match)
- **PTAB_PROXY_PORT**: Local proxy port (default: `8083`, avoids conflict with PFW on `8080`)
  - Only used in standalone mode (no PFW MCP detected)
  - When PFW MCP is installed, PTAB automatically uses PFW's centralized proxy (port `8080`), but will fall back to PTAB's local proxy port
  - **Centralized Proxy Benefits**: Single port for all USPTO MCPs, 7-day persistent links, unified rate limiting

**For detailed installation, manual setup, and troubleshooting**, see **[INSTALL.md](./INSTALL.md)**

## 🔑 Key Features

- **⚙️ User-Customizable Fields** - Configure field sets through YAML without code changes
- **🎯 Context Reduction** - Get focused responses instead of massive API dumps (80-99% reduction)
- **📊 Progressive Disclosure Strategy** - Minimal discovery → Balanced analysis → Document extraction
- **🔍 Three Data Types** - Specialized search tools for Trials (IPR/PGR/CBM), Appeals (Ex Parte), and Interferences
- **🆕 Tool Search Optimization** - Server instructions guide Claude to efficiently discover tools on-demand, reducing context window usage by 70-85% when tool search is enabled ([beta feature](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool))
- **✨ Intelligent Document Extraction** - Auto-optimized hybrid extraction (free PyPDF2 → Mistral OCR fallback) with secure browser downloads
- **🆕 Centralized Proxy Integration** - Auto-detects PFW MCP and uses unified proxy (port 8080) for persistent links and cross-MCP downloads
- **🌐 Secure Browser Downloads** - Click proxy URLs to download PDFs directly while keeping API keys secure
- **📁 Enhanced Filenames** - Professional format with trial metadata: `PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf`
- **👁️ Advanced OCR Capabilities** - Extract text for LLM use from scanned PDFs using Mistral OCR when needed
- **💰 Mistral OCR Cost Transparency** - Real-time cost calculation when using Mistral OCR
- **🔐 Secure API Key Storage** - Optional Windows DPAPI encryption keeps API keys secure (no plain text in config files)
- **🚀 High Performance** - Retry logic with exponential backoff, rate limiting compliance
- **🛡️ Production Ready** - Enhanced error handling, automated log sanitization, persistent audit trail with secure file permissions
- **🔒 Enterprise Security** - SafeLogger auto-masks sensitive data, file-based logging (10MB rotation), separate security logs for compliance
- **💻 Cross-Platform** - Works seamlessly on Linux and Windows
- **📋 Complete API Coverage** - All USPTO PTAB Open Data Portal endpoints supported
- **🔗 Cross-MCP Integration** - Seamless integration with Patent File Wrapper, FPD, Citations, and Pinecone MCPs for complete lifecycle analysis

### Workflow Design - All Performed by the LLM with Minimal User Guidance

**User Requests the following:**

- *"Find all IPR proceedings for Apple Inc filed in 2024"*
- *"Show me Final Written Decisions for patent 8524787"*
- *"Get me the institution decisions for IPR2024-00123"*
- *"Research this company's PTAB challenge record and correlate with prosecution history"* - * Requires that the USPTO Patent File Wrapper (PFW) be installed - [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) and also recommended to ask LLM to perform a ptab_get_guidance tool call prior to this or any cross MCP prompt (see quick reference chart for section selection, additional details in [Usage Examples](USAGE_EXAMPLES.md))
- *"Analyze this technology area's IPR success rates and citation patterns"*

**LLM Performs these steps:**

**Step 1: Discovery (Minimal)** → **Step 2: Selection and Analysis (Balanced - Optional)** → **Step 3: Detailed Trial Review** → **Step 4 (Optional): Select specific trial documents for examination** → **Step 5 (Optional): Retrieve document_id(s) from documents list** → **Step 6 (Optional): Document Extraction for LLM use and/or Download Links of PDFs for user's use**

The field configuration supports an optimized research progression:

1. **Discovery (Minimal)** returns 50-100 trials efficiently without document bloat
2. **Selection and Analysis (Balanced - Optional)** from the retrieved select likely trial(s). Optional balanced search(es) performed if needed in advanced workflows and/or cross-MCP workflows with Patent File Wrapper or FPD
3. **Detailed Trial Review** via `search_trials_complete` for selected trials with complete structured data for LLM's use in analysis
4. **Select specific trial documents for examination** (Optional) e.g. Final Written Decisions, Institution Decisions, Petitions
5. **Retrieve document_id(s) from documents list** (Optional) use `ptab_get_documents` to get the document_id(s)
6. **Document Extraction for LLM use and/or Download Links** (Optional) Document extraction via intelligent hybrid tool that auto-optimizes for cost and quality, and Downloads of the documents as PDFs uses URLs from an HTTP proxy that obscures the USPTO's API key from chat history

## 🎯 Prompt Templates

This MCP server includes sophisticated AI-optimized prompt templates for complex PTAB workflows. For detailed documentation on all templates, features, and usage examples, see **[PROMPTS.md](PROMPTS.md)**.

### Quick Template Overview

| Category | Templates | Purpose |
|----------|-----------|---------|
| **Legal Analysis** | `/trial_precedent_research`, `/ipr_challenge_defense_PFW`, `/portfolio_ptab_risk_assessment_PFW_FPD` | Litigation research, defensive strategy, portfolio risk assessment |
| **Research & Prosecution** | `/prior_art_board_decision_mining`, `/ptab_prior_art_validation_PFW_CITATIONS`, `/technology_landscape_ptab_analysis_PFW` | Prior art research, examiner citation validation, competitive intelligence |
| **Document Management** | `/complete_trial_litigation_package`, `/trial_timeline_analysis`, `/complete_prosecution_lifecycle_PFW_FPD_CITATIONS` | Organized retrieval, timeline analysis, comprehensive lifecycle workflows |

**Key Features Across All Templates:**

- **Enhanced Input Processing** - Flexible identifier support (trial numbers, patent numbers, party names)
- **Smart Validation** - Automatic format detection and guidance
- **Cross-MCP Integration** - Seamless workflows with PFW, FPD, Citations, and Pinecone MCPs
- **Context Optimization** - Token reduction through progressive disclosure

## 📊 Available Functions

### Search Functions (9 Focused Tools - 3 per Data Type)

#### Trials Search Tools (IPR, PGR, CBM)

| Function (Display Name) | Context Reduction | Use Case |
|----------|------------------|----------|
| `search_trials_minimal` (Search trials minimal) | typical 95-99% | Ultra-fast trial discovery (user-customizable minimal fields) |
| `search_trials_balanced` (Search trials balanced) | typical 85-95% | Comprehensive trial analysis (no documentBag) |
| `search_trials_complete` (Search trials complete) | typical 80-90% | Complete trial data for detailed examination |

#### Appeals Search Tools (Ex Parte Appeals)

| Function (Display Name) | Context Reduction | Use Case |
|----------|------------------|----------|
| `search_appeals_minimal` (Search appeals minimal) | typical 95-99% | Ultra-fast appeal discovery (user-customizable minimal fields) |
| `search_appeals_balanced` (Search appeals balanced) | typical 85-95% | Comprehensive appeal analysis (no documentBag) |
| `search_appeals_complete` (Search appeals complete) | typical 80-90% | Complete appeal data for detailed examination |

#### Interferences Search Tools

| Function (Display Name) | Context Reduction | Use Case |
|----------|------------------|----------|
| `search_interferences_minimal` (Search interferences minimal) | typical 95-99% | Ultra-fast interference discovery (user-customizable minimal fields) |
| `search_interferences_balanced` (Search interferences balanced) | typical 85-95% | Comprehensive interference analysis (no documentBag) |
| `search_interferences_complete` (Search interferences complete) | typical 80-90% | Complete interference data for detailed examination |

## Search Strategies

### Specialized Search Strategies

- **IPR/PGR/CBM Analysis** - Use `search_trials_*` tools to analyze inter partes review, post-grant review, and covered business method proceedings
- **Ex Parte Appeal Analysis** - Use `search_appeals_*` tools to research PTAB appeal decisions and examiner reversal patterns
- **Interference Proceedings** - Use `search_interferences_*` tools to analyze priority disputes between inventors
- **Cross-MCP Integration** - Link PTAB data with PFW prosecution history using `applicationNumberText` and patent numbers
- **Red Flag Identification** - Focus on institution decisions, final written decisions, and settlement patterns for litigation risk assessment

### Query Examples

```python
# Find IPR proceedings for specific patent
search_trials_minimal(
    patent_number="8524787",
    trial_type="IPR",
    limit=50
)

# Technology area IPR analysis
search_trials_balanced(
    petitioner_name="Apple Inc",
    filing_date_from="2020-01-01",
    filing_date_to="2024-12-31",
    limit=100
)

# Cross-MCP workflow example
# 1. Find patents with PFW
# 2. Check PTAB challenge history
search_trials_minimal(
    patent_number=patent_from_pfw,
    limit=20
)
```

### Document Processing Functions

| Function (Display Name) | Purpose | Requirements |
|----------|----------|----------|
| `ptab_get_documents` (Get trial documents) | Full docket access for any PTAB proceeding with pagination, sort, and filtering. Trials use POST search endpoint (true count, `next_offset`); appeals/interferences use GET. | USPTO_API_KEY |
| `ptab_get_document_content` (PTAB get document content) | Intelligent document extraction with cost transparency | USPTO_API_KEY (+ MISTRAL_API_KEY for OCR fallback) |
| `ptab_get_document_download` (PTAB get document download) | Secure browser-accessible download URLs with enhanced filenames | USPTO_API_KEY |

### Document Processing Capabilities

- **Document List Tier (`ptab_get_documents`)**: Full docket access for all PTAB proceeding types
  - **Universal identifier support** - Works with trial numbers, appeal numbers, and interference numbers
  - **identifier_type parameter** - Specify "trial", "appeal", or "interference" for correct routing
  - **Full pagination for trials** - Uses POST search endpoint (`trials/documents/search`); returns true `total_documents` count (e.g. 105 for a heavily-litigated IPR) and `next_offset` hint. The legacy GET endpoint was silently capped at 25 documents.
  - **`offset` + `limit` parameters** - Page through the complete docket: `offset=0, limit=25` → first 25; `offset=25, limit=25` → next 25, etc.
  - **`sort_order` parameter** - `"asc"` returns oldest-first (Petition, POPR, early exhibits); `"desc"` (default) returns newest-first (FWD, Sur-Reply, hearing transcripts)
  - **`document_title` filter** - Case-insensitive substring match on `documentTypeDescriptionText` (e.g. `document_title='Final Written Decision'`, `document_title='Patent Owner Response'`). Matches the description field, not the title field.
  - **`document_category` filter** - Coarse category filter: PETITION, RESPONSE, ORDER, DECISION, MOTION, FINAL
  - **`filing_party` filter** - Filter by BOARD, PETITIONER, or PATENT OWNER
  - **LLM-optimized parsing** - Extracts document IDs, descriptions, filing dates, filing party
  - **Known API limitation** - The Petition (Paper 1) and Institution Decision may not be indexed by the search endpoint in some proceedings. If critical early documents are missing after paginating through all results, use the trial ZIP download (available via `search_trials_balanced` → `fileDownloadURI`) which contains the complete docket.
- **Intelligent Extraction Tier (`ptab_get_document_content`)**: Hybrid auto-optimized extraction
  - **Smart method selection** - Automatically tries PyPDF2 first (free), falls back to Mistral OCR (API key needed) when needed
  - **Cost optimization** - Only pay for OCR when PyPDF2 extraction fails quality check
  - **Quality detection** - Automatically determines if extraction is usable or requires OCR
  - **Transparent reporting** - Shows which method was used and associated costs
  - **Unified interface** - Single tool handles all PTAB document types (eliminates tool confusion)
  - **Advanced capabilities** - Extracts text from scanned documents using Mistral OCR
  - **Cost** - Free for text-based PDFs, ~$0.001-$0.003 per document for scanned OCR using Mistral
- **Browser Download Tier (`ptab_get_document_download`)**: Secure proxy downloads with enhanced filenames
  - **Click-to-download** URLs that work directly in any browser
  - **Centralized proxy integration** - If set up, auto-detects PFW MCP and uses unified proxy (port 8080) for all USPTO documents downloads, will fall back to local proxy if issues detected with centralized proxy.
    - **Persistent links** - 7-day encrypted links when using PFW centralized proxy (work across MCP restarts)
    - **Unified architecture** - Single HTTP proxy (port 8080) for all USPTO MCPs when PFW installed
    - **Standalone fallback** - Local proxy (port 8083) when PFW not detected
  - **Enhanced filenames** - Professional format with trial metadata
    - Format: `PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf`
    - Chronological sorting by trial filing date
    - Instant context for patent attorneys and file management
  - **API key security** - USPTO credentials never exposed in chat history or browser
  - **Rate limiting compliance** - Automatic enforcement of USPTO's download limits

### LLM Guidance Function

| Function (Display Name) | Purpose | Requirements |
|----------|----------|----------|
| `ptab_get_guidance` (PTAB get guidance) | Context-efficient selective guidance sections (95-99% token reduction) | None |

#### Context-Efficient Guidance System

**NEW: `ptab_get_guidance` Tool** - Solves MCP Resources visibility problem with selective guidance sections:

**🎯 Quick Reference Chart** - Know exactly which section to call:

- 🔍 "Find trials by company/patent/date" → `ptab_get_guidance("tools")`
- 📄 "Download trial documents" → `ptab_get_guidance("documents")`
- 🔖 "Understand trial types (IPR/PGR/CBM)" → `ptab_get_guidance("tools")`
- 🤝 "Correlate trials with prosecution" → `ptab_get_guidance("workflows_pfw")`
- 🚩 "FPD petition + PTAB patterns" → `ptab_get_guidance("workflows_fpd")`
- 📊 "Citation quality + PTAB correlation" → `ptab_get_guidance("workflows_citations")`
- 🧠 "Research MPEP guidance with Assistant" → `ptab_get_guidance("workflows_pinecone")`
- 🏢 "Complete portfolio due diligence" → `ptab_get_guidance("workflows_complete")`
- ⚙️ "Progressive disclosure strategy" → `ptab_get_guidance("tools")`
- 💰 "Reduce extraction costs" → `ptab_get_guidance("cost")`

The tool provides specific workflows, field recommendations, API call optimization strategies, anti-patterns to avoid, and cross-MCP integration patterns for maximum efficiency. See [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) for detailed examples and integration workflows.

### Utility Functions

| Function (Display Name) | Purpose | Requirements |
|----------|----------|----------|
| `ptab_get_field_configs` (Get field configs) | View current YAML field configuration | None |
| `ptab_validate_identifiers` (Validate identifiers) | Validate trial/appeal/interference numbers | None |

## 💻 Usage Examples & Integration Workflows

For comprehensive usage examples, including:

- **Trial searches** (patent number, petitioner name, filing dates)
- **Appeal analysis** (art unit, technology center, decision outcomes)
- **Interference proceedings** (party analysis, priority disputes)
- **Advanced document filtering** (document types, selective downloads)
- **Cross-MCP integration workflows** (PTAB + PFW + FPD + Citations + Pinecone)
- **Complete lifecycle due diligence** examples
- **Litigation research patterns**
- **IPR success rate analysis**
- **Cost optimization strategies**

See the detailed **[USAGE_EXAMPLES.md](USAGE_EXAMPLES.md)** documentation.

## 🔧 Field Customization

The MCP server supports user-customizable field sets through YAML configuration for optimal context reduction. You can modify field sets without changing any code!

**For comprehensive field customization documentation, see [CUSTOMIZATION.md](CUSTOMIZATION.md).**

### Quick Start

1. **Edit** `field_configs.yaml` in the project root directory
2. **Uncomment fields** you want by removing the `#` symbol
3. **Save and restart** Claude Desktop - changes take effect on restart

### Available Field Sets

**Three data types with progressive disclosure:**
- **Trials** (IPR/PGR/CBM): minimal (12 fields) → balanced (30-50) → complete (all)
- **Appeals** (Ex Parte): minimal (9 fields) → balanced (25-40) → complete (all)
- **Interferences**: minimal (6 fields) → balanced (20-30) → complete (all)

### Example: Litigation Research Field Set

```yaml
trials_minimal:
  fields:
    - trialNumber                                    # IPR2024-00123
    - patentOwnerData.applicationNumberText          # → PFW integration
    - patentOwnerData.patentNumber                   # Patent number
    - regularPetitionerData.realPartyInInterestName # Petitioner
    - trialMetaData.trialStatusCategory             # Status
```

**See [CUSTOMIZATION.md](CUSTOMIZATION.md) for:**
- Complete field reference for all data types
- Token reduction strategies
- Cross-MCP integration patterns
- Custom field set examples
- Troubleshooting guide

## 🔗 Cross-MCP Integration

This MCP is designed to work seamlessly with other USPTO MCPs and knowledge bases for comprehensive patent lifecycle analysis:

### Related USPTO MCP Servers

| MCP Server | Purpose | GitHub Repository |
|------------|---------|-------------------|
| **USPTO Patent File Wrapper (PFW)** | Prosecution history & documents | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) |
| **USPTO Final Petition Decisions (FPD)** | Petition decisions during prosecution | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp.git) |
| **USPTO Enriched Citation** | AI-extracted citation intelligence from Office Actions mailed Oct 2017-present | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp.git) |
| **Pinecone Assistant MCP** | Patent law knowledge base with AI-powered chat and citations (MPEP, examination guidance) - 1 API key, limited free tier | [pinecone_assistant_mcp](https://github.com/john-walkoe/pinecone_assistant_mcp.git) |
| **Pinecone RAG MCP** | Patent law knowledge base with custom embeddings (MPEP, examination guidance) - Requires Pinecone + embedding model, monthly resetting free tier | [pinecone_rag_mcp](https://github.com/john-walkoe/pinecone_rag_mcp.git) |

### Integration Overview

The **Patent Trial and Appeal Board (PTAB) MCP** provides access to post-grant proceedings and appeal decisions, tracking patent challenges after issuance. When combined with the other MCPs, it enables:

- **PTAB + PFW**: Cross-reference PTAB proceedings with prosecution history for litigation research
- **PTAB + FPD**: Correlate petition red flags with post-grant challenge patterns
- **PTAB + Citations**: Analyze examiner citation quality in patents later challenged at PTAB
- **PTAB + Pinecone (Assistant or RAG)**: Research MPEP guidance and legal standards before extracting expensive PTAB documents
- **PFW + FPD + PTAB**: Complete patent lifecycle tracking from filing through post-grant challenges
- **PFW + FPD + PTAB + Citations**: Comprehensive due diligence with prosecution, petitions, citations, and challenges

### Key Integration Patterns

**Cross-Referencing Fields:**

- `patentOwnerData.applicationNumberText` - Primary key linking PTAB proceedings to PFW prosecution
- `patentOwnerData.patentNumber` - Patent number linking to Citations and other MCPs
- `patentOwnerData.groupArtUnitNumber` - Art unit analysis across all MCPs
- `regularPetitionerData.realPartyInInterestName` - Party matching across MCPs
- `patentOwnerData.technologyCenterNumber` - Technology classification analysis

**Progressive Workflow:**

1. **Discovery** (PTAB): Find relevant IPR/PGR/CBM proceedings using minimal search
2. **Prosecution Context** (PFW): Cross-reference challenged patents with prosecution history
3. **Citation Intelligence** (Citations): Analyze examiner citation quality for challenged patents (Oct 2017+ only)
4. **Petition Check** (FPD): Review prosecution procedural history for red flags
5. **Knowledge Research** (Pinecone): Research MPEP guidance if available (Assistant MCP: `assistant_context` / RAG MCP: `semantic_search`)
6. **Document Analysis** (PTAB): Extract targeted PTAB documents for board reasoning
7. **Risk Scoring**: Quantify patent vulnerability based on PTAB patterns, prosecution quality, and citation analysis

For detailed integration workflows, cross-referencing examples, and complete use cases, see [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md#cross-mcp-integration-workflows).

## 🆕 Centralized Proxy Integration (PFW + PTAB)

When both PFW and PTAB MCPs are installed, PTAB automatically integrates with PFW's centralized proxy for unified document management:

**Architecture Benefits:**

- **Single Port** - One HTTP server (port 8080) for all USPTO document downloads
- **Persistent Links** - 7-day encrypted links via PFW's SQLite database (work across MCP restarts)
- **Unified Rate Limiting** - Shared USPTO limits across all MCPs
- **Cross-MCP Caching** - PFW caches documents from all USPTO MCPs for faster access
- **Automatic Detection** - PTAB detects PFW at startup and switches to centralized mode

**How It Works:**

1. PTAB extracts PDF download URL from USPTO API response
2. PTAB generates enhanced filename: `PTAB-{date}_{trial}_{patent}_{description}.pdf`
3. PTAB registers document with PFW: `POST /register-ptab-document` (includes enhanced filename)
4. PFW stores metadata in database (trial_number, download_url, api_key, enhanced_filename)
5. PTAB returns download link: `http://localhost:8080/download/{trial_number}/{doc_id}`
6. User clicks link → PFW fetches from USPTO → streams PDF with enhanced filename
7. Link persists for 7 days and works across MCP restarts

**Standalone Mode:**

- Without PFW: PTAB uses local proxy (port 8083) for immediate session-based downloads
- Enhanced filenames still work (same generation logic used locally)
- Graceful fallback ensures PTAB works independently with full filename functionality

## 📈 Performance Comparison

| Method | Response Size | Context Usage | Features |
|--------|---------------|---------------|----------|
| **Direct curl** | ~200KB+ | High | Raw API access |
| **MCP Balanced** | ~30KB | Medium | Key fields for analysis |
| **MCP Minimal** | ~5KB | Very Low | Essential data only |
| **Custom Fields** | ~2KB | Ultra-Low | 2-3 fields only (99% reduction) |

## 🧪 Testing

### Core Tests (Essential)

**With uv (Recommended):**
```bash
# Test core functionality
uv run python tests/test_basic.py

# Expected: ALL TESTS PASSED!
```

**With traditional Python:**
```bash
python tests/test_basic.py
```

### Expected Outputs

**test_basic.py:**
```
[OK] Settings imported successfully
[OK] FieldManager imported successfully
[OK] PTABClient initialized successfully
ALL TESTS PASSED!
```

**Configuration Files:**
- **pytest.ini**: Configures pytest for async tests
  - Enables `asyncio_mode = auto` for seamless async/await testing
  - Sets test discovery patterns and verbosity
  - Located at project root

- **.pre-commit-config.yaml**: Git pre-commit hooks for security
  - Runs `detect-secrets` scan before each commit
  - Prevents accidental API key commits
  - Install with: `pip install pre-commit && pre-commit install`

See [tests/README.md](tests/README.md) for comprehensive testing guide.

## 📁 Project Structure

```
uspto_ptab_mcp/
├── field_configs.yaml             # Root-level field customization (YAML)
├── .pre-commit-config.yaml        # Pre-commit hooks for security scanning
├── .secrets.baseline              # Baseline file for detect-secrets (tracks known secrets)
├── .prompt_injections.baseline    # Baseline file for prompt injection detection
├── pytest.ini                     # Pytest configuration for async tests
├── src/
│   └── ptab_mcp/
│       ├── main.py                 # MCP server with 15 tools
│       ├── __main__.py            # Entry point for -m execution
│       ├── shared_secure_storage.py # Secure API key storage (DPAPI/chmod 600)
│       ├── config/
│       │   ├── field_manager.py   # YAML field configuration management
│       │   ├── settings.py        # Environment configuration
│       │   ├── tool_reflections.py # Sectioned LLM guidance (10 sections, 95-99% token reduction)
│       │   ├── api_constants.py   # API configuration constants (official USPTO rate limits)
│       │   ├── filter_field_mapping.py # Field mapping for search filters
│       │   ├── log_config.py      # Logging configuration (file-based with rotation)
│       │   └── storage_paths.py   # File storage path utilities
│       ├── prompts/               # 11 AI-optimized prompt templates
│       │   ├── __init__.py        # Prompt registration
│       │   ├── trial_precedent_research.py
│       │   ├── complete_trial_litigation_package.py
│       │   ├── prior_art_board_decision_mining.py
│       │   ├── trial_timeline_analysis.py
│       │   ├── ipr_challenge_defense_PFW.py
│       │   ├── ipr_petitioner_portfolio_analysis_PFW.py
│       │   ├── portfolio_ptab_risk_assessment_PFW_FPD.py
│       │   ├── technology_landscape_ptab_analysis_PFW.py
│       │   ├── cross_mcp_patent_intelligence_PFW.py
│       │   ├── ptab_prior_art_validation_PFW_CITATIONS.py
│       │   └── complete_prosecution_lifecycle_PFW_FPD_CITATIONS.py
│       ├── api/
│       │   ├── ptab_client.py      # PTAB API client (ODP API integration)
│       │   └── field_constants.py # Field name constants
│       ├── proxy/
│       │   ├── server.py          # HTTP proxy for secure downloads
│       │   ├── rate_limiter.py    # USPTO rate limiting compliance (5 files/10s)
│       │   ├── centralized_integration.py # PFW proxy integration
│       │   └── models.py          # Pydantic models for proxy
│       ├── shared/
│       │   ├── error_utils.py     # Error handling utilities
│       │   ├── circuit_breaker.py # Circuit breaker pattern
│       │   ├── internal_auth.py   # Internal authentication (JWT)
│       │   ├── dpapi_crypto.py    # Windows DPAPI encryption
│       │   ├── cache.py           # Caching utilities
│       │   ├── log_sanitizer.py   # Log sanitization (API key masking)
│       │   └── safe_logger.py     # SafeLogger wrapper (auto-sanitization)
│       ├── services/
│       │   └── ocr_service.py     # OCR quality detection and processing
│       ├── validation/
│       │   └── validators.py      # Input validation functions
│       └── util/
│           ├── response_formatter.py # Response formatting
│           └── filter_builder.py  # Search filter construction
├── deploy/
│   ├── linux_setup.sh            # Linux deployment script (chmod 600 security)
│   ├── windows_setup.ps1         # PowerShell deployment script (DPAPI)
│   ├── manage_api_keys.ps1       # API key management utilities
│   ├── Validation-Helpers.psm1   # PowerShell validation module
│   ├── validation-helpers.sh     # Bash validation helpers
│   ├── merge_ptab_to_claude_json.py # Claude Code config merger (Python)
│   └── quick_merge_claude_config.sh # Claude Code config merger (Bash wrapper)
├── tests/
│   ├── test_basic.py             # Core functionality test
│   ├── test_integration.py       # Integration tests
│   └── README.md                 # Testing documentation
├── .security/                     # Security scanning tools (gitignored)
│   ├── check_prompt_injections.py # Prompt injection detector
│   ├── ptab_prompt_injection_detector.py # Detection engine
│   ├── test_benign.txt           # Test benign inputs
│   ├── test_malicious.txt        # Test malicious inputs
│   ├── VALIDATION_REPORT.md      # Security validation results
│   └── README.md                 # Security tools documentation
├── reference/
│   ├── PTAB_swagger.yaml         # API specification
│   ├── PTAB-to-ODP-PTAB-API-Mapping.txt # Legacy API mapping
│   └── Document_Descriptions_List.csv # Document type reference
├── documentation_photos/          # Visual documentation
│   ├── Prompts-Step1.jpg         # Prompt template usage guides
│   ├── Prompts-Step2.jpg
│   ├── Prompts-Step3.jpg
│   ├── Prompts-Step4.jpg
│   └── Prompts-Step5.jpg
├── pyproject.toml                 # Package configuration
├── uv.lock                        # uv lockfile (gitignored)
├── README.md                      # This file
├── INSTALL.md                     # Comprehensive installation guide
├── CUSTOMIZATION.md              # Field customization guide
├── USAGE_EXAMPLES.md             # Function examples and workflows
├── PROMPTS.md                    # Prompt templates documentation
├── API_KEY_GUIDE.md              # API key setup guide
├── SECURITY_GUIDELINES.md        # Security best practices (updated 2026-01-17)
├── SECURITY_SCANNING.md          # Automated secret detection guide
└── LICENSE                       # MIT License

Runtime Generated Files (not in repo):
~/.uspto_ptab_mcp/
├── logs/
│   ├── ptab_mcp.log              # Application logs (10MB rotation, 5 backups)
│   └── security.log              # Security events (10MB rotation, 10 backups)
├── .uspto_api_key                # Encrypted USPTO API key (DPAPI/chmod 600)
├── .mistral_api_key              # Encrypted Mistral API key (DPAPI/chmod 600)
└── .uspto_internal_auth_secret   # Internal auth secret (shared across MCPs)
```

## 🔍 Troubleshooting

### Common Issues

#### API Key Issues
- **For Claude Desktop:** API keys in config file are sufficient
- **For test scripts:** Environment variables must be set

**Setting USPTO API Key:**
- **Windows Command Prompt:** `set USPTO_API_KEY=your_key`
- **Windows PowerShell:** `$env:USPTO_API_KEY="your_key"`
- **Linux/macOS:** `export USPTO_API_KEY=your_key`

**Setting Mistral API Key (for OCR):**
- **Windows Command Prompt:** `set MISTRAL_API_KEY=your_key`
- **Windows PowerShell:** `$env:MISTRAL_API_KEY="your_key"`
- **Linux/macOS:** `export MISTRAL_API_KEY=your_key`

#### uv vs pip Issues
- **uv advantages:** Better dependency resolution, faster installs
- **Mixed installation:** Can use both `uv sync` and `pip install -e .`
- **Testing:** Use `uv run` prefix for uv-managed projects

#### Fields Not Returning Data
- **Cause:** Field name not in YAML config
- **Solution:** Edit `field_configs.yaml` to include desired fields

#### Authentication Errors
- **Cause:** Missing or invalid API key
- **Solution:** Verify `USPTO_API_KEY` environment variable or Claude Desktop config
- **API Key Source:** Get free API key from [USPTO Open Data Portal](https://data.uspto.gov/myodp/)

#### MCP Server Won't Start
- **Cause:** Missing dependencies or incorrect paths
- **Solution:** Re-run setup script, restart all PowerShell windows, restart Claude Desktop (or other MCP Client) and verify configuration
- **If problems persist:** Reset the MCP installation (see "Resetting MCP Installation" below)

#### Virtual Environment Issues (Windows Setup)
- **Symptom:** "No pyvenv.cfg file" errors during `windows_setup.ps1`
- **Cause:** Claude Desktop locks `.venv` files when running, preventing proper virtual environment creation
- **Solution:**
  1. Close Claude Desktop completely before running setup script
  2. Remove `.venv` folder: `Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue`
  3. Run `.\deploy\windows_setup.ps1` again

#### Resetting MCP Installation

**If you need to completely reset the MCP installation to run the Windows Quick installer again:**

```powershell
# Navigate to the project directory
cd C:\Users\YOUR_USERNAME\uspto_ptab_mcp

# Remove Python cache directories
Get-ChildItem -Path ./src -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
}

# Remove database files (if any)
Remove-Item ./proxy_documents.db -Force -ErrorAction SilentlyContinue
Remove-Item ./ptab_links.db -Force -ErrorAction SilentlyContinue

# Now you can run the setup script again
.\deploy\windows_setup.ps1
```

**Linux/macOS Reset:**
```bash
# Navigate to the project directory
cd ~/uspto_ptab_mcp

# Remove Python cache directories
find ./src -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove virtual environment and database files
rm -rf .venv
rm -f proxy_documents.db ptab_links.db

# Run setup script again
./deploy/linux_setup.sh
```

### Getting Help

1. Check the test scripts for working examples
2. Review the field configuration in `field_configs.yaml`
3. Verify your Claude Desktop configuration matches the provided templates in INSTALL.md
4. Use `ptab_get_guidance` for workflow-specific guidance

## 🛡️ Security & Production Readiness

### Enhanced Error Handling
- **Retry logic with exponential backoff** - Automatic retries for transient failures (3 attempts with 1s, 2s, 4s delays)
- **Smart retry strategy** - Doesn't retry authentication errors or client errors (4xx)
- **Structured logging** - Request ID tracking for better debugging and monitoring
- **Production-grade resilience** - Handles timeouts, network issues, and API rate limits gracefully
- **Configurable timeouts** - USPTO_TIMEOUT and USPTO_DOWNLOAD_TIMEOUT environment variables for API request tuning

### Security Features
- **🔐 Windows DPAPI Secure Storage** - API keys encrypted with Windows Data Protection API (user-specific encryption)
- **Environment variable API keys** - No hardcoded credentials anywhere in codebase
- **Zero plain text API keys** - Secure storage option eliminates API keys from Claude Desktop config files
- **Cross-platform security** - Automatic fallback to environment variables on non-Windows systems
- **Secure test patterns** - Test files use environment variables with fallbacks
- **Comprehensive .gitignore** - Prevents accidental credential commits
- **Security guidelines** - Complete documentation for secure development practices
- **Automated secret scanning** - GitHub Actions workflows prevent API key leaks (detect-secrets)
- **20+ secret types detected** - AWS keys, GitHub tokens, JWT, private keys, API keys, and more
- **Prompt injection detection** - 70+ pattern detection system protects against AI-specific attacks
- **Baseline management** - Two baseline systems (secrets & prompt injection) track known findings while catching real threats
- **Field name constants** - Eliminates magic strings, reduces typo-based security issues

### Request Tracking & Debugging

All API requests include unique request IDs (8-char UUIDs) for correlation:
```
[a1b2c3d4] Starting POST request to trials/proceedings/search
[a1b2c3d4] Request successful on attempt 1
```

### Documentation
- `SECURITY_GUIDELINES.md` - Comprehensive security best practices
- `SECURITY_SCANNING.md` - Automated secret detection and prevention guide
- `tests/README.md` - Complete testing guide with API key setup
- Enhanced error messages with request IDs for better support

## 📝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License

## ⚠️ Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTY OF ANY KIND.**

**Independent Project Notice**: This is an independent personal project and is not affiliated with, endorsed by, or sponsored by the United States Patent and Trademark Office (USPTO).

The author makes no representations or warranties, express or implied, including but not limited to:

- **Accuracy & AI-Generated Content**: No guarantee of data accuracy, completeness, or fitness for any purpose. Users are specifically cautioned that outputs generated or assisted by Artificial Intelligence (AI) components, including but not limited to text, data, or analyses, may be inaccurate, incomplete, fictionalized, or represent "hallucinations" (confabulations) by the AI model.
- **Availability**: USPTO API and Mistral API dependencies may cause service interruptions.
- **Legal Compliance**: Users are solely responsible for ensuring their use of this software, and any submissions or actions taken based on its outputs, strictly comply with all applicable laws, regulations, and policies, including but not limited to:
  - The latest [Guidance on Use of Artificial Intelligence-Based Tools in Practice Before the United States Patent and Trademark Office](https://www.federalregister.gov/documents/2024/04/11/2024-07629/guidance-on-use-of-artificial-intelligence-based-tools-in-practice-before-the-united-states-patent) (USPTO Guidance).
  - The USPTO's Duty of Candor and Good Faith (e.g., 37 CFR 1.56, 11.303), which includes a duty to disclose material information and correct errors.
  - The USPTO's signature requirements (e.g., 37 CFR 1.4(d), 2.193(c), 11.18), certifying human review and reasonable inquiry.
  - All rules regarding inventorship (e.g., each claimed invention must have at least one human inventor).
- **Legal Advice**: This tool provides data access and processing only, not legal counsel. All results must be independently verified, critically analyzed, and professionally judged by qualified legal professionals.
- **Commercial Use**: Users must verify USPTO and Mistral terms for commercial applications.
- **Confidentiality & Data Security**: The author makes no representations regarding the confidentiality or security of any data, including client-sensitive or technical information, input by the user into the software's AI components or transmitted to third-party AI services (e.g., Mistral API). Users are responsible for understanding and accepting the privacy policies, data retention practices, and security measures of any integrated third-party AI services.
- **Foreign Filing Licenses & Export Controls**: Users are solely responsible for ensuring that the input or processing of any data, particularly technical information, through this software's AI components does not violate U.S. foreign filing license requirements (e.g., 35 U.S.C. 184, 37 CFR Part 5) or export control regulations (e.g., EAR, ITAR). This includes awareness of potential "deemed exports" if foreign persons access such data or if AI servers are located outside the United States.

**LIMITATION OF LIABILITY:** Under no circumstances shall the author be liable for any direct, indirect, incidental, special, or consequential damages arising from use of this software, even if advised of the possibility of such damages.

### USER RESPONSIBILITY: YOU ARE SOLELY RESPONSIBLE FOR THE INTEGRITY AND COMPLIANCE OF ALL FILINGS AND ACTIONS TAKEN BEFORE THE USPTO.

- **Independent Verification**: All outputs, analyses, and content generated or assisted by AI within this software MUST be thoroughly reviewed, independently verified, and corrected by a human prior to any reliance, action, or submission to the USPTO or any other entity. This includes factual assertions, legal contentions, citations, evidentiary support, and technical disclosures.
- **Duty of Candor & Good Faith**: You must adhere to your duty of candor and good faith with the USPTO, including the disclosure of any material information (e.g., regarding inventorship or errors) and promptly correcting any inaccuracies in the record.
- **Signature & Certification**: You must personally sign or insert your signature on any correspondence submitted to the USPTO, certifying your personal review and reasonable inquiry into its contents, as required by 37 CFR 11.18(b). AI tools cannot sign documents, nor can they perform the required human inquiry.
- **Confidential Information**: DO NOT input confidential, proprietary, or client-sensitive information into the AI components of this software without full client consent and a clear understanding of the data handling practices of the underlying AI providers. You are responsible for preventing inadvertent or unauthorized disclosure.
- **Export Controls**: Be aware of and comply with all foreign filing license and export control regulations when using this tool with sensitive technical data.
- **Service Compliance**: Ensure compliance with all USPTO (e.g., Terms of Use for USPTO websites, USPTO.gov account policies, restrictions on automated data mining) and Mistral terms of service. AI tools cannot obtain USPTO.gov accounts.
- **Security**: Maintain secure handling of API credentials and client information.
- **Testing**: Test thoroughly before production use.
- **Professional Judgment**: This tool is a supplement, not a substitute, for your own professional judgment and expertise.

**By using this software, you acknowledge that you have read this disclaimer and agree to use the software at your own risk, accepting full responsibility for all outcomes and compliance with relevant legal and ethical obligations.**

> **Note for Legal Professionals:** While this tool provides access to patent research tools commonly used in legal practice, it is a data retrieval and AI-assisted processing system only. All results require independent verification, critical professional analysis, and cannot substitute for qualified legal counsel or the exercise of your personal professional judgment and duties outlined in the USPTO Guidance on AI Use.

## 🔗 Related Links

- [USPTO Open Data Portal](https://data.uspto.gov/myodp)
- [USPTO PTAB Open Data Portal API](https://api.uspto.gov/api/v1/patent/)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Claude](https://claude.ai)
- [uv Package Manager](https://github.com/astral-sh/uv)
- [Mistral AI](https://mistral.ai/solutions/document-ai)

## 💝 Support This Project

If you find this USPTO PTAB MCP Server useful, please consider supporting the development! This project was developed during my personal time over many hours to provide a comprehensive, production-ready tool for the patent community.

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://paypal.me/walkoe)

Your support helps maintain and improve this open-source tool for everyone in the patent community. Thank you!

## Acknowledgments

- [USPTO](https://www.uspto.gov/) for providing the PTAB Open Data Portal API
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- **[Claude Code](https://claude.ai/code)** for exceptional development assistance, architectural guidance, documentation creation, PowerShell automation, test organization, and comprehensive code development throughout this project
- **[Claude Desktop](https://claude.ai)** for additional development support and testing assistance

---

**Questions?** See [INSTALL.md](INSTALL.md) for complete cross-platform installation guide or review the test scripts for working examples.
