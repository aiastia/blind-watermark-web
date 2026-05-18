// API 基础地址配置
// 本地/全栈部署：留空，自动用当前域名
// 分离部署(CF Pages + Railway)：改为 Railway 后端地址，如 'https://xxx.up.railway.app'
const API = window.__API_URL__ || window.location.origin;

const utils = {
  fmtSize(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(1) + ' MB';
  },
  toast(msg) {
    const el = document.createElement('div');
    el.className = 'copy-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2000);
  },
  copyText(text) {
    navigator.clipboard.writeText(text).then(() => utils.toast('✅ 已复制到剪贴板'));
  },
  downloadBlob(url, filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  },
  async fetchBlob(endpoint, formData) {
    const resp = await fetch(`${API}${endpoint}`, { method: 'POST', body: formData });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '请求失败');
    }
    const blob = await resp.blob();
    const headers = {};
    resp.headers.forEach((v, k) => { headers[k] = v; });
    return { blob, headers };
  },
  async fetchJSON(endpoint, formData) {
    const resp = await fetch(`${API}${endpoint}`, { method: 'POST', body: formData });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '请求失败');
    }
    return resp.json();
  },
};

/* Shared Vue mixin for file upload pages */
const fileUploadMixin = {
  methods: {
    handleDrop(e, refName) {
      e.currentTarget.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) {
        this.setFile(file);
      }
    },
    handleMultiDrop(e) {
      e.currentTarget.classList.remove('dragover');
      const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
      if (files.length) this.addFiles(files);
    },
  },
};