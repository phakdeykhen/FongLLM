// Records the microphone straight to a 16 kHz mono WAV blob, so the backend can read it without ffmpeg.

export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const ctx = new AudioContext()
  const source = ctx.createMediaStreamSource(stream)
  const node = ctx.createScriptProcessor(4096, 1, 1)
  const chunks = []
  node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  source.connect(node)
  node.connect(ctx.destination)

  return async function stop() {
    node.disconnect()
    source.disconnect()
    stream.getTracks().forEach((t) => t.stop())
    await ctx.close()
    const length = chunks.reduce((n, c) => n + c.length, 0)
    const all = new Float32Array(length)
    let off = 0
    for (const c of chunks) { all.set(c, off); off += c.length }
    return encodeWav(downsample(all, ctx.sampleRate, 16000), 16000)
  }
}

function downsample(data, from, to) {
  if (from === to) return data
  const ratio = from / to
  const out = new Float32Array(Math.floor(data.length / ratio))
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio)
    const end = Math.min(Math.floor((i + 1) * ratio), data.length)
    let sum = 0
    for (let j = start; j < end; j++) sum += data[j]
    out[i] = sum / Math.max(end - start, 1)
  }
  return out
}

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(buf)
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, samples.length * 2, true)
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true))
  return new Blob([buf], { type: 'audio/wav' })
}
