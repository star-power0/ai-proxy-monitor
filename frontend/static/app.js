const API = window.location.protocol === "file:" ? "http://127.0.0.1:8084" : window.location.origin;

let stations = [];
let checkRunning = false;

async function load() {
  const res = await fetch(`${API}/api/status`);
  const data = await res.json();
  stations = data.stations || [];
  document.getElementById("db-path").textContent = data.db ? `CCSwitch DB: ${data.db}` : "未找到 ccswitch 数据库";
  render();
}

async function refresh() {
  if (checkRunning) return;
  checkRunning = true;
  const btn = document.getElementById("btn-refresh");
  btn.disabled = true;
  btn.textContent = "检测中...";
  try {
    await fetch(`${API}/api/health`);
    await load();
  } finally {
    btn.disabled = false;
    btn.textContent = "手动刷新";
    checkRunning = false;
  }
}

function isAnomaly(station) {
  return station.status !== "online";
}

function sortScore(station) {
  if (station.status === "error") return 0;
  if (station.status === "unknown") return 1;
  if (station.current_group_names?.length) return 2;
  return 3;
}

function render() {
  const parsed = stations
    .map(station => ({
      ...station,
      is_anomaly: isAnomaly(station),
    }))
    .sort((a, b) => sortScore(a) - sortScore(b) || a.host.localeCompare(b.host, "zh-CN"));

  const anomalies = parsed.filter(station => station.is_anomaly);
  const normal = parsed.filter(station => !station.is_anomaly);

  // 动态更新顶部四个大数字，确保数据100%同步
  const totalCount = stations.length;
  const onlineCount = stations.filter(s => s.status === "online").length;
  const warnCount = stations.filter(s => s.status === "unknown").length;
  const errorCount = stations.filter(s => s.status === "error").length;

  document.getElementById("stat-total").textContent = totalCount;
  document.getElementById("stat-ok").textContent = onlineCount;
  document.getElementById("stat-warn").textContent = warnCount;
  document.getElementById("stat-low").textContent = errorCount;

  const anomalySection = document.getElementById("anomaly-section");
  anomalySection.style.display = anomalies.length ? "block" : "none";
  document.getElementById("anomaly-list").innerHTML = anomalies.map((s, idx) => stationCardHtml(s, idx)).join("");
  document.getElementById("station-list").innerHTML = normal.map((s, idx) => stationCardHtml(s, idx + anomalies.length)).join("");
  document.getElementById("last-updated").textContent = new Date().toLocaleTimeString("zh-CN");
  
  // 绑定顶部统计卡片点击事件并初始化下拉面板
  bindStatCardsEvents();
  
  const btnToggleAll = document.getElementById("btn-toggle-all");
  if (btnToggleAll) {
    btnToggleAll.textContent = "折叠全部";
  }
}

function getCleanWebsiteUrl(station) {
  let url = "";
  if (station.website_url) {
    url = station.website_url;
  } else {
    const host = station.host ? station.host.toLowerCase() : "";
    if (!host) return "";
    url = `https://${host}`;
  }
  
  const urlLower = url.toLowerCase();
  if (urlLower.includes("deepseek.com")) {
    return "https://platform.deepseek.com/usage";
  }
  if (urlLower.includes("aicards.shop") || urlLower.includes("xiaoleai.team")) {
    return "https://aicards.shop/user/dashboard";
  }
  if (urlLower.includes("anyrouter.top")) {
    return "https://anyrouter.top/console";
  }
  if (urlLower.includes("freemodel.dev")) {
    return "https://freemodel.dev/dashboard/usage";
  }
  if (urlLower.includes("qlcodeapi.com")) {
    return "https://api.qlcodeapi.com/keys";
  }
  if (urlLower.includes("tygzs.cn")) {
    return "https://sub2api.tygzs.cn/keys";
  }
  if (urlLower.includes("riyuexy.cc")) {
    return "https://svip.riyuexy.cc/keys";
  }
  if (urlLower.includes("qlhazycoder.top")) {
    return "https://api.qlhazycoder.top/wallet";
  }
  if (urlLower.includes("twgom.com")) {
    return "https://api.twgom.com/wallet";
  }
  if (urlLower.includes("baiyuan.cc.cd")) {
    return "https://baiyuan.cc.cd/wallet";
  }
  if (urlLower.includes("cheapyun.cc.cd")) {
    return "https://cheapyun.cc.cd/console";
  }
  if (urlLower.includes("prorisehub.com")) {
    return "https://newapi.prorisehub.com/wallet";
  }
  if (urlLower.includes("vsllm.com")) {
    return "https://vsllm.com/console/topup?tab=topup";
  }
  if (urlLower.includes("proxy-gls.de5.net")) {
    return "https://api-public.proxy-gls.de5.net/wallet";
  }
  return url;
}

