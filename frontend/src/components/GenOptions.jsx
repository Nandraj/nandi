import { useEffect, useState } from 'react'
import { Dices, Minus, Plus, X } from 'lucide-react'
import { api } from '../api'
import { Alert, Segmented } from '../ui'

export const PRESETS = {
  '832x448': '832×448 · landscape', '832x1216': '832×1216 · tall (full body)', '1024x576': '1024×576 · 16:9', '448x832': '448×832 · portrait', '640x640': '640×640 · square',
  '512x512': '512×512 · square', '768x768': '768×768 · square', '1024x1024': '1024×1024 · square', '1280x704': '1280×704 · wide', '704x1280': '704×1280 · tall', custom: 'Custom…',
}
const EMPTY = { file: '', weight: 1, mode: 'all' }
const snap = (n) => Math.min(2048, Math.max(256, Math.round((+n || 64) / 64) * 64))

/** LoRA state for a new project/settings: saved list if configured, else the auto-detected Lightning pair. */
export function resolveLoras(saved, loraResp) {
  if (Array.isArray(saved)) return [saved[0] || { ...EMPTY }, saved[1] || { ...EMPTY }]
  const d = loraResp?.defaults || {}
  return [
    d.lora1 ? { file: d.lora1, weight: 1, mode: 'base' } : { ...EMPTY },
    d.lora2 ? { file: d.lora2, weight: 1, mode: 'refiner' } : { ...EMPTY },
  ]
}

function LoraSelect({ list, value, onChange }) {
  const inList = list.some((l) => l.file === value)
  const [custom, setCustom] = useState(false)
  if (!list.length || custom || (value && !inList)) {
    return (
      <div className="flex gap-2">
        <input className="input" placeholder="file name, e.g. my_lora_f16.ckpt (empty = none)" value={value} onChange={(e) => onChange(e.target.value.trim())} />
        {list.length > 0 && <button type="button" className="btn btn-secondary" onClick={() => { setCustom(false); onChange('') }}>List</button>}
      </div>
    )
  }
  return (
    <select className="input" value={value} onChange={(e) => (e.target.value === '__custom' ? setCustom(true) : onChange(e.target.value))}>
      <option value="">None (disabled)</option>
      {list.map((l) => <option key={l.file} value={l.file}>{l.name === l.file ? l.file : l.name}</option>)}
      <option value="__custom">Other file name…</option>
    </select>
  )
}


/** Up to two LoRAs (file, weight, mode). `resp` is the /api/loras response. */
export function LoraEditor({ value, onChange, disabled, resp, title = 'LoRAs', hint = true }) {
  const [showSecond, setShowSecond] = useState(false)
  const list = [value?.[0] || EMPTY, value?.[1] || EMPTY]
  const setLora = (i, patch) => onChange(list.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const second = showSecond || !!list[1].file
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="section-title">{title} <span className="font-normal text-muted">— optional</span></legend>
      {[0, 1].slice(0, second ? 2 : 1).map((i) => {
        const l = list[i]
        return (
          <div key={i} className="space-y-3 rounded-xl border border-line bg-surface2/50 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">LoRA {i + 1}</span>
              {i === 0 && !second && <button type="button" title="Add LoRA 2" onClick={() => setShowSecond(true)} className="btn btn-secondary btn-sm"><Plus className="h-4 w-4" />Add LoRA 2</button>}
              {i === 1 && <button type="button" title="Remove LoRA 2" onClick={() => { setLora(1, { file: '' }); setShowSecond(false) }} className="btn btn-secondary btn-sm"><Minus className="h-4 w-4" />Remove</button>}
            </div>
            <LoraSelect list={resp.loras} value={l.file} onChange={(file) => setLora(i, { file })} />
            <div>
              <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-muted">Weight</span><span className="font-semibold text-ink">{Math.round(l.weight * 100)}%</span></div>
              <input type="range" min={0} max={200} step={5} disabled={!l.file} value={Math.round(l.weight * 100)} onChange={(e) => setLora(i, { weight: +e.target.value / 100 })} className="w-full" />
            </div>
            <Segmented className="w-full" value={l.mode} disabled={!l.file} onChange={(mode) => setLora(i, { mode })} options={[['base', 'Base'], ['refiner', 'Refiner'], ['all', 'All']]} />
          </div>
        )
      })}
      {resp.reachable === false && <Alert tone="warn">Draw Things isn’t reachable on its gRPC port, so the LoRA list is unavailable. Start its API server, then reopen this panel. You can still type a file name.</Alert>}
      {resp.reachable && !resp.browsing && !resp.loras.length && <Alert tone="warn">Draw Things connected but isn’t sharing its model list. Turn on <b>Enable Model Browsing</b> in its API Server settings, then reopen this panel.</Alert>}
      {hint && <p className="hint">Base applies to the high-noise expert only (or the only model), Refiner to the low-noise expert only. With a “Lightning” LoRA and no explicit steps/CFG, the app uses the Lightning steps and CFG from Settings.</p>}
    </fieldset>
  )
}

