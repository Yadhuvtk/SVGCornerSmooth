import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch() {
    // Intentionally silent in UI; the fallback message is user-facing.
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="offline-fallback">
          <h1>Backend offline</h1>
          <p>Backend offline — make sure the Flask server is running on port 5050.</p>
        </div>
      )
    }
    return this.props.children
  }
}
