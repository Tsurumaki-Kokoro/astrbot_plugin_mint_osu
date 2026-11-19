"use strict";

const bridge = window.AstrBotPluginView ?? window.AstrBotPluginPage;
const get = (id) => document.getElementById(id);
const mainFilters = get("filters");
const integer = new Intl.NumberFormat("zh-CN");
const decimal = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const timestamp = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
const shanghaiDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
});
const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const outcomes = {
  same: "相符", different: "不符", unsure: "无法确认", timeout: "超时",
  error: "请求失败", invalid: "响应无效", cancelled: "已取消",
};
const knownPlatforms = new Set();
const knownGroups = new Map();
const knownModels = new Set();
let page = 1;
let requestNumber = 0;
const showSummary = get("overview") !== null;
let timeFilter;
let heatmapReference;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function count(value) {
  return value == null ? "—" : integer.format(value);
}

function money(value, currency) {
  if (value == null || !currency || !Number.isFinite(Number(value))) return "—";
  return `${currency} ${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 9,
  })}`;
}

function formatTime(value) {
  if (value == null) return "—";
  const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? "—" : timestamp.format(date);
}

function empty(target, text = "所选范围内暂无数据。") {
  target.replaceChildren(element("p", text, "empty"));
}

function table(target, columns, rows, emptyText) {
  if (!rows.length) {
    empty(target, emptyText);
    return;
  }
  const view = element("table");
  const headings = view.createTHead().insertRow();
  for (const { name, numeric } of columns) {
    const heading = element("th", name, numeric ? "numeric" : "");
    heading.scope = "col";
    headings.append(heading);
  }
  const body = view.createTBody();
  for (const row of rows) {
    const line = body.insertRow();
    row.forEach((value, index) => {
      const cell = line.insertCell();
      cell.className = columns[index].numeric ? "numeric" : columns[index].className ?? "";
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
    });
  }
  target.replaceChildren(view);
}

function formParams(form) {
  return Object.fromEntries([...new FormData(form)].flatMap(([key, value]) => {
    const text = String(value).trim();
    return text ? [[key, text]] : [];
  }));
}

function fillOptions(list, values) {
  get(list).replaceChildren(...[...values].sort().map((value) => {
    const option = element("option");
    option.value = value;
    return option;
  }));
}

function rememberOptions(data) {
  for (const { platform, group_id: group } of data.groups ?? []) {
    if (platform) knownPlatforms.add(platform);
    if (!group) continue;
    if (!knownGroups.has(platform)) knownGroups.set(platform, new Set());
    knownGroups.get(platform).add(group);
  }
  for (const platform of data.platforms ?? []) {
    if (typeof platform === "string") knownPlatforms.add(platform);
  }
  for (const { model } of data.models ?? []) {
    if (model) knownModels.add(model);
  }
  fillOptions("platforms", knownPlatforms);
  if (!showSummary) fillOptions("model-options", knownModels);
  const platform = mainFilters.elements.platform.value.trim();
  fillOptions("groups", platform ? knownGroups.get(platform) ?? [] :
    new Set([...knownGroups.values()].flatMap((groups) => [...groups])));
}

function renderMetrics({
  commands, active_groups: groups, private_count: privateCount, models, local_wins: localWins,
}) {
  const total = commands.reduce((n, item) => n + item.count, 0);
  const errors = commands.reduce((n, item) => n + (item.errors ?? 0), 0);
  const judged = models.reduce((n, item) => n + item.count, 0);
  const tokens = models.reduce((n, item) => n + tokenTotal(item), 0);
  const usageCount = models.reduce((n, item) => n + (item.usage_count ?? 0), 0);
  const priced = models.reduce((n, item) => n + (item.priced ?? 0), 0);
  const settled = models.reduce((n, item) => n + (item.settled ?? 0), 0);
  const totals = new Map();
  for (const { amount, currency } of models) {
    if (amount != null && currency) totals.set(currency, (totals.get(currency) ?? 0) + Number(amount));
  }
  const charges = [...totals].map(([currency, amount]) => money(amount, currency)).join(" / ");
  const metrics = [
    ["指令调用", count(total)], ["私聊调用", count(privateCount)], ["活跃群数", count(groups)],
    ["技术失败率", total ? `${decimal.format(errors * 100 / total)}%` : "—"],
    ["模型判定", count(judged)], ["已知 Token", usageCount ? count(tokens) : "—"],
    ["已估算费用", charges || "—", `计价覆盖 ${count(priced)} / ${count(judged)}`],
    ["本地判对结算", count(localWins)], ["模型判对结算", count(settled)],
  ];
  get("metrics").replaceChildren(...metrics.map(([label, value, detail]) => {
    const group = element("div");
    group.append(element("dt", label), element("dd", value));
    if (detail) group.append(element("p", detail, "minor"));
    return group;
  }));
}

