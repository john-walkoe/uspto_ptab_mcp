"""MCP App HTML views for USPTO PTAB MCP.

Two views, adapted from the PFW reference implementation:
- SEARCH_RESULTS_HTML: one view for all nine search tools; normalizes the
  three proceeding shapes (trials / appeals / interferences) via the
  response envelope's data_type key.
- DOWNLOADS_HTML: recent downloads panel fed primarily by ontoolresult
  (iframes cannot fetch() localhost — Lesson 23); /api/recent-downloads
  fetch is a secondary Refresh path only.
"""

# ---------------------------------------------------------------------------
# View 1: Search Results (used by all search_* tools)
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PTAB Search Results</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #3d2a6b; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .badge { background: #7a5fd0; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.summary-bar { background: #efe9fe; border-bottom: 1px solid #d5c8f7; padding: 7px 14px; font-size: 12px; color: #3d2a6b; display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.summary-bar span { font-weight: 600; }

.filter-bar { background: #f6f3fd; border: 1px solid #d5c8f7; border-radius: 6px; margin: 8px 14px 0; padding: 7px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sort-bar { background: #f6f3fd; border: 1px solid #d5c8f7; border-radius: 6px; margin: 6px 14px 0; padding: 5px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.field-notice { background: #fffbe6; border-bottom: 1px solid #ffe58f; padding: 5px 14px; font-size: 11px; color: #7d5a00; line-height: 1.5; }
.filter-label { font-size: 10px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; margin-right: 2px; }
.pill { border: 1px solid #d5c8f7; border-radius: 12px; padding: 2px 9px; font-size: 11px; font-weight: 700; cursor: pointer; background: #fff; color: #3d2a6b; transition: all 0.12s; user-select: none; }
.pill:hover { border-color: #7a5fd0; background: #efe9fe; }
.pill.active { background: #3d2a6b; color: #fff; border-color: #3d2a6b; }
.pill-count { font-size: 9px; font-weight: 700; background: #efe9fe; color: #3d2a6b; border-radius: 8px; padding: 0 4px; margin-left: 3px; }
.pill.active .pill-count { background: rgba(255,255,255,0.25); }
.sort-pill { border: 1px solid #d5c8f7; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 600; cursor: pointer; background: #fff; color: #555; transition: all 0.12s; user-select: none; }
.sort-pill:hover { border-color: #7a5fd0; background: #efe9fe; color: #3d2a6b; }
.sort-pill.active { background: #3d2a6b; color: #fff; border-color: #3d2a6b; }
.filter-result { font-size: 11px; color: #888; margin-left: auto; }
.clear-link { font-size: 11px; color: #c0392b; cursor: pointer; text-decoration: underline; display: none; }

.container { padding: 10px 14px; }
.card { background: #fff; border: 1px solid #e0dcec; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; }
.card:hover { border-color: #7a5fd0; box-shadow: 0 1px 4px rgba(122,95,208,0.15); }
.card.hidden { display: none; }
.proc-num { font-size: 12px; color: #7a5fd0; font-weight: 700; font-family: monospace; }
.card-title { font-weight: 600; font-size: 13px; margin: 4px 0 5px; }
.meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 4px 12px; font-size: 11px; margin-top: 6px; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { color: #888; font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px; }
.meta-val { color: #1a1a2e; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { margin-top: 7px; display: flex; gap: 6px; flex-wrap: wrap; }
.btn { display: inline-block; border: none; border-radius: 4px; padding: 3px 9px; font-size: 11px; cursor: pointer; }
.btn-primary { background: #3d2a6b; color: #fff; }
.btn-primary:hover { background: #7a5fd0; }
.btn-secondary { background: #efe9fe; color: #3d2a6b; border: 1px solid #d5c8f7; }
.btn-secondary:hover { background: #d5c8f7; }
.type-badge { display: inline-block; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 700; margin-left: 6px; }
.type-IPR { background: #2b6cb0; color: #fff; }
.type-PGR { background: #6b46c1; color: #fff; }
.type-CBM { background: #2c7a7b; color: #fff; }
.type-DER { background: #c05621; color: #fff; }
.type-Appeal { background: #276749; color: #fff; }
.type-Interference { background: #4a5568; color: #fff; }
.status-badge { display: inline-block; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600; background: #efe9fe; color: #3d2a6b; margin-left: 6px; }

#loading { text-align: center; padding: 30px; color: #666; }
#error { background: #fde8e8; border: 1px solid #f5c6cb; color: #721c24; padding: 10px 14px; margin: 10px 14px; border-radius: 4px; }
.no-match { text-align: center; padding: 20px; color: #888; font-size: 12px; display: none; }
</style>
</head>
<body>
<div class="header">
  <h1>PTAB Search Results</h1>
  <span class="badge" id="tier-badge">—</span>
</div>
<div class="summary-bar" id="summary-bar" style="display:none"></div>
<div class="field-notice" id="field-notice" style="display:none"><strong>Note:</strong> Fields showing <strong>"—"</strong> were not requested in this tool call. The LLM selects fields to balance context efficiency.</div>
<div class="filter-bar" id="filter-bar" style="display:none"></div>
<div class="sort-bar" id="sort-bar" style="display:none"></div>
<div id="loading">Waiting for search results...</div>
<div id="error" style="display:none"></div>
<div class="container" id="content" style="display:none">
  <div id="cards"></div>
  <div class="no-match" id="no-match">No results match the selected filters.</div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'PTAB Search Results', version: '1.0.0' });

let allDocs = [];
let cardEls = [];
let activeFilters = {};
let currentSort = null;

app.ontoolresult = (result) => {
  const text = result.content?.find(c => c.type === 'text')?.text;
  try { render(JSON.parse(text)); }
  catch(e) { showError('Could not parse search results: ' + e.message); }
};

app.connect();

// Normalize the three proceeding shapes into one card model.
function normalize(rec, dataType) {
  const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
  const d = (v) => (v ? String(v).split('T')[0] : '');

  if (dataType === 'appeals') {
    return {
      num: rec.appealNumber || '—',
      type: 'Appeal',
      status: get(rec, 'documentData.decisionOutcome') || '',
      filed: d(get(rec, 'documentData.documentFilingDate')),
      decided: d(get(rec, 'documentData.decisionDate')),
      decisionType: get(rec, 'documentData.decisionTypeCodeDescription') || get(rec, 'documentData.decisionType') || '',
      partyALabel: 'Appellant',
      partyA: get(rec, 'appellantData.appellantName') || '—',
      partyBLabel: '', partyB: '',
      patentNum: get(rec, 'appellantData.patentNumber') || get(rec, 'applicationData.patentNumber') || '',
      appNum: rec.applicationNumber || '',
      artUnit: get(rec, 'appellantData.groupArtUnitNumber') || '',
      tc: get(rec, 'appellantData.technologyCenterNumber') || '',
    };
  }
  if (dataType === 'interferences') {
    return {
      num: rec.interferenceNumber || '—',
      type: 'Interference',
      status: get(rec, 'documentData.decisionOutcome') || '',
      filed: d(get(rec, 'documentData.documentFilingDate')),
      decided: d(get(rec, 'documentData.decisionDate')),
      decisionType: get(rec, 'documentData.decisionType') || '',
      partyALabel: 'Senior Party',
      partyA: get(rec, 'partyData.seniorParty') || '—',
      partyBLabel: 'Junior Party',
      partyB: get(rec, 'partyData.juniorParty') || '—',
      patentNum: get(rec, 'partyData.seniorPartyPatentNumber') || '',
      appNum: get(rec, 'partyData.seniorPartyApplicationNumber') || '',
      artUnit: '', tc: '',
    };
  }
  // trials (default)
  const num = rec.trialNumber || '—';
  const typeFromNum = /^[A-Z]+/.exec(num)?.[0];
  return {
    num,
    type: get(rec, 'trialMetaData.trialTypeCode') || typeFromNum || 'Trial',
    status: get(rec, 'trialMetaData.trialStatusCategory') || '',
    filed: d(get(rec, 'trialMetaData.accordedFilingDate')),
    decided: d(get(rec, 'trialMetaData.terminationDate')),
    instituted: d(get(rec, 'trialMetaData.institutionDecisionDate')),
    decisionType: '',
    partyALabel: 'Petitioner',
    partyA: get(rec, 'regularPetitionerData.realPartyInInterestName') || '—',
    partyBLabel: 'Patent Owner',
    partyB: get(rec, 'patentOwnerData.patentOwnerName') || '—',
    patentNum: get(rec, 'patentOwnerData.patentNumber') || '',
    appNum: get(rec, 'patentOwnerData.applicationNumberText') || '',
    artUnit: get(rec, 'patentOwnerData.groupArtUnitNumber') || '',
    tc: get(rec, 'patentOwnerData.technologyCenterNumber') || '',
  };
}

function render(data) {
  document.getElementById('loading').style.display = 'none';
  if (data.error || data.status === 'error') { showError(data.message || data.error || 'API error'); return; }

  const dataType = data.data_type || 'trials';
  const records = data.results || [];
  allDocs = records.map(r => normalize(r, dataType));
  activeFilters = {};
  currentSort = null;

  const total = data.count ?? allDocs.length;
  const tier = data.field_set || 'search';
  document.getElementById('tier-badge').textContent = tier.toUpperCase();

  const bar = document.getElementById('summary-bar');
  bar.style.display = 'flex';
  bar.innerHTML = `
    <div>Found: <span>${Number(total).toLocaleString()}</span> ${dataType}</div>
    <div>Showing: <span>${allDocs.length}</span></div>
  `;

  document.getElementById('field-notice').style.display = tier.includes('minimal') ? 'block' : 'none';

  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  cardEls = [];
  if (allDocs.length === 0) {
    cardsEl.innerHTML = '<div style="text-align:center;padding:24px;color:#888">No proceedings found.</div>';
  } else {
    allDocs.forEach(p => {
      const el = buildCard(p);
      cardsEl.appendChild(el);
      cardEls.push(el);
    });
  }

  buildFilterBar();
  buildSortBar();
  document.getElementById('content').style.display = 'block';
}

// US patent number gate for the Google Patents button (Lesson 26):
// plain 6-8 digit utility numbers or RE reissues; excludes empty/odd values.
function googlePatentsUrl(patentNum) {
  const clean = String(patentNum).replace(/[,\/]/g, '').trim();
  if (!/^(RE)?\d{6,8}$/i.test(clean)) return null;
  return `https://patents.google.com/patent/US${encodeURIComponent(clean.toUpperCase())}`;
}

function buildCard(p) {
  const div = document.createElement('div');
  div.className = 'card';

  div.dataset.type = p.type;
  div.dataset.status = p.status || '';
  div.dataset.partya = p.partyA || '';
  div.dataset.partyb = p.partyB || '';
  div.dataset.num = p.num;
  div.dataset.filed = p.filed || '';
  div.dataset.patentnum = p.patentNum || '';

  const gpUrl = googlePatentsUrl(p.patentNum);
  const appNumClean = String(p.appNum || '').replace(/[,\/]/g, '');

  div.innerHTML = `
    <div class="proc-num">${p.num}<span class="type-badge type-${p.type}">${p.type}</span>${p.status ? `<span class="status-badge">${p.status}</span>` : ''}</div>
    <div class="meta">
      <div class="meta-item"><span class="meta-label">${p.partyALabel}</span><span class="meta-val" title="${p.partyA}">${p.partyA}</span></div>
      ${p.partyBLabel ? `<div class="meta-item"><span class="meta-label">${p.partyBLabel}</span><span class="meta-val" title="${p.partyB}">${p.partyB}</span></div>` : ''}
      <div class="meta-item"><span class="meta-label">Filed</span><span class="meta-val">${p.filed || '—'}</span></div>
      ${p.instituted ? `<div class="meta-item"><span class="meta-label">Institution</span><span class="meta-val">${p.instituted}</span></div>` : ''}
      ${p.decided ? `<div class="meta-item"><span class="meta-label">${p.type === 'Appeal' || p.type === 'Interference' ? 'Decided' : 'Terminated'}</span><span class="meta-val">${p.decided}</span></div>` : ''}
      ${p.decisionType ? `<div class="meta-item"><span class="meta-label">Decision</span><span class="meta-val" title="${p.decisionType}">${p.decisionType}</span></div>` : ''}
      ${p.patentNum ? `<div class="meta-item"><span class="meta-label">Patent</span><span class="meta-val">${p.patentNum}</span></div>` : ''}
      ${p.appNum ? `<div class="meta-item"><span class="meta-label">Application</span><span class="meta-val">${p.appNum}</span></div>` : ''}
      ${p.artUnit ? `<div class="meta-item"><span class="meta-label">Art Unit</span><span class="meta-val">${p.artUnit}</span></div>` : ''}
      ${p.tc ? `<div class="meta-item"><span class="meta-label">Tech Center</span><span class="meta-val">${p.tc}</span></div>` : ''}
    </div>
    <div class="actions">
      ${gpUrl ? `<button class="btn btn-primary" data-gp="${gpUrl}">Google Patents →</button>` : ''}
      ${appNumClean ? `<button class="btn btn-secondary" data-app="${appNumClean}">Patent Center →</button>` : ''}
    </div>
  `;

  div.querySelector('[data-gp]')?.addEventListener('click', async () => {
    try { await app.openLink({ url: gpUrl }); } catch { window.open(gpUrl, '_blank'); }
  });
  div.querySelector('[data-app]')?.addEventListener('click', async () => {
    const url = `https://patentcenter.uspto.gov/applications/${appNumClean}`;
    try { await app.openLink({ url }); } catch { window.open(url, '_blank'); }
  });

  return div;
}

function buildFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  const types = countBy(p => p.type, v => !!v);
  const statuses = countBy(p => p.status, v => !!v);
  const partiesA = countBy(p => p.partyA, v => !!v && v !== '—');
  const partiesB = countBy(p => p.partyB, v => !!v && v !== '—');

  bar.style.display = 'flex';
  bar.innerHTML = '';
  let hasAnyFilter = false;

  if (Object.keys(types).length > 1) {
    hasAnyFilter = true;
    appendLabel(bar, 'Type:');
    Object.entries(types).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'type', val));
    });
  }

  if (Object.keys(statuses).length > 1 && Object.keys(statuses).length <= 8) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Status:');
    Object.entries(statuses).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'status', val));
    });
  }

  // Party filters: pills only for parties appearing >= 2 times (Lesson: frequency threshold)
  const frequentA = Object.fromEntries(Object.entries(partiesA).filter(([,c]) => c >= 2));
  if (Object.keys(frequentA).length >= 1 && Object.keys(frequentA).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, allDocs[0]?.partyALabel + ':');
    Object.entries(frequentA).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'partya', val));
    });
  }

  const frequentB = Object.fromEntries(Object.entries(partiesB).filter(([,c]) => c >= 2));
  if (Object.keys(frequentB).length >= 1 && Object.keys(frequentB).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, (allDocs.find(p => p.partyBLabel)?.partyBLabel || 'Party') + ':');
    Object.entries(frequentB).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'partyb', val));
    });
  }

  if (!hasAnyFilter) { bar.style.display = 'none'; return; }

  const counter = document.createElement('span');
  counter.className = 'filter-result';
  counter.id = 'filter-result';
  bar.appendChild(counter);

  const clearLink = document.createElement('a');
  clearLink.className = 'clear-link';
  clearLink.id = 'clear-link';
  clearLink.textContent = '× Clear';
  clearLink.addEventListener('click', clearFilters);
  bar.appendChild(clearLink);
}

function appendLabel(bar, text) {
  const lbl = document.createElement('span');
  lbl.className = 'filter-label';
  lbl.textContent = text;
  bar.appendChild(lbl);
}

function appendSep(bar) {
  const sep = document.createElement('div');
  sep.style.cssText = 'width:1px;background:#e0dcec;height:18px;margin:0 4px;align-self:center;flex-shrink:0;';
  bar.appendChild(sep);
}

function buildSortBar() {
  const bar = document.getElementById('sort-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  const hasData = (key) => cardEls.some(el => el.dataset[key] && el.dataset[key] !== '—' && el.dataset[key] !== '');
  const sortOptions = [
    { label: 'Number', key: 'num' },
    { label: 'Filed', key: 'filed' },
    { label: 'Patent #', key: 'patentnum' },
    { label: 'Status', key: 'status' },
  ].filter(opt => opt.key === 'num' || hasData(opt.key));

  if (sortOptions.length < 2) { bar.style.display = 'none'; return; }

  bar.style.display = 'flex';
  bar.innerHTML = '';
  appendLabel(bar, 'Sort:');

  sortOptions.forEach(({ label, key }) => {
    const pill = document.createElement('span');
    pill.className = 'sort-pill';
    pill.textContent = label;
    pill.dataset.sortkey = key;
    pill.addEventListener('click', () => {
      document.querySelectorAll('.sort-pill').forEach(p => p.classList.remove('active'));
      if (currentSort === key) {
        currentSort = null;
        renderCardsInOrder(allDocs);
      } else {
        currentSort = key;
        pill.classList.add('active');
        const sorted = [...allDocs].sort((a, b) => {
          const aEl = cardEls[allDocs.indexOf(a)];
          const bEl = cardEls[allDocs.indexOf(b)];
          const aVal = (aEl?.dataset[key] || '').toLowerCase();
          const bVal = (bEl?.dataset[key] || '').toLowerCase();
          return aVal.localeCompare(bVal, undefined, { numeric: key === 'patentnum' });
        });
        renderCardsInOrder(sorted);
      }
    });
    bar.appendChild(pill);
  });
}

function renderCardsInOrder(orderedDocs) {
  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  orderedDocs.forEach(p => {
    const idx = allDocs.indexOf(p);
    if (idx >= 0 && cardEls[idx]) cardsEl.appendChild(cardEls[idx]);
  });
  applyFilters();
}

function makePill(label, count, dim, val) {
  const pill = document.createElement('span');
  pill.className = 'pill';
  pill.dataset.dim = dim;
  pill.dataset.val = val;
  pill.innerHTML = `${label} <span class="pill-count">${count}</span>`;
  pill.addEventListener('click', () => {
    if (activeFilters[dim] === val) {
      activeFilters[dim] = null;
      pill.classList.remove('active');
    } else {
      document.querySelectorAll(`.pill[data-dim="${dim}"]`).forEach(p => p.classList.remove('active'));
      activeFilters[dim] = val;
      pill.classList.add('active');
    }
    applyFilters();
  });
  return pill;
}

function countBy(fn, filterFn = () => true) {
  const map = {};
  allDocs.forEach(d => {
    const v = fn(d);
    if (filterFn(v)) map[v] = (map[v] || 0) + 1;
  });
  return map;
}

function applyFilters() {
  let visible = 0;
  cardEls.forEach((el) => {
    const show =
      (!activeFilters.type   || el.dataset.type   === activeFilters.type) &&
      (!activeFilters.status || el.dataset.status === activeFilters.status) &&
      (!activeFilters.partya || el.dataset.partya === activeFilters.partya) &&
      (!activeFilters.partyb || el.dataset.partyb === activeFilters.partyb);
    el.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  document.getElementById('no-match').style.display = visible === 0 ? 'block' : 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  const hasFilter = Object.values(activeFilters).some(Boolean);
  if (counter) counter.textContent = hasFilter ? `${visible} of ${allDocs.length} shown` : '';
  if (clearEl) clearEl.style.display = hasFilter ? 'inline' : 'none';
}

function clearFilters() {
  activeFilters = {};
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  cardEls.forEach(el => el.classList.remove('hidden'));
  document.getElementById('no-match').style.display = 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  if (counter) counter.textContent = '';
  if (clearEl) clearEl.style.display = 'none';
}

function showError(msg) {
  document.getElementById('loading').style.display = 'none';
  const el = document.getElementById('error');
  el.style.display = 'block';
  el.textContent = 'Error: ' + msg;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# View 2: Recent Downloads panel (used by ptab_get_document_download)
# ---------------------------------------------------------------------------

DOWNLOADS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recent Downloads</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #3d2a6b; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .count { background: #7a5fd0; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.header .refresh-btn { margin-left: auto; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: #fff; border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.header .refresh-btn:hover { background: rgba(255,255,255,0.25); }

.tip { background: #fff9e6; border-bottom: 1px solid #ffe08a; padding: 5px 14px; font-size: 11px; color: #6b5000; }

.container { padding: 10px 14px; }

.empty-state { text-align: center; padding: 40px 20px; color: #888; }
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 13px; }
.empty-hint { font-size: 11px; color: #aaa; margin-top: 4px; }

.doc-card { background: #fff; border: 1px solid #e0dcec; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; display: flex; align-items: flex-start; gap: 10px; }
.doc-card:hover { border-color: #7a5fd0; box-shadow: 0 1px 4px rgba(122,95,208,0.12); }

.doc-icon { width: 32px; height: 32px; border-radius: 4px; background: #efe9fe; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.doc-info { flex: 1; min-width: 0; }
.doc-title { font-weight: 600; font-size: 12px; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-meta { font-size: 11px; color: #888; display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 5px; }
.doc-type-badge { display: inline-block; background: #efe9fe; color: #3d2a6b; border-radius: 3px; padding: 1px 5px; font-size: 10px; font-weight: 700; }
.doc-actions { display: flex; gap: 6px; }
.btn { border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.btn-download { background: #3d2a6b; color: #fff; text-decoration: none; display: inline-block; }
.btn-download:hover { background: #7a5fd0; }

.timestamp { font-size: 10px; color: #bbb; margin-left: auto; white-space: nowrap; align-self: center; }

#status { font-size: 11px; color: #888; text-align: center; padding: 6px; }
</style>
</head>
<body>
<div class="header">
  <h1>Recent Downloads</h1>
  <span class="count" id="count-badge">0</span>
  <button class="refresh-btn" id="refresh-btn">↻ Refresh</button>
</div>
<div class="tip">Click Download to open a document in your browser. Links are valid for 7 days.</div>
<div id="status"></div>
<div class="container" id="content">
  <div class="empty-state" id="empty-state">
    <div class="empty-icon">📂</div>
    <div class="empty-text">No recent downloads yet</div>
    <div class="empty-hint">Use ptab_get_document_download to generate links</div>
  </div>
  <div id="cards"></div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'PTAB Recent Downloads', version: '1.0.0' });

// In-session download store — populated directly from tool results (no fetch needed)
let sessionDownloads = [];
// proxyBaseUrl: derived from the first download_url seen in a tool result so
// it also works behind Docker/reverse proxies (PTAB_PROXY_BASE_URL).
let proxyBaseUrl = 'http://localhost:8083';

app.ontoolresult = (result) => {
  try {
    const text = result.content?.find(c => c.type === 'text')?.text;
    const data = JSON.parse(text);
    const now = new Date().toISOString();

    // ptab_get_document_download result shape
    if (data.download_url && data.document_id) {
      const newDoc = {
        title: data.enhanced_filename || data.document_description || 'Document',
        identifier_type: data.identifier_type || 'trial',
        identifier: data.identifier || '',
        proxy_url: data.download_url,
        generated_at: now,
      };
      const baseMatch = data.download_url.match(/^(https?:\/\/[^/]+)/);
      if (baseMatch) proxyBaseUrl = baseMatch[1];

      sessionDownloads = [newDoc, ...sessionDownloads].slice(0, 10);
      renderDownloads(sessionDownloads);
      document.getElementById('status').textContent = '';
      return;
    }
  } catch {}
  // No directly parseable downloads — try proxy fetch as fallback
  loadDownloads();
};

app.connect();

// Refresh button — bound here instead of an inline onclick attribute so the
// markup stays CSP-clean without script-src 'unsafe-inline' (audit L-5)
document.getElementById('refresh-btn').addEventListener('click', () => loadDownloads());

// Delegated click handler — use app.openLink() so Claude Desktop opens the
// URL in the system browser, bypassing iframe sandbox restrictions (Lesson 24).
document.getElementById('cards').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-url]');
  if (!btn) return;
  const url = btn.dataset.url;
  if (!url) return;
  try {
    await app.openLink({ url });
  } catch {
    // Fallback for hosts that don't support openLink
    window.open(url, '_blank');
  }
});

window.loadDownloads = async function() {
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Refreshing...';
  try {
    const resp = await fetch(`${proxyBaseUrl}/api/recent-downloads`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    const docs = (body.downloads || []).map(d => ({
      title: d.enhanced_filename || d.document_description || 'Document',
      identifier_type: d.identifier_type || 'trial',
      identifier: d.identifier || '',
      proxy_url: d.download_url,
      generated_at: d.registered_at,
    }));
    // Merge proxy results with session store, deduplicate by proxy_url
    const seen = new Set(sessionDownloads.map(d => d.proxy_url));
    const merged = [...sessionDownloads, ...docs.filter(d => !seen.has(d.proxy_url))].slice(0, 10);
    sessionDownloads = merged;
    renderDownloads(sessionDownloads);
    statusEl.textContent = '';
  } catch (e) {
    // Proxy fetch failed (CSP/CORS/not running) — show what we have from session
    renderDownloads(sessionDownloads);
    statusEl.textContent = sessionDownloads.length === 0 ? `Generate a download to see links here.` : '';
  }
};

function renderDownloads(docs) {
  const countBadge = document.getElementById('count-badge');
  const emptyState = document.getElementById('empty-state');
  const cardsEl = document.getElementById('cards');

  countBadge.textContent = docs.length;
  emptyState.style.display = docs.length === 0 ? 'block' : 'none';
  cardsEl.innerHTML = '';

  docs.forEach(doc => cardsEl.appendChild(buildCard(doc)));
}

const DOC_ICONS = { trial: '⚖️', appeal: '📜', interference: '🔀', default: '📄' };

function buildCard(doc) {
  const div = document.createElement('div');
  div.className = 'doc-card';

  const type = doc.identifier_type || 'default';
  const icon = DOC_ICONS[type] || DOC_ICONS.default;
  const time = doc.generated_at ? formatTime(doc.generated_at) : '';

  div.innerHTML = `
    <div class="doc-icon">${icon}</div>
    <div class="doc-info">
      <div class="doc-title" title="${doc.title}">${doc.title || 'Document'}</div>
      <div class="doc-meta">
        <span class="doc-type-badge">${type}</span>
        <span>${doc.identifier || '—'}</span>
      </div>
      <div class="doc-actions">
        <button class="btn btn-download" data-url="${doc.proxy_url}">Download PDF</button>
      </div>
    </div>
    ${time ? `<div class="timestamp">${time}</div>` : ''}
  `;

  return div;
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString();
  } catch { return ''; }
}
</script>
</body>
</html>"""
