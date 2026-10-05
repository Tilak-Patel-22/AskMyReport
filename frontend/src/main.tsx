import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/global.css'
import { ChatPage } from './pages/ChatPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ChatPage />
  </StrictMode>,
)
