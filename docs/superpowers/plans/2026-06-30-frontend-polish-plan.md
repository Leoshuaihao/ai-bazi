# 前端精修实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSS 拆分减负 + 流月返工为横条联动 + AI 对话面板状态 + 付费自动刷新

**Architecture:** 四个独立 task，互不依赖可任意顺序执行。全改 `public/index.html`（Task 1 额外创建 `bazi.css`）。不改后端。

**Tech Stack:** Vanilla JS + CSS，无新依赖

## Global Constraints

- 不修改现有命理逻辑（排盘、旺衰、断前事、校正模块）
- 前端改动以弹层/浮层为主，不破坏现有布局
- 所有付费功能入口有明确的「锁 + 价格」标记
- 使用现有 CSS 变量（--bg-deep, --ink, --accent 等）
- 使用现有 `apiFetch` / `authFetch` 函数

---

## 文件变更总览

```
public/
├── bazi.css          # NEW: 从 index.html 中抽出的 ~580 行 CSS
└── index.html        # MODIFY: 减到 ~2150 行（删除 CSS + 重构流月/对话/刷新）
```

---

### Task 1: CSS 拆分——创建 bazi.css

**Files:**
- Create: `public/bazi.css`
- Modify: `public/index.html` (lines 9-591 → 替换为 `<link>`)

**验收标准:**
- `public/bazi.css` 包含 index.html 中 `<style>` 标签内的全部 CSS（583 行）
- `index.html` 中 `<style>...</style>` 替换为 `<link rel="stylesheet" href="bazi.css">`
- 页面渲染与拆分前完全一致（登录/日期选择器/支付/积分/对话面板/流月卡片均正常）
- `index.html` 行数从 2718 降到 ~2145

- [ ] **Step 1: 从 index.html 提取 CSS 到 bazi.css**

```bash
cd '/Users/lee/WorkSpace/claude项目/ai-bazi-hermes版'
# 提取第 9 行（<style>之后）到第 591 行（</style>之前）的所有 CSS
sed -n '10,590p' public/index.html > public/bazi.css
```

- [ ] **Step 2: 替换 index.html 中的 <style> 块为 <link>**

删除 `public/index.html` 中第 9-591 行（整个 `<style>...</style>` 块及其闭合标签），在第 9 行位置插入：

```html
<link rel="stylesheet" href="bazi.css">
```

⚠️ 注意：保留第 1540 行附近的 inline SVG `<style>` 块（那是独立的内联样式，不动它）。

- [ ] **Step 3: 验证页面渲染**

启动服务器，浏览器打开 `http://localhost:8022`，逐项检查：
1. 登录弹层——居中、遮罩正常
2. 日期选择器——五列滚轮正常
3. 支付弹层——产品卡片正常
4. 积分中心——徽章 + 弹出面板正常
5. AI 对话面板——侧边栏正常
6. 流月详批——未解锁门控按钮正常

- [ ] **Step 4: Commit**

```bash
git add public/bazi.css public/index.html
git commit -m "refactor: CSS 拆分到 bazi.css，index.html 减 580 行"
```

---

### Task 2: 流月返工——横条 + 三层联动

**Files:**
- Modify: `public/index.html` — 替换流月 HTML + 重写流月 JS + 修改 `renderDayunDims` 联动

**验收标准:**
- 流月区域从卡片网格改为横条格式（和 大运横条/流年横条 视觉一致）
- 未解锁：流月横条显示月份干支（无喜忌标签），五块分析展示大运分析
- 已解锁：流月横条显示喜忌标签，点击流月→五块分析刷为当月分析
- 点击大运→五块分析刷回大运分析
- 点击流年→五块分析刷为该年分析
- 五块分析联动：`renderDayunDims(type, data)` 接受参数

**实现细节:**

流月横条 HTML 替换（删除现有 `#liuyue-section` 内所有内容，替换为）：

