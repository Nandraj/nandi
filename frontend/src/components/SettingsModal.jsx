import { useEffect, useState } from 'react'
import { api } from '../api'
import { Alert, Modal, Spinner } from '../ui'
import { Plug } from 'lucide-react'
import GenOptions, { resolveLoras } from './GenOptions'

const SAMPLERS = ['DPMPP2MKarras', 'EulerA', 'DDIM', 'PLMS', 'DPMPPSDEKarras', 'UniPC', 'LCM', 'EulerASubstep', 'DPMPPSDESubstep', 'TCD', 'EulerATrailing', 'DPMPPSDETrailing', 'DPMPP2MAYS', 'EulerAAYS', 'DPMPPSDEAYS', 'DPMPP2MTrailing', 'DDIMTrailing', 'UniPCTrailing', 'UniPCAYS', 'TCDTrailing']
const PRESETS = [
  ['Ollama (local)', 'ollama', 'http://localhost:11434'],
  ['llama.cpp server (local)', 'openai', 'http://127.0.0.1:8080'],
  ['LM Studio (local)', 'openai', 'http://localhost:1234/v1'],
  ['OpenAI', 'openai', 'https://api.openai.com/v1'],
  ['Anthropic (Claude)', 'anthropic', 'https://api.anthropic.com'],
  ['OpenRouter', 'openai', 'https://openrouter.ai/api/v1'],
  ['Groq', 'openai', 'https://api.groq.com/openai/v1'],
  ['DeepSeek', 'openai', 'https://api.deepseek.com'],
  ['Together AI', 'openai', 'https://api.together.xyz/v1'],
  ['Mistral', 'openai', 'https://api.mistral.ai/v1'],
  ['Google Gemini', 'openai', 'https://generativelanguage.googleapis.com/v1beta/openai'],
]
const PROVIDERS = { ollama: 'Ollama API', openai: 'OpenAI-compatible API', anthropic: 'Anthropic API' }

const TABS = {
  connections: ['Connections', [
    ['Draw Things (gRPC)', [['dt_host', 'Host'], ['dt_port', 'Port', 'number'], ['dt_tls', 'Use TLS', 'bool'], ['dt_secret', 'Shared secret (if set in Draw Things)', 'password']]],
  ]],
  video: ['Video model', [
    ['Wan 2.2 I2V A14B', [['hne_model', 'High-noise expert (model)'], ['lne_model', 'Low-noise expert (refiner)'], ['refiner_start', 'Refiner start (0–1)', 'number'], ['steps', 'Steps', 'number'], ['cfg', 'Guidance (CFG)', 'number'], ['shift', 'Shift', 'number'], ['sampler', 'Sampler', 'sampler'], ['negative_prompt', 'Negative prompt', 'area']]],
    ['Lightning LoRAs — used when a “lightning” LoRA is active', [['lightning_steps', 'Steps', 'number'], ['lightning_cfg', 'CFG', 'number']]],
    ['First-frame model — used when there is no reference image', [['keyframe_model', 'Text-to-image model'], ['keyframe_steps', 'Steps', 'number'], ['keyframe_cfg', 'CFG', 'number'], ['keyframe_shift', 'Shift', 'number'], ['keyframe_sampler', 'Sampler', 'sampler']]],
  ]],
  defaults: ['New-project defaults', []],
}

