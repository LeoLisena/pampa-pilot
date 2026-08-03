const state = { project: null, history: [], proposal: null, conversationId: null, selectedStem: null, chain: null, filterProposal: null, filterBinding: null, undo: null };
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
  (project.stems || []).forEach(stem => {
    const row = document.createElement('div');
    row.className = 'stem-row';
    const badgeClass = stem.source === 'Suno' ? 'amber' : stem.source === 'Sin clasificar' ? 'neutral' : '';
    const role = stem.role || 'other';
    row.innerHTML = `
      <div class="stem-name"><span class="stem-icon role-${escapeHtml(role)}">${instrumentIcon(role)}</span><span></span></div>
      <span class="badge ${badgeClass}">${escapeHtml(stem.source)}</span>
      <span class="badge ${stem.status === 'Analizado' ? '' : 'neutral'}">${escapeHtml(stem.status)}</span>
      <span class="badge ${stem.problems === 'Sin problemas detectados' ? '' : 'neutral'}">${escapeHtml(stem.problems)}</span>
      <div class="stem-actions"><button class="play-button" title="Abrir controles de producción">▶</button><button class="icon-button" title="Abrir controles">⋮</button></div>`;
    row.querySelector('.stem-name span:last-child').textContent = stem.name;
    row.querySelectorAll('.stem-actions button').forEach(button => button.addEventListener('click', () => openStemTools(stem)));
    list.appendChild(row);
  });
  const banner = $('#analysis-banner');
  const bannerTitle = banner.querySelector('strong');
  const bannerText = banner.querySelector('p');
  const detailsButton = $('#analysis-details');
  if (project.analysis) {
    const counts = project.analysis.summary?.finding_counts_by_severity || {};
    const findingCount = Object.values(counts).reduce((total, value) => total + Number(value || 0), 0);
    bannerTitle.textContent = 'Análisis técnico completado.';
    bannerText.textContent = `${project.analysis.summary?.stem_count || project.stems?.length || 0} stems medidos · ${findingCount} hallazgo${findingCount === 1 ? '' : 's'} para revisar · ninguna acción aplicada.`;
    detailsButton.disabled = false;
  } else {
    bannerTitle.textContent = 'Proyecto cargado.';
    bannerText.textContent = 'Los datos técnicos aparecerán aquí después del análisis.';
    detailsButton.disabled = true;
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function instrumentIcon(role) {
  const paths = {
    lead_vocal: '<circle cx="12" cy="8" r="4"/><path d="M7 8v1a5 5 0 0 0 10 0V8M12 14v6M8 20h8"/>',
    backing_vocals: '<circle cx="8" cy="8" r="2.5"/><circle cx="16" cy="8" r="2.5"/><path d="M3.5 18c.3-3 2-5 4.5-5s4.2 2 4.5 5M11.5 18c.3-3 2-5 4.5-5s4.2 2 4.5 5"/>',
    choir: '<circle cx="6" cy="8" r="2"/><circle cx="12" cy="6.5" r="2.5"/><circle cx="18" cy="8" r="2"/><path d="M2.5 18c.3-3 1.5-5 3.5-5 1.2 0 2.2.7 2.8 1.8M7.5 19c.3-4 1.8-6 4.5-6s4.2 2 4.5 6M15.2 14.8c.6-1.1 1.6-1.8 2.8-1.8 2 0 3.2 2 3.5 5"/>',
    guitar: '<path d="M14.5 4.5 20 2l2 2-2.5 5.5M14.5 4.5l5 5M15.5 8.5l-5 5M9.5 12.5c-2.4-1.3-5-.8-6.3 1.2-1.6 2.5.1 6.2 3.2 6.8 2.6.5 5-1.5 5.1-4.2 2.7-.1 4.7-2.5 4.2-5.1-.2-1.1-.7-2-1.2-2.7Z"/><circle cx="9" cy="15" r="1.5"/>',
    bass: '<path d="M15 4 20 2l2 2-3 5M15 4l4 5M15.5 8.5l-5 5M9.5 12.5c-2.4-1.2-5-.7-6.2 1.4-1.4 2.5.3 6 3.3 6.6 2.8.5 5.2-1.8 4.8-4.6 2.3-.3 4-2.3 3.8-4.7-.1-1-.5-2-1-2.7Z"/><path d="m8 14 3 3"/>',
    drums: '<ellipse cx="12" cy="15" rx="5" ry="6"/><circle cx="6" cy="10" r="3"/><circle cx="18" cy="10" r="3"/><path d="M3 4h6M6 4v3M15 4h6M18 4v3M8 21l-2 2M16 21l2 2"/>',
    percussion: '<path d="m5 4 7 14M12 4 5 18"/><circle cx="5" cy="4" r="2.5"/><circle cx="12" cy="4" r="2.5"/><path d="M15 12h7M18.5 9v6M16 18h5"/>',
    keys: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 5v14M10 5v14M14 5v14M18 5v14M5 5v7h2V5M9 5v7h2V5M17 5v7h2V5"/>',
    synth: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M5 9c2-5 4 5 6 0s4 5 8 0M5 15h14M7 15v5M11 15v5M15 15v5"/>',
    strings: '<path d="M12 2c2 2 2 4 .5 6 2 1.5 3.5 3.5 2.8 6.5-.6 2.8-2.2 5.3-3.3 7.5-1.1-2.2-2.7-4.7-3.3-7.5-.7-3 1-5 2.8-6.5C10 6 10 4 12 2Z"/><path d="M12 2v20M7 10l10 5M17 10 7 15"/>',
    other: '<path d="M2 12h3l2-6 4 12 3-9 3 6 2-3h3"/>'
  };
  const safeRole = Object.hasOwn(paths, role) ? role : 'other';
  return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[safeRole]}</svg>`;
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
  return selected || null;
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
  const applied = proposal.status === 'applied';
  const executable = proposal.executable === true;
  container.innerHTML = `
    <section class="proposal-card">
      <h3>${applied ? '✓' : '◉'} ${escapeHtml(proposal.title || 'Propuesta pendiente')}</h3>
      <p>${changes} ajuste${changes === 1 ? '' : 's'} ${applied ? 'aplicado y verificado' : executable ? 'listo para aplicar' : 'sugerido · requiere mapeo determinista'}</p>
      <div class="proposal-actions">
        <button data-decision="preview">◉ Previsualizar</button>
        ${!applied && executable ? '<button class="apply" data-decision="apply">✓ Aplicar</button>' : ''}
        ${!applied ? '<button class="reject" data-decision="reject">× Rechazar</button>' : ''}
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
      const application = result.application || {};
      addMessage('assistant', application.message || result.message || 'La acción no fue aplicada.');
      if (result.status === 'applied') {
        if (application.transaction_request_id) {
          rememberUndo(application);
        }
        renderProposal(result);
        await refreshStatus();
        toast('Plan aplicado y verificado en REAPER.');
      } else {
        toast('REAPER no fue modificado: falta el mapeo determinista.');
      }
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
    if (result.proposal?.status === 'applied') {
      const application = result.proposal.application || {};
      if (application.transaction_request_id) rememberUndo(application);
      toast('Acciones del chat aplicadas automáticamente y verificadas.');
    }
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

$('#analyze-project').addEventListener('click', async event => {
  if (!state.project) return;
  const button = event.currentTarget;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Midiendo stems…';
  toast('Analizando los WAV sin modificar REAPER…');
  try {
    const result = await api(`/api/projects/${encodeURIComponent(state.project.name)}/analysis`, {method: 'POST'});
    renderProject(result.project);
    $('#chat-input').value = 'Interpretá el diagnóstico técnico recién generado y proponé el próximo paso más útil, sin aplicar cambios todavía.';
    $('#chat-form').requestSubmit();
  } catch (error) {
    addMessage('assistant', `No pude analizar el proyecto: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

function metric(value, unit = '') {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)}${unit}` : '—';
}

function sourceKindLabel(value) {
  return ({suno_stems: 'Suno', organic_multitrack: 'Orgánico', unknown: 'Sin clasificar', mixed: 'Suno + orgánico'})[value] || 'Sin clasificar';
}

function findingCopy(finding) {
  const copies = {
    'signal.clipping': ['Clipping detectado', 'El stem contiene muestras al límite digital.', 'Revisar el archivo fuente y preferir una reexportación limpia.'],
    'signal.dc_offset': ['Desplazamiento de continua', 'El stem presenta un nivel de continua que puede consumir headroom.', 'Probar un filtro de eliminación de DC y verificar el render.'],
    'stereo.negative_correlation': ['Posible incompatibilidad mono', 'La correlación estéreo negativa puede provocar pérdida de energía o cambios de timbre al pasar a mono.', 'Comparar en mono antes de reducir o modificar el ancho estéreo.'],
    'dynamics.wide_organic_performance': ['Dinámica amplia', 'La interpretación orgánica presenta una variación dinámica considerable.', 'Evaluar automatización o compresión suave mediante una comparación A/B.'],
    'dynamics.already_controlled_suno': ['Dinámica ya controlada', 'La dinámica estrecha es compatible con procesamiento previo de Suno.', 'No agregar compresión por rutina.'],
    'spectrum.vocal_low_frequency_candidate': ['Graves en la voz', 'La voz concentra energía grave que conviene revisar en contexto.', 'Escuchar un recorte suave y compararlo en A/B.'],
    'spectrum.vocal_sibilance_candidate': ['Sibilancia candidata', 'La voz concentra energía intermitente en la banda de sibilancia.', 'Escuchar las eses y evaluar un de-esser suave sólo si molestan.'],
    'spectrum.low_end_concentration_candidate': ['Concentración de graves', 'Un stem que no es bajo concentra una proporción elevada de energía grave.', 'Revisar posible solapamiento con bajo y bombo antes de ecualizar.'],
    'spectrum.presence_concentration_candidate': ['Concentración de presencia', 'El stem concentra energía en la zona de presencia.', 'Escuchar dureza o competencia con la voz antes de ecualizar.'],
    'capture.quiet_floor_candidate': ['Piso en pasajes silenciosos', 'Los pasajes tranquilos de esta toma orgánica conservan señal residual.', 'Escuchar pausas y respiraciones antes de decidir limpieza o puerta.']
  };
  return copies[finding.id] || [finding.id, finding.observation || 'Hallazgo técnico para revisar.', finding.suggested_action || 'Verificar mediante escucha y A/B.'];
}

function renderAnalysisDetails() {
  const analysis = state.project?.analysis;
  const content = $('#analysis-detail-content');
  if (!analysis) {
    content.innerHTML = '<div class="empty-state">Todavía no hay un análisis vigente.</div>';
    return;
  }
  const stemCards = (analysis.stems || []).map(stem => {
    const observations = stem.observations || {};
    const findings = stem.findings || [];
    const findingMarkup = findings.length
      ? `<ul>${findings.map(item => { const copy = findingCopy(item); return `<li><strong>${escapeHtml(copy[0])}</strong><span>${escapeHtml(copy[1])}</span><small>${escapeHtml(copy[2])}</small></li>`; }).join('')}</ul>`
      : '<p class="no-findings">Sin problemas objetivos detectados por las reglas actuales.</p>';
    return `<article class="analysis-stem-card">
      <div class="analysis-stem-heading"><h3>${escapeHtml(stem.track_name || stem.name)}</h3><span class="badge">${escapeHtml(sourceKindLabel(stem.source_kind))}</span></div>
      <div class="metric-grid">
        <span><small>LUFS integrado</small><strong>${metric(observations.integrated_lufs, ' LUFS')}</strong></span>
        <span><small>Pico</small><strong>${metric(observations.sample_peak_dbfs, ' dBFS')}</strong></span>
        <span><small>Factor de cresta</small><strong>${metric(observations.crest_factor_db, ' dB')}</strong></span>
        <span><small>Correlación estéreo</small><strong>${metric(observations.stereo_correlation)}</strong></span>
      </div>
      <div class="finding-list">${findingMarkup}</div>
    </article>`;
  }).join('');
  content.innerHTML = `<p class="analysis-safety">Análisis offline de señal. No modifica REAPER y no reemplaza la escucha humana.</p><div class="analysis-stem-list">${stemCards}</div>`;
}

const stemToolsDialog = $('#stem-tools-dialog');

function normalizedTrackName(value) {
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/^\s*\d+[\s._-]*/, '').replace(/[^a-z0-9]/g, '');
}

function processorLabel(value) {
  return ({reagate: 'Puerta · ReaGate', reaeq: 'Ecualización · ReaEQ', reacomp: 'Compresión · ReaComp', deesser: 'De-esser · ReaXcomp', dynamic_resonance: 'Resonancia dinámica · ReaXcomp', waveshaper: 'Saturación'})[value] || value;
}

function reasonLabel(value) {
  const translated = {
    'Measured quiet passages support a conservative threshold hypothesis.': 'Los pasajes silenciosos medidos justifican probar un umbral conservador.',
    'A time-varying spectral prominence supports a broad-band ReaXcomp audition.': 'Una prominencia espectral variable justifica probar un control dinámico amplio.',
    'Intermittent 5-10 kHz peaks support a high-band compression audition.': 'Los picos intermitentes entre 5 y 10 kHz justifican probar un de-esser suave.'
  };
  return translated[value] || value || 'Punto de partida para escuchar en contexto.';
}

async function openStemTools(stem) {
  state.selectedStem = stem;
  state.chain = null;
  state.filterProposal = null;
  state.filterBinding = null;
  $('#stem-tools-title').textContent = stem.name;
  $('#stem-source-kind').value = ['suno_stems', 'organic_multitrack', 'unknown'].includes(stem.source_kind) ? stem.source_kind : 'unknown';
  $('#stem-volume').value = '';
  $('#stem-pan').value = '';
  $('#stem-muted').value = '';
  $('#include-saturation').checked = false;
  $('#chain-preview').innerHTML = '<p class="analysis-safety">Todavía no se generó una propuesta.</p>';
  $('#filter-preview').innerHTML = '<p class="analysis-safety">Elegí un filtro para analizar esta pista.</p>';
  $('#filter-binding-field').classList.add('hidden');
  $('#apply-filter').disabled = true;
  $('#apply-chain').disabled = true;
  $('#stem-tools-result').textContent = '';
  $('#stem-reaper-binding').textContent = 'Consultando el proyecto abierto en REAPER…';
  stemToolsDialog.showModal();
  stemToolsDialog.querySelector('.modal-card').scrollTop = 0;
  try {
    const reply = await api('/api/reaper/project');
    const wanted = new Set([stem.name, stem.track_name].map(normalizedTrackName));
    const matches = (reply.result?.tracks || []).filter(track => wanted.has(normalizedTrackName(track.name)));
    if (matches.length !== 1) throw new Error('No se encontró una coincidencia única');
    const track = matches[0];
    state.selectedStem.reaperTrack = track;
    state.selectedStem.projectRef = reply.result.project_ref;
    $('#stem-volume').value = Number(track.volume_db || 0).toFixed(1);
    $('#stem-pan').value = Math.round(Number(track.pan || 0) * 100);
    $('#stem-muted').value = String(Boolean(track.muted));
    $('#toggle-solo').textContent = Number(track.solo || 0) > 0 ? 'Desactivar Solo' : 'Activar Solo';
    $('#stem-reaper-binding').className = 'tool-status connected';
    $('#stem-reaper-binding').textContent = `Vinculada con REAPER: ${track.name} · ${track.fx_count} FX · los cambios tendrán Undo`;
  } catch (error) {
    delete state.selectedStem.reaperTrack;
    $('#stem-reaper-binding').className = 'tool-status offline';
    $('#stem-reaper-binding').textContent = 'REAPER/Bridge no está disponible. Podés clasificar y generar propuestas offline; Aplicar queda bloqueado.';
  }
}

function parameterLabel(key) {
  return ({threshold_db: 'Umbral', ratio: 'Ratio', attack_ms: 'Ataque', release_ms: 'Release', knee_db: 'Knee', rms_ms: 'RMS', highpass_hz: 'Detector HPF', lowpass_hz: 'Detector LPF', frequency_hz: 'Frecuencia', gain_db: 'Ganancia', bandwidth_octaves: 'Ancho', filter_type: 'Tipo', drive_percent: 'Drive', muffle_percent: 'Muffle', output_gain_db: 'Salida', lower_crossover_hz: 'Crossover inferior', upper_crossover_hz: 'Crossover superior', band3_top_frequency_hz: 'Límite superior', preset_name: 'Preset'})[key] || key.replaceAll('_', ' ');
}

function parameterValue(key, value) {
  if (typeof value !== 'number') return String(value);
  const unit = key.endsWith('_db') ? ' dB' : key.endsWith('_ms') ? ' ms' : key.endsWith('_hz') ? ' Hz' : key.endsWith('_percent') ? ' %' : '';
  return `${Number(value.toFixed(2))}${unit}`;
}

$('#preview-filter').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem) return;
  const output = $('#filter-preview');
  output.innerHTML = '<p>Analizando y calculando parámetros…</p>';
  $('#apply-filter').disabled = true;
  $('#filter-binding-field').classList.add('hidden');
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/filters/preview`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stem_name: state.selectedStem.name, source_kind: $('#stem-source-kind').value, filter_type: $('#individual-filter').value, preset_name: $('#reatune-preset').value})});
    state.filterProposal = reply.proposal;
    state.filterBinding = reply.binding;
    const parameters = Object.entries(reply.proposal.parameters || {});
    const parameterMarkup = parameters.length ? `<div class="parameter-grid">${parameters.map(([key, value]) => `<span><small>${escapeHtml(parameterLabel(key))}</small><strong>${escapeHtml(parameterValue(key, value))}</strong></span>`).join('')}</div>` : '<p>No se generaron parámetros aplicables.</p>';
    const decisionCopy = ({not_recommended: 'No recomendado para esta fuente.', insufficient_evidence: 'No hay evidencia suficiente.', classify_source_first: 'Primero clasificá el origen.', audition_only: 'Listo para comparar mediante escucha.'})[reply.proposal.decision] || reply.proposal.decision;
    output.innerHTML = `<h4>${escapeHtml(reply.proposal.title)}</h4><p>${escapeHtml(reasonLabel(reply.proposal.reason))}</p>${parameterMarkup}<p><strong>${escapeHtml(decisionCopy)}</strong></p>`;
    if (reply.binding.status === 'selection_required') {
      const select = $('#filter-binding');
      select.innerHTML = reply.binding.choices.map(item => `<option value="${escapeHtml(item.guid)}">${escapeHtml(item.name)}${item.preset_name ? ` · ${escapeHtml(item.preset_name)}` : ''}</option>`).join('');
      $('#filter-binding-field').classList.remove('hidden');
      output.insertAdjacentHTML('beforeend', `<p>${escapeHtml(reply.binding.reason)}</p>`);
    } else if (reply.binding.status === 'reuse_existing') {
      output.insertAdjacentHTML('beforeend', '<p>Se reutilizará la instancia existente; no se duplicará el FX.</p>');
    } else {
      output.insertAdjacentHTML('beforeend', '<p>Se creará una instancia nueva del FX nativo.</p>');
    }
    $('#apply-filter').disabled = !reply.can_apply;
    $('#stem-tools-result').textContent = reply.can_apply ? 'Filtro listo para tu aprobación.' : 'La propuesta queda sólo como referencia; no se puede aplicar ahora.';
  } catch (error) {
    output.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    $('#stem-tools-result').textContent = 'Este filtro no está disponible para la combinación actual.';
  }
});

$('#individual-filter').addEventListener('change', () => {
  state.filterProposal = null;
  $('#apply-filter').disabled = true;
  $('#filter-preview').innerHTML = '<p class="analysis-safety">Calculá nuevamente los parámetros para este filtro.</p>';
  $('#filter-binding-field').classList.add('hidden');
});

$('#apply-filter').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem || !state.filterProposal) return;
  if (!window.confirm(`Aplicar ${state.filterProposal.title} a ${state.selectedStem.name}?`)) return;
  const selectedGuid = state.filterBinding?.status === 'selection_required' ? $('#filter-binding').value : null;
  $('#stem-tools-result').textContent = 'Aplicando el filtro y verificando sus parámetros…';
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/filters/apply`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stem_name: state.selectedStem.name, source_kind: $('#stem-source-kind').value, filter_type: state.filterProposal.filter_type, preset_name: $('#reatune-preset').value, approved_proposal_id: state.filterProposal.proposal_id, fx_guid: selectedGuid || null})});
    rememberUndo(reply);
    $('#apply-filter').disabled = true;
    $('#stem-tools-result').textContent = `${reply.proposal.title} aplicado y verificado. Podés deshacerlo.`;
  } catch (error) { $('#stem-tools-result').textContent = error.message; }
});

