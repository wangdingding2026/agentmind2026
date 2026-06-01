const API = '/panel/api';

const PAGE_LOADERS = {
  command: loadCommandCenter,
  tasks: loadTasksWorkbench,
  agents: loadAgentsWorkbench,
  routing: loadRoutingWorkbench,
  audit: loadAuditWorkbench,
  memory: loadMemoryWorkbench,
  orchestrator: loadOrchestrationPlans,
  settings: loadSettingsWorkbench,
};

const state = {
  currentPage: normalizePage(localStorage.getItem('agentmind_commander_page')),
  agents: [],
};

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function fetchAPI(path, options = {}) {
  try {
    const res = await fetch(API + path, options);
    return await res.json();
  } catch (error) {
    showToast('请求失败: ' + error.message, 'error');
    return null;
  }
}

function showToast(message, type = 'success') {
  const toast = $('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.className = 'toast ' + type + ' show';
  setTimeout(() => { toast.className = 'toast'; }, 2400);
}

function formatTime(value) {
  if (!value) return '-';
  try { return new Date(value).toLocaleString('zh-CN'); } catch { return value; }
}

function formatMs(value) {
  if (value == null || value === '') return '-';
  const ms = Number(value);
  if (!Number.isFinite(ms)) return '-';
  return ms < 1000 ? Math.round(ms) + 'ms' : (ms / 1000).toFixed(1) + 's';
}

function statusBadge(status) {
  const labels = {
    completed: '完成',
    failed: '失败',
    executing: '执行中',
    routing: '路由中',
    pending: '等待',
    timeout: '超时',
    healthy: '健康',
    unhealthy: '异常',
  };
  const safe = escapeHtml(status || 'unknown');
  return '<span class="status ' + safe + '">' + escapeHtml(labels[status] || status || '-') + '</span>';
}

function tagsHtml(tags) {
  return (tags || []).map(tag => '<span class="tag">' + escapeHtml(tag) + '</span>').join('');
}

function emptyHtml(message) {
  return '<div class="empty">' + escapeHtml(message) + '</div>';
}

function rowButton(label, action, id, extraClass = '') {
  const classes = ('btn-outline ' + extraClass).trim();
  return '<button class="' + classes + '" type="button" data-action="' + action + '" data-id="' + escapeHtml(id || '') + '">' + escapeHtml(label) + '</button>';
}

function normalizePage(page) {
  return PAGE_LOADERS[page] ? page : 'command';
}

function activatePage(page) {
  state.currentPage = normalizePage(page);
  localStorage.setItem('agentmind_commander_page', state.currentPage);
  document.querySelectorAll('.page').forEach(section => {
    const active = section.id === 'page-' + state.currentPage;
    section.hidden = !active;
    section.classList.toggle('active', active);
  });
  document.querySelectorAll('.nav-item').forEach(button => {
    button.classList.toggle('active', button.dataset.page === state.currentPage);
  });
  loadPage(state.currentPage);
}

function loadPage(page) {
  const loader = PAGE_LOADERS[normalizePage(page)];
  if (loader) loader();
}

async function loadCommandCenter() {
  const [overview, memory, feishu, embedding, tasks] = await Promise.all([
    fetchAPI('/control/overview'),
    fetchAPI('/memory/stats'),
    fetchAPI('/feishu/status'),
    fetchAPI('/embedding/status'),
    fetchAPI('/tasks?limit=50'),
  ]);
  renderCommandStatusOverview(overview, memory, feishu, embedding);
  renderCommandTasks(tasks);
  renderCommandErrors(overview);
  renderCommandRouting(overview);
  renderCommandAudit(overview);
}

function renderCommandStatusOverview(overview, memory, feishu, embedding) {
  const summary = (overview && overview.summary) || {};
  const agentsTotal = summary.agents_total ?? 0;
  const agentsHealthy = summary.agents_healthy ?? 0;
  const tasksTotal = summary.tasks_total ?? 0;
  const tasksFailed = summary.tasks_failed ?? 0;
  const feishuState = feishu && feishu.connected ? '已连接' : feishu && feishu.enabled ? '连接中' : '未启用';
  const embeddingState = embedding && embedding.has_local_model ? '本地可用' : 'API/关键词后备';
  const cards = [
    ['整体状态', overview ? overview.status : 'unknown', overview && overview.status === 'healthy' ? 'green' : 'orange', '控制面当前汇总状态'],
    ['Agent 健康', agentsHealthy + '/' + agentsTotal, agentsHealthy === agentsTotal && agentsTotal > 0 ? 'green' : 'orange', '健康数 / 总数'],
    ['任务', tasksTotal + ' 总数', tasksFailed ? 'red' : 'green', tasksFailed + ' 失败'],
    ['记忆', (memory && memory.total) ?? 0, '', '团队与个人记忆条目'],
    ['飞书通道', feishuState, feishu && feishu.connected ? 'green' : '', '外部消息连接'],
    ['Embedding', embeddingState, embedding && embedding.has_local_model ? 'green' : 'orange', '向量能力状态'],
  ];
  $('command-status-overview').innerHTML = cards.map(([label, value, cls, detail]) => (
    '<div class="metric-card ' + cls + '"><p class="metric-value">' + escapeHtml(value ?? 0) +
    '</p><p class="metric-label">' + escapeHtml(label) + '</p><p class="metric-detail">' +
    escapeHtml(detail || '') + '</p></div>'
  )).join('');
}

function renderCommandTasks(data) {
  const tasks = (data && data.tasks) || [];
  $('command-tasks-tbody').innerHTML = tasks.slice(0, 10).map(taskRow).join('') ||
    '<tr><td colspan="7" class="empty">暂无任务</td></tr>';
}

function renderCommandErrors(overview) {
  const errors = (overview && overview.recent_errors) || [];
  $('command-errors-list').innerHTML = errors.length ? errors.map(error => (
    listItem(error.routed_agent || error.trace_id || '任务失败', (error.error_message || '').slice(0, 120))
  )).join('') : emptyHtml('暂无错误');
}

function renderCommandRouting(overview) {
  const strategies = (overview && overview.strategies) || [];
  $('command-routing-list').innerHTML = strategies.length ? strategies.slice(0, 6).map(strategy => (
    listItem(strategy.name || '-', (strategy.kind || '-') + ' · ' + (strategy.enabled === false ? '禁用' : '启用'))
  )).join('') : emptyHtml('暂无策略');
}

function renderCommandAudit(overview) {
  const events = (overview && overview.recent_audit_events) || [];
  $('command-audit-list').innerHTML = events.length ? events.slice(0, 6).map(event => (
    listItem(event.module || '-', (event.action || '-') + (event.trace_id ? ' · ' + event.trace_id : ''))
  )).join('') : emptyHtml('暂无审计事件');
}

function listItem(title, meta) {
  return '<div class="list-item"><div class="item-title">' + escapeHtml(title) +
    '</div><div class="item-meta">' + escapeHtml(meta || '-') + '</div></div>';
}

function taskRow(task) {
  return '<tr>' +
    '<td>' + escapeHtml(formatTime(task.created_at)) + '</td>' +
    '<td>' + escapeHtml((task.trace_id || '').slice(0, 12)) + '</td>' +
    '<td>' + escapeHtml((task.user_message || '').slice(0, 80)) + '</td>' +
    '<td>' + escapeHtml(task.routed_agent || '-') + '</td>' +
    '<td>' + statusBadge(task.status) + '</td>' +
    '<td>' + escapeHtml(formatMs(task.execution_time_ms)) + '</td>' +
    '<td>' + rowButton('详情', 'open-task-detail', task.trace_id, 'btn-task-replay') + '</td>' +
  '</tr>';
}

async function loadTasksWorkbench() {
  const status = $('task-status-filter').value;
  const suffix = status ? '&status=' + encodeURIComponent(status) : '';
  const [tasks, errors] = await Promise.all([
    fetchAPI('/tasks?limit=50' + suffix),
    fetchAPI('/tasks/recent-errors?limit=10'),
  ]);
  $('tasks-tbody').innerHTML = ((tasks && tasks.tasks) || []).map(taskRow).join('') ||
    '<tr><td colspan="7" class="empty">暂无任务</td></tr>';
  $('task-errors-list').innerHTML = ((errors && errors.errors) || []).map(error => (
    listItem(error.trace_id || 'failed', (error.error_message || '').slice(0, 140))
  )).join('') || emptyHtml('暂无失败任务');
}

async function openTaskDetail(traceId) {
  if (!traceId) {
    showToast('缺少 trace_id', 'error');
    return;
  }
  $('task-replay-panel').classList.add('open');
  $('task-replay-panel').setAttribute('aria-hidden', 'false');
  $('task-replay-title').textContent = traceId;
  $('task-detail-summary').innerHTML = emptyHtml('加载中...');
  $('task-detail-routing').innerHTML = emptyHtml('加载中...');
  $('task-replay-content').innerHTML = emptyHtml('加载中...');
  $('task-detail-audit').innerHTML = emptyHtml('加载中...');

  const [explanation, replay] = await Promise.all([
    fetchAPI("/tasks/" + encodeURIComponent(traceId) + "/explanation"),
    fetchAPI("/tasks/" + encodeURIComponent(traceId) + "/replay?limit=50"),
  ]);
  renderTaskExplanation(explanation);
  renderTaskReplay(replay);
}

function loadTaskReplay(traceId) {
  return openTaskDetail(traceId);
}

function closeTaskDetail() {
  $('task-replay-panel').classList.remove('open');
  $('task-replay-panel').setAttribute('aria-hidden', 'true');
}

function renderTaskExplanation(data) {
  if (!data || !data.found) {
    $('task-detail-summary').innerHTML = emptyHtml('未找到任务');
    $('task-detail-routing').innerHTML = emptyHtml('无路由解释');
    $('task-detail-audit').innerHTML = emptyHtml('无审计事件');
    return;
  }
  const task = data.task || {};
  $('task-detail-summary').innerHTML =
    '<div><strong>状态：</strong>' + statusBadge(data.status) + '</div>' +
    '<div><strong>阶段：</strong>' + escapeHtml(data.stage || '-') + '</div>' +
    '<div><strong>摘要：</strong>' + escapeHtml(data.summary || '-') + '</div>' +
    '<div><strong>Agent：</strong>' + escapeHtml(task.routed_agent || '-') + '</div>' +
    '<div><strong>耗时：</strong>' + escapeHtml(formatMs(task.execution_time_ms)) + '</div>';
  const routing = data.routing || {};
  const decision = routing.decision || {};
  $('task-detail-routing').innerHTML =
    '<div><strong>策略：</strong>' + escapeHtml(decision.strategy || '-') + '</div>' +
    '<div><strong>选中 Agent：</strong>' + escapeHtml(decision.agent_id || '-') + '</div>' +
    '<div><strong>置信度：</strong>' + escapeHtml(decision.confidence ?? '-') + '</div>' +
    '<div><strong>治理事件：</strong>' + escapeHtml((routing.governance_events || []).length) + '</div>';
  const audit = data.audit_events || [];
  $('task-detail-audit').innerHTML = audit.length ? audit.map(event => (
    '<div class="detail-event"><strong>' + escapeHtml(event.module || '-') + '</strong> · ' +
    escapeHtml(event.action || '-') + '<div class="item-meta">' + escapeHtml(event.created_at || '') + '</div></div>'
  )).join('') : emptyHtml('无审计事件');
}

function renderTaskReplay(data) {
  if (!data) {
    $('task-replay-content').innerHTML = emptyHtml('回放加载失败');
    return;
  }
  if (!data.found) {
    $('task-replay-content').innerHTML = emptyHtml('未找到持久化任务事件');
    return;
  }
  const events = data.timeline || [];
  const header = '<div class="item-meta">状态：' + escapeHtml(data.replay_status || '-') +
    ' · 事件：' + escapeHtml(data.event_count || 0) +
    ' · 来源：' + escapeHtml(data.source || '-') + '</div>';
  const rows = events.map(formatReplayEvent).join('') || emptyHtml('暂无事件');
  $('task-replay-content').innerHTML = header + rows;
}

function formatReplayEvent(event, index) {
  const type = event.event_type || '-';
  const preview = event.payload && event.payload.preview ? event.payload.preview : '';
  const message = event.message || preview || '';
  const border = type === 'partial_output' ? '#2563eb' : '#cbd5e1';
  return '<div class="detail-event" style="border-left-color:' + border + '">' +
    '<div class="item-meta">' + (index + 1) + '. ' + escapeHtml(event.created_at || '-') +
    ' · ' + escapeHtml(type) + (event.agent_id ? ' · ' + escapeHtml(event.agent_id) : '') + '</div>' +
    (message ? '<div>' + escapeHtml(message).slice(0, 320) + '</div>' : '') +
  '</div>';
}

async function loadAgentsWorkbench() {
  const [agentsData, connectorsData] = await Promise.all([
    fetchAPI('/agents'),
    fetchAPI('/connectors'),
  ]);
  const installed = {};
  const rows = [];
  ((agentsData && agentsData.agents) || []).forEach(agent => {
    installed[agent.id] = true;
    rows.push({
      id: agent.id,
      name: agent.name,
      type: agent.type,
      tags: agent.tags || [],
      installed: true,
      healthy: agent.healthy,
      enabled: agent.enabled,
    });
  });
  ((connectorsData && connectorsData.connectors) || []).forEach(connector => {
    if (!installed[connector.id]) {
      rows.push({
        id: connector.id,
        name: connector.name,
        type: connector.type,
        tags: connector.tags || [],
        installed: false,
        healthy: null,
        enabled: false,
      });
    }
  });
  state.agents = rows;
  $('agents-tbody').innerHTML = rows.map(agent => (
    '<tr><td><strong>' + escapeHtml(agent.name) + '</strong><div class="item-meta">' + escapeHtml(agent.id) + '</div></td>' +
    '<td>' + escapeHtml(agent.type || '-') + '</td>' +
    '<td>' + tagsHtml(agent.tags) + '</td>' +
    '<td>' + (agent.installed ? statusBadge('healthy') : '<span class="item-meta">未安装</span>') + '</td>' +
    '<td>' + (agent.installed ? statusBadge(agent.healthy ? 'healthy' : 'unhealthy') : '-') + '</td>' +
    '<td>' + (agent.installed ? agentOps(agent) : '<span class="item-meta">连接器</span>') + '</td></tr>'
  )).join('') || '<tr><td colspan="6" class="empty">暂无 Agent</td></tr>';
}

function agentOps(agent) {
  return rowButton('测试', 'test-agent', agent.id) + ' ' +
    rowButton('重启', 'restart-agent', agent.id) + ' ' +
    rowButton('标签', 'edit-agent-tags', agent.id) + ' ' +
    rowButton(agent.enabled ? '禁用' : '启用', 'toggle-agent', agent.id);
}

async function scanAgents() {
  showToast('正在扫描...');
  try {
    const res = await fetch('/v1/agents/scan', { method: 'POST' });
    await res.json();
    showToast('扫描完成');
    loadAgentsWorkbench();
  } catch (error) {
    showToast('扫描失败: ' + error.message, 'error');
  }
}

async function testAgent(agentId) {
  try {
    const res = await fetch('/v1/agents/' + encodeURIComponent(agentId) + '/health-check', { method: 'POST' });
    const data = await res.json();
    showToast(data.healthy ? agentId + ' 连接正常' : agentId + ' 连接异常', data.healthy ? 'success' : 'error');
    loadAgentsWorkbench();
  } catch (error) {
    showToast('测试失败: ' + error.message, 'error');
  }
}

async function restartAgent(agentId) {
  const data = await fetchAPI('/agents/' + encodeURIComponent(agentId) + '/restart', { method: 'POST' });
  showToast(data && data.error ? '重启失败: ' + data.error : agentId + ' 重启完成', data && data.error ? 'error' : 'success');
  loadAgentsWorkbench();
}

async function toggleAgent(agentId) {
  const data = await fetchAPI('/agents/' + encodeURIComponent(agentId) + '/toggle', { method: 'POST' });
  showToast(data && data.error ? '切换失败: ' + data.error : agentId + (data && data.enabled ? ' 已启用' : ' 已禁用'), data && data.error ? 'error' : 'success');
  loadAgentsWorkbench();
}

async function editAgentTags(agentId) {
  const agent = state.agents.find(item => item.id === agentId) || {};
  const current = (agent.tags || []).join(', ');
  const input = prompt('编辑标签，多个标签用英文逗号分隔', current);
  if (input == null) return;
  const tags = input.split(',').map(tag => tag.trim()).filter(Boolean);
  const data = await fetchAPI('/agents/' + encodeURIComponent(agentId) + '/tags', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  });
  showToast(data && data.error ? '标签保存失败: ' + data.error : '标签已保存', data && data.error ? 'error' : 'success');
  if (data) loadAgentsWorkbench();
}

