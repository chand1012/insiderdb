const view = document.querySelector('#view');

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function fmtMoney(value) { return value == null ? '' : money.format(Number(value)); }
function fmtNumber(value) { return value == null ? '' : number.format(Number(value)); }
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}
function codeBadge(code) {
  const variant = code === 'P' ? 'success' : code === 'S' ? 'danger' : 'secondary';
  return `<span class="badge" data-variant="${variant}">${escapeHtml(code || '')}</span>`;
}
async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}
function setLoading() { view.innerHTML = document.querySelector('#loading-template').innerHTML; }
function setError(error) { view.innerHTML = `<article class="card" role="alert" data-variant="danger"><h2>Request failed</h2><p class="error">${escapeHtml(error.message)}</p></article>`; }

function clusterRows(rows) {
  return rows.map(row => `<tr>
    <td><a href="#/ticker/${encodeURIComponent(row.ticker)}">${escapeHtml(row.ticker)}</a></td>
    <td>${escapeHtml(row.cluster_start)}</td>
    <td>${escapeHtml(row.cluster_end)}</td>
    <td class="number">${row.unique_insiders}</td>
    <td class="number">${fmtMoney(row.total_value)}</td>
    <td class="wrap">${escapeHtml((row.insider_names || []).join(', '))}</td>
    <td class="wrap">${escapeHtml((row.officer_titles || []).join(', '))}</td>
  </tr>`).join('');
}

function transactionRows(rows) {
  return rows.map(row => `<tr>
    <td>${escapeHtml(row.filing_date)}</td>
    <td>${escapeHtml(row.transaction_date || '')}</td>
    <td><a href="#/ticker/${encodeURIComponent(row.ticker || '')}">${escapeHtml(row.ticker || '')}</a></td>
    <td class="wrap">${escapeHtml(row.issuer || '')}</td>
    <td class="wrap">${escapeHtml(row.reporting_owner_name || '')}</td>
    <td class="wrap">${escapeHtml(row.officer_title || row.role || '')}</td>
    <td>${codeBadge(row.transaction_code)}</td>
    <td class="number">${fmtNumber(row.shares)}</td>
    <td class="number">${fmtMoney(row.price)}</td>
    <td class="number">${fmtMoney(row.value)}</td>
    <td><a href="${escapeHtml(row.source_url)}" target="_blank" rel="noreferrer">SEC</a></td>
  </tr>`).join('');
}

function clusterTable(rows) {
  return `<div class="table"><table>
    <thead><tr><th>Ticker</th><th>Start</th><th>End</th><th class="number">Insiders</th><th class="number">Value</th><th>Insiders</th><th>Titles</th></tr></thead>
    <tbody>${clusterRows(rows)}</tbody>
  </table></div>`;
}
function transactionTable(rows) {
  return `<div class="table"><table>
    <thead><tr><th>Filed</th><th>Trade</th><th>Ticker</th><th>Issuer</th><th>Insider</th><th>Title</th><th>Code</th><th class="number">Shares</th><th class="number">Price</th><th class="number">Value</th><th>Filing</th></tr></thead>
    <tbody>${transactionRows(rows)}</tbody>
  </table></div>`;
}

async function dashboard() {
  setLoading();
  const [summary, clusters, buys] = await Promise.all([
    api('/api/summary'),
    api('/api/cluster-buys?days=30&limit=25'),
    api(`/api/transactions?transaction_code=P&end_date=${new Date().toISOString().slice(0, 10)}&limit=25`),
  ]);
  view.innerHTML = `<section class="hero"><h1>SEC Insider Database</h1><p>Local SEC ownership intelligence for cluster buys, insider transactions, and ingestion health.</p></section>
    <section class="row metrics">
      <article class="card metric col-3"><p>Filings</p><strong>${fmtNumber(summary.filing_count)}</strong></article>
      <article class="card metric col-3"><p>Transactions</p><strong>${fmtNumber(summary.transaction_count)}</strong></article>
      <article class="card metric col-3"><p>Coverage</p><strong>${escapeHtml(summary.min_filing_date || '')} - ${escapeHtml(summary.max_filing_date || '')}</strong></article>
      <article class="card metric col-3"><p>Backfill</p><strong>${summary.backfill_complete ? 'Complete' : `Q${summary.backfill_quarter || ''} ${summary.backfill_year || ''}`}</strong></article>
    </section>
    <section><h2>Latest Cluster Buys</h2>${clusterTable(clusters)}</section>
    <section><h2>Latest Purchases</h2>${transactionTable(buys)}</section>`;
}

