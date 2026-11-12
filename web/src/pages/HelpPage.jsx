export default function HelpPage() {
  const rows = [
    ['Ask anything', 'Type in the message box and press Enter. Shift+Enter adds a new line.'],
    ['Create an image', <><code>/image a cat on the moon</code> (about 5 seconds), or just ask FongAI 3.4 for a picture.</>],
    ['Create a video', <><code>/video waves on a beach</code> (takes a few minutes).</>],
    ['Talk instead of typing', 'Click the mic, speak, then click it again. Whisper turns your voice into text.'],
    ['Use your documents', 'Click + or drop .txt / .md files on the message box. Answers will quote them.'],
    ['Khmer', 'Write in Khmer: FongAI 3.4 translates your question and answers in Khmer.'],
    ['Open Settings', 'Press ⇧⌘, (Ctrl+Shift+, on Windows).'],
    ['Models', 'FongAI 3.4 is smart and can create images. FongAI 3.2 is the tiny model trained here.'],
  ]
  return (
    <div className="page">
      <h1 className="page-title">Get help</h1>
      <div className="list">
        {rows.map(([k, v]) => <div key={k} className="help-row"><b>{k}</b><span>{v}</span></div>)}
      </div>
    </div>
  )
}
