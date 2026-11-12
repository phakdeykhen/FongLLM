import ChatView from '@/components/chat/ChatView.jsx'
import ChatHeader from '@/components/chat/ChatHeader.jsx'

// An open conversation: title bar, messages, composer docked at the bottom.
export default function ChatPage({ chat, busy, status, composer, onOpenImage, onEdit, actions }) {
  return (
    <div className="chat-layout">
      <ChatHeader chat={chat} {...actions} />
      <ChatView chat={chat} busy={busy} status={status} onOpenImage={onOpenImage} onEdit={onEdit} />
      <div className="dock">{composer}<p className="dock-note">Fong AI can make mistakes. Check important answers.</p></div>
    </div>
  )
}