async function clustersPage() {
  setLoading();
  view.innerHTML = `<h1>Cluster Buys</h1><form class="card toolbar" id="cluster-form">
    <label>Days <input name="days" type="number" value="30" min="0" max="3650"></label>
    <label>Ticker <input name="ticker" placeholder="AAPL"></label>
    <label>Min value <input name="min_total_value" type="number" min="0" step="1000"></label>
    <label>Limit <input name="limit" type="number" value="100" min="1" max="500"></label>
    <button type="submit">Search</button>
  </form><section id="cluster-results"></section>`;
  const form = document.querySelector('#cluster-form');
  const results = document.querySelector('#cluster-results');
  async function run() {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of [...params.entries()]) if (!value) params.delete(key);
    results.innerHTML = '<p class="muted">Loading...</p>';
    results.innerHTML = clusterTable(await api(`/api/cluster-buys?${params}`));
  }
  form.addEventListener('submit', event => { event.preventDefault(); run().catch(setError); });
  await run();
}

async function screenerPage() {
  setLoading();
  view.innerHTML = `<h1>Transaction Screener</h1><form class="card toolbar" id="screen-form">
    <label>Ticker <input name="ticker" placeholder="AAPL"></label>
    <label>Owner <input name="owner" placeholder="Insider name"></label>
    <label>Code <input name="transaction_code" value="P" maxlength="8"></label>
    <label>Start <input name="start_date" type="date"></label>
    <label>End <input name="end_date" type="date"></label>
    <label>Min value <input name="min_value" type="number" min="0" step="1000"></label>
    <label>Limit <input name="limit" type="number" value="100" min="1" max="500"></label>
    <button type="submit">Search</button>
  </form><section id="screen-results"></section>`;
  const form = document.querySelector('#screen-form');
  const results = document.querySelector('#screen-results');
  async function run() {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of [...params.entries()]) if (!value) params.delete(key);
    results.innerHTML = '<p class="muted">Loading...</p>';
    results.innerHTML = transactionTable(await api(`/api/transactions?${params}`));
  }
  form.addEventListener('submit', event => { event.preventDefault(); run().catch(setError); });
  await run();
}

async function tickerPage(ticker) {
  setLoading();
  const [detail, rows] = await Promise.all([
    api(`/api/tickers/${encodeURIComponent(ticker)}`),
    api(`/api/tickers/${encodeURIComponent(ticker)}/transactions?limit=200`),
  ]);
  view.innerHTML = `<h1>${escapeHtml(detail.ticker)}</h1>
    <section class="row metrics">
      <article class="card metric col-3"><p>Issuer</p><strong>${escapeHtml(detail.issuer || '')}</strong></article>
      <article class="card metric col-3"><p>Purchase value</p><strong>${fmtMoney(detail.purchase_value)}</strong></article>
      <article class="card metric col-3"><p>Sale value</p><strong>${fmtMoney(detail.sale_value)}</strong></article>
      <article class="card metric col-3"><p>Insiders</p><strong>${fmtNumber(detail.unique_insiders)}</strong></article>
    </section>
    <h2>Recent Transactions</h2>${transactionTable(rows)}`;
}

