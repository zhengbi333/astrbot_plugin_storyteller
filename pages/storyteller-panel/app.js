/* 为你续写的故事 · 面板逻辑 v2（空灵科技风：顶部导航 + 居中章节排版） */
const bridge = window.AstrBotPluginPage;

const NAV = [
  { key: "overview", label: "总览" },
  { key: "troubleshoot", label: "清障" },
  { key: "models", label: "模型" },
  { key: "image", label: "生图" },
  { key: "appearance", label: "外观" },
  { key: "intercept", label: "拦＆改" },
  { key: "send", label: "发送" },
  { key: "rewrite", label: "润色" },
  { key: "debounce", label: "防抖" },
  { key: "identity", label: "防认错" },
  { key: "relationship", label: "关系" },
  { key: "voice", label: "风格" },
  { key: "persona", label: "人格" },
  { key: "presence", label: "状态" },
  { key: "schedule", label: "日程" },
  { key: "wardrobe", label: "穿搭" },
  { key: "mind", label: "内心" },
  { key: "memory", label: "记忆" },
  { key: "proactive", label: "主动" },
  { key: "emoji", label: "表情包" },
  { key: "token", label: "Token" },
  { key: "settings", label: "设置" },
  { key: "debug", label: "调试" },
  { key: "thanks", label: "鸣谢" },
];

const TITLES = {
  overview: ["总览", "品牌、Bot 当前状态与 token 总消耗"],
  troubleshoot: ["清障", "各模块自检：一键全部测试，故障红色标注"],
  models: ["模型", "全插件模型配置集中点：改这里或改各模块页，两处同步生效"],
  image: ["生图", "对话里说「画一张…」即可触发；独立 API 或 AstrBot 卡片渲染"],
  appearance: ["外观", "配色主题、明暗模式与背景效果"],
  intercept: ["拦＆改", "主链 LLM 请求介入方式、最终发送模板与最近发送内容"],
  rewrite: ["润色", "回复捕获后按模板二次润色与人格校准"],
  debounce: ["消息防抖", "连续消息合并状态"],
  identity: ["防认错", "区分当前对话对象，别搞混人称"],
  relationship: ["关系模型", "与每个人的关系档案"],
  voice: ["风格锚", "说话方式档案"],
  persona: ["人格", "你的身份与世界观（{人格} 注入体）"],
  presence: ["状态锚", "此刻的心情与精力"],
  schedule: ["日程锚", "每日日程"],
  wardrobe: ["穿搭与衣柜", "当前穿搭与衣物库"],
  mind: ["内心世界", "梦境、思考与见闻"],
  memory: ["记忆", "你的长期记忆（约定/愿望/时间线）"],
  proactive: ["主动对话", "智能主动触达"],
  send: ["发送", "回复发送缓冲与「被抢话」裁决"],
  emoji: ["表情包", "本地图库与分类"],
  token: ["Token 用量", "总 / 当天 / 当月 / 每模型"],
  settings: ["设置", "插件开关与界面偏好"],
  debug: ["插件调试", "运行时日志与诊断"],
  thanks: ["鸣谢", "创作者与测试伙伴"],
};

/* 基础明暗变量（与 style.css 的 :root 一致，主题在基础上覆盖） */
const BASE_LIGHT = {
  bg: "#f4fbfc", ink: "#16282b", ink2: "#5f7a7e", ink3: "#9db3b6",
  line: "rgba(22,74,82,0.12)", glowA: "#14b8a6", glowB: "#38bdf8",
};
const BASE_DARK = {
  bg: "#071114", ink: "#d9ecee", ink2: "#86a4a8", ink3: "#4d6a6e",
  line: "rgba(160,216,222,0.13)", glowA: "#2dd4bf", glowB: "#38bdf8",
};

const THEMES = [
  { key: "tide", name: "潮汐", sw: ["#14b8a6", "#38bdf8"],
    light: {}, dark: {} },
  { key: "aurora", name: "极光", sw: ["#22c55e", "#06b6d4"],
    light: { glowA: "#17a34a", glowB: "#0aa5c4" }, dark: { glowA: "#4ade80", glowB: "#22d3ee" } },
  { key: "pearl", name: "月白", sw: ["#64748b", "#94a3b8"],
    light: { bg: "#f8fafc", glowA: "#64748b", glowB: "#94a3b8" }, dark: { glowA: "#93a4b8", glowB: "#b8c5d8" } },
  { key: "nebula", name: "星云", sw: ["#7c6cf0", "#38bdf8"],
    light: { glowA: "#7c6cf0", glowB: "#38bdf8" }, dark: { glowA: "#a78bfa", glowB: "#4fb8f5" } },
  { key: "deepsea", name: "深海", sw: ["#2563eb", "#0ea5e9"],
    light: { bg: "#eef7ff", glowA: "#2563eb", glowB: "#0ea5e9" }, dark: { bg: "#060d1a", glowA: "#3b82f6", glowB: "#38bdf8" } },
  { key: "fern", name: "幽谷", sw: ["#16a34a", "#84cc16"],
    light: { glowA: "#16a34a", glowB: "#7cb814" }, dark: { glowA: "#22c55e", glowB: "#a3e635" } },
  { key: "rose", name: "暮霞", sw: ["#f43f5e", "#fb7185"],
    light: { glowA: "#e23d5c", glowB: "#fb7185" }, dark: { bg: "#150a0f", glowA: "#fb7185", glowB: "#fda4af" } },
  { key: "onyx", name: "玄墨", sw: ["#2dd4bf", "#38bdf8"],
    light: { glowA: "#14b8a6", glowB: "#38bdf8" },
    dark: { bg: "#04090b", line: "rgba(150,210,216,0.14)", glowA: "#2dd4bf", glowB: "#38bdf8" } },
];

const SCHEMES = [
  { key: "auto", label: "跟随系统" },
  { key: "light", label: "明亮" },
  { key: "dark", label: "暗色" },
];

const VAR_MAP = {
  bg: "--bg", ink: "--ink", ink2: "--ink-2", ink3: "--ink-3",
  line: "--line", glowA: "--glow-a", glowB: "--glow-b",
};

const state = {
  current: "overview",
  health: null,
  appearance: null,
  configSchema: null,
  configValues: null,
  providers: null, // AstrBot 模型列表（LLM 对话 provider 下拉用）
  embeddingProviders: null, // 嵌入模型列表（嵌入下拉用，与 LLM 分类分开）
  settingsModule: null,
  debugSub: "diag",
  tabOrder: null, // 用户自定义选项卡顺序（null = 默认布局）
  dragActive: false, // 拖拽进行中标志：抑制拖拽结束后的误点击
  logTimers: {}, // 各页日志轮询定时器（离开页面时清理）
  // 分页状态（发送页 / Token 页）
  sendQueuePage: 1,
  sendRecordPage: 1,
  tokenSource: "companion", // companion / main / memory
  tokenTaskPage: 1,
  tokenRecentPage: 1,
  memoryTlinePage: 1, // 记忆页·近期时间线分页（每页 15 条）
};

/* 通用分页组件：页大小可配（默认 5；记忆时间线用 10），返回分页条 HTML（<=1 页不渲染） */
const PAGE_SIZE = 5;
const TL_PAGE_SIZE = 10;
function pagerBar(pagerId, total, page, pageSize = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return "";
  const cur = Math.max(1, Math.min(page, pages));
  return `
    <div class="pager" id="${pagerId}">
      <button class="page-btn" data-page="${cur - 1}" ${cur <= 1 ? "disabled" : ""}>‹ 上一页</button>
      <span class="page-info">${cur} / ${pages}</span>
      <button class="page-btn" data-page="${cur + 1}" ${cur >= pages ? "disabled" : ""}>下一页 ›</button>
    </div>`;
}
function bindPager(pagerId, total, setPage, rerender, pageSize = PAGE_SIZE) {
  const node = document.getElementById(pagerId);
  if (!node) return;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  node.querySelectorAll("[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const p = parseInt(btn.dataset.page, 10);
      if (p >= 1 && p <= pages) {
        setPage(p);
        rerender();
      }
    });
  });
}
function pageSlice(list, page, pageSize = PAGE_SIZE) {
  const start = (Math.max(1, page) - 1) * pageSize;
  return (list || []).slice(start, start + pageSize);
}

const $ = (sel) => document.querySelector(sel);

/* 前端诊断日志：记录关键事件与 API 调用结果，展示于「调试」选项卡 */
const DIAG_LIMIT = 200;
const diagLines = [];

function diagLog(message) {
  const stamp = new Date().toTimeString().slice(0, 8);
  diagLines.push(`[${stamp}] ${message}`);
  if (diagLines.length > DIAG_LIMIT) diagLines.shift();
  const node = document.getElementById("dbg-diag");
  if (node) {
    node.textContent = diagLines.join("\n");
    node.scrollTop = node.scrollHeight;
  }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

/* 异步数据填充后的轻淡入 */
function dataIn(node) {
  if (!node) return;
  node.classList.remove("data-in");
  void node.offsetWidth;
  node.classList.add("data-in");
}

function toast(message, kind = "ok") {
  const wrap = $("#toast-wrap");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  wrap.appendChild(node);
  setTimeout(() => node.remove(), 3200);
}

/* 页面顶部错误横幅（API 不可用时定位问题用） */
function showApiBanner(message) {
  const existing = $("#api-banner");
  if (existing) existing.remove();
  const banner = document.createElement("div");
  banner.id = "api-banner";
  banner.textContent = message;
  document.body.prepend(banner);
}

async function apiGet(endpoint, params) {
  try {
    const result = await withTimeout(bridge.apiGet(endpoint, params || {}), 150000, "GET " + endpoint);
    diagLog(`GET ${endpoint} 成功`);
    return result;
  } catch (err) {
    diagLog(`GET ${endpoint} 失败: ${err.message}`);
    toast(err.message || "请求失败", "err");
    throw err;
  }
}

async function apiPost(endpoint, body) {
  try {
    diagLog(`POST ${endpoint} 发出: ${JSON.stringify(body || {}).slice(0, 100)}`);
    const result = await withTimeout(bridge.apiPost(endpoint, body || {}), 180000, "POST " + endpoint);
    diagLog(`POST ${endpoint} 成功`);
    return result;
  } catch (err) {
    diagLog(`POST ${endpoint} 失败: ${err.message}`);
    toast(`${err.message || "请求失败"}`, "err");
    throw err;
  }
}

/* 桥调用超时兜底：后端若卡住（如生成任务长时间无响应），不会让按钮永远"生成中" */
function withTimeout(promise, ms, label) {
  let timer = null;
  const timeoutP = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${label} 超时（${Math.round(ms / 1000)} 秒无响应），已终止等待`));
    }, ms);
  });
  return Promise.race([promise, timeoutP]).finally(() => {
    if (timer !== null) {
      try { clearTimeout(timer); } catch (_e) { /* 沙箱可能无 clearTimeout */ }
    }
  });
}

/* 生成按钮忙碌态：进入"生成中…"并每秒累加显示已等待秒数（让用户知道仍在工作而非卡死）。
   结束后自动恢复按钮原文与可用状态；沙箱无 setInterval 时静默退化为纯文本。 */
async function runWithBusy(btn, busyText, task) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = busyText;
  let secs = 0;
  let timer = null;
  try {
    timer = setInterval(() => {
      secs += 1;
      try { btn.textContent = `${busyText} ${secs}s`; } catch (_e) { /* 忽略 */ }
    }, 1000);
  } catch (_e) { timer = null; /* 沙箱可能无 setInterval */ }
  try {
    return await task();
  } finally {
    if (timer !== null) {
      try { clearInterval(timer); } catch (_e) { /* 沙箱可能无 clearInterval */ }
    }
    btn.disabled = false;
    btn.textContent = original;
  }
}

function modal(html) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="mask"><div class="dialog">${html}</div></div>`;
  root.querySelector(".mask").addEventListener("click", (event) => {
    if (event.target === event.currentTarget || event.target.closest("[data-close]")) closeModal();
  });
}

function closeModal() {
  $("#modal-root").innerHTML = "";
}

function confirmDialog(title, message, onConfirm) {
  modal(`
    <h3>${esc(title)}</h3>
    <p>${esc(message)}</p>
    <div class="dialog-actions">
      <button class="btn" data-close>取消</button>
      <button class="btn glow" id="dlg-ok">确认</button>
    </div>
  `);
  $("#dlg-ok").addEventListener("click", () => {
    closeModal();
    onConfirm();
  });
}

/* ------------------------------------------------------------- 主题应用 */

function systemDark() {
  try {
    const ctx = bridge.getContext ? bridge.getContext() : null;
    if (ctx && typeof ctx.isDark === "boolean") return ctx.isDark;
  } catch (e) {
    /* 忽略 */
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveMode(scheme) {
  if (scheme === "light") return "light";
  if (scheme === "dark") return "dark";
  return systemDark() ? "dark" : "light";
}

function themeVars(themeKey, mode) {
  const theme = THEMES.find((item) => item.key === themeKey);
  const base = mode === "dark" ? BASE_DARK : BASE_LIGHT;
  return { ...base, ...((theme && theme[mode]) || {}) };
}

function applyAppearance(appearance) {
  state.appearance = appearance || {};
  const a = state.appearance;
  const mode = resolveMode(a.scheme);
  const vars = themeVars(a.theme || "tide", mode);
  if (a.primary) vars.glowA = a.primary;
  if (a.accent) vars.glowB = a.accent;
  if (a.canvas && a.canvas_enabled) vars.bg = a.canvas;
  Object.entries(VAR_MAP).forEach(([key, cssName]) => {
    document.documentElement.style.setProperty(cssName, vars[key]);
  });
  if (a.scheme && a.scheme !== "auto") {
    document.documentElement.setAttribute("data-theme", mode);
  } else {
    document.documentElement.setAttribute("data-theme", mode);
  }
  const canvasOn = Boolean(a.canvas_enabled);
  const bgUrl = canvasOn && a.bg_data_url ? `url("${a.bg_data_url}")` : "none";
  document.documentElement.style.setProperty("--bg-image", bgUrl);
  document.documentElement.style.setProperty("--bg-image-opacity", String(a.canvas_opacity ?? 0.8));
  document.documentElement.style.setProperty("--bg-image-blur", `${a.canvas_blur ?? 0}px`);
  document.body.classList.toggle("bg-on", Boolean(canvasOn && a.bg_data_url));
}

/* 外观变更：乐观更新（本地立即生效），再异步持久化，失败时回滚。
   render 异常不阻断保存：渲染失败仅记录诊断，保存请求照常发出。 */
async function setAppearance(patch) {
  diagLog(`setAppearance: ${JSON.stringify(patch).slice(0, 100)}`);
  const previous = state.appearance;
  const next = { ...(previous || {}), ...patch };
  applyAppearance(next);
  diagLog("applyAppearance 完成");
  try {
    render();
    diagLog("render 完成");
  } catch (err) {
    diagLog(`render 异常（已继续保存）: ${err.message} @ ${err.stack ? err.stack.split("\n")[1] || "" : ""}`);
  }
  try {
    const saved = await apiPost("appearance/update", patch);
    diagLog(`apiPost 返回: ${JSON.stringify(saved).slice(0, 120)}`);
    // 后端返回不含背景图 data URL，合并保留本地缓存，避免背景图闪失
    const merged = { ...saved.appearance, bg_data_url: previous && previous.bg_data_url };
    applyAppearance(merged);
    toast("已保存");
  } catch (err) {
    diagLog(`保存失败: ${err.message}`);
    toast("保存失败，已回滚", "err");
    applyAppearance(previous);
    render();
  }
}

/* ------------------------------------------------------------- 数据加载 */

async function loadHealth() {
  try {
    state.health = await apiGet("health");
    diagLog(`health: ${state.health ? "v" + state.health.version : "无"}`);
  } catch (e) {
    state.health = null;
    diagLog(`health 失败: ${e.message}`);
    showApiBanner("插件接口不可用：" + (e.message || "请求失败") + "（请确认插件已启用并重载）");
  }
  $("#top-version").textContent = state.health ? `v${state.health.version}` : "连接失败";
}

async function loadAppearance() {
  const data = await apiGet("appearance");
  diagLog(`appearance 已加载: theme=${data.appearance && data.appearance.theme}`);
  applyAppearance(data.appearance);
}

/* ------------------------------------------------------------- 页面渲染 */

/* 按用户自定义顺序返回选项卡；无自定义或数据损坏时用默认布局 */
function orderedNav() {
  if (!state.tabOrder || state.tabOrder.length !== NAV.length) return NAV;
  const byKey = new Map(NAV.map((item) => [item.key, item]));
  const out = [];
  for (const key of state.tabOrder) {
    if (byKey.has(key)) {
      out.push(byKey.get(key));
      byKey.delete(key);
    }
  }
  for (const item of byKey.values()) out.push(item); // 兜底：漏掉的补在末尾
  return out;
}

/* 自动保存选项卡顺序；保存成功提示「已保存」 */
function saveTabOrder() {
  apiPost("ui/tab_order", { order: state.tabOrder })
    .then(() => toast("已保存"))
    .catch(() => {});
}

/* 读取后端保存的选项卡顺序（失败时静默使用默认布局） */
async function loadTabOrder() {
  try {
    const data = await apiGet("ui/tab_order");
    const order = data && data.order;
    if (Array.isArray(order) && order.length === NAV.length) {
      state.tabOrder = order;
    }
  } catch (err) {
    diagLog(`选项卡顺序加载失败: ${err.message}`);
  }
}

function renderNav() {
  const nav = $("#top-nav");
  nav.innerHTML = orderedNav()
    .map(
      (item) =>
        `<div class="nav-item ${item.key === state.current ? "active" : ""}" data-nav="${item.key}">${item.label}</div>`
    )
    .join("");
  // 指针拖拽排序（不依赖 HTML5 DnD：浏览器直接访问与 launcher 内置 iframe 页面均可用）
  // 交互：拿起后跟随鼠标，其它选项卡滑动让位露出插入位置，松手落定并自动保存
  let drag = null;
  const NAV_GAP = 6;
  const DRAG_THRESHOLD = 5; // 超过该位移才视为拖拽（区分点击）

  function measureDrag() {
    const rects = [];
    for (const el of nav.children) rects.push(el.getBoundingClientRect());
    drag.rects = rects;
    drag.index = Array.prototype.indexOf.call(nav.children, drag.el);
    drag.targetIndex = drag.index;
    drag.el.style.zIndex = "30";
    drag.el.classList.add("dragging");
    state.dragActive = true;
  }

  function moveDrag(clientX, clientY) {
    // rect 与 clientX/Y 同为视口坐标，直接相减：
    // 位移 = 鼠标位置 - 元素原位置 - 抓取点偏移（按下时鼠标在元素内的相对位置）
    // —— 拿起后抓取点保持与鼠标重合，而不是左上角贴鼠标
    const rect = drag.rects[drag.index];
    const x = clientX - rect.left - drag.grabX;
    const y = clientY - rect.top - drag.grabY;
    drag.el.style.transform = `translate(${x}px, ${y}px) scale(1.04)`;
    // 判定基准 = 被拖选项卡「中心」——与卡片宽度无关，任何卡片、任何位置判定一致
    const dragCenter = rect.left + rect.width / 2 + x;
    const half = rect.width / 2;
    drag.dragCenter = dragCenter;
    drag.half = half;
    applyShift();
  }

  /* 让位动画：判定范围 = 目标实际范围向两侧扩固定扩展量（20px，约 1/4 选项卡）——
     被拖卡片刚遮住目标一点点（而非差半卡、亦非遮住一半）就让位；
     进入与离开使用同一边界，回移立即恢复，无提前/滞后 */
  function applyShift() {
    const { rects, index: dragIndex } = drag;
    const dc = drag.dragCenter;
    const E = 20; // 判定扩展量（固定 px，宽度无关）
    const n = rects.length;
    for (const el of nav.children) {
      if (el === drag.el) continue;
      el.style.transform = "";
    }
    // 1) 接触/重叠：dragCenter 落在哪些目标的扩展范围内 → 取最近的
    let overlap = -1;
    let bestDist = Infinity;
    for (let i = 0; i < n; i++) {
      if (i === drag.index) continue;
      if (dc >= rects[i].left - E && dc <= rects[i].left + rects[i].width + E) {
        const d = Math.abs(dc - (rects[i].left + rects[i].width / 2));
        if (d < bestDist) {
          bestDist = d;
          overlap = i;
        }
      }
    }
    if (overlap >= 0) {
      if (overlap < dragIndex) {
        // 目标在左：目标及中间项向右让位
        for (let i = overlap; i < dragIndex; i++) {
          nav.children[i].style.transform = `translateX(${rects[i].width + NAV_GAP}px)`;
        }
      } else {
        // 目标在右：目标及中间项向左让位
        for (let i = dragIndex + 1; i <= overlap; i++) {
          nav.children[i].style.transform = `translateX(${-rects[i].width - NAV_GAP}px)`;
        }
      }
      return;
    }
    // 2) 两端：拖出最右/最左
    let lastRight = -Infinity;
    let firstLeft = Infinity;
    for (let i = 0; i < n; i++) {
      if (i === dragIndex) continue;
      lastRight = Math.max(lastRight, rects[i].left + rects[i].width);
      firstLeft = Math.min(firstLeft, rects[i].left);
    }
    if (dc > lastRight) {
      for (let i = dragIndex + 1; i < n; i++) {
        nav.children[i].style.transform = `translateX(${-rects[i].width - NAV_GAP}px)`;
      }
      return;
    }
    if (dc < firstLeft) {
      for (let i = 0; i < dragIndex; i++) {
        nav.children[i].style.transform = `translateX(${rects[i].width + NAV_GAP}px)`;
      }
    }
  }

  function finishDrag() {
    const items = Array.prototype.slice.call(nav.children);
    const dragIndex = items.indexOf(drag.el);
    items.splice(dragIndex, 1);
    // 落位与让位动画使用同一判定（扩展范围接触语义）：
    // 显示交换到哪里，松手就落在哪里，不再出现「显示末尾、落位却在旁边一格」
    const dc = drag.dragCenter;
    const rects = drag.rects;
    const E = 20; // 判定扩展量（与动画一致，保证落位 = 显示位置）
    let insertPos = dragIndex; // 兜底：原位
    let overlap = -1;
    let bestDist = Infinity;
    for (let i = 0; i < rects.length; i++) {
      if (i === dragIndex) continue;
      if (dc >= rects[i].left - E && dc <= rects[i].left + rects[i].width + E) {
        const d = Math.abs(dc - (rects[i].left + rects[i].width / 2));
        if (d < bestDist) {
          bestDist = d;
          overlap = i;
        }
      }
    }
    if (overlap >= 0) {
      const opos = items.indexOf(nav.children[overlap]);
      insertPos = overlap > dragIndex ? opos + 1 : opos;
    } else {
      // 两端兜底（扩展范围已覆盖全部间隙，此处防边界）
      let lastRight = -Infinity;
      let firstLeft = Infinity;
      for (let i = 0; i < rects.length; i++) {
        if (i === dragIndex) continue;
        lastRight = Math.max(lastRight, rects[i].left + rects[i].width);
        firstLeft = Math.min(firstLeft, rects[i].left);
      }
      if (dc > lastRight) insertPos = items.length;
      else if (dc < firstLeft) insertPos = 0;
    }
    items.splice(insertPos, 0, drag.el);
    // DOM 重排（元素本身不重建，事件绑定保留），随后清除全部位移让其平滑归位
    items.forEach((el) => nav.appendChild(el));
    for (const el of nav.children) {
      el.style.transform = "";
      el.style.zIndex = "";
    }
    drag.el.classList.remove("dragging");
    const newOrder = Array.prototype.map.call(nav.children, (el) => el.dataset.nav);
    const curOrder = orderedNav().map((i) => i.key);
    if (JSON.stringify(newOrder) !== JSON.stringify(curOrder)) {
      state.tabOrder = newOrder;
      saveTabOrder();
    }
    drag = null;
    setTimeout(() => {
      state.dragActive = false;
    }, 60);
  }

  function cancelDrag() {
    for (const el of nav.children) {
      el.style.transform = "";
      el.style.zIndex = "";
    }
    drag.el.classList.remove("dragging");
    drag = null;
    setTimeout(() => {
      state.dragActive = false;
    }, 60);
  }

  nav.querySelectorAll("[data-nav]").forEach((node) => {
    node.addEventListener("click", () => {
      if (state.dragActive) return; // 拖拽结束后的误点击不切换页面
      state.current = node.dataset.nav;
      render();
    });
    node.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "touch") return; // 触摸保持点击，不拖拽
      if (e.button !== 0) return;
      const rect = node.getBoundingClientRect();
      drag = {
        el: node,
        key: node.dataset.nav,
        startX: e.clientX,
        startY: e.clientY,
        grabX: e.clientX - rect.left, // 抓取点：鼠标相对元素左缘/顶缘
        grabY: e.clientY - rect.top,
        moved: false,
      };
      node.setPointerCapture(e.pointerId);
    });
    node.addEventListener("pointermove", (e) => {
      if (!drag || drag.el !== node) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      if (!drag.moved) {
        if (Math.abs(dx) + Math.abs(dy) < DRAG_THRESHOLD) return;
        drag.moved = true;
        drag.startX = e.clientX; // 重置起点，跟随不跳变
        drag.startY = e.clientY;
        measureDrag();
      }
      moveDrag(e.clientX, e.clientY);
    });
    node.addEventListener("pointerup", (e) => {
      if (!drag || drag.el !== node) return;
      if (!drag.moved) {
        drag = null; // 纯点击：不进入拖拽流程
        return;
      }
      finishDrag();
    });
    node.addEventListener("pointercancel", () => {
      if (!drag || drag.el !== node) return;
      if (drag.moved) cancelDrag();
      else drag = null;
    });
  });
}

/* 动画设置：按配置应用类型与时长（CSS 变量），供 render 切换时使用 */
function applyAnimationSettings() {
  const general = (state.configValues && state.configValues.general) || {};
  const rawType = String(general.animation_type || "rise");
  const enabled = general.page_animation !== false && rawType !== "none";
  const type = enabled ? rawType : "none";
  const names = { fade: "view-fade", rise: "view-rise", zoom: "view-zoom", slide: "view-slide" };
  const duration = Math.max(80, Math.min(1200, parseInt(general.animation_duration, 10) || 320));
  document.documentElement.style.setProperty("--anim-name", names[type] || "view-rise");
  document.documentElement.style.setProperty("--anim-duration", `${duration}ms`);
  state.anim = { enabled, type };
}

async function render() {
  // 离开旧页面：停止该页的实时轮询（防抖页等）
  stopAllPolling();
  renderNav();
  const [title, sub] = TITLES[state.current] || TITLES.overview;
  document.title = `${title} · 为你续写的故事`;
  try {
    if (state.current === "overview") renderOverview();
    if (state.current === "troubleshoot") renderTroubleshoot().catch((err) => diagLog(`清障页异常: ${err.message}`));
    if (state.current === "models") renderModels().catch((err) => diagLog(`模型页异常: ${err.message}`));
    if (state.current === "image") renderImage().catch((err) => diagLog(`生图页异常: ${err.message}`));
    if (state.current === "appearance") renderAppearance();
    // 异步数据加载不阻塞切换动画：同步部分先填充占位，数据回来后再填充内容
    if (state.current === "intercept") renderIntercept().catch((err) => diagLog(`拦＆改页异常: ${err.message}`));
    if (state.current === "rewrite") renderRewrite().catch((err) => diagLog(`润色页异常: ${err.message}`));
    if (state.current === "debounce") renderDebounce().catch((err) => diagLog(`防抖页异常: ${err.message}`));
    if (state.current === "identity") renderIdentity().catch((err) => diagLog(`身份页异常: ${err.message}`));
    if (state.current === "relationship") renderRelationships().catch((err) => diagLog(`关系页异常: ${err.message}`));
    if (state.current === "voice") renderVoice().catch((err) => diagLog(`风格页异常: ${err.message}`));
    if (state.current === "persona") renderPersona().catch((err) => diagLog(`人格页异常: ${err.message}`));
    if (state.current === "presence") renderPresence().catch((err) => diagLog(`状态页异常: ${err.message}`));
    if (state.current === "schedule") renderSchedule().catch((err) => diagLog(`日程页异常: ${err.message}`));
    if (state.current === "wardrobe") renderWardrobe().catch((err) => diagLog(`穿搭页异常: ${err.message}`));
    if (state.current === "mind") renderMind().catch((err) => diagLog(`内心页异常: ${err.message}`));
    if (state.current === "memory") renderMemory().catch((err) => diagLog(`记忆页异常: ${err.message}`));
    if (state.current === "proactive") renderProactive().catch((err) => diagLog(`主动页异常: ${err.message}`));
    if (state.current === "send") renderSend().catch((err) => diagLog(`发送页异常: ${err.message}`));
    if (state.current === "emoji") renderEmoji().catch((err) => diagLog(`表情包页异常: ${err.message}`));
    if (state.current === "token") renderToken().catch((err) => diagLog(`Token页异常: ${err.message}`));
    if (state.current === "settings") renderSettings().catch((err) => diagLog(`设置页异常: ${err.message}`));
    if (state.current === "debug") renderDebug().catch((err) => diagLog(`调试页异常: ${err.message}`));
    if (state.current === "thanks") renderThanks();
  } catch (err) {
    diagLog(`页面渲染异常: ${err.message}`);
    const view = $("#view");
    if (view) {
      view.innerHTML = `<div class="section"><p class="section-desc">渲染异常：${esc(err.message)}</p></div>`;
    }
  }
  // 页面切换动画：占位内容就绪后立即播放，不等网络
  const view = $("#view");
  if (view && state.anim && state.anim.enabled) {
    view.classList.remove("view-anim", "data-in");
    void view.offsetWidth;
    view.classList.add("view-anim");
  }
}

/* 轮询管理：各页实时刷新面板（离开页面自动停止） */
const pollers = {};

function startPolling(key, intervalMs, fn) {
  stopPolling(key);
  if (!intervalMs || intervalMs < 300) intervalMs = 1000;
  pollers[key] = setInterval(fn, intervalMs);
}

function stopPolling(key) {
  if (pollers[key]) {
    clearInterval(pollers[key]);
    delete pollers[key];
  }
}

function stopAllPolling() {
  Object.keys(pollers).forEach(stopPolling);
}

/* 日志面板刷新间隔（general.log_poll_interval，默认 1 秒） */
function pollIntervalSec() {
  try {
    const v = state.configValues && state.configValues.general && state.configValues.general.log_poll_interval;
    const n = parseInt(String(v), 10);
    return Number.isFinite(n) && n >= 1 ? n * 1000 : 1000;
  } catch (err) {
    return 1000;
  }
}

/* 防抖页：活跃会话与结算历史 */
function sessionUser(sessionId) {
  const parts = String(sessionId || "").split(":");
  return parts[parts.length - 1] || sessionId || "-";
}

