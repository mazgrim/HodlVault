import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ThemeProvider, applyTheme, getInitialTheme } from './hooks/useTheme'
import './index.css'

// Apply the saved theme before the first paint to avoid a flash.
applyTheme(getInitialTheme())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </React.StrictMode>
)
