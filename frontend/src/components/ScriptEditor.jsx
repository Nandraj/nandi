import { useState } from 'react'
import { Save } from 'lucide-react'

const COLORS = ['bg-brand', 'bg-info', 'bg-ok', 'bg-warn', 'bg-danger', 'bg-fuchsia-500']

export default function ScriptEditor({ script, onSave, locked }) {
  const [s, setS] = useState(script)
  const [dirty, setDirty] = useState(false)
  const upd = (patch) => { setS({ ...s, ...patch }); setDirty(true) }
  const updScene = (i, patch) => upd({ scenes: s.scenes.map((x, j) => (j === i ? { ...x, ...patch } : x)) })
  const updChar = (i, patch) => upd({ characters: s.characters.map((x, j) => (j === i ? { ...x, ...patch } : x)) })
  const total = s.scenes.reduce((a, x) => a + (+x.duration_sec || 0), 0)

  return (
    <div className="card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div><h2 className="section-title">Script</h2><p className="hint mt-0.5">{s.scenes.length} scenes · {total.toFixed(1)}s total — edit anything before approving</p></div>
        {dirty && !locked && <button onClick={() => { onSave(s); setDirty(false) }} className="btn btn-primary btn-sm"><Save className="h-4 w-4" />Save edits</button>}
      </div>
      <fieldset disabled={locked} className="space-y-5 p-5">
        <div className="space-y-3">
          <input className="input text-base font-semibold" value={s.title} onChange={(e) => upd({ title: e.target.value })} />
          <textarea rows={2} className="input" value={s.logline} onChange={(e) => upd({ logline: e.target.value })} />
          <div><label className="label">Visual style — appended to every chunk prompt</label>
            <textarea rows={2} className="input" value={s.style} onChange={(e) => upd({ style: e.target.value })} /></div>
        </div>

        {s.characters.length > 0 && (
          <div>
            <div className="label">Characters</div>
            <div className="space-y-2">
              {s.characters.map((c, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-[10rem_1fr]">
                  <input className="input" value={c.name} onChange={(e) => updChar(i, { name: e.target.value })} />
                  <input className="input" value={c.description} onChange={(e) => updChar(i, { description: e.target.value })} />
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="label">Timeline</div>
          <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full">
            {s.scenes.map((sc, i) => <div key={i} title={`${sc.title} · ${sc.duration_sec}s`} className={`${COLORS[i % COLORS.length]} opacity-80`} style={{ flex: Math.max(0.5, +sc.duration_sec || 1) }} />)}
          </div>
        </div>

        <div className="space-y-3">
          {s.scenes.map((sc, i) => (
            <div key={i} className="rounded-xl border border-line p-4">
              <div className="mb-3 flex items-center gap-3">
                <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold text-white ${COLORS[i % COLORS.length]}`}>{i + 1}</span>
                <input className="input font-medium" value={sc.title} onChange={(e) => updScene(i, { title: e.target.value })} />
                <div className="flex shrink-0 items-center gap-1.5">
                  <input type="number" step="0.5" min="1" className="input w-20" value={sc.duration_sec} onChange={(e) => updScene(i, { duration_sec: +e.target.value })} />
                  <span className="text-xs text-muted">sec</span>
                </div>
              </div>
              <div className="space-y-3">
                <div><label className="label">Summary</label><textarea rows={2} className="input" value={sc.summary} onChange={(e) => updScene(i, { summary: e.target.value })} /></div>
                <div><label className="label">Video prompt</label><textarea rows={4} className="input font-mono text-xs leading-relaxed" value={sc.visual_prompt} onChange={(e) => updScene(i, { visual_prompt: e.target.value })} /></div>
              </div>
            </div>
          ))}
        </div>
      </fieldset>
    </div>
  )
}