/* 绑定设置项（bool 用点击、数字/文本/下拉用 change、选项用点击） */
function bindSettingsIn(container) {
  container.querySelectorAll("[data-setting]").forEach((node) => {
    const parts = node.dataset.setting.split(".");
    const module = parts[0];
    const key = parts[1];
    const type = node.dataset.type;
    // 兜底：即便漏标 data-type，原生 checkbox 也按布尔处理（读 checked 而非 value，否则永远存成 "on"）
    if (type === "bool" || node.type === "checkbox") {
      node.addEventListener("change", () => {
        saveConfigValue(module, key, node.checked);
      });
    } else if (type === "option") {
      node.addEventListener("click", () => {
        saveConfigValue(module, key, node.dataset.option);
        container.querySelectorAll(`[data-setting="${module}.${key}"]`).forEach((n) => n.classList.remove("active"));
        node.classList.add("active");
      });
    } else if (type === "number") {
      node.addEventListener("change", () => {
        saveConfigValue(module, key, Number(node.value));
      });
    } else {
      // text / provider 下拉等：change 时保存字符串值
      node.addEventListener("change", () => {
        saveConfigValue(module, key, node.value);
      });
    }
  });
}

async function renderDebounce() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载防抖…</div>`;
  let schemaData;
  try {
    schemaData = await apiGet("config/schema");
  } catch (err) {
    if (state.current === "debounce") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "debounce") return;
  const schema = schemaData.schema || {};
  const values = schemaData.values || {};
  const dbSchema = (schema.debounce && schema.debounce.items) || {};
  const dbValues = values.debounce || {};
  const field = (key) => {
    const item = dbSchema[key] || {};
    return renderSettingField("debounce", key, item, dbValues[key]);
  };
  // 智能判断实验区（橙色大开关 + 实验标签 + 直连模型下拉 + 最终等待时长）
  const smartHint = (dbSchema.smart_judge && dbSchema.smart_judge.hint) || "";
  const smartZone = `
    <div class="setting-card smart-zone">
      ${masterSwitch("debounce-smart", "智能判断", smartHint, Boolean(dbValues.smart_judge), "orange", "实验，慎用")}
      ${field("smart_provider_id")}
      ${field("smart_max_quiet_wait")}
      ${field("smart_use_context")}
      ${field("smart_context_count")}
    </div>`;
  // 其余防抖设置：开关聚前、数值/文本手动编辑在后（已排除总开关/撤回过滤/智能判断组）
  const restKeys = Object.keys(dbSchema).filter((k) =>
    !["enabled", "recall_filter", "smart_judge", "smart_provider_id", "smart_max_quiet_wait", "smart_use_context", "smart_context_count"].includes(k)
  );
  const restHtml = sortSettingEntries(
    restKeys.map((k) => [k, dbSchema[k]])
  ).map(([k]) => renderSettingField("debounce", k, dbSchema[k], dbValues[k])).join("");
  view.innerHTML = `
    ${placeholderHintCard("debounce")}
    <div class="debounce-layout">
      <div class="debounce-left">
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">正在收集的内容</h3>
            <button class="btn" id="db-refresh">刷新</button>
          </div>
          <div id="db-sessions">加载中…</div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">结算历史</h3>
            <div class="pager">
              <button class="page-btn" id="db-prev">‹ 上一页</button>
              <span class="page-info" id="db-page-info"></span>
              <button class="page-btn" id="db-next">下一页 ›</button>
            </div>
          </div>
          <div id="db-history">加载中…</div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">防抖插件日志</h3>
            <span class="hint">${Math.round(pollIntervalSec() / 1000)}s 实时</span>
          </div>
          <pre class="log-view" id="dbg-debounce-log">加载中…</pre>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">防抖 LLM 请求与判定结果</h3>
            <span class="hint">${Math.round(pollIntervalSec() / 1000)}s 实时</span>
          </div>
          <pre class="log-view" id="dbg-debounce-smart">加载中…</pre>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head">
            <h3 class="panel-title">图片识图<span class="field-key">vision</span></h3>
            <span class="hint">防抖页收纳</span>
          </div>
          <p class="section-desc">发送的图片由识图模型理解（防抖智能判断可用）；关闭则忽略图片。文件/链接摘要与识图共用一个模型。</p>
          <div class="settings-grid" style="grid-template-columns:1fr 1fr">
            ${renderSettingField("vision", "enabled", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.enabled) || { description: "识图开关", type: "bool", default: true }, (values.vision || {}).enabled)}
            ${renderSettingField("vision", "provider_id", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.provider_id) || { description: "识图模型", type: "string", role: "provider", default: "" }, (values.vision || {}).provider_id)}
            ${renderSettingField("vision", "file_summary", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.file_summary) || { description: "文件文档摘要", type: "bool", default: true }, (values.vision || {}).file_summary)}
            ${renderSettingField("vision", "link_summary", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.link_summary) || { description: "链接标题与要点", type: "bool", default: true }, (values.vision || {}).link_summary)}
            ${renderSettingField("vision", "media_retry", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.media_retry) || { description: "媒体调用重试次数", type: "int", default: 0 }, (values.vision || {}).media_retry)}
            ${renderSettingField("vision", "file_max_chars", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.file_max_chars) || { description: "文档读取上限(字符)", type: "int", default: 40000 }, (values.vision || {}).file_max_chars)}
            ${renderSettingField("vision", "gif_frames", (schemaData.schema && schemaData.schema.vision && schemaData.schema.vision.items && schemaData.schema.vision.items.gif_frames) || { description: "动图抽帧数", type: "int", default: 3 }, (values.vision || {}).gif_frames)}
          </div>
        </section>
      </div>
      <div class="debounce-right">
        <div class="settings-grid">
          ${masterSwitch("debounce-enabled", "防抖总开关", (dbSchema.enabled && dbSchema.enabled.hint) || "", Boolean(dbValues.enabled))}
          ${field("recall_filter")}
          ${smartZone}
          ${restHtml || '<div class="hint">暂无设置项</div>'}
        </div>
      </div>
    </div>
  `;
  bindSettingsIn(view);
  bindMasterSwitch("debounce-enabled", "debounce", "enabled");
  bindMasterSwitch("debounce-smart", "debounce", "smart_judge");
  const refreshBtn = document.getElementById("db-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", tickDebounce);
  const prevBtn = document.getElementById("db-prev");
  const nextBtn = document.getElementById("db-next");
  if (prevBtn) prevBtn.addEventListener("click", () => {
    state.debouncePage = Math.max(0, (state.debouncePage || 0) - 1);
    tickDebounce();
  });
  if (nextBtn) nextBtn.addEventListener("click", () => {
    state.debouncePage = (state.debouncePage || 0) + 1;
    tickDebounce();
  });
  // 四个展示面板统一实时轮询（间隔由「设置 → 日志面板刷新间隔」控制）
  startPolling("debounce", pollIntervalSec(), tickDebounce);
  await tickDebounce();
}

async function tickDebounce() {
  if (state.current !== "debounce") return;
  try {
    const [statusData, historyData, logData, smartData] = await Promise.all([
      apiGet("debounce/status"),
      apiGet("debounce/history"),
      apiGet("debounce/logs", { limit: 100 }),
      apiGet("debounce/smart_log", { limit: 30 }),
    ]);
    if (state.current !== "debounce") return;
    renderDebounceSessions(statusData);
    renderDebounceHistory(historyData);
    renderDebounceLogs(logData);
    renderDebounceSmart(smartData);
  } catch (err) {
    if (state.current !== "debounce") return;
  }
}

function renderDebounceSessions(statusData) {
  const sessionsNode = document.getElementById("db-sessions");
  if (!sessionsNode) return;
  const sessions = (statusData && statusData.sessions) || [];
  const enabled = !!(statusData && statusData.enabled);
  sessionsNode.innerHTML = !enabled
    ? '<div class="hint">防抖未开启（右侧开关可打开）。</div>'
    : sessions.length
      ? sessions.map((s) => `
          <div class="field">
            <div class="field-row">
              <div>
                <div class="field-title">${esc(sessionUser(s.session_id))}</div>
                <div class="hint">已收集 ${s.count} 条 · 剩余 ${s.remaining.toFixed(1)}s · ${esc(s.text_preview || "（仅图片）")}</div>
              </div>
              <button class="btn" data-flush-session="${esc(s.session_id)}">立即结算</button>
            </div>
          </div>
        `).join("")
      : '<div class="hint">暂无正在收集的内容。</div>';
  sessionsNode.querySelectorAll("[data-flush-session]").forEach((node) => {
    node.addEventListener("click", async () => {
      try {
        await apiPost("debounce/flush", { session_id: node.dataset.flushSession });
        toast("已立即结算");
        tickDebounce();
      } catch (err) {
        toast(`结算失败：${err.message}`, "err");
      }
    });
  });
}

function renderDebounceHistory(historyData) {
  const historyNode = document.getElementById("db-history");
  if (!historyNode) return;
  const history = (historyData && historyData.items) || [];
  const PAGE_SIZE = 8;
  const page = state.debouncePage || 0;
  const totalPages = Math.max(1, Math.ceil(history.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  state.debouncePage = safePage;
  const pageItems = history.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
  historyNode.innerHTML = pageItems.length
    ? pageItems.map((h) => `
        <div class="field">
          <div class="field-title">[${esc(h.time)}] ${esc(sessionUser(h.session_id))} · ${h.count} 条${h.image_count ? ` · ${h.image_count} 图` : ""}</div>
          <div class="hint" style="white-space:pre-wrap">${esc(h.text)}</div>
        </div>
      `).join("")
    : '<div class="hint">暂无结算记录。</div>';
  const pageInfo = document.getElementById("db-page-info");
  if (pageInfo) pageInfo.textContent = `${safePage + 1} / ${totalPages}`;
  const prevBtn = document.getElementById("db-prev");
  const nextBtn = document.getElementById("db-next");
  if (prevBtn) prevBtn.disabled = safePage <= 0;
  if (nextBtn) nextBtn.disabled = safePage >= totalPages - 1;
}

function renderDebounceLogs(logData) {
  const node = document.getElementById("dbg-debounce-log");
  if (!node) return;
  const items = (logData && logData.items) || [];
  node.textContent = items.length
    ? items.map((l) => `[${l.time}] ${l.message}`).join("\n")
    : "（暂无防抖日志）";
  node.scrollTop = node.scrollHeight;
}

function renderDebounceSmart(smartData) {
  const node = document.getElementById("dbg-debounce-smart");
  if (!node) return;
  const entries = (smartData && smartData.entries) || [];
  const sessions = (smartData && smartData.sessions) || [];
  const lines = [];
  for (const s of sessions) {
    const sm = s.smart || {};
    const enabled = Boolean(sm.enabled);
    const headFlag = enabled ? "● 智能判断" : "○ 常规防抖";
    let line = `${headFlag}｜${esc(sessionUser(s.session_id))}｜已收集 ${s.count} 条`;
    if (enabled) {
      line += `｜状态：${sm.status || "等待中"}｜已判定 ${sm.judge_count || 0} 次`;
      if (sm.last_action) {
        const actionCn = sm.last_action === "release" ? "放行" : sm.last_action === "fallback" ? "回退" : "继续等待";
        line += `｜最近：${actionCn}（${sm.last_reason || "-"}）`;
      }
      line += `｜剩余 ${s.remaining.toFixed(1)}s`;
    }
    lines.push(line);
    if (s.text_preview) lines.push(`  ↳ ${s.text_preview.slice(0, 90)}`);
  }
  if (!sessions.length && !entries.length) {
    lines.push("（暂无活动。开启「智能判断」后，缓冲内容每次更新都会直连判定模型快速判断。）");
  }
  for (const e of entries) {
    const kindCn = { request: "请求", result: "结果", fallback: "回退", timeout: "超时" }[e.kind] || e.kind;
    let line = `[${e.time}] ${kindCn}｜${esc(sessionUser(e.session_id))}｜`;
    if (e.kind === "request") {
      line += `发送给判定模型：${esc((e.prompt || "").slice(0, 140))}`;
    } else if (e.kind === "result") {
      const actionCn = e.action === "release" ? "放行" : e.action === "continue" ? "继续等待" : "?";
      line += `判定：${actionCn}｜${esc(e.reason || "")}`;
    } else {
      line += `处理：${esc(e.reason || "")}`;
    }
    lines.push(line);
  }
  node.textContent = lines.join("\n") || "（暂无记录）";
  node.scrollTop = node.scrollHeight;
}

/* 功能区总开关（大 + 颜色）+ 开关绑定 */
function masterSwitch(id, title, hint, checked, color = "red", tag = "") {
  const tagHtml = tag
    ? `<span class="exp-tag">${esc(tag)}</span>`
    : "";
  return `
    <div class="master-switch">
      <div>
        <div class="master-switch-title">${esc(title)}${tagHtml}</div>
        <div class="hint">${esc(hint)}</div>
      </div>
      <label class="switch ${color} large"><input type="checkbox" id="${id}" ${checked ? "checked" : ""}><span></span></label>
    </div>`;
}

async function bindMasterSwitch(id, module, key) {
  const node = document.getElementById(id);
  if (!node) return;
  node.addEventListener("change", async (e) => {
    try {
      await apiPost("config/module/update", { module, values: { [key]: e.target.checked } });
      toast("已保存");
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast(`保存失败：${err.message}`, "err");
    }
  });
}

async function loadModuleEnabled(module, key) {
  try {
    const data = await apiGet("config/schema");
    const values = data.values || {};
    return !(values[module] && values[module][key] === false);
  } catch (err) {
    return true;
  }
}

/* 关系页：左（关系档案）/ 中（人物卡 + 手动调整）/ 右（关系设置 + 判断模型） */
async function renderRelationships() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载关系…</div>`;
  let data;
  try {
    data = await apiGet("relationships");
  } catch (err) {
    if (state.current === "relationship") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "relationship") return;
  const rels = data.relationships || [];
  const cfg = state.configSchema || {};
  const cvals = state.configValues || {};
  const relSchema = (cfg.relationship && cfg.relationship.items) || {};
  const pipelineItems = (cfg.pipeline && cfg.pipeline.items) || {};
  const relVals = cvals.relationship || {};
  const pct = (a) => Math.max(0, Math.min(100, Math.round((a || 0) * 100)));
  let sel = rels.find((r) => r.user_id === state.relSelected) || rels[0] || null;
  if (sel) state.relSelected = sel.user_id; else state.relSelected = "";
  // 右栏设置卡（印象配置 + 关系判断模型）
  const batchItem = relSchema.impression_batch || { description: "印象提炼触发条数", type: "int", default: 10, hint: "hint" };
  const intervalItem = relSchema.impression_min_interval || { description: "印象提炼最短间隔(分钟)", type: "int", default: 30, hint: "hint" };
  const judgeItem = pipelineItems.provider_id || { description: "关系判断模型", type: "string", role: "provider", default: "" };
  const rightCards = [
    renderSettingField("relationship", "impression_batch", batchItem, relVals.impression_batch),
    renderSettingField("relationship", "impression_min_interval", intervalItem, relVals.impression_min_interval),
    renderSettingField("pipeline", "provider_id", judgeItem, (cvals.pipeline || {}).provider_id),
    renderSettingField("pipeline", "enabled", pipelineItems.enabled || { description: "回复链路总开关", type: "bool", default: true }, (cvals.pipeline || {}).enabled),
    renderSettingField("pipeline", "judge_enabled", pipelineItems.judge_enabled || { description: "关系判断开关", type: "bool", default: true }, (cvals.pipeline || {}).judge_enabled),
  ].join("");
  view.innerHTML = `
    ${placeholderHintCard("relationship")}
    <div class="rel-layout">
      <div class="rel-left">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">关系档案</h3><span class="hint">共 ${rels.length} 人</span></div>
          <div id="rel-list">
            ${rels.length ? rels.map((r) => `
              <div class="rel-item ${sel && r.user_id === sel.user_id ? "active" : ""}" data-rel="${esc(r.user_id)}">
                <div class="rel-item-top"><span class="rel-item-name">${esc(r.address || r.user_id)}</span><span class="hint">${esc(r.stage)} · ${esc(r.tier)}</span></div>
                <div class="progress"><div class="progress-fill" style="width:${pct(r.affection)}%"></div></div>
                <div class="hint">好感 ${pct(r.affection)}% · 互动 ${r.interactions} 次${r.impression ? " · " + esc(r.impression.slice(0, 20)) : ""}</div>
              </div>`).join("") : '<div class="hint">还没有关系记录，聊起来就有了。</div>'}
          </div>
        </section>
      </div>
      <div class="rel-center">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">人物卡</h3></div>
          ${sel ? `
            <div class="field">
              <div class="field-row"><div class="field-title">${esc(sel.address || sel.user_id)}</div><span class="hint">${esc(sel.user_id)}</span></div>
            </div>
            <div class="field"><div class="field-title">称呼</div><input class="text-input" id="rel-address" value="${esc(sel.address || "")}" /></div>
            <div class="field"><div class="field-title">好感度 <span class="field-key">0–100</span></div><input class="text-input" type="number" min="0" max="100" id="rel-aff" value="${pct(sel.affection)}" /></div>
            <div class="field"><div class="field-title">关系阶段 / 互动档位</div><div class="hint">${esc(sel.stage)} · ${esc(sel.tier)}</div></div>
            <div class="field"><div class="field-title">最近印象</div><div class="hint" style="color:var(--ink)">${esc(sel.impression || "（暂无，聊够后由关系判断模型提炼）")}</div></div>
            <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
              <button class="btn" id="rel-save">保存修改</button>
              <button class="btn" id="rel-preview-anchor">预览 {关系} 注入</button>
            </div>
            <div class="hint" id="rel-preview-out" style="margin-top:8px;white-space:pre-wrap"></div>
          ` : '<div class="hint">暂无档案</div>'}
        </section>
      </div>
      <div class="rel-right">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">关系设置</h3></div>
          ${masterSwitch("rel-enabled", "关系模型", "Bot 与每个用户的关系，随互动自然演进；总开关关闭则不记录、不注入 {关系}。", await loadModuleEnabled("relationship", "enabled"))}
          <div class="settings-grid" style="grid-template-columns:1fr">${rightCards}</div>
          <div class="rel-setting-note">关系判断模型：攒满「触发条数」条互动、且距上次提炼超过「最短间隔」时，由它提炼最近印象并微调好感度（原设置页「链路」的判定模型已移入此处）。</div>
        </section>
      </div>
    </div>
  `;
  await bindMasterSwitch("rel-enabled", "relationship", "enabled");
  bindSettingsIn(view);
  view.querySelectorAll("[data-rel]").forEach((node) => {
    node.addEventListener("click", () => { state.relSelected = node.dataset.rel; renderRelationships(); });
  });
  const saveBtn = document.getElementById("rel-save");
  if (saveBtn && sel) saveBtn.addEventListener("click", async () => {
    const aff = document.getElementById("rel-aff");
    const addr = document.getElementById("rel-address");
    const body = { user_id: sel.user_id };
    if (aff) body.affection = Math.max(0, Math.min(100, Number(aff.value) || 0)) / 100;
    if (addr) body.address = addr.value;
    try {
      await apiPost("relationships/update", body);
      toast("已保存");
      state.relSelected = sel.user_id;
      await reloadConfig();
      await renderRelationships();
    } catch (err) { toast(`保存失败：${err.message}`, "err"); }
  });
  const prevBtn = document.getElementById("rel-preview-anchor");
  const prevOut = document.getElementById("rel-preview-out");
  if (prevBtn && prevOut && sel) prevBtn.addEventListener("click", () => {
    const affV = Math.max(0, Math.min(1, (Number((document.getElementById("rel-aff") || {}).value) || 0) / 100));
    const stageV = affV >= 0.75 ? "亲近" : affV >= 0.5 ? "熟络" : affV >= 0.25 ? "普通" : "陌生";
    const tierV = affV >= 0.7 ? "亲近" : affV >= 0.35 ? "温暖" : affV >= 0.15 ? "放松" : "回避";
    const addrV = ((document.getElementById("rel-address") || {}).value || "").trim();
    const impV = (sel.impression || "").trim();
    prevOut.textContent = `【与对方的关系】\n${addrV ? `你平时称呼对方：${addrV}。\n` : ""}你和对方目前是「${stageV}」的关系，互动档位是「${tierV}」。\n${impV ? `最近印象：${impV}\n` : ""}这用来把握语气和分寸，但对方是谁以账号/ID 为准（见防认错）。`;
  });
}

/* 防认错页：当前对话对象提示说明 + 开关 */
async function renderIdentity() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载防认错…</div>`;
  let values;
  try {
    const data = await apiGet("config/schema");
    values = data.values || {};
  } catch (err) {
    if (state.current === "identity") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "identity") return;
  const enabled = !(values.identity && values.identity.enabled === false);
  let editorData = {};
  try {
    editorData = await apiGet("identity/editor");
  } catch (err) {}
  if (state.current !== "identity") return;
  const custom = editorData.custom || "";
  const preview = editorData.preview || "";
  state.configValues = state.configValues || {};
  state.configValues.identity = { ...(values.identity || {}), custom_text: custom };
  view.innerHTML = `
    ${placeholderHintCard("identity")}
    <section class="panel">
      <div class="identity-editor-row">
        <div class="identity-editor-left">
          ${masterSwitch("id-enabled", "防认错锚", "开启后，每次注入提示词的人称区分提醒（区分当前对话对象，别搞混人称）。", enabled)}
        </div>
        <div class="identity-editor-right">
          <div class="field-title">「{身份}」注入内容<span class="field-key">被取代后的内容</span></div>
          <div class="hint">此处预览/编辑每次注入 LLM 的防认错提醒。留空 = 自动生成；填写 = 此后固定使用（可引用 {当前用户}、{场合} 占位符）。保存生效。建议搭配防抖的 {当前说话}、{上下文} 使用。</div>
          <textarea id="id-editor" class="template-editor" spellcheck="false" placeholder="${esc(preview || "留空 = 自动生成防认错提醒；点「载入最近生成」可把自动内容放进此处便于修改。")}">${esc(custom)}</textarea>
          <div style="display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap">
            <span class="hint">最近自动生成预览：</span>
            <button class="btn" id="id-preview">载入最近生成</button>
            <span class="hint" style="max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${preview ? esc(preview.replace(/\n/g, " ").slice(0, 50)) + "…" : "（暂无，先发条对话）"}</span>
          </div>
          <div style="margin-top:12px">
            <button class="btn" id="id-save">保存注入内容</button>
          </div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">防认错提醒</h2>
        <p class="section-desc">提醒 LLM：提示词里已含当前对话、记忆与上下文，注意区分「当前和你对话的人」（{当前用户}、{场合}、{身份}），别张冠李戴。</p>
      </div>
      <div class="hint" style="white-space:pre-wrap">判定规则：
· 人物基于当前会话判定（发送者 ID + 会话键），不是从记忆里猜的；
· 称呼优先取【为你篆刻的历史】插件记录的名字，兜底平台昵称，再兜底 ID；
· 记忆/上下文里出现其他人时，明确提示「那是别人，不要张冠李戴」；
· 对方自称是另一个人时，像正常人一样自然接话，不机械否认。</div>
    </section>
  `;
  await bindMasterSwitch("id-enabled", "identity", "enabled");
  $("#id-preview").addEventListener("click", async () => {
    try {
      const d = await apiGet("identity/editor");
      const p = (d && d.preview) || "";
      const el = document.getElementById("id-editor");
      if (el) el.value = p || "";
      toast(p ? "已载入最近自动生成的内容" : "暂无自动生成记录（先发几条对话）", p ? "" : "err");
    } catch (err) {
      toast(`载入失败：${err.message}`, "err");
    }
  });
  $("#id-save").addEventListener("click", async () => {
    const el = document.getElementById("id-editor");
    if (!el) return;
    try {
      const val = el.value.trim();
      await apiPost("config/module/update", { module: "identity", values: { custom_text: val } });
      state.configValues.identity = { ...(state.configValues.identity || {}), custom_text: val };
      toast(val ? "防认错注入内容已保存（此后固定使用）" : "已清空，恢复自动生成");
    } catch (err) {
      toast(`保存失败：${err.message}`, "err");
    }
  });
}

/* 风格页：左（说话风格档案）/ 中（一键生成与示例）/ 右（风格设置） */
async function renderVoice() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载风格档案…</div>`;
  let data;
  try {
    data = await apiGet("voice");
  } catch (err) {
    if (state.current === "voice") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "voice") return;
  const voice = data.voice || {};
  state.voice = voice;
  const cfg = state.configSchema || {};
  const cvals = state.configValues || {};
  const voiceSchema = (cfg.voice && cfg.voice.items) || {};
  const voiceVals = cvals.voice || {};
  const genItem = voiceSchema.provider_id || { description: "风格生成模型", type: "string", role: "provider", default: "" };
  const groupItem = voiceSchema.group_quiet || { description: "群聊降噪", type: "bool", default: true };
  view.innerHTML = `
    ${placeholderHintCard("voice")}
    <div class="voice-layout">
      <div class="voice-left">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">一键生成</h3><span class="hint">直连风格生成模型</span></div>
          <div class="setting-card">
            <div class="field">
              <div class="field-title">人格选择</div>
              <div class="hint">读取 AstrBot 当前默认人格，自动填入下方输入框。</div>
              <select class="input" id="v-persona-select"><option value="">（加载中…）</option></select>
            </div>
          </div>
          <textarea id="v-persona" class="template-editor" spellcheck="false" placeholder="例如：一个温柔但偶尔毒舌的学姐……"></textarea>
          <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <button class="btn" id="v-generate">一键生成</button>
            <span class="hint">生成后用档案替换当前档案（自动保存）。</span>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">示例</h3><span class="hint">一键套用内置风格</span></div>
          <div id="v-examples">加载中…</div>
        </section>
      </div>
      <div class="voice-center">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">说话风格档案</h3><span class="hint">七维 + 口头禅</span></div>
          ${voiceTextField("tone", "语气基调", "温柔、耐心、轻声细语", voice.tone)}
          ${voiceTextField("sentence_length", "句子长短", "偏短句，偶尔长句", voice.sentence_length)}
          ${voiceTextField("verbosity", "话量倾向", "惜字如金 / 适中 / 话痨偏长爱铺陈（可附单次句数偏好）", voice.verbosity)}
          ${voiceTextField("punctuation", "标点与表情习惯", "多用省略号和波浪号", voice.punctuation)}
          ${voiceTextField("address", "称呼与距离感", "亲昵但不腻", voice.address)}
          ${voiceTextField("rhythm", "回复节奏（跟随对方）", "分两条短句发；对方简短我也简短，对方细腻我也跟着铺陈", voice.rhythm)}
          <div class="setting-card">
            <div class="field">
              <div class="field-title">口头禅与口癖</div>
              <div class="hint">每条含「文本 + 频率 + 触发语境」，由 LLM 按语境自然带出。</div>
              <div id="v-catchphrases"></div>
              <button class="btn" id="v-add-cp">+ 添加口头禅</button>
            </div>
          </div>
        </section>
      </div>
      <div class="voice-right">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">风格设置</h3></div>
          ${masterSwitch("voice-enabled", "风格锚", "开启后按这套说话档案回复；可随时关闭。", await loadModuleEnabled("voice", "enabled"))}
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("voice", "provider_id", genItem, voiceVals.provider_id)}
            ${renderSettingField("voice", "group_quiet", groupItem, voiceVals.group_quiet)}
          </div>
          <div class="rel-setting-note">风格生成模型：「一键生成」直连此模型生成整套风格档案（不走主链）；留空按「留空回退模型」策略，驳回时生成失败并报错日志。</div>
        </section>
      </div>
    </div>
  `;
  ["tone", "sentence_length", "punctuation", "address", "rhythm", "verbosity"].forEach((key) => {
    const node = document.getElementById(`v-${key}`);
    if (node) node.addEventListener("change", () => saveVoiceField(key, node.value));
  });
  const addBtn = document.getElementById("v-add-cp");
  if (addBtn) addBtn.addEventListener("click", () => {
    state.voice.catchphrases = state.voice.catchphrases || [];
    state.voice.catchphrases.push({ text: "", frequency: "", context: "" });
    renderCatchphraseRows();
  });
  renderCatchphraseRows();
  bindSettingsIn(view);
  // 人格选择：读取 AstrBot 当前默认人格，选择后自动填充到输入框
  const selEl = document.getElementById("v-persona-select");
  const ta = document.getElementById("v-persona");
  if (selEl && ta) {
    try {
      const pd = await apiGet("voice/personas");
      const ps = pd.personas || [];
      if (ps.length) {
        selEl.innerHTML = `<option value="">（不选择，手动填写）</option>` +
          ps.map((p) => `<option value="${esc(p.persona_id)}" data-desc="${esc(p.description || "")}">${esc(p.name || p.persona_id)}</option>`).join("");
        selEl.addEventListener("change", () => {
          const opt = selEl.options[selEl.selectedIndex];
          if (opt && opt.dataset.desc) ta.value = (opt.dataset.desc || "").trim();
        });
      } else {
        selEl.innerHTML = `<option value="">（未读取到 AstrBot 人格库，请手动填写）</option>`;
      }
    } catch (e) {
      selEl.innerHTML = `<option value="">（人格读取失败，请手动填写）</option>`;
    }
  }
  const genBtn = document.getElementById("v-generate");
  if (genBtn) genBtn.addEventListener("click", async () => {
    const persona = ((document.getElementById("v-persona") || {}).value || "").trim();
    if (!persona) { toast("请先填写人格描述或选一个人格", "err"); return; }
    try {
      const res = await runWithBusy(genBtn, "生成中…", () => apiPost("voice/generate", { persona_desc: persona }));
      state.voice = res.voice || {};
      toast("已生成并保存");
      await renderVoice();
    } catch (err) {
      toast(`生成失败：${err.message}`, "err");
    }
  });
  loadVoiceExamples();
  await bindMasterSwitch("voice-enabled", "voice", "enabled");
}

function voiceTextField(key, title, placeholder, value) {
  return `
    <div class="setting-card">
      <div class="field">
        <div class="field-title">${esc(title)}</div>
        <input id="v-${key}" class="input" value="${esc(value || "")}" placeholder="${esc(placeholder)}">
      </div>
    </div>
  `;
}

