// State
let state = 'idle'; // idle, recording, transcribing, loading
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
const openFolderBtn = document.getElementById('open-folder-btn');
const historyList = document.getElementById('history-list');

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

  switch (state) {
    case 'loading':
      statusBadge.textContent = 'Loading model...';
      statusBadge.className = 'badge badge-loading';
      recordBtn.disabled = true;
      recordLabel.textContent = 'Loading model...';
      break;

    case 'idle':
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

// Record button click
recordBtn.addEventListener('click', async () => {
  if (state === 'idle') {
    await pywebview.api.start_recording();
    setState('recording');
  } else if (state === 'recording') {
    setState('transcribing');
    const result = await pywebview.api.stop_recording();
    if (result && result.text) {
      showPopup('Text copied!');
      await loadHistory();
    } else if (result && result.error) {
      showPopup('Error: ' + result.error, true);
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

// Open folder
openFolderBtn.addEventListener('click', async () => {
  await pywebview.api.open_dictations_folder();
});

// History
async function loadHistory() {
  const history = await pywebview.api.get_history();
  if (!history || history.length === 0) {
    historyList.innerHTML = '<div class="history-empty">No dictations yet</div>';
    return;
  }

  historyList.innerHTML = history.map(item => {
    const isError = item.status === 'error' || item.status === 'pending';
    const statusDot = item.status === 'ok'
      ? '<span class="status-dot ok" title="Transcribed">&#x25CF;</span>'
      : '<span class="status-dot error" title="Failed">&#x25CF;</span>';

    const retryBtn = isError
      ? `<button class="history-retry" onclick="retryItem(this, '${escapeAttr(item.wav)}')" title="Retry transcription">&#x21BB;</button>`
      : '';

    const copyBtn = item.status === 'ok'
      ? `<button class="history-copy" onclick="copyHistoryItem(this, '${escapeAttr(item.text)}')" title="Copy">
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

async function copyHistoryItem(btn, text) {
  await pywebview.api.copy_text(text);
  btn.classList.add('copied');
  setTimeout(() => btn.classList.remove('copied'), 1500);
}

async function retryItem(btn, wavPath) {
  btn.disabled = true;
  btn.textContent = '...';
  setState('transcribing');
  try {
    const result = await pywebview.api.retry_transcription(wavPath);
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

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, ' ');
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

// Init
let initialized = false;
async function init() {
  if (initialized) return;
  initialized = true;

  setState('loading');

  // Load config
  const config = await pywebview.api.get_config();
  hotkeyText.textContent = formatHotkey(config.hotkey);
  autopasteToggle.checked = config.auto_paste;
  hotkeyPreset.value = config.hotkey;

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
      if (backendState !== state) {
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

// Use pywebviewready event — fires after pywebview.api is available
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
