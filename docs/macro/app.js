/* Macro Tracker — renders data/bundle.js into the dashboard.
   No framework, no build step. The data is already on window by the time
   this runs, because bundle.js is a plain script tag loaded before it. */

const LIVE    = window.__LIVE__    || { market: {}, macro: {}, errors: [] };
const THEMES  = window.__THEMES__  || { themes: [], catalysts: [] };
const PENDING = window.__PENDING__ || [];

const STATUS = {
  green:  { color: 'var(--green)',  label: 'Positive'   },
  yellow: { color: 'var(--yellow)', label: 'Watch'      },
  red:    { color: 'var(--red)',    label: 'Negative'   },
  orange: { color: 'var(--orange)', label: 'Active risk'},
  blue:   { color: 'var(--blue)',   label: 'Developing' },
};

const RATING = {
  positive: 'var(--green)',
  negative: 'var(--red)',
  neutral:  'var(--muted)',
};

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const fmt = n =>
  typeof n === 'number' ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';

/* Direction is never carried by color alone — the arrow says it too. */
function delta(pct) {
  if (pct === null || pct === undefined) return '<span class="d flat">—</span>';
  const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
  const arw = pct > 0 ? '▲' : pct < 0 ? '▼' : '·';
  return `<span class="d ${cls}">${arw} ${Math.abs(pct).toFixed(2)}%</span>`;
}

function tick(d, showAsOf) {
  if (!d) return '';
  return `<div class="tick">
    <div class="k">${esc(d.label)}</div>
    <div class="v">${fmt(d.value)}${esc(d.unit || '')}</div>
    ${d.note === 'year over year'
      ? `<div class="d flat">year over year</div>`
      : delta(d.changePct)}
    ${showAsOf && d.asOf ? `<div class="asof">${esc(d.asOf)}</div>` : ''}
  </div>`;
}

function dataPoints(pts) {
  if (!pts || !pts.length) return '<div class="empty">No verified figures this cycle.</div>';
  return pts.map(p => `<div class="dp">
    <div class="dp-row"><span class="dp-k">${esc(p.label)}</span>
      <span class="dp-v">${esc(p.value)}</span></div>
    ${p.detail ? `<div class="dp-d">${esc(p.detail)}</div>` : ''}
    ${p.source ? `<div class="dp-s">${esc(p.source)}</div>` : ''}
  </div>`).join('');
}

function impact(rows) {
  if (!rows || !rows.length) return '<div class="empty">No holdings materially affected.</div>';
  return rows.map(r => `<div class="pi">
    <span class="pi-dot" style="background:${RATING[r.rating] || 'var(--muted)'}"></span>
    <div>
      <div class="pi-h">${esc(r.holding)}
        <span style="color:${RATING[r.rating] || 'var(--muted)'};font-size:11px">
          ${esc((r.rating || '').toUpperCase())}</span>
      </div>
      <div class="pi-r">${esc(r.reason)}</div>
    </div>
  </div>`).join('');
}

function card(t) {
  const s = STATUS[t.status] || STATUS.blue;
  return `<section class="card" style="--s:${s.color}">
    <div class="card-head">
      <h2>${esc(t.name)}</h2>
      <span class="badge">${esc(s.label)}</span>
    </div>
    <div class="changed">${esc(t.whatChanged)}</div>
    <div class="lbl">Key data</div>${dataPoints(t.dataPoints)}
    <div class="lbl">Portfolio impact</div>${impact(t.portfolioImpact)}
    ${t.watch ? `<div class="watch"><b>What to watch next</b>${esc(t.watch)}</div>` : ''}
  </section>`;
}