/** Any number of additional LoRAs (e.g. trained character LoRAs) on top of the two fixed slots above. */
export function ExtraLoraEditor({ value, onChange, disabled, resp }) {
  const list = value || []
  const setLora = (i, patch) => onChange(list.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="section-title">Additional LoRAs <span className="font-normal text-muted">— e.g. character LoRAs, optional</span></legend>
      {list.map((l, i) => (
        <div key={i} className="space-y-3 rounded-xl border border-line bg-surface2/50 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold">Extra LoRA {i + 1}</span>
            <button type="button" title="Remove" onClick={() => onChange(list.filter((_, j) => j !== i))} className="btn btn-secondary btn-sm"><X className="h-4 w-4" />Remove</button>
          </div>
          <LoraSelect list={resp.loras} value={l.file} onChange={(file) => setLora(i, { file })} />
          <div>
            <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-muted">Weight</span><span className="font-semibold text-ink">{Math.round(l.weight * 100)}%</span></div>
            <input type="range" min={0} max={200} step={5} disabled={!l.file} value={Math.round(l.weight * 100)} onChange={(e) => setLora(i, { weight: +e.target.value / 100 })} className="w-full" />
          </div>
          <Segmented className="w-full" value={l.mode} disabled={!l.file} onChange={(mode) => setLora(i, { mode })} options={[['base', 'Base'], ['refiner', 'Refiner'], ['all', 'All']]} />
        </div>
      ))}
      <button type="button" onClick={() => onChange([...list, { ...EMPTY }])} className="btn btn-secondary btn-sm"><Plus className="h-4 w-4" />Add LoRA</button>
      <p className="hint">Applied together with the LoRAs above. A character LoRA trained for Wan 2.2 A14B usually comes as a high-noise and a low-noise file: add both, set the first to <b>Base</b> and the second to <b>Refiner</b>. A single-file LoRA: use <b>All</b>.</p>
    </fieldset>
  )
}

export default function GenOptions({ value, onChange, disabled, showSize = true, showLoras = true }) {
  const [resp, setResp] = useState({ loras: [], source: '' })
  useEffect(() => { api.loras().then(setResp).catch(() => setResp({ loras: [], source: 'none' })) }, [])
  const [preset, setPreset] = useState(PRESETS[`${value.width}x${value.height}`] ? `${value.width}x${value.height}` : 'custom')
  const set = (patch) => onChange({ ...value, ...patch })

  return (
    <div className="space-y-6">
      {showSize && (
        <fieldset disabled={disabled} className="space-y-3">
          <legend className="section-title">Frame size</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            <div><label className="label">Preset</label>
              <select className="input" value={preset} onChange={(e) => {
                setPreset(e.target.value)
                if (e.target.value !== 'custom') { const [w, h] = e.target.value.split('x').map(Number); set({ width: w, height: h }) }
              }}>{Object.entries(PRESETS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
            <div><label className="label">Width (px)</label>
              <input className="input" type="number" step={64} value={value.width} onChange={(e) => { setPreset('custom'); set({ width: +e.target.value }) }} onBlur={() => set({ width: snap(value.width) })} /></div>
            <div><label className="label">Height (px)</label>
              <input className="input" type="number" step={64} value={value.height} onChange={(e) => { setPreset('custom'); set({ height: +e.target.value }) }} onBlur={() => set({ height: snap(value.height) })} /></div>
          </div>
          <p className="hint">Multiples of 64, between 256 and 2048. Larger frames are much slower and need far more memory.</p>
        </fieldset>
      )}

      <fieldset disabled={disabled} className="space-y-3">
        <legend className="section-title">Seed</legend>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <div><label className="label">Mode</label>
            <select className="input" value={value.seed_mode} onChange={(e) => set({ seed_mode: e.target.value })}>
              <option value="random">Random for every chunk</option>
              <option value="fixed">Fixed — same for all chunks</option>
              <option value="increment">Fixed + chunk number</option>
            </select></div>
          {value.seed_mode !== 'random' && <>
            <div><label className="label">Seed</label>
              <input className="input" type="number" min={0} max={4294967295} value={value.seed} onChange={(e) => set({ seed: Math.max(0, Math.min(4294967295, Math.floor(+e.target.value || 0))) })} /></div>
            <button type="button" onClick={() => set({ seed: Math.floor(Math.random() * 4294967295) })} className="btn btn-secondary"><Dices className="h-4 w-4" />Randomize</button>
          </>}
        </div>
      </fieldset>

      {showLoras && <LoraEditor value={value.loras} onChange={(loras) => set({ loras })} disabled={disabled} resp={resp} title="LoRAs" />}
      {showLoras && value.extra_loras !== undefined && <ExtraLoraEditor value={value.extra_loras} onChange={(extra_loras) => set({ extra_loras })} disabled={disabled} resp={resp} />}
    </div>
  )
}
