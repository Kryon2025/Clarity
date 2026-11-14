/* ============================================================
   深清商店 · 前端逻辑
   原生 JavaScript，无构建步骤；所有请求走同源 /api/*
   ============================================================ */
(function () {
  'use strict';

  var TOKEN_KEY = 'sq_token';
  var USER_KEY = 'sq_user';

  var PALETTE_KEYS = ['bgTop', 'bgMid', 'bgBottom', 'accent', 'cardBg', 'textPrimary'];
  var PALETTE_LABELS = {
    bgTop: '背景上', bgMid: '背景中', bgBottom: '背景下',
    accent: '强调色', cardBg: '卡片底色', textPrimary: '正文'
  };
  var FALLBACK_PALETTE = {
    bgTop: '#0A1F2E', bgMid: '#06202C', bgBottom: '#04121A',
    accent: '#35E0C8', cardBg: '#0D2634', textPrimary: '#EAF8FC'
  };
  var ROLE_LABELS = { user: '普通用户', developer: '开发者', admin: '管理员' };
  var STATUS_LABELS = { pending: '待审核', approved: '已通过', rejected: '已拒绝' };
  var KIND_LABELS = { theme: '主题', plugin: '插件' };
  /* 适配端：desktop=电脑端、mobile=手机端（与后端 items.platforms 一致） */
  var PLATFORMS = ['desktop', 'mobile'];
  var PLATFORM_LABELS = { desktop: '电脑端', mobile: '手机端' };
  /* 发布 Token（cwpt_...）：创建时只返回一次明文，列表只给前缀 */
  var TOKEN_STATUS_LABELS = { active: '生效中', revoked: '已撤销' };
  /* GitHub 发布源地址：仓库或 releases 页面（后端还会做一次严格校验） */
  var GITHUB_URL_RE = /^https?:\/\/(www\.)?github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+/i;

  var state = {
    token: '',
    user: null,
    items: [],
    itemsLoaded: false,
    itemsSeq: 0,
    itemsError: null,
    loadingItems: false,
    q: '',
    kind: '',
    platform: '',
    sort: 'rating',
    authMode: 'login',
    loginMode: 'password',
    devCode: { purpose: '', code: '' },
    adminTab: 'pending',
    pendingItems: [],
    pendingComments: [],
    users: [],
    devItems: [],
    editingId: null,
    tokens: [],
    tokensLoaded: false,
    newToken: '',
    returnHash: '#/store',
    detail: { item: null, comments: [], mode: 'store', loading: false, rating: 5, commentSubmitted: false }
  };

  // ---------- 基础工具 ----------
  function $(selector, root) { return (root || document).querySelector(selector); }
  function $$(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  function esc(value) {
    var text = value === null || value === undefined ? '' : String(value);
    return text.replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }

  function fmtNum(value) {
    var n = Number(value) || 0;
    if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, '') + '亿';
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    return String(n);
  }

  function fmtDate(value, withTime) {
    if (!value) return '—';
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value).slice(0, 10);
    function pad(n) { return String(n).padStart(2, '0'); }
    var text = date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
    if (!withTime) return text;
    return text + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  function toArray(value) {
    if (Array.isArray(value)) {
      return value.filter(function (item) { return typeof item === 'string' && item.trim(); }).map(function (item) { return item.trim(); });
    }
    if (typeof value !== 'string' || !value.trim()) return [];
    var text = value.trim();
    if (text.charAt(0) === '[') {
      try {
        var parsed = JSON.parse(text);
        if (Array.isArray(parsed)) return toArray(parsed);
      } catch (err) { /* 忽略：按分隔符处理 */ }
    }
    return text.split(/[,，\n]/).map(function (item) { return item.trim(); }).filter(Boolean);
  }

  function toPlatforms(value) {
    var list = toArray(value).map(function (item) { return String(item).toLowerCase(); });
    var out = [];
    PLATFORMS.forEach(function (key) {
      if (list.indexOf(key) >= 0) out.push(key);
    });
    return out.length ? out : ['desktop'];
  }

  function toPalette(value) {
    var obj = value;
    if (typeof value === 'string') {
      try { obj = JSON.parse(value); } catch (err) { obj = null; }
    }
    var out = {};
    if (!obj || typeof obj !== 'object') return out;
    PALETTE_KEYS.forEach(function (key) {
      var raw = obj[key];
      if (typeof raw === 'string' && /^#[0-9a-f]{6}$/i.test(raw.trim())) out[key] = raw.trim().toUpperCase();
    });
    return out;
  }

  function paletteWithDefaults(palette) {
    var out = {};
    PALETTE_KEYS.forEach(function (key) {
      out[key] = palette && palette[key] ? palette[key] : FALLBACK_PALETTE[key];
    });
    return out;
  }

  function paletteBackground(palette) {
    var p = paletteWithDefaults(palette);
    return 'linear-gradient(135deg, ' + p.bgTop + ' 0%, ' + p.bgMid + ' 52%, ' + p.bgBottom + ' 100%)';
  }

  function paletteDots(palette) {
    var p = paletteWithDefaults(palette);
    return ['accent', 'textPrimary', 'cardBg'].map(function (key) {
      return '<span class="swatch-dot" style="background:' + p[key] + '"></span>';
    }).join('');
  }

  function starsHTML(rating, large) {
    var value = clamp(Number(rating) || 0, 0, 5);
    var percent = (value / 5) * 100;
    return '<span class="stars' + (large ? ' lg' : '') + '" role="img" aria-label="评分 ' + value.toFixed(1) + ' 分">' +
      '<span class="stars-fill" style="width:' + percent.toFixed(1) + '%"></span></span>';
  }

  function roleLabel(role) { return ROLE_LABELS[role] || role || '用户'; }
  function statusLabel(status) { return STATUS_LABELS[status] || status; }
  function kindLabel(kind) { return KIND_LABELS[kind] || kind; }

  function rolePill(role) {
    var safe = role === 'admin' || role === 'developer' ? role : 'user';
    return '<span class="pill pill-role-' + safe + '">' + esc(roleLabel(safe)) + '</span>';
  }

  function statusPill(status) {
    var safe = status === 'approved' || status === 'rejected' ? status : 'pending';
    return '<span class="pill pill-' + safe + '">' + esc(statusLabel(safe)) + '</span>';
  }

  function kindPill(kind) {
    var safe = kind === 'plugin' ? 'plugin' : 'theme';
    return '<span class="pill pill-' + safe + '">' + esc(kindLabel(safe)) + '</span>';
  }

  function platformPill(platform) {
    var safe = platform === 'mobile' ? 'mobile' : 'desktop';
    return '<span class="pill pill-platform-' + safe + '">' + esc(PLATFORM_LABELS[safe]) + '</span>';
  }

  function platformsHTML(item) {
    var list = item && item.platforms && item.platforms.length ? item.platforms : ['desktop'];
    return list.map(platformPill).join('');
  }

  function initials(name, email) {
    var text = String(name || email || '?').trim();
    var match = text.match(/[A-Za-z0-9\u4e00-\u9fa5]/);
    return (match ? match[0] : '?').toUpperCase();
  }

  // ---------- 数据归一化 ----------
  function normalizeItem(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var kind = String(raw.kind || '').toLowerCase() === 'plugin' ? 'plugin' : 'theme';
    var rating = Number(raw.rating);
    var downloads = Number(raw.downloads);
    var authorId = raw.author_id === undefined || raw.author_id === null ? null : Number(raw.author_id);
    return {
      id: raw.id === undefined || raw.id === null ? '' : String(raw.id),
      kind: kind,
      name: String(raw.name || raw.title || '未命名').trim() || '未命名',
      summary: String(raw.summary || '').trim(),
      description: String(raw.description || '').trim(),
      author: String(raw.author || raw.author_name || '匿名').trim() || '匿名',
      authorId: isNaN(authorId) ? null : authorId,
      version: String(raw.version || '1.0.0').trim() || '1.0.0',
      downloadUrl: String(raw.download_url || raw.downloadUrl || '').trim(),
      palette: toPalette(raw.palette !== undefined && raw.palette !== null ? raw.palette : raw.palette_json),
      tags: toArray(raw.tags !== undefined && raw.tags !== null ? raw.tags : raw.tags_json),
      screenshots: toArray(raw.screenshots !== undefined && raw.screenshots !== null ? raw.screenshots : raw.screenshots_json),
      platforms: toPlatforms(raw.platforms !== undefined && raw.platforms !== null ? raw.platforms : raw.platforms_json),
      githubUrl: String(raw.github_url || raw.githubUrl || '').trim(),
      repoBranch: String(raw.repo_branch || raw.repoBranch || 'main').trim() || 'main',
      apiVersion: String(raw.api_version || raw.apiVersion || '').trim(),
      readmePath: String(raw.readme_path || raw.readmePath || 'README.md').trim() || 'README.md',
      iconPath: String(raw.icon_path || raw.iconPath || 'icon.png').trim() || 'icon.png',
      lastSyncAt: String(raw.last_sync_at || raw.lastSyncAt || ''),
      lastSyncError: String(raw.last_sync_error || raw.lastSyncError || '').trim(),
      status: String(raw.status || 'approved').toLowerCase(),
      rejectReason: String(raw.reject_reason || '').trim(),
      downloads: isNaN(downloads) ? 0 : downloads,
      rating: isNaN(rating) ? 0 : clamp(rating, 0, 5),
      createdAt: String(raw.created_at || raw.createdAt || ''),
      updatedAt: String(raw.updated_at || raw.updatedAt || ''),
      publishedAt: String(raw.published_at || '')
    };
  }

  function normalizeList(data) {
    var list = Array.isArray(data) ? data : (data && Array.isArray(data.items) ? data.items : []);
    return list.map(normalizeItem).filter(Boolean);
  }

  function normalizeComment(raw) {
    if (!raw || typeof raw !== 'object') return null;
    return {
      id: raw.id === undefined || raw.id === null ? '' : String(raw.id),
      itemId: raw.item_id === undefined || raw.item_id === null ? '' : String(raw.item_id),
      itemName: String(raw.item_name || ''),
      userId: raw.user_id === undefined || raw.user_id === null ? null : Number(raw.user_id),
      userName: String(raw.user_name || raw.author || '匿名用户').trim() || '匿名用户',
      rating: clamp(Number(raw.rating) || 0, 0, 5),
      text: String(raw.text || ''),
      status: String(raw.status || 'pending').toLowerCase(),
      createdAt: String(raw.created_at || '')
    };
  }

  function normalizeToken(raw) {
    if (!raw || typeof raw !== 'object') return null;
    return {
      id: raw.id === undefined || raw.id === null ? '' : String(raw.id),
      name: String(raw.name || '').trim() || '未命名 Token',
      scope: String(raw.scope || 'all'),
      prefix: String(raw.prefix || ''),
      status: String(raw.status || 'active').toLowerCase(),
      createdAt: String(raw.created_at || ''),
      lastUsedAt: String(raw.last_used_at || ''),
      expiresAt: String(raw.expires_at || ''),
      revokedAt: String(raw.revoked_at || ''),
      token: String(raw.token || '')
    };
  }

  function isGithubUrl(value) {
    return GITHUB_URL_RE.test(String(value || '').trim());
  }

  function githubLinkHTML(item, extraClass) {
    if (!item || !item.githubUrl) return '';
    return '<a class="gh-link' + (extraClass ? ' ' + extraClass : '') + '" href="' + esc(item.githubUrl) + '"' +
      ' target="_blank" rel="noopener" title="' + esc(item.githubUrl) + '">' +
      '<span class="gh-mark" aria-hidden="true">⌥</span>GitHub ↗</a>';
  }

  function findItem(itemId) {
    var id = String(itemId);
    var pools = [state.items, state.devItems, state.pendingItems];
    for (var i = 0; i < pools.length; i += 1) {
      var found = (pools[i] || []).filter(function (item) { return item.id === id; })[0];
      if (found) return found;
    }
    return null;
  }

  // ---------- API ----------
  function ApiError(message, status, data) {
    this.name = 'ApiError';
    this.message = message;
    this.status = status;
    this.data = data;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function errorMessage(err) {
    if (err instanceof ApiError) return err.message;
    if (err && err.message) return '请求失败：' + err.message;
    return '请求失败，请稍后再试';
  }

  function api(path, options) {
    var opts = options || {};
    var headers = { Accept: 'application/json' };
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    var body;
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers,
      body: body,
      credentials: 'same-origin'
    }).catch(function () {
      throw new ApiError('无法连接到服务器，请确认后端已启动', 0, null);
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (err) { data = null; }
        }
        if (response.ok) return data;
        var message = '';
        if (data && typeof data.detail === 'string') message = data.detail;
        else if (data && typeof data.error === 'string') message = data.error;
        else if (data && Array.isArray(data.detail)) {
          message = data.detail.map(function (item) { return (item && item.msg) || ''; }).filter(Boolean).join('；');
        }
        if (!message && response.status !== 401) {
          if (response.status === 403) message = '没有权限执行此操作';
          else if (response.status === 404) message = '内容不存在或尚未公开';
          else message = '请求失败（' + response.status + '）';
        }
        if (response.status === 401 && state.token) {
          clearSession();
          message = message || '登录已过期，请重新登录';
        }
        var apiErr = new ApiError(message || '请求失败（' + response.status + '）', response.status, data);
        var retryAfter = response.headers ? Number(response.headers.get('Retry-After')) : NaN;
        if (retryAfter > 0) apiErr.retryAfter = retryAfter;
        throw apiErr;
      });
    });
  }

  // ---------- 会话 ----------
  function persistSession() {
    try {
      if (state.token) localStorage.setItem(TOKEN_KEY, state.token);
      else localStorage.removeItem(TOKEN_KEY);
      if (state.user) localStorage.setItem(USER_KEY, JSON.stringify(state.user));
      else localStorage.removeItem(USER_KEY);
    } catch (err) { /* 隐私模式忽略 */ }
  }

  function setSession(token, user) {
    state.token = String(token || '');
    state.user = user && typeof user === 'object' ? user : null;
    persistSession();
    renderAuthBox();
    renderNavVisibility();
  }

  function clearSession() {
    state.token = '';
    state.user = null;
    persistSession();
    renderAuthBox();
    renderNavVisibility();
  }

  function hasRole(role) {
    if (!state.user) return false;
    if (role === 'admin') return state.user.role === 'admin';
    if (role === 'developer') return state.user.role === 'admin' || state.user.role === 'developer';
    return true;
  }

  function refreshMe() {
    if (!state.token) return Promise.resolve(null);
    return api('/api/auth/me').then(function (me) {
      if (me && typeof me === 'object') {
        state.user = me;
        persistSession();
        renderAuthBox();
        renderNavVisibility();
      }
      return state.user;
    }).catch(function () { return null; });
  }

  // ---------- Toast ----------
  function toast(message, type) {
    var root = $('#toastRoot');
    if (!root) return;
    var el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    var icons = { success: '✓', error: '!', info: 'ℹ' };
    el.innerHTML = '<span class="toast-icon" aria-hidden="true">' + (icons[type] || icons.info) + '</span>' +
      '<span>' + esc(message) + '</span>';
    root.appendChild(el);
    setTimeout(function () {
      el.classList.add('is-out');
      setTimeout(function () { el.remove(); }, 280);
    }, type === 'error' ? 5200 : 3600);
  }

  // ---------- 弹层 ----------
  function lockScroll(locked) { document.body.style.overflow = locked ? 'hidden' : ''; }

  function closeModal() {
    var root = $('#modalRoot');
    if (root) root.innerHTML = '';
    lockScroll(false);
    state.detail = { item: null, comments: [], mode: 'store', loading: false, rating: 5, commentSubmitted: false };
  }

  function openModalShell(html, options) {
    var opts = options || {};
    var root = $('#modalRoot');
    root.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-label="' + esc(opts.label || '详情') + '">' +
      '<div class="modal-backdrop" data-action="close-modal"></div>' +
      '<div class="modal-panel" tabindex="-1">' + html + '</div>' +
      '</div>';
    lockScroll(true);
    var panel = root.querySelector('.modal-panel');
    if (panel) panel.focus();
  }

  function openDialog(html) {
    var root = $('#modalRoot');
    if (!root) return;
    var wrap = document.createElement('div');
    wrap.className = 'modal sub';
    wrap.setAttribute('role', 'alertdialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.innerHTML = '<div class="modal-backdrop" data-action="close-dialog"></div>' +
      '<div class="modal-panel sm" tabindex="-1">' + html + '</div>';
    root.appendChild(wrap);
    var panel = wrap.querySelector('.modal-panel');
    if (panel) panel.focus();
  }

  function closeDialog() {
    var root = $('#modalRoot');
    if (!root) return;
    var dialogs = $$('.modal.sub', root);
    if (dialogs.length) dialogs[dialogs.length - 1].remove();
    if (!root.querySelector('.modal')) lockScroll(false);
  }

  function closeTopDialog() {
    var root = $('#modalRoot');
    if (!root) return false;
    var dialogs = $$('.modal.sub', root);
    if (!dialogs.length) return false;
    dialogs[dialogs.length - 1].remove();
    if (!root.querySelector('.modal')) lockScroll(false);
    return true;
  }

  function confirmDialog(options) {
    var opts = options || {};
    return new Promise(function (resolve) {
      openDialog('<div class="dialog-body">' +
        '<h3>' + esc(opts.title || '确认操作') + '</h3>' +
        '<p>' + esc(opts.message || '') + '</p>' +
        '<div class="dialog-actions">' +
          '<button type="button" class="btn ghost" data-dialog-cancel="1">取消</button>' +
          '<button type="button" class="btn ' + (opts.danger ? 'danger' : 'primary') + '" data-dialog-ok="1">' + esc(opts.okText || '确定') + '</button>' +
        '</div></div>');
      var root = $('#modalRoot');
      var dialog = root ? root.querySelector('.modal.sub:last-child') : null;
      if (!dialog) { resolve(false); return; }
      dialog.querySelector('[data-dialog-ok]').addEventListener('click', function () { closeDialog(); resolve(true); });
      dialog.querySelector('[data-dialog-cancel]').addEventListener('click', function () { closeDialog(); resolve(false); });
      dialog.querySelector('.modal-backdrop').addEventListener('click', function () { closeDialog(); resolve(false); });
    });
  }

  function reasonDialog(options) {
    var opts = options || {};
    return new Promise(function (resolve) {
      openDialog('<div class="dialog-body">' +
        '<h3>' + esc(opts.title || '拒绝原因') + '</h3>' +
        '<p>' + esc(opts.message || '') + '</p>' +
        '<div class="field"><label for="dialogReason">拒绝理由（会展示给开发者）</label>' +
        '<textarea id="dialogReason" rows="3" maxlength="500" placeholder="例如：截图与描述不符 / 下载地址不可用"></textarea>' +
        '<p class="form-error" id="dialogReasonError" hidden></p></div>' +
        '<div class="dialog-actions">' +
          '<button type="button" class="btn ghost" data-dialog-cancel="1">取消</button>' +
          '<button type="button" class="btn danger" data-dialog-ok="1">确认拒绝</button>' +
        '</div></div>');
      var root = $('#modalRoot');
      var dialog = root ? root.querySelector('.modal.sub:last-child') : null;
      if (!dialog) { resolve(null); return; }
      var input = dialog.querySelector('#dialogReason');
      var errorEl = dialog.querySelector('#dialogReasonError');
      function finish(value) { closeDialog(); resolve(value); }
      dialog.querySelector('[data-dialog-cancel]').addEventListener('click', function () { finish(null); });
      dialog.querySelector('.modal-backdrop').addEventListener('click', function () { finish(null); });
      dialog.querySelector('[data-dialog-ok]').addEventListener('click', function () {
        var text = (input.value || '').trim();
        if (text.length < 2) {
          errorEl.hidden = false;
          errorEl.textContent = '请填写至少 2 个字的拒绝理由。';
          input.focus();
          return;
        }
        finish(text);
      });
      setTimeout(function () { if (input) input.focus(); }, 40);
    });
  }

  // ---------- 路由 ----------
  function parseHash() {
    var raw = (location.hash || '#/store').replace(/^#\/?/, '');
    var parts = raw.split('/').filter(Boolean);
    return { page: parts[0] || 'store', param: parts.slice(1).join('/') };
  }

  function go(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  function setActiveNav(page) {
    $$('#mainNav .nav-link').forEach(function (link) {
      var active = link.getAttribute('data-nav') === page;
      link.classList.toggle('is-active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function showView(name) {
    $$('#app > .view').forEach(function (view) {
      view.hidden = view.id !== 'view-' + name;
    });
    var titles = {
      store: '深清商店 · 主题与插件',
      auth: '登录 · 深清商店',
      dev: '开发者中心 · 深清商店',
      tokens: '发布 Token · 深清商店',
      admin: '管理后台 · 深清商店'
    };
    document.title = titles[name] || '深清商店';
    setActiveNav(name === 'auth' ? '' : name);
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  function route() {
    closeModal();
    var parsed = parseHash();
    var page = parsed.page;
    // 明文 Token 只属于本次会话的前台页面：离开页面就清掉
    if (page !== 'tokens') state.newToken = '';

    if (page === 'item') {
      showView('store');
      loadItems();
      if (parsed.param) openDetail(parsed.param, 'store', { push: false });
      return;
    }
    if (page === 'auth' || page === 'login' || page === 'register') {
      state.authMode = page === 'register' ? 'register' : 'login';
      showView('auth');
      renderAuthView();
      return;
    }
    if (page === 'dev') {
      if (!hasRole('developer')) {
        showView('store');
        toast('请先用开发者账号登录', 'info');
        go('#/auth');
        return;
      }
      showView('dev');
      loadDevItems();
      return;
    }
    if (page === 'tokens') {
      if (!hasRole('developer')) {
        showView('store');
        toast('请先用开发者账号登录', 'info');
        go('#/auth');
        return;
      }
      showView('tokens');
      loadTokens();
      return;
    }
    if (page === 'admin') {
      if (!hasRole('admin')) {
        showView('store');
        toast('请先用管理员账号登录', 'info');
        go('#/auth');
        return;
      }
      showView('admin');
      loadAdmin();
      return;
    }
    showView('store');
    loadItems();
  }

  function renderNavVisibility() {
    var devLink = $('#mainNav [data-nav="dev"]');
    var tokenLink = $('#mainNav [data-nav="tokens"]');
    var adminLink = $('#mainNav [data-nav="admin"]');
    if (devLink) devLink.hidden = !hasRole('developer');
    if (tokenLink) tokenLink.hidden = !hasRole('developer');
    if (adminLink) adminLink.hidden = !hasRole('admin');
    var page = parseHash().page;
    setActiveNav(page === 'item' || page === 'auth' ? '' : page);
  }

  function renderAuthBox() {
    var box = $('#authBox');
    if (!box) return;
    if (state.user) {
      var displayName = state.user.name || state.user.email || '用户';
      box.innerHTML = '<span class="user-chip">' +
        '<span class="avatar" aria-hidden="true">' + esc(initials(state.user.name, state.user.email)) + '</span>' +
        '<span class="user-name" title="' + esc(state.user.email || '') + '">' + esc(displayName) + '</span>' +
        rolePill(state.user.role) +
        '</span>' +
        '<button type="button" class="icon-btn" data-action="logout" title="退出登录" aria-label="退出登录">⏻</button>';
    } else {
      box.innerHTML = '<a class="btn ghost sm" href="#/store">逛逛商店</a>' +
        '<a class="btn primary sm" href="#/auth">登录 / 注册</a>';
    }
  }

  // ---------- 登录 / 注册 ----------
  var CODE_LENGTH = 6;
  var CODE_TTL_FALLBACK = 600;
  var CODE_RESEND_SECONDS = 60;
  var codeCooldown = {};
  var codeTimer = null;

  function authStage() {
    return state.authMode === 'register' || state.authMode === 'reset' ? state.authMode : 'login';
  }

  function codePurpose() {
    var stage = authStage();
    return stage === 'login' ? 'login' : stage;
  }

  function cooldownKey(email) {
    return String(email || '').trim().toLowerCase();
  }

  function cooldownLeft(email) {
    var until = codeCooldown[cooldownKey(email)] || 0;
    return Math.max(0, Math.ceil((until - Date.now()) / 1000));
  }

  function authEmailValue() {
    var input = $('#authEmail');
    return input ? String(input.value || '').trim() : '';
  }

  function isEmailText(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || ''));
  }

  function hideAuthError() {
    var errorEl = $('#authError');
    if (errorEl) { errorEl.hidden = true; errorEl.textContent = ''; }
  }

  function showAuthError(message) {
    var errorEl = $('#authError');
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = message;
    } else {
      toast(message, 'error');
    }
  }

  function renderCodeButton() {
    var btn = $('#sendCodeBtn');
    if (!btn) return;
    var left = cooldownLeft(authEmailValue());
    if (left > 0) {
      btn.disabled = true;
      btn.textContent = left + ' 秒后重发';
    } else {
      btn.disabled = false;
      btn.textContent = '获取验证码';
    }
  }

  function startCodeCooldown(email, seconds) {
    codeCooldown[cooldownKey(email)] = Date.now() + Math.max(1, Number(seconds) || CODE_RESEND_SECONDS) * 1000;
    renderCodeButton();
    if (codeTimer) return;
    codeTimer = window.setInterval(function () {
      renderCodeButton();
      var now = Date.now();
      var active = Object.keys(codeCooldown).some(function (key) { return (codeCooldown[key] || 0) > now; });
      if (!active) {
        window.clearInterval(codeTimer);
        codeTimer = null;
      }
    }, 1000);
  }

  function renderDevCode() {
    var box = $('#devCodeBox');
    var valueEl = $('#devCodeValue');
    if (!box || !valueEl) return;
    var dev = state.devCode || {};
    if (dev.code && dev.purpose === codePurpose()) {
      box.hidden = false;
      valueEl.textContent = dev.code;
    } else {
      box.hidden = true;
      valueEl.textContent = '';
    }
  }

  function sendCode() {
    var email = authEmailValue();
    var purpose = codePurpose();
    hideAuthError();
    if (!isEmailText(email)) { showAuthError('请先填写有效的邮箱地址'); return; }
    if (cooldownLeft(email) > 0) return;
    var btn = $('#sendCodeBtn');
    if (btn) { btn.disabled = true; btn.textContent = '发送中…'; }
    api('/api/auth/send-code', { method: 'POST', body: { email: email, purpose: purpose } }).then(function (data) {
      var ttl = Number(data && data.ttl_seconds);
      if (!ttl || ttl <= 0) ttl = CODE_TTL_FALLBACK;
      startCodeCooldown(email, CODE_RESEND_SECONDS);
      if (data && data.dev_code) {
        state.devCode = { purpose: purpose, code: String(data.dev_code) };
      } else {
        state.devCode = { purpose: '', code: '' };
      }
      renderDevCode();
      toast('验证码已发送，' + Math.max(1, Math.round(ttl / 60)) + ' 分钟内有效', 'success');
      var codeInput = $('#authCode');
      if (codeInput) codeInput.focus();
    }).catch(function (err) {
      if (btn) { btn.disabled = false; btn.textContent = '获取验证码'; }
      if (err && err.retryAfter > 0) startCodeCooldown(email, err.retryAfter);
      else renderCodeButton();
      showAuthError(errorMessage(err));
    });
  }

  function renderAuthView() {
    var tabs = $('.auth-tabs');
    var modeTabs = $('#loginModeTabs');
    var form = $('#authForm');
    var foot = $('#authFoot');
    var loggedBox = $('#authLoggedIn');
    var sub = $('#authSub');
    if (!form) return;

    if (state.user) {
      if (tabs) tabs.hidden = true;
      if (modeTabs) modeTabs.hidden = true;
      form.hidden = true;
      if (foot) foot.hidden = true;
      if (loggedBox) {
        loggedBox.hidden = false;
        loggedBox.innerHTML = '<div class="notice ok">当前已登录：<b>' + esc(state.user.name || state.user.email) + '</b>（' + esc(roleLabel(state.user.role)) + '）</div>' +
          '<div class="form-actions" style="margin-top:14px">' +
            '<a class="btn ghost" href="#/store">回到商店</a>' +
            '<button type="button" class="btn danger-ghost" data-action="logout">退出登录</button>' +
          '</div>';
      }
      return;
    }

    var stage = authStage();
    var isRegister = stage === 'register';
    var isReset = stage === 'reset';
    var isCodeLogin = stage === 'login' && state.loginMode === 'code';

    if (tabs) tabs.hidden = isReset;
    if (modeTabs) modeTabs.hidden = stage !== 'login';
    form.hidden = false;
    if (foot) foot.hidden = false;
    if (loggedBox) { loggedBox.hidden = true; loggedBox.innerHTML = ''; }

    var nameField = $('#nameField');
    if (nameField) nameField.hidden = !isRegister;
    var passwordField = $('#passwordField');
    if (passwordField) passwordField.hidden = isReset || isCodeLogin;
    var newPasswordField = $('#newPasswordField');
    if (newPasswordField) newPasswordField.hidden = !isReset;
    var codeField = $('#codeField');
    if (codeField) codeField.hidden = !(isRegister || isReset || isCodeLogin);

    var passwordInput = $('#authPassword');
    if (passwordInput) passwordInput.setAttribute('autocomplete', isRegister ? 'new-password' : 'current-password');

    var subText = {
      login: '登录后即可发表评论、提交主题与插件',
      register: '注册一个账号，评论、提交与审核都会用得上',
      reset: '填写注册邮箱，验证码通过后即可重设密码'
    };
    if (sub) sub.textContent = subText[stage];
    var submit = $('#authSubmit');
    if (submit) submit.textContent = isRegister ? '注册并登录' : (isReset ? '重置密码' : '登录');

    $$('.auth-tab').forEach(function (tab) {
      var active = tab.getAttribute('data-auth-mode') === stage;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $$('.mode-tab').forEach(function (tab) {
      var active = (tab.getAttribute('data-login-mode') || 'password') === (state.loginMode === 'code' ? 'code' : 'password');
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    var aux = $('#authAux');
    if (aux) aux.hidden = !(stage === 'login' || isReset);
    var forgotBtn = $('#forgotBtn');
    if (forgotBtn) forgotBtn.hidden = stage !== 'login';
    var backBtn = $('#backToLoginBtn');
    if (backBtn) backBtn.hidden = !isReset;

    hideAuthError();
    renderCodeButton();
    renderDevCode();
  }

  function setAuthMode(mode) {
    state.authMode = mode === 'register' ? 'register' : 'login';
    if (state.authMode === 'login') state.loginMode = state.loginMode === 'code' ? 'code' : 'password';
    renderAuthView();
    var focusEl = state.authMode === 'register' ? $('#authName') : $('#authEmail');
    if (focusEl) focusEl.focus();
  }

  function setLoginMode(mode) {
    state.loginMode = mode === 'code' ? 'code' : 'password';
    state.authMode = 'login';
    renderAuthView();
    var focusEl = state.loginMode === 'code' ? $('#authCode') : $('#authPassword');
    if (focusEl) focusEl.focus();
  }

  function setAuthStage(stage) {
    state.authMode = stage === 'register' || stage === 'reset' ? stage : 'login';
    renderAuthView();
    var focusEl = state.authMode === 'register' ? $('#authName') : $('#authEmail');
    if (focusEl) focusEl.focus();
  }

  function validAuthCode(code) {
    return new RegExp('^\\d{' + CODE_LENGTH + '}$').test(code);
  }

  function clearAuthSecrets() {
    state.devCode = { purpose: '', code: '' };
    var codeInput = $('#authCode');
    if (codeInput) codeInput.value = '';
    var newPwd = $('#authNewPassword');
    if (newPwd) newPwd.value = '';
  }

  function postAuth(path, payload, pendingText, onSuccess) {
    var btn = $('#authSubmit');
    var oldText = btn ? btn.textContent : '';
    var switched = false;
    if (btn) { btn.disabled = true; btn.textContent = pendingText; }
    api(path, { method: 'POST', body: payload }).then(function (data) {
      onSuccess(data);
      switched = true;
    }).catch(function (err) {
      showAuthError(errorMessage(err));
    }).then(function () {
      if (btn) {
        btn.disabled = false;
        if (!switched) btn.textContent = oldText;
      }
    });
  }

  function finishAuthLogin(data, welcome) {
    if (!data || !data.token || !data.user) throw new ApiError('登录响应格式不正确', 0, null);
    setSession(data.token, data.user);
    var form = $('#authForm');
    if (form) form.reset();
    clearAuthSecrets();
    renderDevCode();
    toast(welcome, 'success');
    go('#/store');
  }

  function submitAuth(form) {
    var stage = authStage();
    var email = authEmailValue();
    var codeInput = $('#authCode');
    var code = codeInput ? String(codeInput.value || '').trim() : '';
    var passwordInput = $('#authPassword');
    var password = passwordInput ? passwordInput.value || '' : '';
    var newPwdInput = $('#authNewPassword');
    var newPassword = newPwdInput ? newPwdInput.value || '' : '';
    var nameInput = $('#authName');
    var name = nameInput ? String(nameInput.value || '').trim() : '';

    hideAuthError();

    if (stage === 'reset') {
      if (!isEmailText(email)) { showAuthError('请输入有效的邮箱地址'); return; }
      if (!validAuthCode(code)) { showAuthError('请输入 6 位邮箱验证码'); return; }
      if (newPassword.length < 6) { showAuthError('新密码至少 6 位'); return; }
      postAuth('/api/auth/reset-password', { email: email, code: code, new_password: newPassword }, '提交中…', function () {
        if (form) form.reset();
        clearAuthSecrets();
        state.authMode = 'login';
        state.loginMode = 'password';
        renderAuthView();
        var emailInput = $('#authEmail');
        if (emailInput) emailInput.value = email;
        var pwd = $('#authPassword');
        if (pwd) pwd.focus();
        toast('密码已重置，请使用新密码登录', 'success');
      });
      return;
    }

    if (!isEmailText(email)) { showAuthError('请输入有效的邮箱地址'); return; }

    if (stage === 'register') {
      if (!name) { showAuthError('请填写昵称'); return; }
      if (!validAuthCode(code)) { showAuthError('请输入 6 位邮箱验证码'); return; }
      if (password.length < 6) { showAuthError('密码至少 6 位'); return; }
      postAuth('/api/auth/register', { email: email, password: password, name: name, code: code }, '注册中…', function (data) {
        finishAuthLogin(data, '注册成功，欢迎加入深清商店');
      });
      return;
    }

    if (state.loginMode === 'code') {
      if (!validAuthCode(code)) { showAuthError('请输入 6 位邮箱验证码'); return; }
      postAuth('/api/auth/login-code', { email: email, code: code }, '登录中…', function (data) {
        finishAuthLogin(data, '欢迎回来，' + ((data && data.user && data.user.name) || '朋友'));
      });
      return;
    }

    if (password.length < 6) { showAuthError('密码至少 6 位'); return; }
    postAuth('/api/auth/login', { email: email, password: password }, '登录中…', function (data) {
      finishAuthLogin(data, '欢迎回来，' + ((data && data.user && data.user.name) || '朋友'));
    });
  }

  function logout() {
    clearSession();
    state.itemsLoaded = false;
    state.tokens = [];
    state.tokensLoaded = false;
    state.newToken = '';
    toast('已退出登录', 'info');
    go('#/store');
  }

  // ---------- 商店列表 ----------
  function loadItems() {
    var seq = ++state.itemsSeq;
    state.loadingItems = true;
    renderStoreSkeleton();
    var params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.kind) params.set('kind', state.kind);
    if (state.platform) params.set('platform', state.platform);
    params.set('sort', state.sort || 'rating');
    api('/api/store/items?' + params.toString()).then(function (data) {
      if (seq !== state.itemsSeq) return;
      state.items = normalizeList(data);
      state.itemsLoaded = true;
      state.itemsError = null;
      renderStore();
    }).catch(function (err) {
      if (seq !== state.itemsSeq) return;
      state.itemsError = err;
      renderStoreError(err);
    }).then(function () {
      if (seq === state.itemsSeq) state.loadingItems = false;
    });
  }

  function skeletonCardHTML() {
    return '<div class="skeleton"><div class="skel-block skel-cover"></div>' +
      '<div class="skel-body">' +
        '<div class="skel-block skel-line w60"></div>' +
        '<div class="skel-block skel-line w40"></div>' +
        '<div class="skel-block skel-line tall"></div>' +
        '<div class="skel-block skel-line w85"></div>' +
      '</div></div>';
  }

  function renderStoreSkeleton() {
    var grid = $('#storeGrid');
    var stateBox = $('#storeState');
    if (stateBox) stateBox.hidden = true;
    if (!grid) return;
    var html = '';
    for (var i = 0; i < 6; i += 1) html += skeletonCardHTML();
    grid.innerHTML = html;
    renderStoreStats();
  }

  function renderStoreStats() {
    var box = $('#storeStats');
    if (!box) return;
    var items = state.items || [];
    var themes = items.filter(function (item) { return item.kind === 'theme'; }).length;
    var plugins = items.filter(function (item) { return item.kind === 'plugin'; }).length;
    box.innerHTML = '<div class="stat"><b>' + fmtNum(items.length) + '</b><span>收录条目</span></div>' +
      '<div class="stat"><b>' + fmtNum(themes) + '</b><span>主题</span></div>' +
      '<div class="stat"><b>' + fmtNum(plugins) + '</b><span>插件</span></div>';
  }

  function renderStoreError(err) {
    var grid = $('#storeGrid');
    var stateBox = $('#storeState');
    if (grid) grid.innerHTML = '';
    renderStoreStats();
    if (!stateBox) return;
    stateBox.hidden = false;
    stateBox.className = 'state-box state-danger';
    stateBox.innerHTML = '<span class="state-icon" aria-hidden="true">⚠</span>' +
      '<h3>商店加载失败</h3>' +
      '<p>' + esc(errorMessage(err)) + '</p>' +
      '<button type="button" class="btn ghost" data-action="reload-store">重新加载</button>';
  }

  function coverHTML(item, variant) {
    var isDetail = variant === 'detail';
    var base = isDetail ? 'detail-cover' : 'card-cover';
    var kindClass = item.kind === 'plugin' ? 'cover-plugin' : 'cover-theme';
    var settings = item.kind === 'plugin' ? '' : ' style="background:' + paletteBackground(item.palette) + '"';
    var inner = '';
    if (item.kind === 'plugin') {
      inner = '<span class="cover-glyph" aria-hidden="true">❖</span>';
    } else {
      inner = '<div class="swatch-dots" aria-hidden="true">' + paletteDots(item.palette) + '</div>';
    }
    var badges = '';
    if (!isDetail) {
      badges += '<span class="cover-badge">' + kindPill(item.kind) + '</span>';
      if (item.status !== 'approved') badges += '<span class="cover-status">' + statusPill(item.status) + '</span>';
    }
    return '<div class="' + base + ' ' + kindClass + '"' + settings + '>' + inner + badges + '</div>';
  }

  function itemCardHTML(item, index) {
    var rating = item.rating > 0
      ? '<span class="rating-num">' + item.rating.toFixed(1) + '</span>'
      : '<span class="rating-empty">暂无评分</span>';
    var tags = item.tags.slice(0, 3).map(function (tag) { return '<span class="tag">' + esc(tag) + '</span>'; }).join('');
    var more = item.tags.length > 3 ? '<span class="tag-more">+' + (item.tags.length - 3) + '</span>' : '';
    var action;
    if (item.kind === 'plugin') {
      action = item.downloadUrl
        ? '<a class="btn primary sm" href="' + esc(item.downloadUrl) + '" target="_blank" rel="noopener" data-action="download" data-id="' + esc(item.id) + '">下载插件</a>'
        : '<button type="button" class="btn primary sm" disabled title="作者暂未提供下载地址">下载插件</button>';
    } else {
      action = '<button type="button" class="btn primary sm" data-action="copy-palette" data-id="' + esc(item.id) + '">复制配色</button>';
    }
    return '<article class="card" style="--i:' + index + '">' +
      coverHTML(item, 'card') +
      '<div class="card-body">' +
        '<div class="card-title-row">' +
          '<h3 class="card-title" title="' + esc(item.name) + '">' + esc(item.name) + '</h3>' +
          '<span class="card-ver">v' + esc(item.version) + '</span>' +
        '</div>' +
        '<p class="card-author">' + esc(item.author) + '</p>' +
        '<p class="card-summary">' + (item.summary ? esc(item.summary) : '<span class="dim">作者还没有写简介</span>') + '</p>' +
        (item.githubUrl
          ? '<p class="card-github">' + githubLinkHTML(item) +
            (item.lastSyncAt ? '<span class="dim">· 同步于 ' + fmtDate(item.lastSyncAt) + '</span>' : '') + '</p>'
          : '') +
        '<div class="card-meta">' + starsHTML(item.rating) + rating +
          '<span class="platform-badges">' + platformsHTML(item) + '</span>' +
          '<span class="dl">↓ ' + fmtNum(item.downloads) + '</span></div>' +
        '<div class="tags">' + tags + more + '</div>' +
        '<div class="card-actions">' +
          '<button type="button" class="btn ghost sm" data-action="open-detail" data-id="' + esc(item.id) + '">查看</button>' +
          action +
        '</div>' +
      '</div>' +
    '</article>';
  }

  function renderStore() {
    var grid = $('#storeGrid');
    var stateBox = $('#storeState');
    renderStoreStats();
    if (!grid) return;
    var items = state.items || [];
    if (!items.length) {
      grid.innerHTML = '';
      if (!stateBox) return;
      var searching = !!(state.q || state.kind || state.platform);
      stateBox.hidden = false;
      stateBox.className = 'state-box';
      stateBox.innerHTML = '<span class="state-icon" aria-hidden="true">' + (searching ? '⌕' : '◌') + '</span>' +
        '<h3>' + (searching ? '没有找到匹配的条目' : '商店还空着') + '</h3>' +
        '<p>' + (searching ? '换个关键词，或切换类型再试试。' : '等第一位开发者提交主题或插件，通过审核后就会出现在这里。') + '</p>' +
        (searching ? '<button type="button" class="btn ghost" data-action="reset-filters">清除筛选</button>' : '');
      return;
    }
    if (stateBox) stateBox.hidden = true;
    grid.innerHTML = items.map(function (item, index) { return itemCardHTML(item, index); }).join('');
  }

  // ---------- 条目详情 ----------
  function commentHTML(comment) {
    return '<div class="comment">' +
      '<span class="avatar" aria-hidden="true">' + esc(initials(comment.userName)) + '</span>' +
      '<div class="comment-body">' +
        '<div class="comment-head">' +
          '<span class="comment-name">' + esc(comment.userName) + '</span>' +
          starsHTML(comment.rating) +
          '<span class="comment-time">' + fmtDate(comment.createdAt) + '</span>' +
        '</div>' +
        '<p class="comment-text">' + esc(comment.text) + '</p>' +
      '</div>' +
    '</div>';
  }

  function commentFormHTML(rating) {
    var stars = '';
    for (var i = 1; i <= 5; i += 1) {
      var on = i <= rating;
      stars += '<button type="button" class="' + (on ? 'is-on' : '') + '" data-rate="' + i + '" aria-label="' + i + ' 星" aria-pressed="' + (on ? 'true' : 'false') + '">★</button>';
    }
    return '<form class="comment-form" id="commentForm" novalidate>' +
      '<div class="comment-form-head"><b>写下你的评价</b>' +
        '<div class="rate-picker" role="radiogroup" aria-label="评分">' + stars + '</div>' +
      '</div>' +
      '<textarea id="commentText" maxlength="500" placeholder="用过之后感觉如何？说说它适合什么样的场景。" required></textarea>' +
      '<div class="comment-form-foot">' +
        '<span class="counter"><span id="commentCounter">0</span>/500 · 提交后需管理员审核</span>' +
        '<button type="submit" class="btn primary sm">提交评论</button>' +
      '</div>' +
    '</form>';
  }

  function bindDetailEvents() {
    var root = $('#modalRoot');
    if (!root) return;
    var picker = root.querySelector('.rate-picker');
    if (picker) {
      var buttons = $$('[data-rate]', picker);
      var current = state.detail.rating || 5;
      function paint(value) {
        buttons.forEach(function (btn) {
          var on = Number(btn.getAttribute('data-rate')) <= value;
          btn.classList.toggle('is-on', on);
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      }
      buttons.forEach(function (btn) {
        btn.addEventListener('mouseenter', function () { paint(Number(btn.getAttribute('data-rate'))); });
        btn.addEventListener('focus', function () { paint(Number(btn.getAttribute('data-rate'))); });
        btn.addEventListener('click', function () {
          current = Number(btn.getAttribute('data-rate'));
          state.detail.rating = current;
          paint(current);
        });
      });
      picker.addEventListener('mouseleave', function () { paint(current); });
    }
    var textarea = root.querySelector('#commentText');
    var counter = root.querySelector('#commentCounter');
    if (textarea && counter) {
      var sync = function () { counter.textContent = String(textarea.value.length); };
      textarea.addEventListener('input', sync);
      sync();
    }
  }

  function renderDetailModal() {
    var detail = state.detail;
    if (!detail.item) {
      openModalShell('<button type="button" class="modal-close" data-action="close-modal" aria-label="关闭">✕</button>' +
        '<div class="state-box" style="border:0;margin:0;padding:90px 20px;background:transparent">' +
          '<span class="spinner big"></span><p>正在加载详情…</p></div>', { label: '条目详情' });
      return;
    }

    var item = detail.item;
    var isAdmin = hasRole('admin');
    var canReview = isAdmin && item.status === 'pending';
    var palette = paletteWithDefaults(item.palette);
    var meta = [];
    meta.push('作者 ' + esc(item.author));
    meta.push('v' + esc(item.version));
    if (item.publishedAt) meta.push(fmtDate(item.publishedAt) + ' 上架');
    else if (item.createdAt) meta.push(fmtDate(item.createdAt) + ' 提交');
    var metaHTML = meta.map(function (part) { return '<span>' + part + '</span>'; }).join('<span class="dot">·</span>');

    var html = coverHTML(item, 'detail');
    html += '<div class="detail-body">';
    html += '<div class="detail-top">' +
      '<div class="detail-heading">' +
        '<div class="detail-sub" style="margin:0 0 10px">' + kindPill(item.kind) + statusPill(item.status) +
          '<span class="platform-badges">' + platformsHTML(item) + '</span></div>' +
        '<h2>' + esc(item.name) + '</h2>' +
        '<div class="detail-sub">' + metaHTML + '</div>' +
        '<div class="detail-sub" style="margin-top:8px">' + starsHTML(item.rating, true) +
          '<span class="rating-num">' + (item.rating > 0 ? item.rating.toFixed(1) : '暂无评分') + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="detail-stats">' +
        '<div class="stat-cell"><b>' + (item.rating > 0 ? item.rating.toFixed(1) : '—') + '</b><span>评分</span></div>' +
        '<span class="divider"></span>' +
        '<div class="stat-cell"><b>' + fmtNum(item.downloads) + '</b><span>下载</span></div>' +
        '<span class="divider"></span>' +
        '<div class="stat-cell"><b>' + detail.comments.length + '</b><span>评论</span></div>' +
      '</div>' +
    '</div>';

    if (item.status === 'pending') {
      html += '<div class="notice warn" style="margin-top:16px">该条目正在审核中，仅作者与管理员可见。通过审核后会自动出现在商店与桌面端目录。</div>';
    } else if (item.status === 'rejected') {
      html += '<div class="notice danger" style="margin-top:16px">该条目未通过审核。' +
        (item.rejectReason ? '原因：' + esc(item.rejectReason) : '') + '</div>';
    }

    html += '<div class="detail-actions">';
    if (item.kind === 'plugin' && item.downloadUrl) {
      html += '<a class="btn primary" href="' + esc(item.downloadUrl) + '" target="_blank" rel="noopener" data-action="download" data-id="' + esc(item.id) + '">下载插件包</a>';
    }
    if (item.kind === 'theme') {
      html += '<button type="button" class="btn primary" data-action="copy-palette" data-id="' + esc(item.id) + '">复制配色 JSON</button>';
    }
    html += '</div>';

    if (item.kind === 'plugin') {
      html += '<div class="download-url">' + (item.downloadUrl ? esc(item.downloadUrl) : '作者暂未提供下载地址') + '</div>';
    }

    if (item.githubUrl) {
      html += '<div class="detail-github">' +
        githubLinkHTML(item, 'lg') +
        '<span class="mono dim detail-github-url">' + esc(item.githubUrl) + '</span>' +
        (item.lastSyncAt ? '<span class="dim">· 版本同步于 ' + fmtDate(item.lastSyncAt, true) + '</span>' : '') +
        (item.lastSyncError ? '<span class="sync-inline-error">· 同步失败：' + esc(item.lastSyncError) + '</span>' : '') +
        '</div>';
    }

    html += '<section class="detail-section"><h3>介绍</h3>' +
      '<div class="detail-desc">' + (item.description ? esc(item.description) : '作者还没有填写详细介绍。') + '</div></section>';

    if (item.kind === 'theme') {
      html += '<section class="detail-section"><h3>配色色板</h3><div class="palette-grid">' +
        PALETTE_KEYS.map(function (key) {
          return '<div class="swatch-item">' +
            '<span class="swatch-color" style="background:' + esc(palette[key]) + '"></span>' +
            '<span><span class="swatch-label">' + esc(PALETTE_LABELS[key]) + '</span><br>' +
            '<span class="swatch-hex">' + esc(palette[key]) + '</span></span>' +
          '</div>';
        }).join('') +
      '</div></section>';
    }

    if (item.screenshots.length) {
      html += '<section class="detail-section"><h3>截图</h3><div class="shots">' +
        item.screenshots.slice(0, 8).map(function (src, index) {
          return '<a href="' + esc(src) + '" target="_blank" rel="noopener" aria-label="截图 ' + (index + 1) + '">' +
            '<img src="' + esc(src) + '" alt="' + esc(item.name) + ' 截图 ' + (index + 1) + '" loading="lazy" onerror="this.style.opacity=0.15">' +
          '</a>';
        }).join('') +
      '</div></section>';
    }

    html += '<section class="detail-section"><h3>评论 <span class="dim" style="font-weight:400;font-size:12px">' + detail.comments.length + ' 条</span></h3>';
    if (detail.comments.length) {
      html += '<div class="comments">' + detail.comments.map(commentHTML).join('') + '</div>';
    } else {
      html += '<p class="comment-empty">还没有评论，来做第一个评价的人。</p>';
    }
    if (item.status !== 'approved') {
      html += '<div class="notice" style="margin-top:14px">条目通过审核后才会开放评论。</div>';
    } else if (!state.user) {
      html += '<div class="notice" style="margin-top:14px">登录后可以发表评论。<a href="#/auth" data-action="go-login">去登录</a></div>';
    } else {
      if (detail.commentSubmitted) {
        html += '<div class="notice ok" style="margin-top:14px">评论已提交，等待管理员审核通过后展示。</div>';
      }
      html += commentFormHTML(detail.rating || 5);
    }
    html += '</section>';

    if (canReview) {
      html += '<div class="review-bar">' +
        '<div class="review-hint">审核该提交：通过后立即上架公开商店与桌面端目录；拒绝会把理由展示给开发者。</div>' +
        '<div class="review-btns">' +
          '<button type="button" class="btn danger-ghost" data-action="reject-item" data-id="' + esc(item.id) + '">拒绝</button>' +
          '<button type="button" class="btn primary" data-action="approve-item" data-id="' + esc(item.id) + '">通过并上架</button>' +
        '</div>' +
      '</div>';
    }
    html += '</div>';

    openModalShell('<button type="button" class="modal-close" data-action="close-modal" aria-label="关闭">✕</button>' + html,
      { label: item.name });
    bindDetailEvents();
  }

  function openDetail(itemId, mode, options) {
    if (!itemId) return;
    var opts = options || {};
    var viewMode = mode || 'store';
    state.detail = { item: null, comments: [], mode: viewMode, loading: true, rating: 5, commentSubmitted: false };
    renderDetailModal();
    api('/api/store/items/' + encodeURIComponent(itemId)).then(function (data) {
      var raw = data && data.item ? data.item : data;
      var item = normalizeItem(raw);
      if (!item) throw new ApiError('条目数据无效', 0, null);
      state.detail.item = item;
      return api('/api/store/items/' + encodeURIComponent(itemId) + '/comments').catch(function () { return []; });
    }).then(function (commentData) {
      var list = Array.isArray(commentData) ? commentData : (commentData && commentData.comments) || [];
      state.detail.comments = list.map(normalizeComment).filter(Boolean);
      renderDetailModal();
      if (opts.push !== false && viewMode === 'store') {
        var hash = '#/item/' + encodeURIComponent(state.detail.item.id);
        if (location.hash !== hash) {
          state.returnHash = location.hash || '#/store';
          history.pushState({ modal: 'detail' }, '', hash);
        }
      }
    }).catch(function (err) {
      closeModal();
      toast(errorMessage(err), 'error');
      if (viewMode === 'store' && location.hash.indexOf('#/item/') === 0) {
        history.replaceState({}, '', state.returnHash || '#/store');
      }
    });
  }

  function submitComment(form) {
    var detail = state.detail;
    if (!detail.item) return;
    var textarea = form.querySelector('#commentText');
    var text = (textarea.value || '').trim();
    var rating = detail.rating || 5;
    if (text.length < 2) {
      toast('评论至少写 2 个字', 'error');
      textarea.focus();
      return;
    }
    var submit = form.querySelector('button[type="submit"]');
    if (submit) { submit.disabled = true; submit.textContent = '提交中…'; }
    api('/api/store/items/' + encodeURIComponent(detail.item.id) + '/comments', {
      method: 'POST',
      body: { rating: rating, text: text }
    }).then(function () {
      detail.commentSubmitted = true;
      toast('评论已提交，等待管理员审核', 'success');
      renderDetailModal();
    }).catch(function (err) {
      toast(errorMessage(err), 'error');
      if (submit) { submit.disabled = false; submit.textContent = '提交评论'; }
    });
  }

  function reviewItem(item, action) {
    var task;
    if (action === 'reject') {
      task = reasonDialog({
        title: '拒绝这条提交',
        message: '拒绝理由会展示给开发者，请写清楚需要修改的地方。'
      }).then(function (reason) {
        if (reason === null) return null;
        return { reason: reason };
      });
    } else {
      task = confirmDialog({
        title: '通过这条提交？',
        message: '通过后「' + (item.name || '该条目') + '」会立即出现在公开商店与桌面端目录中。',
        okText: '通过并上架'
      }).then(function (ok) { return ok ? { reason: '' } : null; });
    }
    task.then(function (result) {
      if (!result) return;
      return api('/api/admin/review', {
        method: 'POST',
        body: { item_id: item.id, action: action, reason: result.reason }
      }).then(function () {
        toast(action === 'approve' ? '已通过，条目已上架' : '已拒绝，理由已发送给开发者', 'success');
        closeModal();
        state.itemsLoaded = false;
        return loadAdmin();
      }).catch(function (err) {
        toast(errorMessage(err), 'error');
      });
    });
  }

  // ---------- 开发者中心 ----------
  function loadDevItems() {
    var list = $('#devList');
    if (list) {
      list.innerHTML = '<div class="panel" style="text-align:center;padding:36px">' +
        '<span class="spinner"></span> <span class="muted">正在加载我的提交…</span></div>';
    }
    api('/api/dev/items').then(function (data) {
      state.devItems = normalizeList(data);
      state.devItems.sort(function (a, b) {
        return String(b.updatedAt || b.createdAt).localeCompare(String(a.updatedAt || a.createdAt));
      });
      renderDevItems();
    }).catch(function (err) {
      var banner = $('#devSyncStatus');
      if (banner) { banner.hidden = true; banner.innerHTML = ''; }
      if (!list) return;
      list.innerHTML = '<div class="state-box state-danger"><span class="state-icon" aria-hidden="true">⚠</span>' +
        '<h3>加载失败</h3><p>' + esc(errorMessage(err)) + '</p>' +
        '<button type="button" class="btn ghost" data-action="reload-dev">重试</button></div>';
    });
  }

  function devRowHTML(item) {
    var actions = [];
    if (item.status === 'pending') {
      actions.push('<button type="button" class="btn ghost sm" data-action="edit-dev-item" data-id="' + esc(item.id) + '">继续编辑</button>');
    }
    if (item.status === 'rejected') {
      actions.push('<button type="button" class="btn ghost sm" data-action="reclone-dev-item" data-id="' + esc(item.id) + '">复制重提</button>');
    }
    actions.push('<button type="button" class="btn ghost sm" data-action="open-detail" data-id="' + esc(item.id) + '">查看详情</button>');
    var reason = item.status === 'rejected' && item.rejectReason
      ? '<div class="reject-note">拒绝原因：' + esc(item.rejectReason) + '</div>' : '';
    var when = item.status === 'approved' && item.publishedAt
      ? '上架于 ' + fmtDate(item.publishedAt)
      : '更新于 ' + fmtDate(item.updatedAt || item.createdAt, true);
    return '<article class="sub-row status-' + esc(item.status) + '">' +
      '<div class="sub-main">' +
        '<div class="sub-title-row">' + kindPill(item.kind) + '<h3>' + esc(item.name) + '</h3>' + statusPill(item.status) +
          '<span class="platform-badges">' + platformsHTML(item) + '</span></div>' +
        '<p class="sub-summary">' + (item.summary ? esc(item.summary) : '<span class="dim">暂无简介</span>') + '</p>' +
        '<div class="sub-meta">' +
          '<span>v' + esc(item.version) + '</span>' +
          '<span>' + when + '</span>' +
          '<span>↓ ' + fmtNum(item.downloads) + ' 次下载</span>' +
          '<span>' + starsHTML(item.rating) + ' ' + (item.rating > 0 ? item.rating.toFixed(1) : '暂无评分') + '</span>' +
          (item.githubUrl ? '<span>' + githubLinkHTML(item) + '</span>' : '') +
          (item.lastSyncAt ? '<span class="dim">GitHub 同步于 ' + fmtDate(item.lastSyncAt, true) + '</span>' : '') +
        '</div>' +
        (item.lastSyncError ? '<div class="sync-error">GitHub 同步失败：' + esc(item.lastSyncError) + '</div>' : '') +
        reason +
      '</div>' +
      '<div class="sub-actions">' + actions.join('') + '</div>' +
    '</article>';
  }

  function renderDevSyncStatus() {
    var box = $('#devSyncStatus');
    if (!box) return;
    var items = state.devItems || [];
    if (!items.length) { box.hidden = true; box.innerHTML = ''; return; }
    var synced = items.filter(function (item) { return !!item.lastSyncAt; });
    var failed = items.filter(function (item) { return !!item.lastSyncError; });
    var lastStamp = synced.map(function (item) { return item.lastSyncAt; }).sort().pop() || '';
    var summary;
    if (lastStamp) {
      summary = '上次 GitHub 同步：<b>' + fmtDate(lastStamp, true) + '</b> · 成功 ' + synced.length +
        ' 条 · 失败 ' + failed.length + ' 条';
    } else {
      summary = '还没有同步过：管理员可在后台立即同步；后台线程每 6 小时自动同步一次。';
    }
    var html = '<span class="sync-icon" aria-hidden="true">⟳</span><span>' + summary + '</span>';
    if (failed.length) {
      html += '<div class="sync-banner-errors">' + failed.slice(0, 3).map(function (item) {
        return '<div class="sync-error-item"><b>' + esc(item.name) + '</b>：' + esc(item.lastSyncError) + '</div>';
      }).join('') +
        (failed.length > 3 ? '<div class="dim">还有 ' + (failed.length - 3) + ' 条同步失败…</div>' : '') + '</div>';
    }
    box.hidden = false;
    box.className = 'sync-banner' + (failed.length ? ' has-error' : '');
    box.innerHTML = html;
  }

  function renderDevItems() {
    var list = $('#devList');
    var count = $('#devCount');
    if (count) count.textContent = state.devItems.length ? '共 ' + state.devItems.length + ' 条' : '';
    if (!list) return;
    if (!state.devItems.length) {
      list.innerHTML = '<div class="state-box"><span class="state-icon" aria-hidden="true">✎</span>' +
        '<h3>还没有提交</h3><p>点击右上角「新建提交」，把你的主题或插件交给管理员审核。</p></div>';
      return;
    }
    list.innerHTML = state.devItems.map(devRowHTML).join('');
    renderDevSyncStatus();
  }

  function openDevForm(item, prefill) {
    var wrap = $('#devFormWrap');
    if (!wrap) return;
    var source = item || prefill || null;
    state.editingId = item ? item.id : null;
    $('#devFormTitle').textContent = item ? '编辑提交' : '新建提交';
    $('#devSubmitBtn').textContent = item ? '保存修改' : '提交审核';
    $('#devKind').value = source && source.kind === 'plugin' ? 'plugin' : 'theme';
    $('#devItemId').value = source ? source.id || '' : '';
    $('#devItemId').disabled = !!item;
    $('#devName').value = source ? source.name || '' : '';
    $('#devSummary').value = source ? source.summary || '' : '';
    $('#devDescription').value = source ? source.description || '' : '';
    $('#devVersion').value = source ? source.version || '1.0.0' : '1.0.0';
    $('#devDownload').value = source ? source.downloadUrl || '' : '';
    $('#devGithub').value = source ? source.githubUrl || '' : '';
    $('#devBranch').value = source ? source.repoBranch || 'main' : 'main';
    $('#devApiVersion').value = source ? source.apiVersion || '' : '';
    $('#devReadme').value = source ? source.readmePath || 'README.md' : 'README.md';
    $('#devIcon').value = source ? source.iconPath || 'icon.png' : 'icon.png';
    $('#devTags').value = source ? (source.tags || []).join(', ') : '';
    $('#devPalette').value = source && source.kind === 'theme' && Object.keys(source.palette || {}).length
      ? JSON.stringify(paletteWithDefaults(source.palette), null, 2)
      : '';
    $('#devShots').value = source ? (source.screenshots || []).join('\n') : '';
    var platformList = source && source.platforms && source.platforms.length ? source.platforms : ['desktop'];
    $$('#devPlatforms input[name="platforms"]').forEach(function (box) {
      box.checked = platformList.indexOf(box.value) >= 0;
    });
    clearDevFormError();
    syncDevKind();
    wrap.hidden = false;
    wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setTimeout(function () { $('#devName').focus(); }, 160);
  }

  function closeDevForm() {
    var wrap = $('#devFormWrap');
    if (wrap) wrap.hidden = true;
    state.editingId = null;
    var form = $('#devForm');
    if (form) form.reset();
    clearDevFormError();
  }

  function syncDevKind() {
    var kindEl = $('#devKind');
    if (!kindEl) return;
    var kind = kindEl.value;
    var paletteField = $('#paletteField');
    var downloadHint = $('#downloadHint');
    var download = $('#devDownload');
    var idInput = $('#devItemId');
    if (paletteField) paletteField.hidden = kind !== 'theme';
    if (downloadHint) downloadHint.textContent = kind === 'plugin' ? '（必填，zip 包直链）' : '（主题可留空）';
    if (download) download.placeholder = kind === 'plugin' ? 'https://example.com/plugin.zip' : 'https://example.com/theme.json（可选）';
    if (idInput) idInput.placeholder = kind === 'plugin' ? 'com.example.my-plugin' : 'theme-ocean（可选）';
  }

  function devFormError(message) {
    var el = $('#devFormError');
    if (el) {
      el.hidden = false;
      el.textContent = message;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      toast(message, 'error');
    }
  }

  function clearDevFormError() {
    var el = $('#devFormError');
    if (el) { el.hidden = true; el.textContent = ''; }
  }

  function splitTags(text) {
    return String(text || '').split(/[,，、\n]/).map(function (part) { return part.trim(); }).filter(Boolean).slice(0, 10);
  }

  function parsePaletteText(text) {
    var raw = String(text || '').trim();
    if (!raw) return { error: '主题需要填写配色 JSON（可点击「填入示例配色」）' };
    var obj;
    try {
      obj = JSON.parse(raw);
    } catch (err) {
      return { error: '配色 JSON 格式不正确：' + (err.message || '无法解析') };
    }
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return { error: '配色必须是 JSON 对象' };
    var palette = {};
    var missing = [];
    var bad = [];
    PALETTE_KEYS.forEach(function (key) {
      var value = obj[key];
      if (typeof value !== 'string' || !value.trim()) { missing.push(key); return; }
      if (!/^#[0-9a-f]{6}$/i.test(value.trim())) { bad.push(key); return; }
      palette[key] = value.trim().toUpperCase();
    });
    if (missing.length) return { error: '缺少配色键：' + missing.join('、') };
    if (bad.length) return { error: '颜色格式不正确（应为 #RRGGBB）：' + bad.join('、') };
    return { palette: palette };
  }

  function submitDevForm(form) {
    var kind = $('#devKind').value === 'plugin' ? 'plugin' : 'theme';
    var name = ($('#devName').value || '').trim();
    var summary = ($('#devSummary').value || '').trim();
    var description = ($('#devDescription').value || '').trim();
    var version = ($('#devVersion').value || '').trim() || '1.0.0';
    var downloadUrl = ($('#devDownload').value || '').trim();
    var githubUrl = ($('#devGithub').value || '').trim();
    var repoBranch = ($('#devBranch').value || '').trim() || 'main';
    var apiVersion = ($('#devApiVersion').value || '').trim();
    var readmePath = ($('#devReadme').value || '').trim() || 'README.md';
    var iconPath = ($('#devIcon').value || '').trim() || 'icon.png';
    var tags = splitTags($('#devTags').value);
    var screenshots = ($('#devShots').value || '').split('\n').map(function (line) { return line.trim(); }).filter(Boolean);
    var itemId = ($('#devItemId').value || '').trim();
    var editingId = state.editingId;
    var palette = {};
    var platforms = $$('#devPlatforms input[name="platforms"]')
      .filter(function (box) { return box.checked; })
      .map(function (box) { return box.value; });

    clearDevFormError();
    if (!name) { devFormError('请填写名称'); return; }
    if (!summary) { devFormError('请填写一句话简介'); return; }
    if (!isGithubUrl(githubUrl)) {
      devFormError('请填写 GitHub 仓库或发布页地址（例如 https://github.com/owner/repo）');
      return;
    }
    if (!platforms.length) { devFormError('请至少选择一个适配端（电脑端或手机端）'); return; }
    if (kind === 'plugin' && !downloadUrl) { devFormError('插件必须填写下载地址'); return; }
    if (itemId && !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(itemId)) {
      devFormError('条目 ID 只能包含字母、数字、点、下划线与短横线，且不能以符号开头');
      return;
    }
    if (kind === 'theme') {
      var parsed = parsePaletteText($('#devPalette').value);
      if (parsed.error) { devFormError(parsed.error); return; }
      palette = parsed.palette;
    }

    var payload = {
      kind: kind,
      name: name,
      summary: summary,
      description: description,
      version: version,
      download_url: downloadUrl,
      github_url: githubUrl,
      repo_branch: repoBranch,
      api_version: apiVersion,
      readme_path: readmePath,
      icon_path: iconPath,
      tags: tags,
      screenshots: screenshots,
      palette: palette,
      platforms: platforms
    };
    if (itemId && !editingId) payload.id = itemId;

    var btn = $('#devSubmitBtn');
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }
    var request = editingId
      ? api('/api/dev/items/' + encodeURIComponent(editingId), { method: 'PUT', body: payload })
      : api('/api/dev/items', { method: 'POST', body: payload });
    request.then(function () {
      toast(editingId ? '已保存修改，等待重新审核' : '提交成功，等待管理员审核', 'success');
      closeDevForm();
      state.itemsLoaded = false;
      return loadDevItems();
    }).catch(function (err) {
      devFormError(errorMessage(err));
    }).then(function () {
      if (btn) { btn.disabled = false; btn.textContent = editingId ? '保存修改' : '提交审核'; }
    });
  }

  // ---------- 发布 Token ----------
  function copyText(text, okMessage) {
    var done = function () { toast(okMessage, "success"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        fallbackCopy(text);
        done();
      });
    } else {
      fallbackCopy(text);
      done();
    }
  }

  function renderTokenSecret() {
    var box = $("#tokenSecret");
    var value = $("#tokenSecretValue");
    if (!box || !value) return;
    if (!state.newToken) {
      box.hidden = true;
      value.textContent = "";
      return;
    }
    box.hidden = false;
    value.textContent = state.newToken;
  }

  function tokenStatusPill(status) {
    var safe = status === "revoked" ? "revoked" : "active";
    return '<span class="pill pill-token-' + safe + '">' + esc(TOKEN_STATUS_LABELS[safe]) + "</span>";
  }

  function renderTokens() {
    var table = $("#tokenTable");
    var count = $("#tokenCount");
    if (count) count.textContent = state.tokens.length ? "共 " + state.tokens.length + " 个" : "";
    renderTokenSecret();
    if (!table) return;
    if (!state.tokens.length) {
      table.innerHTML = '<div class="state-box" style="border:0;background:transparent">' +
        '<span class="state-icon" aria-hidden="true">⚿</span>' +
        "<h3>还没有发布 Token</h3><p>创建一个，就能在 CI 里直接提交与更新条目。</p></div>";
      return;
    }
    var head = '<div class="token-row head"><span>名称 / 前缀</span><span>状态</span>' +
      '<span>创建</span><span>最后使用</span><span>过期</span><span style="text-align:right">操作</span></div>';
    var rows = state.tokens.map(function (token) {
      var actions = token.status === "active"
        ? '<button type="button" class="btn danger-ghost sm" data-action="revoke-token" data-id="' + esc(token.id) + '">撤销</button>'
        : '<span class="dim token-revoked-note">已撤销</span>';
      return '<div class="token-row">' +
        '<div class="token-name"><b>' + esc(token.name) + '</b><span class="mono dim token-prefix">' + esc(token.prefix) + "…</span></div>" +
        "<div>" + tokenStatusPill(token.status) + "</div>" +
        '<div class="token-date">' + fmtDate(token.createdAt, true) + "</div>" +
        '<div class="token-date">' + (token.lastUsedAt ? fmtDate(token.lastUsedAt, true) : '<span class="dim">未使用</span>') + "</div>" +
        '<div class="token-date">' + (token.expiresAt ? fmtDate(token.expiresAt, true) : '<span class="dim">永久</span>') + "</div>" +
        '<div class="token-actions">' + actions + "</div>" +
        "</div>";
    }).join("");
    table.innerHTML = head + rows;
  }

  function loadTokens() {
    var table = $("#tokenTable");
    if (table) {
      table.innerHTML = '<div style="text-align:center;padding:28px">' +
        '<span class="spinner"></span> <span class="muted">正在加载 Token…</span></div>';
    }
    api("/api/dev/tokens").then(function (data) {
      var list = Array.isArray(data) ? data : (data && Array.isArray(data.tokens) ? data.tokens : []);
      state.tokens = list.map(normalizeToken).filter(Boolean);
      state.tokensLoaded = true;
      renderTokens();
    }).catch(function (err) {
      if (!table) return;
      table.innerHTML = '<div class="state-box state-danger" style="border:0;background:transparent">' +
        '<span class="state-icon" aria-hidden="true">⚠</span><h3>加载失败</h3><p>' + esc(errorMessage(err)) + "</p>" +
        '<button type="button" class="btn ghost" data-action="reload-tokens">重试</button></div>';
    });
  }

  function createToken(form) {
    var name = ($("#tokenName").value || "").trim();
    var expiresDays = Number($("#tokenExpires").value);
    var errorEl = $("#tokenFormError");
    function fail(message) {
      if (errorEl) {
        errorEl.hidden = false;
        errorEl.textContent = message;
      } else {
        toast(message, "error");
      }
    }
    if (errorEl) { errorEl.hidden = true; errorEl.textContent = ""; }
    if (!name) { fail("请填写 Token 名称"); return; }
    if (!isFinite(expiresDays) || expiresDays < 0) expiresDays = 0;
    var btn = $("#tokenSubmitBtn");
    if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
    api("/api/dev/tokens", { method: "POST", body: { name: name, expires_days: expiresDays } }).then(function (data) {
      var created = normalizeToken(data);
      if (!created) throw new ApiError("Token 创建响应格式不正确", 0, null);
      state.tokens = [created].concat(state.tokens.filter(function (item) { return String(item.id) !== String(created.id); }));
      state.newToken = created.token || "";
      if (form) form.reset();
      renderTokens();
      toast("Token 已创建：明文只显示一次，请立刻复制", "success");
    }).catch(function (err) {
      fail(errorMessage(err));
    }).then(function () {
      if (btn) { btn.disabled = false; btn.textContent = "生成 Token"; }
    });
  }

  function copyNewToken() {
    if (!state.newToken) {
      toast("没有可复制的 Token，请重新创建", "info");
      return;
    }
    copyText(state.newToken, "Token 已复制，请妥善保存（只显示一次）");
  }

  function revokeToken(tokenId) {
    var target = state.tokens.filter(function (item) { return String(item.id) === String(tokenId); })[0];
    confirmDialog({
      title: "撤销这个 Token？",
      message: "「" + (target ? target.name : "该 Token") + "」撤销后立刻失效，正在使用它的 CI 发布会收到 401。",
      okText: "撤销 Token",
      danger: true
    }).then(function (ok) {
      if (!ok) return null;
      return api("/api/dev/tokens/" + encodeURIComponent(tokenId) + "/revoke", { method: "POST" }).then(function (data) {
        var updated = normalizeToken(data);
        if (updated) {
          state.tokens = state.tokens.map(function (item) {
            return String(item.id) === String(updated.id) ? updated : item;
          });
          renderTokens();
        } else {
          loadTokens();
        }
        toast("Token 已撤销", "success");
      }).catch(function (err) {
        toast(errorMessage(err), "error");
      });
    });
  }

  // ---------- 管理后台 ----------
  function loadAdmin() {
    var tasks = [loadAdminPending(), loadAdminComments()];
    if (state.adminTab === 'users') tasks.push(loadAdminUsers());
    return Promise.all(tasks);
  }

  function setAdminTab(tab) {
    state.adminTab = tab === 'users' || tab === 'comments' ? tab : 'pending';
    $$('.seg-tab[data-admin-tab]').forEach(function (btn) {
      var active = btn.getAttribute('data-admin-tab') === state.adminTab;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    var pendingPanel = $('#adminPendingPanel');
    var commentsPanel = $('#adminCommentsPanel');
    var usersPanel = $('#adminUsersPanel');
    if (pendingPanel) pendingPanel.hidden = state.adminTab !== 'pending';
    if (commentsPanel) commentsPanel.hidden = state.adminTab !== 'comments';
    if (usersPanel) usersPanel.hidden = state.adminTab !== 'users';
    if (state.adminTab === 'users') loadAdminUsers();
    else if (state.pendingItems.length === 0 && state.pendingComments.length === 0) loadAdmin();
  }

  function loadAdminPending() {
    var panel = $('#adminPendingPanel');
    if (panel) {
      panel.innerHTML = '<div class="panel" style="text-align:center;padding:36px">' +
        '<span class="spinner"></span> <span class="muted">正在加载待审核列表…</span></div>';
    }
    return api('/api/admin/submissions?status=pending').then(function (data) {
      state.pendingItems = normalizeList(data);
      renderAdminPending();
    }).catch(function (err) {
      if (!panel) return;
      panel.innerHTML = '<div class="state-box state-danger"><span class="state-icon" aria-hidden="true">⚠</span>' +
        '<h3>加载失败</h3><p>' + esc(errorMessage(err)) + '</p>' +
        '<button type="button" class="btn ghost" data-action="reload-admin">重试</button></div>';
    });
  }

  function adminPendingCardHTML(item) {
    var cover = item.kind === 'plugin'
      ? '<div class="review-cover cover-plugin"><span class="cover-glyph" aria-hidden="true">❖</span></div>'
      : '<div class="review-cover cover-theme" style="background:' + paletteBackground(item.palette) + '"></div>';
    return '<article class="review-card">' +
      cover +
      '<div class="review-info">' +
        '<div class="review-title-row">' + kindPill(item.kind) + '<h3>' + esc(item.name) + '</h3>' + statusPill(item.status) + '</div>' +
        '<p class="review-summary">' + (item.summary ? esc(item.summary) : '<span class="dim">暂无简介</span>') + '</p>' +
        '<div class="review-meta">' +
          '<span>作者：' + esc(item.author) + '</span>' +
          '<span>版本：v' + esc(item.version) + '</span>' +
          '<span>提交于 ' + fmtDate(item.createdAt, true) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="review-actions">' +
        '<button type="button" class="btn ghost sm" data-action="open-detail" data-id="' + esc(item.id) + '">查看详情</button>' +
        '<button type="button" class="btn primary sm" data-action="approve-item" data-id="' + esc(item.id) + '">通过</button>' +
        '<button type="button" class="btn danger-ghost sm" data-action="reject-item" data-id="' + esc(item.id) + '">拒绝</button>' +
      '</div>' +
    '</article>';
  }

  function renderAdminPending() {
    var panel = $('#adminPendingPanel');
    var count = $('#pendingCount');
    if (count) count.textContent = String(state.pendingItems.length);
    if (!panel) return;
    if (!state.pendingItems.length) {
      panel.innerHTML = '<div class="state-box"><span class="state-icon" aria-hidden="true">✓</span>' +
        '<h3>没有待审核的提交</h3><p>开发者提交后会出现在这里，通过后自动上架。</p></div>';
      return;
    }
    panel.innerHTML = state.pendingItems.map(adminPendingCardHTML).join('');
  }

  function loadAdminComments() {
    var panel = $('#adminCommentsPanel');
    if (panel) {
      panel.innerHTML = '<div class="panel" style="text-align:center;padding:36px">' +
        '<span class="spinner"></span> <span class="muted">正在加载待审核评论…</span></div>';
    }
    return api('/api/admin/comments?status=pending').then(function (data) {
      var list = Array.isArray(data) ? data : (data && Array.isArray(data.comments) ? data.comments : []);
      state.pendingComments = list.map(normalizeComment).filter(Boolean);
      renderAdminComments();
    }).catch(function (err) {
      if (!panel) return;
      panel.innerHTML = '<div class="state-box state-danger"><span class="state-icon" aria-hidden="true">⚠</span>' +
        '<h3>评论审核暂不可用</h3><p>' + esc(errorMessage(err)) + '</p></div>';
    });
  }

  function renderAdminComments() {
    var panel = $('#adminCommentsPanel');
    var count = $('#pendingCommentCount');
    if (count) count.textContent = String(state.pendingComments.length);
    if (!panel) return;
    if (!state.pendingComments.length) {
      panel.innerHTML = '<div class="state-box"><span class="state-icon" aria-hidden="true">✓</span>' +
        '<h3>没有待审核评论</h3><p>用户提交评论后会出现在这里，通过后才对所有人可见。</p></div>';
      return;
    }
    panel.innerHTML = state.pendingComments.map(function (comment) {
      return '<article class="sub-row status-pending">' +
        '<div class="sub-main">' +
          '<div class="sub-title-row"><h3>' + esc(comment.itemName || '条目 #' + comment.itemId) + '</h3>' +
            starsHTML(comment.rating) + '<span class="dim" style="font-size:12px">' + comment.rating.toFixed(0) + ' 星</span></div>' +
          '<p class="sub-summary">' + esc(comment.text) + '</p>' +
          '<div class="sub-meta">' +
            '<span>' + esc(comment.userName) + '</span>' +
            '<span>' + fmtDate(comment.createdAt, true) + '</span>' +
            '<span class="mono">item #' + esc(comment.itemId) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="sub-actions">' +
          '<button type="button" class="btn ghost sm" data-action="open-detail" data-id="' + esc(comment.itemId) + '" data-mode="admin">查看条目</button>' +
          '<button type="button" class="btn primary sm" data-action="approve-comment" data-id="' + esc(comment.id) + '">通过</button>' +
          '<button type="button" class="btn danger-ghost sm" data-action="reject-comment" data-id="' + esc(comment.id) + '">忽略</button>' +
        '</div>' +
      '</article>';
    }).join('');
  }

  function reviewComment(commentId, action) {
    var confirmed = action === 'reject'
      ? confirmDialog({ title: '忽略这条评论？', message: '忽略后该评论不会展示在商店页。', okText: '忽略评论', danger: true })
      : Promise.resolve(true);
    confirmed.then(function (ok) {
      if (!ok) return null;
      return api('/api/admin/comments/' + encodeURIComponent(commentId) + '/review', {
        method: 'POST',
        body: { action: action }
      }).then(function () {
        toast(action === 'approve' ? '评论已通过，已展示在条目页' : '评论已忽略', 'success');
        state.itemsLoaded = false;
        return loadAdminComments();
      }).catch(function (err) {
        toast(errorMessage(err), 'error');
      });
    });
  }

  function loadAdminUsers() {
    var table = $('#userTable');
    if (table) {
      table.innerHTML = '<div style="text-align:center;padding:28px">' +
        '<span class="spinner"></span> <span class="muted">正在加载用户…</span></div>';
    }
    return api('/api/admin/users').then(function (data) {
      state.users = (Array.isArray(data) ? data : []).filter(function (user) { return user && typeof user === 'object'; });
      renderAdminUsers();
    }).catch(function (err) {
      if (!table) return;
      table.innerHTML = '<div class="state-box state-danger"><span class="state-icon" aria-hidden="true">⚠</span>' +
        '<h3>加载失败</h3><p>' + esc(errorMessage(err)) + '</p></div>';
    });
  }

  function renderAdminUsers() {
    var table = $('#userTable');
    var count = $('#userCount');
    if (count) count.textContent = state.users.length ? '共 ' + state.users.length + ' 位用户' : '';
    if (!table) return;
    if (!state.users.length) {
      table.innerHTML = '<p class="muted">暂无用户。</p>';
      return;
    }
    var rows = state.users.map(function (user) {
      var self = state.user && Number(user.id) === Number(state.user.id);
      var actions = [];
      if (!self && user.role === 'user') {
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="developer">设为开发者</button>');
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="admin">设为管理员</button>');
      } else if (!self && user.role === 'developer') {
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="admin">设为管理员</button>');
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="user">降为普通用户</button>');
      } else if (!self && user.role === 'admin') {
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="developer">降为开发者</button>');
        actions.push('<button type="button" class="btn ghost" data-action="set-role" data-id="' + esc(user.id) + '" data-role="user">降为普通用户</button>');
      }
      return '<div class="user-row">' +
        '<div class="user-identity">' +
          '<span class="avatar" aria-hidden="true">' + esc(initials(user.name, user.email)) + '</span>' +
          '<span class="who"><b>' + esc(user.name || '未命名') + '</b><span>' + esc(user.email || '') + '</span></span>' +
        '</div>' +
        '<div>' + rolePill(user.role) + '</div>' +
        '<div class="user-date">' + fmtDate(user.created_at) + '</div>' +
        '<div class="user-actions">' + (self ? '<span class="self-note">当前账号</span>' : (actions.join('') || '<span class="self-note">—</span>')) + '</div>' +
      '</div>';
    }).join('');
    table.innerHTML = '<div class="user-row head"><span>用户</span><span>角色</span><span>注册时间</span>' +
      '<span style="text-align:right">调整</span></div>' + rows;
  }

  function setUserRole(userId, role) {
    var target = state.users.filter(function (user) { return Number(user.id) === Number(userId); })[0];
    var label = roleLabel(role);
    confirmDialog({
      title: '确认调整角色',
      message: '将「' + (target ? target.name || target.email : '该用户') + '」设为' + label + '？' +
        (role === 'admin' ? '管理员可以审核提交并管理所有用户。' : ''),
      okText: '确认设为' + label
    }).then(function (ok) {
      if (!ok) return null;
      return api('/api/admin/users/' + encodeURIComponent(userId) + '/role', {
        method: 'POST',
        body: { role: role }
      }).then(function () {
        toast('角色已更新为' + label, 'success');
        return loadAdminUsers().then(function () {
          if (state.user && Number(state.user.id) === Number(userId)) return refreshMe();
          return null;
        });
      }).catch(function (err) {
        toast(errorMessage(err), 'error');
      });
    });
  }

  // ---------- 复制配色 ----------
  function fallbackCopy(text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (err) { /* 忽略 */ }
    area.remove();
  }

  function copyPalette(itemId) {
    var item = findItem(itemId);
    if (!item && state.detail.item && String(state.detail.item.id) === String(itemId)) item = state.detail.item;
    if (!item) { toast('找不到条目信息，请刷新后重试', 'error'); return; }
    var text = JSON.stringify(paletteWithDefaults(item.palette), null, 2);
    var done = function () { toast('配色 JSON 已复制，可在深清「主题」页导入自定义主题', 'success'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        fallbackCopy(text);
        done();
      });
    } else {
      fallbackCopy(text);
      done();
    }
  }

  // ---------- 事件 ----------
  function onClick(event) {
    var trigger = event.target && event.target.closest ? event.target.closest('[data-action]') : null;
    if (!trigger) return;
    var action = trigger.getAttribute('data-action');
    var id = trigger.getAttribute('data-id');

    if (action === 'logout') {
      event.preventDefault();
      logout();
      return;
    }
    if (action === 'close-modal') {
      event.preventDefault();
      closeModal();
      if (location.hash.indexOf('#/item/') === 0) {
        history.replaceState({}, '', state.returnHash || '#/store');
      }
      return;
    }
    if (action === 'close-dialog') {
      closeDialog();
      return;
    }
    if (action === 'open-detail') {
      event.preventDefault();
      var mode = trigger.getAttribute('data-mode');
      if (!mode) {
        var visible = $$('#app > .view').filter(function (view) { return !view.hidden; })[0];
        mode = visible && visible.id === 'view-admin' ? 'admin' : visible && visible.id === 'view-dev' ? 'dev' : 'store';
      }
      openDetail(id, mode, { push: mode === 'store' });
      return;
    }
    if (action === 'copy-palette') {
      event.preventDefault();
      copyPalette(id);
      return;
    }
    if (action === 'reload-store') { loadItems(); return; }
    if (action === 'reload-dev') { loadDevItems(); return; }
    if (action === 'reload-tokens') { loadTokens(); return; }
    if (action === 'revoke-token') { revokeToken(id); return; }
    if (action === 'reload-admin') { loadAdmin(); return; }
    if (action === 'reset-filters') {
      state.q = '';
      state.kind = '';
      state.platform = '';
      var search = $('#searchInput');
      if (search) search.value = '';
      $$('#kindChips .chip').forEach(function (chip) {
        var active = (chip.getAttribute('data-kind') || '') === '';
        chip.classList.toggle('is-active', active);
        chip.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      $$('#platformChips .chip').forEach(function (chip) {
        var active = (chip.getAttribute('data-platform') || '') === '';
        chip.classList.toggle('is-active', active);
        chip.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      loadItems();
      return;
    }
    if (action === 'go-login') {
      event.preventDefault();
      closeModal();
      go('#/auth');
      return;
    }
    if (action === 'edit-dev-item') {
      var editingItem = findItem(id);
      if (editingItem) openDevForm(editingItem);
      else toast('找不到该提交，请刷新后重试', 'error');
      return;
    }
    if (action === 'reclone-dev-item') {
      var sourceItem = findItem(id);
      if (sourceItem) openDevForm(null, sourceItem);
      else toast('找不到该提交，请刷新后重试', 'error');
      return;
    }
    if (action === 'approve-item' || action === 'reject-item') {
      var target = findItem(id);
      if (!target && state.detail.item && String(state.detail.item.id) === String(id)) target = state.detail.item;
      if (!target) { toast('找不到该提交，请刷新后重试', 'error'); return; }
      reviewItem(target, action === 'approve-item' ? 'approve' : 'reject');
      return;
    }
    if (action === 'approve-comment') { reviewComment(id, 'approve'); return; }
    if (action === 'reject-comment') { reviewComment(id, 'reject'); return; }
    if (action === 'set-role') { setUserRole(id, trigger.getAttribute('data-role')); return; }
  }

  function bindEvents() {
    document.addEventListener('click', onClick);
    document.addEventListener('submit', function (event) {
      if (event.target && event.target.id === 'commentForm') {
        event.preventDefault();
        submitComment(event.target);
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      if (closeTopDialog()) return;
      if ($('#modalRoot .modal')) {
        closeModal();
        if (location.hash.indexOf('#/item/') === 0) {
          history.replaceState({}, '', state.returnHash || '#/store');
        }
      }
    });

    var search = $('#searchInput');
    if (search) {
      var timer = null;
      search.addEventListener('input', function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          state.q = search.value.trim();
          loadItems();
        }, 280);
      });
    }

    var sort = $('#sortSelect');
    if (sort) {
      sort.addEventListener('change', function () {
        state.sort = sort.value;
        loadItems();
      });
    }

    var kindChips = $('#kindChips');
    if (kindChips) {
      kindChips.addEventListener('click', function (event) {
        var chip = event.target.closest('.chip[data-kind]');
        if (!chip) return;
        state.kind = chip.getAttribute('data-kind') || '';
        $$('.chip', kindChips).forEach(function (item) {
          var active = (item.getAttribute('data-kind') || '') === state.kind;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        loadItems();
      });
    }

    var platformChips = $('#platformChips');
    if (platformChips) {
      platformChips.addEventListener('click', function (event) {
        var chip = event.target.closest('.chip[data-platform]');
        if (!chip) return;
        state.platform = chip.getAttribute('data-platform') || '';
        $$('.chip', platformChips).forEach(function (item) {
          var active = (item.getAttribute('data-platform') || '') === state.platform;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        loadItems();
      });
    }

    $$('.auth-tab').forEach(function (tab) {
      tab.addEventListener('click', function () { setAuthMode(tab.getAttribute('data-auth-mode')); });
    });
    $$('.mode-tab').forEach(function (tab) {
      tab.addEventListener('click', function () { setLoginMode(tab.getAttribute('data-login-mode')); });
    });
    var sendCodeBtn = $('#sendCodeBtn');
    if (sendCodeBtn) sendCodeBtn.addEventListener('click', sendCode);
    var authEmailInput = $('#authEmail');
    if (authEmailInput) authEmailInput.addEventListener('input', renderCodeButton);
    var forgotBtn = $('#forgotBtn');
    if (forgotBtn) forgotBtn.addEventListener('click', function () { setAuthStage('reset'); });
    var backToLoginBtn = $('#backToLoginBtn');
    if (backToLoginBtn) backToLoginBtn.addEventListener('click', function () { setAuthStage('login'); });
    var devCodeFill = $('#devCodeFill');
    if (devCodeFill) {
      devCodeFill.addEventListener('click', function () {
        var codeInput = $('#authCode');
        if (!codeInput || !state.devCode || !state.devCode.code) return;
        codeInput.value = state.devCode.code;
        codeInput.focus();
      });
    }
    $$('.seg-tab[data-admin-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () { setAdminTab(tab.getAttribute('data-admin-tab')); });
    });

    var newBtn = $('#newSubmissionBtn');
    if (newBtn) newBtn.addEventListener('click', function () { openDevForm(null); });
    var formClose = $('#devFormClose');
    if (formClose) formClose.addEventListener('click', closeDevForm);
    var formCancel = $('#devCancelBtn');
    if (formCancel) formCancel.addEventListener('click', closeDevForm);
    var kindSelect = $('#devKind');
    if (kindSelect) kindSelect.addEventListener('change', syncDevKind);
    var templateBtn = $('#paletteTemplateBtn');
    if (templateBtn) {
      templateBtn.addEventListener('click', function () {
        $('#devPalette').value = JSON.stringify(FALLBACK_PALETTE, null, 2);
        clearDevFormError();
      });
    }
    var authForm = $('#authForm');
    if (authForm) {
      authForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitAuth(authForm);
      });
    }
    var devForm = $('#devForm');
    if (devForm) {
      devForm.addEventListener('submit', function (event) {
        event.preventDefault();
        submitDevForm(devForm);
      });
    }
    var tokenForm = $('#tokenForm');
    if (tokenForm) {
      tokenForm.addEventListener('submit', function (event) {
        event.preventDefault();
        createToken(tokenForm);
      });
    }
    var tokenCopyBtn = $('#tokenCopyBtn');
    if (tokenCopyBtn) tokenCopyBtn.addEventListener('click', copyNewToken);

    window.addEventListener('hashchange', route);
    window.addEventListener('popstate', function () { route(); });
  }

  // ---------- 启动 ----------
  function boot() {
    try {
      state.token = localStorage.getItem(TOKEN_KEY) || '';
      var rawUser = localStorage.getItem(USER_KEY) || '';
      if (rawUser) {
        var parsedUser = JSON.parse(rawUser);
        if (parsedUser && typeof parsedUser === 'object') state.user = parsedUser;
      }
    } catch (err) {
      state.token = state.token || '';
      state.user = null;
    }
    renderAuthBox();
    renderNavVisibility();
    bindEvents();
    if (state.token) refreshMe();
    route();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();



