import ModelPanel, { PromptBox } from './ModelPanel'
import { Segmented } from '../ui'
import { useState } from 'react'

export const MODES = {
  script: ['Script movie', 'An LLM writes a script from your idea; rendered as a chunked video.'],
  image: ['Image', 'One prompt (and negative prompt) → image(s).'],
  video: ['Video', 'One prompt (and negative prompt) → video. Add a reference image to animate it, or leave it empty for a text-to-video model.'],
  t2v: ['Text → Video', 'Render a first image, then animate it. Each stage has its own prompt and negative prompt.'],
  character: ['Character', 'Describe a character (or add a reference image) and get a set of images in different poses, angles and lighting, with captions, to train a LoRA.'],
}

const Stage = ({ title, sub, children }) => (
  <div className="space-y-3 rounded-xl border border-line bg-surface2/40 p-4">
    <div><div className="section-title">{title}</div>{sub && <div className="hint mt-0.5">{sub}</div>}</div>
    {children}
  </div>
)

/** Realistic vs cartoon: the backend injects matching words into the prompt and negative prompt. */
export function StylePicker({ value, onChange, disabled }) {
  return (
    <div>
      <label className="label">Look</label>
      <Segmented value={value || 'auto'} disabled={disabled} onChange={(k) => onChange(k === 'auto' ? '' : k)}
        options={[['auto', 'Auto'], ['realistic', 'Realistic'], ['cartoon', 'Animated / cartoon']]} />
      <p className="hint mt-1.5">Adds style words to your prompts (and opposing ones to the negative prompt) so the result is clearly {value === 'cartoon' ? 'a cartoon' : value === 'realistic' ? 'realistic' : 'what your prompt says'}.</p>
    </div>
  )
}

/** Character mode: how many images, and the optional caption trigger word. */
function CharacterBlock({ value, onChange, disabled }) {
  const ch = value.character || { count: 20, trigger: '' }
  const set = (patch) => onChange({ ...value, character: { ...ch, ...patch } })
  const [raw, setRaw] = useState(String(ch.count))
  const setCount = (n) => { setRaw(String(n)); set({ count: Math.max(1, Math.min(200, Math.floor(+n || 1))) }) }
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <label className="label">How many images?</label>
        <input type="number" min={1} max={200} disabled={disabled} className="input" value={raw}
          onChange={(e) => { setRaw(e.target.value); if (e.target.value !== '') set({ count: Math.max(1, Math.min(200, Math.floor(+e.target.value || 1))) }) }}
          onBlur={() => setRaw(String(ch.count))} />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[12, 20, 30, 40].map((n) => <button type="button" key={n} disabled={disabled} onClick={() => setCount(n)} className={`btn btn-sm ${ch.count === n ? 'btn-primary' : 'btn-secondary'}`}>{n}</button>)}
        </div>
        <p className="hint mt-1.5">15–40 is a good LoRA dataset. Each image gets a different pose, camera angle, framing, lighting and background.</p>
      </div>
      <div>
        <label className="label">Trigger word <span className="font-normal text-muted">(optional)</span></label>
        <input disabled={disabled} className="input" value={ch.trigger} onChange={(e) => set({ trigger: e.target.value })} placeholder="e.g. mira_char" />
        <p className="hint mt-1.5">A rare made-up word that goes at the start of every caption; you then use it in video prompts to call the character.</p>
      </div>
    </div>
  )
}

