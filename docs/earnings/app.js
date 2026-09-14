/* Renders data.json into the dashboard. No framework, no build step. */

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function fmtPct(v) {
  if (v === null || v === undefined) return 'n/a';
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

function metricLine(m) {
  if ('change_pts' in m) {
    return `${esc(m.metric)}: ${m.change_pts > 0 ? '+' : ''}${m.change_pts.toFixed(1)} points `
         + `(${m.from_pct.toFixed(1)}% &rarr; ${m.to_pct.toFixed(1)}%)`;
  }
  return `${esc(m.metric)}: ${fmtPct(m.change_pct)}`;
}

function column(label, items, cls) {
  const body = items.length
    ? items.map(m => `<div class="metric-line ${cls}">${metricLine(m)}</div>`).join('')
    : `<div class="metric-empty">Nothing here</div>`;
  return `<div><div class="col-lbl">${label}</div>${body}</div>`;
}

const SEVERITY_COLOR = { high: 'var(--red)', medium: 'var(--orange)', low: 'var(--yellow)' };

function flagsBlock(flags) {
  if (!flags.length) {
    return `<div class="flags"><div class="no-flags">No red flags detected.</div></div>`;
  }
  const order = { high: 0, medium: 1, low: 2 };
  const sorted = [...flags].sort((a, b) => order[a.severity] - order[b.severity]);
  const rows = sorted.map(f => `
    <div class="flag">
      <span class="flag-dot" style="background:${SEVERITY_COLOR[f.severity]}"></span>
      <div>
        <div class="flag-title">${esc(f.flag)}</div>
        <div class="flag-detail">${esc(f.detail)}</div>
      </div>
    </div>`).join('');
  return `<div class="flags">${rows}</div>`;
}

/* Card accent + badge follow the worst flag present — a company with any
   HIGH flag reads as critical at a glance, without having to read further. */
function statusFor(company) {
  const flags = company.red_flags || [];
  if (flags.some(f => f.severity === 'high')) return { color: 'var(--red)', label: 'Flagged' };
  if (flags.some(f => f.severity === 'medium')) return { color: 'var(--orange)', label: 'Watch' };
  return { color: 'var(--green)', label: 'Clean' };
}

function descLine(description) {
  return description ? `<div class="desc">${esc(description)}</div>` : '';
}

function fmtMoneyShort(v) {
  if (v === null || v === undefined) return 'n/a';
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString()}`;
}

/* Placeholder only — the real SVG is drawn by drawSparklines() once this
   is actually laid out in the DOM. clientWidth is 0 before that, and a
   viewBox stretched to fit an assumed width (rather than the real one)
   scales X and Y unevenly, which turns the endpoint dot into an ellipse.
   Building it at the container's true pixel width keeps a 1:1 scale, so
   the circle stays a circle regardless of how wide the card ends up. */
function sparklineContainer(points, accentColor) {
  if (points.length < 2) return '';
  const values = points.map(p => p.revenue);
  return `<div class="spark-wrap">
    <div class="spark" data-values="${esc(JSON.stringify(values))}" data-accent="${esc(accentColor)}"></div>
    <div class="spark-caption">
      <span>Revenue &middot; ${points.length} quarters</span>
      <span>${fmtMoneyShort(values[values.length - 1])}</span>
    </div>
  </div>`;
}

function drawSparklines() {
  document.querySelectorAll('.spark').forEach(el => {
    const W = el.clientWidth;
    if (!W) return; // not laid out yet — a later resize/redraw will catch it
    const values = JSON.parse(el.dataset.values);
    const accent = el.dataset.accent;
    const H = 40, PAD_X = 4, PAD_Y = 6;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const stepX = values.length > 1 ? (W - PAD_X * 2) / (values.length - 1) : 0;

    const coords = values.map((v, i) => [
      PAD_X + i * stepX,
      PAD_Y + (H - PAD_Y * 2) * (1 - (v - min) / range),
    ]);
    const d = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const [lastX, lastY] = coords[coords.length - 1];

    // viewBox width == W == the SVG's own pixel width, so scaleX == scaleY
    // == 1 — nothing here gets stretched non-uniformly.
    el.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
           aria-label="Revenue trend, ${fmtMoneyShort(values[0])} to ${fmtMoneyShort(values[values.length - 1])} over ${values.length} quarters">
        <path d="${d}" fill="none" stroke="var(--muted)" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="5"
                fill="${accent}" stroke="var(--card)" stroke-width="2"/>
      </svg>`;
  });
}

function streakNotes(trend) {
  const lines = [];
  // Only surface a streak once it's genuinely more informative than the
  // single quarter-over-quarter comparison already shown elsewhere on the
  // card — "grew for 2 quarters" says the same thing "up this quarter" does.
  if (trend.revenue_growth_streak >= 3) {
    lines.push(`Revenue has grown for ${trend.revenue_growth_streak} straight quarters.`);
  }
  if (trend.margin_expansion_streak >= 3) {
    lines.push(`Gross margin has expanded for ${trend.margin_expansion_streak} straight quarters.`);
  }
  return lines.length
    ? `<div class="streaks">${lines.map(l => `<div>${esc(l)}</div>`).join('')}</div>`
    : '';
}

function quartersTable(rows) {
  const body = rows.map(r => `
    <tr>
      <td>${esc(r.period_end)}</td>
      <td class="num">${r.revenue != null ? fmtMoneyShort(r.revenue) : 'n/a'}</td>
      <td class="num">${r.gross_margin_pct != null ? r.gross_margin_pct.toFixed(1) + '%' : 'n/a'}</td>
      <td class="num">${r.eps_diluted != null ? r.eps_diluted.toFixed(2) : 'n/a'}</td>
    </tr>`).join('');
  return `
  <details class="qtable">
    <summary>Show all ${rows.length} quarters</summary>
    <table>
      <thead><tr><th>Quarter</th><th class="num">Revenue</th><th class="num">Gross margin</th><th class="num">EPS</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
  </details>`;
}