async function addAgent() {
  const body = {
    id: $('new-agent-id').value.trim(),
    name: $('new-agent-name').value.trim(),
    command: $('new-agent-cmd').value.trim(),
    tags: $('new-agent-tags').value.trim(),
  };
  if (!body.id || !body.name || !body.command) {
    showToast('请填写 ID、名称和命令', 'error');
    return;
  }
  const data = await fetchAPI('/agents/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  $('add-agent-msg').textContent = data && data.ok ? '已添加' : (data && data.error) || '添加失败';
  if (data && data.ok) {
    $('new-agent-id').value = '';
    $('new-agent-name').value = '';
    $('new-agent-cmd').value = '';
    $('new-agent-tags').value = '';
    $('add-agent-panel').hidden = true;
    loadAgentsWorkbench();
  }
}

async function loadRoutingWorkbench() {
  const [rules, strategies, agents] = await Promise.all([
    fetchAPI('/rules'),
    fetchAPI('/routing/strategies'),
    fetchAPI('/agents'),
  ]);
  renderAgentOptions((agents && agents.agents) || []);
  $('routing-strategies-list').innerHTML = ((strategies && strategies.strategies) || []).map(strategy => (
    listItem(strategy.name || '-', (strategy.kind || '-') + ' · ' + (strategy.enabled === false ? '禁用' : '启用'))
  )).join('') || emptyHtml('暂无策略');
  renderRouteRules((rules && rules.rules) || []);
}

function renderAgentOptions(agents) {
  const options = '<option value="">-</option>' + agents.map(agent => (
    '<option value="' + escapeHtml(agent.id) + '">' + escapeHtml(agent.name || agent.id) + '</option>'
  )).join('');
  $('rm-first').innerHTML = options;
  $('rm-second').innerHTML = options;
}

function renderRouteRules(rules) {
  if (!rules.length) {
    $('route-matrix-list').innerHTML = '<table><thead><tr><th>规则</th><th>匹配</th><th>第一选择</th><th>第二选择</th><th>类型</th><th>操作</th></tr></thead><tbody><tr><td colspan="6" class="empty">暂无规则</td></tr></tbody></table>';
    return;
  }
  $('route-matrix-list').innerHTML = '<table><thead><tr><th>规则</th><th>匹配</th><th>第一选择</th><th>第二选择</th><th>类型</th><th>操作</th></tr></thead><tbody>' +
    rules.map(rule => '<tr><td>' + tagsHtml([rule.name]) + '</td><td>' + escapeHtml((rule.patterns || []).join(', ') || '-') +
      '</td><td>' + escapeHtml(rule.first_agent || rule.target_agent || '-') + '</td><td>' + escapeHtml(rule.second_agent || '-') +
      '</td><td>' + escapeHtml(rule.type || '-') + '</td><td>' + rowButton('删除', 'delete-route-rule', rule.name) + '</td></tr>').join('') +
    '</tbody></table>';
}

async function saveRouteRule() {
  const name = $('rm-name').value.trim();
  if (!name) {
    showToast('请输入规则名', 'error');
    return;
  }
  const body = {
    name,
    type: $('rm-type').value,
    patterns: $('rm-patterns').value.split(',').map(part => part.trim()).filter(Boolean),
    first_agent: $('rm-first').value,
    second_agent: $('rm-second').value,
    priority: 10,
  };
  const data = await fetchAPI('/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  showToast(data && data.ok ? '规则已保存' : (data && data.error) || '保存失败', data && data.ok ? 'success' : 'error');
  if (data && data.ok) {
    $('route-form').hidden = true;
    loadRoutingWorkbench();
  }
}

async function deleteRouteRule(name) {
  if (!confirm('确认删除规则 ' + name + '？')) return;
  const data = await fetchAPI('/rules/' + encodeURIComponent(name), { method: 'DELETE' });
  showToast(data && data.ok ? '已删除' : '删除失败', data && data.ok ? 'success' : 'error');
  loadRoutingWorkbench();
}

async function loadAuditWorkbench() {
  const params = new URLSearchParams({
    limit: '80',
    module: $('audit-module').value.trim(),
    action: $('audit-action').value.trim(),
    agent_id: $('audit-agent').value.trim(),
    trace_id: $('audit-trace').value.trim(),
  });
  const data = await fetchAPI('/audit/events?' + params.toString());
  const events = (data && data.events) || [];
  $('audit-tbody').innerHTML = events.map(event => (
    '<tr><td>' + escapeHtml(formatTime(event.created_at)) + '</td><td>' + escapeHtml(event.module || '-') +
    '</td><td>' + escapeHtml(event.action || '-') + '</td><td>' + escapeHtml(event.agent_id || '-') +
    '</td><td>' + escapeHtml(event.risk_level || '-') + '</td><td>' + escapeHtml(event.trace_id || '-') + '</td></tr>'
  )).join('') || '<tr><td colspan="6" class="empty">暂无审计事件</td></tr>';
}

async function loadMemoryWorkbench() {
  await Promise.all([loadMemoryStats(), searchMemory()]);
}

async function loadMemoryStats() {
  const data = await fetchAPI('/memory/stats');
  $('memory-stats-row').innerHTML =
    '<div class="metric-card"><p class="metric-value">' + escapeHtml(data && data.total || 0) +
    '</p><p class="metric-label">记忆总数</p></div>' +
    '<div class="metric-card green"><p class="metric-value">' + escapeHtml(data && data.latest_at ? formatTime(data.latest_at) : '-') +
    '</p><p class="metric-label">最新记忆</p></div>';
}

async function searchMemory() {
  const q = $('mem-query').value || '';
  const uid = $('mem-user').value || '';
  const data = await fetchAPI('/memory/search?q=' + encodeURIComponent(q) + '&user_id=' + encodeURIComponent(uid) + '&limit=30');
  const memories = (data && data.memories) || [];
  $('memory-list').innerHTML = memories.length ?
    '<table><thead><tr><th>摘要</th><th>来源</th><th>时间</th><th>标签</th><th>操作</th></tr></thead><tbody>' +
    memories.map(memory => '<tr><td>' + escapeHtml((memory.summary || '').slice(0, 120)) + '</td><td>' +
      escapeHtml(memory.source_agent || '-') + '</td><td>' + escapeHtml(formatTime(memory.created_at)) +
      '</td><td>' + tagsHtml(memory.tags || []) + '</td><td>' + rowButton('删除', 'delete-memory', memory.memory_id) + '</td></tr>').join('') +
    '</tbody></table>' : emptyHtml('暂无记忆');
}

async function deleteMemory(memoryId) {
  if (!confirm('确认删除这条记忆？')) return;
  const data = await fetchAPI('/memory/' + encodeURIComponent(memoryId), { method: 'DELETE' });
  showToast(data && data.ok ? '已删除' : '删除失败', data && data.ok ? 'success' : 'error');
  loadMemoryWorkbench();
}

async function cleanupMemory() {
  if (!confirm('确认清理超过30天的记忆？')) return;
  const data = await fetchAPI('/memory/cleanup', { method: 'POST' });
  showToast('已清理 ' + escapeHtml(data && data.deleted || 0) + ' 条记忆');
  loadMemoryWorkbench();
}

async function loadOrchestrationPlans() {
  try {
    const resp = await fetch('/v1/orchestrations/list');
    const data = await resp.json();
    const plans = data.plans || [];
    $('orchestration-plans-list').innerHTML = '<table><thead><tr><th>名称</th><th>触发词</th><th>流程</th><th>使用次数</th><th>操作</th></tr></thead><tbody>' +
      (plans.map(plan => '<tr><td><strong>' + escapeHtml(plan.name) + '</strong></td><td>' +
        escapeHtml((plan.trigger_words || []).join(', ') || '无') + '</td><td>' +
        escapeHtml((plan.steps || []).map(step => step.agent_id).join(' -> ') || '无步骤') + '</td><td>' +
        escapeHtml(plan.usage_count || 0) + '</td><td>' + rowButton('删除', 'delete-orchestration', plan.plan_id) + '</td></tr>').join('') ||
        '<tr><td colspan="5" class="empty">暂无已保存计划</td></tr>') + '</tbody></table>';
  } catch (error) {
    $('orchestration-plans-list').innerHTML = emptyHtml('编排计划加载失败');
  }
}

function loadOrchPlans() {
  return loadOrchestrationPlans();
}

async function deleteOrchestration(planId) {
  if (!confirm('确认删除这个编排计划？删除后无法恢复')) return;
  const resp = await fetch('/v1/orchestrations/' + encodeURIComponent(planId), { method: 'DELETE' });
  const data = await resp.json();
  showToast(data && data.ok ? '已删除' : '删除失败', data && data.ok ? 'success' : 'error');
  loadOrchestrationPlans();
}

async function loadSettingsWorkbench() {
  await Promise.all([loadFeishuConfig(), loadSettings(), loadEmbeddingStatus()]);
}

function setToggleBtn(id, enabled, onText = '已启用', offText = '已禁用') {
  const button = $(id);
  if (!button) return;
  button.textContent = enabled ? onText : offText;
  button.classList.toggle('enabled', !!enabled);
}

async function loadFeishuConfig() {
  const [cfg, status] = await Promise.all([fetchAPI('/feishu/config'), fetchAPI('/feishu/status')]);
  if (cfg) {
    $('feishu-app-id').value = cfg.app_id || '';
    $('feishu-app-secret').value = cfg.app_secret || '';
  }
  setToggleBtn('btn-feishu-toggle', status && status.connected, '已连接', '未连接');
}

async function toggleFeishu() {
  const connected = $('btn-feishu-toggle').textContent === '已连接';
  if (connected) {
    const data = await fetchAPI('/feishu/disconnect', { method: 'POST' });
    $('feishu-save-msg').textContent = data && data.ok ? '已断开' : '断开失败';
  } else {
    const appId = $('feishu-app-id').value.trim();
    const appSecret = $('feishu-app-secret').value.trim();
    if (!appId || !appSecret) {
      showToast('请填写 App ID 和 Secret', 'error');
      return;
    }
    const data = await fetchAPI('/feishu/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
    });
    $('feishu-save-msg').textContent = data && data.ok ? '已连接' : (data && data.error) || '连接失败';
  }
  loadFeishuConfig();
}

async function loadSettings() {
  const data = await fetchAPI('/settings');
  if (!data) return;
  const memory = data.memory || {};
  const embedding = data.embedding || {};
  const semantic = data.semantic_router || {};
  const history = data.history || {};
  const meta = data.meta || {};
  $('setting-max-entries').value = memory.max_entries || 10000;
  $('setting-history-max-entries').value = history.max_entries ?? 10000;
  $('setting-history-retention-days').value = history.retention_days || 30;
  $('setting-emb-endpoint').value = embedding.endpoint || '';
  $('setting-emb-key').value = embedding.api_key || '';
  $('setting-emb-model').value = embedding.model || 'text-embedding-3-small';
  $('setting-sr-endpoint').value = semantic.endpoint || '';
  $('setting-sr-key').value = semantic.api_key || '';
  $('setting-sr-model').value = semantic.model || '';
  $('setting-core-llm-endpoint').value = meta.endpoint || '';
  $('setting-core-llm-key').value = meta.api_key || '';
  $('setting-core-llm-model').value = meta.model || '';
  setToggleBtn('btn-sr-toggle', semantic.enabled || false);
  setToggleBtn('btn-emb-toggle', embedding.enabled || false);
  setToggleBtn('btn-core-llm-toggle', meta.enabled || false);
}

async function saveSettingsSection(section) {
  const resp = await fetchAPI('/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(section),
  });
  return resp && resp.ok;
}

