import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react'

const TONES = {
  neutral: 'bg-surface2 text-muted', brand: 'bg-brand-soft text-brand', ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn', danger: 'bg-danger-soft text-danger', info: 'bg-info-soft text-info',
}
export const STATUS = {
  draft: ['Draft', 'neutral'], scripting: ['Writing script', 'warn'], script_ready: ['Script ready', 'info'], sample_ready: ['Sample ready', 'info'],
  generating: ['Generating', 'brand'], done: ['Complete', 'ok'], failed: ['Failed', 'danger'], cancelled: ['Cancelled', 'neutral'],
  pending: ['Queued', 'neutral'], running: ['Rendering', 'brand'],
}
const DOT = { neutral: 'bg-muted/50', brand: 'bg-brand', ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger', info: 'bg-info' }

export const Badge = ({ status, tone, children }) => {
  const [label, t] = STATUS[status] || [status, 'neutral']
  const k = tone || t
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${TONES[k]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${DOT[k]} ${['scripting', 'generating', 'running'].includes(status) ? 'animate-pulse' : ''}`} />
      {children || label}
    </span>
  )
}
export const StatusDot = ({ status }) => <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[(STATUS[status] || [0, 'neutral'])[1]]} ${['scripting', 'generating'].includes(status) ? 'animate-pulse' : ''}`} />
export const Spinner = ({ className = 'h-4 w-4' }) => <Loader2 className={`animate-spin ${className}`} />

export function Alert({ tone = 'danger', children, onClose }) {
  const Icon = tone === 'danger' ? AlertTriangle : tone === 'ok' ? CheckCircle2 : Info
  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3.5 py-2.5 text-sm ${TONES[tone]}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" /><div className="flex-1 break-words">{children}</div>
      {onClose && <button onClick={onClose} className="opacity-70 hover:opacity-100"><X className="h-4 w-4" /></button>}
    </div>
  )
}

export function Segmented({ value, onChange, options, disabled, className = '' }) {
  return (
    <div className={`inline-grid auto-cols-fr grid-flow-col gap-0.5 rounded-lg border border-line bg-surface2 p-0.5 ${className}`}>
      {options.map(([k, label, Icon]) => (
        <button key={k} type="button" disabled={disabled} onClick={() => onChange(k)}
          className={`flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 ${value === k ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink'}`}>
          {Icon && <Icon className="h-4 w-4" />}{label}
        </button>
      ))}
    </div>
  )
}

export const ProgressBar = ({ value, className = '' }) => (
  <div className={`h-2 overflow-hidden rounded-full bg-surface2 ${className}`}>
    <div className="h-full rounded-full bg-brand transition-all duration-500" style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
  </div>
)

export function Stepper({ steps, current, failed }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto">
      {steps.map((label, i) => {
        const done = i < current, active = i === current
        return (
          <li key={label} className="flex items-center gap-2">
            <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-semibold ${done ? 'bg-ok text-white' : active ? (failed ? 'bg-danger text-white' : 'bg-brand text-white') : 'bg-surface2 text-muted'}`}>
              {done ? '✓' : i + 1}
            </span>
            <span className={`text-sm ${active ? 'font-semibold text-ink' : 'text-muted'}`}>{label}</span>
            {i < steps.length - 1 && <span className={`mx-1 h-px w-8 sm:w-14 ${done ? 'bg-ok' : 'bg-line'}`} />}
          </li>
        )
      })}
    </ol>
  )
}

export function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`card flex max-h-[90vh] w-full flex-col ${wide ? 'max-w-3xl' : 'max-w-xl'} shadow-2xl`}>
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="btn btn-ghost btn-sm"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}