/* 人格页：左（一键生成人格注入体）/ 中（注入体编辑）/ 右（人格设置） */
async function renderPersona() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载人格…</div>`;
  let data;
  try {
    data = await apiGet("persona/read");
  } catch (err) {
    if (state.current === "persona") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "persona") return;
  const persona = data.persona || {};
  const text = (persona.text || "").trim();
  const cfg = state.configSchema || {};
  const cvals = state.configValues || {};
  const perSchema = (cfg.persona && cfg.persona.items) || {};
  const perVals = cvals.persona || {};
  const genItem = perSchema.provider_id || { description: "人格生成模型", type: "string", role: "provider", default: "" };
  view.innerHTML = `
    ${placeholderHintCard("persona")}
    <div class="voice-layout">
      <div class="voice-left">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">一键生成人格注入体</h3><span class="hint">直连人格生成模型</span></div>
          <div class="setting-card">
            <div class="field">
              <div class="field-title">人格选择</div>
              <div class="hint">从 AstrBot 人格库中选择，自动填入下方描述框。</div>
              <select class="input" id="p-persona-select"><option value="">（加载中…）</option></select>
            </div>
          </div>
          <textarea id="p-desc" class="template-editor" spellcheck="false" placeholder="例如：你是洛洛，一个温柔但偶尔毒舌的学姐，来自……"></textarea>
          <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <button class="btn" id="p-generate">一键生成</button>
            <span class="hint">生成「{人格}」注入体（名字/身份/世界观…）并自动保存。</span>
          </div>
        </section>
      </div>
      <div class="voice-center">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">人格注入体（{人格} 占位符内容）</h3><span class="hint">可直接编辑</span></div>
          <textarea id="p-text" class="template-editor" style="min-height:34vh" spellcheck="false" placeholder="${esc(text || "（暂无注入体：选个人格或填描述点一键生成）")}">${esc(text)}</textarea>
          <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <button class="btn" id="p-save">保存注入体</button>
            <button class="btn" id="p-clear">清空（回退 AstrBot 默认人格）</button>
            <span class="hint">清空保存后，{人格} 将回退为 AstrBot 当前默认人格。</span>
          </div>
        </section>
      </div>
      <div class="voice-right">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">人格设置</h3></div>
          ${masterSwitch("persona-enabled", "人格注入", "开启后注入 {人格} 占位符（你的身份/世界观等）。", await loadModuleEnabled("persona", "enabled"))}
          <div class="settings-grid" style="grid-template-columns:1fr">${renderSettingField("persona", "provider_id", genItem, perVals.provider_id)}</div>
          <div class="rel-setting-note">人格生成模型：「一键生成」直连该模型生成人格注入体（不走主链）；留空按「留空回退模型」策略，驳回时生成失败并报错。人格管「身份背景」，风格管「说话方式」。</div>
        </section>
      </div>
    </div>
  `;
  await bindMasterSwitch("persona-enabled", "persona", "enabled");
  bindSettingsIn(view);
  const selEl = document.getElementById("p-persona-select");
  const dta = document.getElementById("p-desc");
  if (selEl && dta) {
    try {
      const pd = await apiGet("persona/personas");
      const ps = pd.personas || [];
      if (ps.length) {
        selEl.innerHTML = `<option value="">（不选择，手动填写）</option>` +
          ps.map((p) => `<option value="${esc(p.persona_id)}" data-desc="${esc(p.description || "")}">${esc(p.name || p.persona_id)}</option>`).join("");
        selEl.addEventListener("change", () => {
          const o = selEl.options[selEl.selectedIndex];
          if (o && o.dataset.desc) dta.value = (o.dataset.desc || "").trim();
        });
      } else {
        selEl.innerHTML = `<option value="">（未读取到 AstrBot 人格库，请手动填写）</option>`;
      }
    } catch (e) {
      selEl.innerHTML = `<option value="">（人格读取失败，请手动填写）</option>`;
    }
  }
  const genBtn = document.getElementById("p-generate");
  if (genBtn) genBtn.addEventListener("click", async () => {
    const desc = ((document.getElementById("p-desc") || {}).value || "").trim();
    if (!desc) { toast("请先填写人格描述或选一个人格", "err"); return; }
    try {
      await runWithBusy(genBtn, "生成中…", () => apiPost("persona/generate", { persona_desc: desc }));
      toast("已生成并保存");
      await renderPersona();
    } catch (err) {
      toast(`生成失败：${err.message}`, "err");
    }
  });
  const saveBtn = document.getElementById("p-save");
  if (saveBtn) saveBtn.addEventListener("click", async () => {
    const v = ((document.getElementById("p-text") || {}).value || "").trim();
    try { await apiPost("persona/update", { text: v }); toast("已保存"); }
    catch (err) { toast(`保存失败：${err.message}`, "err"); }
  });
  const clearBtn = document.getElementById("p-clear");
  if (clearBtn) clearBtn.addEventListener("click", async () => {
    try {
      await apiPost("persona/update", { text: "" });
      toast("已清空，{人格} 回退 AstrBot 默认人格");
      await renderPersona();
    } catch (err) { toast(`清空失败：${err.message}`, "err"); }
  });
}

/* 润色页：左（模板编辑 + 发送给润色LLM的内容 + 润色后内容）/ 右（润色配置） */
async function renderRewrite() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载润色…</div>`;
  if (state.current !== "rewrite") return;
  const cfg = state.configSchema || {};
  const cvals = state.configValues || {};
  const rwSchema = (cfg.rewrite && cfg.rewrite.items) || {};
  const rwVals = cvals.rewrite || {};
  const genItem = rwSchema.provider_id || { description: "润色模型", type: "string", role: "provider", default: "" };
  const rwUserItem = rwSchema.rewrite_user_enabled || { description: "放行时润色用户消息", type: "bool", default: false };
  view.innerHTML = `
    <div class="rel-layout">
      <div class="rel-left" style="flex:1 1 0%;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">发送给润色 LLM 的模板</h3>
            <div style="display:flex;align-items:center;gap:10px"><button class="btn" id="rw-save-template">保存模板</button></div>
          </div>
          <p class="section-desc">润色提示词模板；占位符 {回复}{人格}{风格}{状态}{关系}{当前说话}{当前用户}{场合}… 发送前替换。</p>
          <div class="ph-chips" id="rw-chips"></div>
          <textarea id="rw-template" class="template-editor" spellcheck="false">${esc(rwVals.template || "")}</textarea>
        </section>
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">发送给润色 LLM 的内容</h3><span class="hint">实时</span></div>
          <pre class="log-view" id="rw-sent" style="max-height:26vh">加载中…</pre>
        </section>
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">润色后内容</h3><span class="hint">实时</span></div>
          <pre class="log-view" id="rw-polished" style="max-height:26vh">加载中…</pre>
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 340px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">润色配置</h3></div>
          <div class="rel-setting-note">这条对话最终「走主链 / 直连」由<b>「拦＆改 → 介入方式」</b>决定（当前介入方式：<b>${esc(((cvals.intercept || {}).mode) || "（未读取）")}</b>）。<br><br>本模块<b>不决定路由</b>，只在 LLM 回复生成后把它捕获、交给润色模型二次润色与人格校准——「接管改换（直连）」「接管走主链」「放行」三类回复都会先到这里润色再发出；「监视 / 阻断」不产生回复，故不经过本模块。</div>
          ${masterSwitch("rewrite-enabled", "回复润色总开关", "开启后捕获 LLM 回复（接管直连/走主链/放行），按模板交给润色模型二次润色与人格校准。", await loadModuleEnabled("rewrite", "enabled"))}
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("rewrite", "provider_id", genItem, rwVals.provider_id)}
            ${renderSettingField("rewrite", "rewrite_user_enabled", rwUserItem, rwVals.rewrite_user_enabled)}
          </div>
          <div class="rel-setting-note">润色模型：「回复润色总开关」开启后，润色模型直连生成润色文本（不走主链）；留空按「留空回退模型」策略，驳回/失败时用原回复发出并报错日志。</div>
        </section>
      </div>
    </div>
  `;
  await bindMasterSwitch("rewrite-enabled", "rewrite", "enabled");
  bindSettingsIn(view);
  // 模板占位符 chips
  const chipNode = document.getElementById("rw-chips");
  const ta = document.getElementById("rw-template");
  if (chipNode && ta) {
    chipNode.innerHTML = TEMPLATE_PLACEHOLDERS.map((p) => `<span class="ph-chip" data-ph="${esc(p)}">${esc(p)}</span>`).join("");
    chipNode.querySelectorAll(".ph-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const s = ta.selectionStart === null ? ta.value.length : ta.selectionStart;
        const e = ta.selectionEnd === null ? ta.value.length : ta.selectionEnd;
        ta.value = ta.value.slice(0, s) + chip.dataset.ph + ta.value.slice(e);
        const np = s + chip.dataset.ph.length;
        ta.focus();
        try { ta.setSelectionRange(np, np); } catch (err) {}
      });
    });
  }
  const saveTpl = document.getElementById("rw-save-template");
  if (saveTpl) saveTpl.addEventListener("click", async () => {
    const v = ((document.getElementById("rw-template") || {}).value || "");
    try {
      await apiPost("config/module/update", { module: "rewrite", values: { template: v } });
      if (!state.configValues) state.configValues = {};
      state.configValues.rewrite = { ...(state.configValues.rewrite || {}), template: v };
      toast("润色模板已保存");
    } catch (err) { toast(`保存失败：${err.message}`, "err"); }
  });
  await tickRewrite();
  startPolling("rewrite", pollIntervalSec(), tickRewrite);
}

async function tickRewrite() {
  const sentNode = document.getElementById("rw-sent");
  const polNode = document.getElementById("rw-polished");
  if (!sentNode || !polNode) return;
  try {
    const data = await apiGet("rewrite/buffer", { limit: 5 });
    if (state.current !== "rewrite") return;
    const items = data.items || [];
    sentNode.textContent = items.length ? items.map((it) => `[${it.time}] ${(it.prompt || "").slice(0, 900)}`).join("\n\n" + "─".repeat(44) + "\n\n") : "（暂无：发一条对话，捕获回复后实时显示）";
    polNode.textContent = items.length ? items.map((it) => `[${it.time}] ${it.polished || ""}`).join("\n\n" + "─".repeat(44) + "\n\n") : "（暂无）";
  } catch (err) {
    if (state.current !== "rewrite") return;
    sentNode.textContent = `加载失败：${err.message}`;
    polNode.textContent = `加载失败：${err.message}`;
  }
}

async function saveVoiceField(key, value) {
  if (!state.voice) return;
  state.voice[key] = value;
  await saveVoice();
}

async function saveVoice() {
  try {
    const res = await apiPost("voice/update", state.voice || {});
    state.voice = res.voice || state.voice;
    toast("已保存");
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
  }
}

function renderCatchphraseRows() {
  const box = document.getElementById("v-catchphrases");
  if (!box) return;
  const list = state.voice.catchphrases || [];
  box.innerHTML = list.map((cp, i) => `
    <div class="field-row" style="gap:6px">
      <input class="input" data-cp="text" data-i="${i}" value="${esc(cp.text || "")}" placeholder="文本，如「喵」">
      <input class="input" data-cp="frequency" data-i="${i}" value="${esc(cp.frequency || "")}" placeholder="频率，如「偶尔」">
      <input class="input" data-cp="context" data-i="${i}" value="${esc(cp.context || "")}" placeholder="语境，如「开心时」">
      <button class="btn" data-cp-del="${i}">删</button>
    </div>
  `).join("");
  box.querySelectorAll("[data-cp]").forEach((node) => {
    node.addEventListener("change", () => {
      const i = Number(node.dataset.i);
      const field = node.dataset.cp;
      if (!state.voice.catchphrases[i]) state.voice.catchphrases[i] = { text: "", frequency: "", context: "" };
      state.voice.catchphrases[i][field] = node.value;
      saveVoice();
    });
  });
  box.querySelectorAll("[data-cp-del]").forEach((node) => {
    node.addEventListener("click", () => {
      const i = Number(node.dataset.cpDel);
      state.voice.catchphrases.splice(i, 1);
      renderCatchphraseRows();
      saveVoice();
    });
  });
}

async function loadVoiceExamples() {
  const box = document.getElementById("v-examples");
  if (!box) return;
  try {
    const data = await apiGet("voice/examples");
    const examples = data.examples || [];
    box.innerHTML = examples.map((ex, i) => `
      <div class="field">
        <div class="field-row">
          <div>
            <div class="field-title">${esc(ex.name)}</div>
            <div class="hint">${esc(ex.voice.tone || "")}</div>
          </div>
          <button class="btn" data-example="${i}">套用</button>
        </div>
      </div>
    `).join("");
    box.querySelectorAll("[data-example]").forEach((node) => {
      node.addEventListener("click", async () => {
        const i = Number(node.dataset.example);
        const ex = examples[i];
        if (!ex) return;
        state.voice = ex.voice || {};
        await saveVoice();
        await renderVoice();
      });
    });
  } catch (err) {
    box.textContent = `加载示例失败：${err.message}`;
  }
}

