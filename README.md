# Pet Memory Doodle Lab

A local web page that turns a small moment with your pet into a black-and-white ballpoint-pen doodle.

**[Live demo](https://pet-memory-doodle-lab.yunganghu04.chatgpt.site)** (edit the scene and see the prompt and sample image; no image generation)

![Sample doodle](static/assets/sample-dog-walk.png)

## What you need

- Python 3.9 or newer (no other packages)
- To generate new images: your own OpenAI API key (create one on the [OpenAI platform](https://platform.openai.com/api-keys); using it costs money)

## Use

1. Get the code and start the app:

   ```sh
   git clone https://github.com/tony-workbench/pet-memory-doodle-lab.git
   cd pet-memory-doodle-lab
   python3 app.py
   ```

   If port 8767 is taken, add `--port 8768` and open that port instead.

2. Open <http://127.0.0.1:8767>.
3. Pick an example scene, or describe your own and list what should appear in the picture.
4. Open "See the full prompt" and check it holds no personal details you don't want to send. Without a key you can still copy or download the prompt and the sample image.
5. Press `Ctrl+C` in the terminal to stop.

## Generate new images

1. Enter your key in the terminal (hidden, and kept out of shell history):

   ```sh
   printf 'OpenAI API key: '; read -rs OPENAI_API_KEY; echo
   export OPENAI_API_KEY
   ```

2. Start the app in the same terminal: `python3 app.py`
3. Click "Generate doodle" on the page, then download the PNG.
4. Press `Ctrl+C`, then run `unset OPENAI_API_KEY`. Never put the key in the web page, the code or a Git commit.

## Test

```sh
python3 -m unittest discover -s tests -v
```

With Node.js installed, the tests also check that the browser demo builds the same prompt as the Python app.

## Host your own demo

1. Build the static version:

   ```sh
   python3 scripts/build_demo.py
   ```

2. Preview it locally:

   ```sh
   python3 -m http.server 8768 --bind 127.0.0.1 --directory demo/dist
   ```

3. Upload `demo/dist/` to any static web host; the entry page is `index.html`.

## Docs

- Design: [docs/DESIGN.md](docs/DESIGN.md)
- Security: [SECURITY.md](SECURITY.md)
