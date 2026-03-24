// State
let state = 'idle'; // idle, recording, transcribing, loading, setup, load_error
let timerInterval = null;
let timerSeconds = 0;

// Elements
const recordBtn = document.getElementById('record-btn');
const micIcon = document.getElementById('mic-icon');
const stopIcon = document.getElementById('stop-icon');
const timer = document.getElementById('timer');
const recordLabel = document.getElementById('record-label');
const statusBadge = document.getElementById('status-badge');
const micSelect = document.getElementById('mic-select');
const hotkeyText = document.getElementById('hotkey-text');
const hotkeyEditBtn = document.getElementById('hotkey-edit-btn');
const hotkeyModal = document.getElementById('hotkey-modal');
const hotkeyPreset = document.getElementById('hotkey-preset');
const hotkeySave = document.getElementById('hotkey-save');
const hotkeyCancel = document.getElementById('hotkey-cancel');
const autopasteToggle = document.getElementById('autopaste-toggle');
const llmCleanupToggle = document.getElementById('llm-cleanup-toggle');
const openFolderBtn = document.getElementById('open-folder-btn');
const llmProviderSelect = document.getElementById('llm-provider-select');
const openrouterSettings = document.getElementById('openrouter-settings');
const openrouterKeyInput = document.getElementById('openrouter-key');
const openrouterModelInput = document.getElementById('openrouter-model');
const historyList = document.getElementById('history-list');
const setupScreen = document.getElementById('setup-screen');
const setupLocalBtn = document.getElementById('setup-local');
const setupCloudBtn = document.getElementById('setup-cloud');
const downloadScreen = document.getElementById('download-screen');
const downloadStatus = document.getElementById('download-status');
const downloadDetail = document.getElementById('download-detail');
const downloadSpeed = document.getElementById('download-speed');
const progressBar = document.getElementById('progress-bar');
const downloadError = document.getElementById('download-error');
const downloadActions = document.getElementById('download-actions');
const retryLoadBtn = document.getElementById('retry-load-btn');
const resetSetupBtn = document.getElementById('reset-setup-btn');
const logPreview = document.getElementById('log-preview');
const viewLogsBtn = document.getElementById('view-logs-btn');
const logsModal = document.getElementById('logs-modal');
const logsContent = document.getElementById('logs-content');
const logsPath = document.getElementById('logs-path');
const logsOpenFile = document.getElementById('logs-open-file');
const logsRefresh = document.getElementById('logs-refresh');
const logsClose = document.getElementById('logs-close');

// Format hotkey for display
function formatHotkey(raw) {
  return raw
    .replace(/<cmd>/g, 'Cmd')
    .replace(/<shift>/g, 'Shift')
    .replace(/<ctrl>/g, 'Ctrl')
    .replace(/<alt>/g, 'Alt')
    .replace(/<space>/g, 'Space')
    .replace(/<f(\d+)>/g, 'F$1')
    .replace(/\+/g, ' + ');
}

// Format ETA
function formatEta(seconds) {
  if (seconds <= 0) return '';
  if (seconds < 60) return `~${seconds}s remaining`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `~${m}m ${s}s remaining`;
}

