<p align="center">
  <img src="frontend/public/nandi.svg" alt="Nandi logo: Shiva's bull with a creation spark between the horns" width="120" />
</p>

<h1 align="center">Nandi</h1>

<p align="center"><b>An unofficial companion app for <a href="https://drawthings.ai">Draw Things</a></b><br/>
Characters, images, clips and full movies, driven from your browser over Draw Things' gRPC API.</p>

> **Unofficial.** Nandi is an independent open-source project. It is **not affiliated with, endorsed by, or sponsored by Draw Things** or its authors.
> "Draw Things" is a name and trademark of its respective owner. Nandi only talks to the gRPC server that the Draw Things app exposes on your own machine.
> No Draw Things application code is included, and **no model weights** are included or downloaded. Models such as Wan 2.2, Flux or Z-Image have their own licenses, so check them before use.

*Why "Nandi"?* In Hindu tradition Nandi is Shiva's bull, his devoted companion who is always at his side. Nandi (the app) is the buddy that sits next to Draw Things.

---

## What it does

Pick a mode on **New project**:

| Mode | You provide | You get |
|---|---|---|
| **Script movie** | an idea | An LLM writes a scene-by-scene script (editable, with feedback and revision). Once approved, the movie is generated in chunks and joined. |
| **Image** | prompt + negative prompt (optional reference image) | 1–16 images (text-to-image, or image-to-image with a reference) |
| **Video** | prompt + negative prompt, optional start image | An animated clip (image-to-video, or text-to-video with no image) |
| **Text → Video** | image prompt + negative, video prompt + negative | A first image, then a video animated from it |
| **Character** | a description and/or a reference image, image count, optional trigger word | N images of one character in varied poses, angles, lighting and backgrounds, plus caption files, downloadable as a LoRA dataset zip |

Highlights
- **Any model Draw Things reports**, picked per stage, with suggested steps / CFG / shift / sampler / frames / fps per model, all 20 samplers, CLIP skip, strength, LoRAs, and the advanced fields (hires fix, upscaler, TeaCache, tiling, stage 2, CFG zero-star…). Empty fields fall back to Settings.
- **Chunked long videos** (Wan 2.2 A14B image-to-video): each chunk continues from the last frame of the previous one. Failed or cancelled runs can be **resumed**; finished chunks are skipped. Individual chunks can be re-prompted and re-rendered.
- **Script LLM of your choice:** Ollama, any OpenAI-compatible API (local or cloud), or Anthropic. An **Enhance** button expands any prompt.
- **Character LoRA workflow** with consistent-character sampling and a ready-to-train dataset zip (see below).
- Light / dark / auto theme, live status of the LLM and Draw Things in the sidebar.

## Requirements

