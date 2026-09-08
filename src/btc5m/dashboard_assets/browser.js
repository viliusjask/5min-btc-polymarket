"use strict";
let browserState = null, browserDetail = null, browserFetching = false, browserLoaded = 0;
let browserDetailKey = null, browserDetailRequest = 0, browserDetailPending = null, browserDetailLoaded = 0;
let browserSort = "net", browserDescending = true, browserInitialized = false;
const browserSelected = new Set(), BROWSER_LIMIT = 8;
const BROWSER_COLORS = ["#79a8ff", "#4cdbb4", "#bd98ff", "#f1b569", "#62c8e8", "#ed93ba", "#d8da78", "#f1e7dc"];
const browserSource = (source) => ({paper: "Original portfolios", directional: "Directional study", "order-flow": "Order-flow study"})[source] || source;
const browserPhase = (row) => row.phase_kind === "holdout" ? "Later-data test · " + row.phase : row.phase_kind === "continuous" ? "Continuous · policy changes" : "Exploration · " + row.phase;
const browserCohort = () => $("browser-cohort").value;
const browserMetric = (row, key) => number(row.metrics[browserCohort()][key]);
const browserNumber = (value, format = money) => number(value) === null ? "Unavailable" : format(value);
const browserPercent = (value) => number(value) === null ? "Unavailable" : (Number(value) * 100).toFixed(2) + "%";