// Format elapsed time
function formatElapsed(seconds) {
  if (seconds <= 0) return '0s';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

// Timer
function startTimer() {
  timerSeconds = 0;
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    timerSeconds++;
    updateTimerDisplay();
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
}

function updateTimerDisplay() {
  const m = Math.floor(timerSeconds / 60).toString().padStart(2, '0');
  const s = (timerSeconds % 60).toString().padStart(2, '0');
  timer.textContent = `${m}:${s}`;
}

// State updates
function setState(newState) {
  state = newState;

  // Hide error/action elements by default
  downloadError.classList.add('hidden');
  downloadActions.classList.add('hidden');

  switch (state) {
    case 'setup':
      setupScreen.classList.remove('hidden');
      downloadScreen.classList.add('hidden');
      recordBtn.disabled = true;
      break;

    case 'downloading':
      setupScreen.classList.add('hidden');
      statusBadge.textContent = 'Downloading...';
      statusBadge.className = 'badge badge-loading';
      recordBtn.disabled = true;
      recordLabel.textContent = 'Downloading model...';
      downloadScreen.classList.remove('hidden');
      progressBar.classList.remove('indeterminate');
      startStatusPolling();
      break;

    case 'loading':
      setupScreen.classList.add('hidden');
      statusBadge.textContent = 'Loading model...';
      statusBadge.className = 'badge badge-loading';
      recordBtn.disabled = true;
      recordLabel.textContent = 'Loading model...';
      downloadScreen.classList.remove('hidden');
      downloadStatus.textContent = 'Loading model into memory...';
      progressBar.classList.add('indeterminate');
      progressBar.style.width = '30%';
      downloadDetail.textContent = 'This may take a minute on first launch';
      downloadSpeed.textContent = '';
      startStatusPolling();
      break;

    case 'load_error':
      setupScreen.classList.add('hidden');
      statusBadge.textContent = 'Error';
      statusBadge.className = 'badge badge-loading';
      recordBtn.disabled = true;
      recordLabel.textContent = 'Model failed to load';
      downloadScreen.classList.remove('hidden');
      downloadStatus.textContent = 'Failed to load model';
      progressBar.classList.remove('indeterminate');
      progressBar.style.width = '0%';
      downloadDetail.textContent = '';
      downloadSpeed.textContent = '';
      downloadActions.classList.remove('hidden');
      startStatusPolling();
      break;

    case 'idle':
      setupScreen.classList.add('hidden');
      statusBadge.textContent = 'Ready';
      statusBadge.className = 'badge badge-ready';
      recordBtn.disabled = false;
      recordBtn.classList.remove('recording');
      micIcon.classList.remove('hidden');
      stopIcon.classList.add('hidden');
      timer.classList.remove('active');
      recordLabel.textContent = 'Press to record';
      stopTimer();
      timer.textContent = '00:00';
      downloadScreen.classList.add('hidden');
      stopStatusPolling();
      break;

    case 'recording':
      statusBadge.textContent = 'Recording';
      statusBadge.className = 'badge badge-recording';
      recordBtn.classList.add('recording');
      micIcon.classList.add('hidden');
      stopIcon.classList.remove('hidden');
      timer.classList.add('active');
      recordLabel.textContent = 'Recording... press to stop';
      startTimer();
      break;

    case 'transcribing':
      statusBadge.textContent = 'Transcribing...';
      statusBadge.className = 'badge badge-transcribing';
      recordBtn.disabled = true;
      recordBtn.classList.remove('recording');
      micIcon.classList.remove('hidden');
      stopIcon.classList.add('hidden');
      timer.classList.remove('active');
      recordLabel.textContent = 'Processing...';
      stopTimer();
      break;
  }
}

// Setup screen handlers
async function handleSetupChoice(provider) {
  await pywebview.api.complete_setup(provider);
  setState('loading');
}

setupLocalBtn.addEventListener('click', () => handleSetupChoice('local'));
setupCloudBtn.addEventListener('click', () => handleSetupChoice('openrouter'));

// Retry / Reset buttons on error screen
retryLoadBtn.addEventListener('click', async () => {
  await pywebview.api.retry_model_load();
  setState('loading');
});

resetSetupBtn.addEventListener('click', async () => {
  await pywebview.api.reset_setup();
  setState('setup');
});

// Record button click
recordBtn.addEventListener('click', async () => {
  if (state === 'idle') {
    console.log('Starting recording...');
    const result = await pywebview.api.start_recording();
    if (result && result.error) {
      showPopup(result.error, true);
      console.error('start_recording error:', result.error);
    } else {
      setState('recording');
    }
  } else if (state === 'recording') {
    setState('transcribing');
    console.log('Stopping recording...');
    try {
      const result = await pywebview.api.stop_recording();
      console.log('stop_recording result:', result);
      if (result && result.text) {
        showPopup('Text copied!');
        await loadHistory();
      } else if (result && result.error) {
        showPopup('Error: ' + result.error, true);
        await loadHistory();
      }
    } catch (e) {
      console.error('stop_recording exception:', e);
      showPopup('Error: ' + e, true);
    }
    setState('idle');
  }
});

// Microphone select
micSelect.addEventListener('change', async () => {
  const deviceId = micSelect.value === 'default' ? null : parseInt(micSelect.value);
  await pywebview.api.set_config('microphone_device_id', deviceId);
});

// Hotkey
hotkeyEditBtn.addEventListener('click', () => {
  hotkeyModal.classList.remove('hidden');
});

hotkeyCancel.addEventListener('click', () => {
  hotkeyModal.classList.add('hidden');
});

hotkeySave.addEventListener('click', async () => {
  const newHotkey = hotkeyPreset.value;
  await pywebview.api.set_config('hotkey', newHotkey);
  hotkeyText.textContent = formatHotkey(newHotkey);
  hotkeyModal.classList.add('hidden');
});

// Auto-paste
autopasteToggle.addEventListener('change', async () => {
  await pywebview.api.set_config('auto_paste', autopasteToggle.checked);
});

// LLM Cleanup toggle
llmCleanupToggle.addEventListener('change', async () => {
  const enabled = llmCleanupToggle.checked;
  await pywebview.api.set_config('llm_cleanup', enabled);
  toggleLlmSettings(enabled);
});

function toggleLlmSettings(cleanupEnabled) {
  const llmSection = document.getElementById('llm-provider-section');
  if (cleanupEnabled) {
    llmSection.classList.remove('hidden');
  } else {
    llmSection.classList.add('hidden');
  }
}

// LLM Provider
llmProviderSelect.addEventListener('change', async () => {
  const provider = llmProviderSelect.value;
  await pywebview.api.set_config('llm_provider', provider);
  toggleOpenrouterSettings(provider);
});

function toggleOpenrouterSettings(provider) {
  if (provider === 'openrouter') {
    openrouterSettings.classList.remove('hidden');
  } else {
    openrouterSettings.classList.add('hidden');
  }
}

// OpenRouter API key
let keyDebounce = null;
openrouterKeyInput.addEventListener('input', () => {
  clearTimeout(keyDebounce);
  keyDebounce = setTimeout(async () => {
    await pywebview.api.set_config('openrouter_api_key', openrouterKeyInput.value.trim());
  }, 500);
});

let modelDebounce = null;
openrouterModelInput.addEventListener('input', () => {
  clearTimeout(modelDebounce);
  modelDebounce = setTimeout(async () => {
    await pywebview.api.set_config('openrouter_model', openrouterModelInput.value.trim());
  }, 500);
});

// Open folder
openFolderBtn.addEventListener('click', async () => {
  await pywebview.api.open_dictations_folder();
});

// Main screen logs button
const mainViewLogsBtn = document.getElementById('main-view-logs-btn');
mainViewLogsBtn.addEventListener('click', async () => {
  logsModal.classList.remove('hidden');
  await refreshLogs();
});

// ── Logs ──
viewLogsBtn.addEventListener('click', async () => {
  logsModal.classList.remove('hidden');
  await refreshLogs();
});

logsClose.addEventListener('click', () => {
  logsModal.classList.add('hidden');
});

logsRefresh.addEventListener('click', async () => {
  await refreshLogs();
});

logsOpenFile.addEventListener('click', async () => {
  await pywebview.api.open_log_file();
});

async function refreshLogs() {
  try {
    const result = await pywebview.api.get_logs(200);
    logsContent.textContent = result.lines.join('');
    logsPath.textContent = result.path;
    logsContent.scrollTop = logsContent.scrollHeight;
  } catch (e) {
    logsContent.textContent = 'Failed to load logs: ' + e;
  }
}

// Live log preview on loading screen (last 3 lines)
async function updateLogPreview() {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    const result = await pywebview.api.get_logs(5);
    if (result.lines && result.lines.length > 0) {
      const last3 = result.lines.slice(-3).map(l => l.trim()).join('\n');
      logPreview.textContent = last3;
    }
  } catch (e) {
    // ignore
  }
}

