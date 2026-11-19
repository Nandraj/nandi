import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, Wand2 } from 'lucide-react'
import { api } from '../api'
import { Spinner } from '../ui'
import { LoraEditor } from './GenOptions'

/** Advanced Draw Things configuration fields: [key, label, type, placeholder/default, video-only?] grouped for display. */
const ADV = [
  ['Upscaling & quality', [
    ['hires_fix', 'High-res fix', 'bool'], ['hires_fix_start_width', 'Hires start width (px)', 'num', 0], ['hires_fix_start_height', 'Hires start height (px)', 'num', 0],
    ['hires_fix_strength', 'Hires strength', 'num', 0.7], ['upscaler', 'Upscaler', 'upscaler'], ['upscaler_scale_factor', 'Upscaler scale (0 = model default, 2, 4)', 'num', 0],
    ['face_restoration', 'Face restoration model (file)', 'text'], ['sharpness', 'Sharpness', 'num', 0],
    ['clip_weight', 'Text-encoder weight', 'num', 1], ['image_guidance_scale', 'Image guidance (edit models)', 'num', 1.5],
  ]],
  ['Sampling', [
    ['zero_negative_prompt', 'Zero negative prompt', 'bool'], ['stochastic_sampling_gamma', 'Stochastic sampling γ', 'num', 0.3],
    ['resolution_dependent_shift', 'Resolution-dependent shift', 'bool'], ['cfg_zero_star', 'CFG zero-star', 'bool'], ['cfg_zero_init_steps', 'CFG zero-init steps', 'num', 0],
    ['speed_up_with_guidance_embed', 'Speed up with guidance embed', 'bool'], ['guidance_embed', 'Guidance embed (Flux-style)', 'num', 3.5],
    ['stage_2_steps', 'Stage-2 steps', 'num', 10], ['stage_2_cfg', 'Stage-2 CFG', 'num', 1], ['stage_2_shift', 'Stage-2 shift', 'num', 1],
    ['t5_text_encoder', 'Use T5 text encoder', 'bool'],
  ]],
  ['Speed — TeaCache', [
    ['tea_cache', 'TeaCache', 'bool'], ['tea_cache_start', 'Start step', 'num', 5], ['tea_cache_end', 'End step (-1 = last)', 'num', -1],
    ['tea_cache_threshold', 'Threshold', 'num', 0.06], ['tea_cache_max_skip_steps', 'Max skipped steps', 'num', 3],
  ]],
  ['Memory — tiling', [
    ['tiled_decoding', 'Tiled decoding', 'bool'], ['decoding_tile_width', 'Decode tile width', 'num', 10], ['decoding_tile_height', 'Decode tile height', 'num', 10], ['decoding_tile_overlap', 'Decode overlap', 'num', 2],
    ['tiled_diffusion', 'Tiled diffusion', 'bool'], ['diffusion_tile_width', 'Diffusion tile width', 'num', 16], ['diffusion_tile_height', 'Diffusion tile height', 'num', 16], ['diffusion_tile_overlap', 'Diffusion overlap', 'num', 2],
  ]],
  ['Video conditioning (SVD-style models)', [
    ['fps_id', 'FPS id', 'num', 5], ['motion_bucket_id', 'Motion bucket', 'num', 127], ['cond_aug', 'Conditioning noise', 'num', 0.02], ['start_frame_cfg', 'Start-frame CFG', 'num', 1],
  ], 'video'],
]

const NUM_FIELDS = (kind, hideCount) => [
  ['steps', 'Steps'], ['cfg', 'Guidance (CFG)'], ['shift', 'Shift'], ['clip_skip', 'CLIP skip'],
  ['strength', kind === 'image' ? 'Strength (with reference image)' : 'Strength'],
  ...(kind === 'image' ? (hideCount ? [] : [['count', 'Number of images']]) : [['frames', 'Frames per chunk'], ['fps', 'Output fps']]),
]

const inList = (list, f) => list.some((m) => m.file === f)