/* 状态页：心情 + 精力 + 正在想的事 */
async function renderPresence() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载状态…</div>`;
  let data;
  try {
    data = await apiGet("presence");
  } catch (err) {
    if (state.current === "presence") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "presence") return;
  const presence = data.presence || {};
  const diag = data.diagnostic || {};
  state.presence = presence;
  const cfg = state.configSchema || {};
  const cvals = state.configValues || {};
  const prSchema = (cfg.presence && cfg.presence.items) || {};
  const prVals = cvals.presence || {};
  const dimBar = (label, value, lo, hi) => {
    const pct = Math.max(0, Math.min(100, Math.round(((value - lo) / (hi - lo)) * 100)));
    return `
      <div class="field">
        <div class="field-row">
          <div class="field-title">${label}</div>
          <div class="hint">${Number(value || 0).toFixed(2)}</div>
        </div>
        <div class="progress"><div class="progress-fill" style="width:${pct}%"></div></div>
      </div>`;
  };
  const drift = Array.isArray(presence.drift) ? presence.drift : [];
  const ripples = Array.isArray(presence.ripples) ? presence.ripples : [];
  const echoes = Array.isArray(presence.echoes) ? presence.echoes : [];
  const history = Array.isArray(presence.history) ? presence.history : [];
  const modelItem = prSchema.provider_id || { description: "状态模型", type: "string", role: "provider", default: "" };
  const weatherItem = prSchema.weather || { description: "当前天气", type: "string", default: "" };
  const settingCards = [
    "auto_refresh", "beat_interval", "stain_interval", "time_bg_enabled", "ripple_enabled", "memory_drydock",
  ].map((k) => {
    const item = prSchema[k] || { description: k, type: "bool", default: undefined };
    return renderSettingField("presence", k, item, prVals[k]);
  }).join("");
  view.innerHTML = `
    ${placeholderHintCard("presence")}
    <div class="presence-dash">
      <div class="presence-masters">
        ${masterSwitch("presence-enabled", "状态锚", "开启后按「语气走廊」影响回复语气；不降理解质量。", await loadModuleEnabled("presence", "enabled"))}
        ${masterSwitch("pr-light-evolve", "轻量事件演化", "对话中的情绪词/求助/道谢/争执 → 即时染色心绪并留涟漪+余波。关闭后全部停止写盘（已有数据保留），状态只在手动一键生成或开启「自动演化」时变化。", await loadModuleEnabled("presence", "light_evolve_enabled"))}
        <div class="presence-evolve panel">
          <div class="presence-evolve-title">演化</div>
          <div class="hint">${diag.auto_refresh ? "自动演化中" : "手动模式：开启「自动演化」后按节拍后台刷新"} · 节拍 ${esc(String(diag.next_beat_min || 30))} min · 来源 ${esc(diag.source || "未生成")}${diag.updated_at ? " · 更新于 " + esc(diag.updated_at) : ""}</div>
          <button class="btn" id="pr-evolve">一键生成</button>
        </div>
      </div>
      <div class="presence-cols-wrap">
      <div class="presence-cols">
        <div class="presence-main">
          <div class="dash-grid">
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">此刻 · 心绪三表</h3><span class="hint">调子 / 转速 / 电量</span></div>
              ${dimBar("调子（低沉 ↔ 轻快）", presence.tone !== undefined ? presence.tone : presence.valence, -1, 1)}
              ${dimBar("转速（慢 ↔ 急）", presence.tempo !== undefined ? presence.tempo : presence.arousal, -1, 1)}
              ${dimBar("电量（亏 ↔ 满）", presence.battery !== undefined ? presence.battery : presence.energy, 0, 1)}
              ${presenceField("mood", "心情（一句话）", "心情不错", presence.mood)}
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">心事</h3><span class="hint">心里正飘着的事</span></div>
              ${drift.length ? drift.slice(0, 3).map((it) => `<div class="hint" style="color:var(--ink);line-height:1.7">· ${esc(it.text || "")}</div>`).join("") : '<div class="hint">（暂无）</div>'}
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">状态怎么随对话/事件变</h3></div>
              <div class="hint" style="line-height:1.8;color:var(--ink)">① 对话中的情绪词/求助/道谢/争执 → 即时染色心绪并留下涟漪+余波（「轻量事件演化」，默认开，纯规则不调 LLM，可在上方主开关关闭）；② 每次读取 {状态} 按时间底色揉动语气走廊；③ 自动演化（可选）按节拍读「当下」（时间/日程/天气/余波/最近对话/上次状态）做大叙事——长期记忆不是情绪驱动器。</div>
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">最近余波</h3><span class="hint">演化输入 · 最多 3 条</span></div>
              ${echoes.length ? echoes.slice(0, 3).map((it) => `<div class="hint" style="color:var(--ink);line-height:1.7">· ${esc(it.text || "")}</div>`).join("") : '<div class="hint">（暂无：对话中出现情绪余波会留下这里）</div>'}
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">互动涟漪</h3><span class="hint">还没完全出来 · 最多 3 条</span></div>
              ${ripples.length ? ripples.slice(0, 3).map((it) => `<div class="hint" style="color:var(--ink);line-height:1.7">· ${esc(it.text || "")}</div>`).join("") : '<div class="hint">（暂无）</div>'}
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">语气走廊（Stance）</h3></div>
              <div class="hint" style="white-space:pre-wrap;color:var(--ink);line-height:1.8">${esc(diag.stance || "（暂无）")}</div>
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">手动微调心绪</h3></div>
              <div class="hint">直接改三表或心情，保存后自动重算语气走廊。</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
                <input class="text-input" id="pr-tone" style="width:90px" type="number" min="-1" max="1" step="0.05" value="${Number(presence.tone ?? presence.valence ?? 0).toFixed(2)}" />
                <input class="text-input" id="pr-tempo" style="width:90px" type="number" min="-1" max="1" step="0.05" value="${Number(presence.tempo ?? presence.arousal ?? 0).toFixed(2)}" />
                <input class="text-input" id="pr-battery" style="width:90px" type="number" min="0" max="1" step="0.05" value="${Number(presence.battery ?? presence.energy ?? 0.5).toFixed(2)}" />
                <button class="btn" id="pr-apply">应用</button>
              </div>
              <div class="field-key" style="margin-top:6px">顺序：调子 · 转速 · 电量</div>
            </section>
            <section class="panel">
              <div class="panel-head"><h3 class="panel-title">演化节拍记录</h3></div>
              ${history.length ? history.slice(-6).reverse().map((h) => `<div class="hint" style="line-height:1.7">${esc(h.at || "")}：${esc(h.mood || "")}（调子 ${Number(h.tone || 0).toFixed(2)} / 转速 ${Number(h.tempo || 0).toFixed(2)} / 电量 ${Number(h.battery ?? 0.5).toFixed(2)}）</div>`).join("") : '<div class="hint">（暂无）</div>'}
            </section>
          </div>
        </div>
        <aside class="presence-side">
          <section class="panel">
            <div class="panel-head"><h3 class="panel-title">状态设置</h3><span class="hint">自动演化默认关</span></div>
            <div class="settings-grid presence-settings-grid">
              ${renderSettingField("presence", "provider_id", modelItem, prVals.provider_id)}
              ${renderSettingField("presence", "weather", weatherItem, prVals.weather)}
              ${settingCards}
            </div>
            <div class="rel-setting-note">自动演化默认关（升级后不会突然常调模型）：要演化点「一键生成」或开启「自动演化」按节拍刷新；「轻量事件演化」控制对话中即时染色/涟漪/余波，可在上方一键关闭。</div>
          </section>
        </aside>
      </div>
      </div>
    </div>
  `;
  ["mood"].forEach((key) => {
    const node = document.getElementById(`p-${key}`);
    if (node) node.addEventListener("change", () => savePresenceField(key, node.value));
  });
  bindSettingsIn(view);
  const applyBtn = document.getElementById("pr-apply");
  if (applyBtn) applyBtn.addEventListener("click", async () => {
    try {
      const body = state.presence || {};
      body.tone = Math.max(-1, Math.min(1, Number((document.getElementById("pr-tone") || {}).value) || 0));
      body.tempo = Math.max(-1, Math.min(1, Number((document.getElementById("pr-tempo") || {}).value) || 0));
      body.battery = Math.max(0, Math.min(1, Number((document.getElementById("pr-battery") || {}).value) || 0.5));
      body.updated_at = new Date().toISOString().slice(0, 19).replace("T", " ");
      const res = await apiPost("presence/update", body);
      state.presence = res.presence || {};
      toast("已应用并重算语气走廊");
      await renderPresence();
    } catch (err) { toast(`应用失败：${err.message}`, "err"); }
  });
  const genBtn = document.getElementById("pr-evolve");
  if (genBtn) genBtn.addEventListener("click", async () => {
    genBtn.disabled = true;
    genBtn.textContent = "演化中…";
    try {
      const res = await apiPost("presence/evolve", {});
      state.presence = res.presence || {};
      toast("已演化并保存");
      await renderPresence();
    } catch (err) {
      toast(`演化失败：${err.message}`, "err");
      genBtn.disabled = false;
      genBtn.textContent = "一键生成";
    }
  });
  await bindMasterSwitch("pr-light-evolve", "presence", "light_evolve_enabled");
  await bindMasterSwitch("presence-enabled", "presence", "enabled");
}

function presenceField(key, title, placeholder, value) {
  return `
    <div class="field">
      <div class="field-title">${esc(title)}</div>
      <input id="p-${key}" class="input" value="${esc(value || "")}" placeholder="${esc(placeholder)}">
    </div>
  `;
}

async function savePresenceField(key, value) {
  if (!state.presence) return;
  state.presence[key] = value;
  try {
    const res = await apiPost("presence/update", state.presence);
    state.presence = res.presence || state.presence;
    toast("已保存");
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
  }
}

/* 日程页：时间 → 活动 */
async function renderSchedule() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载日程…</div>`;
  let data;
  try {
    data = await apiGet("schedule");
  } catch (err) {
    if (state.current === "schedule") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "schedule") return;
  const schedule = data.schedule || {};
  const diag = data.diagnostic || {};
  state.schedule = schedule;
  const now = diag.now || "";
  const entries = Array.isArray(schedule.entries) ? schedule.entries : [];
  const backlog = Array.isArray(schedule.backlog) ? schedule.backlog : [];
  const future = Array.isArray(schedule.future) ? schedule.future : [];
  const nowTime = (diag.now || "").slice(11, 16) || (diag.now || "");
  const inRange = (e) => {
    const s = e.start || "";
    const en = e.end || "";
    if (!en) return nowTime >= s;
    if (s <= en) return s <= nowTime && nowTime < en;
    return nowTime >= s || nowTime < en;
  };
  const entryRows = entries.map((e, i) => {
    const isNow = inRange(e);
    return `
      <div class="field ${isNow ? "sched-now" : ""}" style="${isNow ? "border-left:3px solid var(--glow-a);padding-left:10px" : ""}">
        <div class="field-row" style="gap:6px">
          <input class="input" data-s="start" data-i="${i}" value="${esc(e.start || "")}" placeholder="开始" style="max-width:84px">
          <input class="input" data-s="end" data-i="${i}" value="${esc(e.end || "")}" placeholder="结束" style="max-width:84px">
          <input class="input" data-s="activity" data-i="${i}" value="${esc(e.activity || "")}" placeholder="活动">
          <button class="btn" data-s-del="${i}">删</button>
        </div>
        ${e.replaced_from ? `<div class="hint">原计划：${esc(e.replaced_from)}${e.note ? " · " + esc(e.note) : ""}</div>` : (e.note ? `<div class="hint">${esc(e.note)}</div>` : "")}
        ${isNow ? '<div class="hint" style="color:var(--glow-a)">▶ 此刻</div>' : ""}
      </div>`;
  }).join("");
  // 「转盘」展示：命中此刻的条目索引（无命中则取最近开始的，随今天进行）
  const nowIdx = entries.findIndex((e) => inRange(e));
  const activeIdx = nowIdx >= 0 ? nowIdx : (entries.length ? entries.length - 1 : -1);
  const slotOf = (i) => {
    if (activeIdx < 0) return "sched-other";
    if (i === activeIdx) return "sched-now";
    if (i === activeIdx - 1) return "sched-prev";
    if (i === activeIdx + 1) return "sched-next";
    return "sched-other";
  };
  const readRow = (e, i) => {
    const isNow = i === activeIdx;
    return `
      <div class="sched-line ${slotOf(i)}" data-slot="${i}">
        <span class="sched-time">${esc(e.start || "")}${e.end ? "–" + esc(e.end) : ""}</span>
        <span class="sched-act">${esc(e.activity || "")}</span>
        ${e.note ? `<span class="hint">${esc(e.note)}</span>` : ""}
        ${isNow ? '<span class="hint" style="color:var(--glow-a)">▶ 此刻</span>' : ""}
      </div>`;
  };
  const shown = entries.map((e, i) => readRow(e, i)).join("");
  view.innerHTML = `
    ${placeholderHintCard("schedule")}
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">未来规划</h3><span class="hint">还没排进某天的事</span></div>
          ${future.length ? future.map((f) => `
            <div class="field"><div class="hint" style="color:var(--ink)">${esc(f.activity || "")}${f.date ? "（" + esc(f.date) + "）" : ""}${f.note ? " · " + esc(f.note) : ""}</div></div>`).join("")
            : '<div class="hint">暂无</div>'}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">延误日程</h3><span class="hint">被替换/延误的事</span></div>
          ${backlog.length ? backlog.map((b) => `
            <div class="field"><div class="hint" style="color:var(--ink)">${esc(b.activity || "")}${b.reason ? " · " + esc(b.reason) : ""}${b.at ? " · " + esc(b.at) : ""}</div></div>`).join("")
            : '<div class="hint">暂无</div>'}
          <div class="hint" style="margin-top:8px">下次生成日程时有机会补上。</div>
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">当天日程</h3>
              <div class="hint">${esc(diag.current_activity || "空闲/未安排")} · 共 ${diag.count || 0} 段${activeIdx >= 0 ? "（转盘：此刻在" + esc(entries[activeIdx].activity || "") + "）" : ""}</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center">
              <button class="btn" id="s-toggle">展开全部</button>
              <button class="btn glow" id="s-generate">一键生成新日程</button>
            </div>
          </div>
          ${entries.length ? `
            <div id="s-marquee">${shown}</div>
            <div id="s-rows" style="display:none">${entryRows}</div>
          ` : '<div class="hint">今天还没有日程——点右上角一键生成；插件运行期间也会自动补生成（电脑/服务离线期间不会生成）。</div>'}
          <button class="btn" id="s-add" style="margin-top:10px">+ 添加一段</button>
        </section>
        <div class="setting-card" style="margin-top:16px">
          <div class="field-title">生成提示词（发给直连模型的原文）<span class="field-key">prompt preview</span></div>
          <div class="hint">「一键生成新日程」实际发送给日程模型的完整内容 = 固定任务模板（只输出 JSON：日程段+穿搭）+ 人格与世界观（注入体）/ 人格风格 / 此刻状态 / 天气 / 记忆里的约定愿望（最近 6 条）/ 衣柜名单 / 未来规划 / 延误事项（有则拼接，无则不占字）。下方为<b>只读预览</b>：不调用模型、不消耗 Token，与真实生成时发送的内容完全一致。</div>
          <button class="btn" id="s-prompt-preview" style="margin-top:10px">查看 / 刷新提示词预览</button>
          <div id="s-prompt-box" style="display:none;margin-top:10px"></div>
        </div>
      </div>
      <div class="rel-right" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">日程设置</h3></div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("schedule", "enabled", (state.configSchema && state.configSchema.schedule && state.configSchema.schedule.items && state.configSchema.schedule.items.enabled) || { description: "日程锚总开关", type: "bool", default: true }, ((state.configValues || {}).schedule || {}).enabled)}
            ${renderSettingField("schedule", "auto_manage_enabled", (state.configSchema && state.configSchema.schedule && state.configSchema.schedule.items && state.configSchema.schedule.items.auto_manage_enabled) || { description: "实时调整（像人）", type: "bool", default: true }, ((state.configValues || {}).schedule || {}).auto_manage_enabled)}
            ${renderSettingField("schedule", "provider_id", (state.configSchema && state.configSchema.schedule && state.configSchema.schedule.items && state.configSchema.schedule.items.provider_id) || { description: "日程模型", type: "string", role: "provider", default: "" }, ((state.configValues || {}).schedule || {}).provider_id)}
            ${renderSettingField("schedule", "diary_time", (state.configSchema && state.configSchema.schedule && state.configSchema.schedule.items && state.configSchema.schedule.items.diary_time) || { description: "写日记时间(HH:MM)", type: "string", default: "23:30" }, ((state.configValues || {}).schedule || {}).diary_time)}
            ${renderSettingField("schedule", "diary_minutes", (state.configSchema && state.configSchema.schedule && state.configSchema.schedule.items && state.configSchema.schedule.items.diary_minutes) || { description: "写日记时长(分钟)", type: "int", default: 20 }, ((state.configValues || {}).schedule || {}).diary_minutes)}
          </div>
          <div class="rel-setting-note">日程锚只注入「当前正在做什么」；对话里出现明确的安排时，Bot 会用日程模型像人一样决定改不改（重要→替换/排空档/进未来规划/改穿搭，原安排进延误缓存池）；检测门槛高，不每句话判定。</div>
        </section>
      </div>
    </div>
  `;
  const addBtn = document.getElementById("s-add");
  if (addBtn) addBtn.addEventListener("click", () => {
    state.schedule.entries = state.schedule.entries || [];
    state.schedule.entries.push({ start: "09:00", end: "10:00", activity: "", note: "" });
    renderScheduleRows();
  });
  renderScheduleRows();
  const toggleBtn = document.getElementById("s-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", () => {
    const marquee = document.getElementById("s-marquee");
    const rows = document.getElementById("s-rows");
    const expanded = marquee && marquee.style.display !== "none";
    if (marquee) marquee.style.display = expanded ? "none" : "";
    if (rows) rows.style.display = expanded ? "" : "none";
    if (toggleBtn) toggleBtn.textContent = expanded ? "收起为转盘" : "展开全部";
    if (expanded) { renderScheduleRows(); } else { bindScheduleRows(); }
  });
  const genBtn = document.getElementById("s-generate");
  if (genBtn) genBtn.addEventListener("click", () => {
    const doGenerate = async () => {
      try {
        await runWithBusy(genBtn, "生成中…", () => apiPost("schedule/generate", {}));
        toast("已生成并保存");
        await renderSchedule();
      } catch (err) {
        toast(`生成失败：${err.message}`, "err");
      }
    };
    if (entries.length) {
      confirmDialog("覆盖当前日程", "今天已有日程，生成新日程会覆盖它（延误池与未来规划保留）。确定吗？", doGenerate);
    } else {
      doGenerate();
    }
  });
  // 提示词预览（只读，不消耗 Token）：展示发送给直连模型的原文 + 素材清单
  const pvBtn = document.getElementById("s-prompt-preview");
  if (pvBtn) pvBtn.addEventListener("click", async () => {
    const box = document.getElementById("s-prompt-box");
    if (!box) return;
    pvBtn.disabled = true;
    try {
      const res = await apiGet("schedule/prompt_preview");
      const ings = (res.ingredients || []).map((it) => `
        <div class="hint" style="color:var(--ink)">${it.used ? "✅" : "➖"} <b>${esc(it.label)}</b>${it.note ? " — " + esc(it.note) : ""}
          ${it.used && it.preview ? `<div class="hint" style="margin-top:2px">　${esc(it.preview)}${it.preview.length >= 80 ? "…" : ""}</div>` : ""}
        </div>`).join("");
      box.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div class="hint" style="margin:0">将发送给模型：<b>${esc(res.model || "default")}</b> · 共 ${res.length || 0} 字符 · 素材拼入情况：</div>
          <button class="btn" id="s-prompt-close">收起</button>
        </div>
        <div class="panel" style="padding:10px 12px;margin-bottom:10px">${ings}</div>
        <pre class="panel" style="white-space:pre-wrap;word-break:break-word;font-size:12.5px;line-height:1.7;padding:12px;max-height:340px;overflow:auto;margin:0">${esc(res.prompt || "")}</pre>
      `;
      box.style.display = "";
      const closeBtn = document.getElementById("s-prompt-close");
      if (closeBtn) closeBtn.addEventListener("click", () => { box.style.display = "none"; });
    } catch (err) {
      toast(`预览失败：${err.message}`, "err");
    } finally {
      pvBtn.disabled = false;
    }
  });
  await bindMasterSwitch("schedule-enabled", "schedule", "enabled");
  bindSettingsIn(view);
}

function renderScheduleRows() {
  const box = document.getElementById("s-rows");
  if (!box) return;
  const list = (state.schedule && state.schedule.entries) || [];
  box.innerHTML = list.map((item, i) => `
    <div class="field-row" style="gap:6px">
      <input class="input" data-s="start" data-i="${i}" value="${esc(item.start || "")}" placeholder="开始 HH:MM">
      <input class="input" data-s="end" data-i="${i}" value="${esc(item.end || "")}" placeholder="结束 HH:MM">
      <input class="input" data-s="activity" data-i="${i}" value="${esc(item.activity || "")}" placeholder="活动">
      <button class="btn" data-s-del="${i}">删</button>
    </div>
    ${item.note ? `<div class="hint">${esc(item.note)}</div>` : ""}
  `).join("");
  bindScheduleRows();
}

function bindScheduleRows() {
  const box = document.getElementById("s-rows");
  if (!box) return;
  const list = (state.schedule && state.schedule.entries) || [];
  box.querySelectorAll("[data-s]").forEach((node) => {
    node.addEventListener("change", () => {
      const i = Number(node.dataset.i);
      const field = node.dataset.s;
      if (!list[i]) list[i] = { start: "", end: "", activity: "", note: "" };
      list[i][field] = node.value;
      saveSchedule();
    });
  });
  box.querySelectorAll("[data-s-del]").forEach((node) => {
    node.addEventListener("click", () => {
      list.splice(Number(node.dataset.sDel), 1);
      renderScheduleRows();
      saveSchedule();
    });
  });
}

async function saveSchedule() {
  try {
    const res = await apiPost("schedule/update", { entries: (state.schedule && state.schedule.entries) || [] });
    state.schedule = res.schedule || state.schedule;
    toast("已保存");
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
  }
}

/* 穿搭页：当前穿搭 + 衣柜 */
async function renderWardrobe() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载穿搭…</div>`;
  let data;
  try {
    data = await apiGet("wardrobe");
  } catch (err) {
    if (state.current === "wardrobe") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "wardrobe") return;
  const closetRaw = Array.isArray(data.closet) ? data.closet : [];
  let closet = closetRaw.slice();
  // 0.151 重要优先：手动标记 > 自动重要 > 普通，其余保持添加顺序
  const rankOf = (c) => (c.manual ? 0 : c.important ? 1 : 2);
  closet.sort((a, b) => rankOf(a) - rankOf(b));
  const outfit = data.outfit || {};
  const outfitItems = Array.isArray(outfit.items) ? outfit.items : [];
  view.innerHTML = `
    ${placeholderHintCard("wardrobe")}
    <section class="section">
      <div class="section-head"><h2 class="section-title">穿搭设置</h2>
        <p class="section-desc">开启后 {穿搭} 占位符与衣柜/当前穿搭可用。生成衣柜会注入角色人格、天气与现有衣柜风格。</p>
      </div>
      ${masterSwitch("wardrobe-enabled", "穿搭与衣柜总开关", "开启后 {穿搭} 占位符与衣柜/当前穿搭可用。", await loadModuleEnabled("wardrobe", "enabled"))}
      <div class="settings-grid" style="grid-template-columns:1fr 1fr">${renderSettingField("wardrobe", "provider_id", (state.configSchema && state.configSchema.wardrobe && state.configSchema.wardrobe.items && state.configSchema.wardrobe.items.provider_id) || { description: "穿搭生成模型", type: "string", role: "provider", default: "" }, ((state.configValues || {}).wardrobe || {}).provider_id)}</div>
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">当前穿搭</h3>
              <div class="hint">由 LLM 结合天气/场合/心情生成，也可以手动修改。</div>
            </div>
            <button class="btn" id="gen-outfit" style="white-space:nowrap">一键生成穿搭</button>
          </div>
          <div class="field">
            <div class="field-title">穿戴</div>
            <input class="input" id="outfit-items" value="${esc(outfitItems.join("、"))}" placeholder="如：白色连衣裙、帆布鞋">
            <div class="field-title" style="margin-top:10px">理由</div>
            <input class="input" id="outfit-note" value="${esc(outfit.note || "")}" placeholder="这样穿的理由">
            <button class="btn glow" id="save-outfit" style="margin-top:10px">保存穿搭</button>
          </div>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><div><h3 class="panel-title">添加衣物</h3><span class="hint">自动标记为重要（蓝色边线）</span></div></div>
          <div class="field-row" style="gap:6px;flex-wrap:wrap">
            <input class="input" id="new-closet-name" placeholder="名称，如「白色连衣裙」" style="flex:1 1 100%">
            <input class="input" id="new-closet-cat" placeholder="类别（可选）" style="flex:1">
            <button class="btn" id="add-closet" style="flex-shrink:0">添加</button>
          </div>
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head">
            <div><h3 class="panel-title">衣柜</h3><span class="hint">${closet.length}/70 件 · 重要衣物（蓝/橙边线）优先展示，不会被一键置换清空</span></div>
          </div>
          <div id="wardrobe-closet-list"></div>
          <div id="wardrobe-pager" style="margin-top:8px"></div>
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 320px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">生成衣柜</h3><span class="hint">预览 → 逐件应用</span></div>
          <button class="btn glow" id="gen-batch" style="width:100%">✨ 一次生成十件</button>
          <div class="hint" style="margin-top:6px">生成结果展示在下方，每件可单独「应用」（加入衣柜）或「删除」（从预览移除）；每次生成会重置预览；与现有衣柜明显同款会被自动剔除。</div>
          <div id="gen-preview" style="margin-top:8px"></div>
          <div style="height:1px;background:var(--line);margin:12px 0"></div>
          <button class="btn" id="replace-all" style="width:100%">🔄 一键置换衣柜（清空+重新生成 20 件）</button>
          <div class="hint" style="margin-top:6px">直接置换，不经过预览；重要衣物（蓝/橙边线）保留，只能手动删除。</div>
        </section>
      </div>
    </div>
  `;
  // 衣柜分页渲染（10 件/页，重要优先已排序），紧凑行距 + 重要边线 + 钉/删
  const renderClosetPage = () => {
    const listBox = document.getElementById("wardrobe-closet-list");
    const pagerBox = document.getElementById("wardrobe-pager");
    if (!listBox) return;
    // 0.154：衣柜每页 20 件（用户要求；行距已紧凑，单页信息密度更高）
    const PAGE = 20;
    const pages = Math.max(1, Math.ceil(closet.length / PAGE));
    let page = state.wardrobePage || 0;
    if (page >= pages) page = pages - 1;
    if (page < 0) page = 0;
    state.wardrobePage = page;
    const slice = closet.slice(page * PAGE, page * PAGE + PAGE);
    listBox.innerHTML = slice.length ? slice.map((c) => {
      const cls = c.manual ? "wardrobe-item manual" : (c.important ? "wardrobe-item important" : "wardrobe-item");
      return `
        <div class="${cls}">
          <div class="wardrobe-item-info">
            <div style="font-size:13.5px;font-weight:600;color:var(--ink);line-height:1.35">${esc(c.name)}${c.manual ? " <span class='hint' style='color:#f59e0b'>📌手动</span>" : (c.important ? " <span class='hint' style='color:#38bdf8'>★重要</span>" : "")}</div>
            <div class="hint" style="line-height:1.35">${esc(c.category || "")}${c.note ? " · " + esc(c.note) : ""}</div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
            <button class="btn mini" data-pin-item="${esc(c.id)}" data-manual="${c.manual ? "1" : "0"}" title="${c.manual ? "取消手动标记" : "标记为重要（手动）"}">${c.manual ? "取消📌" : "📌"}</button>
            <button class="btn mini ghost-danger" data-del-item="${esc(c.name)}">删</button>
          </div>
        </div>`;
    }).join("") : '<div class="hint">衣柜还是空的——点右栏「一次生成十件」生成预览后应用，或直接「一键置换衣柜」。</div>';
    pagerBox.innerHTML = pages > 1 ? `
      <div class="field-row" style="gap:6px;justify-content:space-between">
        <span class="hint" style="color:var(--ink)">第 ${page + 1}/${pages} 页 · 共 ${closet.length} 件</span>
        <div style="display:flex;gap:6px">
          <button class="btn" data-closet-page="${page - 1}" ${page === 0 ? "disabled" : ""}>‹ 上一页</button>
          <button class="btn" data-closet-page="${page + 1}" ${page >= pages - 1 ? "disabled" : ""}>下一页 ›</button>
        </div>
      </div>` : "";
    listBox.querySelectorAll("[data-del-item]").forEach((node) => {
      node.addEventListener("click", async () => {
        try {
          await apiPost("wardrobe/closet/remove", { name: node.dataset.delItem });
          toast("已删除");
          await renderWardrobe();
        } catch (err) { toast(`删除失败：${err.message}`, "err"); }
      });
    });
    listBox.querySelectorAll("[data-pin-item]").forEach((node) => {
      node.addEventListener("click", async () => {
        try {
          await apiPost("wardrobe/pin", { item_id: node.dataset.pinItem, manual: node.dataset.manual !== "1" });
          toast("已更新标记");
          await renderWardrobe();
        } catch (err) { toast(`标记失败：${err.message}`, "err"); }
      });
    });
    pagerBox.querySelectorAll("[data-closet-page]").forEach((node) => {
      node.addEventListener("click", () => {
        state.wardrobePage = Math.max(0, Math.min(pages - 1, Number(node.dataset.closetPage) || 0));
        renderClosetPage();
      });
    });
  };
  renderClosetPage();
  // 生成预览（一次十件）：每次生成重置；每条独立「应用」/「删除」。
  // 预览放在全局 state（0.152 修复：点「应用」后整页重渲染不再导致其余预览消失）
  if (!Array.isArray(state.wardrobePreview)) state.wardrobePreview = [];
  let previewItems = state.wardrobePreview;
  const renderPreview = () => {
    const box = document.getElementById("gen-preview");
    if (!box) return;
    if (!previewItems.length) {
      box.innerHTML = '<div class="hint">（尚未生成——点上方「一次生成十件」）</div>';
      return;
    }
    box.innerHTML = previewItems.map((it, idx) => `
      <div style="display:flex;align-items:center;gap:8px;padding:3px 8px;margin:3px 0;border-left:2px solid var(--line);font-size:13px">
        <div style="flex:1;min-width:0">
          <div style="color:var(--ink);line-height:1.35">${esc(String(it.name || ""))}</div>
          <div class="hint" style="line-height:1.35;opacity:.75">${esc(String(it.category || ""))}${it.note ? " · " + esc(String(it.note)) : ""}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0">
          <button class="btn mini" data-apply-item="${idx}">应用</button>
          <button class="btn mini ghost-danger" data-remove-item="${idx}">删除</button>
        </div>
      </div>`).join("");
    box.querySelectorAll("[data-apply-item]").forEach((node) => {
      node.addEventListener("click", async () => {
        const idx = Number(node.dataset.applyItem);
        const item = previewItems[idx];
        if (!item) return;
        try {
          await apiPost("wardrobe/apply_batch", { items: [item] });
          state.wardrobePreview.splice(idx, 1);
          previewItems = state.wardrobePreview;
          renderPreview();
          toast(`已加入衣柜：${String(item.name || "").slice(0, 20)}`);
          await renderWardrobe();
        } catch (err) {
          toast(err.message || "应用失败（衣柜可能已满）", "err");
        }
      });
    });
    box.querySelectorAll("[data-remove-item]").forEach((node) => {
      node.addEventListener("click", () => {
        state.wardrobePreview.splice(Number(node.dataset.removeItem), 1);
        previewItems = state.wardrobePreview;
        renderPreview();
      });
    });
  };
  renderPreview(); // 从全局状态恢复（应用/删除/整页重渲染后预览不丢）
  const genBatchBtn = document.getElementById("gen-batch");
  if (genBatchBtn) genBatchBtn.addEventListener("click", async () => {
    try {
      await runWithBusy(genBatchBtn, "生成中…", async () => {
        const res = await apiPost("wardrobe/generate_batch", { count: 10 });
        state.wardrobePreview = (res && res.items) || [];
        previewItems = state.wardrobePreview;
        renderPreview();
      });
      toast(`已生成 ${previewItems.length} 件预览`);
    } catch (err) {
      toast(`生成失败：${err.message}`, "err");
      state.wardrobePreview = [];
      previewItems = state.wardrobePreview;
      renderPreview();
    }
  });
  const replaceAllBtn = document.getElementById("replace-all");
  if (replaceAllBtn) replaceAllBtn.addEventListener("click", async () => {
    const doReplace = async () => {
      try {
        await runWithBusy(replaceAllBtn, "置换中…", () => apiPost("wardrobe/replace_all", {}));
        toast("已置换衣柜（重要衣物保留）");
        await renderWardrobe();
      } catch (err) {
        toast(`置换失败：${err.message}`, "err");
      }
    };
    if (closet.length) {
      confirmDialog("一键置换衣柜", "将清空非重要衣物并重新生成 20 件（重要衣物的蓝/橙边线衣物保留），确定吗？", doReplace);
    } else {
      doReplace();
    }
  });
  const saveOutfitBtn = document.getElementById("save-outfit");
  if (saveOutfitBtn) saveOutfitBtn.addEventListener("click", async () => {
    const raw = document.getElementById("outfit-items").value;
    const items = raw.replace(/，/g, ",").replace(/、/g, ",").split(",").map((x) => x.trim()).filter(Boolean);
    const note = document.getElementById("outfit-note").value.trim();
    try {
      await apiPost("wardrobe/outfit", { items, note });
      toast("已保存");
    } catch (err) { toast(`保存失败：${err.message}`, "err"); }
  });
  const genOutfitBtn = document.getElementById("gen-outfit");
  if (genOutfitBtn) genOutfitBtn.addEventListener("click", async () => {
    try {
      await runWithBusy(genOutfitBtn, "生成中…", () => apiPost("wardrobe/generate", {}));
      toast("已生成穿搭并保存");
      await renderWardrobe();
    } catch (err) {
      toast(`生成失败：${err.message}`, "err");
    }
  });
  const addClosetBtn = document.getElementById("add-closet");
  if (addClosetBtn) addClosetBtn.addEventListener("click", async () => {
    const name = document.getElementById("new-closet-name").value.trim();
    const category = document.getElementById("new-closet-cat").value.trim();
    if (!name) { toast("请填衣物名称", "err"); return; }
    try {
      await apiPost("wardrobe/closet/add", { name, category });
      toast("已添加（重要）");
      await renderWardrobe();
    } catch (err) { toast(`添加失败：${err.message}`, "err"); }
  });
  await bindMasterSwitch("wardrobe-enabled", "wardrobe", "enabled");
  bindSettingsIn(view);
}

/* 内心页：梦境 / 思考 / 见闻 */
async function renderMind() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载内心世界…</div>`;
  let data, diaryData;
  try {
    data = await apiGet("mind");
    diaryData = await apiGet("diary");
  } catch (err) {
    if (state.current === "mind") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${err.message}</p></div>`;
    }
    return;
  }
  if (state.current !== "mind") return;

  const mindState = {
    data, diary: (diaryData.entries || []),
    viewMode: { dreams: "now", thoughts: "now" },  // now=只展示当前 | paged=分页(5/页)
  };
  const refresh = async () => {
    mindState.data = await apiGet("mind");
    mindState.diary = ((await apiGet("diary")).entries || []);
    render();
  };
  const renderList = (kind) => {
    const box = document.getElementById(`mind-list-${kind}`);
    if (!box) return;
    const items = mindState.data[kind] || [];
    const PAGE = 3;
    const mode = kind === "sightings" ? "paged" : (mindState.viewMode[kind] || "now");
    let page = mindState[`page_${kind}`] || 0;
    if (mode === "now") {
      if (!items.length) {
        box.innerHTML = `<div class="hint">还没有记录——点上方按钮生成，或等后台自动。</div>`;
      } else {
        const latest = items[0];
        box.innerHTML = `
          <div class="field mind-current" style="border-left:3px solid var(--glow-a);padding-left:10px">
            <div class="hint" style="color:var(--ink)">${esc(latest.text || "")}</div>
            <div class="hint" style="opacity:.55">${esc(latest.at || "")} · 共 ${items.length} 条，切换分页可回看</div>
          </div>`;
      }
      return;
    }
    const pages = Math.max(1, Math.ceil(items.length / PAGE));
    if (page >= pages) page = pages - 1;
    if (page < 0) page = 0;
    mindState[`page_${kind}`] = page;
    const slice = items.slice(page * PAGE, page * PAGE + PAGE);
    box.innerHTML = slice.length ? slice.map((it, idx) => `
      <div class="field">
        <div class="field-row" style="align-items:flex-start">
          <div style="flex:1;min-width:0">
            <div class="hint" style="color:var(--ink)">${esc(it.text || "")}</div>
            <div class="hint" style="opacity:.55">${esc(it.at || "")}</div>
          </div>
          <button class="btn" data-mind-del="${kind}:${page * PAGE + idx}" style="flex-shrink:0">删</button>
        </div>
      </div>`).join("") : '<div class="hint">还没有记录。</div>';
    const pager = document.getElementById(`mind-pager-${kind}`);
    if (pager) pager.innerHTML = pages > 1 ? `
      <div class="field-row" style="gap:6px;justify-content:space-between;margin-top:6px">
        <span class="hint" style="color:var(--ink)">第 ${page + 1}/${pages} 页 · 共 ${items.length} 条</span>
        <div style="display:flex;gap:6px">
          <button class="btn" data-mind-page="${kind}:${page - 1}" ${page === 0 ? "disabled" : ""}>‹ 上一页</button>
          <button class="btn" data-mind-page="${kind}:${page + 1}" ${page >= pages - 1 ? "disabled" : ""}>下一页 ›</button>
        </div>
      </div>` : "";
    box.querySelectorAll("[data-mind-del]").forEach((node) => {
      node.addEventListener("click", async () => {
        const [k, idx] = String(node.dataset.mindDel).split(":");
        try {
          await apiPost("mind/delete", { kind: k, index: Number(idx) });
          toast("已删除");
          await refresh();
        } catch (err) { toast(`删除失败：${err.message}`, "err"); }
      });
    });
    const pg = document.getElementById(`mind-pager-${kind}`);
    if (pg) pg.querySelectorAll("[data-mind-page]").forEach((node) => {
      node.addEventListener("click", () => {
        const [k, p] = String(node.dataset.mindPage).split(":");
        mindState[`page_${k}`] = Number(p) || 0;
        renderList(k);
      });
    });
  };
  const mindCard = (kind, title, subtitle, btnId, btnText) => `
    <section class="panel">
      <div class="panel-head">
        <div><h3 class="panel-title">${title}</h3><span class="hint">${subtitle}</span></div>
        <button class="btn" id="${btnId}" style="white-space:nowrap">${btnText}</button>
      </div>
      <div class="field-row" style="gap:6px;margin-bottom:8px">
        <div class="pill ${mindState.viewMode[kind] === "now" ? "active" : ""}" data-mind-mode="${kind}:now">只展示当前</div>
        <div class="pill ${mindState.viewMode[kind] === "paged" ? "active" : ""}" data-mind-mode="${kind}:paged">分页展示</div>
      </div>
      <div id="mind-list-${kind}"></div>
      <div id="mind-pager-${kind}"></div>
    </section>`;
  const cfgVal = (mod, key, fallback) => (((state.configValues || {})[mod] || {})[key] ?? fallback);
  const cfgItem = (mod, key, fallback) => (state.configSchema && state.configSchema[mod] && state.configSchema[mod].items && state.configSchema[mod].items[key]) || fallback;

  const render = () => {
    const d = mindState.diary;
    const diaryExpanded = !!mindState.diaryExpanded;
    const diaryVisible = Math.min(mindState.diaryPage || 0, Math.max(0, d.length - 1));
    const diaryEntryHtml = (e, i) => `
      <div class="diary-book-entry ${i === 0 ? "diary-today" : ""}">
        <div class="diary-date"><span class="diary-date-chip">${esc(e.date || "")}</span></div>
        <div class="diary-text">${esc(e.content || "")}</div>
      </div>`;
    // 日记本：默认只展示最新 1 篇；其余按「下一页/上一页」逐篇翻（不刷屏）；可展开全部
    const diaryHtml = d.length ? (diaryExpanded
      ? d.map(diaryEntryHtml).join("")
      : diaryEntryHtml(d[diaryVisible], diaryVisible))
      : '<div class="hint" style="padding:10px 0">还没有日记——深夜会自动写，也可以现在写一篇。</div>';
    const diaryMoreBtn = d.length > 1 ? `
      <button class="btn" id="mind-diary-more" style="margin-top:8px">${diaryExpanded ? "收起（只留最新一篇）" : `展开全部（共 ${d.length} 篇，历史仍保留）`}</button>` : "";
    const diaryPager = (!diaryExpanded && d.length > 1) ? `
      <div class="field-row" style="gap:6px;justify-content:space-between;margin-top:6px">
        <span class="hint" style="color:var(--ink)">第 ${diaryVisible + 1}/${d.length} 篇</span>
        <div style="display:flex;gap:6px">
          <button class="btn" data-diary-page="${diaryVisible - 1}" ${diaryVisible === 0 ? "disabled" : ""}>‹ 上一篇</button>
          <button class="btn" data-diary-page="${diaryVisible + 1}" ${diaryVisible >= d.length - 1 ? "disabled" : ""}>下一篇 ›</button>
        </div>
      </div>` : "";
    view.innerHTML = `
      ${placeholderHintCard("mind")}
      <div class="rel-layout" style="align-items:flex-start">
        <div class="rel-left" style="flex:0 0 300px">
          <section class="panel">
            <div class="panel-head">
              <div><h3 class="panel-title">见闻</h3><span class="hint">刷到的新鲜事</span></div>
              <button class="btn" id="mind-browse" style="white-space:nowrap">刷一刷</button>
            </div>
            <div id="mind-list-sightings"></div>
            <div class="field" style="margin-top:8px">
              <div class="field-title">搜一段新鲜事（手动）</div>
              <div class="field-row" style="gap:6px">
                <input class="input" id="mind-search-q" placeholder="关键词，如：AI 新闻" style="flex:1">
                <button class="btn glow" id="mind-search-btn" style="flex-shrink:0">搜一下</button>
              </div>
            </div>
            <div class="settings-grid" style="grid-template-columns:1fr;margin-top:8px">
              ${renderSettingField("search", "provider_id", cfgItem("search", "provider_id", { description: "搜索整理模型", type: "string", role: "provider", default: "" }), cfgVal("search", "provider_id", ""))}
              ${renderSettingField("search", "browse_enabled", cfgItem("search", "browse_enabled", { description: "自主浏览（无聊自己刷）", type: "bool", default: true }), cfgVal("search", "browse_enabled", true))}
              ${renderSettingField("search", "browse_interval_hours", cfgItem("search", "browse_interval_hours", { description: "自主间隔(小时)", type: "int", default: 6 }), cfgVal("search", "browse_interval_hours", 6))}
              ${renderSettingField("search", "engine", cfgItem("search", "engine", { description: "搜索引擎", type: "string", options: ["tavily", "bing"], default: "tavily" }), cfgVal("search", "engine", "tavily"))}
              ${renderSettingField("search", "api_key", cfgItem("search", "api_key", { description: "API Key", type: "string", default: "" }), cfgVal("search", "api_key", ""))}
              ${renderSettingField("search", "result_count", cfgItem("search", "result_count", { description: "结果数", type: "int", default: 3 }), cfgVal("search", "result_count", 3))}
              ${renderSettingField("search", "enabled", cfgItem("search", "enabled", { description: "搜索开关", type: "bool", default: false }), cfgVal("search", "enabled", false))}
              ${!String(cfgVal("search", "api_key", "") || "").trim() && String(cfgVal("search", "engine", "") || "tavily") !== "bing" ? `<div class="hint" style="margin-top:8px;color:#f97316;font-weight:700">⚠ 未配置 API Key：自主浏览（见闻）与手动搜索不会真正执行（Tavily 引擎必须有 key，空 key 会静默失败）——请填入 Tavily API Key，或把引擎改为 Bing（可尝试无 key）。</div>` : ""}
            </div>
          </section>
        </div>
        <div class="rel-center" style="flex:1;min-width:0">
          ${mindCard("dreams", "梦境", "深夜偶尔做的一段长梦", "mind-dream-gen", "生成梦境")}
          <div style="height:16px"></div>
          ${mindCard("thoughts", "思考", "闲时冒出的念头", "mind-think-gen", "冒个念头")}
          <div style="height:16px"></div>
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3 class="panel-title">日记本</h3>
                <span class="hint">每天一篇，记录这一天的她${d.length ? ` · 已存 ${d.length} 篇` : ""}</span>
              </div>
              <button class="btn" id="mind-diary-gen" style="white-space:nowrap">写一篇</button>
            </div>
            <div class="diary-book">${diaryHtml}</div>
            ${diaryPager}
            ${diaryMoreBtn}
          </section>
        </div>
        <div class="rel-right" style="flex:0 0 300px">
          <section class="panel">
            <div class="panel-head"><h3 class="panel-title">内心设置</h3></div>
            <div class="settings-grid" style="grid-template-columns:1fr">
              ${renderSettingField("mind", "enabled", cfgItem("mind", "enabled", { description: "内心模块总开关", type: "bool", default: true }), cfgVal("mind", "enabled", true))}
              ${renderSettingField("mind", "dream_provider_id", cfgItem("mind", "dream_provider_id", { description: "梦境模型", type: "string", role: "provider", default: "" }), cfgVal("mind", "dream_provider_id", ""))}
              ${renderSettingField("mind", "diary_provider_id", cfgItem("mind", "diary_provider_id", { description: "日记模型", type: "string", role: "provider", default: "" }), cfgVal("mind", "diary_provider_id", ""))}
              ${renderSettingField("mind", "think_provider_id", cfgItem("mind", "think_provider_id", { description: "思考模型", type: "string", role: "provider", default: "" }), cfgVal("mind", "think_provider_id", ""))}
              ${renderSettingField("mind", "think_daily_limit", cfgItem("mind", "think_daily_limit", { description: "每天思考次数上限", type: "int", default: 7 }), cfgVal("mind", "think_daily_limit", 7))}
              ${renderSettingField("mind", "think_interval_minutes", cfgItem("mind", "think_interval_minutes", { description: "思考最小间隔(分钟)", type: "int", default: 60 }), cfgVal("mind", "think_interval_minutes", 60))}
            </div>
          </section>
        </div>
      </div>
      <section class="panel" style="margin-top:16px">
        <div class="section-head" style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <h2 class="section-title">发给日记 LLM 的内容</h2>
            <p class="section-desc">「写日记」实际发送给日记模型的完整提示词与素材（只读预览，零 Token）。</p>
          </div>
          <button class="btn" id="diary-preview-btn">查看 / 刷新</button>
        </div>
        <div id="diary-preview-out" class="hint">（点击查看）</div>
      </section>
    `;
    bindSettingsIn(view);
    renderList("dreams");
    renderList("thoughts");
    renderList("sightings");
    // 展示模式切换：只展示当前 ⇄ 分页展示
    view.querySelectorAll("[data-mind-mode]").forEach((node) => {
      node.addEventListener("click", () => {
        const [kind, mode] = String(node.dataset.mindMode).split(":");
        mindState.viewMode[kind] = mode;
        render();
      });
    });
    // 见闻删除（renderList("sightings") 会渲染列表，这里补删除绑定）
    const sightBox = document.getElementById("mind-list-sightings");
    if (sightBox) sightBox.addEventListener("click", async (ev) => {
      const del = ev.target.closest("[data-mind-del]");
      if (!del) return;
      const [kind, idx] = String(del.dataset.mindDel).split(":");
      try {
        await apiPost("mind/delete", { kind, index: Number(idx) });
        toast("已删除");
        await refresh();
      } catch (err) { toast(`删除失败：${err.message}`, "err"); }
    });
    const bindGen = (id, kind) => {
      const btn = document.getElementById(id);
      if (btn) btn.addEventListener("click", async () => {
        try {
          await runWithBusy(btn, "生成中…", () => apiPost("mind/generate", { kind }));
          toast(kind === "diary" ? "日记已生成" : "已生成");
          await refresh();
        } catch (err) { toast(`生成失败：${err.message}`, "err"); }
      });
    };
    bindGen("mind-dream-gen", "dream");
    bindGen("mind-think-gen", "think");
    bindGen("mind-diary-gen", "diary");
    const diaryMore = document.getElementById("mind-diary-more");
    if (diaryMore) diaryMore.addEventListener("click", () => {
      mindState.diaryExpanded = !mindState.diaryExpanded;
      render();
    });
    view.querySelectorAll("[data-diary-page]").forEach((node) => {
      node.addEventListener("click", () => {
        mindState.diaryPage = Math.max(0, Number(node.dataset.diaryPage) || 0);
        render();
      });
    });
    // 日记提示词预览（只读，零 Token）
    const diaryPvBtn = document.getElementById("diary-preview-btn");
    if (diaryPvBtn) diaryPvBtn.addEventListener("click", async () => {
      diaryPvBtn.disabled = true;
      try {
        const res = await apiGet("diary/prompt_preview");
        const out = document.getElementById("diary-preview-out");
        if (out) {
          out.innerHTML = `
            <div class="hint" style="margin-bottom:6px">将发送给模型：<b>${esc(res.model || "-")}</b> · 共 ${res.length || 0} 字符</div>
            <pre class="panel" style="white-space:pre-wrap;word-break:break-word;font-size:12.5px;line-height:1.7;padding:12px;max-height:280px;overflow:auto;margin:0">${esc(res.prompt || "")}</pre>`;
        }
      } catch (err) { toast(`预览失败：${err.message}`, "err"); }
      diaryPvBtn.disabled = false;
    });
    const browseBtn = document.getElementById("mind-browse");
    if (browseBtn) browseBtn.addEventListener("click", async () => {
      try {
        await runWithBusy(browseBtn, "搜一下…", () => apiPost("mind/search", { query: "最近有什么新鲜事" }));
        toast("已更新见闻");
        await refresh();
      } catch (err) { toast(`搜索失败：${err.message}`, "err"); }
    });
    const searchBtn = document.getElementById("mind-search-btn");
    const searchQ = document.getElementById("mind-search-q");
    if (searchBtn && searchQ) searchBtn.addEventListener("click", async () => {
      const q = searchQ.value.trim();
      if (!q) { toast("请先输入关键词", "err"); return; }
      searchBtn.disabled = true;
      try {
        await apiPost("mind/search", { query: q });
        toast("已保存见闻");
        await refresh();
      } catch (err) { toast(`搜索失败：${err.message}`, "err"); }
      finally { searchBtn.disabled = false; }
    });
  };
  render();
}