```html
<div id="liuyue-section" style="margin-top:10px; display:none;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-weight:800;font-size:0.78rem;color:var(--ink-2);">📅 流月</span>
    <span id="liuyue-year-label" style="color:var(--muted);font-size:0.68rem;"></span>
  </div>
  <div id="liuyue-gate" style="text-align:center;padding:10px;border:1px solid var(--line);border-radius:var(--radius-sm);">
    <button class="btn btn-primary" onclick="unlockLiuYue()" style="font-size:0.78rem;">🔓 解锁流月 · ¥9.9</button>
  </div>
  <div class="dayun-strip" id="liuyue-strip" style="display:none;"></div>
  <div id="liuyue-loading" style="display:none;text-align:center;padding:10px;color:var(--muted);font-size:0.72rem;">⏳</div>
</div>
```

流月 JS 重写（替换现有 2058-2125 行全部流月函数）：

```javascript
// ============ 流月详批（横条 + 联动） ============
let S_liuyueData = null;  // { months: [...], year: N }
let S_activeAnalysis = 'dayun'; // 'dayun' | 'liunian' | 'liuyue'

async function unlockLiuYue() {
  if (!AUTH_TOKEN) { openAuthModal(); return; }
  openPayModal('liuyue');
}

function checkLiuYueAccess() {
  if (!S.chart || !S.chart.day_master) { $('#liuyue-section').style.display = 'none'; return; }
  const pub = isReportPublished();
  $('#liuyue-section').style.display = pub ? '' : 'none';
  if (!pub) return;
  if (AUTH_TOKEN) { loadLiuYueIfEntitled(); }
  else { showLiuYueGate(); }
}

async function loadLiuYueIfEntitled() {
  try {
    const cd = S.chart;
    if (!cd || !cd.day_master) return;
    showLiuYueLoading();
    const data = await authFetch('/api/liuyue', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chart_data: cd, year: new Date().getFullYear() }),
    });
    S_liuyueData = data;
    renderLiuYueStrip(data);
  } catch (e) {
    if (e.message && e.message.includes('402')) { showLiuYueGate(); }
    else { showLiuYueGate(); }
  }
}

function showLiuYueGate() {
  $('#liuyue-gate').style.display = '';
  $('#liuyue-strip').style.display = 'none';
  $('#liuyue-loading').style.display = 'none';
}

function showLiuYueLoading() {
  $('#liuyue-gate').style.display = 'none';
  $('#liuyue-strip').style.display = 'none';
  $('#liuyue-loading').style.display = '';
}

function renderLiuYueStrip(data) {
  $('#liuyue-gate').style.display = 'none';
  $('#liuyue-loading').style.display = 'none';
  $('#liuyue-year-label').textContent = data.year + '年';
  const strip = $('#liuyue-strip');
  strip.style.display = '';
  const pub = isReportPublished();
  strip.innerHTML = data.months.map((m, i) => {
    const xjCls = m.xi_ji === '喜' ? 'xi' : m.xi_ji === '忌' ? 'ji' : 'ping';
    const xjEmoji = m.xi_ji === '喜' ? '👍' : m.xi_ji === '忌' ? '⚠️' : '';
    return `<div class="dayun-card liuyue-card-item" onclick="onLiuYueClick(${i})" style="min-width:62px;padding:6px 5px;">
      <div style="font-size:0.6rem;color:var(--faint);">${m.label.substring(0,2)}</div>
      <div style="font-family:var(--font-ming);font-size:0.78rem;font-weight:800;">
        <span style="color:${WX_COLOR[STEM_WX[m.stem]]||'var(--ink-2)'};">${escHtml(m.stem)}</span><span style="color:${WX_COLOR[BRANCH_WX[m.branch]]||'var(--ink-2)'};">${escHtml(m.branch)}</span>
      </div>
      ${pub ? `<div style="font-size:0.5rem;color:${xiJiColor(m.xi_ji)};font-weight:800;">${xjEmoji} ${m.xi_ji}</div>` : '<div style="font-size:0.5rem;color:var(--faint);">-</div>'}
      <div style="font-size:0.52rem;color:var(--muted);margin-top:1px;">${escHtml(m.ten_god)}</div>
    </div>`;
  }).join('');
}

function onLiuYueClick(idx) {
  const m = S_liuyueData?.months?.[idx];
  if (!m) return;
  S_activeAnalysis = 'liuyue';
  // Highlight active card
  document.querySelectorAll('.liuyue-card-item').forEach((el, i) => el.classList.toggle('current', i === idx));
  // Render analysis for this month
  renderLiuYueDims(m);
}

function renderLiuYueDims(m) {
  const label = m.label;
  const dims = [['career','事业'],['wealth','财富'],['marriage','婚姻'],['relationship','贵人'],['health','健康']];
  const interpretation = m.interpretation || '暂无详细分析';
  const cards = dims.map(([k, dimLabel]) => {
    return `<div class="dim-card" style="min-width:0;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
        <span style="font-size:0.72rem;font-weight:800;color:var(--ink);">${escHtml(dimLabel)}</span>
        <span style="font-size:0.6rem;color:var(--accent);">${escHtml(label)}</span>
      </div>
      <p style="font-size:0.7rem;color:var(--ink-2);line-height:1.5;">${escHtml(interpretation)}</p>
    </div>`;
  }).join('');
  $('#dayun-dims').innerHTML = `<div class="dim-grid" style="grid-template-columns:repeat(5,1fr);">${cards}</div>`;
}
```