$('#save-stem-source').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem) return;
  const result = $('#stem-tools-result');
  result.textContent = 'Guardando procedencia…';
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/stem-source`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({stem_name: state.selectedStem.name, source_kind: $('#stem-source-kind').value})
    });
    renderProject(reply.project);
    state.selectedStem = reply.project.stems.find(item => item.name === state.selectedStem.name) || state.selectedStem;
    result.textContent = 'Origen guardado. Volvé a analizar para actualizar el diagnóstico.';
  } catch (error) { result.textContent = error.message; }
});

$('#apply-static-mix').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem) return;
  const volumeRaw = $('#stem-volume').value;
  const panRaw = $('#stem-pan').value;
  const mutedRaw = $('#stem-muted').value;
  const payload = {stem_name: state.selectedStem.name};
  if (volumeRaw !== '') payload.volume_db = Number(volumeRaw);
  if (panRaw !== '') payload.pan = Number(panRaw) / 100;
  if (mutedRaw !== '') payload.muted = mutedRaw === 'true';
  if (Object.keys(payload).length === 1) return toast('Ingresá al menos un cambio.');
  if (!window.confirm(`Aplicar en REAPER volumen ${volumeRaw || 'sin cambio'} dB, paneo ${panRaw || 'sin cambio'} y mute ${mutedRaw || 'sin cambio'}?`)) return;
  const result = $('#stem-tools-result');
  result.textContent = 'Aplicando y verificando en REAPER…';
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/static-mix/apply`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    rememberUndo(reply);
    result.textContent = 'Ajuste aplicado y releído correctamente. Podés deshacerlo.';
  } catch (error) { result.textContent = error.message; }
});