/* 记忆页：长期记忆（联动【为你篆刻的历史】插件，只读可视化） */
async function renderMemory() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载记忆…</div>`;
  let data;
  try {
    data = await apiGet("memory");
  } catch (err) {
    if (state.current === "memory") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "memory") return;
  const items = (list) => (list && list.length)
    ? list.map((it) => `
        <div class="field">
          <div class="hint" style="color:var(--ink)">${esc(it.text || "")}</div>
          <div class="hint" style="opacity:.55">${esc(it.type || it.at ? `（${esc(it.type || "记忆")}${it.at ? " · " + esc(it.at) : ""}）` : "")}</div>
        </div>`).join("")
    : '<div class="hint">还没有记录——对话中的约定/愿望会沉淀到这里。</div>';
  // 时间线条目：角色徽标 + 会话标注 + 时间 + 角色色条
  const tlineMeta = (it) => {
    const role = String(it.role || "");
    const isOp = it.kind === "op";
    if (isOp) return { label: "操作", cls: "tline-op", who: it.user || "记忆库" };
    if (role === "bot") return { label: "Bot", cls: "tline-bot", who: "你（Bot）" };
    if (role === "system" || it.system) return { label: "系统", cls: "tline-sys", who: it.user || "系统" };
    if (role === "user") return { label: "用户", cls: "tline-user", who: it.user || "私聊对方" };
    if (role === "group_member") return { label: "群成员", cls: "tline-member", who: it.user || "群成员" };
    return { label: "成员", cls: "tline-member", who: it.user || it.user || "" };
  };
  const tlineWhere = (it) => it.scope === "group" ? (it.group ? `群聊 ${it.group}` : "群聊") : "私聊";
  const tlineAt = (it) => String(it.at || "").replace("T", " ").slice(5, 16);
  const tlineItems = (list) => (list && list.length) ? list.map((it) => {
    const meta = tlineMeta(it);
    return `
      <div class="field tline-item ${meta.cls}">
        <div class="field-row" style="gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-start">
          <span class="tline-badge ${meta.cls}">${esc(meta.label)}</span>
          <span class="hint" style="color:var(--ink)">${esc(meta.who)}</span>
          <span class="hint">${esc(tlineWhere(it))}</span>
          <span class="hint" style="opacity:.6">${esc(tlineAt(it))}</span>
        </div>
        <div class="tline-text">${esc(it.text || "")}</div>
      </div>`;
  }).join("") : '<div class="hint">还没有时间线条目。</div>';
  const cfgVal = (k, fb) => (((state.configValues || {}).memory || {})[k] ?? fb);
  const cfgItem = (k, fb) => (state.configSchema && state.configSchema.memory && state.configSchema.memory.items && state.configSchema.memory.items[k]) || fb;
  const linkageCls = data.available ? "block-success" : ((data.reason || "").includes("协同桥接") ? "block-blocked" : "block-failed");
  const linkageLabel = data.available ? "联动正常" : ((data.reason || "").includes("协同桥接") ? "桥接未开启" : "未检测到插件");
  const tlineAll = data.timeline || [];
  const tlinePages = Math.max(1, Math.ceil(tlineAll.length / TL_PAGE_SIZE));
  state.memoryTlinePage = Math.min(state.memoryTlinePage, tlinePages);
  const tlinePageItems = pageSlice(tlineAll, state.memoryTlinePage, TL_PAGE_SIZE);
  view.innerHTML = `
    ${placeholderHintCard("memory")}
    <section class="panel" style="margin-bottom:12px">
      <div class="panel-head">
        <h3 class="panel-title">联动状态</h3>
        <span class="outcome-block ${linkageCls}">${linkageLabel}</span>
        <button class="btn mini" data-pro-test-link style="margin-left:auto">检测联动</button>
      </div>
      <p class="section-desc">${esc(data.reason || data.note || "检测中…")}</p>
      ${data.detail ? `<div class="hint" style="opacity:.6;word-break:break-all">${esc(data.detail)}</div>` : ""}
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">最近记忆</h3><span class="hint">${data.available ? "来自【为你篆刻的历史】" : "未联动"}</span></div>
          ${data.available ? items(data.memories) : `<div class="hint">${esc(data.note || "未安装记忆插件")}</div>`}
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">近期时间线</h3><span class="hint">${tlineAll.length} 条 · 每页 ${TL_PAGE_SIZE} 条</span></div>
          ${data.available ? tlineItems(tlinePageItems) : `<div class="hint">${esc(data.note || "未安装记忆插件")}</div>`}
          ${pagerBar("memory-tline-pager", tlineAll.length, state.memoryTlinePage, TL_PAGE_SIZE)}
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">记忆联动设置</h3></div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("memory", "managed_injection", cfgItem("managed_injection", { description: "记忆托管注入", type: "bool", default: true }), cfgVal("managed_injection", true))}
            ${renderSettingField("memory", "commitment_enabled", cfgItem("commitment_enabled", { description: "约定提取", type: "bool", default: true }), cfgVal("commitment_enabled", true))}
            ${renderSettingField("memory", "profile_enabled", cfgItem("profile_enabled", { description: "画像采集", type: "bool", default: true }), cfgVal("profile_enabled", true))}
            ${renderSettingField("memory", "embedding_provider_id", cfgItem("embedding_provider_id", { description: "嵌入模型", type: "string", role: "provider", default: "" }), cfgVal("embedding_provider_id", ""))}
            ${renderSettingField("memory", "profile_provider_id", cfgItem("profile_provider_id", { description: "画像模型", type: "string", role: "provider", default: "" }), cfgVal("profile_provider_id", ""))}
            ${renderSettingField("memory", "commitment_provider_id", cfgItem("commitment_provider_id", { description: "约定模型", type: "string", role: "provider", default: "" }), cfgVal("commitment_provider_id", ""))}
          </div>
          <div class="rel-setting-note"><b>{记忆}</b> 占位符 = 从这里取：放行时由记忆插件注入；接管时本插件用 compose_injection 生成完整记忆包。未检测到【为你篆刻的历史】（或桥接未开启）时占位符留空，不影响其它模块。</div>
        </section>
      </div>
    </div>
  `;
  bindSettingsIn(view);
  bindPager("memory-tline-pager", tlineAll.length, (p) => { state.memoryTlinePage = p; }, () => renderMemory(), TL_PAGE_SIZE);
  const testBtn = view.querySelector("[data-pro-test-link]");
  if (testBtn) {
    testBtn.addEventListener("click", () => {
      testBtn.disabled = true;
      testBtn.textContent = "检测中…";
      apiGet("memory").then((d) => {
        if (state.current === "memory") renderMemory();
      }).catch(() => {
        testBtn.disabled = false;
        testBtn.textContent = "检测失败，重试";
      });
    });
  }
}

/* 主动页：三栏（已发送时间线 / 候选判定 / 用户卡+设置），含试发预览 */
async function renderProactive() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载主动对话…</div>`;
  let data;
  try {
    data = await apiGet("proactive/status");
  } catch (err) {
    if (state.current === "proactive") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "proactive") return;
  const outcomeLabel = {
    sent: "已发送", silent: "沉默（没想说的）", blocked: "被边界拦截",
    thinking: "生成中", send_failed: "发送失败",
  };
  const sourceMeta = {
    mood: { label: "心情", cls: "src-mood" },
    activity: { label: "日程", cls: "src-act" },
    memory: { label: "记忆", cls: "src-mem" },
    timeline: { label: "未完话题", cls: "src-timeline" },
    search: { label: "见闻", cls: "src-search" },
    dream: { label: "梦", cls: "src-dream" },
  };
  const srcChip = (key) => sourceMeta[key]
    ? `<span class="src-chip ${sourceMeta[key].cls}">${sourceMeta[key].label}</span>` : "";
  // 通用分页：切片 + 页码条（5 条/页，换页按钮明显）
  const pagerHtml = (pageKey, total, cur) => {
    const pages = Math.max(1, Math.ceil(total / 5));
    if (pages <= 1) return "";
    return `
      <div class="field-row" style="gap:6px;justify-content:space-between;align-items:center;margin-top:8px">
        <span class="hint" style="color:var(--ink)">第 ${cur + 1}/${pages} 页 · 共 ${total} 条</span>
        <div style="display:flex;gap:6px">
          <button class="btn" data-pro-page="${pageKey}:${cur - 1}" ${cur === 0 ? "disabled" : ""}>‹ 上一页</button>
          <button class="btn" data-pro-page="${pageKey}:${cur + 1}" ${cur >= pages - 1 ? "disabled" : ""}>下一页 ›</button>
        </div>
      </div>`;
  };
  const proPage = {
    cand: state.proCandPage || 0,
    done: state.proDonePage || 0,
    fail: state.proFailPage || 0,
    user: state.proUserPage || 0,
  };
  // 已发送时间线（数组，模板切片分页）
  const candArr = (data.candidates || []);
  const failArr = candArr.filter((c) => ["send_failed", "blocked", "silent", "timeout"].includes(c.outcome));
  const sentArr = (data.sent_history || []);
  const sentRowsOf = (h) => `
    <div class="setting-card" style="padding:10px 12px">
      <div class="hint" style="color:var(--ink)">「${esc(h.text || "")}」</div>
      <div class="hint" style="opacity:.55">${esc(h.user)} · ${esc(h.at || "")}</div>
    </div>`;
  // 候选判定记录（来源染色）→ 数组，模板切片分页
  // 状态色块标注
  const outcomeBlock = {
    sent: "block-success", send_failed: "block-failed", silent: "block-silent",
    blocked: "block-blocked", thinking: "block-thinking",
  };
  const candRows = candArr.map((c) => {
    const s = c.sources || {};
    const chips = ["mood", "activity", "memory", "timeline", "search", "dream"]
      .filter((k) => s[k]).map(srcChip).join("");
    // 消息记录式：结果标注 → 内容（说了什么）→ 时间 → （未发时）原因
    const isSent = c.outcome === "sent";
    return `
      <div class="setting-card" style="padding:12px 14px">
        <div class="field-row" style="gap:8px;align-items:flex-start">
          <div style="flex:1;min-width:0">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
              <span class="outcome-block ${outcomeBlock[c.outcome] || ""}">${outcomeLabel[c.outcome] || c.outcome}</span>
              ${isSent ? "" : `<span class="hint" style="font-weight:700">${esc(c.reason || "")}</span>`}
            </div>
            ${c.text ? `<div class="hint" style="color:var(--ink);font-size:15px">「${esc(c.text)}」</div>` : (isSent ? "" : `<div class="hint" style="color:var(--ink)">（未发送）</div>`)}
            <div class="hint" style="opacity:.6;margin-top:6px">${esc(c.time || "")} · 素材：${chips || "无"}</div>
          </div>
        </div>
      </div>`;
  });
  // 报错汇报台：只记录未成功发送（失败/拦截/沉默/超时）→ 数组，模板切片分页
  const failRows = failArr.map((c) => `
    <div class="setting-card" style="padding:10px 12px;border-left:3px solid #ef4444">
      <div class="field-row" style="gap:8px;align-items:flex-start">
        <div style="flex:1;min-width:0">
          <div style="display:flex;gap:8px;align-items:center">
            <span class="hint" style="color:#ef4444;font-weight:700">${outcomeLabel[c.outcome] || c.outcome}</span>
            <span class="hint" style="color:var(--ink)">${esc(c.reason || "")}</span>
          </div>
          ${c.text ? `<div class="hint" style="opacity:.7;margin-top:4px">「${esc(c.text)}」</div>` : ""}
        </div>
        <span class="hint" style="flex-shrink:0">${esc(c.time || "")}</span>
      </div>
    </div>`);
  // 用户卡
  const targets = (data.target_users || []);
  const userCards = Object.keys(data.per_user || {}).map((u) => {
    const info = data.per_user[u] || {};
    const lastS = info.last_sent ? `上次 ${esc(info.last_sent)}（${(info.seconds_ago || 0) / 3600 | 0}h${Math.round(((info.seconds_ago || 0) % 3600) / 60)}m 前）` : "从未发送";
    const lastI = info.last_interaction ? `最近回应 ${esc(info.last_interaction)}` : "暂无回应记录";
    return `
      <div class="field">
        <div class="field-row" style="align-items:flex-start">
          <div style="flex:1;min-width:0">
            <div class="field-title">${esc(u)}</div>
            <div class="hint">${lastS}</div>
            <div class="hint">${lastI}</div>
            <div class="hint">今日已主动 <b>${info.today_sent || 0}</b> 条</div>
            <div class="hint">${info.streak ? `连续未回应 <b>${info.streak}</b> 次 · ` : ""}温度：<b style="color:${info.temperature === "偏冷" ? "#6b7280" : info.temperature === "温热" ? "var(--glow-a)" : "var(--ink)"}">${esc(info.temperature)}</b>${info.silenced ? " · <span style='color:#f59e0b'>已静默（等对方先开口）</span>" : ""}</div>
            ${info.temperature_detail ? `<div class="hint" style="opacity:.6">${esc(info.temperature_detail)}</div>` : ""}
          </div>
          <button class="btn" data-pro-target-del="${esc(u)}" style="flex-shrink:0">删</button>
        </div>
      </div>`;
  }).join("");
  // 节奏可视化（后端提供 quiet_now / max_daily）
  const qh = String(data.quiet_hours || "23:00-08:30");
  const maxDaily = Number(data.max_daily ?? 3);
  const rhythmBar = `
    <div class="setting-card" style="padding:10px 12px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <span class="hint" style="color:var(--ink);font-weight:700">今日已发 <b style="color:var(--glow-a)">${data.daily_count || 0}</b>/${maxDaily === 0 ? "不限" : maxDaily}</span>
      <span class="hint" style="color:${data.quiet_now ? "#f59e0b" : "var(--glow-a)"};font-weight:700">${data.quiet_now ? `⏸ 免打扰中（${esc(qh)}）` : `✓ 可发时段 · 免打扰 ${esc(qh)}`}</span>
    </div>`;
  view.innerHTML = `
    <section class="section">
      ${masterSwitch("proactive-enabled", "主动对话", "Bot 主动找你聊天：由状态/日程/记忆/梦取材，克制打扰。", data.enabled)}
      <div class="section-head">
        <h2 class="section-title">主动对话</h2>
        <p class="section-desc">由状态/日程/记忆/梦境余波取材，克制打扰（宁可不说也不说废话）。</p>
      </div>
      <div class="field-row" style="gap:8px;flex-wrap:wrap">
        <span class="hint" style="color:var(--ink)">后台循环 ${data.loop_running ? "运行中" : "未运行"}</span>
        <span class="hint">间隔 ${data.min_interval_hours}~${data.max_interval_hours} 小时</span>
        ${rhythmBar}
        <button class="btn glow" id="pro-trigger" style="font-weight:700">▶ 立即尝试一次</button>
        <button class="btn glow" id="pro-preview">试发预览（不发送）</button>
      </div>
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">已发送消息</h3><span class="hint">${sentArr.length} 条</span></div>
          ${sentArr.slice(proPage.done * 5, proPage.done * 5 + 5).map(sentRowsOf).join("") || '<div class="hint">还没有主动发送过。</div>'}
          ${pagerHtml("done", sentArr.length, proPage.done)}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">目标用户</h3><span class="hint">${targets.length} 人</span></div>
          <div class="field-row" style="gap:6px;margin-bottom:8px">
            <input class="input" id="pro-target-input" placeholder="QQ 号，如 123456" style="flex:1;min-width:0">
            <button class="btn glow" id="pro-target-add" style="flex-shrink:0">添加</button>
          </div>
          ${userCards || '<div class="hint">还没有目标用户——上面输入 QQ 号点「添加」。</div>'}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">未回应动态与心情</h3></div>
          <div class="hint" style="margin-bottom:6px">连续未回应：间隔拉长 → 措辞放轻 → 静默闸门 → 心情微降；对方回复后全部归位、心情回升。</div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("proactive", "mood_link", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.mood_link) || { description: "未回应→心情联动", type: "bool", default: true }, ((state.configValues || {}).proactive || {}).mood_link)}
            ${renderSettingField("proactive", "mood_down_streak", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.mood_down_streak) || { description: "心情微降·未回应次数", type: "int", default: 2 }, ((state.configValues || {}).proactive || {}).mood_down_streak)}
            ${renderSettingField("proactive", "unanswered_slowdown_start", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.unanswered_slowdown_start) || { description: "未回应放大起步(次)", type: "int", default: 2 }, ((state.configValues || {}).proactive || {}).unanswered_slowdown_start)}
            ${renderSettingField("proactive", "unanswered_max_interval_multiplier", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.unanswered_max_interval_multiplier) || { description: "未回应间隔放大封顶(倍)", type: "float", default: 2.2 }, ((state.configValues || {}).proactive || {}).unanswered_max_interval_multiplier)}
            ${renderSettingField("proactive", "silent_after_streak", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.silent_after_streak) || { description: "静默闸门·未回应次数", type: "int", default: 3 }, ((state.configValues || {}).proactive || {}).silent_after_streak)}
            ${renderSettingField("proactive", "silent_after_hours", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.silent_after_hours) || { description: "静默闸门·悬置小时数", type: "float", default: 24 }, ((state.configValues || {}).proactive || {}).silent_after_hours)}
          </div>
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">候选判定记录</h3><span class="hint">${candArr.length} 条</span></div>
          ${candRows.slice(proPage.cand * 5, proPage.cand * 5 + 5).join("") || '<div class="hint">还没有尝试记录（后台循环会在间隔后自动尝试）。</div>'}
          ${pagerHtml("cand", candArr.length, proPage.cand)}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">报错汇报台</h3><span class="hint">只记未发送成的（${failArr.length} 条）</span></div>
          ${failRows.slice(proPage.fail * 5, proPage.fail * 5 + 5).join("") || '<div class="hint">暂无报错——最近没有未发送成功的主动消息。</div>'}
          ${pagerHtml("fail", failArr.length, proPage.fail)}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">主动模板与发送预览</h3></div>
          <div class="hint" style="margin-bottom:6px">占位符：${["{由头}", "{心情}", "{日程}", "{记忆}", "{未完成}", "{见闻}", "{梦}", "{时间}"].map((p) => `<span class="ph-hint-chip">${esc(p)}</span>`).join(" ")} · 留空=用内置默认（两级裁决：值不值得发→自然表达）</div>
          <textarea class="input" id="pro-template" rows="5" placeholder="留空=用内置默认（两级裁决：值不值得发→自然表达）">${esc(((state.configValues || {}).proactive || {}).template || "")}</textarea>
          <div class="field-row" style="gap:8px;margin-top:8px;flex-wrap:wrap">
            <button class="btn glow" id="pro-template-save">保存模板</button>
            <button class="btn" id="pro-prompt-view" style="white-space:nowrap">查看实际发送的完整提示词</button>
          </div>
          <div id="pro-prompt-out" class="hint" style="margin-top:8px">（点击上方按钮查看实际发送给主动模型 LLM 的内容，只读预览，零 Token）</div>
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">主动设置 · 节奏与边界</h3></div>
          <div class="hint" style="margin-bottom:6px">发什么时机、发给谁、是否落历史。未回应相关参数见左栏「未回应动态与心情」。</div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("proactive", "provider_id", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.provider_id) || { description: "主动生成模型", type: "string", role: "provider", default: "" }, ((state.configValues || {}).proactive || {}).provider_id)}
            ${renderSettingField("proactive", "min_interval_hours", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.min_interval_hours) || { description: "最短间隔(小时)", type: "float", default: 4 }, ((state.configValues || {}).proactive || {}).min_interval_hours)}
            ${renderSettingField("proactive", "max_interval_hours", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.max_interval_hours) || { description: "最长间隔(小时)", type: "float", default: 8 }, ((state.configValues || {}).proactive || {}).max_interval_hours)}
            ${renderSettingField("proactive", "max_daily", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.max_daily) || { description: "每日上限(条)", type: "int", default: 3 }, ((state.configValues || {}).proactive || {}).max_daily)}
            ${renderSettingField("proactive", "quiet_hours", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.quiet_hours) || { description: "免打扰时段", type: "string", default: "23:00-08:30" }, ((state.configValues || {}).proactive || {}).quiet_hours)}
            ${renderSettingField("proactive", "cooldown_after_chat_minutes", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.cooldown_after_chat_minutes) || { description: "刚聊完顺延(分钟)", type: "int", default: 30 }, ((state.configValues || {}).proactive || {}).cooldown_after_chat_minutes)}
            ${(function () {
              // 0.176：消息平台前缀改为「已连接平台」下拉（数据源 proactive/status.connected_platforms），
              // 不再只能手填；发送失败时后端会自动诊断/单平台回退。
              const cur = String(((state.configValues || {}).proactive || {}).session_platform ?? "");
              const platforms = (data && data.connected_platforms) || [];
              if (platforms.length) {
                const opts = platforms.map((p) =>
                  `<option value="${esc(p.id)}" ${String(p.id) === cur ? "selected" : ""}>${esc(p.id)}${p.name ? `（${esc(p.name)}）` : ""}</option>`
                ).join("");
                const extra = platforms.some((p) => String(p.id) === cur) ? "" :
                  `<option value="${esc(cur)}" selected>${esc(cur) || "（未设置）"}</option>`;
                return `<div class="setting-card"><div class="field">
                  <div class="field-title">消息平台前缀<span class="field-key">session_platform</span></div>
                  <div class="hint">默认 QQ（aiocqhttp）。选项来自当前 AstrBot 已连接适配器；若目标会话属于其它平台（如 Telethon / QQ 官方 API），请在 AstrBot 连接后再选对应平台，发送失败时插件也会自动诊断并提示。</div>
                  <select class="input" data-setting="proactive.session_platform" data-type="text">${extra}${opts}</select>
                </div></div>`;
              }
              return renderSettingField("proactive", "session_platform", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.session_platform) || { description: "消息平台(默认 QQ)", type: "string", default: "aiocqhttp" }, ((state.configValues || {}).proactive || {}).session_platform);
            })()}
            ${renderSettingField("proactive", "archive_history", (state.configSchema && state.configSchema.proactive && state.configSchema.proactive.items && state.configSchema.proactive.items.archive_history) || { description: "写入会话历史", type: "bool", default: true }, ((state.configValues || {}).proactive || {}).archive_history)}
          </div>
        </section>
      </div>
    </div>
  `;
  bindSettingsIn(view);
  await bindMasterSwitch("proactive-enabled", "proactive", "enabled");
  const btn = document.getElementById("pro-trigger");
  if (btn) btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await apiPost("proactive/trigger", {});
      toast("已尝试发送，稍等结果…");
      await renderProactive();
      // 异步生成：轮询几次直到出现「沉默/已发送/失败」等终态，自动刷新
      let tries = 0;
      const poll = setInterval(async () => {
        tries += 1;
        try {
          const fresh = await apiGet("proactive/status");
          const last = (fresh.candidates || [])[0];
          const done = last && ["sent", "silent", "send_failed", "blocked"].includes(last.outcome);
          if (done || tries >= 6) {
            clearInterval(poll);
            await renderProactive();
          } else {
            await renderProactive();
          }
        } catch (err) { clearInterval(poll); }
      }, 1200);
    } catch (err) { toast(`触发失败：${err.message}`, "err"); }
    btn.disabled = false;
  });
  const pvBtn = document.getElementById("pro-preview");
  if (pvBtn) pvBtn.addEventListener("click", async () => {
    pvBtn.disabled = true;
    try {
      const res = await apiPost("proactive/preview", {});
      const s = res.sources || {};
      const chips = ["mood", "activity", "memory", "timeline", "search", "dream"].filter((k) => s[k]).map(srcChip).join("");
      const box = document.createElement("div");
      box.className = "setting-card";
      box.style.cssText = "margin-top:10px";
      box.innerHTML = `
        <div class="field-title">试发预览</div>
        <div class="hint">${res.should_send ? "✅ 当前意愿" : "⚠️ 当前不会发"}：${esc(res.reason || "")}</div>
        <div class="hint">${chips} ${Object.keys(s).filter((k) => s[k]).length} 路素材</div>
        ${res.text ? `<div class="hint" style="color:var(--ink)">「${esc(res.text)}」</div>` : "<div class='hint'>（没有自然想说的话）</div>"}
      `;
      const prev = document.getElementById("pro-preview-out");
      if (prev) prev.replaceWith(box); else pvBtn.insertAdjacentElement("afterend", box);
      box.id = "pro-preview-out";
    } catch (err) { toast(`预览失败：${err.message}`, "err"); }
    pvBtn.disabled = false;
  });
  // 目标用户增删
  const proAdd = document.getElementById("pro-target-add");
  const proInput = document.getElementById("pro-target-input");
  if (proAdd && proInput) proAdd.addEventListener("click", async () => {
    const v = proInput.value.trim();
    if (!v) { toast("请输入 QQ 号", "err"); return; }
    try {
      await apiPost("proactive/targets", { action: "add", id: v });
      toast("已添加");
      await renderProactive();
    } catch (err) { toast(`添加失败：${err.message}`, "err"); }
  });
  // 主动模板保存
  const tplSave = document.getElementById("pro-template-save");
  if (tplSave) tplSave.addEventListener("click", async () => {
    const val = document.getElementById("pro-template").value;
    try {
      await apiPost("config/module/update", { module: "proactive", values: { template: val } });
      toast("模板已保存");
      await reloadConfig();
    } catch (err) { toast(`保存失败：${err.message}`, "err"); }
  });
  // 提示词预览（只读）
  const promptView = document.getElementById("pro-prompt-view");
  if (promptView) promptView.addEventListener("click", async () => {
    promptView.disabled = true;
    try {
      const res = await apiGet("proactive/prompt_preview");
      const out = document.getElementById("pro-prompt-out");
      if (out) {
        out.innerHTML = `
          <div class="hint" style="margin-bottom:6px">将发送给模型：<b>${esc(res.model || "-")}</b> · ${res.length || 0} 字符${res.template_set ? " · 使用自定义模板" : " · 使用内置默认"}</div>
          <pre class="panel" style="white-space:pre-wrap;word-break:break-word;font-size:12.5px;line-height:1.7;padding:12px;max-height:300px;overflow:auto;margin:0">${esc(res.prompt || "")}</pre>`;
      }
    } catch (err) { toast(`预览失败：${err.message}`, "err"); }
    promptView.disabled = false;
  });
  // 分页按钮（候选/已发送/报错台：5 条/页）
  view.querySelectorAll("[data-pro-page]").forEach((node) => {
    node.addEventListener("click", () => {
      const [key, p] = String(node.dataset.proPage).split(":");
      const map = { cand: "proCandPage", done: "proDonePage", fail: "proFailPage" };
      state[map[key]] = Math.max(0, Number(p) || 0);
      renderProactive();
    });
  });
  view.querySelectorAll("[data-pro-target-del]").forEach((node) => {    node.addEventListener("click", async () => {
      try {
        await apiPost("proactive/targets", { action: "remove", id: node.dataset.proTargetDel });
        toast("已删除");
        await renderProactive();
      } catch (err) { toast(`删除失败：${err.message}`, "err"); }
    });
  });
}

