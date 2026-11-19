import { useCallback, useEffect, useRef, useState } from 'react'
import { Archive, Ban, ChevronDown, Download, ImagePlus, Play, RotateCcw, Send, Sparkles, Trash2, X } from 'lucide-react'
import { api, media } from '../api'
import { Alert, Badge, ProgressBar, Spinner, Stepper } from '../ui'
import GenOptions from './GenOptions'
import { ModelBlocks, PromptBlocks, StylePicker, placeholders, toApiOptions } from './ModeSettings'
import ScriptEditor from './ScriptEditor'

const STEPS = ['Brief', 'Script', 'Generate', 'Result']
const DIRECT_STEPS = ['Setup', 'Generate', 'Result']
const MODE_LABEL = { script: 'Script movie', image: 'Image', video: 'Video', t2v: 'Text → Video', character: 'Character' }

export default function ProjectView({ id, onChanged, onDeleted }) {
  const [p, setP] = useState(null)
  const [err, setErr] = useState('')
  const [feedback, setFeedback] = useState('')
  const [opts, setOpts] = useState(null)
  const [optsDirty, setOptsDirty] = useState(false)
  const [optsOpen, setOptsOpen] = useState(false)
  const [models, setModels] = useState(null)
  const [st, setSt] = useState(null)
  const fileRef = useRef()
  const optsDirtyRef = useRef(false)

  const load = useCallback(() => api.project(id).then((d) => {
    setP(d)
    setOpts((o) => (o && optsDirtyRef.current) ? o : { width: d.width, height: d.height, ...d.options })
  }).catch((e) => setErr(e.message)), [id])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    api.models().then(setModels).catch(() => setModels({ reachable: false, models: [], samplers: [], upscalers: [] }))
    api.settings().then(setSt).catch(() => {})
  }, [])
  const active = p && ['scripting', 'generating'].includes(p.status)
  useEffect(() => { if (!active) return; const t = setInterval(() => { load(); onChanged() }, 2000); return () => clearInterval(t) }, [active, load, onChanged])

  if (!p) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner />{err || 'Loading…'}</div>
  const act = (fn) => async () => { setErr(''); try { setP(await fn()); onChanged() } catch (e) { setErr(e.message) } }
  const done = p.chunks.filter((c) => c.status === 'done').length
  const overall = p.chunks.length ? p.chunks.reduce((a, c) => a + (c.status === 'done' ? 1 : c.progress || 0), 0) / p.chunks.length : 0
  const direct = p.mode !== 'script'
  const isChar = p.mode === 'character'
  const isImage = p.mode === 'image' || isChar
  const steps = direct ? DIRECT_STEPS : STEPS
  const step = direct
    ? (p.status === 'done' ? 2 : ['generating', 'failed', 'cancelled'].includes(p.status) ? 1 : 0)
    : p.status === 'done' ? 3 : ['generating', 'failed', 'cancelled'].includes(p.status) && p.chunks.length ? 2 : 1
  const chunkFrames = Math.max(5, +(p.options.video.frames || 81)), fps = Math.max(1, +(p.options.video.fps || 16))
  const ph = st ? placeholders(st) : { image: {}, video: {} }
  const mv = opts ? { prompts: opts.prompts, image: opts.image, video: opts.video, style: opts.style, character: opts.character } : null
  const setMv = (v) => { setOpts({ ...opts, ...v }); optsDirtyRef.current = true; setOptsDirty(true) }
  const canEdit = !active
  const nLoras = opts ? [...opts.loras, ...(opts.extra_loras || [])].filter((l) => l.file).length : 0
  const running = p.chunks.find((c) => c.status === 'running')

  const optionsBody = () => ({ width: opts.width, height: opts.height, options: { seed_mode: opts.seed_mode, seed: opts.seed, loras: opts.loras, extra_loras: opts.extra_loras || [], ...toApiOptions(p.mode, mv) } })
  const saveOpts = async () => {
    setErr('')
    try {
      setP(await api.saveOptions(id, optionsBody()))
      optsDirtyRef.current = false; setOptsDirty(false); onChanged()
    } catch (e) { setErr(e.message) }
  }
  const start = async () => {   // unsaved edits are saved first so the run uses what's on screen
    if (optsDirtyRef.current && opts) { await api.saveOptions(id, optionsBody()); optsDirtyRef.current = false; setOptsDirty(false) }
    return api.approve(id)
  }

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{p.title}</h1>
            <Badge status={p.status} />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
            <span>{MODE_LABEL[p.mode] || p.mode}</span>{!isImage && <span>{p.duration}s</span>}<span>{p.width}×{p.height}</span>{!isImage && <span>{fps} fps</span>}
          </div>
        </div>
        <button onClick={async () => { if (confirm('Delete this project and all its files?')) { await api.remove(id); onDeleted() } }} className="btn btn-danger btn-sm"><Trash2 className="h-4 w-4" />Delete</button>
      </div>

      <div className="card card-pad"><Stepper steps={steps} current={step} failed={p.status === 'failed'} /></div>

      {err && <Alert onClose={() => setErr('')}>{err}</Alert>}
      {p.message && ['failed', 'cancelled', 'draft'].includes(p.status) && <Alert tone={p.status === 'cancelled' ? 'info' : 'danger'}>{p.message}</Alert>}

      {/* brief */}
      <div className="card card-pad space-y-4">
        <div className="section-title">{direct ? 'Prompts' : 'Brief'}</div>
        {mv && <StylePicker value={mv.style} onChange={(style) => setMv({ ...mv, style })} disabled={active} />}
        {direct && mv
          ? <PromptBlocks mode={p.mode} value={mv} onChange={setMv} disabled={active} />
          : <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/90">{p.prompt}</p>}
        {p.mode !== 't2v' && <div>
          <div className="label">{isChar ? 'Reference character image (optional)' : isImage ? 'Reference image' : p.mode === 'video' ? 'Start image' : 'Reference images'}</div>
          <div className="flex flex-wrap items-center gap-3">
            {p.refs.map((r, i) => (
              <div key={r.id} className="relative">
                <img src={media(`projects/${p.id}/refs/${r.filename}`)} className="h-20 w-28 rounded-lg border border-line object-cover" />
                {i === 0 && !isImage && <span className="absolute bottom-1 left-1 rounded bg-slate-900/70 px-1.5 py-0.5 text-[10px] font-medium text-white">Opening frame</span>}
                {canEdit && <button onClick={act(() => api.delRef(id, r.id))} className="absolute -right-2 -top-2 grid h-5 w-5 place-items-center rounded-full border border-line bg-surface text-muted shadow hover:text-danger"><X className="h-3 w-3" /></button>}
              </div>
            ))}
            {canEdit && <>
              <button onClick={() => fileRef.current.click()} className="grid h-20 w-28 place-items-center rounded-lg border-2 border-dashed border-line text-muted hover:bg-surface2"><ImagePlus className="h-5 w-5" /></button>
              <input ref={fileRef} type="file" multiple hidden accept="image/*" onChange={async (e) => { const fd = new FormData(); [...e.target.files].forEach((x) => fd.append('images', x)); await act(() => api.addRefs(id, fd))() }} />
            </>}
            {!p.refs.length && !canEdit && <span className="hint">{direct ? 'None.' : 'None — the opening frame is rendered from the script.'}</span>}
          </div>
        </div>}
      </div>

      {/* settings */}
      {opts && (
        <div className="card">
          <button onClick={() => setOptsOpen(!optsOpen)} className="flex w-full items-center justify-between px-5 py-4 text-left">
            <div><div className="section-title">Models &amp; generation settings</div>
              <div className="hint mt-0.5">{opts.width}×{opts.height} · {p.mode !== 'video' ? (opts.image.model || 'default image model') : ''}{p.mode === 't2v' ? ' → ' : ''}{!isImage ? (opts.video.model || 'default video model') : ''} · seed {opts.seed_mode}{opts.seed_mode !== 'random' ? ` ${opts.seed}` : ''}{!isImage ? ` · ${nLoras || 'no'} LoRA${nLoras === 1 ? '' : 's'}` : ''}</div></div>
            <ChevronDown className={`h-5 w-5 text-muted transition ${optsOpen ? 'rotate-180' : ''}`} />
          </button>
          {optsOpen && (
            <div className="space-y-6 border-t border-line p-5">
              <ModelBlocks mode={p.mode} value={mv} onChange={setMv} models={models} ph={ph} disabled={active} />
              <GenOptions value={opts} disabled={active} showLoras={!isImage} onChange={(o) => { setOpts({ ...opts, ...o }); optsDirtyRef.current = true; setOptsDirty(true) }} />
            </div>
          )}
        </div>
      )}
      {opts && optsDirty && !active && (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-warn-soft px-3.5 py-2.5">
          <span className="text-xs text-warn">Unsaved changes. They apply the next time you generate{direct && !isImage ? '; resume keeps finished chunks as they are' : ''}.</span>
          <button onClick={saveOpts} className="btn btn-primary btn-sm">Save settings</button>
        </div>
      )}

      {/* script */}
      {p.status === 'scripting' && (
        <div className="card card-pad flex items-center gap-3"><Spinner className="h-5 w-5 text-brand" />
          <div><div className="section-title">Writing your script…</div><div className="hint">{p.message || 'This usually takes under a minute.'}</div></div></div>
      )}
      {p.script && p.status !== 'scripting' && (
        <ScriptEditor key={p.updated} script={p.script} locked={p.status === 'generating'} onSave={(s) => act(() => api.saveScript(id, s))()} />
      )}

      {/* actions */}
      {['draft', 'script_ready', 'sample_ready', 'failed', 'cancelled', 'done'].includes(p.status) && (
        <div className="card card-pad space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            {isChar && !p.refs.length && <>
              {p.sample && <button onClick={act(async () => { if (optsDirtyRef.current && opts) { await api.saveOptions(id, optionsBody()); optsDirtyRef.current = false; setOptsDirty(false) } return api.confirmCharacter(id) })} className="btn btn-ok px-4 py-2.5"><Play className="h-4 w-4" />{p.status === 'done' ? 'Generate again' : 'Use this sample'} · {opts?.character?.count || 20} images</button>}
              <button onClick={act(start)} className={`btn px-4 py-2.5 ${p.sample ? 'btn-secondary' : 'btn-ok'}`}><RotateCcw className="h-4 w-4" />{p.sample ? 'New sample' : 'Generate sample image'}</button>
            </>}
            {direct && !(isChar && !p.refs.length) && <button onClick={act(start)} className="btn btn-ok px-4 py-2.5"><Play className="h-4 w-4" />{p.status === 'done' ? (isImage ? 'Generate again' : 'Regenerate video') : isChar ? `Generate ${opts?.character?.count || 20} character images` : isImage ? 'Generate image' : 'Generate video'}</button>}
            {!direct && p.script && <button onClick={act(start)} className="btn btn-ok px-4 py-2.5"><Play className="h-4 w-4" />{p.status === 'done' ? 'Regenerate video' : 'Approve script & generate video'}</button>}
            {!isImage && p.chunks.length > 0 && ['failed', 'cancelled'].includes(p.status) && <button onClick={act(() => api.resume(id))} className="btn btn-primary px-4 py-2.5"><RotateCcw className="h-4 w-4" />Resume · {done}/{p.chunks.length} chunks done</button>}
            {!direct && !p.script && <button onClick={act(() => api.genScript(id))} className="btn btn-primary"><Sparkles className="h-4 w-4" />Write script</button>}
          </div>
          {!direct && p.script && (
            <div className="flex flex-wrap gap-2">
              <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="Not quite right? Describe what to change, e.g. “make it more suspenseful, add a second character”"
                className="input min-w-[16rem] flex-1" onKeyDown={(e) => { if (e.key === 'Enter' && feedback) act(() => { const f = feedback; setFeedback(''); return api.genScript(id, f) })() }} />
              <button onClick={act(() => { const f = feedback; setFeedback(''); return api.genScript(id, f) })} className="btn btn-secondary">{feedback ? <><Send className="h-4 w-4" />Revise script</> : <><Sparkles className="h-4 w-4" />Rewrite script</>}</button>
            </div>
          )}
        </div>
      )}

      {isChar && !p.refs.length && p.sample && (
        <div className="card">
          <div className="border-b border-line px-5 py-4"><h2 className="section-title">Character sample</h2>
            <p className="hint mt-0.5">{p.status === 'sample_ready' ? 'Happy with this character? Confirm it and every image will be generated from it so the character stays the same. If not, generate a new sample, or adjust the description first.' : 'Reference used for all character images. To use your own picture instead, add a reference image above.'}</p></div>
          <div className="p-5"><img src={media(p.sample) + `?t=${p.updated}`} className="max-h-[28rem] rounded-lg border border-line bg-surface2" /></div>
        </div>
      )}

      {isImage && p.status === 'generating' && (
        <div className="card card-pad flex items-center justify-between gap-3">
          <div className="flex items-center gap-3"><Spinner className="h-5 w-5 text-brand" /><div><div className="section-title">Rendering…</div><div className="hint">{p.message}</div></div></div>
          <button onClick={() => api.cancel(id)} className="btn btn-secondary btn-sm"><Ban className="h-4 w-4" />Cancel</button>
        </div>
      )}

      {/* generation */}
      {p.chunks.length > 0 && (
        <div className="card">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div><h2 className="section-title">Generation</h2><p className="hint mt-0.5">{done} of {p.chunks.length} chunks · {chunkFrames} frames each · last frame seeds the next chunk</p></div>
            {p.status === 'generating' && <button onClick={() => api.cancel(id)} className="btn btn-secondary btn-sm"><Ban className="h-4 w-4" />Cancel</button>}
          </div>
          <div className="space-y-5 p-5">
            <div>
              <div className="mb-1.5 flex justify-between text-xs"><span className="text-muted">{p.status === 'generating' ? (running ? `Rendering chunk ${running.idx + 1}…` : p.message) : 'Overall progress'}</span><span className="font-semibold">{Math.round(overall * 100)}%</span></div>
              <ProgressBar value={overall} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {p.chunks.map((c) => (
                <div key={c.id} className="overflow-hidden rounded-xl border border-line">
                  <div className="flex items-center justify-between gap-2 px-3.5 py-2.5">
                    <div className="min-w-0"><div className="text-sm font-medium">Chunk {c.idx + 1}</div>
                      <div className="truncate text-[11px] text-muted">{direct ? '' : `Scene ${c.scene_idx + 1} · `}{c.keep_frames} frames{c.seed != null ? ` · seed ${c.seed}` : ''}</div></div>
                    <Badge status={c.status} />
                  </div>
                  {c.status === 'running' && <div className="px-3.5 pb-3"><ProgressBar value={c.progress} className="h-1.5" /></div>}
                  {c.status === 'done' && <video src={media(c.video_path)} controls preload="metadata" className="w-full bg-black" />}
                  {c.error && <div className="px-3.5 pb-3 text-xs text-danger">{c.error}</div>}
                  {canEdit && (
                    <div className="space-y-2 border-t border-line px-3.5 py-2.5">
                      {c.status !== 'done' && (
                        <textarea key={c.prompt} defaultValue={c.prompt} rows={4} className="input w-full text-xs"
                          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== c.prompt) act(() => api.setChunkPrompt(id, c.idx, v))() }} />
                      )}
                      <button onClick={() => { if (confirm(`Discard chunk ${c.idx + 1}${c.idx < p.chunks.length - 1 ? ' and all later chunks' : ''} and render again?`)) act(() => api.resetChunks(id, c.idx))() }}
                        className="btn btn-secondary btn-sm"><RotateCcw className="h-4 w-4" />Redo from here</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {p.images?.length > 0 && (
        <div className="card">
          <div className="border-b border-line px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="section-title">{isChar ? `Character images (${p.images.length}${p.status === 'generating' ? ` of ${p.options.character.count}` : ''})` : p.images.length === 1 ? 'Image' : 'Images'}</h2>
              {isChar && <p className="hint mt-0.5">Train a LoRA on these (Draw Things → LoRA training, kohya or ai-toolkit). Delete bad ones before training: the zip has each image with a caption .txt.</p>}</div>
            {isChar && <a href={`/api/projects/${p.id}/dataset.zip`} download className="btn btn-primary btn-sm"><Archive className="h-4 w-4" />Download dataset (zip)</a>}
          </div></div>
          <div className={`grid gap-4 p-5 ${isChar ? 'sm:grid-cols-3 lg:grid-cols-4' : 'sm:grid-cols-2'}`}>
            {p.images.map((src) => (
              <div key={src} className="space-y-2">
                <img src={media(src) + `?t=${p.updated}`} className="w-full rounded-lg border border-line bg-surface2" />
                <a href={media(src)} download className="btn btn-secondary btn-sm"><Download className="h-4 w-4" />Download PNG</a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* result */}
      {p.video_path && (
        <div className="card">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <h2 className="section-title">Final video</h2>
            <a href={media(p.video_path)} download className="btn btn-secondary btn-sm"><Download className="h-4 w-4" />Download MP4</a>
          </div>
          <div className="p-5"><video src={media(p.video_path) + `?t=${p.updated}`} controls className="w-full rounded-lg bg-black" /></div>
        </div>
      )}
    </div>
  )
}
