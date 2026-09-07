"use strict";
const $ = (id) => document.getElementById(id);
const COLORS = {
  momentum: "#79a8ff",
  value: "#4cdbb4",
  fast_value: "#bd98ff",
  model_exit: "#f1b569",
  passive_pairs: "#62c8e8",
  inventory_pairs: "#ed93ba",
};
const NAMES = {
  momentum: "Momentum",
  value: "Value",
  fast_value: "Fast value",
  model_exit: "Model exit",
  passive_pairs: "Passive pairs",
  inventory_pairs: "Inventory pairs",
};
const CATEGORIES = {
  eligible: ["Eligible screen", "#4cdbb4"],
  schedule: ["Scheduled wait", "#65768e"],
  warmup: ["History warm-up", "#edb65b"],
  data: ["Data guard", "#ef8288"],
  strategy: ["Strategy filter", "#bd98ff"],
};
const FEEDS = {
  spot: "Chainlink spot",
  twap60: "Chainlink final-average feed",
  exchange_spot: "Binance BTCUSDT",
};
let state,
  liveState,
  view = "paper",
  liveFetching = false,
  selection = "all",
  hours = 0,
  tab = "orders",
  fetching = false;
const number = (value) =>
  value === null || value === undefined || value === "" ? null : Number(value);
const money = (value) =>
  number(value) === null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(Number(value));
const count = (value) =>
  new Intl.NumberFormat("en-US").format(Number(value) || 0);
const quotePrice = (value) =>
  number(value) === null ? "—" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4,
  }).format(Number(value));
const human = (value) =>
  String(value || "Waiting for a decision")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
const clock = (stamp) =>
  stamp ? new Date(stamp).toISOString().slice(11, 19) : "—";
const dateTime = (stamp) =>
  stamp
    ? new Date(stamp).toISOString().replace("T", " ").slice(0, 19) + " UTC"
    : "—";