/* 发送页：发送缓冲与「被抢话」裁决（队列与记录分页，每页 PAGE_SIZE 条） */
async function renderSend() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载发送状态…</div>`;
  let data;
  try {
    data = await apiGet("send/status");
  } catch (err) {
    if (state.current === "send") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "send") return;
  const queues = data.queues || {};
  const records = data.records || [];
  const interrupted = data.interrupted || {};
  const schema = state.configSchema || {};
  const values = state.configValues || {};
  const sendItems = (schema.send && schema.send.items) || {};
  const cfg = (k, fb) => ((values.send || {})[k] ?? fb);
  // 待发送队列：展平为条目（会话 + 条序号）
  const queueItems = [];
  Object.keys(queues).forEach((sid) => {
    (queues[sid] || []).forEach((q, idx) => {
      queueItems.push({ sid, idx: idx + 1, text: q.text, sent: q.sent });
    });
  });
  const queuePages = Math.max(1, Math.ceil(queueItems.length / PAGE_SIZE));
  state.sendQueuePage = Math.min(state.sendQueuePage, queuePages);
  const recordPages = Math.max(1, Math.ceil(records.length / PAGE_SIZE));
  state.sendRecordPage = Math.min(state.sendRecordPage, recordPages);
  const queuePageItems = pageSlice(queueItems, state.sendQueuePage);
  const recordPageItems = pageSlice(records, state.sendRecordPage);
  view.innerHTML = `
    <section class="section">
      ${masterSwitch("send-enabled", "发送缓冲", "接管回复按自然句段拆入缓存、逐条发送；用户抢话时自动裁决（A 说完再回 / B 丢掉重新组织）。", data.enabled)}
      <div class="section-head">
        <h2 class="section-title">发送缓冲与「被抢话」裁决</h2>
        <p class="section-desc">只有<b>接管改换</b>链路的回复进缓冲（我们生成我们发）；放行/走主链的回复由 AstrBot 管线发送，无法缓存。插件重载时未发完的缓存会丢弃。</p>
      </div>
      ${queueItems.length || Object.keys(interrupted).length ? "" : '<div class="hint">当前没有待发送缓存。</div>'}
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">待发送队列</h3><span class="hint">${queueItems.length} 条</span></div>
          ${queuePageItems.map((q) => `
            <div class="field">
              <div class="hint" style="color:var(--ink)">${esc(q.sid)} · 第 ${q.idx} 条${q.sent ? "（已发）" : ""}</div>
              <div class="hint" style="opacity:.7">${esc(String(q.text || "").slice(0, 40))}</div>
              <button class="btn" data-send-purge="${esc(q.sid)}" style="margin-top:4px">清空该会话缓存</button>
            </div>`).join("") || '<div class="hint">暂无。</div>'}
          ${pagerBar("send-queue-pager", queueItems.length, state.sendQueuePage)}
        </section>
        ${Object.keys(interrupted).length ? `
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">被打断没说完的话</h3><span class="hint">${Object.keys(interrupted).length} 个会话</span></div>
          ${Object.keys(interrupted).map((sid) => `<div class="hint" style="color:var(--ink)">${esc(sid)}：${esc(interrupted[sid])}</div>`).join("")}
        </section>` : ""}
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">裁决与发送记录</h3><span class="hint">${records.length} 条</span></div>
          ${recordPageItems.map((r) => `
            <div class="field">
              <div class="hint" style="color:var(--ink)">${esc(r.time || "")} · ${esc(r.kind || "")}${r.session_id ? ` · ${esc(r.session_id)}` : ""}</div>
              <div class="hint" style="opacity:.7">${esc(String(r.note || ""))}</div>
            </div>`).join("") || '<div class="hint">暂无记录。</div>'}
          ${pagerBar("send-record-pager", records.length, state.sendRecordPage)}
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">发送设置</h3></div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("send", "chunk_interval_min", sendItems.chunk_interval_min || { description: "短句间隔(秒)", type: "float", default: 0.8 }, cfg("chunk_interval_min", 0.8))}
            ${renderSettingField("send", "chunk_interval_max", sendItems.chunk_interval_max || { description: "长句间隔(秒)", type: "float", default: 4.0 }, cfg("chunk_interval_max", 4.0))}
            ${renderSettingField("send", "interrupt_judge_enabled", sendItems.interrupt_judge_enabled || { description: "抢话裁决", type: "bool", default: true }, cfg("interrupt_judge_enabled", true))}
            ${renderSettingField("send", "interrupt_judge_provider_id", sendItems.interrupt_judge_provider_id || { description: "抢话裁决模型", type: "string", role: "provider", default: "" }, cfg("interrupt_judge_provider_id", ""))}
          </div>
          <div class="hint" style="margin-top:8px">裁决关闭时固定按 A（提速发完再回）。被判 B 时，没说完的话会作为上下文注入下一轮生成（像被打断后重新组织）。</div>
        </section>
      </div>
    </div>
  `;
  bindPager("send-queue-pager", queueItems.length, (p) => { state.sendQueuePage = p; }, () => renderSend());
  bindPager("send-record-pager", records.length, (p) => { state.sendRecordPage = p; }, () => renderSend());
  view.querySelectorAll("[data-send-purge]").forEach((node) => {
    node.addEventListener("click", async () => {
      try {
        await apiPost("send/purge", { session_id: node.dataset.sendPurge });
        toast("已清空");
        state.sendQueuePage = 1;
        await renderSend();
      } catch (err) { toast(`清空失败：${err.message}`, "err"); }
    });
  });
  await bindMasterSwitch("send-enabled", "send", "enabled");
  bindSettingsIn(view);
}

/* Token 页：三来源独立展示（为你续写的故事 / AstrBot 主链 / 记忆插件）+ 分页明细 */
const TASK_CN = {
  main_chain: "主链对话", takeover: "接管改换", judge: "回复判定", emoji_judge: "表情包判定",
  rewrite: "润色", interrupt: "抢话裁决", relationship: "关系判断", profile: "用户画像",
  schedule: "日程生成", diary: "写日记", presence: "状态生成", proactive: "主动消息",
  dream: "梦境", think: "思考", search: "搜索整理", smart_judge: "防抖判定",
  voice_gen: "风格生成", persona_gen: "人格生成", wardrobe_gen: "穿搭生成",
  embedding: "嵌入", vision: "识图", media_file: "文件摘要", media_link: "链接要点",
  chat: "对话", summary: "阶段总结", link_point: "链接要点", caption: "图片转述",
  embed: "向量嵌入", rerank: "语义重排", test: "模型测试", maintenance: "维护任务",
};
function taskCn(name) { return TASK_CN[name] || name; }
const SOURCE_CN = { companion: "为你续写的故事（直连）", main: "AstrBot 主链（本插件代记）", memory: "记忆插件" };

async function renderToken() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载 Token 用量…</div>`;
  let data;
  try {
    data = await apiGet("token/stats");
  } catch (err) {
    if (state.current === "token") view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    return;
  }
  if (state.current !== "token") return;
  const stats = data.stats || {};        // 陪伴插件直连（接管改换/自调/生图等）
  const main = data.main || {};          // 本插件介入会话的主链代记
  const astr = data.astr_total || {};    // AstrBot 主链全部调用（本插件代记）
  const memory = data.memory || null;
  // 0.170：AstrBot 总消耗卡 = 全部 LLM 消耗（主链 + 陪伴插件直连 + 记忆插件）——用户反馈"展示总消耗"
  const mergeSum = (...objs) => {
    const out = { total: {}, today: {}, month: {} };
    for (const field of ["total", "today", "month"]) {
      let input = 0, output = 0, sum = 0, calls = 0;
      for (const o of objs) {
        const seg = ((o || {})[field] || {});
        input += Number(seg.input || 0);
        output += Number(seg.output || 0);
        sum += Number(seg.sum || 0);
        calls += Number(seg.calls || 0);
      }
      out[field] = { input, output, sum, calls };
    }
    return out;
  };
  const astrAll = mergeSum(astr, stats, main, memory || {});
  // 顶部三卡（0.148 重定义，0.170 修正）：本插件总消耗 / AstrBot 总消耗（全部）/ 记忆插件总消耗
  const cards = [
    { key: "plugin", label: "为你续写的故事", sub: "本插件总消耗（直连 + 主链代记）", st: stats, extra: main },
    { key: "astr", label: "AstrBot 总消耗", sub: "全部 LLM 消耗（主链 + 陪伴插件 + 记忆插件）", st: astrAll },
    { key: "memory", label: "为你篆刻的历史", sub: "记忆插件总消耗", st: memory },
  ];
  const sum = (s, field) => Number(((s || {})[field] || {}).sum || 0);
  const callsOf = (s, field) => Number(((s || {})[field] || {}).calls || 0);
  const cardSum = (c, field) => sum(c.st, field) + (c.extra ? sum(c.extra, field) : 0);
  const cardIO = (c, field) => Number(((c.st.total || {})[field] || 0)) + (c.extra ? Number(((c.extra.total || {})[field] || 0)) : 0);
  const cardCalls = (c, field) => callsOf(c.st, field) + (c.extra ? callsOf(c.extra, field) : 0);
  const monthBadge = (c) => {
    const monthCalls = cardCalls(c, "month");
    return monthCalls > 0 ? `${monthCalls.toLocaleString()} 次/月` : "本月暂无调用";
  };
  const sourceCard = (c) => {
    if (!c.st) {
      return `
        <section class="panel token-source-card off">
          <div class="panel-head"><h3 class="panel-title">${esc(c.label)}</h3><span class="hint">未联动</span></div>
          <div class="hint" style="margin-top:6px">记忆插件未安装或桥接未开启，暂无统计。</div>
        </section>`;
    }
    const zeroHint = cardSum(c, "total") > 0 ? "" : (
      c.key === "astr"
        ? '<div class="hint" style="opacity:.75;margin-top:6px">尚未统计——主链全局记账自 0.148 起（重载插件后会随主链调用累计；含本插件未介入的会话）。</div>'
        : (c.key === "memory"
            ? '<div class="hint" style="opacity:.75;margin-top:6px">暂无调用——记忆插件的总结 / 转述 / 嵌入等调用发生后才会计数（需已重载新版记忆插件）。</div>'
            : "")
    );
    return `
      <section class="panel token-source-card${c.key === "plugin" ? " primary" : ""}">
        <div class="panel-head"><h3 class="panel-title">${esc(c.label)}</h3><span class="hint">${monthBadge(c)}</span></div>
        <div class="hint" style="opacity:.75;margin-top:2px">${esc(c.sub)}</div>
        <div class="field" style="margin-top:4px">
          <div class="field-row">
            <div class="field-title" style="font-size:20px">${cardSum(c, "total").toLocaleString()}</div>
            <div class="hint">累计 tokens</div>
          </div>
          <div class="hint">今日 ${cardSum(c, "today").toLocaleString()} · 本月 ${cardSum(c, "month").toLocaleString()}</div>
          <div class="hint" style="opacity:.7">入 ${cardIO(c, "input").toLocaleString()} / 出 ${cardIO(c, "output").toLocaleString()}</div>
        </div>
        ${zeroHint}
      </section>`;
  };
  // 占比条：两个插件占全部 LLM 消耗的比例（AstrBot 主链 + 陪伴直连 + 记忆插件）
  const astrSum = sum(astr, "total");
  const pluginSum = cardSum(cards[0], "total");
  const memSum = memory ? sum(memory, "total") : 0;
  const grand = astrSum + pluginSum + memSum;
  const share = (v) => (grand > 0 ? Math.round((v / grand) * 100) : 0);
  const shareBar = grand > 0 ? `
    <section class="panel" style="margin-top:14px">
      <div class="panel-head"><h3 class="panel-title">占比</h3><span class="hint">两插件 vs AstrBot 主链（全部 LLM 消耗）</span></div>
      <div class="token-share" style="display:flex;height:26px;border-radius:6px;overflow:hidden;margin-top:6px">
        <div style="flex:${pluginSum || 0.001};background:var(--glow-a,#14b8a6);display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700">插件 ${share(pluginSum)}%</div>
        <div style="flex:${memSum || 0.001};background:var(--glow-b,#38bdf8);display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700">记忆 ${share(memSum)}%</div>
        <div style="flex:${astrSum || 0.001};background:rgba(125,150,158,0.35);display:flex;align-items:center;justify-content:center;color:var(--ink-2);font-size:12px">AstrBot 主链 ${share(astrSum)}%</div>
      </div>
      <div class="hint" style="margin-top:8px">总盘子 ${grand.toLocaleString()} tokens = AstrBot 主链 ${astrSum.toLocaleString()} + 陪伴插件(直连+代记) ${pluginSum.toLocaleString()} + 记忆插件 ${memSum.toLocaleString()}。主链段含全部主链对话（含本插件未介入的会话），由本插件代记。</div>
    </section>` : "";
  // 明细切换来源（companion/main/memory 三线独立）
  const detailSources = [
    { key: "companion", label: "为你续写的故事（直连）", st: stats },
    { key: "main", label: "AstrBot 主链（本插件代记）", st: main },
    { key: "memory", label: "记忆插件", st: memory },
  ];
  const active = detailSources.find((s) => s.key === state.tokenSource && s.st) || detailSources[0];
  state.tokenSource = active.key;
  const cur = active.st;
  const tasks = (cur.by_task || []).map((t) => ({ ...t, label: taskCn(t.name) }));
  const recents = (cur.recent || []) || [];
  const taskPages = Math.max(1, Math.ceil(tasks.length / PAGE_SIZE));
  state.tokenTaskPage = Math.min(state.tokenTaskPage, taskPages);
  const recentPages = Math.max(1, Math.ceil(recents.length / PAGE_SIZE));
  state.tokenRecentPage = Math.min(state.tokenRecentPage, recentPages);
  const bar = (name, inp, out, calls) => {
    const s2 = inp + out;
    const max = Math.max(sum(cur, "total") || 1, 1);
    const pct = Math.min(100, Math.round((s2 / max) * 100));
    return `
      <div class="field">
        <div class="field-row">
          <div class="field-title">${esc(name)}</div>
          <div class="hint">${s2.toLocaleString()} tokens（入 ${(inp).toLocaleString()} / 出 ${(out).toLocaleString()}）${calls ? ` · ${(calls).toLocaleString()} 次` : ""}</div>
        </div>
        <div class="progress"><div class="progress-fill" style="width:${pct}%"></div></div>
      </div>`;
  };
  const miniCard = (label, t) => `
    <div class="token-mini-card">
      <div class="hint">${esc(label)}</div>
      <div class="token-mini-num">${((t || {}).sum || 0).toLocaleString()}</div>
      <div class="hint" style="opacity:.75">入 ${Number(((t || {}).input) || 0).toLocaleString()} / 出 ${Number(((t || {}).output) || 0).toLocaleString()}</div>
      <div class="hint">${(Number(((t || {}).calls) || 0)).toLocaleString()} 次调用</div>
    </div>`;
  const taskPageItems = pageSlice(tasks, state.tokenTaskPage);
  const recentPageItems = pageSlice(recents, state.tokenRecentPage);
  view.innerHTML = `
    <section class="section">
      <div class="section-head"><h2 class="section-title">Token 用量</h2>
        <p class="section-desc">三线独立记账：<b>为你续写的故事</b>（直连 + 本插件介入的主链代记）、<b>AstrBot 总消耗</b>（主链全部调用，本插件代记）、<b>为你篆刻的历史</b>（经桥接读取）。提供方返回真实用量时记真实值，否则按文本估算（不额外调 LLM）。</p>
      </div>
      <div class="token-source-grid">
        ${cards.map(sourceCard).join("")}
      </div>
      ${shareBar}
    </section>
    <section class="section">
      <div class="section-head"><h2 class="section-title">明细 · ${esc(SOURCE_CN[active.key] || active.label)}</h2></div>
      <div class="token-pills">
        ${detailSources.map((s) => `<button class="pill ${s.key === active.key ? "active" : ""}" data-token-source="${s.key}" ${s.st ? "" : "disabled"}>${esc(s.label)}</button>`).join("")}
      </div>
      <div class="token-mini-grid">
        ${miniCard("总计", cur.total)}
        ${miniCard("今天", cur.today)}
        ${miniCard("本月", cur.month)}
      </div>
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">按任务（本月）</h3><span class="hint">${tasks.length} 项</span></div>
          ${taskPageItems.map((m) => bar(m.label, m.input, m.output, m.calls)).join("") || '<div class="hint">暂无记录。</div>'}
          ${pagerBar("token-task-pager", tasks.length, state.tokenTaskPage)}
        </section>
      </div>
      <div class="rel-right" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">最近调用</h3><span class="hint">${recents.length} 条</span></div>
          ${recentPageItems.map((r) => `
            <div class="field">
              <div class="hint" style="color:var(--ink)">${esc(String(r.time || ""))} · ${esc(taskCn(String(r.task || "")))}</div>
              <div class="hint" style="opacity:.7">${esc(String(r.model || ""))} · 入 ${Number(r.input || 0).toLocaleString()} / 出 ${Number(r.output || 0).toLocaleString()}</div>
            </div>`).join("") || '<div class="hint">暂无调用。</div>'}
          ${pagerBar("token-recent-pager", recents.length, state.tokenRecentPage)}
        </section>
      </div>
    </div>
  `;
  view.querySelectorAll("[data-token-source]").forEach((node) => {
    node.addEventListener("click", () => {
      if (node.disabled) return;
      state.tokenSource = node.dataset.tokenSource;
      state.tokenTaskPage = 1;
      state.tokenRecentPage = 1;
      renderToken();
    });
  });
  bindPager("token-task-pager", tasks.length, (p) => { state.tokenTaskPage = p; }, () => renderToken());
  bindPager("token-recent-pager", recents.length, (p) => { state.tokenRecentPage = p; }, () => renderToken());
}

/* 表情包页：三栏（图库 / 发送记录与策略 / 发送设置） */
async function renderEmoji() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载表情包…</div>`;
  let data, prefsData;
  try {
    data = await apiGet("emoji/categories");
    prefsData = await apiGet("emoji/prefs");
  } catch (err) {
    if (state.current === "emoji") view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    return;
  }
  if (state.current !== "emoji") return;
  const cats = data.categories || [];
  const prefs = (prefsData && prefsData.prefs) || {};
  const sentLog = prefs.sent || [];
  const feedback = prefs.feedback || [];
  const optOut = prefs.opt_out || {};
  const weights = prefs.weights || {};
  const schema = state.configSchema || {};
  const values = state.configValues || {};
  const emojiItems = (schema.emoji && schema.emoji.items) || {};
  const cfg = (m, k, fb) => ((values[m] || {})[k] ?? fb);
  view.innerHTML = `
    <section class="section">
      ${masterSwitch("emoji-enabled", "表情包", "回复时按语境匹配分类发表情包（判定模型决定，可配频率）。", await loadModuleEnabled("emoji", "enabled"))}
      <div class="section-head">
        <h2 class="section-title">表情包</h2>
        <p class="section-desc">判定模型按语境匹配分类；发表情像人：克制（默认 25% 概率）、按发送习惯选图（常用图权重更高）、会学习你的反馈、你说了「别发表情包」就停。</p>
      </div>
      <div class="field-row" style="gap:8px;flex-wrap:wrap">
        ${Object.keys(optOut).length ? `<span class="hint" style="color:#f59e0b;font-weight:700">⚠ ${Object.keys(optOut).length} 位用户已声明「别发表情包」（已停用自动表情）</span>` : ""}
      </div>
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 300px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">图库与分类</h3><span class="hint">${cats.length} 个分类</span></div>
          ${cats.map((c) => `
            <div class="field">
              <div class="field-row">
                <div>
                  <div class="field-title">${esc(c.title)}（${c.count} 张）</div>
                  <div class="hint">${esc(c.description || "")}</div>
                </div>
                <div style="display:flex;gap:6px;flex-shrink:0">
                  <button class="btn" data-edit-cat="${esc(c.id)}" data-title="${esc(c.title)}" data-desc="${esc(c.description || "")}">编辑</button>
                  <button class="btn" data-del-cat="${esc(c.id)}">删</button>
                </div>
              </div>
              <div class="field-row" style="gap:6px;flex-wrap:wrap;align-items:flex-end">
                ${(c.files || []).map((f) => `
                  <div style="position:relative;display:inline-block;margin:2px">
                    <img src="${esc(f.data_url)}" style="width:64px;height:64px;object-fit:contain;border-radius:6px;border:1px solid var(--line);background:rgba(0,0,0,.04)" title="${esc(f.name)}">
                    <button class="btn" data-del-emoji="${esc(c.id)}|${esc(f.name)}" style="position:absolute;top:-6px;right:-6px;padding:0 6px;font-size:10px;line-height:1.7;border-radius:50%" title="删除这张">×</button>
                  </div>`).join("") || (c.count ? '<div class="hint">（已导入但无预览——单张超过 2MB 的不展示预览，仍可删除）</div>' : "")}
                ${c.preview_total > (c.files || []).length ? `<div class="hint" style="opacity:.6">还有 ${c.preview_total - (c.files || []).length} 张未显示（每分类最多预览 8 张）</div>` : ""}
              </div>
              <div class="field-row" style="gap:6px">
                <input class="input" id="up-${esc(c.id)}" type="file" accept="image/*" multiple>
              </div>
            </div>`).join("") || '<div class="hint">还没有分类。</div>'}
          <div class="field">
            <div class="field-title">新增分类</div>
            <input class="input" id="new-cat-title" placeholder="分类标题，如「表达轻微吐槽」">
            <input class="input" id="new-cat-desc" placeholder="描述（可选）">
            <button class="btn" id="add-cat">添加分类</button>
          </div>
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">机制与提示</h3></div>
          <div class="hint" style="margin-top:4px">
            · <b>习惯组选图</b>：按发送历史频率加权挑分类内的图（常用图权重更高），默认不去重，><b>0</b> 天才启用「同图不重复」；<br>
            · 用户正/负面反馈会微调该分类概率（0.5×~1.5×）；<br>
            · 用户明说「别发表情包」自动停用（可恢复），左侧会列出已声明用户；<br>
            · 回复动作判定（沉默/草草回复/表情包/正常发送）统一走「回复判定模型」（关系页 → 关系设置），本页只负责表情包这一环；<br>
            · AstrBot 自带<b>分段回复</b>（平台设置 → 消息分流 → 分段回复），本插件不使用该功能以避免冲突；如需长回复分段发送，请到平台设置中开启。
          </div>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">发送记录</h3><span class="hint">${sentLog.length} 条</span></div>
          ${sentLog.slice(0, 10).map((s) => `
            <div class="field">
              <div class="hint" style="color:var(--ink)">${esc(String(s.at || ""))} · ${esc(String(s.cid || ""))}</div>
              <div class="hint" style="opacity:.6">${esc(String(s.path || "").split(/[\\/]/).pop() || "")}${s.user ? ` · ${esc(s.user)}` : ""}</div>
            </div>`).join("") || '<div class="hint">还没有发送记录。</div>'}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">反馈学习记录</h3><span class="hint">${feedback.length} 条</span></div>
          ${feedback.slice(0, 8).map((f) => `
            <div class="hint">${esc(String(f.at || ""))} · ${esc(f.negative ? "负面" : "正面")} · ${esc(String(f.cid || ""))}</div>`).join("") || '<div class="hint">暂无反馈——用户对表情包的评论会被记录并调整概率。</div>'}
        </section>
      </div>
      <div class="rel-right" style="flex:0 0 320px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">发送设置</h3></div>
          <div class="settings-grid" style="grid-template-columns:1fr">
            ${renderSettingField("emoji", "send_probability", emojiItems.send_probability || { description: "发送概率", type: "float", default: 0.25 }, cfg("emoji", "send_probability", 0.25))}
            ${renderSettingField("emoji", "duplicate_days", emojiItems.duplicate_days || { description: "同图去重天数", type: "int", default: 3 }, cfg("emoji", "duplicate_days", 3))}
            ${renderSettingField("emoji", "judge_provider_id", emojiItems.judge_provider_id || { description: "表情包判定模型", type: "string", role: "provider", default: "" }, cfg("emoji", "judge_provider_id", ""))}
          </div>
          <div class="hint" style="margin-top:8px">判定模型按语境决定这轮是否带表情包；概率闸与反馈学习再微调。表情包判定有独立模型名额，留空时回退「回复判定模型」（关系页）。</div>
        </section>
      </div>
    </div>
  `;
  const addBtn = document.getElementById("add-cat");
  if (addBtn) addBtn.addEventListener("click", async () => {
    const title = document.getElementById("new-cat-title").value.trim();
    const description = document.getElementById("new-cat-desc").value.trim();
    if (!title) { toast("请填分类标题", "err"); return; }
    try {
      await apiPost("emoji/category/add", { title, description });
      toast("已添加");
      await renderEmoji();
    } catch (err) { toast(`添加失败：${err.message}`, "err"); }
  });
  view.querySelectorAll("[data-del-cat]").forEach((node) => {
    node.addEventListener("click", async () => {
      try {
        await apiPost("emoji/category/remove", { id: node.dataset.delCat });
        toast("已删除");
        await renderEmoji();
      } catch (err) { toast(`删除失败：${err.message}`, "err"); }
    });
  });
  view.querySelectorAll("[data-edit-cat]").forEach((node) => {
    node.addEventListener("click", () => {
      const cid = node.dataset.editCat;
      const title = node.dataset.title || "";
      const desc = node.dataset.desc || "";
      modal(`
        <h3>编辑分类</h3>
        <div class="field" style="margin-top:12px">
          <div class="field-title">分类标题</div>
          <input class="input" id="edit-cat-title" value="${esc(title)}">
          <div class="field-title" style="margin-top:10px">描述</div>
          <input class="input" id="edit-cat-desc" value="${esc(desc)}">
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
          <button class="btn" data-close>取消</button>
          <button class="btn glow" id="save-cat-edit">保存</button>
        </div>
      `);
      const saveBtn = document.getElementById("save-cat-edit");
      if (saveBtn) saveBtn.addEventListener("click", async () => {
        const newTitle = document.getElementById("edit-cat-title").value.trim();
        const newDesc = document.getElementById("edit-cat-desc").value.trim();
        if (!newTitle) { toast("标题不能为空", "err"); return; }
        try {
          await apiPost("emoji/category/update", { id: cid, title: newTitle, description: newDesc });
          toast("已保存");
          closeModal();
          await renderEmoji();
        } catch (err) { toast(`保存失败：${err.message}`, "err"); }
      });
    });
  });
  view.querySelectorAll("[data-del-emoji]").forEach((node) => {
    node.addEventListener("click", async () => {
      const [cid, file] = String(node.dataset.delEmoji || "").split("|");
      if (!cid || !file) return;
      confirmDialog("删除这张表情包", "删除后无法恢复（分类保留）。", async () => {
        try {
          await apiPost("emoji/remove", { id: cid, file });
          toast("已删除");
          await renderEmoji();
        } catch (err) { toast(`删除失败：${err.message}`, "err"); }
      });
    });
  });
  view.querySelectorAll('input[type="file"]').forEach((input) => {
    input.addEventListener("change", async () => {
      const cid = input.id.replace("up-", "");
      const files = input.files || [];
      for (const file of files) {
        try {
          // AstrBot 桥禁止 endpoint 内联 query（files:upload 无 params 通道）：
          // 分类 id 放进文件名前缀 (<cid>__<原文件名>)，后端从中解析
          const tagged = new File([file], `${cid}__${file.name}`, { type: file.type || "application/octet-stream" });
          await bridge.upload("emoji/upload", tagged);
        } catch (err) { toast(`上传失败：${err.message}`, "err"); }
      }
      toast("已上传");
      await renderEmoji();
    });
  });
  await bindMasterSwitch("emoji-enabled", "emoji", "enabled");
  bindSettingsIn(view);
}

/* 设置页：模块子选项卡 + 修改即自动保存 */
async function renderSettings() {
  const view = $("#view");
  // 同步占位：切换动画播放期间内容不跳变
  view.innerHTML = `<div class="loading">加载设置…</div>`;
  let data;
  try {
    data = await apiGet("config/schema");
  } catch (err) {
    if (state.current === "settings") {
      view.innerHTML = `<div class="section"><p class="section-desc">设置加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "settings") return;
  state.configSchema = data.schema || {};
  state.configValues = data.values || {};
  applyAnimationSettings();
  const schema = state.configSchema;
  // 有专属选项卡的功能在各自页面管理（含总开关），设置页不重复展示；
  // 设置页只保留「模型配置」（全局生成策略：流式/超时/思考/回退），其它全部模块化到各页
  const EXCLUDED_MODULES = ["identity", "relationship", "voice", "persona", "presence", "schedule", "proactive", "emoji", "wardrobe", "debounce", "intercept", "rewrite", "memory", "vision", "pipeline", "general", "search", "mind", "send", "image"];
  const modules = Object.keys(schema).filter((m) => !EXCLUDED_MODULES.includes(m));
  if (!state.settingsModule || !modules.includes(state.settingsModule)) {
    state.settingsModule = modules[0] || "";
  }
  const module = state.settingsModule;
  const moduleSchema = schema[module] || {};
  const items = moduleSchema.items || {};
  const values = (state.configValues[module] || {});
  // 设置布局逻辑性：开关类聚前（总开关在最前），下拉/选项居中，数值与文本手动编辑在后
  let orderedEntries = sortSettingEntries(Object.entries(items));
  // 「链路」的「判定模型」已移入关系页（关系判断模型），此处不再重复展示
  if (module === "pipeline") orderedEntries = orderedEntries.filter(([k]) => k !== "provider_id");
  view.innerHTML = `
    <div class="mod-tabs">
      ${modules.map((m) => `
        <div class="pill ${m === module ? "active" : ""}" data-mod-tab="${esc(m)}">${esc(schema[m].description || m)}</div>
      `).join("")}
    </div>
    ${placeholderHintCard(module)}
    ${module === "models" ? `<div class="hint" style="margin:0 0 14px;color:var(--ink-2)">这里是<b>生成参数</b>（流式 / 超时 / 预算 / 思考上限 / 回退策略）；各模块专属模型与<b>回退模型</b>的选择请到「模型」页（模型配置集中点，与各处同源同步）。</div>` : ""}
    <section class="section">
      <div class="section-head" style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
        <div>
          <h2 class="section-title">${esc(moduleSchema.description || module)}</h2>
          <p class="section-desc">${esc(moduleSchema.hint || "")} 修改即自动保存。</p>
        </div>
        <button class="btn" data-reset-module="${esc(module)}">恢复默认</button>
      </div>
      ${orderedEntries.map(([key, item]) => `
        ${renderSettingField(module, key, item, values[key])}
      `).join("")}
    </section>
    <section class="section" style="margin-top:16px">
      <div class="section-head">
        <h2 class="section-title">调用超时后的回复</h2>
        <p class="section-desc">插件自调的媒体/接管等调用超时失败时，Bot 是否回一条「报错」说明。留空 = 静默（不打扰，也不把机制暴露给用户）；填了则超时失败时发送这段话。此消息直发，不会写入 AstrBot 会话历史、也不会被记忆插件捕获——它是 Bot 的「报错」，不是对话。</p>
      </div>
      <div class="setting-card">
        <div class="field">
          <div class="field-title">超时回复文案<span class="field-key">general.timeout_reply</span></div>
          <textarea class="text-input" rows="3" style="width:100%" data-setting="general.timeout_reply" data-type="text" placeholder="留空 = 超时失败时静默（不发任何消息）">${esc(((state.configValues.general || {}).timeout_reply) ?? "")}</textarea>
        </div>
      </div>
    </section>
  `;
  bindSettingsEvents();
}

/* 设置项排序：开关(bool) → 模型下拉/选项(role=provider/options) → 数值 → 文本 */
function sortSettingEntries(entries) {
  const rank = (item) => {
    if (item && item.type === "bool") return 0;
    if (item && (item.role === "provider" || (Array.isArray(item.options) && item.options.length))) return 1;
    if (item && (item.type === "int" || item.type === "float")) return 2;
    return 3;
  };
  return entries.slice().sort((a, b) => {
    const r = rank(a[1]) - rank(b[1]);
    return r !== 0 ? r : String(a[0]).localeCompare(String(b[0]));
  });
}