$('#toggle-solo').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem) return;
  const currentlySolo = Number(state.selectedStem.reaperTrack?.solo || 0) > 0;
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/static-mix/apply`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stem_name: state.selectedStem.name, solo: !currentlySolo})});
    rememberUndo(reply);
    state.selectedStem.reaperTrack = {...state.selectedStem.reaperTrack, solo: currentlySolo ? 0 : 1};
    $('#toggle-solo').textContent = currentlySolo ? 'Activar Solo' : 'Desactivar Solo';
    $('#stem-tools-result').textContent = 'Solo aplicado y verificado.';
  } catch (error) { $('#stem-tools-result').textContent = error.message; }
});

$('#preview-chain').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem) return;
  const output = $('#chain-preview');
  output.innerHTML = '<p>Analizando el stem…</p>';
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/producer-chain/preview`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stem_name: state.selectedStem.name, source_kind: $('#stem-source-kind').value, include_artistic_saturation: $('#include-saturation').checked})});
    state.chain = reply.chain;
    const steps = reply.chain.steps || [];
    const status = reply.chain.review_status;
    output.innerHTML = steps.length
      ? `<ol>${steps.map(step => `<li><strong>${escapeHtml(processorLabel(step.processor))}</strong><span>${escapeHtml(reasonLabel(step.reason))}</span><small>${escapeHtml(step.binding === 'reuse_existing' ? 'Reutiliza el FX existente' : 'Creará un FX nativo')}</small></li>`).join('')}</ol><p>${reply.reaper_binding ? 'Pista real verificada.' : 'Previsualización offline: abrí REAPER y el Bridge antes de aplicar.'}</p>`
      : `<p>No se recomienda procesamiento rutinario para esta combinación. ${$('#stem-source-kind').value === 'suno_stems' ? 'El stem de Suno ya puede venir procesado.' : 'No se detectó evidencia suficiente.'}</p>`;
    $('#apply-chain').disabled = !reply.can_apply;
    $('#stem-tools-result').textContent = status === 'blocked_existing_fx' ? 'Hay FX existentes ambiguos; PampaPilot no aplicará nada.' : 'Propuesta lista para tu aprobación.';
  } catch (error) { output.innerHTML = `<p>${escapeHtml(error.message)}</p>`; }
});

