(() => {
  'use strict';

  const isDemo = document.documentElement.dataset.mode === 'demo';
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
    imageMessage: $('image-message'), toast: $('toast'),
    demoNotice: $('demo-notice'), generationNote: $('generation-note'),
    promptExplanation: $('prompt-explanation'), footerNote: $('footer-note')
  };

  const presets = {
    dog: {
      scene: 'On an evening walk, my small dog suddenly runs after two falling leaves, and I hurry after it holding the leash.',
      objects: 'a stick figure, a small four-legged dog, a leash, and two falling leaves'
    },
    cat: {
      scene: 'I sit on the floor reading, and my kitten lies beside the open book with one front paw resting on the page.',
      objects: 'a seated stick figure, a small four-legged kitten, and an open book'
    },
    rest: {
      scene: 'I sit in a chair drinking hot tea while my small dog sleeps curled up at my feet. Neither of us makes a sound; we just stay together quietly.',
      objects: 'a seated stick figure, a small curled-up dog, a chair, and a steaming cup of tea'
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
    if (!value.scene) return 'Write a scene first, then draw it.';
    if (!value.objects) return 'List the people, pets or objects to keep in the picture.';
    if (value.scene.length > state.limits.scene) return `The scene can have at most ${state.limits.scene} characters. Please shorten it.`;
    if (value.objects.length > state.limits.objects) return `The object list can have at most ${state.limits.objects} characters. Please shorten it.`;
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
    elements.generate.disabled = isDemo || !state.configReady || !state.config?.configured || !valid || state.generating || state.configLoading;
    elements.generateLabel.textContent = isDemo ? 'New images need a local key' : state.generating ? 'Generating…' : state.configLoading ? 'Checking setup…' : state.configReady && state.config?.configured ? 'Generate doodle' : 'Connect the service to generate';
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
      elements.imageLabel.textContent = 'v2 prompt sample';
      elements.imageCaption.textContent = isDemo
        ? 'This sample was made earlier with the v2 prompt. Changing the scene updates the prompt, not this image. You can download the sample PNG.'
        : 'This real sample is here for reference. Edit the scene, then click Generate to draw a new one.';
      return;
    }
    const unchanged = state.imageSnapshot === snapshot();
    elements.imageLabel.textContent = unchanged ? 'Just drawn' : 'Last result';
    elements.imageCaption.textContent = unchanged ? 'This drawing was made from your scene. Download the PNG, or change the scene and draw another.' : 'The scene has changed; this is still the last result. Click Generate to draw the new scene.';
  }

  async function post(path, body, signal) {
    if (isDemo) {
      if (path !== '/api/prompt') throw new Error('The online demo does not call the image service. To make new images, follow the README and set up your own key locally.');
      if (!state.configReady || typeof window.DoodleDemo?.prompt !== 'function') throw new Error('The demo files have not loaded yet. Please check again.');
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const result = await window.DoodleDemo.prompt(body);
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return result;
    }
    if (!state.configReady || !state.config?.csrfToken) throw new Error('The local server is not connected yet. Please check the setup again.');
    const response = await fetch(path, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.config.csrfToken },
      body: JSON.stringify(body), signal
    });
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('The local server sent a reply that could not be read. Check the server and try again.'); }
    if (!response.ok || typeof result.error === 'string') throw new Error(typeof result.error === 'string' ? result.error : `The request did not finish (${response.status}). Please try again.`);
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
      elements.promptState.textContent = isDemo ? 'Waiting for demo files' : 'Waiting for the local server';
      elements.promptText.textContent = isDemo ? 'The full prompt appears once the demo files load.' : 'Connect the local server to see the full prompt.';
      return;
    }
    const error = validity();
    if (error) {
      elements.promptState.textContent = 'Waiting for input';
      elements.promptText.textContent = error;
      return;
    }
    elements.promptState.textContent = 'Updating';
    elements.promptText.textContent = 'Building the prompt from your input…';
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
      if (typeof result.prompt !== 'string' || !result.prompt.trim()) throw new Error('No full prompt came back. Please try again.');
      state.prompt = result.prompt;
      state.promptSnapshot = inputSnapshot;
      elements.promptText.textContent = result.prompt;
      elements.promptState.textContent = isDemo ? 'Updated · browser preview' : 'Updated · local preview';
    } catch (error) {
      if (error.name === 'AbortError' || version !== state.promptVersion) return;
      elements.promptState.textContent = 'Preview unavailable';
      elements.promptText.textContent = error.message || (isDemo ? 'The demo preview is unavailable. Please reload.' : 'The preview could not be built. Check the local server.');
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
    elements.configLabel.textContent = isDemo ? 'Loading the online demo' : 'Checking the service';
    elements.promptState.textContent = isDemo ? 'Waiting for demo files' : 'Waiting for the local server';
    elements.promptText.textContent = isDemo ? 'Loading the prompt template…' : 'Connecting to the local server…';
    elements.setupNote.hidden = true;
    setMessage('');
    updateButtons();
    try {
      let config;
      if (isDemo) {
        if (typeof window.DoodleDemo?.config !== 'function') throw new Error('The demo script did not load. Reload the page and try again.');
        config = await window.DoodleDemo.config();
        if (!config || config.mode !== 'demo' || config.configured !== false) throw new Error('The demo settings are invalid. Please reload.');
      } else {
        const response = await fetch('/api/config', { credentials: 'same-origin', cache: 'no-store' });
        config = await response.json();
        if (!response.ok || !config || typeof config.csrfToken !== 'string' || !config.csrfToken || typeof config.configured !== 'boolean') throw new Error('Could not read the local server settings. Make sure the server is running.');
      }
      if (version !== state.configVersion) return;
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
      elements.configLabel.textContent = isDemo ? 'Online demo · prompt editable' : config.configured ? 'Image service ready' : 'Image service not connected';
      elements.configStatus.classList.toggle('is-ready', isDemo || config.configured);
      elements.setupNote.hidden = isDemo || config.configured;
      elements.retry.hidden = isDemo || config.configured;
      elements.model.textContent = isDemo ? 'Sample · a real earlier result' : config.configured && typeof config.model === 'string' ? `Image model · ${config.model}` : 'White paper · thin black lines';
      updateCounters();
      updatePresets();
      updateImageCaption();
      queuePrompt(true);
    } catch (error) {
      if (version !== state.configVersion) return;
      elements.configLabel.textContent = isDemo ? 'Demo files failed to load' : 'Local server not connected';
      elements.configStatus.classList.add('is-error');
      elements.retry.hidden = false;
      elements.promptState.textContent = isDemo ? 'Waiting for demo files' : 'Waiting for the local server';
      elements.promptText.textContent = isDemo ? 'The demo files are unavailable. Reload to preview the prompt.' : 'The local server is unavailable. Connect it to preview the prompt.';
      setMessage(error.message || (isDemo ? 'Could not load the demo files. Reload the page and try again.' : 'Could not connect to the local server. Check it and try again.'));
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
    if (isDemo) {
      setMessage('The online demo only previews the prompt and downloads the sample. To make new images, follow the README and set up your own API key locally.');
      return;
    }
    if (state.generating) return;
    const error = validity();
    if (error) { setMessage(error); elements.scene.focus(); return; }
    if (!state.configReady || !state.config?.configured) { setMessage('Connect the image service before generating.'); return; }
    const value = inputValue();
    const inputSnapshot = snapshot(value);
    cancelPrompt();
    state.generating = true;
    setMessage('');
    elements.imageMessage.textContent = '';
    elements.overlay.hidden = false;
    elements.paper.setAttribute('aria-busy', 'true');
    elements.promptState.textContent = 'Generating';
    updateButtons();
    try {
      const result = await post('/api/generate', value);
      if (typeof result.image !== 'string' || !/^data:image\/png;base64,[A-Za-z0-9+/=\r\n]+$/.test(result.image)) throw new Error('The server did not return a valid PNG. Please try again.');
      if (typeof result.prompt !== 'string' || !result.prompt.trim()) throw new Error('The server did not return the prompt it used. Please try again.');
      const loaded = new Image();
      loaded.src = result.image;
      try { await loaded.decode(); } catch (_) { throw new Error('The image could not be shown. Please try again.'); }
      state.generatedImage = result.image;
      state.imageSnapshot = inputSnapshot;
      elements.image.src = result.image;
      elements.image.alt = `Ballpoint doodle made from your scene: ${value.scene}`;
      elements.downloadImageLabel.textContent = 'Download PNG';
      state.prompt = result.prompt;
      state.promptSnapshot = inputSnapshot;
      elements.promptText.textContent = result.prompt;
      elements.promptState.textContent = 'Prompt used for this image';
      updateImageCaption();
      toast('Your drawing is ready to download.');
    } catch (error) {
      setMessage(error.message || 'This generation did not finish. Check the server and try again.');
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
        const response = await fetch('./assets/sample-dog-walk.png', { credentials: 'same-origin' });
        if (!response.ok) throw new Error('The sample image could not be downloaded. Please try again.');
        blob = await response.blob();
      }
      downloadBlob(blob, state.generatedImage ? 'pet-memory-doodle.png' : 'pet-memory-doodle-example.png');
    } catch (error) {
      elements.imageMessage.textContent = error.message || 'The image could not be downloaded. Please try again.';
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
    try { await navigator.clipboard.writeText(state.prompt); toast('Full prompt copied.'); }
    catch (_) {
      elements.promptDetails.open = true;
      const range = document.createRange();
      range.selectNodeContents(elements.promptText);
      const selection = window.getSelection();
      if (selection) { selection.removeAllRanges(); selection.addRange(range); }
      toast('The browser blocked copying, so the prompt is selected for you to copy by hand.');
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
  if (isDemo) {
    elements.demoNotice.hidden = false;
    elements.generationNote.textContent = 'The online demo never sends your input, calls the image model or costs API money. To make new images, run it locally using the README below.';
    elements.promptExplanation.textContent = 'Below is the prompt your browser built from the two boxes and the fixed v2 template. Your input is not sent to any server.';
    elements.footerNote.textContent = 'What you type stays on this page only and is cleared on reload. The prompt is built in your browser and needs no image-service key.';
    elements.promptDetails.open = true;
  }
  updateImageCaption();
  updateCounters();
  updatePresets();
  loadConfig();
})();
