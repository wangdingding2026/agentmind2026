const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync('src/agentmind/panel/static/index.html', 'utf8');
const script = fs.readFileSync('src/agentmind/panel/static/dashboard.js', 'utf8');

function attrs(source) {
  const out = {};
  for (const match of source.matchAll(/([a-zA-Z0-9_-]+)(?:="([^"]*)")?/g)) {
    out[match[1]] = match[2] == null ? '' : match[2];
  }
  return out;
}

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set((element.className || '').split(/\s+/).filter(Boolean));
  }

  add(value) {
    this.values.add(value);
    this._sync();
  }

  remove(value) {
    this.values.delete(value);
    this._sync();
  }

  toggle(value, force) {
    if (force === undefined ? !this.values.has(value) : force) this.values.add(value);
    else this.values.delete(value);
    this._sync();
  }

  contains(value) {
    return this.values.has(value);
  }

  _sync() {
    this.element.className = [...this.values].join(' ');
  }
}

class Element {
  constructor(tagName, attributes = {}) {
    this.tagName = tagName.toUpperCase();
    this.id = attributes.id || '';
    this.dataset = {};
    this.attributes = { ...attributes };
    this.className = attributes.class || '';
    this.classList = new ClassList(this);
    this.hidden = Object.prototype.hasOwnProperty.call(attributes, 'hidden');
    this.value = attributes.value || '';
    this.textContent = '';
    this.innerHTML = '';
    this.children = [];
    for (const [name, value] of Object.entries(attributes)) {
      if (name.startsWith('data-')) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        this.dataset[key] = value;
      }
    }
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') {
      this.className = String(value);
      this.classList = new ClassList(this);
    }
    if (name.startsWith('data-')) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = String(value);
    }
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  closest(selector) {
    if (selector === '[data-page]' && this.dataset.page) return this;
    if (selector === '[data-page-link]' && this.dataset.pageLink) return this;
    if (selector === '[data-action]' && this.dataset.action) return this;
    return null;
  }
}

function createDocument() {
  const elements = [];
  const byId = new Map();
  for (const match of html.matchAll(/<([a-zA-Z0-9]+)\s+([^>]*?)>/g)) {
    const element = new Element(match[1], attrs(match[2]));
    elements.push(element);
    if (element.id) byId.set(element.id, element);
  }
  return {
    elements,
    byId,
    listeners: {},
    getElementById(id) {
      return byId.get(id) || null;
    },
    querySelectorAll(selector) {
      if (selector === '.page') return elements.filter(el => el.classList.contains('page'));
      if (selector === '.nav-item') return elements.filter(el => el.classList.contains('nav-item'));
      return [];
    },
    addEventListener(type, handler) {
      this.listeners[type] = this.listeners[type] || [];
      this.listeners[type].push(handler);
    },
  };
}