/** Prompt + negative prompt boxes for the mode (script mode keeps its own idea box elsewhere). */
export function PromptBlocks({ mode, value, onChange, disabled }) {
  const pr = value.prompts
  const set = (patch) => onChange({ ...value, prompts: { ...pr, ...patch } })
  const imageBox = (
    <>
      <PromptBox label="Prompt" kind="image" required disabled={disabled} rows={4} value={pr.image} onChange={(v) => set({ image: v })}
        placeholder="A lone astronaut standing in a red desert at dawn, cinematic, 35mm…" />
      <PromptBox label="Negative prompt" disabled={disabled} rows={2} value={pr.image_negative} onChange={(v) => set({ image_negative: v })} placeholder="blurry, low quality, watermark…" />
    </>
  )
  const videoBox = (
    <>
      <PromptBox label="Prompt" kind="video" required disabled={disabled} rows={4} value={pr.video} onChange={(v) => set({ video: v })}
        placeholder="The astronaut walks slowly toward the camera, dust drifting, slow push-in, warm morning light…" />
      <PromptBox label="Negative prompt" disabled={disabled} rows={3} value={pr.video_negative ?? ''} onChange={(v) => set({ video_negative: v })} placeholder="static, blurry, low quality…" />
    </>
  )
  if (mode === 'character') return (
    <div className="space-y-4">
      <PromptBox label="Character description" kind="character" rows={5} disabled={disabled} value={pr.image} onChange={(v) => set({ image: v })}
        hint="Describe only what stays the same: face, hair, skin, build, outfit, accessories. Poses, angles and lighting are varied for you. Optional if you add a reference image."
        placeholder="A 25-year-old woman with a heart-shaped face, green eyes, shoulder-length wavy auburn hair, freckles, wearing a mustard yellow raincoat over a navy sweater and black boots…" />
      <PromptBox label="Negative prompt" disabled={disabled} rows={2} value={pr.image_negative} onChange={(v) => set({ image_negative: v })} placeholder="blurry, low quality, extra fingers, deformed, watermark, text…" />
      <CharacterBlock value={value} onChange={onChange} disabled={disabled} />
    </div>
  )
  if (mode === 'image') return <div className="space-y-4">{imageBox}</div>
  if (mode === 'video') return <div className="space-y-4">{videoBox}</div>
  if (mode === 't2v') return (
    <div className="space-y-4">
      <Stage title="1 · First image" sub="Rendered with the image model; becomes the opening frame of the video.">{imageBox}</Stage>
      <Stage title="2 · Video" sub="Animates the first image.">{videoBox}</Stage>
    </div>
  )
  return null
}

/** Model/sampling panels for the stages the mode uses (+ negatives for script mode, whose prompts come from the LLM). */
export function ModelBlocks({ mode, value, onChange, models, ph, disabled }) {
  const set = (k) => (v) => onChange({ ...value, [k]: v })
  const setPrompt = (patch) => onChange({ ...value, prompts: { ...value.prompts, ...patch } })
  const image = (
    <Stage title={mode === 'image' || mode === 'character' ? 'Image model' : mode === 't2v' ? '1 · First-image model' : 'First-frame model'}
      sub={mode === 'script' ? 'Used only when the project has no reference image.' : mode === 'character' ? 'With a reference image, use a reference-aware model (FLUX.2 Klein, Qwen Image Edit, FLUX Kontext) to keep the identity while changing pose and angle. A normal model runs as image-to-image: if all images look the same, raise Strength (0.9+); if the character changes too much, lower it.' : undefined}>
      {mode === 'script' && <PromptBox label="Negative prompt for the first frame" rows={2} disabled={disabled} value={value.prompts.image_negative} onChange={(v) => setPrompt({ image_negative: v })} />}
      <ModelPanel kind="image" value={value.image} onChange={set('image')} models={models} ph={ph.image} disabled={disabled} hideCount={mode === 'character'} />
    </Stage>
  )
  const video = (
    <Stage title={mode === 't2v' ? '2 · Video model' : 'Video model'}>
      {mode === 'script' && <PromptBox label="Negative prompt for the video" rows={3} disabled={disabled} value={value.prompts.video_negative ?? ''} onChange={(v) => setPrompt({ video_negative: v })}
        hint="Empty = use the negative prompt from Settings." />}
      <ModelPanel kind="video" value={value.video} onChange={set('video')} models={models} ph={ph.video} disabled={disabled} />
    </Stage>
  )
  return <div className="space-y-4">{mode !== 'video' && image}{mode !== 'image' && mode !== 'character' && video}</div>
}

/** Shape sent to the API. Script mode: empty negative = Settings default (null); other modes: exactly what was typed. */
export function toApiOptions(mode, value) {
  const pr = value.prompts
  return {
    prompts: { ...pr, video_negative: mode === 'script' && !pr.video_negative ? null : (pr.video_negative ?? '') },
    image: value.image,
    video: value.video,
    style: value.style || '',
    character: value.character,
  }
}

/** Placeholders shown in empty model fields: the Settings values that will actually be used. */
export const placeholders = (st) => ({
  image: { model: st.keyframe_model, steps: st.keyframe_steps, cfg: st.keyframe_cfg, shift: st.keyframe_shift, sampler: st.keyframe_sampler, clip_skip: 1, strength: 1, count: 1 },
  video: { model: st.hne_model, refiner: st.lne_model, refiner_start: st.refiner_start, steps: st.steps, cfg: st.cfg, shift: st.shift, sampler: st.sampler, clip_skip: 1, strength: 1, frames: 81, fps: 16 },
})

export const emptyModeValue = (videoNegative = '') => ({
  prompts: { image: '', image_negative: '', video: '', video_negative: videoNegative },
  image: {}, video: {}, style: '', character: { count: 20, trigger: '' },
})