| | |
|---|---|
| **Draw Things** | The app (or its gRPC server) running with the API server enabled, default `localhost:7859`. Turn on *Enable Model Browsing* if you want the model pickers filled in. (Menu names can differ between Draw Things versions.) |
| **Python** | 3.9 or newer |
| **Node.js** | A current LTS (20+), only to build the frontend |
| **ffmpeg** | On your `PATH` (macOS: `brew install ffmpeg`). Used to encode and join video. |
| **A text LLM** *(for Script movie and Enhance)* | [Ollama](https://ollama.com) (default model `qwen3.5:2b`), any OpenAI-compatible endpoint, or an Anthropic key. Not needed for plain image / video / character modes. |

## Quick start

```bash
git clone <your-repo-url> nandi && cd nandi
./start.sh          # first run creates backend/.venv, installs requirements, builds the frontend
```

Then open <http://localhost:8000>. `start.sh` also opens it for you, and `NANDI_PORT=9000 ./start.sh` changes the port.

Prefer to do it by hand?

```bash
# backend (API on :8000, also serves frontend/dist when it exists)
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000

# frontend
cd frontend && npm install
npm run build       # then just open http://localhost:8000
npm run dev         # or: dev server on :5173 that proxies /api and /media to :8000
```

Interactive API docs are at <http://localhost:8000/docs>.

## First-time setup

1. Start **Draw Things** and enable its API server (gRPC, port 7859). The self-signed TLS certificate is fetched and trusted automatically.
2. Open Nandi → **Settings** (sidebar):
   - **Draw Things:** host, port, TLS, and the shared secret if you set one.
   - **Script LLM:** provider (Ollama / OpenAI-compatible / Anthropic), base URL, model, API key. Use *Test* to check it.
   - The sidebar dots turn green when the LLM and Draw Things are reachable.
3. Make sure the models you want are downloaded in Draw Things. The defaults for video are:
   `wan_v2.2_a14b_hne_i2v_q8p.ckpt` (high-noise expert) + `wan_v2.2_a14b_lne_i2v_q8p.ckpt` (low-noise expert),
   `umt5_xxl_encoder_q8p.ckpt`, `wan_v2.1_video_vae_f16.ckpt`, and `z_image_turbo_1.0_q8p.ckpt` for first frames.
   The Wan 2.2 Lightning LoRAs (high / low) are picked up automatically when downloaded. Anything else can be selected per project.

## How the script-movie flow works

1. **New project:** movie or clip, idea, duration, format, optional reference images.
2. The LLM writes a script (scenes of about 5 s each, with characters, style and per-scene video prompts). Edit it, or give feedback and revise.
3. **Approve** → the video is generated in chunks:
   - Each chunk is 81 frames @ 16 fps (Wan 2.2's native length; longer clips tend to loop back to the start pose). The high-noise expert is the `model`, the low-noise expert the `refiner_model`.
   - Chunk 1 starts from the first reference image, or from a first frame rendered with the keyframe model if there is none.
   - After each chunk, `ffmpeg` extracts its last frame, which becomes the init image of the next chunk. The duplicated seed frame is dropped, so each continuation adds 80 new frames.
   - Chunks are joined with `ffmpeg -c copy`.

### Character LoRA workflow

1. **New project → Character:** describe the character and/or add a reference image (*Look → cartoon* converts a real person). Choose how many images (15–40 is typical).
   - **With a reference image:** it is used as the reference for every image.
   - **Without one:** a single neutral sample is rendered first. Confirm it (**Use this sample**) or make a **New sample**; the confirmed sample then anchors every image so the character stays consistent.
2. Download the dataset zip (images + captions), delete weak images, and train the LoRA (Draw Things, kohya, ai-toolkit…).
3. In any video project, open **Models & generation settings → Additional LoRAs** and add it next to the two fixed Lightning slots. Wan 2.2 A14B LoRAs usually come as a high-noise file (set to *Base*) and a low-noise file (set to *Refiner*); a single-file LoRA uses *All*.

## Project layout

```
backend/
  app/main.py        FastAPI routes (projects, script, approve/resume, settings, health, dataset zip…)
  app/pipeline.py    generation pipelines (video chunks, image, character) and job control
  app/dt_client.py   Draw Things gRPC client: FlatBuffer config, tensor encode/decode
  app/llm.py         script writer / prompt enhancer (Ollama, OpenAI-compatible, Anthropic)
  app/character.py   character-set prompt variants and captions
  app/video.py       ffmpeg helpers
  app/db.py          SQLite persistence and default settings
  app/pb/            generated gRPC stubs + imageService.proto
  data/              runtime data: database, uploads, chunks, final videos (git-ignored)
frontend/            React + Tailwind (Vite)
start.sh             one-command setup and run
```

## Notes and limits

- Width and height must be multiples of 64; the presets are 832×448, 1024×576, 448×832 and 640×640.
- **Cancelling stops Nandi from waiting.** Draw Things itself may keep rendering the current chunk until it finishes.
- Video generation is heavy: expect minutes per chunk, and more for larger frames.
- **No authentication.** Nandi binds to `127.0.0.1` and stores your LLM key and Draw Things secret in the local SQLite database in `backend/data/`. Don't expose it to a network you don't trust.
- Your data (database, uploads, chunks, final videos) lives in `backend/data/`. Back it up if it matters. Nothing there is committed to git.
- An earlier name of this project was `mv-gen`; if `backend/data/mvgen.db` exists it is still used, so existing projects keep working.

## Troubleshooting

| Symptom | Check |
|---|---|
| Sidebar says *Draw Things offline* | Is the app running with the API server on? Right host/port in Settings? Try toggling TLS. Check the shared secret if you set one. |
| Model pickers are empty | Enable *Model Browsing* in Draw Things, or type the model filename by hand. |
| *model missing* next to the Script LLM | Pull it (`ollama pull qwen3.5:2b`) or change the model in Settings. |
| `ffmpeg failed` / `ffmpeg: command not found` | Install ffmpeg and make sure it's on `PATH`. |
| Port 8000 already in use | `NANDI_PORT=9000 ./start.sh` |
| Video loops back to its start pose | Keep chunks at 81 frames; use more scenes rather than a longer single chunk. |

## Contributing

Issues and pull requests are welcome. Please keep changes small and focused, and say which Draw Things version and models you tested with. Never commit anything from `backend/data/`: it can contain API keys.
By contributing you agree that your work is released under the same license as the project (GPL-3.0).

## Third-party notices

- `backend/app/pb/imageService.proto` and the generated `imageService_pb2*.py` follow the public gRPC definition of Draw Things' community repository ([drawthingsai/draw-things-community](https://github.com/drawthingsai/draw-things-community), **GPL-3.0**). This is one reason Nandi itself is released under GPL-3.0.
- Built with FastAPI, React, Tailwind CSS, Vite, lucide-react, gRPC, FlatBuffers, fpzip, Pillow and ffmpeg; each under its own license.
- Wan 2.2, Z-Image and any other models are third-party; Nandi does not ship or relicense them.

## License

Nandi is free software, released under the **GNU General Public License v3.0**. See [LICENSE](LICENSE).
You may use, study, change and share it; if you distribute a modified version, you must do so under the same license and make its source available.
Third-party models and libraries keep their own licenses (see above).