const fixtures = {
  '/control/overview': {
    status: 'healthy',
    summary: {
      agents_total: 2,
      agents_healthy: 1,
      tasks_total: 3,
      tasks_failed: 1,
    },
    strategies: [{ name: 'explicit', kind: 'core', enabled: true }],
    recent_errors: [{ trace_id: 't-fail', routed_agent: 'a1', error_message: 'boom' }],
    recent_audit_events: [{ module: 'routing', action: 'decide', trace_id: 't1' }],
  },
  '/memory/stats': { total: 2, latest_at: '2026-06-01T00:00:00Z' },
  '/feishu/status': { connected: false, enabled: false },
  '/embedding/status': { enabled: true, has_external_api: true, has_local_model: false },
  '/tasks?limit=50': {
    tasks: [{ trace_id: 't1', created_at: '2026-06-01T00:00:00Z', user_message: 'run task', routed_agent: 'a1', status: 'completed', execution_time_ms: 42 }],
  },
  '/tasks?limit=50&status=failed': {
    tasks: [{ trace_id: 't-fail', created_at: '2026-06-01T00:00:00Z', user_message: 'fail task', routed_agent: 'a1', status: 'failed', execution_time_ms: 9 }],
  },
  '/tasks/recent-errors?limit=10': { errors: [{ trace_id: 't-fail', error_message: 'boom' }] },
  '/tasks/t1/explanation': {
    found: true,
    status: 'completed',
    stage: 'completed',
    summary: 'Task completed',
    task: { routed_agent: 'a1', execution_time_ms: 42 },
    routing: { decision: { strategy: 'explicit', agent_id: 'a1', confidence: 0.9 }, governance_events: [] },
    audit_events: [{ module: 'execution', action: 'complete', created_at: '2026-06-01T00:00:00Z' }],
  },
  '/tasks/t1/replay?limit=50': {
    found: true,
    replay_status: 'available',
    event_count: 1,
    source: 'task_events',
    timeline: [{ event_type: 'partial_output', created_at: '2026-06-01T00:00:00Z', message: 'hello', payload: {} }],
  },
  '/agents': {
    agents: [{ id: 'a1', name: 'Agent One', type: 'cli', tags: ['code'], healthy: true, enabled: true }],
  },
  '/connectors': { connectors: [{ id: 'a2', name: 'Agent Two', type: 'cli', tags: ['search'], open_way: 'agent-two' }] },
  '/routing/strategies': { strategies: [{ name: 'explicit', kind: 'core', enabled: true }] },
  '/rules': { rules: [{ name: 'code', patterns: ['code'], first_agent: 'a1', second_agent: '', type: 'keyword' }] },
  '/audit/events?limit=80&module=&action=&agent_id=&trace_id=': {
    events: [{
      created_at: '2026-06-01T00:00:00Z',
      module: 'config',
      action: 'update',
      agent_id: 'a1',
      risk_level: 'low',
      trace_id: 't1',
      payload: {
        area: 'settings',
        changed_keys: ['embedding'],
        data: {
          feishu: { enabled: true },
          embedding: { enabled: true },
        },
      },
    }],
  },
  '/memory/search?q=&user_id=&limit=30': {
    memories: [{ memory_id: 'm1', summary: 'remember this', source_agent: 'a1', created_at: '2026-06-01T00:00:00Z', tags: ['team'] }],
  },
  '/settings': {
    memory: { max_entries: 10000 },
    embedding: { enabled: false, endpoint: 'https://emb', api_key: 'k', model: 'text-embedding-3-small' },
    semantic_router: { enabled: false, endpoint: 'https://sr', api_key: 'k', model: 'm' },
    history: { max_entries: 10000, retention_days: 30 },
    meta: { enabled: false, endpoint: 'https://llm', api_key: 'k', model: 'glm-4' },
  },
};

