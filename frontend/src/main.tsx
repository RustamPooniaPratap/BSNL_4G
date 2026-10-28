import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { landsOnPortfolio } from './lib/portfolio'

// Opening the app at "/" with no filters lands on Site Portfolio (see landsOnPortfolio).
if (landsOnPortfolio(window.location.pathname, window.location.search)) {
  window.history.replaceState(null, '', '/portfolio')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