function getCleanChannelName(station) {
  if (!station) return "未知";
  let name = station.alias || station.host || "";
  // 1. 去掉括号和里面的倍率, 如 (0.18x)
  name = name.replace(/\s*\([\d\.]+\s*x?\)/gi, "");
  // 2. 去掉“相当于”、“约”、“推荐”、“备用”、“国模”等修饰文字
  name = name.replace(/(相当于|约|推荐|备用|国模)/g, "");
  // 3. 去掉倍率和数字，比如 0.25x, 0.18, 0.12 等
  name = name.replace(/\b[\d\.]+\s*x?\b/gi, "");
  name = name.replace(/[\d\.]+\s*x/gi, "");
  name = name.replace(/\b\d+\b/g, "");
  // 4. 清理括号
  name = name.replace(/[（）()]/g, "");
  // 5. 整理空格
  name = name.replace(/\s+/g, " ").trim();
  
  return name || station.host;
}

function stationCardHtml(station, index = 0) {
  const classes = ["card", "station-card"];
  if (station.is_anomaly) classes.push("anomaly");
  if (station.status) classes.push(station.status); // 注入具体状态 class (online, unknown, error)
  if (station.current_group_names?.length) classes.push("current");

  const badge = statusBadge(station.status);
  
  let balanceClass = "balance-normal";
  let balanceText = "未知";
  
  if (station.host && station.host.toLowerCase().includes("nvidia.com")) {
    balanceText = "免费";
    balanceClass = "balance-free";
  } else if (station.balance !== null && station.balance !== undefined) {
    const balanceVal = Number(station.balance);
    balanceText = `$${balanceVal.toFixed(2)}`;
    
    if (balanceVal < 5.0) {
      balanceClass = "balance-danger";
    } else if (balanceVal < 10.0) {
      balanceClass = "balance-warning";
    } else {
      balanceClass = "balance-normal";
    }
  } else {
    balanceClass = "balance-unknown";
  }
  
  const updateTime = station.last_check ? new Date(station.last_check).toLocaleString("zh-CN") : "未检测";
  const currentGroups = station.current_group_names?.length ? station.current_group_names.join("、") : "无";

  const cleanName = getCleanChannelName(station);
  const targetUrl = getCleanWebsiteUrl(station);
  const linkHtml = targetUrl
    ? `<a href="${targetUrl}" target="_blank" style="color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4);" title="点击一键跳转至站点控制台">${escapeHtml(cleanName)} 🔗</a>`
    : escapeHtml(cleanName);

  let reasonClass = "";
  let loginActionBtn = "";
  if (station.status === "error") {
    reasonClass = "has-error";
  } else if (station.status === "unknown") {
    reasonClass = "has-warn";
  }
  
  // 只要状态是异常、需验证，或者余额是未知，我们就显示“补录登录”的按钮，方便用户一键重新登录
  if (targetUrl && (station.status !== "online" || balanceText === "未知")) {
    loginActionBtn = `
      <div style="margin-top: 10px; display: flex; justify-content: flex-end;">
        <button class="btn-goto-login" style="padding: 5px 12px; font-size: 11px;" onclick="window.triggerLoginHelper('${escapeJs(targetUrl)}')">
          补录登录 🔑
        </button>
      </div>`;
  }

  const reasonBanner = `
    <div class="status-reason-banner ${reasonClass}">
      <strong>状态说明：</strong>${escapeHtml(station.status_reason || "正常，在线运行中")}
      ${loginActionBtn}
    </div>`;

  const delaySec = (index * 0.04).toFixed(2);
  const styleAttr = `style="animation-delay: ${delaySec}s"`;

  const cardId = `station-${index}`;
  const { grouped, sortedRatios } = groupGroupsByRatio(station.groups);

  let groupsHtml = "";
  if (sortedRatios.length === 0) {
    groupsHtml = `<div class="time-label" style="text-align: center; padding: 12px; opacity: 0.5;">无可用分组线路</div>`;
  } else {
    groupsHtml = `
      <div class="ratio-accordion-container">
        ${sortedRatios.map((ratioText, i) => ratioRowHtml(cardId, ratioText, grouped[ratioText], i === 0)).join("")}
      </div>
    `;
  }

  return `
<div class="${classes.join(" ")}" id="station-card-${station.host}" ${styleAttr}>
  <div class="hud-corner hud-tl"></div>
  <div class="hud-corner hud-tr"></div>
  <div class="hud-corner hud-bl"></div>
  <div class="hud-corner hud-br"></div>
  <div class="card-header">
    <div class="card-header-left">
      <div class="card-title">
        ${linkHtml}
      </div>
      <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
        ${badge}
        <span style="font-size: 11px; color: var(--muted); opacity: 0.65; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;" title="${escapeHtml(station.host)}">${escapeHtml(station.host)}</span>
      </div>
    </div>
    <div class="card-header-right">
      <div class="station-balance-label">余额</div>
      <div class="station-balance ${balanceClass}">${balanceText}</div>
    </div>
  </div>
  
  <div class="meta-pills">
    <div class="meta-pill">分组数 <span>${station.group_count}</span></div>
    <div class="meta-pill">在线 <span>${station.online_count}</span></div>
    <div class="meta-pill">异常 <span>${station.error_count}</span></div>
    <div class="meta-pill">需验证 <span>${station.unknown_count}</span></div>
    <div class="meta-pill">当前分组 <span>${escapeHtml(currentGroups)}</span></div>
  </div>
  
  ${reasonBanner}
  
  ${groupsHtml}
  
  <div class="card-footer">
    <div class="time-label">更新时间：${updateTime}</div>
  </div>
</div>`;
}