// History — store data to avoid inline escaping issues
let _historyData = [];

async function loadHistory() {
  const history = await pywebview.api.get_history();
  _historyData = history || [];

  if (_historyData.length === 0) {
    historyList.innerHTML = '<div class="history-empty">No dictations yet</div>';
    return;
  }

  historyList.innerHTML = _historyData.map((item, idx) => {
    const isError = item.status === 'error' || item.status === 'pending';
    const statusDot = item.status === 'ok'
      ? '<span class="status-dot ok" title="Transcribed">&#x25CF;</span>'
      : '<span class="status-dot error" title="Failed">&#x25CF;</span>';

    const retryBtn = isError
      ? `<button class="history-retry" data-action="retry" data-index="${idx}" title="Retry transcription">&#x21BB;</button>`
      : '';

    const copyBtn = item.status === 'ok'
      ? `<button class="history-copy" data-action="copy" data-index="${idx}" title="Copy">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2"/>
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
          </svg>
        </button>`
      : '';

    return `
      <div class="history-item ${isError ? 'history-error' : ''}">
        ${statusDot}
        <span class="history-time">${item.time}</span>
        <span class="history-text">${escapeHtml(item.text)}</span>
        ${retryBtn}
        ${copyBtn}
      </div>
    `;
  }).join('');
}