function ModelSelect({ models, kind, value, onChange, empty, allowEmpty = true }) {
  const [custom, setCustom] = useState(false)
  const own = models.filter((m) => m.kind === kind), other = models.filter((m) => m.kind !== kind)
  if (custom || (value && !inList(models, value))) {
    return (
      <div className="flex gap-2">
        <input className="input" placeholder="model file, e.g. my_model_q8p.ckpt" value={value} onChange={(e) => onChange(e.target.value.trim())} />
        {models.length > 0 && <button type="button" className="btn btn-secondary" onClick={() => { setCustom(false); onChange('') }}>List</button>}
      </div>
    )
  }
  const opt = (m) => <option key={m.file} value={m.file}>{m.name === m.file ? m.file : `${m.name} — ${m.file}`}</option>
  return (
    <select className="input" value={value || ''} onChange={(e) => (e.target.value === '__custom' ? setCustom(true) : onChange(e.target.value))}>
      {allowEmpty && <option value="">{empty}</option>}
      {own.length > 0 && <optgroup label={kind === 'image' ? 'Image models' : 'Video models'}>{own.map(opt)}</optgroup>}
      {other.length > 0 && <optgroup label={kind === 'image' ? 'Other models (video etc.)' : 'Other models (image etc.)'}>{other.map(opt)}</optgroup>}
      <option value="__custom">Other file name…</option>
    </select>
  )
}

function AdvField({ spec, value, onChange, upscalers }) {
  const [key, label, type, def] = spec
  const set = (v) => onChange(v === '' || v === undefined ? undefined : v)
  return (
    <div>
      <label className="label">{label}</label>
      {type === 'bool'
        ? <select className="input" value={value === undefined ? '' : value ? '1' : '0'} onChange={(e) => set(e.target.value === '' ? undefined : e.target.value === '1')}>
            <option value="">Model default</option><option value="1">On</option><option value="0">Off</option></select>
        : type === 'upscaler'
          ? <select className="input" value={value || ''} onChange={(e) => set(e.target.value)}>
              <option value="">None</option>{upscalers.map((u) => <option key={u.file} value={u.file}>{u.name}</option>)}
              {value && !upscalers.some((u) => u.file === value) && <option value={value}>{value}</option>}</select>
          : <input className="input" type={type === 'num' ? 'number' : 'text'} step="any" placeholder={def !== undefined ? `default ${def}` : 'default'}
              value={value ?? ''} onChange={(e) => set(type === 'num' ? (e.target.value === '' ? '' : +e.target.value) : e.target.value)} />}
    </div>
  )
}

/**
 * Model + sampling settings for one stage (`kind` = 'image' | 'video').
 * `value` holds only what the user set; empty fields fall back to Settings (`ph` supplies the placeholders).
 */