function browserFiltered() {
  if (!browserState) return [];
  const query = $("browser-search").value.trim().toLowerCase(), evidence = $("browser-evidence").value, activity = $("browser-activity").value;
  return browserState.experiments.filter(row => {
    const minimum = Math.max(0, Number($("browser-min-rounds").value) || 0);
    if (minimum > 0 && !(row.metrics[browserCohort()].completed >= minimum)) return false;
    if (query && ![row.label, row.family, row.source, row.phase, row.ident, row.version, JSON.stringify(row.parameters)].join(" ").toLowerCase().includes(query)) return false;
    if (["source", "family", "phase"].some(key => $("browser-" + key).value !== "all" && $("browser-" + key).value !== row[key])) return false;
    if (evidence === "flagged" && !(row.flagged_completed > 0)) return false;
    if (evidence === "unflagged" && !(row.metrics.unflagged.completed > 0)) return false;
    if (evidence === "unavailable" && !row.statistics_error && row.status !== "unavailable") return false;
    if (activity === "blocked") return row.budget_rejections > 0;
    return activity === "all" || activity === row.status;
  }).sort((a, b) => {
    if (browserSort === "label") return (browserDescending ? -1 : 1) * a.label.localeCompare(b.label) || a.key.localeCompare(b.key);
    const x = browserMetric(a, browserSort), y = browserMetric(b, browserSort);
    if (x === null || y === null) return x === y ? a.key.localeCompare(b.key) : x === null ? 1 : -1;
    return (browserDescending ? y - x : x - y) || a.key.localeCompare(b.key);
  });
}
function browserOptions() {
  for (const key of ["source", "family", "phase"]) {
    const el = $("browser-" + key), current = el.value;
    const values = [...new Set(browserState.experiments.map(r => r[key]))].sort();
    const items = [["all", "All " + (key === "family" ? "families" : key + "s")], ...values.map(v => [v, key === "source" ? browserSource(v) : human(v)])];
    researchOptions(el.id, items, values.includes(current) ? current : "all");
  }
}
function browserPlot(id, series, format = money) {
  const valid = series.flatMap(s => s.points.filter(p => number(p[1]) !== null));
  if (!valid.length) return empty(clear(id), "No completed curve for this selection", "Choose an experiment with completed capital-used rounds. Unknown results are not plotted as zero.");
  const limits = valid.reduce((b, p) => [Math.min(b[0], p[0]), Math.max(b[1], p[0]), Math.min(b[2], Number(p[1])), Math.max(b[3], Number(p[1]))], [Infinity, -Infinity, 0, 0]);
  const frame = chartFrame(id, limits[2], limits[3], [limits[0], limits[1]], format);
  for (const seriesRow of series) {
    if (!seriesRow.points.some(p => number(p[1]) !== null)) continue;
    let d = "", previous = null;
    for (const [at, value] of seriesRow.points) {
      if (number(value) === null) { previous = null; continue; }
      d += previous === null ? ` M ${frame.x(at)} ${frame.y(Number(value))}` : ` H ${frame.x(at)} V ${frame.y(Number(value))}`;
      previous = value;
    }
    const path = svgNode("path", {d, stroke: seriesRow.color, class: seriesRow.context ? "plotline browser-context-line" : "plotline", opacity: seriesRow.context ? .23 : 1, "stroke-width": seriesRow.context ? 1 : 2});
    path.append(svgNode("title", {}, seriesRow.name));
    frame.svg.append(path);
    const points = seriesRow.points.filter(p => number(p[1]) !== null);
    if (points.length === 1) frame.svg.append(svgNode("circle", {cx: frame.x(points[0][0]), cy: frame.y(Number(points[0][1])), r: 3, fill: seriesRow.color}));
  }
  frame.svg.addEventListener("mousemove", event => {
    const rect = frame.svg.getBoundingClientRect();
    const at = frame.start + Math.max(0, Math.min(1, (event.clientX - rect.left - frame.left) / (frame.w - frame.left - frame.right))) * (frame.end - frame.start);
    const values = [dateTime(at)];
    for (const s of series.filter(s => !s.context)) {
      if (at > s.points.at(-1)?.[0]) continue;
      const p = s.points.filter(p => p[0] <= at).at(-1);
      if (p && number(p[1]) !== null) values.push(s.name + ": " + format(p[1]));
    }
    tooltip(event, values);
  });
  frame.svg.addEventListener("mouseleave", () => { $("tooltip").hidden = true; });
}
function browserCurve(row, metric) {
  const points = row.curves[browserCohort()] || [];
  if (metric === "return" && !(Number(row.allocation) > 0)) return [];
  // Only add a zero origin to an observed completed-profit curve; never fabricate a no-fill curve.
  const origin = points.length && row.start_ms !== null && row.start_ms < points[0][0] ? [[row.start_ms, 0]] : [];
  return [...origin, ...points].map(([at, value]) => [at, metric === "return" ? Number(value) / Number(row.allocation) : Number(value)]);
}
function renderBrowserChart() {
  if (!browserState) return;
  const metric = $("browser-chart-metric").value, allContext = $("browser-all-curves").checked;
  const selected = [...browserSelected].map(k => browserState.experiments.find(r => r.key === k)).filter(Boolean);
  const context = allContext ? browserFiltered().filter(r => !browserSelected.has(r.key)) : [];
  const series = [...context.map(row => ({name: row.label, color: "#91a1b8", context: true, points: browserCurve(row, metric)})), ...selected.map((row, i) => ({name: row.label + " · " + browserSource(row.source) + " · " + row.phase, color: BROWSER_COLORS[i], points: browserCurve(row, metric)}))];
  browserPlot("browser-chart", series, metric === "return" ? browserPercent : money);
  const legendFocus = document.activeElement?.dataset.legendExperiment;
  const legendHost = clear("browser-legend");
  selected.forEach((row, i) => {
    const button = node("button", "quiet"), chip = node("span", "swatch");
    chip.style.background = BROWSER_COLORS[i];
    button.append(chip, node("span", "", row.label + " · " + row.source + " / " + row.phase + (row.curves[browserCohort()].length ? " ×" : " · no completed curve ×")));
    button.dataset.legendExperiment = row.key;
    button.setAttribute("aria-label", "Remove " + row.label + " " + row.source + " " + row.phase + " from comparison");
    button.addEventListener("click", () => { browserSelected.delete(row.key); renderBrowserTable(); renderBrowserChart(); });
    legendHost.append(button);
  });
  if (legendFocus) [...legendHost.querySelectorAll("button")].find(b => b.dataset.legendExperiment === legendFocus)?.focus({preventScroll: true});
  const plotted = context.filter(row => browserCurve(row, metric).length).length;
  $("browser-selection-count").textContent = selected.length + " / " + BROWSER_LIMIT + " highlighted · " + plotted + " other filtered curves in grey · " + context.filter(r => !r.curves[browserCohort()].length).length + " without a completed curve. Highlights remain selected when filters change.";
}
function renderBrowserTable() {
  const rows = browserFiltered(), host = $("browser-list"), scroll = [host.scrollTop, host.scrollLeft];
  const focus = document.activeElement, focusKey = focus?.dataset.openExperiment || focus?.dataset.compareExperiment, focusKind = focus?.dataset.openExperiment ? "openExperiment" : "compareExperiment";
  host.replaceChildren();
  const table = node("table"), head = node("thead"), tr = node("tr");
  const headers = [["Compare", null], ["Experiment", "label"], [browserCohort() === "all" ? "All realized net" : "Unflagged completed net", "net"], ["All realized return", "return"], ["Net / completed round", "mean"], ["Win rate", "win_rate"], ["Completed rounds", "completed"], ["Largest win", "best"], ["Observed equity drawdown", "drawdown"], ["Evidence / activity", null]];
  for (const [title, key] of headers) {
    const th = node("th");
    if (key) {
      th.setAttribute("aria-sort", key === browserSort ? browserDescending ? "descending" : "ascending" : "none");
      const button = node("button", "", title + (key === browserSort ? browserDescending ? " ↓" : " ↑" : ""));
      button.dataset.sort = key;
      button.addEventListener("click", () => { browserDescending = browserSort === key ? !browserDescending : key !== "label"; browserSort = key; renderBrowserTable(); renderBrowserChart(); $("browser-list").querySelector(`[data-sort="${key}"]`).focus(); });
      th.append(button);
    } else th.textContent = title;
    tr.append(th);
  }
  head.append(tr); table.append(head);
  const body = node("tbody");
  for (const row of rows) {
    const tr = node("tr"); tr.dataset.experimentKey = row.key;
    const compare = node("input"); compare.type = "checkbox"; compare.checked = browserSelected.has(row.key); compare.dataset.compareExperiment = row.key;
    compare.disabled = !compare.checked && browserSelected.size >= BROWSER_LIMIT;
    compare.setAttribute("aria-label", "Compare " + row.label + " " + row.source + " " + row.phase);
    compare.addEventListener("change", () => { compare.checked ? browserSelected.add(row.key) : browserSelected.delete(row.key); renderBrowserTable(); renderBrowserChart(); });
    const name = node("div"), button = node("button", "browser-name", row.label);
    button.dataset.openExperiment = row.key; button.addEventListener("click", () => openExperiment(row.key));
    name.append(button, node("div", "browser-meta", browserSource(row.source) + " · " + browserPhase(row) + " · " + row.family), node("div", "browser-meta", "Version " + (row.version?.slice(0, 12) || "unavailable")));
    const m = row.metrics[browserCohort()];
    const evidence = row.statistics_error ? "Round statistics unavailable" : row.status === "unavailable" ? "Report unavailable" : (row.flagged_completed ?? "?") + " flagged completed · " + human(row.status) + (row.budget_rejections ? " · historical LOSS_LIMIT: " + count(row.budget_rejections) : "");
    for (const cell of [compare, name, browserNumber(m.net), browserPercent(m.return), browserNumber(m.mean), browserPercent(m.win_rate), browserNumber(m.completed, count), browserNumber(m.best), browserNumber(m.drawdown), evidence]) {
      const td = node("td"); if (cell instanceof Node) td.append(cell); else td.textContent = cell; tr.append(td);
    }
    body.append(tr);
  }
  table.append(body); host.append(table);
  if (!rows.length) empty(host, "No experiments match these filters", "Reset filters or change the search. Saved experiments have not been removed.");
  $("browser-count").textContent = rows.length + " / " + browserState.experiments.length + " experiments";
  host.scrollTop = scroll[0]; host.scrollLeft = scroll[1];
  if (focus?.dataset.sort) host.querySelector(`[data-sort="${focus.dataset.sort}"]`)?.focus({preventScroll: true});
  if (focusKey) [...host.querySelectorAll("button, input")].find(el => el.dataset[focusKind] === focusKey)?.focus({preventScroll: true});
}
function renderBrowser() {
  if (!browserState || view !== "paper") return;
  const capture = browserState.capture, age = Date.now() - browserState.generated_ms;
  const latest = capture.latest?.code ? " · " + human(capture.latest.code) : "";
  $("browser-status").textContent = (capture.data_status === "recent" && Date.now() - capture.input_ms <= 15000 ? "Usable snapshot received recently" : capture.data_status === "loading" ? "Loading capture history" : "Usable market input " + (capture.data_status === "recent" ? "stale" : capture.data_status)) + latest + " · Recorder " + human(capture.status || "unknown");
  $("browser-updated").textContent = "Input " + dateTime(capture.input_ms) + " · report " + dateTime(browserState.generated_ms) + (age > 60000 ? " · displayed report is stale" : " · refresh 30s");
  $("browser-semantics").textContent = browserCohort() === "all" ? "All net includes recorded realized profit. Mean, win rate and completed count use capital-used completed rounds. Return always uses all realized profit / original allocation." : "Unflagged net is a completed-round subtotal, not restored capital. Return and observed equity drawdown still include all recorded trades. Mean and win rate use unflagged completed rounds.";
  $("browser-intro").textContent = browserState.experiments.length + " experiment / phase rows across " + new Set(browserState.experiments.map(r => r.source)).size + " sources. Phase and version distinguish repeated controls. Each retains its original capital and recorded flags.";
  $("browser-error").hidden = !browserState.errors.length;
  $("browser-error").textContent = browserState.errors.map(e => browserSource(e.source) + ": " + human(e.error)).join(" · ") + (browserState.errors.length ? ". Registered rows remain visible where their catalog is readable." : "");
  browserOptions();
  renderBrowserTable(); renderBrowserChart();
}
async function refreshBrowser() {
  if (browserFetching) return;
  if (browserState && Date.now() - browserLoaded < 30000) return;
  browserFetching = true;
  try {
    const response = await fetch("/api/experiments", {cache: "no-store", signal: AbortSignal.timeout(25000)});
    if (!response.ok) throw Error("Experiment catalog is unavailable. Previously displayed results may be stale.");
    browserState = await response.json(); browserLoaded = Date.now();
    if (!browserInitialized) {
      browserState.experiments.filter(r => r.source === "paper").slice(0, BROWSER_LIMIT).forEach(r => browserSelected.add(r.key));
      browserInitialized = true;
    }
    renderBrowser();
    if (browserDetailKey && view === "paper" && !$("experiment-detail").hidden) loadExperiment();
  } catch (error) { $("browser-error").hidden = false; $("browser-error").textContent = error.message; }
  finally { browserFetching = false; }
}
function showBrowser() {
  view = "paper"; $("paper-view").hidden = false; $("live-view").hidden = true; $("lab-view").hidden = true;
  $("paper-diagnostics").hidden = true; $("experiment-detail").hidden = true; $("experiment-browser").hidden = false;
  $("view-title").textContent = "Paper experiments"; $("view-badge").textContent = "SIMULATED · READ ONLY";
  for (const button of document.querySelectorAll("[data-view]")) { button.classList.toggle("selected", button.dataset.view === "paper"); button.setAttribute("aria-pressed", String(button.dataset.view === "paper")); }
  renderBrowser();
  const key = browserDetailKey;
  [...$("browser-list").querySelectorAll("[data-open-experiment]")].find(b => b.dataset.openExperiment === key)?.focus({preventScroll: true});
}
function openExperiment(key) {
  browserDetailKey = key; browserDetail = null; browserDetailLoaded = 0;
  $("experiment-browser").hidden = true; $("paper-diagnostics").hidden = true; $("experiment-detail").hidden = false;
  $("experiment-cohort").value = browserCohort();
  $("experiment-title").textContent = browserState.experiments.find(r => r.key === key)?.label || "Experiment";
  $("experiment-title").focus(); $("experiment-detail").scrollIntoView({block: "start"});
  for (const id of ["experiment-metrics", "experiment-net-chart", "experiment-drawdown-chart", "experiment-risk", "experiment-round-chart", "experiment-hour-chart", "experiment-hours", "experiment-concentration", "experiment-costs", "experiment-groups", "experiment-rounds", "experiment-orders", "experiment-config"]) clear(id);
  for (const id of ["experiment-conclusion", "experiment-policy", "experiment-risk-note", "experiment-orders-note", "experiment-limits", "experiment-drawdown-note", "experiment-cost-note", "experiment-identity"]) $(id).textContent = "";
  $("experiment-status").textContent = "Reading selected experiment…";
  loadExperiment();
}
async function loadExperiment() {
  if (!browserDetailKey) return;
  if (browserDetail && Date.now() - browserDetailLoaded < 30000 && browserDetail.cohort === browserCohort()) return;
  browserDetailPending?.abort();
  const controller = new AbortController(); browserDetailPending = controller;
  const request = ++browserDetailRequest, key = browserDetailKey;
  const timeout = setTimeout(() => controller.abort(), 20000);
  $("experiment-error").hidden = true;
  try {
    const response = await fetch("/api/experiment?" + new URLSearchParams({key, cohort: browserCohort()}), {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw Error("The selected journal or its registered phase is unavailable. Its row remains in the list; other experiments are still accessible.");
    const result = await response.json();
    if (request !== browserDetailRequest || key !== browserDetailKey) return;
    browserDetail = result; browserDetailLoaded = Date.now(); renderExperiment();
  } catch (error) {
    if (request !== browserDetailRequest) return;
    $("experiment-error").hidden = false; $("experiment-error").textContent = error.name === "AbortError" ? "The selected read timed out. Return to the list or retry this experiment." : error.message;
    $("experiment-status").textContent = browserDetail ? "Previous analysis retained; it may be stale." : "Analysis unavailable";
  } finally { clearTimeout(timeout); if (request === browserDetailRequest) browserDetailPending = null; }
}
function renderExperimentGroups() {
  const groups = browserDetail?.analysis.groups[$("experiment-group").value] || [];
  labTable("experiment-groups", ["Condition", "Completed rounds", "Net", "Mean / round", "Win rate"], groups.map(g => [g.label, count(g.rounds), money(g.net), money(g.mean), browserPercent(g.win_rate)]), "Lifetime entry-condition data is unavailable for this source. Recent fills are not used as a substitute for the full sample.");
}
function renderExperiment() {
  if (!browserDetail || view !== "paper" || $("experiment-detail").hidden) return;
  const d = browserDetail, row = d.experiment, a = d.analysis, s = a.stats, wallet = d.wallet, baseline = row.source === "paper";
  const m = row.metrics[d.cohort];
  $("experiment-title").textContent = row.label;
  $("experiment-identity").textContent = browserSource(row.source) + " · " + browserPhase(row) + " · " + row.ident;
  $("experiment-status").textContent = (d.cohort === "all" ? "All completed rounds, including flags" : "Unflagged completed subtotal; original losses still affect capital and risk limits") + " · " + dateTime(row.start_ms) + " through " + dateTime(d.clock.window_end_ms) + " · analysis read " + dateTime(d.generated_ms) + " · financial report " + dateTime(row.report_generated_ms);
  if (d.report_matches_analysis === false) { $("experiment-error").hidden = false; $("experiment-error").textContent = "The journal advanced beyond the saved wallet report. Account net and return are unavailable here until the report catches up. Completed-round analysis below uses the journal time shown above; saved orders and risk diagnostics retain their report time."; }
  $("experiment-policy").textContent = row.policy_note + " Version " + (row.version || "unavailable") + (d.policy_change?.at_ms ? " · recorded policy change " + dateTime(d.policy_change.at_ms) : "");
  labMetrics("experiment-metrics", [
    [d.cohort === "all" ? "ALL REALIZED NET" : "UNFLAGGED COMPLETED SUBTOTAL", browserNumber(m.net), "Original allocation " + money(row.allocation)],
    ["ALL REALIZED RETURN", browserPercent(m.return), "All recorded realized net / original allocation; unchanged by flag filtering"],
    ["COMPLETED NET / ROUND", browserNumber(s.mean), s.rounds + " completed capital-used markets · " + s.flagged_rounds + " flagged in selected cohort"],
    ["WIN RATE", browserPercent(s.win_rate), s.wins + " wins · " + s.losses + " losses · " + s.flat + " flat"],
    ["RECORDED FEES", browserNumber(row.fees), money(s.fees) + " in selected completed cohort"],
    ["INCOMPLETE MARKETS", count(a.counts.incomplete_used), a.counts.flagged_used + " capital-used markets carry recorded flags"],
  ]);
  $("experiment-conclusion").textContent = s.rounds ? money(s.net) + " completed net from " + s.rounds + " markets; median " + money(s.median) + ". " + (s.best_win_share === null ? "No winning rounds in this cohort. " : "Largest win accounts for " + browserPercent(s.best_win_share) + " of all winning dollars. ") + (s.without_best_3 === null ? "Too few results for the remove-three-winners check. " : "Removing up to three largest wins leaves " + money(s.without_best_3) + ". ") + "Shared market history and selecting from many variants limit this evidence; it is not proof of future profit." : "No completed capital-used rounds in this cohort. No win rate or profit-per-round result can be inferred.";
  browserPlot("experiment-net-chart", [{name: row.label, color: "#4cdbb4", points: browserCurve(row, "net")}]);
  const equity = baseline ? [] : wallet.equity_series || [];
  let peak = Number(row.allocation || 0);
  const drawdown = equity.map(([at, value]) => { if (number(value) === null) return [at, null]; peak = Math.max(peak, Number(value)); return [at, peak - Number(value)]; });
  if (baseline) empty(clear("experiment-drawdown-chart"), "Marked equity history unavailable", "Realized profit alone cannot measure losses on held inventory.");
  else browserPlot("experiment-drawdown-chart", [{name: "Observed decline from peak", color: "#ef8288", points: drawdown}]);
  $("experiment-drawdown-note").textContent = baseline ? "The original journals have no comparable historical bid-marked equity series. Drawdown is deliberately unavailable." : "Maximum from retained marks: " + money(wallet.observed_drawdown) + ". Chart uses sampled bid-marked equity; gaps break the line and can conceal larger losses. " + count(wallet.missing_equity_marks) + " missing marks. Marked value does not guarantee full liquidation.";
  const risk = wallet.risk_budget || {}, last = wallet.last_execution;
  $("experiment-risk-note").textContent = "LOSS_LIMIT protects daily and session loss budgets. New spending must fit after realized losses, held position risk and existing order reservations. A fresh day does not reset a continuing session. " + (row.budget_rejections ? count(row.budget_rejections) + " historical budget rejections are recorded; that count does not prove a current block. " : "") + (last ? "Latest recorded outcome: " + human(last.code || last.reason) + " at " + dateTime(last.received_ms) + ". " : "") + (row.blocked_reasons.length ? "Recorded halts: " + row.blocked_reasons.join(", ") + ". " : "") + (!Object.keys(risk).length ? "Current risk-budget headroom is unavailable in this report; an empty halt list does not mean an entry can proceed." : "Remaining loss budget is before any proposed new order, and is not spendable cash.");
  labTable("experiment-risk", ["Recorded quantity", "Value"], [["Cash", browserNumber(row.cash)], ["Held cost", browserNumber(row.held_cost)], ["Unresolved orders / rounds (source-specific)", browserNumber(row.unresolved, count)], ...Object.entries(risk).map(([k, v]) => [human(k), browserNumber(v)]), ...Object.entries(row.risk_limits || {}).map(([k, v]) => ["Registered " + human(k), String(v)])]);
  researchBars("experiment-round-chart", a.rounds.map(r => ({at_ms: r.start_ms, value: r.net, flagged: r.uncertain})), "No completed capital-used markets.");
  researchBars("experiment-hour-chart", a.hourly.filter(h => h.used_rounds).map(h => ({at_ms: h.at_ms, value: h.net, flagged: h.flagged_rounds > 0})), "No completed hours.");
  labTable("experiment-hours", ["Opening hour UTC", "Net", "Completed", "Excluded used rounds"], a.hourly.map(h => [dateTime(h.at_ms), money(h.net), count(h.used_rounds), count(h.excluded_used)]));
  labTable("experiment-concentration", ["Selected sample", "Value"], [["Completed net", money(s.net)], ["Largest winning share", browserPercent(s.best_win_share)], ["Without largest win", browserNumber(s.without_best_1)], ["Without up to three largest wins", browserNumber(s.without_best_3)], ["Average win / loss", browserNumber(s.average_win) + " / " + browserNumber(s.average_loss)], ["Median round", browserNumber(s.median)]]);
  labTable("experiment-costs", ["Cost assumption", "Net"], [["Before recorded fees", money(s.before_fees)], ["After recorded fees", money(s.net)], ...(s.cost_stress || []).slice(1).map(c => ["Extra " + (Number(c.extra_per_share) * 100).toFixed(2) + "¢ / filled share", money(c.net)])]);
  $("experiment-cost-note").textContent = baseline ? "Fees cover the full selected accounting sample. Per-share sensitivity is unavailable because this source exports only recent individual fills." : "Extra costs apply to bought and sold shares while keeping recorded fills unchanged. This does not simulate liquidity changes, market impact, cash constraints, gas, or maker rebates.";
  renderExperimentGroups();
  labTable("experiment-rounds", ["Market opening UTC", "Net after fees", "Fees", "First filled entry", "Outcome", "Exit", "Flagged"], [...a.rounds].sort((x, y) => x.start_ms - y.start_ms).map(r => [dateTime(r.start_ms), money(r.net), money(r.fees), browserNumber(r.entry_price, quotePrice), r.direction || "Unavailable", r.exit_reason || "Settlement / unavailable", r.uncertain ? "Yes" : "No"]));
  const orders = baseline ? wallet.recent_orders || [] : wallet.orders || [];
  $("experiment-orders-note").textContent = "Oldest first within the latest " + (baseline ? "100" : "50") + " orders supplied by the source report. This bounded journal is not the lifetime trade count. Unfilled orders are not wins or losses.";
  labTable("experiment-orders", ["Order created UTC", "Market", "Action", "Outcome", "Filled shares", "Filled principal", "Fee", "Price limit", "Execution result"], [...orders].sort((x, y) => (x.created_ms ?? x.at_ms) - (y.created_ms ?? y.at_ms)).map(o => [dateTime(o.created_ms ?? o.at_ms), o.slug, o.side, o.outcome ?? o.outcome_side ?? "Unavailable", browserNumber(o.confirmed_quantity ?? o.filled_shares, v => Number(v).toFixed(4)), browserNumber(o.filled_principal), browserNumber(o.fee), quotePrice(o.price_limit ?? o.limit), human(o.execution_status || o.reason) + (o.execution_reason ? " · " + human(o.execution_reason) : "")]));
  const configRows = [];
  function flatten(value, prefix = "") { for (const [key, v] of Object.entries(value || {})) { const label = prefix ? prefix + "." + key : key; if (v && typeof v === "object") flatten(v, label); else configRows.push([label, String(v ?? "Unavailable")]); } }
  flatten(d.configuration);
  if (d.phase_selection) flatten(Object.fromEntries(Object.entries(d.phase_selection).filter(([,value]) => value === null || typeof value !== "object")), "phase_selection");
  labTable("experiment-config", ["Recorded parameter", "Value"], configRows, "Full captured configuration is unavailable; current code defaults must not be presented as historical settings.");
  $("experiment-limits").textContent = d.limitations.join(" ") + " All/unflagged filters are descriptive; excluded past trades still influenced wallet cash and budget guards.";
  $("experiment-research").hidden = baseline;
  $("experiment-compare").disabled = !browserSelected.has(row.key) && browserSelected.size >= BROWSER_LIMIT;
  $("experiment-compare").textContent = browserSelected.has(row.key) ? "Already highlighted in comparison" : "Add to comparison (" + browserSelected.size + "/" + BROWSER_LIMIT + ")";
}
async function experimentContext(section) {
  if (!browserDetail) return;
  const row = browserDetail.experiment;
  if (row.source === "paper") {
    $("experiment-browser").hidden = true; $("experiment-detail").hidden = true; $("paper-diagnostics").hidden = false;
    selection = row.ident; await refresh(); $("strategy").value = row.ident; render();
    $("paper-diagnostics").scrollIntoView(); return;
  }
  labSuite = row.source; labPhase = row.phase; labSelection = row.ident; labSection = section;
  $("lab-suite").value = labSuite; $("lab-family").value = "all";
  labState = null; view = "lab"; $("paper-view").hidden = true; $("lab-view").hidden = false;
  $("lab-content").hidden = true; $("strategy-research").hidden = true;
  for (const button of document.querySelectorAll("[data-lab-section]")) { const selected = button.dataset.labSection === section; button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", String(selected)); }
  await refreshLab(); $("lab-view").scrollIntoView();
}
for (const id of ["browser-source", "browser-family", "browser-phase", "browser-evidence", "browser-activity"]) $(id).addEventListener("change", () => { renderBrowserTable(); renderBrowserChart(); });
$("browser-search").addEventListener("input", () => { renderBrowserTable(); renderBrowserChart(); });
$("browser-min-rounds").addEventListener("input", () => { renderBrowserTable(); renderBrowserChart(); });
$("experiment-cohort").addEventListener("change", () => { $("browser-cohort").value = $("experiment-cohort").value; loadExperiment(); });
$("browser-cohort").addEventListener("change", () => { renderBrowser(); if (browserDetailKey && !$("experiment-detail").hidden) loadExperiment(); });
$("browser-reset-filters").addEventListener("click", () => { $("browser-search").value = ""; $("browser-min-rounds").value = "0"; for (const id of ["source", "family", "phase", "evidence", "activity"]) $("browser-" + id).value = "all"; renderBrowserTable(); renderBrowserChart(); });
$("browser-clear-selection").addEventListener("click", () => { browserSelected.clear(); renderBrowserTable(); renderBrowserChart(); });
$("browser-compare-visible").addEventListener("click", () => { browserSelected.clear(); browserFiltered().slice(0, BROWSER_LIMIT).forEach(row => browserSelected.add(row.key)); renderBrowserTable(); renderBrowserChart(); });
for (const id of ["browser-chart-metric", "browser-all-curves"]) $(id).addEventListener("change", renderBrowserChart);
$("experiment-back").addEventListener("click", showBrowser);
for (const button of document.querySelectorAll("[data-return-browser]")) button.addEventListener("click", showBrowser);
$("experiment-compare").addEventListener("click", () => { if (browserSelected.size < BROWSER_LIMIT) browserSelected.add(browserDetailKey); showBrowser(); });
$("experiment-group").addEventListener("change", renderExperimentGroups);
$("experiment-diagnostics").addEventListener("click", () => experimentContext("overview"));
$("experiment-research").addEventListener("click", () => experimentContext("research"));
$("experiment-export").addEventListener("click", () => { if (!browserDetail) return; const url = URL.createObjectURL(new Blob([JSON.stringify(browserDetail, null, 2)], {type: "application/json"})); const link = node("a"); link.href = url; link.download = "btc5m-experiment.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
window.addEventListener("resize", () => { if (view !== "paper") return; if (!$("experiment-detail").hidden) renderExperiment(); else if (!$("experiment-browser").hidden) renderBrowserChart(); });