function renderSettingField(module, key, item, value) {
  const type = item.type || "string";
  const options = Array.isArray(item.options) ? item.options : [];
  const hint = item.hint ? `<div class="hint">${esc(item.hint)}</div>` : "";
  const head = `
    <div class="field-title">${esc(item.description || key)}<span class="field-key">${esc(key)}</span></div>
    ${hint}
  `;
  // 每个设置项 = 一张与背景区分的「展示板」卡片（参考防抖页）
  const card = (inner) => `<div class="setting-card">${inner}</div>`;
  // 模型选择项（role=provider）：统一下拉菜单形式，选项来自 AstrBot 已配置模型
  // （嵌入/重排字段用各自分类列表，与 LLM 对话模型分开，避免选错）
  if (item.role === "provider") {
    const isEmbedding = item.provider_kind === "embedding" || String(key).includes("embedding");
    const isRerank = item.provider_kind === "rerank" || String(key).includes("rerank");
    const providers = isEmbedding
      ? (state.embeddingProviders || [])
      : (isRerank ? (state.providers || []) : (state.providers || []));
    const val = String(value ?? "");
    // 嵌入/重排模型为独立分类、不参与「留空回退模型」：未设置即报错，文案区分
    const emptyLabel = (isEmbedding || isRerank)
      ? "（未设置——调用将报错）"
      : (module === "models" && key === "fallback_provider_id"
          ? "（未设置——未配置专属模型的调用将被驳回）"
          : "（按「留空回退模型」策略）");
    return card(`
      <div class="field">
        ${head}
        ${isEmbedding || isRerank ? `<div class="hint" style="opacity:.65">列表来源：AstrBot「${isEmbedding ? "嵌入" : "重排"}」模型分类</div>` : ""}
        <select class="input" data-setting="${module}.${key}" data-type="provider">
          <option value="">${emptyLabel}</option>
          ${providers.map((p) => `
            <option value="${esc(p.id)}" ${String(p.id) === val ? "selected" : ""}>${esc(p.label)}</option>
          `).join("")}
        </select>
      </div>
    `);
  }
  if (type === "bool") {
    const on = Boolean(value);
    // 功能总开关（enabled/managed_injection）统一红色大开关效果；「留空回退模型」为策略开关，按用户要求保留橙色；
    // 其余布尔项青绿方形滑块
    const isMaster = key === "enabled" || key === "managed_injection";
    const isOrange = module === "models" && key === "fallback_enabled";
    const cls = `switch ${isMaster ? "red" : isOrange ? "orange" : ""}`;
    return card(`
      <div class="field">
        <div class="field-row">
          <div>${head}</div>
          <label class="${cls}"><input type="checkbox" data-setting="${module}.${key}" data-type="bool" ${on ? "checked" : ""}><span></span></label>
        </div>
      </div>
    `);
  }
  if (options.length > 0) {
    return card(`
      <div class="field">
        ${head}
        <div class="pill-rows" style="margin-top:10px">
          ${options.map((opt) => `
            <div class="pill ${String(opt) === String(value ?? item.default) ? "active" : ""}" data-setting="${module}.${key}" data-type="option" data-option="${esc(String(opt))}">${esc(String(opt))}</div>
          `).join("")}
        </div>
      </div>
    `);
  }
  if (type === "int" || type === "float") {
    const step = type === "int" ? 1 : "0.1";
    return card(`
      <div class="field">
        ${head}
        <input class="text-input" type="number" step="${step}" data-setting="${module}.${key}" data-type="number" value="${esc(value ?? item.default ?? "")}" />
      </div>
    `);
  }
  return card(`
    <div class="field">
      ${head}
      <input class="text-input" type="text" data-setting="${module}.${key}" data-type="text" value="${esc(value ?? item.default ?? "")}" />
    </div>
  `);
}

/* 自动保存单个配置项 */
async function saveConfigValue(module, key, value) {
  diagLog(`设置自动保存: ${module}.${key}=${JSON.stringify(value)}`);
  try {
    const data = await apiPost("config/module/update", { module, values: { [key]: value } });
    if (!state.configValues[module]) state.configValues[module] = {};
    state.configValues[module][key] = (data.values || {})[key];
    applyAnimationSettings();
    toast("已保存");
    // 设置变更即时生效：若当前页依赖该设置，重渲染本页（无需手动刷新/切换）
    refreshCurrentView();
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
    await reloadConfig();
    renderSettings();
  }
}

/* 设置保存后重渲染当前模块页（主动/内心/日程/穿搭等依赖配置的页面） */
function refreshCurrentView() {
  if (!state.current) return;
  const map = {
    proactive: renderProactive,
    mind: renderMind,
    schedule: renderSchedule,
    wardrobe: renderWardrobe,
    presence: renderPresence,
    voice: renderVoice,
    persona: renderPersona,
    relationship: renderRelationships,
    debounce: renderDebounce,
    intercept: renderIntercept,
    rewrite: renderRewrite,
    models: renderModels,
    image: renderImage,
  };
  const fn = map[state.current];
  if (fn && state.current !== "settings") {
    fn().catch((err) => diagLog(`${state.current} 页刷新异常: ${err.message}`));
  }
}

async function reloadConfig() {
  try {
    const data = await apiGet("config/schema");
    state.configSchema = data.schema || {};
    state.configValues = data.values || {};
    applyAnimationSettings();
  } catch (e) {
    diagLog(`配置刷新失败: ${e.message}`);
  }
}

function bindSettingsEvents() {
  $("#view").querySelectorAll("[data-mod-tab]").forEach((node) => {
    node.addEventListener("click", () => {
      state.settingsModule = node.dataset.modTab;
      renderSettings();
    });
  });

  // 兜底：同时匹配漏标 data-type 的原生 checkbox（读 checked，避免存成 "on"）
  $("#view").querySelectorAll("[data-setting][data-type='bool'], input[data-setting][type='checkbox']").forEach((node) => {
    node.addEventListener("change", () => {
      const [module, key] = node.dataset.setting.split(".");
      saveConfigValue(module, key, node.checked);
    });
  });

  $("#view").querySelectorAll("[data-setting][data-type='option']").forEach((node) => {
    node.addEventListener("click", () => {
      const [module, key] = node.dataset.setting.split(".");
      $("#view").querySelectorAll(`[data-setting="${module}.${key}"]`).forEach((n) => {
        n.classList.toggle("active", n === node);
      });
      saveConfigValue(module, key, node.dataset.option);
    });
  });

  $("#view").querySelectorAll("[data-setting][data-type='number']").forEach((node) => {
    node.addEventListener("change", () => {
      const [module, key] = node.dataset.setting.split(".");
      const item = (state.configSchema[module] || {}).items || {};
      const raw = node.value;
      const value = item[key] && item[key].type === "int" ? parseInt(raw, 10) : parseFloat(raw);
      if (!Number.isFinite(value)) {
        toast("请输入有效数字", "err");
        node.value = (state.configValues[module] || {})[key] ?? "";
        return;
      }
      saveConfigValue(module, key, value);
    });
  });

  $("#view").querySelectorAll("[data-setting][data-type='text'], [data-setting][data-type='provider']").forEach((node) => {
    node.addEventListener("change", () => {
      const [module, key] = node.dataset.setting.split(".");
      saveConfigValue(module, key, node.value);
    });
  });

  $("#view").querySelectorAll("[data-reset-module]").forEach((node) => {
    node.addEventListener("click", async () => {
      const module = node.dataset.resetModule;
      try {
        await apiPost("config/module/reset", { module });
        await reloadConfig();
        renderSettings();
        toast("已恢复默认");
      } catch (err) {
        toast(`重置失败：${err.message}`, "err");
      }
    });
  });
}

/* 调试页：子选项卡（诊断 / 拦截与改换） */
async function renderDebug() {
  const view = $("#view");
  // 拦截内容已迁至「拦＆改」选项卡，调试页仅保留诊断
  view.innerHTML = `
    <div class="mod-tabs">
      <div class="pill active" data-debug-tab="diag">诊断</div>
    </div>
    <div id="debug-body">加载中…</div>
  `;
  await renderDiagSub();
}

/* 诊断子页：前端诊断 + 运行时日志 */
async function renderDiagSub() {
  const body = document.getElementById("debug-body");
  body.innerHTML = `
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">前端诊断</h2>
        <p class="section-desc">本页面会话内的关键事件与接口调用记录（实时追加，最多 200 行）。</p>
      </div>
      <pre class="log-view" id="dbg-diag" style="max-height:30vh">${esc(diagLines.join("\n")) || "（暂无记录）"}</pre>
    </section>
    <section class="section">
      <div class="section-head" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <h2 class="section-title">运行时 Provider 诊断</h2>
          <p class="section-desc">进程内真实值：数据目录 / 配置路径 / 各提供商运行时状态（Key 只显示尾号）。可核对面板保存与文件是否同步。</p>
        </div>
        <button class="btn" id="dbg-provider">读取</button>
      </div>
      <pre class="log-view" id="dbg-provider-out" style="max-height:26vh">（点击读取）</pre>
    </section>
    <section class="section">
      <div class="section-head" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <h2 class="section-title">运行时日志</h2>
          <p class="section-desc">后端 storyteller.log 尾部内容（滚动保留，最多 2 MiB × 3）。</p>
        </div>
        <button class="btn" id="dbg-refresh">刷新</button>
      </div>
      <pre class="log-view" id="dbg-log">加载中…</pre>
    </section>
  `;
  diagLog("调试页已打开");
  $("#dbg-refresh").addEventListener("click", loadDebugLog);
  await loadDebugLog();
  const provBtn = document.getElementById("dbg-provider");
  if (provBtn) provBtn.addEventListener("click", async () => {
    provBtn.disabled = true;
    try {
      const res = await apiGet("diag/runtime");
      const lines = [];
      lines.push(`工作目录: ${res.cwd || "-"}`);
      lines.push(`数据目录: ${res.data_dir || "-"}`);
      lines.push(`配置路径: ${res.config_path || "-"}`);
      (res.providers || []).forEach((p) => {
        lines.push(`[${p.id || "-"}] 模型=${p.model || "-"} 超时=${p.timeout ?? "-"} Key尾号=${p.key_tail || "-"}(${p.key_len ?? 0}位) base=${p.base || "-"}`);
      });
      document.getElementById("dbg-provider-out").textContent = lines.join("\n") || "（无提供商）";
    } catch (err) {
      document.getElementById("dbg-provider-out").textContent = `读取失败：${err.message}`;
    } finally {
      provBtn.disabled = false;
    }
  });
}

/* ------------------------------------------------------------ 拦＆改：模板占位符 */
/* 0.178 起：占位符清单由拦截接口下发（intercept/status.placeholders，16 个，含 {穿搭}/{回复}）；
   此常量仅在后端未返回时兜底（历史 14 个） */
const TEMPLATE_PLACEHOLDERS = ["{人格}", "{当前说话}", "{上下文}", "{当前用户}", "{场合}", "{身份}", "{关系}", "{风格}", "{状态}", "{日程}", "{记忆}", "{天气}", "{见闻}", "{时间}"];

/* 各模块注入占位符提示卡：标明该模块在「最终发送给对话 LLM 的信息格式」里提供哪些占位符 */
const MODULE_PLACEHOLDERS = {
  persona: [{ ph: "{人格}", desc: "你的身份与世界观（人格注入体；为空时兜底 AstrBot 当前默认人格）" }],
  debounce: [
    { ph: "{当前说话}", desc: "防抖合并后的对方内容（防抖最终决定传给对话 LLM 的消息）" },
    { ph: "{上下文}", desc: "该会话最近对话呼应（联动【为你篆刻的历史】时间线）" },
    { ph: "{当前用户}", desc: "当前发送者昵称 + 账号" },
    { ph: "{场合}", desc: "发送场合（私聊 / 群聊）" },
  ],
  identity: [
    { ph: "{身份}", desc: "防认错提醒（区分当前对话对象，别搞混人称；可引用 {当前用户}{场合}）" },
  ],
  relationship: [{ ph: "{关系}", desc: "你与对方的关系档案/好感度" }],
  voice: [{ ph: "{风格}", desc: "你的说话风格档案" }],
  presence: [
    { ph: "{状态}", desc: "你此刻的心情/精力" },
    { ph: "{天气}", desc: "配置的当天天气" },
  ],
  schedule: [{ ph: "{日程}", desc: "今日日程（只注入日程，不含穿搭）" }],
  wardrobe: [{ ph: "{穿搭}", desc: "你当前穿什么（衣柜里选好的；只影响语气气质，不会主动提起）" }],
  mind: [{ ph: "{见闻}", desc: "最近看到的见闻" }],
  memory: [{ ph: "{记忆}", desc: "最近记忆（约定/愿望/回想）" }],
};

function placeholderHintCard(moduleKey) {
  const list = MODULE_PLACEHOLDERS[moduleKey];
  if (!list || !list.length) return "";
  return `
    <div class="ph-hint-card">
      <span class="ph-hint-title">注入占位符</span>
      <span class="ph-hint-item">${list.map((it) => `<span class="ph-hint-chip">${esc(it.ph)}</span><span class="ph-hint-desc">${esc(it.desc)}</span>`).join("")}</span>
    </div>`;
}

async function renderIntercept() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载拦＆改…</div>`;
  let schemaData;
  try {
    schemaData = await apiGet("config/schema");
  } catch (err) {
    if (state.current === "intercept") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "intercept") return;
  // 0.178：占位符清单由后端下发（16 个，含 {穿搭}/{回复}），前端不再硬编码（仅回退用）
  let placeholders = [];
  try {
    const st = await apiGet("intercept/status");
    placeholders = (st && st.placeholders) || [];
  } catch (err) { placeholders = []; }
  state.interceptPlaceholders = placeholders;
  const schema = schemaData.schema || {};
  const values = schemaData.values || {};
  (state.configSchema = state.configSchema || {}).intercept = schema.intercept || {};
  (state.configValues = state.configValues || {}).intercept = values.intercept || {};
  const mSchema = schema.intercept || {};
  const mValues = values.intercept || {};
  const items = mSchema.items || {};
  // 拦截设置：参与总开关用防抖同款大卡（masterSwitch），其余设置项（模板除外）各为一张卡片
  const cards = Object.entries(items)
    .filter(([k]) => k !== "template" && k !== "enabled")
    .sort(([a, ai], [b, bi]) => sortOrderOf(ai) - sortOrderOf(bi) || String(a).localeCompare(String(b)))
    .map(([k, it]) => renderSettingField("intercept", k, it, mValues[k]))
    .join("");
  const itcEnabledHint = (items.enabled && items.enabled.hint) || "";
  view.innerHTML = `
    <div class="intercept-layout">
      <div class="intercept-left">
        <section class="section">
          <div class="section-head">
            <h2 class="section-title">拦截设置</h2>
            <p class="section-desc">对主链对话请求的介入方式；原「设置 → 拦截」子选项卡已移入此处。</p>
          </div>
          ${masterSwitch("itc-enabled", "拦截参与总开关", itcEnabledHint, Boolean(mValues.enabled))}
          <div class="settings-grid compact-grid" id="itc-settings">${cards}</div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">LLM 请求拦截</h3>
            <div style="display:flex;align-items:center;gap:10px">
              <span class="hint">实时</span>
              <button class="btn" id="itc-refresh">刷新</button>
            </div>
          </div>
          <p class="section-desc">拦截时抓到的、将发送给 LLM 的对话请求（记忆总结与插件自调模型不经过此钩子）。</p>
          <div id="itc-llm" class="log-view" style="max-height:30vh">加载中…</div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">用户当前请求</h3>
            <div style="display:flex;align-items:center;gap:10px">
              <span class="hint">实时</span>
              <button class="btn ghost-danger" id="itc-clear">清空记录</button>
            </div>
          </div>
          <p class="section-desc">拦截时获取到的用户当前说的话。</p>
          <div id="itc-user" class="log-view" style="max-height:22vh">加载中…</div>
        </section>
      </div>
      <div class="intercept-right">
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">最终发送给对话 LLM 的信息格式</h3>
            <div style="display:flex;align-items:center;gap:10px">
              <button class="btn" id="itc-save-template">保存模板</button>
            </div>
          </div>
          <p class="section-desc">「接管改换」模式按此模板组装提示词（发送给对话模型时的 system_prompt）；占位符发送前替换为各模块当前内容。</p>
          <div class="ph-chips" id="itc-chips"></div>
          <textarea id="itc-template" class="template-editor" spellcheck="false">${esc(mValues.template || "")}</textarea>
          <div class="field-key">提示：点击占位符插入编辑区；未配置的模块占位符会被替换为空字符串。</div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">最近发送给对话 LLM 的内容</h3>
            <span class="hint">实时</span>
          </div>
          <p class="section-desc">最近一次发给回复 LLM 的完整请求（不区分模式，实时刷新），可确认最近发给 LLM 的是什么。</p>
          <div id="itc-sent" class="log-view" style="max-height:34vh">加载中…</div>
        </section>
      </div>
    </div>
  `;
  bindInterceptSettings();
  bindMasterSwitch("itc-enabled", "intercept", "enabled");
  $("#itc-refresh").addEventListener("click", loadIntercept);
  $("#itc-clear").addEventListener("click", async () => {
    try {
      await apiPost("intercept/clear");
      toast("记录已清空");
      await loadIntercept();
    } catch (err) {
      toast(`清空失败：${err.message}`, "err");
    }
  });
  buildTemplateChips();
  $("#itc-save-template").addEventListener("click", saveInterceptTemplate);
  await loadIntercept();
  await loadSent();
  startPolling("intercept", pollIntervalSec(), async () => {
    await loadIntercept();
    await loadSent();
  });
}

function sortOrderOf(item) {
  if (item && item.type === "bool") return 0;
  if (item && (item.role === "provider" || (Array.isArray(item.options) && item.options.length))) return 1;
  if (item && (item.type === "int" || item.type === "float")) return 2;
  return 3;
}

function bindInterceptSettings() {
  const grid = document.getElementById("itc-settings");
  if (!grid) return;
  grid.querySelectorAll("[data-setting]").forEach((node) => {
    const parts = node.dataset.setting.split(".");
    const module = parts[0];
    const key = parts[1];
    const type = node.dataset.type;
    if (type === "bool") {
      node.addEventListener("change", () => saveConfigValue(module, key, node.checked));
    } else if (type === "option") {
      node.addEventListener("click", () => {
        saveConfigValue(module, key, node.dataset.option);
        grid.querySelectorAll(`[data-setting="${module}.${key}"]`).forEach((n) => n.classList.remove("active"));
        node.classList.add("active");
      });
    } else if (type === "number") {
      node.addEventListener("change", () => saveConfigValue(module, key, Number(node.value)));
    } else if (type === "provider") {
      node.addEventListener("change", () => saveConfigValue(module, key, node.value));
    } else {
      node.addEventListener("change", () => saveConfigValue(module, key, node.value));
    }
  });
}

function buildTemplateChips() {
  const chipNode = document.getElementById("itc-chips");
  if (!chipNode) return;
  // 0.178：优先后端下发（intercept/status.placeholders，16 个），兜底前端常量
  const backendList = (state.interceptPlaceholders && state.interceptPlaceholders.length)
    ? state.interceptPlaceholders.map((p) => (p && typeof p === "object" ? (p.placeholder || p.key || "") : String(p)))
    : [];
  const list = backendList.length ? backendList : TEMPLATE_PLACEHOLDERS;
  chipNode.innerHTML = list.map((p) => `<span class="ph-chip" data-ph="${esc(p)}">${esc(p)}</span>`).join("");
  chipNode.querySelectorAll(".ph-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const el = document.getElementById("itc-template");
      if (!el) return;
      const val = chip.dataset.ph;
      const s = el.selectionStart === null ? el.value.length : el.selectionStart;
      const e = el.selectionEnd === null ? el.value.length : el.selectionEnd;
      el.value = el.value.slice(0, s) + val + el.value.slice(e);
      const npos = s + val.length;
      el.focus();
      try { el.setSelectionRange(npos, npos); } catch (err) { /* 桩环境忽略 */ }
    });
  });
}

async function saveInterceptTemplate() {
  const el = document.getElementById("itc-template");
  if (!el) return;
  try {
    const cur = (state.configValues && state.configValues.intercept) || {};
    await apiPost("config/module/update", { module: "intercept", values: { ...cur, template: el.value } });
    state.configValues = state.configValues || {};
    state.configValues.intercept = { ...cur, template: el.value };
    toast("模板已保存");
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
  }
}

async function loadIntercept() {
  const llmNode = document.getElementById("itc-llm");
  const userNode = document.getElementById("itc-user");
  if (!llmNode || !userNode) return;
  try {
    const llmData = await apiGet("intercept/requests", { limit: 30 });
    const userData = await apiGet("intercept/user_requests", { limit: 30 });
    if (state.current !== "intercept") return;
    const llmItems = llmData.items || [];
    const userItems = userData.items || [];
    llmNode.textContent = llmItems.length
      ? llmItems.map((item) => formatInterceptEntry(item)).join("\n\n" + "─".repeat(48) + "\n\n")
      : "（暂无拦截记录）";
    userNode.textContent = userItems.length
      ? userItems.map((item) => `[${item.time}] ${item.user_name || item.session_id || "?"}：${item.text}`).join("\n")
      : "（暂无用户请求记录）";
  } catch (err) {
    if (state.current !== "intercept") return;
    llmNode.textContent = `加载失败：${err.message}`;
    userNode.textContent = `加载失败：${err.message}`;
  }
}

async function loadSent() {
  const node = document.getElementById("itc-sent");
  if (!node) return;
  try {
    const data = await apiGet("intercept/sent", { limit: 20 });
    if (state.current !== "intercept") return;
    const items = data.items || [];
    node.textContent = items.length
      ? items.map((it) => formatSentEntry(it)).join("\n\n" + "─".repeat(48) + "\n\n")
      : "（暂无发送记录）";
  } catch (err) {
    if (state.current !== "intercept") return;
    node.textContent = `加载失败：${err.message}`;
  }
}

function formatSentEntry(it) {
  const lines = [
    `[${it.time}] ${it.mode || "?"} · ${it.user_name || "?"} · ${it.session_id || "?"}${it.blocked ? " · 已阻断" : ""}`,
  ];
  if (it.note) lines.push(`说明: ${it.note}`);
  if (it.system_prompt) lines.push(`system:\n${it.system_prompt}`);
  if (it.prompt) lines.push(`prompt: ${it.prompt}`);
  if (it.text) lines.push(`回复: ${it.text}`);
  return lines.join("\n");
}


function formatInterceptEntry(item) {
  const lines = [
    `[${item.time}] ${item.user_name || "?"} · ${item.session_id || "?"} · 阻断:${item.blocked ? "是" : "否"}`,
  ];
  if (item.prompt) lines.push(`prompt: ${item.prompt}`);
  if (item.system_prompt) lines.push(`system: ${item.system_prompt}`);
  if (item.image_count) {
    lines.push(`图片数: ${item.image_count}`);
    if (item.image_urls && item.image_urls.length) {
      lines.push(`图片: ${item.image_urls.join(" | ")}`);
    }
  }
  if (item.audio_urls && item.audio_urls.length) lines.push(`音频: ${item.audio_urls.join(" | ")}`);
  if (item.contexts) lines.push(`上下文:\n${item.contexts}`);
  return lines.join("\n");
}

async function loadDebugLog() {
  const node = document.getElementById("dbg-log");
  if (!node) return;
  try {
    const data = await apiGet("logs");
    if (state.current === "debug" && node === document.getElementById("dbg-log")) {
      node.textContent = data.logs || "（日志为空）";
    }
  } catch (err) {
    if (state.current === "debug") {
      node.textContent = `日志加载失败: ${err.message}`;
    }
  }
}

/* 清障页：模块自检（一键全部 / 单项），通过绿、异常红 + 原因 */
const CHECK_CN = {
  config: "配置加载", data_dir: "数据目录", token_store: "Token 记账", ui_state: "界面布局",
  appearance: "外观", presence: "状态", schedule: "日程", emoji: "表情包",
  send_buffer: "发送缓冲", relationship: "关系", persona_voice: "风格 · 人格", mind: "内心世界",
  memory_bridge: "记忆联动", models: "模型配置", bg_tasks: "后台任务", logger: "日志系统",
  llm_fallback: "回退模型 · LLM", llm_presence: "状态 · LLM", llm_schedule: "日程 · LLM",
  llm_mind: "内心 · LLM", llm_proactive: "主动 · LLM", llm_relationship: "关系 · LLM",
  llm_debounce: "防抖 · LLM", llm_intercept: "拦＆改 · LLM", llm_rewrite: "润色 · LLM",
  llm_emoji: "表情包 · LLM", llm_send: "发送 · LLM", llm_memory: "记忆 · LLM",
  llm_voice: "风格 · LLM", llm_persona: "人格 · LLM", llm_wardrobe: "穿搭 · LLM",
  llm_embedding: "记忆 · 嵌入模型",
  platforms: "下游客户端",
};

/* 生图页：后端模式与 API 配置 + 状态 + 试一张 + 最近生成记录 */
async function renderImage() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载生图…</div>`;
  let data;
  try {
    data = await apiGet("image/status");
  } catch (err) {
    if (state.current === "image") view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    return;
  }
  if (state.current !== "image") return;
  let schemaData;
  try {
    schemaData = await apiGet("config/schema");
  } catch (err) { schemaData = null; }
  const schema = (schemaData && schemaData.schema && schemaData.schema.image && schemaData.schema.image.items) || {};
  const values = (schemaData && schemaData.values && schemaData.values.image) || {};
  const st = (data && data.status) || {};
  const records = (data && data.records) || [];
  const field = (k) => renderSettingField("image", k, schema[k] || { description: k, type: "string" }, values[k]);
  view.innerHTML = `
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">生图</h2>
        <p class="section-desc">对话里出现「画一张… / 给我画…」时自动生图并发送（带每日限制）；生成后自动记录记忆时间线与会话历史，不会让上下文断裂。发图有独立超时保护（默认 120s）。</p>
      </div>
      <div class="field-row" style="gap:12px;flex-wrap:wrap">
        <span class="hint">状态：${st.enabled ? "已开启" : "已关闭"} · 后端 ${esc(st.backend || "-")} · 端点 ${Number(st.endpoints_ready || 0)} 就绪 · 今日 ${Number(st.today_count || 0)} 张</span>
        ${st.missing && st.missing.length ? `<span class="hint" style="color:#f97316;font-weight:700">⚠ ${esc(st.missing.join("；"))}</span>` : ""}
      </div>
    </section>
    <div class="rel-layout" style="align-items:flex-start">
      <div class="rel-left" style="flex:0 0 340px">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">试生成一张</h3><span class="hint">直连后端验证</span></div>
          <div class="field">
            <div class="field-title">画面描述<span class="field-key">prompt</span></div>
            <input class="text-input" id="img-test-prompt" placeholder="例如：一只白猫在窗台上晒太阳，水彩风" />
          </div>
          <button class="btn glow" id="img-test-run" style="margin-top:8px">生一张</button>
          <div id="img-test-result" class="hint" style="margin-top:8px">（未生成）</div>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">最近生成</h3><span class="hint">${records.length} 条</span></div>
          ${records.map((r) => `
            <div class="field">
              <div class="hint" style="color:var(--ink)">${esc(String(r.time || ""))} · ${r.ok ? "✅" : "❌"} ${esc(String(r.kind || ""))}</div>
              <div class="hint" style="opacity:.7">${esc(String(r.prompt || ""))}${r.note ? " — " + esc(String(r.note)) : ""}</div>
              <div class="hint" style="opacity:.55">${Number(r.elapsed_ms || 0)}ms</div>
            </div>`).join("") || '<div class="hint">还没有生成记录。</div>'}
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">智能判定</h3><span class="hint">A 规则 → B 仲裁</span></div>
          <div class="setting-card smart-zone">
            ${masterSwitch("img-judge", "智能判定", (schema.judge_enabled && schema.judge_enabled.hint) || "规则+上文未命中时，用轻量 LLM 判断是否想要一张图（如「我那的云怎么样」→「给我看看？」）。未配置/超时=安全回退不拦截聊天。", Boolean(values.judge_enabled), "orange", "实验，慎用")}
            ${field("judge_provider_id")}
            ${field("judge_timeout")}
            ${field("judge_context_count")}
          </div>
        </section>
      </div>
      <div class="rel-center" style="flex:1;min-width:0">
        <section class="panel">
          <div class="panel-head"><h3 class="panel-title">后端与限制</h3><span class="hint">中心</span></div>
          <div class="settings-grid" style="grid-template-columns:1fr 1fr">
            ${field("enabled")}${field("backend")}${field("max_daily")}${field("api_timeout_seconds")}${field("card_provider_id")}
            <div class="setting-card" style="grid-column:1/-1">${field("caption")}</div>
          </div>
          <div class="hint" style="margin-top:10px">后端 <b>api</b> = 独立在线生图 API（真 AI 绘画，推荐）：填下方主端点（base_url / API Key / 模型，OpenAI 兼容或火山 seedream / MiniMax 自动归一化端点），超时默认 120s；失败自动尝试下方备端点。后端 <b>card</b> = AstrBot provider 的 text_to_image（当前渲染 HTML 文字卡片图，免费即时，无需 Key）。</div>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">主端点</h3><span class="hint">独立 API</span></div>
          <div class="settings-grid" style="grid-template-columns:1fr 1fr">
            ${field("api_enabled")}${field("api_base_url")}${field("api_api_key")}${field("api_model")}${field("api_size")}
          </div>
        </section>
        <section class="panel" style="margin-top:16px">
          <div class="panel-head"><h3 class="panel-title">备端点</h3><span class="hint">可选 · 失败自动切换</span></div>
          <div class="settings-grid" style="grid-template-columns:1fr 1fr">
            ${field("api_backup_enabled")}${field("api_backup_base_url")}${field("api_backup_api_key")}${field("api_backup_model")}
          </div>
        </section>
      </div>
    </div>
  `;
  bindSettingsIn(view);
  await bindMasterSwitch("img-judge", "image", "judge_enabled");
  const runBtn = document.getElementById("img-test-run");
  if (runBtn) runBtn.addEventListener("click", async () => {
    const prompt = document.getElementById("img-test-prompt");
    if (!prompt || !prompt.value.trim()) { toast("先填画面描述", "err"); return; }
    runBtn.disabled = true;
    runBtn.textContent = "生成中…（有超时保护）";
    try {
      const res = await apiPost("image/generate", { prompt: prompt.value.trim() });
      const box = document.getElementById("img-test-result");
      if (box && res && res.path) {
        box.innerHTML = `✅ 成功：${esc(String(res.note || ""))}（已保存 ${esc(String(res.path || ""))}）`;
      } else if (box) {
        box.textContent = `❌ ${esc(String((res && res.message) || "生成失败"))}`;
      }
      toast(res && res.path ? "已生成" : "生成失败", res && res.path ? "ok" : "err");
    } catch (err) {
      toast(`生成失败：${err.message}`, "err");
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "生一张";
      renderImage();
    }
  });
}

/* 模型页：全插件模型配置集中点（三栏），与各模块页同一个配置变量（改一处、两处同步更新） */
const MODELS_COLUMNS = [
  {
    title: "回复链路与生成",
    desc: "回复怎么生成、谁来判定；回退模型为全局兜底。",
    groups: [
      ["intercept", "拦＆改", ["provider_id"]],
      ["rewrite", "润色", ["provider_id"]],
      ["pipeline", "回复判定", ["provider_id"]],
      ["send", "抢话裁决", ["interrupt_judge_provider_id"]],
      ["debounce", "防抖智能判断", ["smart_provider_id"]],
      ["emoji", "表情包判定", ["judge_provider_id"]],
    ],
  },
  {
    title: "日常生成",
    desc: "状态 / 日程 / 主动等日常内容由哪些模型生成。",
    groups: [
      ["presence", "状态", ["provider_id"]],
      ["schedule", "日程", ["provider_id"]],
      ["proactive", "主动", ["provider_id"]],
      ["search", "搜索整理", ["provider_id"]],
      ["voice", "风格生成", ["provider_id"]],
      ["persona", "人格生成", ["provider_id"]],
      ["wardrobe", "穿搭生成", ["provider_id"]],
    ],
  },
  {
    title: "内心与记忆",
    desc: "梦境 / 思考 / 日记、长期记忆提炼与识图。",
    groups: [
      ["mind", "内心世界", ["dream_provider_id", "think_provider_id", "diary_provider_id"]],
      ["memory", "记忆", ["embedding_provider_id", "profile_provider_id", "commitment_provider_id"]],
      ["vision", "识图", ["provider_id"]],
    ],
  },
];