async function toggleSemantic() {
  const enabled = $('btn-sr-toggle').textContent !== '已启用';
  if (enabled && (!$('setting-sr-endpoint').value.trim() || !$('setting-sr-key').value.trim() || !$('setting-sr-model').value.trim())) {
    showToast('请填写语义路由配置', 'error');
    return;
  }
  const ok = await saveSettingsSection({ semantic_router: {
    enabled,
    endpoint: $('setting-sr-endpoint').value.trim(),
    api_key: $('setting-sr-key').value.trim(),
    model: $('setting-sr-model').value.trim(),
    timeout_seconds: 5,
  }});
  if (ok) setToggleBtn('btn-sr-toggle', enabled);
  showToast(ok ? (enabled ? '语义路由已启用' : '语义路由已禁用') : '保存失败', ok ? 'success' : 'error');
}

async function toggleEmbedding() {
  const enabled = $('btn-emb-toggle').textContent !== '已启用';
  if (enabled && (!$('setting-emb-endpoint').value.trim() || !$('setting-emb-key').value.trim() || !$('setting-emb-model').value.trim())) {
    showToast('请填写 Embedding 配置', 'error');
    return;
  }
  const ok = await saveSettingsSection({ embedding: {
    enabled,
    endpoint: $('setting-emb-endpoint').value.trim(),
    api_key: $('setting-emb-key').value.trim(),
    model: $('setting-emb-model').value.trim() || 'text-embedding-3-small',
    dimension: 768,
    timeout_seconds: 10,
  }});
  if (ok) setToggleBtn('btn-emb-toggle', enabled);
  if (ok) loadEmbeddingStatus();
  showToast(ok ? (enabled ? 'Embedding 已启用' : 'Embedding 已禁用') : '保存失败', ok ? 'success' : 'error');
}