// Event delegation for history actions
historyList.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const idx = parseInt(btn.dataset.index, 10);
  const item = _historyData[idx];
  if (!item) return;

  if (btn.dataset.action === 'copy') {
    await pywebview.api.copy_text(item.text);
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 1500);
  } else if (btn.dataset.action === 'retry') {
    btn.disabled = true;
    btn.textContent = '...';
    setState('transcribing');
    try {
      const result = await pywebview.api.retry_transcription(item.wav);
      if (result && result.text) {
        showPopup('Transcribed!');
      } else if (result && result.error) {
        showPopup(result.error, true);
      }
    } catch (e) {
      showPopup('Retry failed', true);
    }
    setState('idle');
    await loadHistory();
  }
});

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Popup
function showPopup(msg, isError = false) {
  let popup = document.querySelector('.result-popup');
  if (!popup) {
    popup = document.createElement('div');
    popup.className = 'result-popup';
    document.body.appendChild(popup);
  }
  popup.textContent = msg;
  popup.style.background = isError ? 'var(--red)' : 'var(--green)';
  popup.classList.add('show');
  setTimeout(() => popup.classList.remove('show'), isError ? 4000 : 2000);
}

// Status polling for download/loading screen
let statusPollInterval = null;
let logPreviewCounter = 0;

function startStatusPolling() {
  if (statusPollInterval) return;
  statusPollInterval = setInterval(async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    try {
      const status = await pywebview.api.get_loading_status();
      const elapsed = formatElapsed(status.elapsed_seconds);

      // Check for error FIRST
      if (status.error) {
        downloadStatus.textContent = 'Failed to load model';
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '0%';
        downloadDetail.textContent = '';
        downloadError.textContent = status.error;
        downloadError.classList.remove('hidden');
        downloadActions.classList.remove('hidden');
        downloadSpeed.textContent = `Elapsed: ${elapsed}`;
      } else if (status.ready) {
        downloadStatus.textContent = 'Ready!';
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '100%';
        downloadDetail.textContent = '';
        downloadSpeed.textContent = '';
        downloadError.classList.add('hidden');
        downloadActions.classList.add('hidden');
      } else if (status.downloading) {
        downloadStatus.textContent = status.message;
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = status.progress + '%';
        downloadDetail.textContent = `${status.downloaded_mb} / ${status.total_mb} MB  (${status.progress}%)`;
        const parts = [];
        if (status.speed_mbs > 0) parts.push(`${status.speed_mbs} MB/s`);
        if (status.eta_seconds > 0) parts.push(formatEta(status.eta_seconds));
        parts.push(`Elapsed: ${elapsed}`);
        downloadSpeed.textContent = parts.join('  \u2022  ');
      } else if (status.loading) {
        downloadStatus.textContent = status.message || 'Loading model into memory...';
        progressBar.classList.add('indeterminate');
        progressBar.style.width = '30%';
        downloadDetail.textContent = 'This may take a minute on first launch';
        downloadSpeed.textContent = `Elapsed: ${elapsed}`;
      }

      // Update live log preview every ~3 seconds (every 6th poll at 500ms)
      logPreviewCounter++;
      if (logPreviewCounter % 6 === 0) {
        await updateLogPreview();
      }
    } catch (e) {
      // ignore
    }
  }, 500);
}

function stopStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
  logPreviewCounter = 0;
}

// ── Accessibility permission ──
const accessibilityBanner = document.getElementById('accessibility-banner');
const accessibilityGrantBtn = document.getElementById('accessibility-grant-btn');
const accessibilityResetBtn = document.getElementById('accessibility-reset-btn');
const accessibilityRestartBtn = document.getElementById('accessibility-restart-btn');
const accessibilityHint = document.getElementById('accessibility-hint');
const accessibilityStatus = document.getElementById('accessibility-status');
let accessibilityPollInterval = null;

function showAccessibilityStatus(msg, isSuccess) {
  accessibilityStatus.textContent = msg;
  accessibilityStatus.className = 'accessibility-status ' + (isSuccess ? 'success' : 'error');
  accessibilityStatus.classList.remove('hidden');
}

accessibilityGrantBtn.addEventListener('click', async () => {
  console.log('Grant Access clicked');
  accessibilityGrantBtn.disabled = true;
  accessibilityGrantBtn.textContent = 'Requesting...';
  try {
    const result = await pywebview.api.request_accessibility();
    console.log('request_accessibility result:', result);
    if (result && result.granted) {
      accessibilityBanner.classList.add('hidden');
      showPopup('Hotkeys activated!');
    } else {
      // Show hint, reset button, and restart button
      accessibilityHint.classList.remove('hidden');
      accessibilityResetBtn.classList.remove('hidden');
      accessibilityRestartBtn.classList.remove('hidden');
      showAccessibilityStatus(
        'System Settings should have opened. Enable the toggle for PushkaVoice.', false
      );
      startAccessibilityPoll();
    }
  } catch (e) {
    console.error('request_accessibility error:', e);
  }
  setTimeout(() => {
    accessibilityGrantBtn.disabled = false;
    accessibilityGrantBtn.textContent = 'Grant Access';
  }, 3000);
});

accessibilityResetBtn.addEventListener('click', async () => {
  console.log('Fix After Update clicked');
  accessibilityResetBtn.disabled = true;
  accessibilityResetBtn.textContent = 'Resetting...';
  try {
    // Step 1: Reset stale TCC entries and re-prompt
    const result = await pywebview.api.reset_and_request_accessibility();
    console.log('reset_and_request result:', result);

    if (result && result.granted) {
      accessibilityBanner.classList.add('hidden');
      showPopup('Hotkeys activated!');
      return;
    }

    // Step 2: Open System Settings for manual toggle
    await pywebview.api.open_accessibility_settings();

    showAccessibilityStatus(
      'Old entries cleared! System Settings opened — find PushkaVoice and enable the toggle. Then click "Restart Hotkeys".',
      false
    );
    accessibilityRestartBtn.classList.remove('hidden');
    startAccessibilityPoll();
  } catch (e) {
    console.error('reset error:', e);
    showAccessibilityStatus('Reset failed: ' + e, false);
  }
  setTimeout(() => {
    accessibilityResetBtn.disabled = false;
    accessibilityResetBtn.textContent = 'Fix After Update';
  }, 3000);
});

accessibilityRestartBtn.addEventListener('click', async () => {
  console.log('Restart Hotkeys clicked');
  accessibilityRestartBtn.textContent = 'Restarting...';
  accessibilityRestartBtn.disabled = true;
  try {
    await pywebview.api.restart_hotkey();
    // Wait a moment for CGEventTap creation attempts
    await new Promise(r => setTimeout(r, 3000));
    const result = await pywebview.api.check_accessibility();
    if (result && result.granted && result.hotkey_active) {
      accessibilityBanner.classList.add('hidden');
      showPopup('Hotkeys activated!');
    } else if (result && result.granted && !result.hotkey_active) {
      showAccessibilityStatus(
        'Permission granted but hotkeys still not working. Try: remove PushkaVoice from Accessibility list, re-add it, enable the toggle, then restart the app.', false
      );
    } else {
      showAccessibilityStatus(
        'Still no permission. Try "Fix After Update" or restart the app.', false
      );
    }
  } catch (e) {
    console.error('restart_hotkey error:', e);
  }
  accessibilityRestartBtn.textContent = 'Restart Hotkeys';
  accessibilityRestartBtn.disabled = false;
});