$('#apply-chain').addEventListener('click', async () => {
  if (!state.project || !state.selectedStem || !state.chain) return;
  if (!window.confirm(`Aplicar ${state.chain.steps.length} procesadores nativos a ${state.selectedStem.name}?`)) return;
  $('#stem-tools-result').textContent = 'Aplicando toda la cadena en una única transacción…';
  try {
    const reply = await api(`/api/projects/${encodeURIComponent(state.project.name)}/producer-chain/apply`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stem_name: state.selectedStem.name, source_kind: $('#stem-source-kind').value, include_artistic_saturation: $('#include-saturation').checked, approved_chain_id: state.chain.chain_id})});
    rememberUndo(reply);
    $('#apply-chain').disabled = true;
    $('#stem-tools-result').textContent = 'Cadena aplicada y cada FX fue verificado en REAPER.';
  } catch (error) { $('#stem-tools-result').textContent = error.message; }
});

function rememberUndo(reply) {
  const projectRef = reply.project_ref || reply.application?.result?.project_ref || state.selectedStem?.projectRef;
  const transactionIds = reply.transaction_request_ids || (reply.transaction_request_id ? [reply.transaction_request_id] : []);
  state.undo = {project_ref: projectRef, transaction_request_ids: transactionIds};
  $('#undo-last').disabled = !(state.undo.project_ref && state.undo.transaction_request_ids.length);
}

