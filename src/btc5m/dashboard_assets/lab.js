"use strict";
let labState, labFetching = false, labPhase = "explore", labSelection = null;
let labSuite = "directional";
const labNumber = (v, digits = 3) => number(v) === null ? "—" : Number(v).toFixed(digits);
const labPercent = (v) => number(v) === null ? "—" : (Number(v) * 100).toFixed(1) + "%";

function labMetrics(id, rows) {
  const root = clear(id);
  for (const [label, value, note] of rows) {
    const e = node("div", "metric");
    e.append(node("div", "metric-label", label), node("div", "metric-value", value), node("div", "metric-note", note));
    root.append(e);
  }
}
function labTable(id, headers, rows, message = "No records yet") {
  const root = clear(id);
  if (!rows.length) return empty(root, message, "Unavailable values are shown as a dash.");
  const table = node("table"), head = node("thead"), tr = node("tr"), body = node("tbody");
  for (const h of headers) tr.append(node("th", "", h));
  head.append(tr); table.append(head, body);
  for (const values of rows) {
    const row = node("tr");
    for (const v of values) {
      const td = node("td");
      td.append(v instanceof Node ? v : document.createTextNode(v ?? "—"));
      row.append(td);
    }
    body.append(row);
  }
  root.append(table);
}
function labValue(row, metric) {
  if (metric === "clean_completed_pnl" && !row.clean_completed_rounds) return null;
  if (metric === "realized_pnl" && !(row.deployed_rounds ?? row.filled_rounds)) return null;
  return number(row[metric]);
}
function labFormat(value, metric) {
  return value === null ? "—" : metric === "filled_rounds" ? count(value) : money(value);
}
function labChoose(ident) { labSelection = ident; renderLab(); }
function labHeatmap(variants, metric) {
  const grid = variants.filter(v => v.family === "momentum");
  const windowName = v => v.parameters.entry_min_seconds + "–" + v.parameters.entry_max_seconds + "s";
  const leads = [...new Set(grid.map(v => Number(v.parameters.lead_usd)))].sort((a,b) => a-b);
  const windows = [...new Set(grid.map(windowName))].sort();
  labTable("lab-heatmap", ["BTC lead", ...windows], leads.map(lead => ["$" + lead, ...windows.map(window => {
    const v = grid.find(x => Number(x.parameters.lead_usd) === lead && windowName(x) === window);
    if (!v) return "—";
    const value = labValue(v, metric);
    const button = node("button", "lab-cell" + (v.ident === labSelection ? " selected" : ""), labFormat(value, metric) + " · " + v.clean_completed_rounds);
    button.classList.toggle("positive", value !== null && value > 0 && metric !== "observed_drawdown");
    button.classList.toggle("negative", value !== null && (value < 0 || metric === "observed_drawdown" && value > 0));
    button.title = v.label + "; " + v.filled_rounds + " filled rounds; fill rate " + labPercent(v.fill_rate);
    button.addEventListener("click", () => labChoose(v.ident));
    return button;
  })]), "No momentum grid in this phase");
}
function labCalibration(scoring) {
  const central = scoring.models.central, market = scoring.models.market;
  const paired = scoring.comparisons.central_vs_market, fast = scoring.comparisons.fast_vs_central;
  labTable("lab-forecast-metrics", ["Forecast", "Rounds", "Brier ↓", "Log loss ↓"], [
    ["Central model", count(central.n), labNumber(central.brier), labNumber(central.log_loss)],
    ["Market midpoint", count(market.n), labNumber(market.brier), labNumber(market.log_loss)],
    ["Aligned fast model", count(scoring.models.fast.n), labNumber(scoring.models.fast.brier), labNumber(scoring.models.fast.log_loss)],
  ]);
  const host = clear("lab-calibration"), bins = central.bins.filter(b => b.n);
  if (!bins.length) empty(host, "Waiting for settled forecast observations", "One sample per round at 120 seconds remaining, regardless of entry eligibility.");
  else {
    const w = Math.max(host.clientWidth, 280), h = 220, x = p => 44 + p * (w - 65), y = p => 183 - p * 155;
    const svg = svgNode("svg", {viewBox: "0 0 " + w + " " + h, role: "img", "aria-label": "Calibration: forecast probability versus observed Up frequency"});
    for (const p of [0, .25, .5, .75, 1]) {
      svg.append(svgNode("line", {x1: x(0), y1: y(p), x2: x(1), y2: y(p), class: "gridline"}), svgNode("text", {x: x(p), y: 202, "text-anchor": "middle"}, p*100 + "%"), svgNode("text", {x: 38, y: y(p)+3, "text-anchor": "end"}, p*100 + "%"));
    }
    svg.append(svgNode("line", {x1:x(0),y1:y(0),x2:x(1),y2:y(1),class:"lab-diagonal"}));
    for (const b of bins) {
      if (b.descriptive_wilson95) svg.append(svgNode("line", {x1:x(b.mean_probability),x2:x(b.mean_probability),y1:y(b.descriptive_wilson95[0]),y2:y(b.descriptive_wilson95[1]),class:"lab-interval"}));
      const dot = svgNode("circle", {cx:x(b.mean_probability),cy:y(b.observed_up),r:5,fill:"#4cdbb4"});
      dot.append(svgNode("title", {}, b.n + " rounds: model " + labPercent(b.mean_probability) + ", observed " + labPercent(b.observed_up)));
      svg.append(dot);
    }
    host.append(svg);
  }
  $("lab-forecast-note").textContent = scoring.expected_rounds + " scheduled rounds; " + scoring.missing_labels + " without a usable official label. Model minus market Brier: " + labNumber(paired.brier_difference) + " on " + paired.n + " matched rounds. Fast minus central: " + labNumber(fast.brier_difference) + " on " + fast.n + " matched rounds. Negative differences are better. Horizontal: predicted Up; vertical: observed Up. Bars describe small-sample uncertainty under independent rounds; they do not establish trading edge. Log loss clips at 1e-6. Scenario buffers are tested separately.";
}
function labEquity(row) {
  const points = row.equity_series || [], observed = points.filter(p => number(p[1]) !== null);
  if (!observed.length) return empty(clear("lab-equity"), "No observable equity marks", "An absent liquidation quote is not valued at zero.");
  const values = observed.map(p => Number(p[1]));
  const f = chartFrame("lab-equity", Math.min(Number(row.allocation), ...values), Math.max(Number(row.allocation), ...values), [points[0][0], points.at(-1)[0]], money);
  f.svg.append(svgNode("line", {x1:f.x(points[0][0]),x2:f.x(points.at(-1)[0]),y1:f.y(Number(row.allocation)),y2:f.y(Number(row.allocation)),class:"lab-diagonal"}));
  let path = "", broken = true;
  for (const [t,v] of points) {
    if (number(v) === null) { broken = true; continue; }
    path += (broken ? "M" : "L") + " " + f.x(t) + " " + f.y(Number(v)) + " "; broken = false;
  }
  f.svg.append(svgNode("path", {d:path,class:"plotline",stroke:"#4cdbb4"}));
}
function labDetail(row, phase) {
  $("lab-detail-title").textContent = row.label;
  $("lab-evidence").textContent = phase.kind === "holdout" ? "FROZEN LATER-DATA TEST" : row.evidence.toUpperCase();
  const p = row.parameters;
  $("lab-parameters").textContent = p.mode.replaceAll("_"," ") + " · " + p.entry_min_seconds + "–" + p.entry_max_seconds + "s remaining · " + (p.signal === "core" ? "original entry rule" : p.signal + " signal, threshold " + p.signal_threshold) + " · " + p.exit_policy.replaceAll("_"," ") + " exits · " + money(p.stop_per_share) + " absolute stop when enabled · " + p.latency_ms + "ms minimum execution delay · " + (p.scenario === "central" ? "central probability" : "$" + p.adverse_reference_usd + " reference stress") + " · variant " + row.ident;
  labMetrics("lab-wallet", [
    ["PAPER EQUITY", money(row.equity), money(row.cash) + " cash · " + money(row.open_basis) + " held cost"],
    ["REALIZED PROFIT", (row.deployed_rounds ?? row.filled_rounds) ? money(row.realized_pnl) : "—", money(row.fees) + " fees · " + row.unresolved_rounds + " unresolved rounds"],
    ["USABLE COMPLETED PROFIT", row.clean_completed_rounds ? money(row.clean_completed_pnl) : "—", row.clean_completed_rounds + " completed · " + row.uncertain_rounds + " uncertain observed rounds"],
    ["OBSERVED DRAWDOWN", money(row.observed_drawdown), row.missing_equity_marks + " missing marks · gaps may hide larger losses"],
  ]);
  labEquity(row);
  $("lab-equity-note").textContent = "Cash plus held inventory at observed bid depth, after estimated exit fees. Dashed line: " + money(row.allocation) + " initial capital. The chart is sampled; drawdown uses all retained five-second marks. Minimum-size constraints may prevent liquidation of remnants. " + (row.halts.length ? "Halts: " + row.halts.join(", ") : "");
  const funnel = clear("lab-funnel"), labels = [["Eligible rounds", "eligible_rounds"], ["Confirmed rounds", "confirmed_rounds"], ["Opening orders", "opening_orders"], ["Filled openings", "filled_opening_orders"], ["Sell attempts", "sell_orders"], ["Completed rounds", "completed_rounds"]];
  for (const [label,key] of labels) {
    const line = node("div", "lab-funnel-row");
    line.append(node("span", "", label), node("strong", "", count(row.funnel[key]))); funnel.append(line);
  }
  const conversions = row.conversions || {splits:0,merges:0,records:[]};
  const split = p.signal === "split_sell";
  $("lab-conversion-panel").hidden = !split && !conversions.records.length;
  if (split) {
    const line = node("div", "lab-funnel-row");
    line.append(node("span", "", "Collateral splits · separate from fills"), node("strong", "", count(conversions.splits))); funnel.prepend(line);
    const sales = node("div", "lab-funnel-row");
    sales.append(node("span", "", "Filled maker sales / orders"), node("strong", "", count(row.funnel.filled_maker_sales) + " / " + count(row.funnel.maker_sale_orders))); funnel.append(sales);
    $("lab-parameters").textContent = "Split collateral into equal Up and Down shares; post sell orders on both; cancel and merge matched remnants before exiting any imbalance. Same fixed trade budget. " + p.conversion_delay_ms + "ms simulated conversion delay. Variant " + row.ident;
  }
  $("lab-conversion-note").textContent = "Simulated collateral movements, not venue trades. " + (p.conversion_delay_ms ?? 1000) + "ms modeled delay; gas and rebates excluded. Equal token cost allocation is an accounting convention.";
  labTable("lab-conversions", ["UTC time", "Operation", "Pairs", "Cash movement", "Realized profit"], [...conversions.records].reverse().map(r=>[dateTime(r.received_ms),human(r.kind),labNumber(r.quantity,2),money(r.cash),money(r.pnl)]));
  const reasons = Object.entries(row.reasons).sort((a,b) => b[1]-a[1]).slice(0,10);
  labTable("lab-reasons", ["Reason", "Checks"], reasons.map(([k,v]) => [human(k),count(v)]));
  labTable("lab-outcomes", ["Outcome", "Orders"], Object.entries(row.order_outcomes).map(([k,v]) => [human(k),count(v)]), "No order attempts yet");
  labTable("lab-orders", ["UTC time", "Action", "Outcome", "Price limit", "Principal filled", "Shares filled", "Fee", "Result"], [...row.orders].reverse().map(o => [dateTime(o.at_ms), o.side, o.outcome_side, quotePrice(o.limit), money(o.filled_principal), labNumber(o.filled_shares,4), money(o.fee), human(o.reason)]), "No orders for this variant yet");
}
function renderLab() {
  if (view !== "lab" || !labState) return;
  const data = labState, ready = Array.isArray(data.phases);
  $("lab-content").hidden = !ready;
  if (!ready) { $("lab-status").textContent = "Experiment worker has not published results yet"; return; }
  const stale = Date.now()-data.generated_ms > 30000;
  $("lab-status").textContent = stale ? "Experiment report is stale · saved results retained" : data.status === "stopped" ? "Experiment worker stopped · saved results retained" : "Evaluating shared recorded inputs";
  $("lab-updated").textContent = "Input " + dateTime(data.as_of_ms) + " · " + Math.max(0,data.source_highwater-data.cursor) + " frames behind";
  const phaseSelect = $("lab-phase");
  phaseSelect.replaceChildren(...data.phases.map(p => { const option = node("option", "", p.kind === "exploratory" ? "Exploration · all variants" : "Frozen test · " + dateTime(p.start_ms)); option.value=p.id; return option; }));
  if (!data.phases.some(p => p.id === labPhase)) labPhase = data.phases[0].id;
  phaseSelect.value = labPhase;
  const phase = data.phases.find(p => p.id === labPhase), variants = phase.variants;
  const familyNames = {control:"Controls",momentum:"Momentum thresholds",value:"Value thresholds",buffer:"Model buffers",exit:"Exit rules",feed:"Feed / latency",normalized:"Normalized opening lead",recent:"Recent continuation / reversal",flow:"Executed buying / selling pressure",pairs:"Pair construction",confirmation:"Early signal / later confirmation",split:"Split / sell / merge"};
  const familySelect=$("lab-family"), previousFamily=familySelect.value;
  familySelect.replaceChildren(...["all",...new Set(variants.map(v=>v.family))].map(k=>{const option=node("option","",k==="all"?"All families":familyNames[k]||human(k));option.value=k;return option;}));
  familySelect.value=[...familySelect.options].some(o=>o.value===previousFamily)?previousFamily:"all";
  $("lab-momentum-panel").hidden = !variants.some(v=>v.family==="momentum");
  $("lab-momentum-panel").parentElement.style.gridTemplateColumns = $("lab-momentum-panel").hidden ? "minmax(0, 1fr)" : "";
  renderFlowResearch(data.research);
  $("lab-phase-note").textContent = phase.kind === "exploratory" ? "Automatic selection after " + dateTime(data.explore_end_ms) + ": up to three positive variants with at least 30 usable completed rounds, plus Value control. That gate is not proof of profitability. The first partial round is excluded from trading." : "Frozen before " + dateTime(phase.start_ms) + "; entry evaluation ends " + dateTime(phase.end_ms) + ". Fresh $100 paper wallets. " + (phase.selection.reason || phase.selection.method) + ". This test's settings cannot change.";
  labMetrics("lab-metrics", [
    ["REGISTERED TRIALS", count(data.trial_count), "All variants retained, including failures"],
    ["CAPITAL PER VARIANT", "$100", "Independent wallets · fixed trade budgets"],
    ["FORECAST ROUNDS", count(phase.forecasts.models.central.n), "Central model with official outcomes"],
    ["MATCHED BENCHMARK ROUNDS", count(phase.forecasts.comparisons.central_vs_market.n), "Model and market scored on the same rounds"],
  ]);
  const metric = $("lab-metric").value, family = $("lab-family").value;
  const filtered = variants.filter(v => family === "all" || v.family === family);
  filtered.sort((a,b) => { const av=labValue(a,metric),bv=labValue(b,metric); if(av===null) return bv===null ? a.label.localeCompare(b.label) : 1; if(bv===null)return -1; return (metric==="observed_drawdown" ? av-bv : bv-av)||a.label.localeCompare(b.label); });
  if (!variants.some(v => v.ident === labSelection)) labSelection = (filtered[0] || variants[0])?.ident;
  $("lab-variant-count").textContent = filtered.length + " SHOWN · " + variants.length + " IN THIS PHASE";
  labTable("lab-variants", ["Variant · click to inspect", "Compared metric", "Usable rounds", "Entry fill rate · buys / maker sales", "Fees", "Unresolved", "Uncertain"], filtered.map(v => {
    const button = node("button", "lab-select"+(labSelection===v.ident?" selected":""), v.label); button.addEventListener("click",()=>labChoose(v.ident));
    return [button,labFormat(labValue(v,metric),metric),count(v.clean_completed_rounds),labPercent(v.fill_rate),money(v.fees),count(v.unresolved_rounds),count(v.uncertain_rounds)];
  }), "No variants in this family for the selected phase");
  labHeatmap(variants,metric); labCalibration(phase.forecasts);
  const selected = variants.find(v=>v.ident===labSelection);
  if(selected)labDetail(selected,phase);
  $("lab-limits").textContent = data.limitations.join(" ");
}
async function refreshLab() {
  if(labFetching)return;labFetching=true;
  try {
    const requestedSuite=labSuite;
    const response=await fetch("/api/lab?suite="+encodeURIComponent(requestedSuite),{cache:"no-store",signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw new Error("Experiment report unavailable. Saved portfolio data has not been reset.");
    const payload=await response.json();
    if(requestedSuite===labSuite){labState=payload;$("lab-error").hidden=true;renderLab();}
  } catch(error){$("lab-error").hidden=false;$("lab-error").textContent=error.message;}
  finally{labFetching=false;}
}
function renderFlowResearch(research) {
  $("lab-research").hidden = !research;
  if(!research)return;
  const flow=research.flow||{}, window30=flow.windows?.["30"]||{}, depth=flow.depth||{}, scanner=research.scanner||{}, valid=window30.status==="VALID"&&flow.status==="VALID";
  labMetrics("lab-flow-metrics",[
    ["30s EXECUTED IMBALANCE",valid?labPercent(window30.imbalance):"—", valid?labNumber(window30.buy_quantity,4)+" BTC bought · "+labNumber(window30.sell_quantity,4)+" BTC sold":human(window30.status||flow.status||"FLOW_INPUT_MISSING")],
    ["RESTING BOOK PRESSURE",depth.status==="VALID"?labPercent(depth.imbalance):"—", "Order sizes, not win probability · "+human(depth.status||"DEPTH_MISSING")+" · receipt clock"],
    ["PROTECTED QUOTE CANDIDATES",count(scanner.candidates), "Both prices fit the cost bound; no execution attempted"],
    ["CROSS-DURATION CHECKS",count(scanner.checks),human(scanner.latest?.[0]?.status||"SCANNER_STARTING")],
  ]);
  labTable("lab-scanner",["UTC time","Result","Shares per side","Protected cost","Minimum payout if both fill"],(scanner.latest||[]).slice(0,6).map(r=>[dateTime(r.received_ms),human(r.status),r.shares??"—",money(r.protected_cost),money(r.minimum_payout)]));
}
$("lab-suite").addEventListener("change",()=>{labSuite=$("lab-suite").value;labPhase="explore";labSelection=null;labState=null;$("lab-content").hidden=true;$("lab-status").textContent="Loading selected study…";refreshLab();});
$("lab-phase").addEventListener("change",()=>{labPhase=$("lab-phase").value;labSelection=null;renderLab();});
$("lab-family").addEventListener("change",()=>{labSelection=null;renderLab();});
$("lab-metric").addEventListener("change",renderLab);
window.addEventListener("resize",()=>{if(view==="lab")renderLab();});