function startAccessibilityPoll() {
  if (accessibilityPollInterval) return;
  console.log('Starting accessibility poll');
  accessibilityPollInterval = setInterval(async () => {
    try {
      const result = await pywebview.api.check_accessibility();
      if (result && result.granted && result.hotkey_active) {
        accessibilityBanner.classList.add('hidden');
        clearInterval(accessibilityPollInterval);
        accessibilityPollInterval = null;
        console.log('Accessibility granted and hotkeys active, banner hidden');
        showPopup('Hotkeys activated!');
      } else if (result && result.granted && !result.hotkey_active) {
        // Permission OK but CGEventTap failed — need app restart
        showAccessibilityStatus(
          'Permission granted! Restart the app for hotkeys to work.', false
        );
      }
    } catch (e) { console.error('accessibility poll error:', e); }
  }, 2000);
}

async function checkAccessibility() {
  try {
    const result = await pywebview.api.check_accessibility();
    console.log('checkAccessibility result:', result);
    if (result && !result.granted) {
      accessibilityBanner.classList.remove('hidden');
      // Auto-prompt on first launch
      await pywebview.api.request_accessibility();
      // Show the fix button right away — users who updated will need it
      accessibilityResetBtn.classList.remove('hidden');
      startAccessibilityPoll();
    } else if (result && result.granted && !result.hotkey_active) {
      // Permission OK but CGEventTap didn't create — show banner with restart hint
      accessibilityBanner.classList.remove('hidden');
      accessibilityRestartBtn.classList.remove('hidden');
      accessibilityResetBtn.classList.remove('hidden');
      showAccessibilityStatus(
        'Permission granted but hotkeys not active. Try "Restart Hotkeys" or restart the app.', false
      );
    } else {
      accessibilityBanner.classList.add('hidden');
    }
  } catch (e) {
    console.error('checkAccessibility error:', e);
    accessibilityBanner.classList.add('hidden');
  }
}

// ── Updates ──
const versionLabel = document.getElementById('version-label');
const checkUpdateBtn = document.getElementById('check-update-btn');
const updateInfo = document.getElementById('update-info');
const updateAvailable = document.getElementById('update-available');
const updateTag = document.getElementById('update-tag');
const installUpdateBtn = document.getElementById('install-update-btn');
const updateProgress = document.getElementById('update-progress');
const updateProgressBar = document.getElementById('update-progress-bar');
const updateStatusText = document.getElementById('update-status-text');
const updateDone = document.getElementById('update-done');
const restartAppBtn = document.getElementById('restart-app-btn');
const updateError = document.getElementById('update-error');

let pendingDownloadUrl = null;
let updatePollInterval = null;

checkUpdateBtn.addEventListener('click', async () => {
  checkUpdateBtn.disabled = true;
  checkUpdateBtn.textContent = 'Checking...';
  updateInfo.classList.remove('hidden');
  updateAvailable.classList.add('hidden');
  updateProgress.classList.add('hidden');
  updateDone.classList.add('hidden');
  updateError.classList.add('hidden');

  try {
    const result = await pywebview.api.check_for_update();
    if (result.error) {
      updateError.textContent = result.error;
      updateError.classList.remove('hidden');
    } else if (result.available) {
      updateTag.textContent = `New version: ${result.tag}`;
      pendingDownloadUrl = result.download_url;
      updateAvailable.classList.remove('hidden');
    } else {
      updateError.textContent = 'You are on the latest version.';
      updateError.classList.remove('hidden');
      updateError.style.color = 'var(--green)';
      updateError.style.background = 'rgba(34, 197, 94, 0.1)';
    }
  } catch (e) {
    updateError.textContent = 'Check failed: ' + e;
    updateError.classList.remove('hidden');
  }
  checkUpdateBtn.disabled = false;
  checkUpdateBtn.textContent = 'Check for Updates';
});