修改 `renderDayun()` 函数——大运卡片加点击高亮：

在 `renderDayun()` 函数中，大运卡片的 class 由 `dayun-card${isCur?' current':''}` 改为带 onclick：

```javascript
// 在 dayun.map 的 return 中，给卡片加 onclick
return`<div class="dayun-card${isCur?' current':''}" onclick="onDayunClick(${d.start_age})" ...
```

新增 `onDayunClick` 函数：

```javascript
function onDayunClick(startAge) {
  S_activeAnalysis = 'dayun';
  const cur = S.chart?.dayun?.find(d => d.start_age === startAge);
  if (!cur) return;
  document.querySelectorAll('#dayun-strip .dayun-card').forEach((el, i) => {
    const d = S.chart?.dayun?.[i];
    el.classList.toggle('current', d && d.start_age === startAge);
  });
  renderDayunDims(); // 刷回大运分析
}
```

修改 `renderLiunian()` 函数——流年卡片加点击高亮：

流年 map 中的卡片加 `onclick="onLiunianClick(${y})"` 和 class `liunian-card-item`：

```javascript
items.push(`<div class="dayun-card liunian-card-item${isNow?' current':''}" style="min-width:56px;padding:6px 5px;" onclick="onLiunianClick(${y})">...
```

新增 `onLiunianClick` 函数：

```javascript
function onLiunianClick(year) {
  S_activeAnalysis = 'liunian';
  document.querySelectorAll('.liunian-card-item').forEach(el => {
    const yt = el.querySelector('div').textContent;
    el.classList.toggle('current', parseInt(yt) === year);
  });
  // Re-render dims with liunian context (pass year to forecast request)
  renderDayunDims({year: year});
}
```

修改 `renderDayunDims()`——接受可选参数切换到流年模式：

```javascript
function renderDayunDims(opts) {
  opts = opts || {};
  const isLiunian = !!opts.year;
  const fc = S.forecast || {};
  const dims = [['career','事业'],['wealth','财富'],['marriage','婚姻'],['relationship','贵人'],['health','健康']];
  // ... existing loading state logic ...
  
  // If liunian mode with a specific year, pass context label
  const ctxLabel = isLiunian ? `${opts.year}年` : '';
  // ... rest of rendering with ctxLabel shown in each card header ...
}
```

- [ ] **Step 1: 删除现有流月 HTML**（`#liuyue-section` 及其内容），替换为上述新 HTML

- [ ] **Step 2: 删除现有流月 JS**（`unlockLiuYue` 到 `renderLiuYue` 全部），替换为上述新 JS

- [ ] **Step 3: 新增 onDayunClick / onLiunianClick 函数**（插入在 renderLiunian 函数之后）

- [ ] **Step 4: 修改 renderDayun / renderLiunian**——卡片加 onclick 和 class

- [ ] **Step 5: 修改 renderDayunDims**——接受 opts 参数，支持切换上下文标签

- [ ] **Step 6: 移除 checkLiuYueAccess 调用中旧引用**——确保 loadForecast 和 applyUA 中调用无误

- [ ] **Step 7: 验证**
  1. 排盘后点大运卡片→五块分析刷大运
  2. 点流年→五块刷该年
  3. 未解锁→流月横条显示干支无喜忌标签，点不动
  4. 解锁后→流月显示喜忌，点流月→五块刷该月

- [ ] **Step 8: Commit**

```bash
git add public/index.html
git commit -m "feat: 流月返工——横条格式 + 大运/流年/流月三层联动分析"
```

---

### Task 3: AI 对话面板状态对接

**Files:**
- Modify: `public/index.html` — 修改侧边栏 `#chat-panel` 显示状态信息

**验收标准:**
- 未登录：显示「登录后可开始对话」+ 登录按钮
- 已登录 + 有试用次数：显示「剩余 N 次试用」
- 已登录 + 试用用完 + 有积分：显示「积分：N」（每轮 5 积分）
- 已登录 + 试用用完 + 积分不足：显示「积分不足，请购买积分」
- 所有状态实时更新（登录/对话后刷新）

**实现:**

在 `#chat-panel` 的 HTML 中（complementary 区域），在消息列表上方追加状态栏：

```html
<div id="chat-status" style="padding:6px 12px;font-size:0.68rem;border-bottom:1px solid var(--line);">
  <span id="chat-status-text" style="color:var(--muted);">登录后可开始对话</span>
</div>
```

新增 `updateChatStatus()` 函数（替换现有同名函数）：

```javascript
function updateChatStatus() {
  const st = $('#chat-status-text');
  if (!st) return;
  if (!AUTH_USER) {
    st.innerHTML = '🔒 <a href="#" onclick="openAuthModal();return false;" style="color:var(--accent);">登录</a>后可开始对话';
    return;
  }
  const trial = AUTH_USER.trial_chats_remaining;
  if (trial > 0) {
    st.innerHTML = `🆓 剩余 <b style="color:#4ade80;">${trial}</b> 次试用`;
    return;
  }
  // Load points balance
  authFetch('/api/points/balance').then(d => {
    if (d.balance >= 5) {
      st.innerHTML = `💎 积分：<b style="color:var(--accent);">${d.balance}</b>（每轮 5 积分）`;
    } else {
      st.innerHTML = `⚠️ 积分不足，<a href="#" onclick="openPayModal('points_pack');return false;" style="color:var(--accent);">购买积分 ¥6.9</a>`;
    }
  }).catch(() => {
    st.innerHTML = '💎 积分：--';
  });
}
```

在 `updateAuthUI()` 函数末尾追加 `updateChatStatus()` 调用。

在 `sendChatMsg()` 函数中，消息发送成功后调用 `updateChatStatus()` 刷新状态。

- [ ] **Step 1: 在 `#chat-panel` 的消息列表上方插入 `#chat-status` 状态栏 HTML**

- [ ] **Step 2: 替换 `updateChatStatus` 函数**

- [ ] **Step 3: 在 `updateAuthUI` / `sendChatMsg` 末尾加 `updateChatStatus()`**

- [ ] **Step 4: 验证——未登录/有试用/有积分/积分不足 四种状态**

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat: AI 对话面板状态对接——试用次数/积分余额实时显示"
```

---

### Task 4: 付费后自动刷新权益

**Files:**
- Modify: `public/index.html` — 在支付回调/返回时 poll 权益状态

**验收标准:**
- 用户支付完回到页面 → 自动检测 entitlements 已更新 → 流月区域自动刷新（门控消失，横条出现）
- 积分包支付后 → 积分中心余额自动刷新
- 使用 `sessionStorage` 标记「刚支付」，页面加载时检查此标记并 poll

**实现:**

在支付弹层的 `doPay()` 成功后存储标记：

```javascript
// 在 doPay() 函数中，支付成功后追加：
sessionStorage.setItem('bazi_just_paid', '1');
```

页面加载时检查标记并轮询权益（在 `DOMContentLoaded` 或 `updateAuthUI` 中追加）：

```javascript
// 在 updateAuthUI 函数末尾追加
if (AUTH_TOKEN && sessionStorage.getItem('bazi_just_paid') === '1') {
  sessionStorage.removeItem('bazi_just_paid');
  pollEntitlements();
}

async function pollEntitlements() {
  // Poll entitlements check — try /api/liuyue which returns 402 if not entitled
  // If it succeeds, refresh the UI
  let tries = 0;
  const check = async () => {
    if (tries++ > 10) return; // 最多等 30 秒
    try {
      const cd = S.chart;
      if (!cd || !cd.day_master) return;
      const data = await authFetch('/api/liuyue', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chart_data: cd, year: new Date().getFullYear() }),
      });
      // Success! Refresh UI
      S_liuyueData = data;
      renderLiuYueStrip(data);
      loadPoints(); // refresh points badge
    } catch (e) {
      if (e.message && e.message.includes('402')) {
        // Still not entitled, retry in 3s
        setTimeout(check, 3000);
      }
    }
  };
  setTimeout(check, 2000); // 第一次等 2 秒让支付回调先处理
}
```

- [ ] **Step 1: 在 `doPay()` 成功后追加 `sessionStorage.setItem('bazi_just_paid', '1')`**

- [ ] **Step 2: 新增 `pollEntitlements` 函数**（插入在流月函数块附近）

- [ ] **Step 3: 在 `updateAuthUI` 末尾追加付费检查逻辑**

- [ ] **Step 4: 验证——模拟支付流程：点击解锁→跳转支付→返回页面→自动刷新**

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat: 付费后 poll 权益自动刷新——sessionStorage 标记 + 轮询 /api/liuyue"
```

---

## 实施顺序

按依赖关系：

1. **Task 1 (CSS 拆分)** — 无依赖，先做。
2. **Task 2 (流月返工)** — 依赖 Task 1（改了 index.html 结构，先拆分后改动更安全）。
3. **Task 3 (AI 对话状态)** — 无依赖，可并行。
4. **Task 4 (付费刷新)** — 依赖 Task 2（流月 UI 定下来后才知道刷新什么）。

推荐顺序：1 → 2 → 3+4 可并行。

---

## 全局验证清单

所有 task 完成后，走一遍完整用户流程：

- [ ] 未登录 → 打开页面 → AI 面板显示「登录后可开始对话」
- [ ] 登录 → 排盘 → 大运/流年/流月区域出现
- [ ] 点大运卡片 → 五块分析刷大运分析
- [ ] 点流年卡片 → 五块分析刷该年分析
- [ ] 流月区域显示「🔓 解锁流月 · ¥9.9」
- [ ] 点击解锁 → 支付弹层 → 模拟支付 → 页面自动刷新 → 流月横条出现（含喜忌标签）
- [ ] 点流月卡片 → 五块分析刷该月分析
- [ ] AI 对话面板显示试用次数/积分
- [ ] 对话消耗积分 → 积分数值更新