export default function ModelPanel({ kind, value, onChange, models, ph = {}, disabled, hideCount }) {
  const [advOpen, setAdvOpen] = useState(false)
  const [lorasResp, setLorasResp] = useState({ loras: [] })
  useEffect(() => { if (kind === 'image') api.loras().then(setLorasResp).catch(() => setLorasResp({ loras: [], reachable: false })) }, [kind])
  const list = models?.models || []
  const set = (patch) => onChange({ ...value, ...patch })
  const clean = (patch) => {   // drop emptied keys so Settings defaults apply again
    const next = { ...value, ...patch }
    Object.keys(next).forEach((k) => { if (k !== 'refiner' && (next[k] === '' || next[k] === undefined)) delete next[k] })
    onChange(next)
  }
  const pick = (file) => {
    const m = list.find((x) => x.file === file)
    if (!file) { onChange({ adv: value.adv, ...(kind === 'image' ? { loras: value.loras } : {}) }); return }
    const p = m?.preset || {}
    const next = { ...value, model: file }
    for (const k of ['steps', 'cfg', 'shift', 'sampler', ...(kind === 'video' ? ['frames', 'fps', 'refiner_start'] : [])]) if (p[k] !== undefined) next[k] = p[k]
    if (kind === 'video') next.refiner = p.refiner || ''
    onChange(next)
  }
  const adv = value.adv || {}
  const setAdv = (k, v) => { const a = { ...adv }; if (v === undefined) delete a[k]; else a[k] = v; set({ adv: a }) }
  const nAdv = Object.keys(adv).length
  const preset = useMemo(() => list.find((m) => m.file === value.model)?.preset, [list, value.model])

  return (
    <fieldset disabled={disabled} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label">{kind === 'image' ? 'Image model' : 'Video model'}</label>
          <ModelSelect models={list} kind={kind} value={value.model} onChange={pick} empty={`Default (${ph.model || 'from Settings'})`} />
        </div>
        {kind === 'video' && (
          <div>
            <label className="label">Refiner <span className="font-normal text-muted">(low-noise expert, optional)</span></label>
            <ModelSelect models={list} kind="video" value={value.refiner ?? ''} onChange={(v) => set({ refiner: v })} empty={value.model ? 'None' : `Default (${ph.refiner || 'from Settings'})`} allowEmpty />
          </div>
        )}
      </div>
      {models && !models.reachable && <p className="hint text-warn">Draw Things isn’t reachable, so the model list is empty — type a model file name or start its API server.</p>}
      {models?.reachable && !list.length && <p className="hint text-warn">Draw Things isn’t sharing its model list. Turn on <b>Enable Model Browsing</b> in its API Server settings.</p>}
      {preset && <p className="hint">Defaults for this model were applied (steps {preset.steps}, CFG {preset.cfg}, shift {preset.shift}). They’re starting points — adjust freely.</p>}

      <div className="grid gap-3 sm:grid-cols-3">
        {NUM_FIELDS(kind, hideCount).map(([k, label]) => (
          <div key={k}><label className="label">{label}</label>
            <input className="input" type="number" step="any" placeholder={ph[k] !== undefined ? `default ${ph[k]}` : 'default'} value={value[k] ?? ''}
              onChange={(e) => clean({ [k]: e.target.value === '' ? '' : +e.target.value })} /></div>
        ))}
        <div><label className="label">Sampler</label>
          <select className="input" value={value.sampler || ''} onChange={(e) => clean({ sampler: e.target.value })}>
            <option value="">Default{ph.sampler ? ` (${ph.sampler})` : ''}</option>
            {(models?.samplers || []).map((x) => <option key={x}>{x}</option>)}
          </select></div>
        {kind === 'video' && <div><label className="label">Refiner start (0–1)</label>
          <input className="input" type="number" step="any" min={0} max={1} placeholder={`default ${ph.refiner_start ?? 0.1}`} value={value.refiner_start ?? ''}
            onChange={(e) => clean({ refiner_start: e.target.value === '' ? '' : +e.target.value })} /></div>}
      </div>

      {kind === 'image' && <LoraEditor value={value.loras} onChange={(loras) => set({ loras })} resp={lorasResp} title="Image LoRAs" hint={false} />}

      <div className="rounded-xl border border-line">
        <button type="button" onClick={() => setAdvOpen(!advOpen)} className="flex w-full items-center justify-between px-4 py-3 text-left">
          <div><div className="text-sm font-semibold">Advanced Draw Things options</div>
            <div className="hint">{nAdv ? `${nAdv} customised` : 'hires fix, upscaler, TeaCache, tiling, stage 2… (empty = model default)'}</div></div>
          <ChevronDown className={`h-5 w-5 text-muted transition ${advOpen ? 'rotate-180' : ''}`} />
        </button>
        {advOpen && (
          <div className="space-y-5 border-t border-line p-4">
            {ADV.filter(([, , only]) => !only || only === kind).map(([group, fields]) => (
              <div key={group} className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">{group}</div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {fields.map((f) => <AdvField key={f[0]} spec={f} value={adv[f[0]]} onChange={(v) => setAdv(f[0], v)} upscalers={models?.upscalers || []} />)}
                </div>
              </div>
            ))}
            {nAdv > 0 && <button type="button" className="btn btn-secondary btn-sm" onClick={() => set({ adv: {} })}>Reset advanced options</button>}
          </div>
        )}
      </div>
    </fieldset>
  )
}

/** Prompt textarea with an optional “Enhance with LLM” button. */
export function PromptBox({ label, value, onChange, placeholder, rows = 4, kind, required, disabled, hint }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const enhance = async () => {
    setBusy(true); setErr('')
    try { onChange((await api.enhance(value, kind)).prompt) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label className="label !mb-0">{label}</label>
        {kind && <button type="button" onClick={enhance} disabled={busy || disabled || !value.trim()} className="btn btn-ghost btn-sm">{busy ? <Spinner /> : <Wand2 className="h-4 w-4" />}Enhance</button>}
      </div>
      <textarea required={required} disabled={disabled} rows={rows} className="input resize-y" value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      {hint && <p className="hint mt-1">{hint}</p>}
      {err && <p className="mt-1 text-xs text-danger">{err}</p>}
    </div>
  )
}