function node(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function clear(id) {
  const e = typeof id === "string" ? $(id) : id;
  e.replaceChildren();
  return e;
}
function sum(rows, key) {
  return rows.some((row) => number(row[key]) === null)
    ? null
    : rows.reduce((total, row) => total + Number(row[key]), 0);
}
function selectedNames() {
  return Object.keys(state.portfolios).filter(
    (name) => selection === "all" || selection === name,
  );
}
function badge(parent, text, cls = "muted") {
  parent.append(node("span", cls, text));
}
function empty(parent, title, detail) {
  const e = node("div", "empty-state");
  e.append(node("strong", "", title), node("span", "", detail));
  parent.append(e);
}
function swatch(name, color) {
  const e = node("span", "swatch " + (name || ""));
  if (color) e.style.backgroundColor = color;
  return e;
}
function legend(id, entries) {
  const e = clear(id);
  for (const [label, color] of entries) {
    const item = node("span");
    item.append(swatch(null, color), node("span", "", label));
    e.append(item);
  }
}
function bounds() {
  const end = state.collector.last_ms || Date.now();
  return [
    hours
      ? Math.max(state.collector.first_ms || end, end - hours * 3600000)
      : Math.max(state.collector.first_ms || end, end - 86400000),
    end,
  ];
}

function topSummary() {
  const c = state.collector,
    p = Object.values(state.portfolios),
    fills = sum(p, "fills"),
    orders = sum(p, "orders");
  const labels = {
    running: "Recorder active",
    stopping: "Recorder stopping",
    stopped: "Recorder stopped",
    failed: "Recorder failed",
    unresolved: "Stopped with unresolved exposure",
    heartbeat_stale: "Recorder heartbeat overdue",
    receiving_data: "Receiving data · legacy recorder",
    historical: "Historical capture · no recent records",
  };
  $("run-state").textContent = labels[c.status] || human(c.status);
  $("status-dot").className =
    "status-dot " +
    (["running", "receiving_data"].includes(c.status)
      ? "active"
      : ["failed", "unresolved", "heartbeat_stale"].includes(c.status)
        ? "bad"
        : "");
  $("capture-label").textContent = c.first_ms
    ? `${dateTime(c.first_ms).slice(0, 10)} · ${clock(c.first_ms)}–${clock(c.last_ms)} UTC`
    : "No observations yet";
  $("refreshed").textContent =
    "Page refreshed " + clock(state.generated_ms) + " UTC";
  const pnl = sum(p, "realized_net_pnl"),
    held = sum(p, "open_cost_basis"),
    claimable = sum(p, "claimable_value");
  const metrics = [
    [
      "SIMULATED CASH",
      money(sum(p, "cash")),
      "Across " + p.length + " independent portfolios",
    ],
    [
      "REALIZED P/L",
      fills ? money(pnl) : "—",
      fills
        ? "Recorded gains and losses after fees"
        : "Awaiting first bot trade",
    ],
    ["OPEN COST BASIS", money(held), "Cost of inventory still held"],
    [
      "TRADED ROUNDS",
      count(sum(p, "filled_rounds")),
      `${count(fills)} buy/sell fill records · ${count(orders)} order attempts across portfolios`,
    ],
    ["RECORDED FEES", money(sum(p, "fees")), "Maker rebates are omitted"],
    [
      "CLAIMABLE PAYOUT",
      money(claimable),
      "Resolved winnings awaiting paper credit",
    ],
  ];
  const container = clear("metrics");
  for (const [label, value, note] of metrics) {
    const e = node("div", "metric");
    e.append(
      node("div", "metric-label", label),
      node("div", "metric-value", value),
      node("div", "metric-note", note),
    );
    container.append(e);
  }
  const samplingChecks = Object.values(state.decisions)
    .map((d) => d.sampling)
    .filter(Boolean);
  const latestCheck = Math.max(0, ...samplingChecks.map((s) => s.at_ms));
  const historyChecks = samplingChecks
    .filter((s) => s.at_ms === latestCheck)
    .map((s) => s.features);
  const historyReady = historyChecks.some(
    (f) => f.short_sampling_status === "VALID" && f.long_sampling_status === "VALID",
  );
  const gap = !historyReady && historyChecks.some(
    (f) => [f.short_sampling_status, f.long_sampling_status].some(
      (s) => s === "EXCESSIVE_GAP" || s === "INSUFFICIENT_INTERVAL_COVERAGE",
    ),
  );
  $("insight-title").textContent = !c.caught_up
    ? "Loading the full capture"
    : fills === 0
      ? historyReady
        ? "History checks passed · awaiting a trade"
        : gap ? "Entries paused by history coverage" : "Awaiting first bot trade"
      : "Recorded paper execution · simulated fills";
  $("insight-body").textContent = !c.caught_up
    ? `Read ${count(c.events_loaded)} of ${count(c.events_available)} events. Counts are incomplete while the capture loads.`
    : fills === 0
      ? gap
        ? "The latest history checks exceed the allowed gap budget. Brief interruptions are allowed when enough samples and regular intervals remain. Inspect the timestamped history details below."
        : "The policies have not recorded a fill. Scheduled waits, incomplete data and strategy filters are shown separately below. A quiet recorder does not establish whether a strategy is profitable."
      : "Each portfolio is simulated independently. Buying and selling one position creates two fill records. Passive pairs and Inventory pairs share their opening rule; their hedge prices can differ. Inspect holdings and uncertain rounds alongside realized profit.";
  if (c.caught_up && fills === 0)
    $("insight-body").textContent =
      "Recorded market trades are other participants' activity. Our six bots have not executed a paper trade yet. " +
      $("insight-body").textContent;
  const legacyOrders = sum(p, "legacy_matching_orders");
  if (legacyOrders > 0) {
    $("insight-body").textContent =
      $("insight-body").textContent +
      ` ${count(legacyOrders)} historical passive orders used older matching rules with known fill undercounts. Their original results are preserved; resulting losses and missed hedges cannot assess the corrected strategies.`;
  }
  $("runtime-label").textContent =
    `${state.runtime_name} · ${count(c.events_loaded)} journal events · ${Math.max(0, c.restart_times.length - 1)} recorder restarts`;
}
function entrySchedule(name, latest, portfolio) {
  const window = state.thresholds?.entry_windows?.[name];
  if (!window || latest?.reason !== "MISSING_BOOK_SIDE" ||
      number(portfolio.open_cost_basis) > 0 || portfolio.unresolved_orders || portfolio.halts.length ||
      !state.collector.caught_up || state.collector.status !== "running") return null;
  const at = state.collector.last_ms, start = Number(latest.slug?.split("-").at(-1)) * 1000;
  const age = state.generated_ms - latest.at_ms;
  if (!start || !Number.isFinite(age) || !Number.isFinite(at) || age < 0 || age > state.thresholds.price_age_ms || at < start || at >= start + 300000) return null;
  const remaining = (start + 300000 - at) / 1000;
  if (remaining > window[1]) return {
    title: "Waiting for entry window",
    detail: `Opens in ${Math.ceil(remaining - window[1])}s. Current book also has no buyers or sellers on one side.`,
  };
  if (remaining < window[0]) return {
    title: "Entry window closed",
    detail: `Next window ${clock(start + 300000 + (300 - window[1]) * 1000)} UTC. Current round ends in ${Math.ceil(remaining)}s.`,
  };
  return null;
}

function portfolioCards() {
  const root = clear("portfolios");
  for (const [index, [name, p]] of Object.entries(state.portfolios).entries()) {
    const card = node(
      "article",
      "portfolio " + name + (selection === name ? " selected-card" : ""),
    );
    const top = node("div", "card-top"),
      title = node("div", "strategy-name");
    title.append(swatch(name), node("span", "", NAMES[name]));
    top.append(
      title,
      node("span", "strategy-number", String(index + 1).padStart(2, "0")),
    );
    const values = node("div", "portfolio-values"),
      pnl = number(p.realized_net_pnl);
    values.append(
      node(
        "div",
        "portfolio-pnl " + (pnl < 0 ? "negative" : pnl > 0 ? "good" : ""),
        p.fills ? money(pnl) : "—",
      ),
      node(
        "div",
        "portfolio-cash",
        (p.fills ? "Realized P/L · " : "Awaiting first trade · ") +
          money(p.cash) +
          " cash",
      ),
    );
    const mini = node("div", "mini-stats");
    for (const [v, label] of [
      [p.orders, "orders"],
      [p.filled_rounds, "traded rounds"],
      [p.fills, "buy/sell fills"],
    ]) {
      const s = node("span");
      s.append(node("strong", "", v), node("span", "", label));
      mini.append(s);
    }
    const latest = state.decisions[name]?.latest,
      exec = p.last_execution;
    const reason = latest?.reason || exec?.code;
    const schedule = entrySchedule(name, latest, p);
    const gap = ["short", "long"].some(
      (label) => ["EXCESSIVE_GAP", "INSUFFICIENT_INTERVAL_COVERAGE"].includes(latest?.features?.[label + "_sampling_status"]),
    );
    const decision = node(
      "div",
      "decision-status" + (schedule ? " scheduled" : ""),
      schedule ? schedule.title : gap
        ? "History coverage below requirement"
        : human(reason),
    );
    decision.title = schedule?.detail || latest?.explanation || human(reason);
    const time = latest?.at_ms || exec?.received_ms || 0;
    card.append(
      top,
      node("p", "strategy-desc", state.descriptions[name]),
      values,
      mini,
      decision,
      ...(schedule ? [node("p", "caption", schedule.detail)] : []),
      node(
        "p",
        "decision-time",
        time
          ? "Last screen " +
              clock(time) +
              " UTC" +
              (exec ? " · Engine: " + human(exec.code) : "")
          : "No decision recorded",
      ),
    );
    if (p.uncertain_rounds.length || p.unresolved_orders || p.halts.length)
      card.append(
        node(
          "p",
          "caption negative",
          `${p.unresolved_orders} unresolved orders · ${p.uncertain_rounds.length} uncertain rounds${p.halts.length ? " · " + p.halts.join(", ") : ""}`,
        ),
      );
    card.append(
      node(
        "p",
        "decision-time",
        `${p.win_rate_rounds} completed clean rounds · winning rounds ${p.win_rate === null ? "—" : (p.win_rate * 100).toFixed(0) + "%"}`,
      ),
    );
    root.append(card);
  }
}
const NS = "http://www.w3.org/2000/svg";
function svgNode(tag, attrs, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {}))
    e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}
