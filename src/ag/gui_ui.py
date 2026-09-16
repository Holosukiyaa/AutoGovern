"""AG2C WebView 壳搬过来：三区 + 文件树 + 检查器。数据是探针，不是知识卡。"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<title>ag</title>
<link rel="stylesheet" href="/ui/layout.css">
</head>
<body>
<header id="bar">
  <div class="brand">ag</div>
  <label class="field">项目
    <select id="project"></select>
  </label>
  <button type="button" id="refresh">刷新</button>
  <button type="button" id="run">跑探针</button>
  <button type="button" id="checkup">反向开发插针</button>
  <span id="gate" class="gate"></span>
  <span id="status" class="status"></span>
</header>
<nav id="tree">
  <h2>探针</h2>
  <input id="tree-filter" type="search" placeholder="筛选路径">
  <ul></ul>
</nav>
<main id="home">
  <p id="attention" class="hero">加载中…</p>
  <section id="action">
    <header class="zone-head"><h2>要你处理</h2><button type="button" data-copy="actions">复制给 AI</button></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
  <section id="alert">
    <header class="zone-head"><h2>系统警情</h2><button type="button" data-copy="alerts">复制给 AI</button></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
  <section id="record">
    <header class="zone-head"><h2>记录</h2></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
</main>
<aside id="inspect">
  <h2>这根针能说什么</h2>
  <p id="inspect-title">点左侧探针</p>
  <dl id="inspect-fields"></dl>
</aside>
<footer id="ops">
  <div class="tabs">
    <button type="button" class="on">追责证据</button>
    <button type="button" id="copy-ops">复制</button>
  </div>
  <div id="ops-body" class="ops-panel"></div>
</footer>
<script src="/ui/app.js"></script>
</body>
</html>
"""

LAYOUT_CSS = """:root {
  --danger: #f24c40;
  --decision: #f2b340;
  --notice: #b38738;
  --ok: #66946b;
  --muted: #8a8a92;
  --bg: #161618;
  --panel: #1e1e22;
  --fg: #ececec;
  --line: #2c2c32;
  --hover: #26262c;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); font: 14px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif; }
body {
  display: grid;
  grid-template:
    "bar bar bar" auto
    "tree home inspect" 1fr
    "ops ops ops" minmax(10rem, 28%)
    / 28% 1fr 28%;
}
button, select, input {
  font: inherit;
  color: var(--fg);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
}
button { cursor: pointer; padding: 0.25rem 0.7rem; }
button:hover, select:hover { background: var(--hover); }
#bar {
  grid-area: bar;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.9rem;
  border-bottom: 1px solid var(--line);
  background: #121214;
}
.brand { font-weight: 650; letter-spacing: 0.02em; }
.field { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); }
.field select { min-width: 18rem; padding: 0.2rem 0.4rem; }
.gate.warn { color: var(--danger); }
.gate { color: var(--ok); }
.status { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
#tree, #inspect { background: var(--panel); overflow: auto; padding: 0.7rem 0.8rem; }
#tree { grid-area: tree; border-right: 1px solid var(--line); }
#inspect { grid-area: inspect; border-left: 1px solid var(--line); }
#home { grid-area: home; overflow: auto; padding: 0.4rem 0 1rem; }
#ops { grid-area: ops; border-top: 1px solid var(--line); background: #121214; display: flex; flex-direction: column; min-height: 0; }
h2 { color: var(--muted); font-size: 0.78rem; font-weight: 650; letter-spacing: 0.08em; margin: 0 0 0.45rem; }
#tree-filter { width: 100%; margin-bottom: 0.55rem; padding: 0.3rem 0.45rem; }
#tree ul, #home ul { list-style: none; margin: 0; padding: 0; }
#tree li {
  padding: 0.28rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
#tree li:hover, #tree li.active { background: var(--hover); }
.hero {
  margin: 0.7rem 1rem 0.4rem;
  font-size: 1.45rem;
  font-weight: 650;
  line-height: 1.25;
}
section { padding: 0.55rem 1rem 0.2rem; }
.zone-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.35rem; }
.zone-head h2 { margin: 0; }
#home li { padding: 0.35rem 0; border-bottom: 1px solid var(--line); cursor: pointer; }
#home li.error { color: var(--danger); }
#home li.warn { color: var(--decision); }
#home li.ok { color: var(--ok); }
.empty { color: var(--muted); margin: 0.2rem 0 0.6rem; }
section.is-ready:not(.is-empty) .empty { display: none; }
section.is-ready.is-empty ul { display: none; }
#inspect-title { margin: 0 0 0.6rem; font-weight: 650; }
#inspect-fields { margin: 0; }
#inspect-fields dt { color: var(--muted); font-size: 0.75rem; margin-top: 0.55rem; }
#inspect-fields dd { margin: 0.15rem 0 0; word-break: break-all; }
.tabs { display: flex; gap: 0.35rem; padding: 0.45rem 0.75rem; border-bottom: 1px solid var(--line); }
#copy-ops { margin-left: auto; }
.ops-panel { flex: 1; overflow: auto; padding: 0.6rem 0.85rem; white-space: pre-wrap; font-family: ui-monospace, Consolas, monospace; font-size: 0.82rem; color: #d7d7dc; }
.muted { color: var(--muted); }
@media (max-width: 900px) {
  body { grid-template: "bar" auto "home" 1fr "ops" minmax(8rem, 34%) / 1fr; }
  #tree, #inspect { display: none; }
}
"""

