import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Clapperboard, Film, Image as ImageIcon, Sparkles, Type, UserRound, UploadCloud, Video, X } from 'lucide-react'
import { api } from '../api'
import { Alert, Segmented, Spinner } from '../ui'
import GenOptions, { resolveLoras } from './GenOptions'
import { MODES, ModelBlocks, PromptBlocks, StylePicker, emptyModeValue, placeholders, toApiOptions } from './ModeSettings'
import { PromptBox } from './ModelPanel'

export default function NewProject({ onCreated }) {
  const [f, setF] = useState({ title: '', kind: 'movie', prompt: '', duration: 24 })
  const [opts, setOpts] = useState({ width: 832, height: 448, seed_mode: 'random', seed: 0, loras: resolveLoras(null, null), extra_loras: [] })
  const [mode, setMode] = useState('script')
  const [mv, setMv] = useState(emptyModeValue())
  const [models, setModels] = useState(null)
  const [st, setSt] = useState(null)
  const [touched, setTouched] = useState(false)
  const [files, setFiles] = useState([])
  const [adv, setAdv] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [drag, setDrag] = useState(false)
  const pick = useRef()

  useEffect(() => {   // defaults from Settings (seed + LoRAs); auto-pick the Lightning pair if never configured
    Promise.all([api.settings(), api.loras().catch(() => null)]).then(([s, lr]) => {
      setSt(s)
      setOpts((o) => (touched ? o : { ...o, seed_mode: s.seed_mode, seed: s.seed, loras: resolveLoras(s.loras, lr) }))
    })
    api.models().then(setModels).catch(() => setModels({ reachable: false, models: [], samplers: [], upscalers: [] }))
  }, [])

  const ph = st ? placeholders(st) : { image: {}, video: {} }
  const chunkFrames = Math.max(5, +(mv.video.frames || 81)), fps = Math.max(1, +(mv.video.fps || 16))
  const frames = f.duration * fps
  const chunks = Math.ceil(Math.max(0, frames - chunkFrames) / (chunkFrames - 1)) + 1
  const needsText = mode === 'script'
  const showRefs = mode !== 't2v'
  const pickMode = (m) => {
    setMode(m)
    if ((m === 'video' || m === 't2v') && st && !mv.prompts.video_negative) setMv((v) => ({ ...v, prompts: { ...v.prompts, video_negative: st.negative_prompt } }))
    if (m === 'character') setOpts((o) => ({ ...o, width: 832, height: 1216 }))
    else if (mode === 'character') setOpts((o) => ({ ...o, width: 832, height: 448 }))
    if (m === 'script') setF((x) => ({ ...x, duration: x.kind === 'clip' ? 8 : 24 }))
    else if (m !== 'image' && m !== 'character') setF((x) => ({ ...x, duration: 5 }))
  }
  const addFiles = (list) => setFiles((x) => [...x, ...[...list].filter((i) => i.type.startsWith('image/'))])

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const fd = new FormData()
      fd.append('mode', mode); fd.append('title', f.title); fd.append('duration', mode === 'image' || mode === 'character' ? 4 : f.duration)
      fd.append('kind', mode === 'script' ? f.kind : 'clip'); fd.append('prompt', mode === 'script' ? f.prompt : '')
      fd.append('aspect', 'custom'); fd.append('width', opts.width); fd.append('height', opts.height)
      fd.append('options', JSON.stringify({ seed_mode: opts.seed_mode, seed: opts.seed, loras: opts.loras, extra_loras: opts.extra_loras, ...toApiOptions(mode, mv) }))
      if (showRefs) files.forEach((x) => fd.append('images', x))
      let p = await api.create(fd)
      p = mode === 'script' ? await api.genScript(p.id) : await api.approve(p.id)
      onCreated(p)
    } catch (e2) { setErr(e2.message); setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Create a new project</h1>
        <p className="mt-1 text-sm text-muted">Describe your idea. We’ll write a script for you to review, then render it as video.</p>
      </div>

      <div className="card card-pad space-y-5">
        <div>
          <label className="label">What do you want to make?</label>
          <Segmented className="w-full sm:w-auto" value={mode} onChange={pickMode}
            options={[['script', 'Script movie', Film], ['image', 'Image', ImageIcon], ['video', 'Video', Video], ['t2v', 'Text → Video', Type], ['character', 'Character', UserRound]]} />
          <p className="hint mt-1.5">{MODES[mode][1]}</p>
        </div>
        {mode === 'script' && (
          <div>
            <label className="label">Type</label>
            <Segmented value={f.kind} onChange={(k) => setF({ ...f, kind: k, duration: k === 'clip' ? 8 : 24 })} options={[['movie', 'Movie', Film], ['clip', 'Clip', Clapperboard]]} />
          </div>
        )}
        <div><label className="label">Title <span className="font-normal">(optional)</span></label>
          <input className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Untitled project" /></div>
        <StylePicker value={mv.style} onChange={(style) => setMv({ ...mv, style })} />
        {needsText
          ? <PromptBox label="Prompt" kind="video" required rows={5} value={f.prompt} onChange={(v) => setF({ ...f, prompt: v })}
              placeholder={`A lone astronaut walks across a red desert at dawn and discovers a glowing flower…`} />
          : <PromptBlocks mode={mode} value={mv} onChange={setMv} />}

        {mode !== 'image' && mode !== 'character' && <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Duration (seconds)</label>
            <input required type="number" min={4} max={1800} className="input" value={f.duration} onChange={(e) => setF({ ...f, duration: +e.target.value })} />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {[8, 16, 24, 48, 90].map((d) => <button type="button" key={d} onClick={() => setF({ ...f, duration: d })} className={`btn btn-sm ${f.duration === d ? 'btn-primary' : 'btn-secondary'}`}>{d}s</button>)}
            </div>
          </div>
          <div className="rounded-lg bg-surface2 p-3.5 text-sm">
            <div className="text-xs font-medium text-muted">Estimate</div>
            <div className="mt-1 font-semibold">{frames} frames · {chunks} chunk{chunks > 1 ? 's' : ''}</div>
            <div className="mt-0.5 text-xs text-muted">{fps} fps, up to {chunkFrames} frames per chunk · {opts.width}×{opts.height}</div>
          </div>
        </div>}

        {showRefs && <div>
          <label className="label">{mode === 'image' ? 'Reference image' : mode === 'character' ? 'Reference character image' : mode === 'video' ? 'Start image' : 'Reference images'} <span className="font-normal">(optional)</span></label>
          <div onClick={() => pick.current.click()} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
            className={`flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-7 text-center transition ${drag ? 'border-brand bg-brand-soft' : 'border-line hover:bg-surface2'}`}>
            <UploadCloud className="h-6 w-6 text-muted" />
            <div className="text-sm font-medium">Drop images here or click to browse</div>
            <div className="hint">{mode === 'image' ? 'The first image is used as the starting point (image-to-image, see Strength).' : mode === 'character' ? 'Optional. If you add one, it is used as the reference for ALL images. If not, one sample image is rendered first for you to confirm, and that becomes the reference. The character is re-rendered in new poses, angles and lighting. Choose Look → Animated / cartoon to turn a real person into a cartoon (or Realistic for the reverse).' : mode === 'video' ? 'The first image is animated. Without one the video model runs text-to-video.' : 'The first image becomes the opening frame. Without one, a first frame is rendered from the script.'}</div>
            <input ref={pick} type="file" multiple hidden accept="image/png,image/jpeg,image/webp" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
          </div>
          {files.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-3">
              {files.map((x, i) => (
                <div key={i} className="group relative">
                  <img src={URL.createObjectURL(x)} className="h-20 w-28 rounded-lg border border-line object-cover" />
                  {i === 0 && mode !== 'character' && <span className="absolute bottom-1 left-1 rounded bg-slate-900/70 px-1.5 py-0.5 text-[10px] font-medium text-white">Opening frame</span>}
                  <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))} className="absolute -right-2 -top-2 grid h-5 w-5 place-items-center rounded-full border border-line bg-surface text-muted shadow hover:text-danger"><X className="h-3 w-3" /></button>
                </div>
              ))}
            </div>
          )}
        </div>}
      </div>

      <div className="card">
        <button type="button" onClick={() => setAdv(!adv)} className="flex w-full items-center justify-between px-5 py-4 text-left">
          <div><div className="section-title">Models &amp; advanced options</div><div className="hint mt-0.5">{opts.width}×{opts.height} · {mode !== 'video' ? (mv.image.model || 'default image model') : ''}{mode === 't2v' ? ' → ' : ''}{mode !== 'image' && mode !== 'character' ? (mv.video.model || 'default video model') : ''} · seed {opts.seed_mode}</div></div>
          <ChevronDown className={`h-5 w-5 text-muted transition ${adv ? 'rotate-180' : ''}`} />
        </button>
        {adv && <div className="space-y-6 border-t border-line p-5">
          <ModelBlocks mode={mode} value={mv} onChange={setMv} models={models} ph={ph} />
          <GenOptions value={opts} showLoras={mode !== 'image' && mode !== 'character'} onChange={(o) => { setTouched(true); setOpts(o) }} />
        </div>}
      </div>

      {err && <Alert onClose={() => setErr('')}>{err}</Alert>}
      <div className="flex justify-end">
        <button disabled={busy} className="btn btn-primary px-5 py-2.5">{busy ? <Spinner /> : <Sparkles className="h-4 w-4" />}{busy ? 'Creating…' : mode === 'script' ? 'Create & write script' : mode === 'character' ? (files.length ? `Generate ${mv.character?.count || 20} character images` : 'Generate sample image') : 'Create & generate'}</button>
      </div>
    </form>
  )
}