/* Days-until, computed in local time so "today" means the user's today. */
function daysUntil(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const then = new Date(y, m - 1, d);
  const now  = new Date();
  const diff = Math.round((then - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
  if (diff === 0) return 'today';
  if (diff < 0)   return `${Math.abs(diff)}d ago`;
  return `in ${diff}d`;
}

// A macro data print (CPI/PPI/FOMC-type) and a corporate deal are different
// kinds of "what to watch" — lumping an acquisition in with a Fed decision
// under one undifferentiated list made it easy to miss that a deal-type
// catalyst had even happened. Undated/unrecognized types fall back to
// "macro" rather than breaking, since most entries so far have been that.
const CATALYST_TYPE = {
  macro:       { color: 'var(--blue)',   label: 'Macro'       },
  earnings:    { color: 'var(--yellow)', label: 'Earnings'    },
  partnership: { color: 'var(--green)',  label: 'Partnership' },
  acquisition: { color: 'var(--orange)', label: 'Acquisition' },
};

function catalysts(list) {
  if (!list || !list.length) return '';
  const rows = [...list]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map(c => {
      const t = CATALYST_TYPE[c.type] || CATALYST_TYPE.macro;
      return `<div class="cat-row">
      <div class="cat-d">${esc(c.date)}<span class="days">${daysUntil(c.date)}</span></div>
      <div>
        <div class="cat-l">
          <span class="cat-type" style="color:${t.color};border-color:${t.color}">${t.label}</span>
          ${esc(c.label)}
        </div>
        <div class="cat-w">${esc(c.why)}</div>
      </div>
    </div>`;
    }).join('');
  return `<section class="card cat">
    <div class="card-head"><h2>What to Watch</h2>
      <span class="badge">Next catalysts</span></div>
    ${rows}
  </section>`;
}

/* Auto-detected, never auto-verified — see scan_news.py for why. Rendered
   as an unmistakably provisional list (not a themes card, no "why it
   matters" narrative) so it never reads as already-vetted analysis the way
   a catalyst entry does. Ages out on its own after 7 days server-side, so
   there's nothing to dismiss here — just something to notice and, if it's
   real, go verify and turn into an actual catalyst entry. */
function pendingDeals(list) {
  if (!list || !list.length) return '';
  const rows = [...list]
    .sort((a, b) => (b.detectedAt || '').localeCompare(a.detectedAt || ''))
    .map(p => `<div class="pd-row">
      <span class="pd-ticker">${esc(p.ticker)}</span>
      <div>
        <a class="pd-headline" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.headline)}</a>
        <div class="pd-meta">${esc(p.source)} &middot; ${daysUntil((p.publishedAt || '').slice(0, 10))}</div>
      </div>
    </div>`).join('');
  return `<section class="card pending">
    <div class="card-head"><h2>Needs a Look</h2>
      <span class="badge">Unverified</span></div>
    <div class="pd-note">Auto-detected from headlines mentioning a held ticker plus an
      acquisition/partnership keyword — not yet checked against a primary source.
      Verify before treating as fact.</div>
    ${rows}
  </section>`;
}

function render() {
  document.getElementById('today').textContent =
    new Date().toLocaleDateString('en-US',
      { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  document.getElementById('snapshot').innerHTML =
    ['SP500', 'NASDAQCOM', 'VIXCLS'].map(k => tick(LIVE.market[k])).join('');

  document.getElementById('strip').innerHTML =
    ['DFF', 'DGS10', 'CPIAUCSL', 'PPIACO'].map(k => tick(LIVE.macro[k], true)).join('');

  const errs = LIVE.errors || [];
  document.getElementById('errors').innerHTML = errs.length
    ? `<div class="err">Some series failed to refresh: ${esc(errs.join(' · '))}</div>` : '';

  document.getElementById('grid').innerHTML = (THEMES.themes || []).map(card).join('');
  document.getElementById('pending').innerHTML = pendingDeals(PENDING);
  document.getElementById('catalysts').innerHTML = catalysts(THEMES.catalysts);

  const stamp = LIVE.updated ? new Date(LIVE.updated).toLocaleString() : 'never';
  document.getElementById('stamp').textContent =
    `Data refreshed ${stamp} · Analysis as of ${THEMES.updated || 'unknown'}`;
}

render();
