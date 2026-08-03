const state = { project: null, history: [], proposal: null, conversationId: null };
const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || `Error HTTP ${response.status}`);
  return payload;
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  window.clearTimeout(element._timer);
  element._timer = window.setTimeout(() => element.classList.remove('show'), 3500);
}

function setStatus(selector, connected, text) {
  const element = $(selector);
  element.classList.toggle('offline', !connected);
  element.querySelector('span').textContent = text;
}

async function refreshStatus() {
  try {
    const result = await api('/api/status');
    const reaper = result.reaper;
    setStatus('#reaper-status', reaper.connected, reaper.connected ? `REAPER ${reaper.reaper_version || 'conectado'}` : 'REAPER desconectado');
    setStatus('#bridge-status', reaper.connected, reaper.connected ? `Bridge ${reaper.bridge_version || 'conectado'}` : 'Bridge desconectado');
    const brain = result.brain;
    setStatus('#brain-status', brain.connected, brain.connected ? (brain.selected_model || 'LLM conectado').replace(/^.*\//, '') : 'LLM sin conexión');
  } catch (error) {
    setStatus('#reaper-status', false, 'Estado no disponible');
    setStatus('#bridge-status', false, 'Bridge no disponible');
    setStatus('#brain-status', false, 'LLM no disponible');
  }
}

function renderProject(project) {
  if (state.project?.name !== project.name) {
    let conversations = {};
    try { conversations = JSON.parse(localStorage.getItem('pampapilot.conversations') || '{}'); } catch { conversations = {}; }
    state.conversationId = conversations[project.name] || crypto.randomUUID();
    conversations[project.name] = state.conversationId;
    localStorage.setItem('pampapilot.conversations', JSON.stringify(conversations));
    state.history = [];
  }
  state.project = project;
  $('#project-title').textContent = project.name;
  $('#project-bpm').textContent = project.tempo_bpm ? `${project.tempo_bpm} BPM` : 'BPM sin definir';
  $('#project-source').textContent = `Origen: ${project.source_label || 'Sin clasificar'}`;
  const timeline = $('#timeline');
  timeline.innerHTML = '';
  if (!project.sections?.length) {
    timeline.innerHTML = '<div class="empty-state">No hay secciones en la letra. Podés agregarlas al editar el proyecto.</div>';
    $('#structure-note').textContent = 'Sin secciones';
  } else {
    project.sections.forEach(section => {
      const chip = document.createElement('div');
      chip.className = 'section-chip';
      chip.textContent = section;
      timeline.appendChild(chip);
    });
    $('#structure-note').textContent = `${project.sections.length} secciones detectadas`;
  }
  const list = $('#stem-list');
  list.innerHTML = '';
  if (!project.stems?.length) list.innerHTML = '<div class="empty-state">Todavía no se cargaron stems.</div>';
  (project.stems || []).forEach((stem, index) => {
    const row = document.createElement('div');
    row.className = 'stem-row';
    const badgeClass = stem.source === 'Suno' ? 'amber' : stem.source === 'Sin clasificar' ? 'neutral' : '';
    row.innerHTML = `
      <div class="stem-name"><span class="stem-icon">${index % 3 === 0 ? '◉' : index % 3 === 1 ? '♬' : '≋'}</span><span></span></div>
      <span class="badge ${badgeClass}">${escapeHtml(stem.source)}</span>
      <span class="badge neutral">${escapeHtml(stem.status)}</span>
      <span class="badge neutral">${escapeHtml(stem.problems)}</span>
      <div class="stem-actions"><button class="play-button" title="Escuchar en REAPER">▶</button><button class="icon-button">⋮</button></div>`;
    row.querySelector('.stem-name span:last-child').textContent = stem.name;
    list.appendChild(row);
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

async function loadProjects(preferredName = '') {
  const result = await api('/api/projects');
  const projects = result.projects.filter(project => !project.error);
  const selected = projects.find(project => project.name === preferredName) || projects[0];
  if (selected) renderProject(selected);
  else {
    $('#project-title').textContent = 'Creá tu primera canción';
    $('#project-bpm').textContent = '— BPM';
    $('#project-source').textContent = 'Origen: —';
    $('#timeline').innerHTML = '<div class="empty-state">La estructura aparecerá aquí.</div>';
    $('#stem-list').innerHTML = '<div class="empty-state">Cargá stems desde “Nueva canción”.</div>';
  }
}

function addMessage(role, content, pending = false) {
  const article = document.createElement('article');
  article.className = `message ${role === 'user' ? 'user-message' : 'assistant-message'}${pending ? ' pending' : ''}`;
  const paragraph = document.createElement('p');
  paragraph.textContent = content;
  article.appendChild(paragraph);
  $('#messages').appendChild(article);
  $('#messages').scrollTop = $('#messages').scrollHeight;
  return article;
}

function renderProposal(proposal) {
  state.proposal = proposal;
  const container = $('#proposal-card');
  if (!proposal) { container.innerHTML = ''; return; }
  const changes = proposal.changes?.length || 0;
  container.innerHTML = `
    <section class="proposal-card">
      <h3>◉ ${escapeHtml(proposal.title || 'Propuesta pendiente')}</h3>
      <p>${changes} ajuste${changes === 1 ? '' : 's'} sugerido${changes === 1 ? '' : 's'} · requiere aprobación</p>
      <div class="proposal-actions">
        <button data-decision="preview">◉ Previsualizar</button>
        <button class="apply" data-decision="apply">✓ Aplicar</button>
        <button class="reject" data-decision="reject">× Rechazar</button>
      </div>
    </section>`;
  container.querySelectorAll('[data-decision]').forEach(button => button.addEventListener('click', () => decideProposal(button.dataset.decision)));
}

async function decideProposal(decision) {
  if (!state.proposal?.proposal_id) return;
  try {
    const result = await api(`/api/proposals/${state.proposal.proposal_id}/decision`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({decision})
    });
    if (decision === 'preview') {
      const detail = (result.changes || []).map(change => `${change.target}: ${change.action}`).join('\n');
      addMessage('assistant', `${result.summary || result.title}\n\n${detail}`);
    } else if (decision === 'apply') {
      addMessage('assistant', result.message || 'La acción no fue aplicada.');
      toast('REAPER no fue modificado: falta el mapeo determinista.');
    } else {
      renderProposal(null);
      toast('Propuesta rechazada.');
    }
  } catch (error) { toast(error.message); }
}

$('#chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('#chat-input');
  const message = input.value.trim();
  if (!message || !state.project) return;
  addMessage('user', message);
  input.value = '';
  const pending = addMessage('assistant', 'Pensando…', true);
  const slowNotice = window.setTimeout(() => {
    if (pending.isConnected) pending.querySelector('p').textContent = 'Gemma está procesando el contexto del proyecto…';
  }, 12000);
  try {
    const result = await api('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project_name: state.project.name, message, history: state.history.slice(-8), conversation_id: state.conversationId})
    });
    pending.remove();
    window.clearTimeout(slowNotice);
    addMessage('assistant', result.message);
    state.history.push({role: 'user', content: message}, {role: 'assistant', content: result.message});
    renderProposal(result.proposal);
  } catch (error) {
    pending.remove();
    window.clearTimeout(slowNotice);
    const detail = /timed out|timeout/i.test(error.message)
      ? 'El modelo tardó más que el límite configurado. Aumentalo en Configuración o probá un modelo más rápido.'
      : error.message;
    addMessage('assistant', `No pude completar la consulta: ${detail}`);
  }
});

$('#chat-input').addEventListener('keydown', event => {
  if (
    event.key === 'Enter'
    && !event.shiftKey
    && !event.isComposing
  ) {
    event.preventDefault();
    $('#chat-form').requestSubmit();
  }
});

$('#chat-input').addEventListener('input', event => {
  const input = event.currentTarget;
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
});

$('#analyze-project').addEventListener('click', () => {
  if (!state.project) return;
  $('#chat-input').value = 'Analizá los stems del proyecto y proponé el próximo paso más útil.';
  $('#chat-form').requestSubmit();
});

const settingsDialog = $('#settings-dialog');
$('#open-settings').addEventListener('click', () => settingsDialog.showModal());
$('#brain-status').addEventListener('click', () => settingsDialog.showModal());
$('#settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  const resultElement = $('#settings-result');
  resultElement.textContent = 'Probando conexión…';
  const token = $('#brain-token').value;
  try {
    const result = await api('/api/settings/brain', {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({base_url: $('#brain-url').value, model: $('#brain-model').value, token: token || null, authentication_required: $('#brain-auth').value === 'true', timeout_seconds: Number($('#brain-timeout').value)})
    });
    $('#brain-token').value = '';
    resultElement.textContent = result.status.connected ? 'Conexión correcta.' : `Configuración guardada: ${result.status.error}`;
    await refreshStatus();
    if (result.status.connected) window.setTimeout(() => settingsDialog.close(), 700);
  } catch (error) { resultElement.textContent = error.message; }
});

const newSongDialog = $('#new-song-dialog');
$('#open-new-song').addEventListener('click', () => newSongDialog.showModal());
$('#new-song-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const resultElement = $('#new-song-result');
  const progress = $('#upload-progress');
  progress.classList.remove('hidden');
  resultElement.textContent = 'Cargando y organizando archivos…';
  try {
    const result = await api('/api/projects', {method: 'POST', body: new FormData(form)});
    renderProject(result);
    form.reset();
    resultElement.textContent = 'Canción creada.';
    window.setTimeout(() => newSongDialog.close(), 650);
    toast('Canción creada y lista para analizar.');
  } catch (error) { resultElement.textContent = error.message; }
  finally { progress.classList.add('hidden'); }
});

document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));
document.querySelectorAll('.nav-item[data-view]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  toast('Esta vista se habilitará en la siguiente iteración.');
}));

async function loadSettings() {
  try {
    const settings = await api('/api/settings/brain');
    $('#brain-url').value = settings.base_url;
    $('#brain-model').value = settings.model;
    $('#brain-auth').value = settings.authentication_required ? 'true' : 'false';
    $('#brain-timeout').value = String(settings.timeout_seconds || 180);
  } catch { /* defaults remain visible */ }
}

Promise.all([loadSettings(), refreshStatus(), loadProjects()]).catch(error => toast(error.message));
window.setInterval(refreshStatus, 30000);