async function ingestionPage() {
  setLoading();
  const rows = await api('/api/ingestion/summary?limit=120');
  view.innerHTML = `<h1>Ingestion Status</h1><div class="table"><table>
    <thead><tr><th>Date</th><th>Source</th><th class="number">Processed</th><th class="number">Failed</th><th class="number">Skipped</th><th class="number">Transactions</th><th class="number">Avg ms</th><th class="number">Max ms</th></tr></thead>
    <tbody>${rows.map(row => `<tr><td>${row.ingestion_date}</td><td>${row.source}</td><td class="number">${fmtNumber(row.filings_processed)}</td><td class="number">${fmtNumber(row.filings_failed)}</td><td class="number">${fmtNumber(row.filings_skipped)}</td><td class="number">${fmtNumber(row.transactions_extracted)}</td><td class="number">${fmtNumber(row.avg_duration_ms)}</td><td class="number">${fmtNumber(row.max_duration_ms)}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

function apiDocsPage() {
  view.innerHTML = `<h1>API Docs</h1><section class="row">
    <article class="card col-3"><h2>OpenAPI</h2><p>Interactive Swagger UI for the REST API.</p><p><a role="button" href="/docs">Open /docs</a></p></article>
    <article class="card col-3"><h2>ReDoc</h2><p>Readable OpenAPI reference.</p><p><a role="button" href="/redoc">Open /redoc</a></p></article>
    <article class="card col-3"><h2>Schema</h2><p>Machine-readable OpenAPI JSON.</p><p><a role="button" href="/openapi.json">Open schema</a></p></article>
    <article class="card col-3"><h2>MCP</h2><p>Curated FastMCP endpoint for LLM clients.</p></article>
  </section>
  <section class="docs-section">
    <div class="section-heading">
      <h2>MCP Server</h2>
      <p class="muted">Read-only tools for connecting LLM clients to the local SEC insider dataset.</p>
    </div>
    <article class="card docs-card">
      <h3>Connection</h3>
      <dl class="definition-list">
        <div><dt>Endpoint</dt><dd><code>/mcp</code></dd></div>
        <div><dt>Transport</dt><dd>FastMCP HTTP endpoint mounted on this API service</dd></div>
        <div><dt>Access</dt><dd>No authentication in this local release; expose it only on trusted networks.</dd></div>
      </dl>
      <pre><code>{
  "mcpServers": {
    "sec-insider-db": {
      "url": "http://100.70.249.93:8888/mcp"
    }
  }
}</code></pre>
    </article>
    <div class="docs-grid">
      <article class="card docs-card">
        <h3>get_latest_cluster_buys</h3>
        <p>Returns recent rows from <code>sec_cluster_buys</code> for cluster-buy research.</p>
        <dl class="definition-list">
          <div><dt>days</dt><dd>Integer lookback window. Default <code>30</code>.</dd></div>
          <div><dt>limit</dt><dd>Maximum rows to return. Default <code>25</code>.</dd></div>
          <div><dt>min_total_value</dt><dd>Optional minimum aggregate purchase value.</dd></div>
        </dl>
        <pre><code>{
  "days": 14,
  "limit": 20,
  "min_total_value": 100000
}</code></pre>
      </article>
      <article class="card docs-card">
        <h3>search_insider_transactions</h3>
        <p>Searches normalized insider transactions with OpenInsider-style filters.</p>
        <dl class="definition-list">
          <div><dt>ticker</dt><dd>Optional ticker filter, for example <code>AAPL</code>.</dd></div>
          <div><dt>owner</dt><dd>Optional reporting-owner name search.</dd></div>
          <div><dt>transaction_code</dt><dd>SEC transaction code. Defaults to <code>P</code>.</dd></div>
          <div><dt>start_date / end_date</dt><dd>Optional ISO dates like <code>2026-06-01</code>.</dd></div>
          <div><dt>min_value</dt><dd>Optional minimum transaction value.</dd></div>
          <div><dt>limit</dt><dd>Maximum rows to return. Default <code>50</code>.</dd></div>
        </dl>
      </article>
      <article class="card docs-card">
        <h3>get_ticker_insider_activity</h3>
        <p>Returns ticker-level summary data plus recent transactions.</p>
        <dl class="definition-list">
          <div><dt>ticker</dt><dd>Required ticker symbol.</dd></div>
          <div><dt>limit</dt><dd>Maximum recent transactions. Default <code>50</code>.</dd></div>
        </dl>
        <pre><code>{
  "ticker": "AAPL",
  "limit": 25
}</code></pre>
      </article>
      <article class="card docs-card">
        <h3>get_ingestion_health</h3>
        <p>Returns dataset summary and recent ingestion health from the observability views.</p>
        <dl class="definition-list">
          <div><dt>parameters</dt><dd>None.</dd></div>
          <div><dt>includes</dt><dd>Dataset counts, coverage, backfill state, and 14 days of ingestion summary rows.</dd></div>
        </dl>
      </article>
    </div>
    <article class="card docs-card">
      <h3>Suggested Prompts</h3>
      <div class="prompt-list">
        <p><code>Use get_latest_cluster_buys for the last 7 days, then summarize the strongest purchase clusters by ticker, total value, insider count, and obvious risks.</code></p>
        <p><code>Use get_ticker_insider_activity for TICKER and explain recent insider buying or selling patterns in a concise diligence format.</code></p>
        <p><code>Use get_ingestion_health and tell me whether the dataset looks fresh enough for today's screening workflow.</code></p>
      </div>
    </article>
  </section>`;
}

async function route() {
  try {
    const hash = location.hash || '#/';
    const parts = hash.slice(2).split('/').filter(Boolean);
    if (parts[0] === 'clusters') return await clustersPage();
    if (parts[0] === 'screener') return await screenerPage();
    if (parts[0] === 'ticker' && parts[1]) return await tickerPage(parts[1]);
    if (parts[0] === 'ingestion') return await ingestionPage();
    if (parts[0] === 'api-docs') return apiDocsPage();
    return await dashboard();
  } catch (error) {
    setError(error);
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('DOMContentLoaded', route);