function showHeatmap(hours) {
  const clear = get("clear-time");
  clear.hidden = !timeFilter;
  if (timeFilter) clear.textContent = `清除时段筛选 · ${weekdays[timeFilter.weekday]} ${String(timeFilter.hour).padStart(2, "0")}:00`;
  const heatmap = element("table", null, "heatmap");
  const head = heatmap.createTHead().insertRow();
  const first = element("th", "时段");
  first.scope = "col";
  head.append(first);
  for (let hour = 0; hour < 24; hour += 1) {
    const hourHeading = element("th", String(hour).padStart(2, "0"));
    hourHeading.scope = "col";
    head.append(hourHeading);
  }
  const counts = new Map(hours.map(({ weekday, hour, count: amount }) => [`${weekday}:${hour}`, amount]));
  const scale = Math.max(1, ...counts.values());
  const body = heatmap.createTBody();
  for (let weekday = 0; weekday < weekdays.length; weekday += 1) {
    const row = body.insertRow();
    const dayHeading = element("th", weekdays[weekday]);
    dayHeading.scope = "row";
    row.append(dayHeading);
    for (let hour = 0; hour < 24; hour += 1) {
      const amount = counts.get(`${weekday}:${hour}`) ?? 0;
      const level = amount ? Math.ceil(4 * Math.sqrt(amount / scale)) : 0;
      const button = element("button", amount ? count(amount) : "·", `l${level}`);
      const selected = timeFilter?.weekday === weekday && timeFilter.hour === hour;
      button.type = "button";
      button.disabled = !amount;
      button.title = `${weekdays[weekday]} ${String(hour).padStart(2, "0")}:00 · ${count(amount)} 次`;
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-pressed", String(selected));
      button.addEventListener("click", () => {
        timeFilter = selected ? undefined : { weekday, hour };
        page = 1;
        refresh();
      });
      row.insertCell().append(button);
    }
  }
  get("heatmap").replaceChildren(heatmap);
}

function renderDaily(days) {
  const target = get("daily");
  if (!days.length) return empty(target);
  const byDate = new Map(days.map(({ day, count: amount }) => [day, amount]));
  const start = new Date(`${shanghaiDate.format(new Date())}T00:00:00Z`);
  const entries = Array.from({ length: Number(mainFilters.elements.days.value) }, (_, offset) => {
    const date = new Date(start.valueOf() - offset * 86400000).toISOString().slice(0, 10);
    return { day: date, count: byDate.get(date) ?? 0 };
  }).reverse();
  const scale = Math.max(1, ...entries.map((item) => item.count));
  target.replaceChildren(...entries.map(({ day, count: amount }) => {
    const row = element("div", null, "bar-row");
    const bar = element("div", null, "bar");
    bar.setAttribute("aria-hidden", "true");
    const fill = element("div");
    fill.style.width = `${100 * amount / scale}%`;
    bar.append(fill);
    row.append(element("span", String(day).slice(-5)), bar, element("strong", count(amount)));
    return row;
  }));
}

const column = (name, numeric = false) => ({ name, numeric });

function renderCommands(commands) {
  table(get("commands"), [column("指令"), column("次数", true), column("失败率", true), column("P95", true)],
    commands.map((item) => [
      `/${item.command}`, count(item.count),
      item.count ? `${decimal.format((item.errors ?? 0) * 100 / item.count)}%` : "—",
      item.p95_ms == null ? "—" : `${count(item.p95_ms)} ms`,
    ]));
}