export default function SettingsModal({ onClose, health }) {
  const [s, setS] = useState(null)
  const [tab, setTab] = useState(() => (location.hash.split('/')[1] in TABS ? location.hash.split('/')[1] : 'connections'))
  const [busy, setBusy] = useState(false)
  const [test, setTest] = useState(null)
  const [testing, setTesting] = useState(false)
  const [dtModels, setDtModels] = useState([])
  useEffect(() => { api.models().then((m) => setDtModels(m.models || [])).catch(() => {}) }, [])
  useEffect(() => { Promise.all([api.settings(), api.loras().catch(() => null)]).then(([st, lr]) => setS({ ...st, loras: resolveLoras(st.loras, lr) })) }, [])
  const files = health?.drawthings?.files || {}
  const runTest = async () => {
    setTesting(true); setTest(null)
    try { setTest(await api.testLlm({ llm_provider: s.llm_provider, llm_base_url: s.llm_base_url, llm_model: s.llm_model, llm_api_key: s.llm_api_key })) }
    catch (e) { setTest({ ok: false, error: e.message, models: [] }) }
    setTesting(false)
  }
  const modelList = test?.models?.length ? test.models : (health?.ollama?.models || [])
  const llmBlock = !s ? null : (
    <section className="space-y-3">
      <h3 className="section-title">Script writer (LLM)</h3>
      <p className="hint">Connect any provider: a local server (Ollama, llama.cpp, LM Studio) or a hosted API. Writes the movie script.</p>
      <div><label className="label">Quick fill</label>
        <select className="input" value="" onChange={(e) => { const x = PRESETS[+e.target.value]; if (x) { setS({ ...s, llm_provider: x[1], llm_base_url: x[2] }); setTest(null) } }}>
          <option value="">Choose a provider preset…</option>
          {PRESETS.map((x, i) => <option key={x[0]} value={i}>{x[0]}</option>)}
        </select></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label">API type</label>
          <select className="input" value={s.llm_provider} onChange={(e) => { setS({ ...s, llm_provider: e.target.value }); setTest(null) }}>
            {Object.entries(PROVIDERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label className="label">Base URL</label>
          <input className="input" value={s.llm_base_url} onChange={(e) => setS({ ...s, llm_base_url: e.target.value })} placeholder="https://api.openai.com/v1" /></div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label">Model name</label>
          <input className="input" list="llm-models" value={s.llm_model} onChange={(e) => setS({ ...s, llm_model: e.target.value })} placeholder="e.g. gpt-4o-mini" />
          <datalist id="llm-models">{modelList.map((m) => <option key={m} value={m} />)}</datalist></div>
        <div><label className="label">API key <span className="font-normal">(only if required)</span></label>
          <input className="input" type="password" autoComplete="off" value={s.llm_api_key} onChange={(e) => setS({ ...s, llm_api_key: e.target.value })} placeholder="sk-…" /></div>
      </div>
      <div className="flex items-center gap-3">
        <button type="button" onClick={runTest} disabled={testing} className="btn btn-secondary btn-sm">{testing ? <Spinner /> : <Plug className="h-4 w-4" />}Test connection</button>
        {test?.ok && <span className="text-xs text-ok">● Connected · {test.models.length} model{test.models.length === 1 ? '' : 's'} found{test.models.length && test.model_present === false ? ' — selected model not in list' : ''}</span>}
      </div>
      {test && !test.ok && <Alert>{test.error}</Alert>}
      <p className="hint">The key is stored only in this app’s local database and is never sent anywhere except your provider.</p>
    </section>
  )
  const save = async () => { setBusy(true); await api.saveSettings(s); onClose() }

  const field = ([k, label, t]) => (
    <div key={k} className={t === 'bool' ? 'flex items-center justify-between rounded-lg border border-line px-3 py-2.5' : ''}>
      <label className={t === 'bool' ? 'text-sm font-medium' : 'label'}>{label}
        {files[s[k]] !== undefined && <span className={`ml-2 font-normal ${files[s[k]] ? 'text-ok' : 'text-danger'}`}>● {files[s[k]] ? 'found on server' : 'not on server'}</span>}
      </label>
      {t === 'bool' ? <input type="checkbox" className="h-4 w-4" checked={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.checked })} />
        : t === 'ollama' && health?.ollama?.models?.length
          ? <select className="input" value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })}>
              {[...new Set([s[k], ...health.ollama.models])].map((x) => <option key={x} value={x}>{x}{health.ollama.models.includes(x) ? '' : ' (not installed)'}</option>)}
            </select>
          : t === 'provider' ? <select className="input" value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value, ...(e.target.value === 'ollama' && !s.ollama_url ? { ollama_url: 'http://localhost:11434' } : {}) })}>
              <option value="ollama">Ollama</option><option value="openai">OpenAI-compatible (llama.cpp, LM Studio, vLLM…)</option></select>
          : t === 'sampler' ? <select className="input" value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })}>{SAMPLERS.map((x) => <option key={x}>{x}</option>)}</select>
          : t === 'area' ? <textarea rows={3} className="input text-xs" value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })} />
          : <input className="input" list={/_model$/.test(k) ? 'dt-models' : undefined} type={t === 'number' ? 'number' : t === 'password' ? 'password' : 'text'} step="any" value={s[k]} onChange={(e) => setS({ ...s, [k]: t === 'number' ? +e.target.value : e.target.value })} />}
    </div>
  )

  return (
    <Modal title="Settings" onClose={onClose} wide
      footer={<><button onClick={onClose} className="btn btn-secondary">Cancel</button><button onClick={save} disabled={!s || busy} className="btn btn-primary">{busy && <Spinner />}Save changes</button></>}>
      {!s ? <div className="flex items-center gap-2 text-sm text-muted"><Spinner />Loading…</div> : (
        <div className="grid gap-6 md:grid-cols-[11rem_1fr]">
          <nav className="flex gap-1 overflow-x-auto md:flex-col">
            {Object.entries(TABS).map(([k, [label]]) => (
              <button key={k} onClick={() => setTab(k)} className={`whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium ${tab === k ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface2 hover:text-ink'}`}>{label}</button>
            ))}
          </nav>
          <div className="space-y-6">
            <datalist id="dt-models">{dtModels.map((m) => <option key={m.file} value={m.file}>{m.name}</option>)}</datalist>
            {tab === 'defaults'
              ? <>
                  <p className="hint">Starting values for every new project. Each project can still override them.</p>
                  <GenOptions showSize={false} value={{ seed_mode: s.seed_mode, seed: s.seed, loras: s.loras }} onChange={(o) => setS({ ...s, seed_mode: o.seed_mode, seed: o.seed, loras: o.loras })} />
                </>
              : <>{tab === 'connections' && llmBlock}{TABS[tab][1].map(([group, fs]) => (
                  <section key={group} className="space-y-3"><h3 className="section-title">{group}</h3>{fs.map(field)}</section>
                ))}</>}
          </div>
        </div>
      )}
    </Modal>
  )
}