installUpdateBtn.addEventListener('click', async () => {
  if (!pendingDownloadUrl) return;
  installUpdateBtn.disabled = true;
  updateAvailable.classList.add('hidden');
  updateProgress.classList.remove('hidden');
  updateStatusText.textContent = 'Starting download...';
  updateProgressBar.style.width = '0%';

  await pywebview.api.start_update(pendingDownloadUrl);
  startUpdatePoll();
});

function startUpdatePoll() {
  if (updatePollInterval) return;
  updatePollInterval = setInterval(async () => {
    try {
      const s = await pywebview.api.get_update_status();
      updateProgressBar.style.width = s.progress + '%';
      updateStatusText.textContent = s.status;

      if (s.done) {
        clearInterval(updatePollInterval);
        updatePollInterval = null;
        updateProgress.classList.add('hidden');
        updateDone.classList.remove('hidden');
      } else if (s.error) {
        clearInterval(updatePollInterval);
        updatePollInterval = null;
        updateProgress.classList.add('hidden');
        updateError.textContent = s.error;
        updateError.classList.remove('hidden');
        updateError.style.color = '';
        updateError.style.background = '';
      }
    } catch (e) {
      // ignore
    }
  }, 500);
}

restartAppBtn.addEventListener('click', async () => {
  restartAppBtn.disabled = true;
  restartAppBtn.textContent = 'Restarting...';
  try {
    await pywebview.api.restart_app();
  } catch (e) {
    // App may exit before response
  }
});

// Init
let initialized = false;
async function init() {
  if (initialized) return;
  initialized = true;

  // Check if setup is needed
  const setupComplete = await pywebview.api.is_setup_complete();
  if (!setupComplete) {
    setState('setup');
  } else {
    setState('loading');
  }

  // Check accessibility permission (shows banner if needed)
  await checkAccessibility();

  // Show version
  try {
    const ver = await pywebview.api.get_version();
    versionLabel.textContent = `v${ver.version}` + (ver.build > 0 ? ` (build ${ver.build})` : ' (dev)');
  } catch (e) { /* ignore */ }

  // Load config
  const config = await pywebview.api.get_config();
  hotkeyText.textContent = formatHotkey(config.hotkey);
  autopasteToggle.checked = config.auto_paste;
  hotkeyPreset.value = config.hotkey;

  // Load LLM cleanup setting
  const llmCleanup = config.llm_cleanup !== false;  // default true
  llmCleanupToggle.checked = llmCleanup;
  toggleLlmSettings(llmCleanup);

  // Load LLM provider settings
  const provider = config.llm_provider || 'local';
  llmProviderSelect.value = provider;
  toggleOpenrouterSettings(provider);
  openrouterKeyInput.value = config.openrouter_api_key || '';
  openrouterModelInput.value = config.openrouter_model || 'google/gemma-3-4b-it:free';

  // Load devices
  try {
    const devices = await pywebview.api.get_devices();
    micSelect.innerHTML = '<option value="default">System Default</option>';
    devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.id;
      opt.textContent = d.name;
      if (config.microphone_device_id === d.id) opt.selected = true;
      micSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load devices:', e);
  }

  // Load history
  await loadHistory();

  // Poll backend state (model loading + hotkey-triggered recordings)
  setInterval(async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    try {
      const backendState = await pywebview.api.get_state();
      if (backendState !== state && state !== 'setup') {
        if (backendState === 'idle' && (state === 'transcribing' || state === 'loading')) {
          await loadHistory();
        }
        setState(backendState);
      }
    } catch (e) {
      // ignore errors during polling
    }
  }, 500);
}

// Use pywebviewready event
window.addEventListener('pywebviewready', () => {
  console.log('pywebviewready fired');
  init();
});
// Fallback: if pywebview is already ready
window.addEventListener('load', () => {
  if (window.pywebview && window.pywebview.api) {
    console.log('pywebview already ready on load');
    init();
  }
});
