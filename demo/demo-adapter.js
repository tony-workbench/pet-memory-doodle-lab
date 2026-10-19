/* Browser-only prompt preview. This adapter never sends scene text to a server. */
(() => {
  'use strict';

  const scriptSource = document.currentScript?.src || document.baseURI;
  const configURL = new URL('prompt-config.json', scriptSource).href;
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  // Python str.strip() whitespace, including its C1 and information-separator cases.
  const pythonWhitespace = '[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
  const trimPattern = new RegExp('^' + pythonWhitespace + '+|' + pythonWhitespace + '+$', 'g');
  let configuration;

  function safeConfig(value) {
    if (!value || value.version !== 1 || value.mode !== 'demo' || value.configured !== false ||
        typeof value.reference !== 'string' || typeof value.model !== 'string' ||
        typeof value.defaults?.scene !== 'string' || typeof value.defaults?.objects !== 'string' ||
        value.limits?.scene !== 600 || value.limits?.objects !== 300) {
      throw new Error('The static prompt configuration could not be read. Reload this page.');
    }
    const reference = value.reference;
    const scene = value.defaults.scene;
    const objects = value.defaults.objects;
    const sceneStart = reference.indexOf(scene);
    const objectsStart = reference.indexOf(objects);
    if (!scene || !objects || sceneStart < 0 || objectsStart < sceneStart + scene.length ||
        reference.lastIndexOf(scene) !== sceneStart || reference.lastIndexOf(objects) !== objectsStart) {
      throw new Error('The static prompt reference needs repair.');
    }
    return Object.freeze({
      mode: 'demo', configured: false, model: value.model, reference,
      defaults: Object.freeze({ scene, objects }),
      limits: Object.freeze({ scene: 600, objects: 300 }), sceneStart, objectsStart
    });
  }

  function loadConfig() {
    if (!configuration) {
      configuration = fetch(configURL, { credentials: 'omit', mode: 'same-origin', cache: 'no-store' })
        .then(response => {
          if (!response.ok) throw new Error('The static prompt configuration is unavailable. Reload this page.');
          return response.json();
        })
        .then(safeConfig)
        .catch(error => { configuration = undefined; throw error; });
    }
    return configuration;
  }

  function validate(payload, config) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
        Object.prototype.toString.call(payload) !== '[object Object]') {
      throw new Error('Send a JSON object with scene and objects fields.');
    }
    if (Object.keys(payload).some(key => !own(config.limits, key))) {
      throw new Error('Only scene and objects fields are accepted.');
    }
    const result = {};
    for (const key of ['scene', 'objects']) {
      let value = own(payload, key) ? payload[key] : config.defaults[key];
      if (typeof value !== 'string') throw new Error(`The ${key} field must be text.`);
      value = value.replace(trimPattern, '');
      if (!value) throw new Error(`The ${key} field cannot be empty.`);
      const points = Array.from(value);
      if (points.length > config.limits[key]) throw new Error(`The ${key} field must contain at most ${config.limits[key]} characters.`);
      if (points.some(char => (char.codePointAt(0) < 32 && !'\n\r\t'.includes(char)) || char.codePointAt(0) === 127)) {
        throw new Error(`The ${key} field contains unsupported control characters.`);
      }
      if (points.some(char => char.codePointAt(0) >= 0xd800 && char.codePointAt(0) <= 0xdfff)) {
        throw new Error(`The ${key} field contains invalid Unicode characters.`);
      }
      result[key] = value;
    }
    return result;
  }

  async function config() {
    const data = await loadConfig();
    return {
      mode: 'demo', configured: false, model: data.model, csrfToken: null,
      defaults: { ...data.defaults }, limits: { ...data.limits }
    };
  }

  async function prompt(payload = {}) {
    const data = await loadConfig();
    const value = validate(payload, data);
    const { reference, defaults, sceneStart, objectsStart } = data;
    let suffix = reference.slice(objectsStart + defaults.objects.length);
    if (value.scene !== defaults.scene || value.objects !== defaults.objects) {
      suffix = suffix.replace(
        'The dog is a very simple animal outline with four legs and tiny dot eyes.',
        'Any pet in the scene is a very simple animal outline with four legs and tiny dot eyes.'
      );
    }
    return { prompt: reference.slice(0, sceneStart) + value.scene +
      reference.slice(sceneStart + defaults.scene.length, objectsStart) + value.objects + suffix };
  }

  window.DoodleDemo = Object.freeze({ config, prompt });
})();