async function renderModels() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载模型配置…</div>`;
  let data;
  try {
    data = await apiGet("config/schema");
  } catch (err) {
    if (state.current === "models") {
      view.innerHTML = `<div class="section"><p class="section-desc">加载失败：${esc(err.message)}</p></div>`;
    }
    return;
  }
  if (state.current !== "models") return;
  state.configSchema = data.schema || {};
  state.configValues = data.values || {};
  applyAnimationSettings();
  const schema = state.configSchema;
  const values = state.configValues;
  const itemOf = (m, k) => (schema[m] && schema[m].items && schema[m].items[k]) || {};
  const valOf = (m, k) => (values[m] || {})[k];
  const field = (m, k) => renderSettingField(m, k, itemOf(m, k), valOf(m, k));
  // 回退模型：左上重点卡（红色边线 + 橙色背景板）
  const fallbackCard = `
    <section class="section models-fallback">
      <div class="section-head">
        <h2 class="section-title">回退模型</h2>
        <span class="hint">全局兜底 · 优先确认</span>
      </div>
      <p class="section-desc">开启「留空回退模型」后，所有未配置专属模型的模块统一走这里；关闭时未配置专属模型的调用会被驳回。</p>
      <div class="settings-grid" style="grid-template-columns:1fr">
        ${field("models", "fallback_enabled")}
        ${field("models", "fallback_provider_id")}
      </div>
    </section>`;
  // 三栏：每组一个小标题 + 该模块全部模型设置项（与各模块页同一变量，改哪边都同步）
  const column = (col) => `
    <section class="panel">
      <div class="panel-head"><h3 class="panel-title">${esc(col.title)}</h3><span class="hint">${col.groups.length} 个模块</span></div>
      <p class="section-desc">${esc(col.desc || "")}</p>
      ${col.groups.map(([m, name, keys]) => `
        <div class="model-group-title">${esc(name)}<span class="field-key">${esc(m)}</span></div>
        <div class="settings-grid" style="grid-template-columns:1fr">
          ${keys.map((k) => field(m, k)).join("")}
        </div>`).join("")}
    </section>`;
  view.innerHTML = `
    ${placeholderHintCard("models")}
    <div class="models-layout">
      <div class="models-col">
        ${fallbackCard}
        ${column(MODELS_COLUMNS[0])}
      </div>
      <div class="models-col">${column(MODELS_COLUMNS[1])}</div>
      <div class="models-col">${column(MODELS_COLUMNS[2])}</div>
    </div>
    <div class="hint" style="margin-top:14px">本页是<b>模型配置集中点</b>：与各模块页共用同一组配置变量，在模块页或本页修改都会保存到同一个位置、两处同步生效。生成参数（流式 / 超时 / 预算）仍在「设置 → 模型配置」。</div>
  `;
  bindSettingsIn(view);
}

async function renderTroubleshoot() {
  const view = $("#view");
  view.innerHTML = `<div class="loading">加载清障清单…</div>`;
  let data;
  try {
    data = await apiGet("diag/checks");
  } catch (err) {
    if (state.current === "troubleshoot") view.innerHTML = `<div class="section"><p class="section-desc">自检加载失败：${esc(err.message)}</p></div>`;
    return;
  }
  if (state.current !== "troubleshoot") return;
  const checks = data.checks || []; // 定义（无结果）——LLM 项默认未检测，仅点击测试才执行
  // 保留已有测试结果（state.checkResults 不清空，重复进入页面/翻页刷新不丢）
  if (!state.checkResults) state.checkResults = {};
  state.checkDefs = {};
  checks.forEach((c) => { state.checkDefs[c.key] = c; });
  const schema = state.configSchema || {};
  const values = state.configValues || {};
  const tsItems = (schema.troubleshoot && schema.troubleshoot.items) || {};
  const tsVal = (k, fb) => ((values.troubleshoot || {})[k] ?? fb);
  const renderResults = () => {
    const list = checks.map((c) => {
      const r = state.checkResults[c.key];
      const block = !r ? '<div class="check-result idle">未检测</div>'
        : (r.running ? '<div class="check-result idle">检测中…</div>'
          : (r.ok
              ? `<div class="check-result ok"><b>功能正常</b>${r.detail ? `<div class="hint" style="margin-top:2px">${esc(String(r.detail))}</div>` : ""}</div>`
              : `<div class="check-result fail"><b>存在故障</b><div class="hint" style="margin-top:2px">${esc(String(r.detail || ""))}</div></div>`));
      return `
        <div class="check-row">
          <div class="check-top">
            <div class="check-left">
              <div class="field-title">${esc(c.name)}</div>
              <div class="hint">${esc(c.desc || "")}</div>
            </div>
            <button class="btn" data-check-key="${esc(c.key)}">测试</button>
          </div>
          ${block}
        </div>`;
    }).join("");
    const failed = checks.filter((c) => state.checkResults[c.key] && state.checkResults[c.key].ok === false);
    const lluFailed = failed.filter((c) => c.key.startsWith("llm_"));
    const summary = failed.length
      ? `<div class="check-summary-card fail"><b>有 ${failed.length} 项异常</b><div class="hint" style="margin-top:3px">${esc(failed.map((c) => c.name).join("、"))}</div></div>`
      : (Object.keys(state.checkResults).length
          ? `<div class="check-summary-card ok"><b>已测项目全部通过</b><div class="hint" style="margin-top:3px">LLM 项未测不计入（${lluFailed.length ? "「一键 LLM 测试」报告异常项" : "等待「一键 LLM 测试」或逐项点击测试"})</div></div>`
          : "（尚未执行任何测试）");
    return { list, summary };
  };
  const { list, summary } = renderResults();
  view.innerHTML = `
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">清障 · 模块自检</h2>
        <p class="section-desc">只读检查：不调 LLM、不发消息、不改数据；<b>LLM 项默认不测试</b>（真实最小对话，少量消耗），请逐项点击测试或用「一键 LLM 测试」依次串行检测。</p>
      </div>
      <div class="field-row" style="justify-content:flex-start;gap:14px;flex-wrap:wrap">
        <button class="btn glow" id="check-all">一键只读测试</button>
        <button class="btn glow" id="check-llm-all" style="background:linear-gradient(135deg,#f97316,#fbbf24);border-color:transparent;color:#fff">一键 LLM 测试</button>
        ${renderSettingField("troubleshoot", "llm_test_timeout", tsItems.llm_test_timeout || { description: "LLM 测试超时（秒）", type: "int", default: 15 }, tsVal("llm_test_timeout", 15))}
        ${summary}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h3 class="panel-title">模块清单</h3><span class="hint">${checks.length} 项</span></div>
      <div id="check-list" class="check-grid">${list}</div>
    </section>
  `;
  const runSingle = async (key, btn) => {
    if (btn) { btn.disabled = true; }
    state.checkResults[key] = { ...(state.checkResults[key] || {}), running: true };
    renderListOnly();
    try {
      const out = await apiPost("diag/check", { key });
      const r = (out && out.check) || null;
      state.checkResults[key] = r;
    } catch (err) {
      state.checkResults[key] = { key, name: CHECK_CN[key] || key, ok: false, detail: `接口调用失败：${err.message}` };
    }
    if (btn) { btn.disabled = false; }
    rerenderAll();
  };
  const runReadAll = async () => {
    const btn = document.getElementById("check-all");
    if (btn) { btn.disabled = true; btn.textContent = "检测中…"; }
    try {
      const out = await apiPost("diag/run");
      const rs = ((out && out.checks) || []);
      rs.forEach((r) => { state.checkResults[r.key] = r; });
      rerenderAll();
    } catch (err) {
      toast(`检测失败：${err.message}`, "err");
    }
    if (btn) { btn.disabled = false; btn.textContent = "一键只读测试"; }
  };
  const runLlmAll = async () => {
    const btn = document.getElementById("check-llm-all");
    let timer = null;
    let sec = 0;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "测试中…（依次）已 0s";
      timer = setInterval(() => {
        sec += 1;
        const cur = document.getElementById("check-llm-all");
        if (cur) cur.textContent = `测试中…（依次）已 ${sec}s`;
      }, 1000);
    }
    try {
      const out = await apiPost("diag/llm_test");
      const rs = ((out && out.checks) || []);
      rs.forEach((r) => { state.checkResults[r.key] = r; });
      const failed = rs.filter((r) => !r.ok);
      if (failed.length) toast(`LLM 测试完成：${failed.length} 项异常（${failed.map((f) => f.name).join("、")}）`, "err");
      else toast("LLM 测试完成：全部通过");
      rerenderAll();
    } catch (err) {
      toast(`LLM 测试失败：${err.message}`, "err");
    } finally {
      if (timer) clearInterval(timer);
      const cur = document.getElementById("check-llm-all");
      if (cur) { cur.disabled = false; cur.textContent = "一键 LLM 测试"; }
    }
  };
  const renderListOnly = () => {
    const node = document.getElementById("check-list");
    if (!node) return;
    const { list } = renderResults();
    node.innerHTML = list;
    bindSingleButtons();
  };
  const rerenderAll = () => {
    if (state.current === "troubleshoot") renderTroubleshoot();
  };
  const bindSingleButtons = () => {
    document.querySelectorAll("[data-check-key]").forEach((node) => {
      node.addEventListener("click", () => runSingle(node.dataset.checkKey, node));
    });
  };
  bindSingleButtons();
  const allBtn = document.getElementById("check-all");
  if (allBtn) allBtn.addEventListener("click", runReadAll);
  const llmBtn = document.getElementById("check-llm-all");
  if (llmBtn) llmBtn.addEventListener("click", runLlmAll);
  bindSettingsIn(view);
}

/* 鸣谢页：静态人物卡（与记忆插件一致，无点击交互；保留悬停光影） */
async function renderThanks() {
  const view = $("#view");
  const images = {};
  try {
    const data = await apiGet("thanks/images");
    Object.assign(images, ((data && data.images) || {}));
  } catch (err) {
    diagLog(`鸣谢头像加载失败: ${err.message}`);
  }
  const cards = [
    { imgKey: "DS", name: "deepseek（辅助创作者）", desc: "一只爱吃白饭的蓝色大肥鱼" },
    { imgKey: "QED", name: "证毕（杂鱼）", desc: "喵喵喵~" },
    { imgKey: "SO2", name: "二氧化硫（笨蛋）", desc: "！？电电？！" },
  ];
  view.innerHTML = `
    <div class="section">
      <div class="thanks-hero">
        <div class="thanks-title">鸣谢</div>
        <div class="thanks-tagline">这里是只会用 AI 写插件的屑创作者，和他参与测试的朋友们~！</div>
      </div>
      <div class="thanks-row" style="display:flex;flex-wrap:wrap;gap:16px;margin-top:20px">
        ${cards.map((c) => `
          <section class="thanks-card" style="flex:1 1 300px;min-width:280px;height:120px;box-sizing:border-box;display:flex;align-items:center;gap:16px;padding:16px 20px;border:1px solid var(--line);border-left:3px solid color-mix(in srgb, var(--glow-b) 65%, transparent);border-radius:6px;overflow:hidden;color:var(--ink);background:color-mix(in srgb, var(--glow-b) 4%, var(--bg));transition:transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease">
            ${images[c.imgKey]
              ? `<img class="thanks-avatar" src="${esc(images[c.imgKey])}" alt="${esc(c.name)}" style="width:76px;height:76px;flex-shrink:0;border-radius:12px;object-fit:cover;border:1px solid color-mix(in srgb, var(--glow-b) 30%, var(--line))" />`
              : `<div style="width:76px;height:76px;flex-shrink:0;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--ink-3);font-weight:800;font-size:14px;border:1px solid color-mix(in srgb, var(--glow-b) 30%, var(--line))">${esc(c.imgKey)}</div>`}
            <div style="flex:1;min-width:0">
              <div style="font-size:15px;font-weight:700;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(c.name)}">${esc(c.name)}</div>
              <div style="font-size:14px;color:var(--ink-2);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(c.desc)}">${esc(c.desc)}</div>
            </div>
          </section>`).join("")}
      </div>
      <div class="thanks-footer">插件由 opencode 与 DSH 协同实现，AI 还是太好用辣！</div>
    </div>
  `;
}

async function renderOverview() {
  const view = $("#view");
  const health = state.health || {};
  const themeName = THEMES.find((t) => t.key === (state.appearance && state.appearance.theme));
  // 并行取 Bot 当前状态 / 当前活动 / token 总消耗（任一失败静默降级）
  let presence = null, schedule = null, tokenData = null;
  try {
    const [p, sc, tk] = await Promise.all([
      apiGet("presence").catch(() => null),
      apiGet("schedule").catch(() => null),
      apiGet("token/stats").catch(() => null),
    ]);
    presence = p;
    schedule = sc;
    tokenData = tk;
  } catch (err) {
    diagLog(`总览附加数据加载失败: ${err.message}`);
  }
  const pv = (presence && presence.presence) || null;
  const moodText = (pv && pv.mood) || (pv ? "平稳" : "");
  // 0.156：与「状态」页同一口径——调子/转速按 -1..1、电量按 0..1 归一化为 0-100%
  //（此前直接值×100：负值 clamp 成 0%，状态页 50% 而总览 0%，两处对不上）
  const pct = (v, lo = 0, hi = 1) => {
    const num = Number(v);
    if (!Number.isFinite(num)) return 0;
    return Math.max(0, Math.min(100, Math.round(((num - lo) / (hi - lo)) * 100)));
  };
  const pctTone = (v) => pct(v, -1, 1);
  const pctTempo = (v) => pct(v, -1, 1);
  const pctBattery = (v) => pct(v, 0, 1);
  const activity = (schedule && schedule.diagnostic && schedule.diagnostic.current_activity) || "";
  const tkStats = (tokenData && tokenData.stats) || null;
  const tkMemory = (tokenData && tokenData.memory) || null;
  const companionTotal = Number((((tkStats || {}).total || {}).sum) || 0);
  const memoryTotal = tkMemory ? Number((((tkMemory).total || {}).sum) || 0) : null;
  // 模型链预警（0.147）：回退模型与接管模型均为空 & 默认接管改换 → 提示用户配置
  const cfgV = state.configValues || {};
  const fbId = String((cfgV.models || {}).fallback_provider_id || "").trim();
  const tkId = String((cfgV.intercept || {}).provider_id || "").trim();
  const itcMode = String((cfgV.intercept || {}).mode || "接管改换");
  const modelWarning = (!fbId && !tkId) ? `
    <section class="overview-warn" style="margin-top:16px">
      <b>⚠ 尚未配置模型</b> — 当前「${esc(itcMode)}」模式下，接管请求将按「接管失败时」策略处理（默认降级放行主链，Bot 仍会回复但不定制拟人化）。到<b>「模型」</b>页配置回退模型即可获得完整拟人化效果。
    </section>` : "";
  view.innerHTML = `
    <div class="hero">
      <div class="eyebrow">Storyteller Companion</div>
      <h1>为你续写的故事</h1>
      <p>赐予真正的陪伴和生命——这是我们共同的愿望。</p>
      <div class="hero-stats">
        <div class="hero-stat">
          <div class="k">插件版本</div>
          <div class="v flow">${esc(health.version || "-")}</div>
        </div>
        <div class="hero-stat">
          <div class="k">外观主题</div>
          <div class="v flow">${esc(themeName ? themeName.name : "潮汐")}</div>
        </div>
        <div class="hero-stat">
          <div class="k">数据目录</div>
          <div class="v" style="font-size:13px;padding-top:4px">${esc(health.data_dir || "-")}</div>
        </div>
      </div>
    </div>
    <div class="overview-grid">
      <section class="panel overview-card">
        <div class="panel-head"><h3 class="panel-title">Bot 当前状态</h3>${moodText ? `<span class="hint">${esc(moodText)}</span>` : ""}</div>
        ${pv ? `
          <div class="field">
            <div class="field-row"><div class="field-title">调子</div><div class="hint">${pctTone(pv.tone)}%</div></div>
            <div class="progress"><div class="progress-fill" style="width:${pctTone(pv.tone)}%"></div></div>
          </div>
          <div class="field">
            <div class="field-row"><div class="field-title">转速</div><div class="hint">${pctTempo(pv.tempo)}%</div></div>
            <div class="progress"><div class="progress-fill" style="width:${pctTempo(pv.tempo)}%"></div></div>
          </div>
          <div class="field">
            <div class="field-row"><div class="field-title">电量</div><div class="hint">${pctBattery(pv.battery)}%</div></div>
            <div class="progress"><div class="progress-fill" style="width:${pctBattery(pv.battery)}%"></div></div>
          </div>
          ${activity ? `<div class="hint" style="margin-top:8px">此刻在做：${esc(activity)}</div>` : ""}
        ` : '<div class="hint">状态数据暂不可用。</div>'}
      </section>
      <section class="panel overview-card">
        <div class="panel-head"><h3 class="panel-title">Token 总消耗</h3><span class="hint">累计</span></div>
        <div class="field">
          <div class="field-row">
            <div class="field-title" style="font-size:18px">${(companionTotal).toLocaleString()}</div>
            <div class="hint">为你续写的故事</div>
          </div>
        </div>
        <div class="field">
          <div class="field-row">
            <div class="field-title" style="font-size:18px">${memoryTotal === null ? "未联动" : (memoryTotal).toLocaleString()}</div>
            <div class="hint">记忆插件（为你篆刻的历史）</div>
          </div>
        </div>
        <div class="hint" style="margin-top:8px">详细来源与任务分布见 Token 页。</div>
      </section>
    </div>
    ${modelWarning}
  `;
}

function renderAppearance() {
  const view = $("#view");
  const a = state.appearance || {};
  const mode = resolveMode(a.scheme);
  const vars = themeVars(a.theme || "tide", mode);
  const canvasOn = Boolean(a.canvas_enabled);
  view.innerHTML = `
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">配色主题</h2>
        <p class="section-desc">八套空灵色调，随心情换一身。</p>
      </div>
      <div class="dots">
        ${THEMES.map((t) => `
          <div class="dot-cell ${t.key === (a.theme || "tide") ? "active" : ""}" data-theme="${t.key}">
            <div class="dot" style="--sw-a:${t.sw[0]};--sw-b:${t.sw[1]}"></div>
            <div class="dot-tag">${t.name}</div>
          </div>
        `).join("")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2 class="section-title">明暗模式</h2>
        <p class="section-desc">跟随系统，或自己掌控光。</p>
      </div>
      <div class="pill-rows">
        ${SCHEMES.map((s) => `
          <div class="pill ${s.key === (a.scheme || "auto") ? "active" : ""}" data-scheme="${s.key}">${s.label}</div>
        `).join("")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2 class="section-title">自定义颜色</h2>
        <p class="section-desc">留空则跟随当前主题，也可一键恢复。</p>
      </div>
      ${colorField("primary", "主色", a.primary || "", vars.glowA)}
      <div style="margin-top:14px"></div>
      ${colorField("accent", "辅色", a.accent || "", vars.glowB)}
    </section>

    <section class="section">
      <div class="section-head">
        <h2 class="section-title">背景板</h2>
        <p class="section-desc">${canvasOn ? "背景板已启用：底色、透明度与模糊均生效。" : "背景板未启用：页面使用主题默认底色；开启后颜色与效果才生效。"}</p>
      </div>
      <div class="pill-rows">
        <div class="pill ${canvasOn ? "on" : ""}" data-canvas-toggle>${canvasOn ? "背景效果已开启" : "背景效果未启用"}</div>
      </div>
      <p class="hint" style="margin-top:12px">选择背景色、调整透明度/模糊或上传背景图时会自动开启；点开关可手动控制。</p>
      <div class="canvas-controls ${canvasOn ? "" : "controls-muted"}" data-canvas-wrap>
        <div class="color-row" style="margin-top:18px">
          ${colorField("canvas", "背景色", a.canvas || "", vars.bg)}
        </div>
        <div class="slider-field">
          <div class="row">
            <span class="label">透明度</span>
            <span class="val" data-val="opacity">${Math.round((a.canvas_opacity ?? 0.8) * 100)}%</span>
          </div>
          <input type="range" data-range="opacity" min="0" max="1" step="0.05" value="${a.canvas_opacity ?? 0.8}" />
        </div>
        <div class="slider-field">
          <div class="row">
            <span class="label">模糊（玻璃拟态）</span>
            <span class="val" data-val="blur">${a.canvas_blur ?? 0}px</span>
          </div>
          <input type="range" data-range="blur" min="0" max="60" step="1" value="${a.canvas_blur ?? 0}" />
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2 class="section-title">背景图片</h2>
        <p class="section-desc">壁纸库最多保存 5 张，超出自动丢弃最早一张；点击缩略图切换。</p>
      </div>
      <div class="pill-rows">
        <label class="btn glow">上传新壁纸<input class="file-trigger" type="file" id="bg-file" accept="image/png,image/jpeg,image/gif,image/webp,image/bmp" /></label>
        <button class="btn ghost-danger" id="bg-clear" ${a.canvas_hash ? "" : "disabled"}>删除当前壁纸</button>
      </div>
      <div class="bg-grid" id="bg-grid">
        ${(a.bg_library || []).map((item) => `
          <div class="bg-cell ${item.hash === a.canvas_hash ? "active" : ""}" data-bg-hash="${esc(item.hash)}" title="${esc(item.name)}">
            <img src="${item.thumb || ""}" alt="${esc(item.name)}" loading="lazy" />
            ${item.hash === a.canvas_hash ? '<div class="bg-cur">当前</div>' : ""}
          </div>
        `).join("")}
        ${(a.bg_library || []).length === 0 ? '<div class="bg-empty">尚未上传背景图片</div>' : ""}
      </div>
      <div class="bg-preview" id="bg-preview" style="${a.bg_data_url ? `background-image:url('${a.bg_data_url}')` : ""}">
        ${a.bg_data_url ? `<div class="tag">已启用 · ${esc(a.canvas_hash || "")}</div>` : ""}
      </div>
    </section>

    <section class="section foot">
      <button class="btn" id="appearance-reset">恢复默认外观</button>
    </section>
    <section class="section">
      <div class="section-head">
        <h2 class="section-title">页面动画设置</h2>
        <p class="section-desc">主题切换与页面滑入的动画效果（原「设置 → 基础」已按模块化迁入此处）。</p>
      </div>
      <div class="settings-grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
        ${renderSettingField("general", "page_animation", (state.configSchema && state.configSchema.general && state.configSchema.general.items && state.configSchema.general.items.page_animation) || { description: "页面动画", type: "bool", default: true }, (state.configValues && state.configValues.general ? state.configValues.general.page_animation : undefined))}
        ${renderSettingField("general", "animation_type", (state.configSchema && state.configSchema.general && state.configSchema.general.items && state.configSchema.general.items.animation_type) || { description: "动画类型", type: "string", options: ["fade", "rise", "zoom", "slide", "none"], default: "rise" }, (state.configValues && state.configValues.general ? state.configValues.general.animation_type : undefined))}
        ${renderSettingField("general", "animation_duration", (state.configSchema && state.configSchema.general && state.configSchema.general.items && state.configSchema.general.items.animation_duration) || { description: "动画时长(ms)", type: "int", default: 400 }, (state.configValues && state.configValues.general ? state.configValues.general.animation_duration : undefined))}
      </div>
      ${renderSettingField("general", "log_poll_interval", (state.configSchema && state.configSchema.general && state.configSchema.general.items && state.configSchema.general.items.log_poll_interval) || { description: "日志面板刷新间隔(ms)", type: "int", default: 1000 }, (state.configValues && state.configValues.general ? state.configValues.general.log_poll_interval : undefined))}
    </section>
  `;
  bindAppearanceEvents();
  bindSettingsIn(view);
}

function colorField(field, label, currentValue, fallback) {
  return `
    <div class="color-row">
      <div class="color-field">
        <div class="swatch-btn" style="--sw-c:${normalizeColor(currentValue || fallback)}">
          <input type="color" data-custom="${field}" value="${normalizeColor(currentValue || fallback)}" />
        </div>
        <div class="label">${label}</div>
        <input class="text-input" type="text" data-text="${field}" value="${esc(currentValue)}" placeholder="跟随主题" />
        <button class="btn" data-reset="${field}" title="恢复为跟随主题">恢复</button>
      </div>
    </div>
  `;
}

function normalizeColor(value) {
  const match = String(value || "").match(/^#([0-9a-fA-F]{6})$/);
  return match ? `#${match[1].toLowerCase()}` : "#14b8a6";
}

function bindAppearanceEvents() {
  $("#view").querySelectorAll("[data-theme]").forEach((node) => {
    node.addEventListener("click", () => setAppearance({ theme: node.dataset.theme }));
  });

  $("#view").querySelectorAll("[data-scheme]").forEach((node) => {
    node.addEventListener("click", () => setAppearance({ scheme: node.dataset.scheme }));
  });

  $("#view").querySelectorAll("[data-custom]").forEach((node) => {
    node.addEventListener("input", () => {
      applyAppearance({ ...state.appearance, [node.dataset.custom]: node.value });
    });
    node.addEventListener("change", () => {
      const field = node.dataset.custom;
      const patch = { [field]: node.value };
      if (field === "canvas" && node.value) patch.canvas_enabled = true;
      setAppearance(patch);
    });
  });

  $("#view").querySelectorAll("[data-text]").forEach((node) => {
    node.addEventListener("change", () => {
      const field = node.dataset.text;
      const value = node.value.trim();
      if (!value) {
        setAppearance({ [field]: "" });
        return;
      }
      if (/^#[0-9a-fA-F]{6}$/.test(value)) {
        setAppearance({ [field]: value.toLowerCase() });
      } else {
        toast("颜色格式应为 #RRGGBB", "err");
      }
    });
  });

  $("#view").querySelectorAll("[data-reset]").forEach((node) => {
    node.addEventListener("click", () => setAppearance({ [node.dataset.reset]: "" }));
  });

  const canvasToggle = $("#view [data-canvas-toggle]");
  if (canvasToggle) {
    canvasToggle.addEventListener("click", () => {
      const currentlyOn = Boolean(state.appearance && state.appearance.canvas_enabled);
      setAppearance({ canvas_enabled: !currentlyOn });
    });
  }

  $("#view").querySelectorAll("[data-range]").forEach((node) => {
    const field = node.dataset.range;
    const paintFill = () => {
      const ratio = field === "opacity"
        ? parseFloat(node.value || "0")
        : parseInt(node.value || "0", 10) / 60;
      const pct = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
      const glow = getComputedStyle(document.documentElement).getPropertyValue("--glow-a").trim() || "#14b8a6";
      const line = getComputedStyle(document.documentElement).getPropertyValue("--line").trim() || "rgba(22,74,82,0.12)";
      node.style.background = `linear-gradient(90deg, ${glow} ${pct}%, ${line} ${pct}%)`;
    };
    paintFill();
    node.addEventListener("input", () => {
      const value = field === "opacity" ? parseFloat(node.value) : parseInt(node.value, 10);
      applyAppearance({ ...state.appearance, [field === "opacity" ? "canvas_opacity" : "canvas_blur"]: value });
      const label = $("#view").querySelector(`[data-val="${field}"]`);
      if (label) label.textContent = field === "opacity" ? `${Math.round(value * 100)}%` : `${value}px`;
      paintFill();
    });
    node.addEventListener("change", () => {
      const value = field === "opacity" ? parseFloat(node.value) : parseInt(node.value, 10);
      setAppearance({ [field === "opacity" ? "canvas_opacity" : "canvas_blur"]: value, canvas_enabled: true });
    });
  });

  $("#view").querySelectorAll("[data-bg-hash]").forEach((node) => {
    node.addEventListener("click", async () => {
      try {
        await apiPost("appearance/background/select", { hash: node.dataset.bgHash });
        await loadAppearance();
        render();
        toast("壁纸已切换");
      } catch (err) {
        toast(err.message || "切换失败", "err");
      }
    });
  });

  const fileInput = $("#bg-file");
  if (fileInput) {
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      diagLog(`上传选中: ${file.name} (${file.size}B)`);
      toast(`正在上传 ${file.name}…`);
      try {
        const result = await bridge.upload("appearance/background", file);
        diagLog(`上传成功: ${JSON.stringify(result).slice(0, 100)}`);
        toast("壁纸已加入库并启用");
        await loadAppearance();
        render();
      } catch (err) {
        diagLog(`上传失败: ${err.message}`);
        toast(`上传失败：${err.message || "未知错误"}`, "err");
        fileInput.value = "";
      }
    });
  }

  $("#bg-clear").addEventListener("click", () => {
    confirmDialog("删除当前壁纸", "将从壁纸库中删除当前选中的背景图；其余壁纸不受影响。", async () => {
      try {
        await apiPost("appearance/background/clear");
        await loadAppearance();
        render();
        toast("壁纸已删除");
      } catch (err) {
        toast(err.message || "删除失败", "err");
      }
    });
  });

  $("#appearance-reset").addEventListener("click", () => {
    confirmDialog("恢复默认外观", "将恢复全部外观设置为默认值（保留已上传的背景图片）。", async () => {
      await apiPost("appearance/reset");
      await loadAppearance();
      render();
      toast("外观已恢复默认");
    });
  });
}

/* ------------------------------------------------------------- 启动 */

async function boot() {
  diagLog("页面启动");
  try {
    await bridge.ready();
    diagLog("bridge ready 完成");
  } catch (e) {
    diagLog(`bridge ready 异常: ${e.message}`);
  }
  await loadTabOrder();
  renderNav();
  try {
    await Promise.all([loadHealth(), loadAppearance()]);
  } catch (e) {
    diagLog(`初始化加载失败: ${e.message}`);
  }
  try {
    const configData = await apiGet("config/schema");
    state.configSchema = configData.schema || {};
    state.configValues = configData.values || {};
    applyAnimationSettings();
    diagLog("配置已加载");
  } catch (e) {
    diagLog(`配置加载失败: ${e.message}`);
  }
  try {
    const [chatData, embData] = await Promise.all([
      apiGet("models/providers").catch(() => ({ providers: [] })),
      apiGet("models/providers", { kind: "embedding" }).catch(() => ({ providers: [] })),
    ]);
    state.providers = chatData.providers || [];
    state.embeddingProviders = embData.providers || [];
    diagLog(`模型列表已加载: LLM ${state.providers.length} 个 / 嵌入 ${state.embeddingProviders.length} 个`);
  } catch (e) {
    state.providers = [];
    state.embeddingProviders = [];
    diagLog(`模型列表加载失败: ${e.message}`);
  }
  try {
    await render();
    diagLog("初始化完成");
  } catch (err) {
    diagLog(`初始化 render 异常: ${err.message} @ ${err.stack ? err.stack.split("\n")[1] || "" : ""}`);
  }
}

boot();