function chartFrame(id, min, max, range, format) {
  const host = clear(id),
    w = Math.max(host.clientWidth, 280),
    h = 210,
    left = 56,
    right = 10,
    top = 16,
    bottom = 27;
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.1;
  min -= pad;
  max += pad;
  const [start, end] = range,
    x = (t) =>
      left + ((t - start) / Math.max(end - start, 1)) * (w - left - right),
    y = (v) => h - bottom - ((v - min) / (max - min)) * (h - top - bottom);
  const svg = svgNode("svg", {
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": host.parentNode.querySelector("h3").textContent,
  });
  for (let i = 0; i < 4; i++) {
    const v = min + ((max - min) * i) / 3,
      yy = y(v);
    svg.append(
      svgNode("line", {
        x1: left,
        y1: yy,
        x2: w - right,
        y2: yy,
        class: "gridline",
      }),
      svgNode(
        "text",
        { x: left - 9, y: yy + 3, "text-anchor": "end" },
        format(v),
      ),
    );
  }
  const ticks = w > 450 ? 4 : 2;
  for (let i = 0; i <= ticks; i++) {
    const t = start + ((end - start) * i) / ticks;
    svg.append(
      svgNode(
        "text",
        { x: x(t), y: h - 6, "text-anchor": "middle" },
        clock(t).slice(0, 5),
      ),
    );
  }
  host.append(svg);
  return { host, svg, w, h, x, y, left, right, start, end };
}
function tooltip(e, rows) {
  const t = clear("tooltip");
  for (const row of rows) t.append(node("div", "", row));
  t.hidden = false;
  t.style.left = Math.min(e.clientX + 12, window.innerWidth - 300) + "px";
  t.style.top =
    Math.max(
      8,
      Math.min(e.clientY + 10, window.innerHeight - t.offsetHeight - 15),
    ) + "px";
}
function lineChart(id, series, format, emptyText, step = false) {
  const range = bounds();
  const relevant = series.flatMap((s) => {
    const values = s.points
      .filter((p) => p[0] >= range[0] && p[0] <= range[1])
      .map((p) => p[1]);
    const prior = s.points.filter((p) => p[0] < range[0]).at(-1);
    if (step && prior) values.push(prior[1]);
    return values;
  });
  const f = chartFrame(
    id,
    relevant.length ? Math.min(...relevant) : 0,
    relevant.length ? Math.max(...relevant) : 0,
    range,
    format,
  );
  for (const s of series) {
    let points = s.points.filter((p) => p[0] >= range[0] && p[0] <= range[1]);
    const earlier = s.points.filter((p) => p[0] < range[0]).at(-1);
    if (step && earlier) points = [[range[0], earlier[1]], ...points];
    if (step && points.length)
      points = [...points, [range[1], points.at(-1)[1]]];
    if (!points.length) continue;
    let d = `M ${f.x(points[0][0])} ${f.y(points[0][1])}`;
    for (const [t, v] of points.slice(1))
      d += step ? ` H ${f.x(t)} V ${f.y(v)}` : ` L ${f.x(t)} ${f.y(v)}`;
    f.svg.append(svgNode("path", { d, stroke: s.color, class: "plotline" }));
    if (points.length === 1)
      f.svg.append(
        svgNode("circle", {
          cx: f.x(points[0][0]),
          cy: f.y(points[0][1]),
          r: 3,
          fill: s.color,
        }),
      );
  }
  f.svg.addEventListener("mousemove", (e) => {
    const rect = f.svg.getBoundingClientRect(),
      t =
        f.start +
        Math.max(
          0,
          Math.min(
            1,
            (e.clientX - rect.left - f.left) / (f.w - f.left - f.right),
          ),
        ) *
          (f.end - f.start),
      rows = [dateTime(t)];
    for (const s of series) {
      const p = step
        ? s.points.filter((p) => p[0] <= t).at(-1)
        : s.points.reduce(
            (a, p) => (!a || Math.abs(p[0] - t) < Math.abs(a[0] - t) ? p : a),
            null,
          );
      if (p) rows.push(`${s.name}: ${format(p[1])}`);
    }
    tooltip(e, rows);
  });
  f.svg.addEventListener("mouseleave", () => ($("tooltip").hidden = true));
  if (emptyText) f.host.append(node("div", "chart-empty", emptyText));
}
function charts() {
  const names = selectedNames(),
    first = state.collector.first_ms || Date.now();
  const curves = names.map((name) => {
    const p = state.portfolios[name];
    return {
      name: NAMES[name],
      color: COLORS[name],
      points: p.fills
        ? [
            ...(p.curve_truncated ? [] : [[first, 0]]),
            ...p.pnl_curve.map((x) => [x.at_ms, Number(x.pnl)]),
          ]
        : [],
    };
  });
  lineChart(
    "pnl-chart",
    curves,
    (v) => money(v),
    names.every((name) => state.portfolios[name].fills === 0)
      ? "No fills · no performance sample"
      : null,
    true,
  );
  legend(
    "pnl-legend",
    names.map((name) => [NAMES[name], COLORS[name]]),
  );
  const untimed = names.reduce(
    (total, name) => total + state.portfolios[name].untimed_accounting,
    0,
  );
  const truncated = names.some(
    (name) => state.portfolios[name].curve_truncated,
  );
  $("pnl-quality").hidden = !untimed && !truncated;
  $("pnl-quality").textContent = [
    untimed
      ? `${count(untimed)} accounting records have no timestamp. Their gains or losses are included in totals but omitted from this curve.`
      : "",
    truncated
      ? "Only the latest 5,000 accounting points per portfolio are plotted."
      : "",
  ]
    .filter(Boolean)
    .join(" ");
  const priceSeries = Object.keys(FEEDS).map((key, index) => ({
    name: FEEDS[key],
    color: ["#79a8ff", "#4cdbb4", "#f1b569"][index],
    points: state.prices
      .filter((p) => number(p[key]) !== null)
      .map((p) => [p.at_ms, Number(p[key])]),
  }));
  lineChart(
    "price-chart",
    priceSeries,
    (v) =>
      "$" +
      new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v),
    priceSeries.every((s) => !s.points.length) ? "No price observations" : null,
  );
  legend(
    "price-legend",
    priceSeries.map((s) => [s.name, s.color]),
  );
  const range = bounds(),
    buckets = state.timeline
      .filter((b) => b.at_ms + 60000 >= range[0] && b.at_ms <= range[1])
      .map((b) => {
        const totals = {};
        for (const name of names)
          for (const [key, n] of Object.entries(b.strategies[name] || {}))
            totals[key] = (totals[key] || 0) + n;
        return { at_ms: Math.max(b.at_ms, range[0]), totals };
      });
  const maximum = Math.max(
      1,
      ...buckets.map((b) => Object.values(b.totals).reduce((a, b) => a + b, 0)),
    ),
    f = chartFrame("decision-chart", 0, maximum, range, (v) =>
      count(Math.max(0, v)),
    );
  const width = Math.max(
    1,
    Math.min(
      30,
      (f.w - f.left - f.right) / Math.max((range[1] - range[0]) / 60000, 1) - 2,
    ),
  );
  for (const b of buckets) {
    let accumulated = 0;
    for (const [key, [label, color]] of Object.entries(CATEGORIES)) {
      const n = b.totals[key] || 0;
      if (!n) continue;
      const top = f.y(accumulated + n),
        bottom = f.y(accumulated);
      const rect = svgNode("rect", {
        x: f.x(b.at_ms),
        y: top,
        width,
        height: Math.max(bottom - top, 0),
        fill: color,
        rx: 1,
      });
      rect.addEventListener("mousemove", (e) =>
        tooltip(e, [
          clock(b.at_ms) + " UTC",
          ...Object.entries(b.totals).map(
            ([k, v]) => `${CATEGORIES[k]?.[0] || k}: ${count(v)} checks`,
          ),
        ]),
      );
      rect.addEventListener("mouseleave", () => ($("tooltip").hidden = true));
      f.svg.append(rect);
      accumulated += n;
    }
  }
  for (const stamp of state.collector.restart_times.slice(1)) {
    if (stamp < range[0] || stamp > range[1]) continue;
    const mark = svgNode("line", {
      x1: f.x(stamp),
      x2: f.x(stamp),
      y1: 8,
      y2: 185,
      stroke: "#d8e2f2",
      "stroke-dasharray": "2 3",
      opacity: 0.7,
    });
    mark.append(
      svgNode("title", {}, "Recorder restart " + clock(stamp) + " UTC"),
    );
    f.svg.append(mark);
  }
  legend("decision-legend", [
    ...Object.values(CATEGORIES),
    ["Dashed line: recorder restart", "#d8e2f2"],
  ]);
}
function feedHealth() {
  const expandedBooks = new Set([...$("feeds").querySelectorAll("details[open]")].map(d => d.dataset.token));
  const root = clear("feeds"),
    end = state.collector.last_ms || Date.now();
  for (const [key, label] of Object.entries(FEEDS)) {
    const feed = state.feeds[key],
      age =
        feed && number(feed.source_ms) !== null
          ? (end - feed.source_ms) / 1000
          : null;
    const row = node("div", "feed-row"),
      left = node("div");
    left.append(
      node("div", "feed-name", label),
      node(
        "div",
        "feed-detail",
        feed
          ? `Source ${clock(feed.source_ms)} · ${count(state.observation_counts[key])} observations`
          : "No observation recorded",
      ),
    );
    const right = node(
      "div",
      "feed-age " +
        (age === null || age < 0 ? "negative" : age > 5 ? "warning" : "good"),
    );
    right.append(
      node(
        "div",
        "",
        age === null
          ? "Unavailable"
          : age < 0
            ? "Future source time"
            : age.toFixed(1) + "s old",
      ),
      node("div", "feed-detail", feed ? money(feed.price) : ""),
    );
    row.append(left, right);
    root.append(row);
  }
  const books = [...state.books].sort((a, b) =>
    (a.side === "UP" ? 0 : a.side === "DOWN" ? 1 : 2) -
    (b.side === "UP" ? 0 : b.side === "DOWN" ? 1 : 2) || a.token_id.localeCompare(b.token_id));
  const roundStart = Number(books[0]?.slug?.split("-").at(-1)) * 1000;
  const remaining = roundStart ? (roundStart + 300000 - end) / 1000 : null;
  const windows = Object.values(state.thresholds?.entry_windows || {});
  const closed = remaining !== null && remaining >= 0 && windows.length && remaining < Math.min(...windows.map(w => w[0]));
  if (closed) root.append(node("p", "caption", `New entries closed · ${Math.ceil(remaining)}s left in this round. Existing positions are still managed.`));
  for (const [i, book] of books.entries()) {
    const row = node("div", "feed-row"),
      emptyBook = !book.bid_count || !book.ask_count;
    const left = node("div"), right = node("div", "feed-value");
    left.append(node("div", "feed-name", book.side ? `${human(book.side)} order book` : `Outcome book ${i + 1}`));
    const start = Number(book.slug?.split("-").at(-1)) * 1000;
    const age = (end - book.source_ms) / 1000;
    const freshness = age >= 0 ? `${age.toFixed(1)}s old` : `source ${(-age).toFixed(1)}s ahead`;
    left.append(node("div", "feed-detail", `${start ? `Round ${clock(start)} UTC · ` : ""}Source ${clock(book.source_ms)} UTC · ${freshness}`));
    const side = book.side ? human(book.side) : "shares";
    right.append(node("div", emptyBook && !closed ? "warning" : "muted", `Buy ${side}: ${number(book.best_ask) === null ? "unavailable" : quotePrice(book.best_ask)} · Sell ${side}: ${number(book.best_bid) === null ? "unavailable" : quotePrice(book.best_bid)}`));
    if (emptyBook) right.append(node("div", "feed-detail", [
      !book.bid_count ? `No buy orders for ${side}.` : "",
      !book.ask_count ? `No ${side} offered for sale.` : "",
    ].filter(Boolean).join(" ")));
    const depth = node("details", "feed-detail");
    depth.dataset.token = book.token_id;
    depth.open = expandedBooks.has(book.token_id);
    depth.append(node("summary", "", "Depth details"), node("div", "", `Best bid ${quotePrice(book.best_bid)} · Best ask ${quotePrice(book.best_ask)} · ${book.bid_count || 0} buy-price levels · ${book.ask_count || 0} sell-price levels`));
    right.append(depth);
    row.append(left, right);
    root.append(row);
  }
  const h = clear("history"),
    candidate = selection === "all" ? "value" : selection,
    sampling = state.decisions[candidate]?.sampling,
    features = sampling?.features || {};
  h.append(
    node(
      "strong",
      "",
      "Latest " +
        NAMES[candidate] +
        " sampling check" +
        (sampling ? " · " + clock(sampling.at_ms) + " UTC" : ""),
    ),
  );
  if (features.long_sampling_status) {
    for (const label of ["short", "long"]) {
      const row = node(
        "div",
        "",
        `${human(label)}: ${features[label + "_sample_count"]}/${features[label + "_requested_sample_count"]} samples · largest gap ${(features[label + "_max_sample_gap_ms"] || 0) / 1000}s · ${human(features[label + "_sampling_status"])}`,
      );
      h.append(row);
      if (features[label + "_regular_time_coverage"] !== undefined) {
        h.append(node("div", "",
          `${human(label)}: ${(Number(features[label + "_regular_time_coverage"]) * 100).toFixed(1)}% of time in regular intervals · ${features[label + "_irregular_seconds"]}s in long gaps`,
        ));
      }
    }
  } else
    h.append(
      node(
        "div",
        "",
        "No sampling check was reached in this capture; earlier guards prevented it.",
      ),
    );
  if (state.thresholds)
    h.append(
      node(
        "div",
        "",
        `Recorded configuration matches: ${state.thresholds.history_seconds / 60}m history · intervals above ${state.thresholds.max_gap_ms / 1000}s consume the gap budget · ${Number(state.thresholds.coverage) * 100}% minimum sample and regular-time coverage.`,
      ),
    );
  else
    h.append(
      node(
        "div",
        "warning",
        "Configuration differs from this capture; current threshold settings are hidden.",
      ),
    );
  h.append(
    node(
      "div",
      "",
      "The ages above are measured at the capture's last event. They do not mean these historical feeds are live now.",
    ),
  );
}
function breakdown() {
  const counts = {},
    examples = {};
  for (const name of selectedNames()) {
    for (const [reason, n] of Object.entries(state.decisions[name].counts))
      counts[reason] = (counts[reason] || 0) + n;
    const last = state.decisions[name].latest;
    if (last) examples[last.reason] = last.explanation;
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  $("check-count").textContent = count(total) + " TOTAL CHECKS";
  const root = clear("reasons");
  const explanations = {
    ENTRY_WINDOW: "Scheduled wait outside the entry interval.",
    PAIR_WINDOW: "Scheduled wait outside the pair entry/completion interval.",
    MISSING_REFERENCE:
      "Opening settlement reference not verified for this round.",
    MISSING_BOOK_SIDE: "A required Up/Down bid or ask was empty.",
    INSUFFICIENT_HISTORY:
      "Inspect warm-up versus gap/coverage failures below; these have different causes.",
    FAST_STALE: "Exchange information arrived too late for the fast strategy.",
    FAST_UNALIGNED:
      "An exchange tick could not be aligned closely enough to Chainlink.",
  };
  for (const [reason, n] of Object.entries(counts).sort(
    (a, b) => b[1] - a[1],
  )) {
    const row = node("div", "reason-row");
    row.append(
      node("div", "reason-name", human(reason)),
      node("div", "reason-count", count(n)),
      node(
        "div",
        "reason-help",
        explanations[reason] ||
          examples[reason] ||
          "Recorded strategy screen result.",
      ),
    );
    const bar = svgNode("svg", {
      viewBox: "0 0 100 4",
      preserveAspectRatio: "none",
      class: "reason-bar",
    });
    bar.append(
      svgNode("rect", { x: 0, y: 0, width: 100, height: 4, fill: "#243347" }),
      svgNode("rect", {
        x: 0,
        y: 0,
        width: (n / Math.max(total, 1)) * 100,
        height: 4,
        fill: reason.includes("WINDOW")
          ? "#65768e"
          : reason === "ENTRY"
            ? "#4cdbb4"
            : "#edb65b",
      }),
    );
    row.append(bar);
    root.append(row);
  }
  if (!total)
    empty(
      root,
      "No strategy screens recorded",
      "Feed health may explain why the collector could not build a snapshot.",
    );
  const historyCounts = {};
  for (const name of selectedNames())
    for (const [reason, n] of Object.entries(
      state.decisions[name].history_reasons,
    ))
      historyCounts[reason] = (historyCounts[reason] || 0) + n;
  if (Object.keys(historyCounts).length) {
    const box = node("div", "history");
    box.append(node("strong", "", "History failures inside those checks"));
    for (const [reason, n] of Object.entries(historyCounts))
      box.append(node("div", "", human(reason) + ": " + count(n)));
    box.append(
      node("div", "", "A check can fail more than one sampling requirement."),
    );
    root.append(box);
  }
  const incidents = clear("incidents");
  for (const row of state.incidents
    .filter(
      (r) =>
        !(
          r.kind === "snapshot_unavailable" &&
          state.incidents.some(
            (other) =>
              other.kind === "metadata_rejected" && other.code === r.code,
          )
        ),
    )
    .slice(0, 10)) {
    const e = node("div", "incident-row"),
      top = node("div", "incident-top");
    top.append(
      node(
        "span",
        "",
        human(row.code) + (row.stream ? " · " + row.stream : ""),
      ),
      node("strong", "", count(row.count)),
    );
    let text = row.explanation;
    if (row.field) {
      text += ` ${human(row.field)}: expected ${row.expected}, received ${row.actual}.`;
      const skipped = state.incidents.find(
        (r) => r.kind === "snapshot_unavailable" && r.code === row.code,
      );
      if (skipped)
        text += ` Snapshot skips with this code: ${count(skipped.count)}.`;
    }
    e.append(
      top,
      node("p", "incident-info", text),
      node(
        "p",
        "feed-detail",
        `${clock(row.first_ms)}–${clock(row.last_ms)} UTC`,
      ),
    );
    incidents.append(e);
  }
  if (!state.incidents.length)
    empty(
      incidents,
      "No incident records",
      "No recorded incident does not by itself establish feed quality.",
    );
}
function activity() {
  const rows = [];
  for (const name of selectedNames())
    for (const row of state.portfolios[name][
      tab === "orders"
        ? "recent_orders"
        : tab === "fills"
          ? "recent_fills"
          : "positions"
    ])
      rows.push({ ...row, strategy: name });
  rows.sort(
    (a, b) => (b.at_ms || b.created_ms || 0) - (a.at_ms || a.created_ms || 0),
  );
  const root = clear("activity");
  if (!rows.length) {
    empty(
      root,
      tab === "orders"
        ? "No orders were submitted"
        : tab === "fills"
          ? "No simulated fills"
          : "No open holdings",
      tab === "orders"
        ? "Inspect the decision and data-quality panels to see where entries stopped."
        : tab === "fills"
          ? "A quote touch is not a simulated fill. Later trade volume must reach the resting order."
          : "Cash remains available in each independent portfolio.",
    );
    return;
  }
  const headers =
    tab === "orders"
      ? [
          "Time (UTC)",
          "Strategy",
          "Round start",
          "Action",
          "Outcome",
          "Limit",
          "Shares",
          "Filled",
          "Execution outcome",
        ]
      : tab === "fills"
        ? [
            "Time (UTC)",
            "Strategy",
            "Round start",
            "Action",
            "Outcome",
            "Shares",
            "Principal",
            "Fee",
          ]
        : [
            "Strategy",
            "Round start",
            "Outcome",
            "Shares",
            "Cost basis",
            "Claimable",
            "State",
            "Exit status",
          ];
  const table = node("table"),
    head = node("thead"),
    tr = node("tr");
  for (const label of headers) tr.append(node("th", "", label));
  head.append(tr);
  table.append(head);
  const body = node("tbody");
  for (const r of rows.slice(0, 200)) {
    const round = clock(Number(r.slug.split("-").at(-1)) * 1000);
    const values =
      tab === "orders"
        ? [
            clock(r.created_ms),
            NAMES[r.strategy],
            round,
            r.side,
            r.outcome,
            money(r.price_limit),
            r.quantity,
            r.confirmed_quantity,
            human(r.execution_status || r.state) + " / " + human(r.execution_reason || r.reason),
          ]
        : tab === "fills"
          ? [
              clock(r.at_ms),
              NAMES[r.strategy],
              round,
              r.side,
              r.outcome,
              r.quantity,
              money(r.principal),
              money(r.fee),
            ]
          : [
              NAMES[r.strategy],
              round,
              r.side,
              r.quantity,
              money(r.cost_basis),
              money(r.claimable_value),
              human(r.status),
              r.exit_problem || r.exit_reason || "—",
            ];
    const row = node("tr");
    for (const v of values) row.append(node("td", "", v ?? "—"));
    body.append(row);
  }
  table.append(body);
  root.append(table);
}
function render() {
  if (!state || view !== "paper") return;
  topSummary();
  portfolioCards();
  charts();
  feedHealth();
  breakdown();
  activity();
}
async function refresh() {
  if (view === "live") return refreshLive();
  if (fetching) return;
  fetching = true;
  try {
    const response = await fetch("/api/state", {
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok)
      throw new Error(
        "The dashboard could not read the selected paper journals.",
      );
    const next = await response.json();
    state = next;
    const selected = $("strategy");
    if (selected.options.length === 1)
      for (const name of Object.keys(state.portfolios)) {
        const option = node("option", "", NAMES[name]);
        option.value = name;
        selected.append(option);
      }
    $("error").hidden = true;
    render();
  } catch (error) {
    $("error").textContent =
      (error.message || "Dashboard refresh failed") +
      " Previously displayed values are retained and may be stale. No trading action was taken.";
    $("error").hidden = false;
    $("run-state").textContent = "Dashboard refresh failed";
    $("status-dot").className = "status-dot bad";
  } finally {
    fetching = false;
  }
}
$("strategy").addEventListener("change", (e) => {
  selection = e.target.value;
  render();
});
for (const button of document.querySelectorAll("[data-hours]"))
  button.addEventListener("click", () => {
    hours = Number(button.dataset.hours);
    for (const b of document.querySelectorAll("[data-hours]"))
      b.classList.toggle("selected", b === button);
    if (state) charts();
  });
for (const button of document.querySelectorAll("[data-tab]"))
  button.addEventListener("click", () => {
    tab = button.dataset.tab;
    for (const b of document.querySelectorAll("[data-tab]"))
      b.classList.toggle("selected", b === button);
    if (state) activity();
  });
$("export").addEventListener("click", () => {
  const snapshot = view === "live" ? liveState : state;
  if (!snapshot) return;
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    link = node("a");
  link.href = url;
  link.download = `btc5m-${view}-monitoring.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => view === "paper" && state && charts(), 150);
});
for (const button of document.querySelectorAll("[data-view]"))
  button.addEventListener("click", () => {
    view = button.dataset.view;
    $("paper-view").hidden = view !== "paper";
    $("live-view").hidden = view !== "live";
    $("view-title").textContent =
      view === "paper" ? "Paper observatory" : "Real account";
    $("view-badge").textContent =
      view === "paper" ? "SIMULATED · READ ONLY" : "REAL FUNDS · READ ONLY";
    $("tooltip").hidden = true;
    for (const b of document.querySelectorAll("[data-view]")) {
      b.classList.toggle("selected", b === button);
      b.setAttribute("aria-pressed", String(b === button));
    }
    if (view === "paper") render();
    else renderLive();
    refresh();
  });

function liveTable(id, headers, rows, message) {
  const root = clear(id);
  if (!rows.length)
    return empty(root, message, "Only available account records are shown.");
  const table = node("table"),
    head = node("thead"),
    header = node("tr"),
    body = node("tbody");
  for (const title of headers) header.append(node("th", "", title));
  head.append(header);
  for (const values of rows) {
    const row = node("tr");
    for (const value of values) row.append(node("td", "", value ?? "—"));
    body.append(row);
  }
  table.append(head, body);
  root.append(table);
}
function renderLive() {
  if (view !== "live") return;
  const data = liveState || { status: "loading" },
    a = data.account;
  $("live-status").textContent =
    {
      loading: "Connecting to account…",
      ready: "Account connected",
      unavailable: "Account read unavailable",
      not_configured: "Real account not configured",
    }[data.status] || human(data.status);
  $("live-dot").className =
    "status-dot " +
    (data.status === "ready"
      ? "active"
      : data.status === "unavailable"
        ? "bad"
        : "");
  $("live-refreshed").textContent = data.generated_ms
    ? `Account read ${dateTime(data.generated_ms)}${data.refreshing ? " · refreshing…" : ""}`
    : "Account polling every 30s";
  $("live-wallet").textContent = a
    ? `${a.wallet} · ${human(a.wallet_type)}`
    : "";
  $("live-insight-title").textContent = a
    ? "Actual account activity · read only"
    : data.status === "not_configured"
      ? "Connect your account to this view"
      : data.status === "unavailable"
        ? "Could not read the account"
        : "Reading your Polymarket account";
  $("live-insight-body").textContent = a
    ? "This view includes your whole wallet, including trades made elsewhere. Switching to Real does not enable this bot or place an order."
    : data.status === "not_configured"
      ? "Start the dashboard with --account --env-file /absolute/path/to/.env to use your existing account credentials. Keep keys in that file; this page never asks for them."
      : data.status === "unavailable"
        ? "Authentication or a network read failed. Values are unavailable, not zero. The next refresh will retry; the paper run continues independently."
        : "Retrieving cash, holdings, orders and recent trades using existing credentials.";
  const sections = ["cash", "positions", "orders", "trades"];
  const unavailable = a ? sections.filter((k) => a[k].status !== "ok") : [];
  if (unavailable.length) {
    $("live-insight-body").textContent +=
      ` Unavailable: ${unavailable.join(", ")}. These values are shown as unknown.`;
    $("live-status").textContent = "Account partially available";
    $("live-dot").className = "status-dot bad";
  }
  if (a && Date.now() - data.generated_ms > 60000) {
    $("live-status").textContent = "Account values are stale · refreshing";
    $("live-dot").className = "status-dot bad";
    $("live-insight-body").textContent +=
      " Displayed account values are over a minute old. Wait for a successful refresh.";
  }
  const cash = a?.cash.value,
    positions = a?.positions.value,
    orders = a?.orders.value,
    trades = a?.trades.value,
    bot = a?.bot;
  const metrics = [
    ["TRADING CASH", money(cash), "pUSD balance on Polygon"],
    ["HOLDINGS VALUE", money(positions?.total_value), "Public index estimate"],
    [
      "CASH + HOLDINGS",
      number(cash) !== null && number(positions?.total_value) !== null
        ? money(Number(cash) + Number(positions.total_value))
        : "—",
      "Estimated value, not account profit",
    ],
    [
      "OPEN ORDERS",
      orders ? count(orders.length) : "—",
      "Across the actual account",
    ],
    [
      "BOT REALIZED P/L",
      bot?.fills > 0 ? money(bot.realized_pnl) : "—",
      bot?.status === "unavailable"
        ? "Bot journal unavailable"
        : bot?.fills > 0
          ? "Local recorded bot accounting"
          : "No funded bot fills recorded",
    ],
    [
      "RECENT TRADE LEGS",
      trades ? count(trades.rows.length) : "—",
      "Latest page within 7 days · all statuses",
    ],
  ];
  const root = clear("live-metrics");
  for (const [label, value, note] of metrics) {
    const metric = node("div", "metric");
    metric.append(
      node("div", "metric-label", label),
      node("div", "metric-value", value),
      node("div", "metric-note", note),
    );
    root.append(metric);
  }
  const chart = clear("live-holdings-chart");
  const holdings = (positions?.rows || [])
    .filter((p) => number(p.current_value) !== null)
    .sort((a, b) => Number(b.current_value) - Number(a.current_value));
  if (!holdings.length)
    empty(
      chart,
      positions ? "No valued holdings" : "Holdings unavailable",
      "No account profit history is inferred from current balances.",
    );
  for (const p of holdings.slice(0, 8)) {
    const row = node("div", "holding-bar-row"),
      top = node("div", "incident-top"),
      track = node("div", "holding-track"),
      bar = node("div", "holding-bar");
    top.append(
      node("span", "", `${p.title || p.asset_id} · ${p.outcome || ""}`),
      node("strong", "", money(p.current_value)),
    );
    bar.style.width = `${Number(holdings[0].current_value) > 0 ? (Number(p.current_value) / Number(holdings[0].current_value)) * 100 : 0}%`;
    track.append(bar);
    row.append(top, track);
    chart.append(row);
  }
  const botRoot = clear("live-bot");
  if (bot?.status === "recorded") {
    botRoot.append(
      node(
        "p",
        "",
        `${count(bot.orders)} recorded orders · ${count(bot.fills)} receipt-confirmed fills`,
      ),
    );
    botRoot.append(
      node(
        "p",
        "",
        `${count(bot.unresolved_orders)} unresolved orders · ${money(bot.fees)} recorded fees`,
      ),
    );
    if (bot.halts.length)
      botRoot.append(node("p", "negative", bot.halts.map(human).join(", ")));
  } else
    empty(
      botRoot,
      bot?.status === "not_started"
        ? "No funded bot journal yet"
        : "Bot journal unavailable",
      "Paper trades are never counted as real trades.",
    );
  const ownership = (value) =>
    value === null ? "Unknown" : value ? "This bot" : "Outside this journal";
  liveTable(
    "live-positions",
    [
      "Market",
      "Outcome",
      "Shares",
      "Average entry",
      "Current price",
      "Value",
      "Claimable",
    ],
    (positions?.rows || []).map((p) => [
      p.title || p.asset_id,
      p.outcome,
      p.quantity,
      money(p.average_price),
      money(p.current_price),
      money(p.current_value),
      p.redeemable === null ? "Unknown" : p.redeemable ? "Yes" : "No",
    ]),
    positions ? "No account holdings" : "Holdings read unavailable",
  );
  $("live-positions-note").textContent = positions
    ? `${count(positions.total_count)} positions${positions.truncated ? " · first 500 shown" : ""}`
    : "PUBLIC INDEX UNAVAILABLE";
  liveTable(
    "live-orders",
    ["Outcome / token", "Side", "Price", "Size", "Matched", "Status", "Source"],
    (orders || [])
      .slice(0, 500)
      .map((o) => [
        `${o.outcome} · ${o.asset_id}`,
        o.side,
        money(o.price),
        o.quantity,
        o.matched,
        o.status,
        ownership(o.bot_owned),
      ]),
    orders ? "No open account orders" : "Open orders read unavailable",
  );
  $("live-trades-note").textContent =
    `PAST 7 DAYS · LATEST PAGE${trades?.truncated ? " · MORE RECORDS EXIST" : ""}`;
  liveTable(
    "live-trades",
    ["Time (UTC)", "Outcome", "Side", "Shares", "Price", "Status", "Source"],
    (trades?.rows || []).map((t) => [
      dateTime(t.at_ms),
      t.outcome,
      t.side,
      t.quantity,
      money(t.price),
      human(t.status),
      ownership(t.bot_owned),
    ]),
    trades
      ? "No trades in the returned recent page"
      : "Trade history read unavailable",
  );
}
async function refreshLive() {
  if (liveFetching) return;
  liveFetching = true;
  try {
    const response = await fetch("/api/live", {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error("Account view unavailable");
    liveState = await response.json();
    renderLive();
  } catch (_) {
    liveState = { environment: "live", status: "unavailable", account: null };
    renderLive();
  } finally {
    liveFetching = false;
  }
}
refresh();
setInterval(refresh, 5000);
