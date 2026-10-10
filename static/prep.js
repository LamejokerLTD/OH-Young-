// Pre-production page. All server data is written with textContent; nothing is parsed as HTML.
(() => {
  'use strict';

  const STEP_LABELS = {
    probe: '讀取', silence: '靜音偵測', render: '渲染', transcript: '逐字稿', cutlist: '剪輯清單',
  };
  const STATUS_LABELS = {
    queued: '排隊中', running: '處理中', done: '完成', failed: '失敗', cancelled: '已取消', deleted: '成品已刪除',
  };
  const FILE_LABELS = {
    'render': '影片', 'render-audio': '音訊', 'cutlist.edl': 'EDL', 'cutlist.fcpxml': 'FCPXML',
    'cutlist.xml': 'Premiere XML', 'transcript.srt': 'SRT', 'transcript.vtt': 'VTT',
    'transcript.txt': 'TXT', 'transcript.timed.txt': '帶時間碼 TXT', 'transcript.json': 'JSON',
  };
  const RECOMMENDED = { denoise: 'light', eq: true, balance: true, loudness: true };

  const $ = (id) => document.getElementById(id);

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json' };
    const init = { method: options.method || 'GET', headers };
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.body);
    }
    if (init.method !== 'GET') headers['X-Local-Request'] = '1';
    const response = await fetch(path, init);
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      const detail = data && typeof data.detail === 'string' ? data.detail : '發生錯誤，請稍後再試。';
      throw new Error(detail);
    }
    return data;
  }

  function setMessage(text, kind) {
    const node = $('form-message');
    node.textContent = text || '';
    node.className = 'message' + (kind ? ' ' + kind : '');
  }

  function formatSize(bytes) {
    if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(2) + ' GB';
    if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + ' MB';
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }

  function collectParams() {
    const silenceOn = $('silence-on').checked;
    return {
      speed: Number($('speed').value),
      clarity: {
        denoise: $('denoise').value,
        eq: $('eq').checked,
        balance: $('balance').checked,
        loudness: $('loudness').checked,
      },
      silence: {
        enabled: silenceOn,
        threshold_db: Number($('threshold').value),
        min_silence: Number($('min-silence').value),
        pad: Number($('pad').value),
      },
      transcript: {
        enabled: $('transcript-on').checked,
        language: $('language').value,
        traditional: $('traditional').checked,
      },
    };
  }

  // The file most recently ticked; preview uses it so it matches what the user just chose.
  let lastChecked = null;

  function selectedInputs() {
    return Array.from(document.querySelectorAll('#input-list input[type=checkbox]:checked')).map((box) => box.value);
  }

  function previewTarget() {
    const inputs = selectedInputs();
    return inputs.includes(lastChecked) ? lastChecked : inputs[inputs.length - 1];
  }

  function syncOutputs() {
    $('speed-out').textContent = Number($('speed').value).toFixed(2) + '×';
    $('min-out').textContent = Number($('min-silence').value).toFixed(1) + ' 秒';
    $('pad-out').textContent = Number($('pad').value).toFixed(2) + ' 秒';
    const enabled = $('silence-on').checked;
    const fields = $('silence-fields');
    fields.setAttribute('aria-disabled', String(!enabled));
    fields.querySelectorAll('select,input').forEach((field) => { field.disabled = !enabled; });
  }

  function resetParams() {
    $('speed').value = 1;
    $('denoise').value = 'off';
    $('eq').checked = false;
    $('balance').checked = false;
    $('loudness').checked = false;
    $('silence-on').checked = false;
    $('threshold').value = '-35';
    $('min-silence').value = '0.8';
    $('pad').value = '0.15';
    $('transcript-on').checked = true;
    $('language').value = 'zh';
    $('traditional').checked = true;
    syncOutputs();
  }

  async function loadInputs() {
    const list = $('input-list');
    try {
      const data = await api('/api/prep/inputs');
      list.replaceChildren();
      $('input-empty').hidden = data.items.length > 0;
      data.items.forEach((item) => {
        const row = el('li');
        const label = el('label');
        const box = el('input');
        box.type = 'checkbox';
        box.value = item.path;
        box.addEventListener('change', () => { if (box.checked) lastChecked = item.path; });
        label.append(box, el('span', item.path, 'name'));
        row.append(label, el('span', formatSize(item.size), 'size'));
        list.append(row);
      });
    } catch (error) {
      setMessage(error.message, 'error');
    }
  }

  function renderSteps(steps) {
    const list = el('ul', null, 'steps');
    Object.keys(STEP_LABELS).forEach((step) => {
      const state = (steps && steps[step]) || 'pending';
      const label = state === 'skipped' ? '略過' : STEP_LABELS[step];
      list.append(el('li', label, state));
    });
    return list;
  }

  function renderJob(job) {
    const item = el('li', null, 'job');
    const head = el('div', null, 'job-head');
    head.append(el('span', job.name, 'job-name'));
    head.append(el('span', STATUS_LABELS[job.status] || job.status, 'badge ' + job.status));
    item.append(head, el('p', job.stage || '', 'hint'));
    item.append(renderSteps(job.steps));

    if (job.status === 'running' && typeof job.progress === 'number') {
      const bar = el('div', null, 'bar');
      const fill = el('div');
      fill.style.width = Math.round(job.progress * 100) + '%';
      bar.append(fill);
      item.append(bar);
    }
    if (job.summary) {
      const s = job.summary;
      item.append(el('p',
        `成品約 ${s.output_seconds.toFixed(1)} 秒｜移除空白 ${s.removed_seconds.toFixed(1)} 秒｜保留 ${s.segments} 段`,
        'job-summary'));
    }
    if (job.warning) item.append(el('p', job.warning, 'job-warning'));
    if (job.error) item.append(el('p', job.error, 'job-error'));

    if (job.files && job.files.length) {
      const links = el('div', null, 'downloads');
      job.files.forEach((kind) => {
        const link = el('a', FILE_LABELS[kind] || kind);
        link.href = `/api/prep/projects/${job.id}/files/${encodeURIComponent(kind)}`;
        link.setAttribute('download', '');
        links.append(link);
      });
      item.append(links);
    }

    const actions = el('div', null, 'job-actions');
    if (job.status === 'queued' || job.status === 'running') {
      const cancel = el('button', '取消', 'danger');
      cancel.type = 'button';
      cancel.addEventListener('click', () => cancelJob(job.id, cancel));
      actions.append(cancel);
    }
    if (job.status === 'done' && job.files && job.files.length) {
      const remove = el('button', '刪除成品', 'danger');
      remove.type = 'button';
      remove.addEventListener('click', () => deleteOutput(job.id, job.name));
      actions.append(remove);
    }
    if (actions.childNodes.length) item.append(actions);
    return item;
  }

  async function refreshJobs() {
    try {
      const data = await api('/api/prep/projects');
      const list = $('job-list');
      list.replaceChildren(...data.projects.map(renderJob));
      $('job-empty').hidden = data.projects.length > 0;
    } catch (error) {
      setMessage(error.message, 'error');
    }
  }

  async function cancelJob(id, button) {
    button.disabled = true;
    try {
      await api(`/api/prep/projects/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
      setMessage('已送出取消要求。', 'ok');
    } catch (error) {
      setMessage(error.message, 'error');
    }
    refreshJobs();
  }

  async function deleteOutput(id, name) {
    if (!window.confirm(`確定要刪除「${name}」的成品嗎？\n刪除後無法復原，請先確認已下載。`)) return;
    try {
      await api(`/api/prep/projects/${encodeURIComponent(id)}/output`, { method: 'DELETE' });
      setMessage('成品已刪除。', 'ok');
    } catch (error) {
      setMessage(error.message, 'error');
    }
    refreshJobs();
  }

  async function submitBatch() {
    const inputs = selectedInputs();
    if (!inputs.length) {
      setMessage('請先勾選至少一支影片。', 'error');
      return;
    }
    const button = $('submit-btn');
    button.disabled = true;
    try {
      const data = await api('/api/prep/batches', { method: 'POST', body: { inputs, params: collectParams() } });
      setMessage(`已加入 ${data.projects.length} 個工作，依序處理中。`, 'ok');
      refreshJobs();
    } catch (error) {
      setMessage(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function previewFirst() {
    const target = previewTarget();
    if (!target) {
      setMessage('請先勾選一支影片來預覽。', 'error');
      return;
    }
    const button = $('preview-btn');
    button.disabled = true;
    setMessage(`正在產生預覽：${target}（約需數秒到數十秒）…`, '');
    try {
      const data = await api('/api/prep/preview', { method: 'POST', body: { input: target, params: collectParams() } });
      const slot = $('preview-slot');
      slot.replaceChildren(el('p', `預覽檔案：${target}`, 'hint'));
      const isVideo = data.url.endsWith('.mp4');
      const media = document.createElement(isVideo ? 'video' : 'audio');
      media.controls = true;
      media.preload = 'metadata';
      if (isVideo) media.className = 'preview-media';
      media.src = data.url;
      slot.append(media);
      $('preview-panel').hidden = false;
      setMessage(`預覽已產生：${target}（前 ${data.seconds} 秒）。`, 'ok');
      media.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (error) {
      setMessage(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  }

  function applyRecommended() {
    $('denoise').value = RECOMMENDED.denoise;
    $('eq').checked = RECOMMENDED.eq;
    $('balance').checked = RECOMMENDED.balance;
    $('loudness').checked = RECOMMENDED.loudness;
    setMessage('已套用推薦組合：輕度降噪、EQ、音量平衡、響度標準化。', 'ok');
  }

  function bind() {
    $('refresh-inputs').addEventListener('click', loadInputs);
    $('refresh-jobs').addEventListener('click', refreshJobs);
    $('reset-params').addEventListener('click', () => { resetParams(); setMessage('已恢復預設參數。', 'ok'); });
    $('apply-recommended').addEventListener('click', applyRecommended);
    $('submit-btn').addEventListener('click', submitBatch);
    $('preview-btn').addEventListener('click', previewFirst);
    $('close-preview').addEventListener('click', () => {
      $('preview-slot').replaceChildren();
      $('preview-panel').hidden = true;
    });
    ['speed', 'min-silence', 'pad', 'silence-on', 'threshold'].forEach((id) => {
      $(id).addEventListener('input', syncOutputs);
      $(id).addEventListener('change', syncOutputs);
    });
  }

  bind();
  syncOutputs();
  loadInputs();
  refreshJobs();
  window.setInterval(refreshJobs, 2000);
})();
