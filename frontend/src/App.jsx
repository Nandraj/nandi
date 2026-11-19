import { useCallback, useEffect, useMemo, useState } from 'react'
import { Menu, Monitor, Moon, Plus, Search, Settings, Sun } from 'lucide-react'
import { api } from './api'
import NewProject from './components/NewProject'
import ProjectView from './components/ProjectView'
import SettingsModal from './components/SettingsModal'
import { Segmented, StatusDot } from './ui'
import ErrorBoundary from './ErrorBoundary'
import Logo from './components/Logo'

function useTheme() {
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('theme') || 'system' } catch { return 'system' } })
  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => document.documentElement.classList.toggle('dark', theme === 'dark' || (theme === 'system' && mq.matches))
    apply()
    try { localStorage.setItem('theme', theme) } catch {}
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [theme])
  return [theme, setTheme]
}

const Svc = ({ ok, label, detail }) => (
  <div className="flex items-center justify-between text-xs">
    <span className="flex items-center gap-2 text-ink"><span className={`h-2 w-2 rounded-full ${ok === undefined ? 'bg-muted/40' : ok ? 'bg-ok' : 'bg-danger'}`} />{label}</span>
    <span className="truncate text-muted">{detail}</span>
  </div>
)

export default function App() {
  const [projects, setProjects] = useState([])
  const [sel, setSel] = useState('new')
  const [showSettings, setShowSettings] = useState(() => location.hash.startsWith('#settings'))
  const [health, setHealth] = useState(null)
  const [query, setQuery] = useState('')
  const [nav, setNav] = useState(false)
  const [theme, setTheme] = useTheme()

  const refresh = useCallback(() => api.projects().then(setProjects).catch(() => {}), [])
  useEffect(() => { refresh(); const t = setInterval(refresh, 4000); return () => clearInterval(t) }, [refresh])
  useEffect(() => { const f = () => api.health().then(setHealth).catch(() => setHealth(null)); f(); const t = setInterval(f, 30000); return () => clearInterval(t) }, [showSettings])

  const shown = useMemo(() => projects.filter((p) => p.title.toLowerCase().includes(query.toLowerCase())), [projects, query])
  const go = (v) => { setSel(v); setNav(false) }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <Logo size={38} />
        <div><div className="text-sm font-semibold leading-tight">Nandi</div><div className="text-[11px] text-muted">AI video studio</div></div>
      </div>
      <div className="space-y-3 px-4">
        <button onClick={() => go('new')} className="btn btn-primary w-full"><Plus className="h-4 w-4" />New project</button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" />
          <input className="input pl-9" placeholder="Search projects" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      <div className="mt-4 px-5 text-[11px] font-semibold uppercase tracking-wider text-muted">Projects</div>
      <nav className="mt-2 flex-1 space-y-0.5 overflow-y-auto px-3">
        {shown.length === 0 && <div className="px-3 py-6 text-center text-xs text-muted">{projects.length ? 'No matches' : 'No projects yet'}</div>}
        {shown.map((p) => (
          <button key={p.id} onClick={() => go(p.id)} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition ${sel === p.id ? 'bg-brand-soft' : 'hover:bg-surface2'}`}>
            <StatusDot status={p.status} />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-sm ${sel === p.id ? 'font-semibold text-brand' : 'text-ink'}`}>{p.title}</span>
              <span className="block text-[11px] text-muted">{{ script: p.kind, image: 'image', video: 'video', t2v: 'text → video', character: 'character' }[p.mode] || p.kind}{p.mode === 'image' || p.mode === 'character' ? '' : ` · ${p.duration}s`}</span>
            </span>
          </button>
        ))}
      </nav>
      <div className="space-y-3 border-t border-line p-4">
        <div className="space-y-1.5">
          <Svc ok={health?.ollama?.ok && health.ollama.model_present} label="Script LLM" detail={health?.ollama?.ok ? (health.ollama.model_present ? 'ready' : 'model missing') : 'offline'} />
          <Svc ok={health ? !!health.drawthings?.ok : undefined} label="Draw Things" detail={health?.drawthings?.ok ? 'connected' : 'offline'} />
        </div>
        <Segmented className="w-full" value={theme} onChange={setTheme} options={[['light', 'Light', Sun], ['dark', 'Dark', Moon], ['system', 'Auto', Monitor]]} />
        <button onClick={() => setShowSettings(true)} className="btn btn-secondary w-full"><Settings className="h-4 w-4" />Settings</button>
      </div>
    </div>
  )

  return (
    <div className="flex h-screen bg-bg">
      <aside className="hidden w-72 shrink-0 border-r border-line bg-surface lg:block">{sidebar}</aside>
      {nav && <div className="fixed inset-0 z-40 lg:hidden"><div className="absolute inset-0 bg-slate-950/50" onClick={() => setNav(false)} /><aside className="absolute inset-y-0 left-0 w-72 bg-surface shadow-xl">{sidebar}</aside></div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
          <button onClick={() => setNav(true)} className="btn btn-ghost btn-sm"><Menu className="h-5 w-5" /></button>
          <Logo size={26} /><span className="text-sm font-semibold">Nandi</span>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
            <ErrorBoundary key={sel} onReset={() => setSel('new')}>
              {sel === 'new'
                ? <NewProject onCreated={(p) => { refresh(); setSel(p.id) }} />
                : <ProjectView key={sel} id={sel} onChanged={refresh} onDeleted={() => { refresh(); setSel('new') }} />}
            </ErrorBoundary>
          </div>
        </main>
      </div>
      {showSettings && <ErrorBoundary onReset={() => setShowSettings(false)}><SettingsModal health={health} onClose={() => setShowSettings(false)} /></ErrorBoundary>}
    </div>
  )
}