/* 分组倍率解析与聚类排序 */
function groupGroupsByRatio(groups) {
  const grouped = {};
  (groups || []).forEach(group => {
    const groupName = group.group_name || "";
    const ratioMatch = groupName.match(/\(([\d\.]+x)\)/);
    let ratioText = "1.0x";
    let cleanName = groupName;
    if (ratioMatch) {
      ratioText = ratioMatch[1];
      cleanName = groupName.replace(/\s*\([\d\.]+x\)/, "").trim();
    }
    
    if (!grouped[ratioText]) {
      grouped[ratioText] = [];
    }
    grouped[ratioText].push({
      ...group,
      cleanName,
      ratioText
    });
  });
  
  // 按倍率数值升序排序 (从小到大)
  const sortedRatios = Object.keys(grouped).sort((a, b) => {
    const valA = parseFloat(a) || 1.0;
    const valB = parseFloat(b) || 1.0;
    return valA - valB;
  });
  
  return { grouped, sortedRatios };
}

/* 渲染单行倍率折叠面板 */
function ratioRowHtml(stationId, ratioText, ratioGroups, isFirstRatio) {
  const val = parseFloat(ratioText) || 1.0;
  let colorClass = "ratio-normal";
  if (val < 1.0) colorClass = "ratio-low";
  else if (val > 1.5) colorClass = "ratio-high";
  
  // 汇总状态灯 (最高显示 10 个，优先显示异常)
  const maxDots = 10;
  const sortedLines = [...ratioGroups].sort((a, b) => {
    if (a.status !== "online" && b.status === "online") return -1;
    if (a.status === "online" && b.status !== "online") return 1;
    return 0;
  });
  
  let statusDotsHtml = sortedLines.slice(0, maxDots).map(g => {
    const statusDotClass = g.status === "online" ? "ok" : (g.status === "error" ? "err" : "warn");
    return `<span class="summary-dot dot-${statusDotClass}"></span>`;
  }).join("");
  
  if (ratioGroups.length > maxDots) {
    statusDotsHtml += `<span style="font-size: 10px; color: var(--muted); margin-left: 2px;">+${ratioGroups.length - maxDots}</span>`;
  }
  
  // 线路预览名
  const namesPreview = ratioGroups.map(g => g.cleanName).join("、");
  
  // 展开策略：第一个倍率组(最低倍率组) 或 包含任何异常线路的倍率组，默认展开
  const hasAnomaly = ratioGroups.some(g => g.status !== "online");
  const defaultExpanded = isFirstRatio || hasAnomaly;
  
  // 格式化 ID (注意 ratioText 中可能带点，如 0.12x)
  const escapedRatio = ratioText.replace(".", "_");
  const panelId = `panel-${stationId}-${escapedRatio}`;
  const rowId = `row-${stationId}-${escapedRatio}`;
  
  const detailsHtml = ratioGroups.map(group => {
    const delayMs = group.response_time_ms != null ? group.response_time_ms : null;
    let delayClass = "delay-slow";
    if (delayMs !== null && group.status === "online") {
      if (delayMs < 500) delayClass = "delay-fast";
      else if (delayMs < 2000) delayClass = "delay-medium";
    }
    const responseTimeStr = delayMs != null ? `${delayMs}ms` : "超时/未知";
    const statusDotClass = group.status === "online" ? "ok" : (group.status === "error" ? "err" : "warn");
    
    const reasonText = group.status_reason ? group.status_reason : "线路正常";
    const reasonTag = group.status !== "online" 
      ? `<span class="detail-line-reason" title="${escapeHtml(reasonText)}">${escapeHtml(reasonText)}</span>` 
      : ``;

    return `
      <div class="detail-line-item">
        <span class="status-dot dot-${statusDotClass}"></span>
        <span class="detail-line-name">${escapeHtml(group.cleanName)}</span>
        ${reasonTag}
        <span class="detail-line-delay ${delayClass}">${responseTimeStr}</span>
      </div>
    `;
  }).join("");

  return `
    <div class="ratio-row ${defaultExpanded ? 'active' : ''}" id="${rowId}" onclick="toggleRatio('${panelId}', '${rowId}')">
      <div style="display: flex; align-items: center; min-width: 0; flex: 1;">
        <span class="ratio-badge-luxe ${colorClass}">${escapeHtml(ratioText)}</span>
        <div class="ratio-status-summary">
          ${statusDotsHtml}
        </div>
        <span class="ratio-names-preview" title="${escapeHtml(namesPreview)}">${escapeHtml(namesPreview)}</span>
      </div>
      <div class="ratio-row-right">
        <span class="ratio-count">${ratioGroups.length} 个线路</span>
        <span class="ratio-arrow">▼</span>
      </div>
    </div>
    <div class="ratio-detail-panel ${defaultExpanded ? 'expanded' : ''}" id="${panelId}" style="${defaultExpanded ? 'max-height: 1000px;' : ''}">
      ${detailsHtml}
    </div>
  `;
}

