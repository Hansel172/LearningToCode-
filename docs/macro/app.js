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

// Deal-type catalysts (partnerships, acquisitions) used to sit in "What to
// Watch" alongside Fed decisions and CPI prints — two different kinds of
// "thing worth knowing about" mixed into one list. Deals now live in their
// own section (dealsSection, below) next to the auto-detected candidates,
// so there's one place for "what's happening with a held company" instead
// of two. Partnership and acquisition were originally two separate types;
// merged into one "Deal" tag since the distinction wasn't worth a second
// color — old data tagged with either name still resolves via the alias.
const CATALYST_TYPE = {
  macro:    { color: 'var(--blue)',   label: 'Macro'    },
  earnings: { color: 'var(--yellow)', label: 'Earnings' },
  deal:     { color: 'var(--orange)', label: 'Deal'     },
};
const CATALYST_TYPE_ALIAS = { partnership: 'deal', acquisition: 'deal' };
const resolvedType = raw => CATALYST_TYPE_ALIAS[raw] || raw;

/* Today at local midnight, so "date >= todayIso" comparisons (plain string
   compares, since dates are already YYYY-MM-DD) mean "today or later" —
   not "later than right now," which would flicker an event out mid-day. */
const todayIso = (() => {
  const n = new Date();
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`;
})();

/* Only macro/earnings calendar events — deals are split out to
   dealsSection(). Past-dated entries are dropped automatically, every
   render, purely from today's date: a CPI print from three weeks ago isn't
   "up next" anymore, and the whole point of an autonomous tracker is that
   nobody should have to remember to go prune the list by hand. */
function catalysts(list) {
  const upcoming = (list || [])
    .filter(c => resolvedType(c.type) !== 'deal' && c.date >= todayIso)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!upcoming.length) return '';
  const rows = upcoming.map(c => {
    const t = CATALYST_TYPE[resolvedType(c.type)] || CATALYST_TYPE.macro;
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

/* One section for "something's happening with a held company," split into
   two trust levels rather than two separate cards: confirmed deals (a
   catalyst entry someone actually verified, like NVIDIA/Hugging Face) and
   auto-detected candidates (scan_news.py — see that script for why it only
   flags, never auto-writes, a confirmed entry). Confirmed entries have no
   natural expiry (a real deal stays true); pending ones age out server-side
   after 7 days since there's no "mark reviewed" affordance on a static page. */
function dealsSection(catalystList, pending) {
  const confirmed = (catalystList || [])
    .filter(c => resolvedType(c.type) === 'deal')
    .sort((a, b) => b.date.localeCompare(a.date));
  const unverified = pending || [];
  if (!confirmed.length && !unverified.length) return '';

  const confirmedRows = confirmed.map(c => `<div class="cat-row">
      <div class="cat-d">${esc(c.date)}<span class="days">${daysUntil(c.date)}</span></div>
      <div>
        <div class="cat-l">${esc(c.label)}</div>
        <div class="cat-w">${esc(c.why)}</div>
      </div>
    </div>`).join('');

  const pendingRows = unverified
    .sort((a, b) => (b.detectedAt || '').localeCompare(a.detectedAt || ''))
    .map(p => `<div class="pd-row">
      <span class="pd-ticker">${esc(p.ticker)}</span>
      <div>
        <a class="pd-headline" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.headline)}</a>
        <div class="pd-meta">${esc(p.source)} &middot; ${daysUntil((p.publishedAt || '').slice(0, 10))}</div>
      </div>
    </div>`).join('');

  return `<section class="card deals">
    <div class="card-head"><h2>Partnerships &amp; Acquisitions</h2></div>
    ${confirmedRows ? `<div class="deals-sub">Confirmed</div>${confirmedRows}` : ''}
    ${pendingRows ? `<div class="deals-sub deals-sub-unverified">Unverified — needs a look</div>
      <div class="pd-note">Auto-detected from headlines mentioning a held ticker plus an
        acquisition/partnership keyword — not yet checked against a primary source.
        Verify before treating as fact.</div>${pendingRows}` : ''}
  </section>`;
}

function render() {
  document.getElementById('today').textContent =
    new Date().toLocaleDateString('en-US',
      { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  document.getElementById('snapshot').innerHTML =
    ['SP500', 'NASDAQCOM', 'VIXCLS', 'DCOILWTICO'].map(k => tick(LIVE.market[k])).join('');

  document.getElementById('strip').innerHTML =
    ['DFF', 'DGS10', 'CPIAUCSL', 'PPIACO'].map(k => tick(LIVE.macro[k], true)).join('');

  const errs = LIVE.errors || [];
  document.getElementById('errors').innerHTML = errs.length
    ? `<div class="err">Some series failed to refresh: ${esc(errs.join(' · '))}</div>` : '';

  document.getElementById('grid').innerHTML = (THEMES.themes || []).map(card).join('');
  document.getElementById('pending').innerHTML = dealsSection(THEMES.catalysts, PENDING);
  document.getElementById('catalysts').innerHTML = catalysts(THEMES.catalysts);

  const stamp = LIVE.updated ? new Date(LIVE.updated).toLocaleString() : 'never';
  document.getElementById('stamp').textContent =
    `Data refreshed ${stamp} · Analysis as of ${THEMES.updated || 'unknown'}`;
}

render();