APP_JS = """
function fillList(id, rows, emptyText) {
  var section = document.getElementById(id);
  var ul = section.querySelector("ul");
  var empty = section.querySelector(".empty");
  ul.innerHTML = "";
  (rows || []).forEach(function (row) {
    var li = document.createElement("li");
    li.className = row.severity || "";
    li.textContent = row.text || "";
    li.dataset.id = row.id || "";
    li.onclick = function () { inspect(row.id); };
    ul.appendChild(li);
  });
  var vacant = !ul.childElementCount;
  section.classList.add("is-ready");
  section.classList.toggle("is-empty", vacant);
  if (empty) empty.textContent = emptyText || "没有条目。";
}
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text || "");
}
function inspect(id) {
  var model = window.__AG_VIEW || {};
  var item = (model.tree || []).find(function (row) { return row.id === id; });
  document.getElementById("inspect-title").textContent = (item && (item.path || item.note)) || "点左侧探针";
  var dl = document.getElementById("inspect-fields");
  dl.innerHTML = "";
  if (!item) return;
  var fields = [
    ["种类", item.kind],
    ["路径", item.path],
    ["范围", item.breadth],
    ["能说什么", item.claim],
    ["状态", item.status],
    ["追责 run", item.run_id],
    ["git", item.git_head],
    ["证据", item.evidence]
  ];
  fields.forEach(function (pair) {
    if (!pair[1]) return;
    var dt = document.createElement("dt");
    dt.textContent = pair[0];
    var dd = document.createElement("dd");
    dd.textContent = pair[1];
    dl.appendChild(dt);
    dl.appendChild(dd);
  });
  document.querySelectorAll("#tree li").forEach(function (li) {
    li.classList.toggle("active", li.dataset.id === id);
  });
}
function render(view) {
  window.__AG_VIEW = view;
  var n = (view.actions || []).length;
  var rate = view.trust_rate == null ? "未知" : Math.round(view.trust_rate * 100) + "%";
  document.getElementById("attention").textContent = n ? ("有 " + n + " 件要看") : "声明过的针没有红账";
  document.getElementById("gate").textContent = view.stale ? "证据过期" : "可跑";
  document.getElementById("gate").className = "gate" + (view.stale ? " warn" : "");
  document.getElementById("status").textContent = "可信率 " + rate + " · 提醒不拦业务";
  fillList("action", view.actions, "没有要处理的红账。");
  fillList("alert", view.alerts, "没有警情。");
  fillList("record", view.records, "没有记录。");
  var ul = document.querySelector("#tree ul");
  ul.innerHTML = "";
  (view.tree || []).forEach(function (row) {
    var li = document.createElement("li");
    li.textContent = (row.path || row.note || row.id) + " · " + (row.status || "");
    li.dataset.id = row.id;
    li.onclick = function () { inspect(row.id); };
    ul.appendChild(li);
  });
  document.getElementById("ops-body").textContent = view.evidence_text || "";
}
function loadView(root) {
  var url = "/api/view?root=" + encodeURIComponent(root || "");
  fetch(url).then(function (r) { return r.json(); }).then(render);
}
function boot() {
  fetch("/api/projects").then(function (r) { return r.json(); }).then(function (data) {
    var sel = document.getElementById("project");
    sel.innerHTML = "";
    (data.projects || []).forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = p.root;
      opt.textContent = p.root;
      sel.appendChild(opt);
    });
    if (sel.value) loadView(sel.value);
    else {
      document.getElementById("attention").textContent = "还没有登记项目";
    }
  });
  document.getElementById("project").onchange = function () { loadView(this.value); };
  document.getElementById("refresh").onclick = function () { loadView(document.getElementById("project").value); };
  document.getElementById("run").onclick = function () {
    var root = document.getElementById("project").value;
    fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root: root }) })
      .then(function () { loadView(root); });
  };
  document.getElementById("checkup").onclick = function () {
    var root = document.getElementById("project").value;
    fetch("/api/checkup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root: root }) })
      .then(function () { loadView(root); });
  };
  document.getElementById("tree-filter").oninput = function () {
    var q = this.value.toLowerCase();
    document.querySelectorAll("#tree li").forEach(function (li) {
      li.style.display = li.textContent.toLowerCase().indexOf(q) >= 0 ? "" : "none";
    });
  };
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.onclick = function () {
      var key = btn.getAttribute("data-copy");
      var rows = (window.__AG_VIEW || {})[key] || [];
      copyText(rows.map(function (r, i) { return (i + 1) + ". " + r.text; }).join("\\n"));
    };
  });
  document.getElementById("copy-ops").onclick = function () {
    copyText(document.getElementById("ops-body").textContent);
  };
}
boot();
"""
