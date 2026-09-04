const API_BASE =
  window.ATS_API_BASE ||
  "http://localhost:5000";

const state = {
  search: "",
  industries: new Set(),
  tiers: new Set(),
  minScore: 0,
  sortBy: "ats_score",
  sortDir: "desc",
  page: 1,
  pageSize: 15,
};

function debounce(fn, wait) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

async function fetchJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.industries.size) params.set("industry", Array.from(state.industries).join(","));
  if (state.tiers.size) params.set("tier", Array.from(state.tiers).join(","));
  if (state.minScore > 0) params.set("min_score", String(state.minScore));
  params.set("sort_by", state.sortBy);
  params.set("sort_dir", state.sortDir);
  params.set("page", String(state.page));
  params.set("page_size", String(state.pageSize));
  return params.toString();
}

function formatCurrency(value) {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safePercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

async function loadMeta() {
  const meta = await fetchJSON("/api/meta");
  const industryList = document.getElementById("industry-list");
  industryList.innerHTML = meta.industries
    .map(
      (ind) => `
      <label>
        <input type="checkbox" value="${escapeHTML(ind)}" class="industry-checkbox" />
        ${escapeHTML(ind)}
      </label>`
    )
    .join("");

  const tierList = document.getElementById("tier-list");
  tierList.innerHTML = meta.tiers
    .map((t) => `<button class="tier-chip" data-tier="${escapeHTML(t)}" type="button">Tier ${escapeHTML(t)}</button>`)
    .join("");
}

async function loadStats() {
  const bar = document.getElementById("stats-bar");
  try {
    const stats = await fetchJSON(`/api/stats/summary?${buildQuery()}`);
    const filtered = state.search || state.industries.size || state.tiers.size || state.minScore > 0;
    bar.innerHTML = `
      <div class="stat-block">
        <div class="stat-value">${stats.total_leads}</div>
        <div class="stat-label">${filtered ? "Matching leads" : "Total leads"}</div>
      </div>
      <div class="stat-block">
        <div class="stat-value">${stats.average_score}</div>
        <div class="stat-label">Average ATS score${filtered ? " (filtered)" : ""}</div>
      </div>
      <div class="stat-block">
        <div class="stat-label" style="margin-bottom:6px">Tier breakdown${filtered ? " (filtered)" : ""}</div>
        <div>
          ${["A", "B", "C", "D"]
            .map(
              (t) =>
                `<span class="tier-count"><span class="n">${stats.tier_counts[t]}</span><span class="t">Tier ${t}</span></span>`
            )
            .join("")}
        </div>
      </div>
    `;
  } catch (err) {
    bar.innerHTML = `<div class="stat-skeleton">Could not load stats (${err.message}). Is the API running on ${API_BASE}?</div>`;
  }
}

function renderTableRows(items) {
  const tbody = document.getElementById("lead-table-body");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No leads match the current filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = items
    .map(
      (item) => `
      <tr data-lead-id="${item.id}">
        <td class="company-name">${escapeHTML(item.company_name)}</td>
        <td class="hide-narrow">${escapeHTML(item.industry)}</td>
        <td class="num">${formatCurrency(item.estimated_annual_revenue)}</td>
        <td class="num hide-narrow">${item.years_in_business}</td>
        <td class="score-cell">
          <span class="score-num">${item.ats_score}</span>
          <span class="tier-badge ${item.ats_tier}">${item.ats_tier}</span>
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("tr[data-lead-id]").forEach((row) => {
    row.addEventListener("click", () => openDrawer(row.dataset.leadId));
  });
}

function renderPagination(data) {
  const el = document.getElementById("pagination");
  const start = (data.page - 1) * data.page_size + 1;
  const end = Math.min(data.page * data.page_size, data.total);
  el.innerHTML = `
    <span>${data.total === 0 ? "0 results" : `${start}-${end} of ${data.total}`}</span>
    <span>
      <button id="prev-page" ${data.page <= 1 ? "disabled" : ""}>Prev</button>
      <button id="next-page" ${data.page >= data.total_pages ? "disabled" : ""}>Next</button>
    </span>
  `;
  document.getElementById("prev-page")?.addEventListener("click", () => {
    state.page = Math.max(1, state.page - 1);
    loadLeads();
  });
  document.getElementById("next-page")?.addEventListener("click", () => {
    state.page = state.page + 1;
    loadLeads();
  });
}

async function loadLeads() {
  const tbody = document.getElementById("lead-table-body");
  try {
    const data = await fetchJSON(`/api/leads?${buildQuery()}`);
    renderTableRows(data.items);
    renderPagination(data);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Could not load leads (${err.message}).</td></tr>`;
  }
}

// Filter changes affect both the table AND the stats bar; pagination and
// column-sort only affect the table. Keeping these separate avoids an
// unnecessary stats refetch on every page click or sort toggle.
async function refresh() {
  await Promise.all([loadLeads(), loadStats()]);
}

async function openDrawer(leadId) {
  const overlay = document.getElementById("drawer-overlay");
  const drawer = document.getElementById("drawer");
  const content = document.getElementById("drawer-content");

  overlay.classList.remove("hidden");
  drawer.classList.remove("hidden");
  content.innerHTML = `<p style="color:var(--text-muted)">Loading…</p>`;

  try {
    const lead = await fetchJSON(`/api/leads/${leadId}`);
    content.innerHTML = `
      <h2>${escapeHTML(lead.company_name)}</h2>
      <div class="drawer-sub">${escapeHTML(lead.industry)} · ${escapeHTML(lead.city)}, ${escapeHTML(lead.state)}</div>

      <div class="drawer-score-total">
        <span class="big">${lead.score.total_score}</span>
        <span class="tier-badge ${lead.score.tier}">${lead.score.tier}</span>
      </div>

      <div class="evidence-card">
        <div class="evidence-head">
          <span>Decision confidence</span>
          <span class="evidence-score">${safePercent(lead.evidence.confidence_score)}% · ${escapeHTML(lead.evidence.label)}</span>
        </div>
        <div class="evidence-track"><div class="evidence-fill" style="width:${safePercent(lead.evidence.confidence_score)}%"></div></div>
        <div class="evidence-caveat">${escapeHTML(lead.evidence.caveat)}</div>
        ${lead.evidence.gaps.length ? `
          <div class="evidence-label">What still needs verification</div>
          <ul class="evidence-list">${lead.evidence.gaps.map((g) => `<li>${escapeHTML(g)}</li>`).join("")}</ul>
        ` : ""}
        <div class="next-action"><span>Next diligence step</span>${escapeHTML(lead.evidence.next_action)}</div>
      </div>

      ${lead.score.factors
        .map(
          (f) => `
        <div class="factor">
          <div class="factor-head">
            <span class="fname">${escapeHTML(f.name)}</span>
            <span class="fpoints">${f.points} / ${(f.weight * 100).toFixed(0)}</span>
          </div>
          <div class="factor-bar-track">
            <div class="factor-bar-fill" style="width:${safePercent(f.raw_score)}%"></div>
          </div>
          <div class="factor-rationale">${escapeHTML(f.rationale)}</div>
        </div>
      `
        )
        .join("")}

      <div class="drawer-meta-row"><span>Employees</span><span>${lead.employee_count}</span></div>
      <div class="drawer-meta-row"><span>Years in business</span><span>${lead.years_in_business}</span></div>
      <div class="drawer-meta-row"><span>Ownership</span><span>${escapeHTML(lead.ownership_type)}</span></div>
      <div class="drawer-meta-row"><span>Est. annual revenue</span><span>${formatCurrency(lead.estimated_annual_revenue)}</span></div>

      <div class="source-note">${escapeHTML(lead.source_note)}</div>
    `;
  } catch (err) {
    content.innerHTML = `<p class="empty-state">Could not load lead detail (${err.message}).</p>`;
  }
}

function closeDrawer() {
  document.getElementById("drawer-overlay").classList.add("hidden");
  document.getElementById("drawer").classList.add("hidden");
}

function attachStaticListeners() {
  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  document.getElementById("drawer-overlay").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  document.getElementById("search-input").addEventListener(
    "input",
    debounce((e) => {
      state.search = e.target.value.trim();
      state.page = 1;
      refresh();
    }, 300)
  );

  document.getElementById("min-score-input").addEventListener("input", (e) => {
    state.minScore = Number(e.target.value);
    document.getElementById("min-score-value").textContent = String(state.minScore);
    state.page = 1;
    refresh();
  });

  document.getElementById("reset-filters").addEventListener("click", () => {
    state.search = "";
    state.industries.clear();
    state.tiers.clear();
    state.minScore = 0;
    state.page = 1;
    document.getElementById("search-input").value = "";
    document.getElementById("min-score-input").value = "0";
    document.getElementById("min-score-value").textContent = "0";
    document.querySelectorAll(".industry-checkbox").forEach((cb) => (cb.checked = false));
    document.querySelectorAll(".tier-chip").forEach((chip) => (chip.className = "tier-chip"));
    refresh();
  });

  document.getElementById("industry-list").addEventListener("change", (e) => {
    if (!e.target.classList.contains("industry-checkbox")) return;
    if (e.target.checked) state.industries.add(e.target.value);
    else state.industries.delete(e.target.value);
    state.page = 1;
    refresh();
  });

  document.getElementById("tier-list").addEventListener("click", (e) => {
    const chip = e.target.closest(".tier-chip");
    if (!chip) return;
    const tier = chip.dataset.tier;
    if (state.tiers.has(tier)) {
      state.tiers.delete(tier);
      chip.className = "tier-chip";
    } else {
      state.tiers.add(tier);
      chip.className = `tier-chip active-${tier}`;
    }
    state.page = 1;
    refresh();
  });

  document.querySelectorAll(".lead-table th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const field = th.dataset.sort;
      if (state.sortBy === field) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortBy = field;
        state.sortDir = "desc";
      }
      document.querySelectorAll(".lead-table th").forEach((h) => {
        h.classList.remove("sort-active");
        h.removeAttribute("aria-sort");
      });
      th.classList.add("sort-active");
      th.setAttribute("aria-sort", state.sortDir === "asc" ? "ascending" : "descending");
      loadLeads();
    });
  });

  document.getElementById("export-btn").addEventListener("click", () => {
    window.open(`${API_BASE}/api/leads/export.csv?${buildQuery()}`, "_blank");
  });
}

async function init() {
  attachStaticListeners();
  await Promise.all([loadMeta(), loadStats()]);
  await loadLeads();
}

init();