function renderGroups(groups, total) {
  const denominator = total ?? groups.reduce((n, item) => n + item.count, 0);
  table(get("group-ranking"),
    [column("群"), column("平台实例"), column("次数", true), column("占比", true),
      column("活跃天数", true), column("活跃日日均", true)],
    groups.map((item) => {
      const button = element("button", item.group_name || item.group_id);
      button.type = "button";
      button.addEventListener("click", () => {
        get("private-chat").checked = false;
        mainFilters.elements.group.disabled = false;
        mainFilters.elements.platform.value = item.platform;
        mainFilters.elements.group.value = item.group_id;
        heatmapReference = undefined;
        timeFilter = undefined;
        page = 1;
        refresh();
      });
      return [
        button, item.platform, count(item.count),
        denominator ? `${decimal.format(item.count * 100 / denominator)}%` : "—",
        count(item.active_days),
        item.active_days ? decimal.format(item.count / item.active_days) : "—",
      ];
    }));
}

function tokenTotal(item) {
  return (item.input_other ?? 0) + (item.input_cached ?? 0) + (item.output ?? 0);
}

function renderModels(models) {
  const columns = [
    column("供应商"), column("模型"), column("判定次数", true), column("Token 覆盖", true),
    column("普通输入", true), column("缓存命中", true), column("输出", true),
    column("估算费用", true), column("计价覆盖", true), column("无法确认", true),
    column("判对结算", true), column("每次判对结算费用", true),
  ];
  table(get("models"), columns, models.map((item) => {
    const fraction = item.usage_count ? count : () => "—";
    return [
      item.provider, item.model, count(item.count), `${count(item.usage_count)} / ${count(item.count)}`,
      fraction(item.input_other), fraction(item.input_cached), fraction(item.output),
      money(item.amount, item.currency), `${count(item.priced)} / ${count(item.count)}`,
      count(item.unsure), count(item.settled),
      item.priced === item.count && item.settled && item.amount != null ?
        money(Number(item.amount) / item.settled, item.currency) : "—",
    ];
  }));
}