async function toggleCoreLLM() {
  const enabled = $('btn-core-llm-toggle').textContent !== '已启用';
  if (enabled && (!$('setting-core-llm-endpoint').value.trim() || !$('setting-core-llm-key').value.trim() || !$('setting-core-llm-model').value.trim())) {
    showToast('请填写 Core LLM 配置', 'error');
    return;
  }
  const ok = await saveSettingsSection({ meta: {
    enabled,
    endpoint: $('setting-core-llm-endpoint').value.trim(),
    api_key: $('setting-core-llm-key').value.trim(),
    model: $('setting-core-llm-model').value.trim() || 'glm-4',
    timeout_seconds: 10,
  }});
  if (ok) setToggleBtn('btn-core-llm-toggle', enabled);
  showToast(ok ? (enabled ? 'Core LLM 已启用' : 'Core LLM 已禁用') : '保存失败', ok ? 'success' : 'error');
}

async function loadEmbeddingStatus() {
  const data = await fetchAPI('/embedding/status');
  if (!data) return;
  $('embedding-status-line').textContent = data.has_local_model ?
    '本地模型已安装，离线语义搜索可用' :
    '未检测到本地模型，使用 API 或关键词后备';
}

async function saveRetentionSettings() {
  const maxEntries = parseInt($('setting-max-entries').value, 10);
  const historyMax = parseInt($('setting-history-max-entries').value, 10);
  const retentionDays = parseInt($('setting-history-retention-days').value, 10);
  const ok = await saveSettingsSection({
    memory: { max_entries: Number.isNaN(maxEntries) ? 10000 : maxEntries },
    history: {
      max_entries: Number.isNaN(historyMax) ? 10000 : historyMax,
      retention_days: Number.isNaN(retentionDays) ? 30 : retentionDays,
    },
  });
  $('settings-save-msg').textContent = ok ? '已保存' : '保存失败';
}