const VERDICT_COLOR = {
  'Improving': 'var(--green)',
  'Weakening': 'var(--red)',
  'Holding steady': 'var(--yellow)',
};

/* Only rendered for tickers with a positions_data/<TICKER>.json file —
   i.e. an actual held position, not just something on the watchlist. Most
   recent first (already sorted that way by attach_position_history.py). */
function positionHistoryBlock(history) {
  if (!history || !history.length) return '';
  const rows = history.map(e => `
    <div class="pos-entry">
      <div class="pos-entry-head">
        <span class="pos-date">${esc(e.date)} &middot; quarter ending ${esc(e.period_end)}</span>
        <span class="pos-verdict" style="color:${VERDICT_COLOR[e.verdict] || 'var(--muted)'}">${esc(e.verdict)}</span>
      </div>
      ${e.key_metric ? `<div class="pos-line">${esc(e.key_metric)}</div>` : ''}
      ${e.position_note ? `<div class="pos-line pos-position">${esc(e.position_note)}</div>` : ''}
    </div>`).join('');
  return `
  <details class="position-history">
    <summary>Your position &middot; ${history.length} logged ${history.length === 1 ? 'entry' : 'entries'}</summary>
    <div class="pos-entries">${rows}</div>
  </details>`;
}

function companyCard(company) {
  if (company.error) {
    return `<section class="card"><div class="card-head"><h2>${esc(company.ticker)}</h2></div>
      ${descLine(company.description)}
      <div class="error-card">${esc(company.error)}</div></section>`;
  }
  if (company.insufficient_data) {
    return `<section class="card"><div class="card-head"><h2>${esc(company.ticker)}</h2></div>
      ${descLine(company.description)}
      <div class="error-card">Only ${company.quarters_available} quarter(s) available — need at least 2 to compare.</div></section>`;
  }

  const s = statusFor(company);
  const gapNote = !company.is_quarterly_comparison
    ? `<div class="gap-note">Only ${company.gap_days}-day span between the two most recent
       filings (~${Math.round(company.gap_days / 30.4)} months) — common for a recently-public
       company. Treat this as a longer-term change, not quarter over quarter.</div>`
    : '';

  const reaction = company.analyst_reaction
    ? `<div class="reaction">EPS ${esc(company.analyst_reaction.eps)} &middot; `
      + `Consensus ${esc(company.analyst_reaction.consensus)} &middot; `
      + `Surprise ${esc(company.analyst_reaction.surprise)}</div>`
    : '';

  const trend = company.trend || {};
  // Labeled explicitly and kept visually distinct from everything below it
  // (a callout, not a bullet list) — this is the one part of the card
  // that's synthesized rather than independently computed from SEC/Nasdaq
  // data, and a reader should always be able to tell which is which.
  const story = company.story
    ? `<div class="story"><div class="story-label">AI summary</div>${esc(company.story)}</div>`
    : '';

  return `<section class="card" style="--s:${s.color}">
    <div class="card-head">
      <div>
        <h2>${esc(company.ticker)}</h2>
        <div class="period">Quarter ending ${esc(company.period_end)} vs. ${esc(company.compared_to)}</div>
      </div>
      <span class="badge">${s.label}</span>
    </div>
    ${descLine(company.description)}
    ${gapNote}
    ${story}
    ${sparklineContainer(trend.revenue_points || [], s.color)}
    ${streakNotes(trend)}
    <div class="cols">
      ${column('The Good', company.good, 'good')}
      ${column('The Bad', company.bad, 'bad')}
      ${column('The Ugly', company.ugly, 'ugly')}
    </div>
    ${flagsBlock(company.red_flags)}
    ${reaction}
    ${trend.quarters_table ? quartersTable(trend.quarters_table) : ''}
    ${positionHistoryBlock(company.position_history)}
  </section>`;
}

/* Lower number = shown first. A company with a high-severity flag is the
   one thing worth seeing before you scroll, so it leads; errored/thin-data
   entries have nothing actionable to show and sink to the bottom. */
function severityRank(company) {
  if (company.error || company.insufficient_data) return 3;
  const flags = company.red_flags || [];
  if (flags.some(f => f.severity === 'high')) return 0;
  if (flags.some(f => f.severity === 'medium')) return 1;
  return 2;
}

function render(data) {
  const companies = [...(data.companies || [])].sort((a, b) =>
    severityRank(a) - severityRank(b) || a.ticker.localeCompare(b.ticker));
  document.getElementById('grid').innerHTML = companies.map(companyCard).join('');
  drawSparklines();
}

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawSparklines, 150);
});

async function boot() {
  try {
    const r = await fetch('data.json?t=' + Date.now(), { cache: 'no-store' });
    const data = await r.json();
    render(data);
  } catch (e) {
    document.getElementById('grid').innerHTML =
      `<div class="error-card">Couldn't load data: ${esc(e.message)}</div>`;
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1800);
}

document.getElementById('share').addEventListener('click', async () => {
  const shareData = {
    title: 'Earnings Tracker',
    text: 'My earnings watchlist',
    url: location.href,
  };
  if (navigator.share) {
    try { await navigator.share(shareData); }
    catch (e) { /* user cancelled the share sheet — not an error */ }
  } else if (navigator.clipboard) {
    await navigator.clipboard.writeText(location.href);
    toast('Link copied');
  } else {
    toast(location.href);
  }
});

boot();