function sourceLink(row) {
  try {
    const url = new URL(row.source);
    if (url.protocol !== "https:") return row.source ?? "—";
    const link = element("a", url.hostname);
    link.href = url.toString();
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch {
    return row.source ?? "—";
  }
}

function renderPricing(pricing) {
  const columns = [
    column("厂商"), column("模型"), column("计价档"), column("价格版本"), column("来源"),
    column("普通输入 / 百万", true), column("缓存命中 / 百万", true), column("输出 / 百万", true),
  ];
  const rows = [];
  for (const [provider, models] of Object.entries(pricing?.catalog ?? {})) {
    for (const [model, rates] of Object.entries(models)) {
      const addRow = (label, amounts) => rows.push([
        provider, model, label, pricing.version, sourceLink({ source: pricing.sources?.[provider] }),
        ...amounts.slice(0, 3).map((value) => money(value, "USD")),
      ]);
      const longContext = pricing.long_context?.[model];
      if (provider === "deepseek") {
        addRow("峰时", rates);
        addRow("谷时", rates.map((value) => Number(value) / 2));
      } else {
        addRow(longContext ? `输入 < ${count(longContext[0])}` : "标准", rates);
        if (longContext) addRow(`输入 ≥ ${count(longContext[0])}`, longContext[1]);
      }
    }
  }
  table(get("pricing"), columns, rows, "暂无适用价目。");
}

function renderSummary(data) {
  const { commands = [], groups = [], hours = [], days = [], models = [] } = data;
  rememberOptions(data);
  if (!timeFilter || !heatmapReference) heatmapReference = hours;
  get("coverage").textContent = data.coverage_start ?
    `北京时间 UTC+8 · 记录始于 ${formatTime(data.coverage_start)}` : "北京时间 UTC+8";
  renderMetrics({ ...data, commands, models });
  showHeatmap(heatmapReference);
  renderDaily(days);
  renderCommands(commands);
  renderGroups(groups, data.group_total);
  renderModels(models);
  renderPricing(data.pricing);
}

function renderRecords({ items = [], total = 0, page: current = 1, page_size: size = 50 }) {
  rememberOptions({
    groups: items,
    models: items,
  });
  const columns = [
    column("时间"), column("群／平台实例"), column("模型"),
    { name: "玩家答案与标准曲名", className: "answers" },
    column("判定与结算"), column("耗时", true), column("Token 入／缓存／出", true),
    column("估算费用", true),
  ];
  table(get("records"), columns, items.map((item) => {
    const answer = element("div", null, "answer-pair");
    answer.append(element("span", item.answer ?? "—"), element("span", item.title ?? "—", "minor"));
    const model = element("div", null, "answer-pair");
    model.append(element("span", item.model ?? "—"), element("span", item.provider ?? "", "minor"));
    const cost = element("div", null, "answer-pair");
    cost.append(element("span", money(item.amount, item.currency)));
    if (item.price_version) cost.append(element("span", item.price_version, "minor"));
    if (item.price_tier) cost.append(element("span", item.price_tier, "minor"));
    const result = String(item.result ?? "").toLowerCase();
    const status = element("div", null, "answer-pair");
    status.append(element("span", outcomes[result] ?? (item.result || "—")));
    if (result === "same") status.append(element("span", item.settled ? "已结算答对" : "未结算", "minor"));
    return [
      formatTime(item.timestamp), [item.group_id || "私聊", item.platform].filter(Boolean).join("／"),
      model, answer, status, item.duration_ms == null ? "—" : `${count(item.duration_ms)} ms`,
      [item.input_other, item.input_cached, item.output].map(count).join(" / "),
      cost,
    ];
  }), "最近 7 天内暂无符合筛选条件的判定记录。");
  page = current;
  const pages = Math.max(1, Math.ceil(total / size));
  get("previous").disabled = page <= 1;
  get("next").disabled = page >= pages;
  get("page-info").textContent = `${count(page)} / ${count(pages)} 页，共 ${count(total)} 条`;
  get("pagination").hidden = total === 0;
}

async function refresh() {
  const current = ++requestNumber;
  const section = get(showSummary ? "overview" : "judgments");
  const status = get(showSummary ? "summary-status" : "judgment-status");
  const params = { ...formParams(mainFilters), ...timeFilter };
  if (get("private-chat")?.checked) params.group = "__private__";
  status.classList.remove("error");
  status.textContent = "加载中…";
  section.setAttribute("aria-busy", "true");
  try {
    if (!bridge) throw new Error("请在 AstrBot 管理后台打开此页面。");
    await bridge.ready();
    const data = showSummary ?
      await bridge.apiGet("stats/summary", params) :
      await bridge.apiGet("stats/judgments", {
        ...params, days: Math.min(Number(params.days), 7), page,
      });
    if (current !== requestNumber) return;
    const payload = data?.data ?? data;
    const rows = showSummary ? payload?.commands : payload?.items;
    if (!Array.isArray(rows)) throw new Error(payload?.message ?? "统计接口返回的数据无效。");
    if (showSummary) renderSummary(payload);
    else renderRecords(payload);
    status.textContent = "";
  } catch (error) {
    if (current !== requestNumber) return;
    status.classList.add("error");
    status.textContent = `加载失败。 ${error.message}`;
  } finally {
    if (current === requestNumber) section.setAttribute("aria-busy", "false");
  }
}

mainFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  heatmapReference = undefined;
  timeFilter = undefined;
  page = 1;
  refresh();
});
mainFilters.elements.platform.addEventListener("change", () => {
  mainFilters.elements.group.value = "";
  rememberOptions({});
});
get("private-chat")?.addEventListener("change", (event) => {
  mainFilters.elements.group.disabled = event.target.checked;
  timeFilter = undefined;
  heatmapReference = undefined;
  page = 1;
  refresh();
});
get("clear-time")?.addEventListener("click", () => {
  timeFilter = undefined;
  page = 1;
  refresh();
});
get("previous")?.addEventListener("click", () => {
  page -= 1;
  refresh();
});
get("next")?.addEventListener("click", () => {
  page += 1;
  refresh();
});
refresh();