$('#undo-last').addEventListener('click', async () => {
  if (!state.undo) return;
  try {
    await api('/api/reaper/undo-plan', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(state.undo)});
    state.undo = null;
    $('#undo-last').disabled = true;
    $('#stem-tools-result').textContent = 'La última acción de PampaPilot fue deshecha.';
  } catch (error) { $('#stem-tools-result').textContent = error.message; }
});

const capabilitiesDialog = $('#capabilities-dialog');
async function openCapabilities() {
  capabilitiesDialog.showModal();
  const result = await api('/api/capabilities');
  const labels = {ready: 'Disponible offline', web_ready: 'Pantalla + chat', chat_ready: 'Disponible por chat', engine_ready: 'Motor listo'};
  $('#capability-list').innerHTML = result.groups.map(group => `<section><h3>${escapeHtml(group.title)}</h3><p>${escapeHtml(group.description)}</p><div>${group.items.map(item => `<span><strong>${escapeHtml(item.title)}</strong><small class="capability-${item.status}">${escapeHtml(labels[item.status] || item.status)}</small></span>`).join('')}</div></section>`).join('');
}

$('#open-capabilities').addEventListener('click', openCapabilities);
$('#open-capabilities-stems').addEventListener('click', openCapabilities);

const activityDialog = $('#activity-dialog');
async function openActivity() {
  activityDialog.showModal();
  const result = await api('/api/activity');
  $('#activity-list').innerHTML = result.items.length ? result.items.map(item => `<article><strong>${escapeHtml(item.summary)}</strong><span>${escapeHtml([item.project, item.target].filter(Boolean).join(' · '))}</span><small>${item.reaper_modified ? 'REAPER modificado y verificado' : 'Sin modificar REAPER'}</small></article>`).join('') : '<div class="empty-state">Todavía no hay acciones en esta sesión.</div>';
}
$('#open-activity').addEventListener('click', openActivity);

