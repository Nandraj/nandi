import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="m-6 rounded-xl border border-line bg-surface p-6">
        <h2 className="text-base font-semibold">Something went wrong</h2>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-danger">{String(this.state.error?.message || this.state.error)}</pre>
        <button className="btn btn-primary mt-4" onClick={() => { this.setState({ error: null }); this.props.onReset?.() }}>Dismiss</button>
      </div>
    )
  }
}