function handleAction(action, id) {
  const actions = {
    'refresh-current': () => loadPage(state.currentPage),
    'load-tasks': loadTasksWorkbench,
    'open-task-detail': () => openTaskDetail(id),
    'close-task-detail': closeTaskDetail,
    'scan-agents': scanAgents,
    'toggle-add-agent': () => { $('add-agent-panel').hidden = !$('add-agent-panel').hidden; },
    'add-agent': addAgent,
    'test-agent': () => testAgent(id),
    'restart-agent': () => restartAgent(id),
    'edit-agent-tags': () => editAgentTags(id),
    'toggle-agent': () => toggleAgent(id),
    'toggle-route-form': () => { $('route-form').hidden = !$('route-form').hidden; },
    'save-route-rule': saveRouteRule,
    'delete-route-rule': () => deleteRouteRule(id),
    'load-audit': loadAuditWorkbench,
    'search-memory': searchMemory,
    'delete-memory': () => deleteMemory(id),
    'cleanup-memory': cleanupMemory,
    'delete-orchestration': () => deleteOrchestration(id),
    'toggle-feishu': toggleFeishu,
    'toggle-semantic': toggleSemantic,
    'toggle-embedding': toggleEmbedding,
    'toggle-core-llm': toggleCoreLLM,
    'save-retention-settings': saveRetentionSettings,
  };
  if (actions[action]) actions[action]();
}

document.addEventListener('click', event => {
  const nav = event.target.closest('[data-page]');
  if (nav) {
    activatePage(nav.dataset.page);
    return;
  }
  const pageLink = event.target.closest('[data-page-link]');
  if (pageLink) {
    activatePage(pageLink.dataset.pageLink);
    return;
  }
  const action = event.target.closest('[data-action]');
  if (action) {
    handleAction(action.dataset.action, action.dataset.id);
  }
});

document.addEventListener('keyup', event => {
  if (event.key === 'Enter' && (event.target.id === 'mem-query' || event.target.id === 'mem-user')) {
    searchMemory();
  }
});

activatePage(state.currentPage);