async function main() {
  const document = createDocument();
  const requests = [];
  let scanResponse = { ok: true, json: async () => ({ ok: true }) };
  const storage = { agentmind_commander_page: 'api' };
  const context = {
    document,
    console,
    setTimeout(fn) { fn(); },
    localStorage: {
      getItem(key) { return storage[key] || null; },
      setItem(key, value) { storage[key] = String(value); },
    },
    confirm() { return true; },
    prompt(_message, current) { return current ? current + ', review' : 'review'; },
    URLSearchParams,
    TextDecoder,
    fetch: async (url, options = {}) => {
      requests.push({ url, method: options.method || 'GET', body: options.body || '' });
      if (url === '/v1/agents/scan') return scanResponse;
      if (url === '/v1/agents/a1/health-check') return { json: async () => ({ healthy: true }) };
      if (url === '/v1/orchestrations/list') return { json: async () => ({ plans: [{ plan_id: 'p1', name: 'Plan', trigger_words: ['go'], steps: [{ agent_id: 'a1' }], usage_count: 1 }] }) };
      if (url === '/v1/orchestrations/p1') return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/agents/a1/restart')) return { json: async () => ({ agent_id: 'a1', healthy: true }) };
      if (url.startsWith('/panel/api/agents/a1/toggle')) return { json: async () => ({ agent_id: 'a1', enabled: false }) };
      if (url.startsWith('/panel/api/agents/a1/tags')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/agents/a2/tags')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/agents/add')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/rules/code')) return { json: async () => ({ ok: true }) };
      if (url === '/panel/api/rules' && options.method === 'POST') return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/memory/m1')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/memory/cleanup')) return { json: async () => ({ deleted: 1 }) };
      if (url.startsWith('/panel/api/feishu/config')) return { json: async () => ({ app_id: 'cli', app_secret: 'secret' }) };
      if (url.startsWith('/panel/api/feishu/connect')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/feishu/disconnect')) return { json: async () => ({ ok: true }) };
      if (url.startsWith('/panel/api/settings') && options.method === 'POST') return { json: async () => ({ ok: true }) };
      const path = url.startsWith('/panel/api') ? url.slice('/panel/api'.length) : url;
      if (fixtures[path]) return { json: async () => fixtures[path] };
      throw new Error('Unhandled fetch ' + url);
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(script, context, { filename: 'dashboard.js' });
  await Promise.resolve();
  assert.strictEqual(storage.agentmind_commander_page, 'command');

  const pages = ['command', 'tasks', 'agents', 'routing', 'audit', 'memory', 'orchestrator', 'settings'];
  for (const page of pages) {
    context.activatePage(page);
    await Promise.resolve();
    assert.strictEqual(storage.agentmind_commander_page, page);
    const activePage = document.getElementById('page-' + page);
    assert(activePage && !activePage.hidden, 'page not visible: ' + page);
  }
  const statusOverview = document.getElementById('command-status-overview').innerHTML;
  assert(statusOverview.includes('系统状态'));
  assert(statusOverview.includes('正常'));
  assert(!statusOverview.includes('degraded'));
  assert(statusOverview.includes('Agent 健康'));
  assert(statusOverview.includes('1/2'));
  assert(statusOverview.includes('任务'));
  assert(statusOverview.includes('1 失败'));
  assert(statusOverview.includes('飞书通道'));
  assert(statusOverview.includes('智能匹配'));
  assert(statusOverview.includes('可用'));
  assert(statusOverview.includes('使用已配置的 API'));
  assert(!statusOverview.includes('Embedding'));
  assert(document.getElementById('command-tasks-tbody').innerHTML.includes('run task'));

  document.getElementById('task-status-filter').value = 'failed';
  await context.loadTasksWorkbench();
  assert(document.getElementById('tasks-tbody').innerHTML.includes('fail task'));
  await context.openTaskDetail('t1');
  assert(document.getElementById('task-replay-panel').classList.contains('open'));
  assert(document.getElementById('task-detail-summary').innerHTML.includes('Task completed'));
  assert(document.getElementById('task-detail-summary').innerHTML.includes('已完成'));
  assert(document.getElementById('task-replay-content').innerHTML.includes('可回放'));
  assert(document.getElementById('task-replay-content').innerHTML.includes('任务事件'));
  assert(document.getElementById('task-replay-content').innerHTML.includes('片段输出'));
  assert(!document.getElementById('task-replay-content').innerHTML.includes('partial_output'));
  context.closeTaskDetail();
  assert(!document.getElementById('task-replay-panel').classList.contains('open'));

  await context.loadAgentsWorkbench();
  assert(!document.getElementById('add-agent-panel').hidden, 'add agent panel should stay visible');
  assert(document.getElementById('agents-tbody').innerHTML.includes('Agent One'));
  const agentRowCells = document.getElementById('agents-tbody').innerHTML.split('</tr>')[0].split('</td>');
  assert(agentRowCells[2].includes('data-action="edit-agent-tags"'));
  assert(!agentRowCells[5].includes('data-action="edit-agent-tags"'));
  const connectorRowCells = document.getElementById('agents-tbody').innerHTML.split('</tr>')[1].split('</td>');
  assert(connectorRowCells[2].includes('data-action="edit-agent-tags"'));
  assert(connectorRowCells[5].includes('data-action="test-agent"'));
  assert(connectorRowCells[5].includes('data-action="restart-agent"'));
  assert(connectorRowCells[5].includes('data-action="toggle-agent"'));
  await context.scanAgents();
  assert.strictEqual(document.getElementById('toast').textContent, '扫描完成');
  scanResponse = {
    ok: false,
    status: 500,
    json: async () => ({ error: 'scan failed' }),
  };
  await context.scanAgents();
  assert(document.getElementById('toast').textContent.includes('scan failed'));
  await context.testAgent('a1');
  await context.restartAgent('a1');
  await context.toggleAgent('a1');
  await context.testAgent('a2');
  assert(document.getElementById('toast').textContent.includes('先启用'));
  await context.restartAgent('a2');
  assert(document.getElementById('toast').textContent.includes('先启用'));
  await context.toggleAgent('a2');
  await context.editAgentTags('a1');
  await context.editAgentTags('a2');
  document.getElementById('new-agent-name').value = 'New Agent';
  document.getElementById('new-agent-open').value = 'echo';
  document.getElementById('new-agent-tags').value = 'code';
  await context.addAgent();
  const addRequest = requests.find(req => req.url === '/panel/api/agents/add');
  assert(addRequest, 'missing add agent request');
  assert.deepStrictEqual(JSON.parse(addRequest.body), {
    agent: 'Agent Two',
    open_way: 'agent-two',
    tags: 'search',
  });
  const manualAddRequest = requests.filter(req => req.url === '/panel/api/agents/add')[1];
  assert(manualAddRequest, 'missing manual add agent request');
  assert.deepStrictEqual(JSON.parse(manualAddRequest.body), {
    agent: 'New Agent',
    open_way: 'echo',
    tags: 'code',
  });
  assert(document.getElementById('add-agent-msg').className.includes('success'));
  const toastAfterAdd = document.getElementById('toast').textContent;
  await context.addAgent();
  assert(document.getElementById('add-agent-msg').textContent.includes('打开方式'));
  assert(document.getElementById('add-agent-msg').className.includes('error'));
  assert.strictEqual(document.getElementById('toast').textContent, toastAfterAdd);

  await context.loadRoutingWorkbench();
  assert(document.getElementById('routing-strategies-list').innerHTML.includes('explicit'));
  assert(document.getElementById('route-matrix-list').innerHTML.includes('code'));
  document.getElementById('rm-name').value = 'code';
  document.getElementById('rm-patterns').value = 'code';
  document.getElementById('rm-first').value = 'a1';
  await context.saveRouteRule();
  await context.deleteRouteRule('code');

  await context.loadAuditWorkbench();
  assert(document.getElementById('audit-tbody').innerHTML.includes('配置'));
  assert(document.getElementById('audit-tbody').innerHTML.includes('智能匹配 Embedding 配置'));
  assert(document.getElementById('audit-tbody').innerHTML.includes('更新'));
  assert(!document.getElementById('audit-tbody').innerHTML.includes('config'));
  assert(!document.getElementById('audit-tbody').innerHTML.includes('update'));
  assert(!document.getElementById('audit-tbody').innerHTML.includes('系统设置'));
  await context.loadMemoryWorkbench();
  assert(document.getElementById('memory-list').innerHTML.includes('remember this'));
  await context.deleteMemory('m1');
  await context.cleanupMemory();
  await context.loadOrchestrationPlans();
  assert(document.getElementById('orchestration-plans-list').innerHTML.includes('Plan'));
  await context.loadOrchPlans();
  await context.deleteOrchestration('p1');
  await context.loadSettingsWorkbench();
  assert.strictEqual(document.getElementById('setting-sr-model').value, 'm');
  assert(document.getElementById('embedding-status-line').textContent.includes('已配置 API'));
  await context.toggleFeishu();
  await context.toggleSemantic();
  await context.toggleEmbedding();
  await context.toggleCoreLLM();
  await context.saveRetentionSettings();

  const requiredRequests = [
    '/panel/api/control/overview',
    '/panel/api/tasks?limit=50',
    '/panel/api/tasks/t1/explanation',
    '/panel/api/tasks/t1/replay?limit=50',
    '/panel/api/agents/a1/tags',
    '/panel/api/rules',
    '/panel/api/audit/events?limit=80&module=&action=&agent_id=&trace_id=',
    '/panel/api/memory/search?q=&user_id=&limit=30',
    '/v1/orchestrations/list',
    '/panel/api/settings',
  ];
  for (const url of requiredRequests) {
    assert(requests.some(req => req.url === url), 'missing request ' + url);
  }
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