function statusBadge(status) {
  if (status === "online") {
    return `
      <div class="status-badge-container">
        <span class="status-dot dot-ok"></span>
        <span class="badge badge-ok">在线</span>
      </div>`;
  }
  if (status === "error") {
    return `
      <div class="status-badge-container">
        <span class="status-dot dot-err"></span>
        <span class="badge badge-err">异常</span>
      </div>`;
  }
  return `
    <div class="status-badge-container">
      <span class="status-dot dot-warn"></span>
      <span class="badge badge-fail">需验证</span>
    </div>`;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

window.toggleRatio = function(panelId, rowId) {
  const panel = document.getElementById(panelId);
  const row = document.getElementById(rowId);
  if (!panel || !row) return;
  
  const isExpanded = panel.classList.contains("expanded");
  if (isExpanded) {
    panel.classList.remove("expanded");
    row.classList.remove("active");
    panel.style.maxHeight = null;
  } else {
    panel.classList.add("expanded");
    row.classList.add("active");
    // 动态计算实际高度以展示过渡动画
    panel.style.maxHeight = panel.scrollHeight + "px";
    
    // 延迟恢复自适应，避免面板内部 DOM 改变时高度崩塌
    setTimeout(() => {
      if (panel.classList.contains("expanded")) {
        panel.style.maxHeight = "1000px";
      }
    }, 400);
  }
};

let currentStatDropdownType = null;

window.toggleStatDropdown = function(statusType) {
  const panel = document.getElementById("stat-detail-dropdown");
  if (!panel) return;
  
  const warnCard = document.getElementById("stat-warn").closest(".stat");
  const errorCard = document.getElementById("stat-low").closest(".stat");
  
  const targetStations = stations.filter(s => s.status === statusType);
  
  if (currentStatDropdownType === statusType && panel.classList.contains("expanded")) {
    panel.classList.remove("expanded");
    panel.style.maxHeight = null;
    warnCard.classList.remove("active");
    errorCard.classList.remove("active");
    currentStatDropdownType = null;
    return;
  }
  
  if (targetStations.length === 0) {
    panel.classList.remove("expanded");
    panel.style.maxHeight = null;
    warnCard.classList.remove("active");
    errorCard.classList.remove("active");
    currentStatDropdownType = null;
    return;
  }
  
  const title = statusType === "error" ? "异常站点快捷通道" : "需验证站点快捷通道";
  const titleIcon = statusType === "error" ? "🔴" : "🟡";
  const typeClass = statusType === "error" ? "error-item" : "warn-item";
  
  const itemsHtml = targetStations.map(s => {
    const targetUrl = getCleanWebsiteUrl(s);
    const loginBtn = targetUrl 
      ? `<a href="${targetUrl}" target="_blank" class="btn-goto-login">一键登录 🔗</a>`
      : `<span style="font-size: 12px; color: var(--muted);">无登录地址</span>`;
    const reason = s.status_reason || (statusType === "error" ? "检测连接超时或服务器异常" : "线路状态需手动验证");
    const cleanName = getCleanChannelName(s);
    
    return `
      <div class="stat-dropdown-item ${typeClass}">
        <div class="stat-dropdown-left">
          <span class="stat-dropdown-host">${escapeHtml(cleanName)} <span style="font-size: 11px; color: var(--muted); font-weight: normal; margin-left: 6px;">(${escapeHtml(s.host)})</span></span>
          <span class="stat-dropdown-reason" title="${escapeHtml(reason)}">${escapeHtml(reason)}</span>
        </div>
        ${loginBtn}
      </div>
    `;
  }).join("");
  
  panel.innerHTML = `
    <div class="stat-dropdown-container">
      <div class="stat-dropdown-header">
        <div class="stat-dropdown-title">${titleIcon} ${title} (${targetStations.length} 个)</div>
        <span class="stat-dropdown-close" onclick="window.toggleStatDropdown('${statusType}')">×</span>
      </div>
      <div class="stat-dropdown-list">
        ${itemsHtml}
      </div>
    </div>
  `;
  
  warnCard.classList.remove("active");
  errorCard.classList.remove("active");
  if (statusType === "unknown") warnCard.classList.add("active");
  if (statusType === "error") errorCard.classList.add("active");
  
  panel.classList.add("expanded");
  panel.style.maxHeight = panel.scrollHeight + "px";
  
  setTimeout(() => {
    if (panel.classList.contains("expanded")) {
      panel.style.maxHeight = "800px";
    }
  }, 400);
  
  currentStatDropdownType = statusType;
};

function bindStatCardsEvents() {
  const warnCard = document.getElementById("stat-warn").closest(".stat");
  const errorCard = document.getElementById("stat-low").closest(".stat");
  
  const warnCount = stations.filter(s => s.status === "unknown").length;
  const errorCount = stations.filter(s => s.status === "error").length;
  
  if (warnCount > 0) {
    warnCard.classList.add("clickable");
    warnCard.onclick = () => window.toggleStatDropdown("unknown");
  } else {
    warnCard.classList.remove("clickable");
    warnCard.onclick = null;
  }
  
  if (errorCount > 0) {
    errorCard.classList.add("clickable");
    errorCard.onclick = () => window.toggleStatDropdown("error");
  } else {
    errorCard.classList.remove("clickable");
    errorCard.onclick = null;
  }
  
  const panel = document.getElementById("stat-detail-dropdown");
  if (panel) {
    panel.classList.remove("expanded");
    panel.style.maxHeight = null;
    warnCard.classList.remove("active");
    errorCard.classList.remove("active");
    currentStatDropdownType = null;
  }
}

document.getElementById("btn-refresh").addEventListener("click", refresh);
load();

// 搜索与智能定位逻辑
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");

if (searchInput && searchResults) {
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim().toLowerCase();
    if (!query) {
      searchResults.style.display = "none";
      searchResults.innerHTML = "";
      return;
    }
    
    // 根据渠道名 alias 或者域名 host 进行搜索
    const matches = stations.filter(s => {
      const cleanName = getCleanChannelName(s).toLowerCase();
      const host = (s.host || "").toLowerCase();
      return cleanName.includes(query) || host.includes(query);
    });
    
    if (matches.length === 0) {
      searchResults.innerHTML = `<div class="search-no-results">未找到匹配站点</div>`;
      searchResults.style.display = "block";
      return;
    }
    
    searchResults.innerHTML = matches.map(s => {
      const cleanName = getCleanChannelName(s);
      return `
        <div class="search-result-item" onclick="window.scrollToStation('${escapeJs(s.host)}')">
          <span class="result-name">${escapeHtml(cleanName)}</span>
          <span class="result-host">${escapeHtml(s.host)}</span>
        </div>
      `;
    }).join("");
    searchResults.style.display = "block";
  });
  
  // 点击页面其它地方隐藏搜索框
  document.addEventListener("click", (e) => {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = "none";
    }
  });
  
  // 绑定回车直接定位第一个匹配项
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const query = searchInput.value.trim().toLowerCase();
      if (!query) return;
      const firstMatch = stations.find(s => {
        const cleanName = getCleanChannelName(s).toLowerCase();
        const host = (s.host || "").toLowerCase();
        return cleanName.includes(query) || host.includes(query);
      });
      if (firstMatch) {
        window.scrollToStation(firstMatch.host);
      }
    }
  });
}

