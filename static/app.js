(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $('doodle-form'), scene: $('scene'), objects: $('objects'),
    sceneCount: $('scene-count'), objectsCount: $('objects-count'),
    configStatus: $('config-status'), configLabel: $('config-label'), retry: $('config-retry'),
    setupNote: $('setup-note'), message: $('form-message'), generate: $('generate-button'), generateLabel: $('generate-label'),
    promptDetails: $('prompt-details'), promptState: $('prompt-state'), promptText: $('prompt-text'),
    copyPrompt: $('copy-prompt'), downloadPrompt: $('download-prompt'),
    image: $('doodle-image'), imageLabel: $('image-label'), imageCaption: $('image-caption'),
    paper: $('drawing-paper'), overlay: $('generation-overlay'), model: $('model-label'),
    downloadImage: $('download-image'), downloadImageLabel: $('download-image-label'),
    imageMessage: $('image-message'), toast: $('toast')
  };

  const presets = {
    dog: {
      scene: '傍晚遛狗时，小狗突然追着两片落叶往前跑，我一边握着牵引绳一边跟上。',
      objects: '一个简笔人物、一只四脚小狗、一根牵引绳、两片落叶'
    },
    cat: {
      scene: '我坐在地上读书，小猫趴在摊开的书旁边，把一只前爪轻轻搭在书页上。',
      objects: '一个坐着的简笔人物、一只四脚小猫、一本摊开的书'
    },
    rest: {
      scene: '我坐在椅子上喝热茶，小狗蜷在我的脚边睡着了。我们都没有说话，安静地待在一起。',
      objects: '一个坐着的简笔人物、一只蜷卧的小狗、一把椅子、一只冒热气的茶杯'
    }
  };

  const state = {
    config: null, configReady: false, configLoading: false, configVersion: 0,
    limits: { scene: 600, objects: 300 }, edited: false,
    prompt: '', promptSnapshot: '', promptVersion: 0, promptController: null, promptTimer: null,
    generating: false, generatedImage: null, imageSnapshot: '', downloading: false,
    objectURLs: new Set(), toastTimer: null
  };

  function inputValue() {
    return { scene: elements.scene.value.trim(), objects: elements.objects.value.trim() };
  }

  function snapshot(value = inputValue()) {
    return JSON.stringify(value);
  }

  function validity() {
    const value = inputValue();
    if (!value.scene) return '先写下一个场景，再把它画出来。';
    if (!value.objects) return '请写下画面里需要保留的人物、宠物或物件。';
    if (value.scene.length > state.limits.scene) return `场景最多 ${state.limits.scene} 个字符，请稍微精简一下。`;
    if (value.objects.length > state.limits.objects) return `画面物件最多 ${state.limits.objects} 个字符，请稍微精简一下。`;
    return '';
  }

  function setMessage(message) {
    elements.message.textContent = message || '';
    elements.message.hidden = !message;
  }

  function toast(message) {
    window.clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.hidden = false;
    state.toastTimer = window.setTimeout(() => { elements.toast.hidden = true; }, 3200);
  }

  function updateCounters() {
    for (const name of ['scene', 'objects']) {
      elements[name + 'Count'].textContent = `${elements[name].value.length} / ${state.limits[name]}`;
      elements[name + 'Count'].classList.toggle('is-over', elements[name].value.length > state.limits[name]);
    }
  }

  function updateButtons() {
    const valid = !validity();
    elements.generate.disabled = !state.configReady || !state.config?.configured || !valid || state.generating || state.configLoading;
    elements.generateLabel.textContent = state.generating ? '正在生成…' : state.configLoading ? '正在检查配置…' : state.configReady && state.config?.configured ? '生成这幅小画' : '连接服务后生成';
    const promptReady = !!state.prompt && state.promptSnapshot === snapshot();
    elements.copyPrompt.disabled = !promptReady;
    elements.downloadPrompt.disabled = !promptReady;
    elements.scene.disabled = state.generating;
    elements.objects.disabled = state.generating;
    document.querySelectorAll('.preset-button').forEach((button) => { button.disabled = state.generating; });
    elements.retry.disabled = state.configLoading || state.generating;
    elements.downloadImage.disabled = state.generating || state.downloading;
  }

  function updatePresets() {
    const current = snapshot();
    document.querySelectorAll('.preset-button').forEach((button) => {
      button.setAttribute('aria-pressed', String(current === snapshot(presets[button.dataset.preset])));
    });
  }

  function updateImageCaption() {
    if (!state.generatedImage) {
      elements.imageLabel.textContent = '第二轮 prompt 示例';
      elements.imageCaption.textContent = '这张真实生成的示例供你参考。编辑左侧内容后，点击生成即可画出新场景。';
      return;
    }
    const unchanged = state.imageSnapshot === snapshot();
    elements.imageLabel.textContent = unchanged ? '刚刚生成的小画' : '上次生成结果';
    elements.imageCaption.textContent = unchanged ? '这张小画由你提交的场景生成。可以下载 PNG，也可以改写场景后再画一张。' : '左侧内容已修改，这里仍保留上次的生成结果。点击生成即可画出新场景。';
  }

  async function post(path, body, signal) {
    if (!state.configReady || !state.config?.csrfToken) throw new Error('本地服务尚未连接，请重新检查配置。');
    const response = await fetch(path, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.config.csrfToken },
      body: JSON.stringify(body), signal
    });
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('本地服务返回了无法读取的响应，请检查服务后重试。'); }
    if (!response.ok || typeof result.error === 'string') throw new Error(typeof result.error === 'string' ? result.error : `请求未完成（${response.status}），请重试。`);
    return result;
  }

  function cancelPrompt() {
    window.clearTimeout(state.promptTimer);
    state.promptVersion += 1;
    if (state.promptController) state.promptController.abort();
    state.promptController = null;
  }

  function queuePrompt(immediate = false) {
    cancelPrompt();
    state.prompt = '';
    state.promptSnapshot = '';
    updateButtons();
    if (!state.configReady) {
      elements.promptState.textContent = '等待本地服务';
      elements.promptText.textContent = '请连接本地服务后查看完整提示词。';
      return;
    }
    const error = validity();
    if (error) {
      elements.promptState.textContent = '等待输入';
      elements.promptText.textContent = error;
      return;
    }
    elements.promptState.textContent = '正在更新';
    elements.promptText.textContent = '正在根据当前输入组装提示词…';
    state.promptTimer = window.setTimeout(refreshPrompt, immediate ? 0 : 400);
  }

  async function refreshPrompt() {
    const version = state.promptVersion;
    const value = inputValue();
    const inputSnapshot = snapshot(value);
    const controller = new AbortController();
    state.promptController = controller;
    try {
      const result = await post('/api/prompt', value, controller.signal);
      if (version !== state.promptVersion || inputSnapshot !== snapshot()) return;
      if (typeof result.prompt !== 'string' || !result.prompt.trim()) throw new Error('本地服务没有返回完整提示词，请重试。');
      state.prompt = result.prompt;
      state.promptSnapshot = inputSnapshot;
      elements.promptText.textContent = result.prompt;
      elements.promptState.textContent = '已更新 · 本地预览';
    } catch (error) {
      if (error.name === 'AbortError' || version !== state.promptVersion) return;
      elements.promptState.textContent = '预览暂不可用';
      elements.promptText.textContent = error.message || '暂时无法生成预览，请检查本地服务。';
    } finally {
      if (version === state.promptVersion) {
        state.promptController = null;
        updateButtons();
      }
    }
  }

  async function loadConfig() {
    if (state.generating) return;
    const version = ++state.configVersion;
    cancelPrompt();
    state.configLoading = true;
    state.configReady = false;
    state.config = null;
    state.prompt = '';
    elements.configStatus.classList.remove('is-ready', 'is-error');
    elements.configLabel.textContent = '正在检查服务';
    elements.promptState.textContent = '等待本地服务';
    elements.promptText.textContent = '正在连接本地服务…';
    elements.setupNote.hidden = true;
    setMessage('');
    updateButtons();
    try {
      const response = await fetch('/api/config', { credentials: 'same-origin', cache: 'no-store' });
      const config = await response.json();
      if (version !== state.configVersion) return;
      if (!response.ok || typeof config.csrfToken !== 'string' || !config.csrfToken || typeof config.configured !== 'boolean') throw new Error('无法读取本地服务配置，请确认服务已启动。');
      state.config = config;
      state.configReady = true;
      if (typeof config.defaults?.scene === 'string' && typeof config.defaults?.objects === 'string') {
        presets.dog = { scene: config.defaults.scene, objects: config.defaults.objects };
      }
      for (const name of ['scene', 'objects']) {
        const limit = config.limits?.[name];
        if (Number.isInteger(limit) && limit > 0 && limit <= 10000) state.limits[name] = limit;
        elements[name].maxLength = state.limits[name];
        if (!state.edited && typeof config.defaults?.[name] === 'string') elements[name].value = config.defaults[name];
      }
      elements.configLabel.textContent = config.configured ? '图像服务已就绪' : '尚未连接图像服务';
      elements.configStatus.classList.toggle('is-ready', config.configured);
      elements.setupNote.hidden = config.configured;
      elements.retry.hidden = config.configured;
      elements.model.textContent = config.configured && typeof config.model === 'string' ? `图像模型 · ${config.model}` : '白纸 · 黑色细线';
      updateCounters();
      updatePresets();
      updateImageCaption();
      queuePrompt(true);
    } catch (error) {
      if (version !== state.configVersion) return;
      elements.configLabel.textContent = '本地服务未连接';
      elements.configStatus.classList.add('is-error');
      elements.retry.hidden = false;
      elements.promptState.textContent = '等待本地服务';
      elements.promptText.textContent = '本地服务暂不可用。连接后即可预览提示词。';
      setMessage(error.message || '无法连接本地服务，请检查服务后重新尝试。');
    } finally {
      if (version === state.configVersion) { state.configLoading = false; updateButtons(); }
    }
  }

  function edited() {
    state.edited = true;
    setMessage('');
    updateCounters();
    updatePresets();
    updateImageCaption();
    queuePrompt();
  }

  async function generate(event) {
    event.preventDefault();
    if (state.generating) return;
    const error = validity();
    if (error) { setMessage(error); elements.scene.focus(); return; }
    if (!state.configReady || !state.config?.configured) { setMessage('请先连接图像服务，再生成小画。'); return; }
    const value = inputValue();
    const inputSnapshot = snapshot(value);
    cancelPrompt();
    state.generating = true;
    setMessage('');
    elements.imageMessage.textContent = '';
    elements.overlay.hidden = false;
    elements.paper.setAttribute('aria-busy', 'true');
    elements.promptState.textContent = '正在生成';
    updateButtons();
    try {
      const result = await post('/api/generate', value);
      if (typeof result.image !== 'string' || !/^data:image\/png;base64,[A-Za-z0-9+/=\r\n]+$/.test(result.image)) throw new Error('服务没有返回有效的 PNG 图片，请重试。');
      if (typeof result.prompt !== 'string' || !result.prompt.trim()) throw new Error('服务没有返回本次使用的提示词，请重试。');
      const loaded = new Image();
      loaded.src = result.image;
      try { await loaded.decode(); } catch (_) { throw new Error('收到的图片无法显示，请重试。'); }
      state.generatedImage = result.image;
      state.imageSnapshot = inputSnapshot;
      elements.image.src = result.image;
      elements.image.alt = `根据当前提交场景生成的圆珠笔涂鸦：${value.scene}`;
      elements.downloadImageLabel.textContent = '下载 PNG';
      state.prompt = result.prompt;
      state.promptSnapshot = inputSnapshot;
      elements.promptText.textContent = result.prompt;
      elements.promptState.textContent = '本次生成使用的提示词';
      updateImageCaption();
      toast('小画已生成，可以下载了。');
    } catch (error) {
      setMessage(error.message || '这次生成没有完成，请检查服务后重试。');
      queuePrompt(true);
    } finally {
      state.generating = false;
      elements.overlay.hidden = true;
      elements.paper.setAttribute('aria-busy', 'false');
      updateButtons();
    }
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    state.objectURLs.add(url);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => { URL.revokeObjectURL(url); state.objectURLs.delete(url); }, 10000);
  }

  function pngBlob(dataURL) {
    const binary = atob(dataURL.slice(dataURL.indexOf(',') + 1));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: 'image/png' });
  }

  async function downloadImage() {
    if (state.downloading || state.generating) return;
    state.downloading = true;
    elements.imageMessage.textContent = '';
    updateButtons();
    try {
      let blob;
      if (state.generatedImage) blob = pngBlob(state.generatedImage);
      else {
        const response = await fetch('/assets/sample-dog-walk.png', { credentials: 'same-origin' });
        if (!response.ok) throw new Error('示例图片暂时无法下载，请重试。');
        blob = await response.blob();
      }
      downloadBlob(blob, state.generatedImage ? 'pet-memory-doodle.png' : 'pet-memory-doodle-example.png');
    } catch (error) {
      elements.imageMessage.textContent = error.message || '暂时无法下载图片，请重试。';
    } finally { state.downloading = false; updateButtons(); }
  }

  elements.form.addEventListener('submit', generate);
  elements.scene.addEventListener('input', edited);
  elements.objects.addEventListener('input', edited);
  elements.retry.addEventListener('click', loadConfig);
  elements.downloadImage.addEventListener('click', downloadImage);
  document.querySelectorAll('.preset-button').forEach((button) => {
    button.addEventListener('click', () => {
      if (state.generating) return;
      const preset = presets[button.dataset.preset];
      elements.scene.value = preset.scene;
      elements.objects.value = preset.objects;
      edited();
    });
  });
  elements.copyPrompt.addEventListener('click', async () => {
    if (!state.prompt || state.promptSnapshot !== snapshot()) return;
    try { await navigator.clipboard.writeText(state.prompt); toast('完整提示词已复制。'); }
    catch (_) {
      elements.promptDetails.open = true;
      const range = document.createRange();
      range.selectNodeContents(elements.promptText);
      const selection = window.getSelection();
      if (selection) { selection.removeAllRanges(); selection.addRange(range); }
      toast('浏览器未允许自动复制，已选中提示词，可手动复制。');
    }
  });
  elements.downloadPrompt.addEventListener('click', () => {
    if (!state.prompt || state.promptSnapshot !== snapshot()) return;
    downloadBlob(new Blob([state.prompt], { type: 'text/plain;charset=utf-8' }), 'pet-memory-prompt.txt');
  });
  window.addEventListener('pagehide', () => {
    cancelPrompt();
    state.objectURLs.forEach((url) => URL.revokeObjectURL(url));
    state.objectURLs.clear();
  });
  elements.scene.value = presets.dog.scene;
  elements.objects.value = presets.dog.objects;
  updateCounters();
  updatePresets();
  loadConfig();
})();