const analysisDialog = $('#analysis-dialog');
$('#analysis-details').addEventListener('click', () => {
  renderAnalysisDetails();
  analysisDialog.showModal();
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
      body: JSON.stringify({base_url: $('#brain-url').value, model: $('#brain-model').value, token: token || null, authentication_required: $('#brain-auth').value === 'true', timeout_seconds: Number($('#brain-timeout').value), remember_token: $('#remember-token').checked, approval_mode: $('#approval-mode').value})
    });
    $('#brain-token').value = '';
    resultElement.textContent = result.status.connected ? 'Conexión correcta.' : `Configuración guardada: ${result.status.error}`;
    await refreshStatus();
    if (result.status.connected) window.setTimeout(() => settingsDialog.close(), 700);
  } catch (error) {
    if (error.message === 'La canción ya existe') {
      const title = String(new FormData(form).get('title') || '').trim();
      const selected = await loadProjects(title);
      if (selected?.name === title) {
        form.reset();
        resultElement.textContent = 'La canción ya existía: se abrió sin sobrescribir archivos.';
        toast(`Proyecto existente abierto: ${title}`);
        window.setTimeout(() => newSongDialog.close(), 850);
        return;
      }
    }
    resultElement.textContent = error.message;
  }
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
    const payload = new FormData(form);
    for (const [field, value] of Array.from(payload.entries())) {
      if (value instanceof File && !value.name) payload.delete(field);
    }
    const result = await api('/api/projects', {method: 'POST', body: payload});
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
  if (button.dataset.view === 'home') document.querySelector('.project-column').scrollIntoView({behavior: 'smooth'});
  else if (button.dataset.view === 'songs') $('#open-new-song').click();
  else if (button.dataset.view === 'chat') $('#chat-input').focus();
}));

async function loadSettings() {
  try {
    const settings = await api('/api/settings/brain');
    $('#brain-url').value = settings.base_url;
    $('#brain-model').value = settings.model;
    $('#brain-auth').value = settings.authentication_required ? 'true' : 'false';
    $('#brain-timeout').value = String(settings.timeout_seconds || 180);
    $('#remember-token').checked = Boolean(settings.token_persisted);
    $('#approval-mode').value = settings.approval_mode || 'manual';
  } catch { /* defaults remain visible */ }
}

Promise.all([loadSettings(), refreshStatus(), loadProjects()]).catch(error => toast(error.message));
window.setInterval(refreshStatus, 30000);