window.scrollToStation = function(host) {
  const card = document.getElementById(`station-card-${host}`);
  if (searchResults) searchResults.style.display = "none";
  if (searchInput) searchInput.value = ""; // 选定后清空搜索框
  
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    
    // 高亮闪烁特效
    card.classList.remove("highlight-glow");
    void card.offsetWidth; // 触发 reflow 重置动画
    card.classList.add("highlight-glow");
    
    setTimeout(() => {
      card.classList.remove("highlight-glow");
    }, 2000);
  }
};

// 全局快捷键 / 或 Ctrl+K 聚焦搜索框，ESC 键退出聚焦
document.addEventListener("keydown", (e) => {
  const isInputActive = document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA";
  
  if (!isInputActive) {
    if (e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key === "k")) {
      e.preventDefault();
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
  } else {
    if (e.key === "Escape") {
      searchInput.blur();
      if (searchResults) searchResults.style.display = "none";
    }
  }
});

// 辅助转义 JS 字符串以防止 html 转义出错
function escapeJs(str) {
  return (str || "").replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// 绑定全局折叠/展开所有线路
window.toggleAllPanels = function() {
  const panels = document.querySelectorAll(".ratio-detail-panel");
  const rows = document.querySelectorAll(".ratio-row");
  const btn = document.getElementById("btn-toggle-all");
  if (!btn) return;
  
  const isExpanding = btn.textContent === "展开全部";
  
  panels.forEach(panel => {
    if (isExpanding) {
      panel.classList.add("expanded");
      panel.style.maxHeight = "1000px";
    } else {
      panel.classList.remove("expanded");
      panel.style.maxHeight = null;
    }
  });
  
  rows.forEach(row => {
    if (isExpanding) {
      row.classList.add("active");
    } else {
      row.classList.remove("active");
    }
  });
  
  btn.textContent = isExpanding ? "折叠全部" : "展开全部";
};

const btnToggleAll = document.getElementById("btn-toggle-all");
if (btnToggleAll) {
  btnToggleAll.addEventListener("click", window.toggleAllPanels);
}

// ===== 自定义暗黑风模态框（替代原生 alert/confirm）=====
function _createModalEl() {
  const existing = document.getElementById('custom-modal-overlay');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.id = 'custom-modal-overlay';
  el.style.cssText = [
    'position:fixed','top:0','left:0','width:100%','height:100%',
    'background:rgba(2,4,8,0.78)','backdrop-filter:blur(12px)',
    '-webkit-backdrop-filter:blur(12px)',
    'z-index:99999','display:flex','align-items:center','justify-content:center',
    'animation:modalFadeIn 0.2s ease'
  ].join(';');
  return el;
}

function _injectModalStyles() {
  if (document.getElementById('custom-modal-styles')) return;
  const s = document.createElement('style');
  s.id = 'custom-modal-styles';
  s.textContent = `
    @keyframes modalFadeIn { from { opacity:0; transform:scale(0.95); } to { opacity:1; transform:scale(1); } }
    .modal-box {
      background: linear-gradient(135deg, rgba(10,16,30,0.97) 0%, rgba(6,10,20,0.99) 100%);
      border: 1px solid rgba(56,189,248,0.3);
      border-radius: 16px;
      padding: 32px;
      max-width: 440px;
      width: 90%;
      box-shadow: 0 0 60px rgba(56,189,248,0.12), 0 24px 48px rgba(0,0,0,0.6);
      color: #f1f5f9;
      font-family: 'Outfit', sans-serif;
    }
    .modal-icon { font-size: 28px; margin-bottom: 14px; }
    .modal-title { font-size: 18px; font-weight: 700; margin-bottom: 10px; color: #fff; }
    .modal-msg { font-size: 14px; color: #94a3b8; line-height: 1.7; margin-bottom: 24px; }
    .modal-btns { display:flex; gap:12px; justify-content:flex-end; }
    .modal-btn {
      padding: 9px 22px; border-radius: 10px; font-size: 14px; font-weight: 600;
      cursor: pointer; border: none; transition: all 0.18s;
    }
    .modal-btn-cancel {
      background: rgba(255,255,255,0.07); color: #94a3b8;
      border: 1px solid rgba(255,255,255,0.12);
    }
    .modal-btn-cancel:hover { background: rgba(255,255,255,0.13); color: #f1f5f9; }
    .modal-btn-confirm {
      background: linear-gradient(135deg, #38bdf8, #0ea5e9);
      color: #040810;
    }
    .modal-btn-confirm:hover { filter: brightness(1.12); }
    .modal-btn-ok {
      background: linear-gradient(135deg, #4ade80, #22c55e);
      color: #040810;
    }
    .modal-btn-ok:hover { filter: brightness(1.1); }
    .modal-btn-err {
      background: linear-gradient(135deg, #f87171, #ef4444);
      color: #040810;
    }
    .modal-btn-err:hover { filter: brightness(1.1); }
  `;
  document.head.appendChild(s);
}

function showModal(icon, title, msg, btnLabel = '确定', btnClass = 'modal-btn-ok') {
  _injectModalStyles();
  return new Promise(resolve => {
    const overlay = _createModalEl();
    overlay.innerHTML = `
      <div class="modal-box">
        <div class="modal-icon">${icon}</div>
        <div class="modal-title">${title}</div>
        <div class="modal-msg">${msg}</div>
        <div class="modal-btns">
          <button class="modal-btn ${btnClass}" id="modal-ok-btn">${btnLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#modal-ok-btn').addEventListener('click', () => {
      overlay.remove();
      resolve();
    });
  });
}

function showConfirm(icon, title, msg, confirmLabel = '确认', cancelLabel = '取消') {
  _injectModalStyles();
  return new Promise(resolve => {
    const overlay = _createModalEl();
    overlay.innerHTML = `
      <div class="modal-box">
        <div class="modal-icon">${icon}</div>
        <div class="modal-title">${title}</div>
        <div class="modal-msg">${msg}</div>
        <div class="modal-btns">
          <button class="modal-btn modal-btn-cancel" id="modal-cancel-btn">${cancelLabel}</button>
          <button class="modal-btn modal-btn-confirm" id="modal-confirm-btn">${confirmLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#modal-cancel-btn').addEventListener('click', () => { overlay.remove(); resolve(false); });
    overlay.querySelector('#modal-confirm-btn').addEventListener('click', () => { overlay.remove(); resolve(true); });
  });
}

window.triggerLoginHelper = async function(url) {
  if (!url) return;
  const confirmed = await showConfirm(
    '🔑',
    '补录登录 — 唤起浏览器',
    '软件将在桌面拉起一个可视化的 Chrome 登录窗口。<br><br>请在该窗口中完成登录/扫码，登录成功后<strong style="color:#38bdf8">直接关闭</strong>该浏览器窗口，大屏将自动重新检测刷新余额。',
    '立即开始 🚀',
    '取消'
  );
  if (!confirmed) return;
  
  const btn = document.getElementById("btn-refresh");
  const originalText = btn ? btn.textContent : "手动刷新";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "登录检测中...";
  }
  
  try {
    const res = await fetch(`${API}/api/login_channel?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (data.success) {
      await showModal('✅', '登录成功', '登录窗口已关闭，正在重新检测以同步最新余额...', '开始刷新', 'modal-btn-ok');
      await refresh(); 
    } else {
      await showModal('⚠️', '登录辅助失败', '错误详情：<br><code style="font-size:12px;color:#f87171;word-break:break-all">' + escapeHtml(data.error || '未知原因') + '</code>', '知道了', 'modal-btn-err');
    }
  } catch (e) {
    await showModal('❌', '连接失败', '无法连接到登录辅助服务：<br><code style="font-size:12px;color:#f87171">' + escapeHtml(e.message) + '</code>', '知道了', 'modal-btn-err');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
};

// ==================== Cyber Canvas Particle Network ====================
(function initCyberCanvas() {
  const canvas = document.getElementById("cyber-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  
  let width = canvas.width = window.innerWidth;
  let height = canvas.height = window.innerHeight;
  
  window.addEventListener("resize", () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });
  
  const particles = [];
  // 限制粒子总数，最大 65 个，画面清爽开阔，对大屏友好
  const particleCount = Math.min(65, Math.floor((width * height) / 22000));
  
  const mouse = {
    x: null,
    y: null,
    radius: 160
  };
  
  window.addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  
  window.addEventListener("mouseleave", () => {
    mouse.x = null;
    mouse.y = null;
  });
  
  class Particle {
    constructor() {
      this.x = Math.random() * width;
      this.y = Math.random() * height;
      this.vx = (Math.random() - 0.5) * 0.85; // 稍微快一点点以增加灵动感
      this.vy = (Math.random() - 0.5) * 0.85;
      this.radius = Math.random() * 1.5 + 2.0; // 粒子微型化：2.0px - 3.5px
      this.color = Math.random() > 0.45 ? "rgba(56, 189, 248, 0.55)" : "rgba(74, 222, 128, 0.45)";
    }
    
    update() {
      if (mouse.x !== null && mouse.y !== null) {
        const dx = mouse.x - this.x;
        const dy = mouse.y - this.y;
        const distSq = dx * dx + dy * dy;
        const mouseRadiusSq = mouse.radius * mouse.radius; // 25600
        if (distSq < mouseRadiusSq) {
          const dist = Math.sqrt(distSq);
          if (dist > 0) {
            const force = (mouse.radius - dist) / mouse.radius;
            this.vx += (dx / dist) * force * 0.02; // 缓和吸附
            this.vy += (dy / dist) * force * 0.02;
          }
        }
      }
      
      const speed = Math.sqrt(this.vx * this.vx + this.vy * this.vy);
      if (speed > 1.6) {
        this.vx = (this.vx / speed) * 1.6;
        this.vy = (this.vy / speed) * 1.6;
      }
      
      this.x += this.vx;
      this.y += this.vy;
      
      if (this.x < 0 || this.x > width) this.vx *= -1;
      if (this.y < 0 || this.y > height) this.vy *= -1;
      
      if (this.x < 0) this.x = 0;
      if (this.x > width) this.x = width;
      if (this.y < 0) this.y = 0;
      if (this.y > height) this.y = height;
    }
    
    draw() {
      // 彻底移除耗能的 shadowBlur 外发光以换取硬件加速性能
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = this.color;
      ctx.fill();
    }
  }
  
  for (let i = 0; i < particleCount; i++) {
    particles.push(new Particle());
  }
  
  function animate() {
    ctx.clearRect(0, 0, width, height);
    
    particles.forEach(p => {
      p.update();
      p.draw();
    });
    
    ctx.save();
    
    // 绘制连线：移除了 shadowBlur
    for (let i = 0; i < particles.length; i++) {
      const p1 = particles[i];
      
      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j];
        const dx = p1.x - p2.x;
        const dy = p1.y - p2.y;
        const distSq = dx * dx + dy * dy;
        
        // 缩短连线距离至 140px，降低线段密集度（140 * 140 = 19600）
        if (distSq < 19600) {
          const dist = Math.sqrt(distSq);
          const alpha = ((140 - dist) / 140) * 0.22; // 降低连线最高透明度
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = `rgba(56, 189, 248, ${alpha})`;
          ctx.lineWidth = 1.0; // 线条调细至 1.0px
          ctx.stroke();
        }
      }
      
      if (mouse.x !== null && mouse.y !== null) {
        const dx = p1.x - mouse.x;
        const dy = p1.y - mouse.y;
        const distSq = dx * dx + dy * dy;
        const mouseRadiusSq = mouse.radius * mouse.radius; // 160 * 160 = 25600
        if (distSq < mouseRadiusSq) {
          const dist = Math.sqrt(distSq);
          const alpha = ((mouse.radius - dist) / mouse.radius) * 0.35; // 缓和鼠标交互线明度
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.strokeStyle = `rgba(56, 189, 248, ${alpha})`;
          ctx.lineWidth = 1.0;
          ctx.stroke();
        }
      }
    }
    ctx.restore();
    
    requestAnimationFrame(animate);
  }
  
  requestAnimationFrame(animate);
})();
