"""Live training charts for the FongAI build (reads finetune/build.log; never touches the training).

Run:  .venv/bin/python finetune/chart.py      then open http://localhost:8765
"""
import http.server, json, os, re, subprocess, time, webbrowser

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.log")
PORT = 8765
# mlx_lm 0.32 log lines:  "    20    1.900 ▼    1,234     14.0k"  and  "     1    val 2.100    10.00s"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TRAIN = re.compile(r"^\s*(\d+)\s+([\d.]+|nan|inf)\s+[▼▲]\s+([\d,]+)\s+([\d.]+)k")
VAL = re.compile(r"^\s*(\d+)\s+val\s+([\d.]+)")
STEP_TIMES = []  # (wall time, step) seen by this server, for speed / time left
MEM = []         # (step, GB) memory of the training process, sampled by this server
DATA = re.compile(r"^\[(\d+)/(\d+)\]")


def parse():
    d = {k: [] for k in ("train_loss", "val_loss", "tok_sec", "tokens_k", "mem")}
    data, status, tail, nan, last_step = None, "waiting", [], False, 0
    try:
        lines = ANSI.sub("", open(LOG, encoding="utf-8", errors="replace").read()).splitlines()
    except FileNotFoundError:
        lines = []
    for ln in lines:
        if m := TRAIN.search(ln):
            i = int(m[1])
            if m[2] in ("nan", "inf"):
                nan = True
            else:
                d["train_loss"].append([i, float(m[2])])
            last_step = i
            d["tok_sec"].append([i, float(m[3].replace(",", ""))])
            d["tokens_k"].append([i, float(m[4])])
        elif m := VAL.search(ln):
            d["val_loss"].append([int(m[1]), float(m[2])])
        elif m := DATA.match(ln):
            data = [int(m[1]), int(m[2])]
    text = "\n".join(lines)
    if "Done: ollama run fongai" in text: status = "done"
    elif re.search(r"EXIT [1-9]|Traceback", text): status = "failed"
    elif "fuse" in text.lower() and d["train_loss"] and d["train_loss"][-1][0] >= 400: status = "fusing / packaging"
    elif d["train_loss"] or d["val_loss"]: status = "training"
    elif data: status = "making data"
    if nan: status = "BROKEN: train loss is nan (training diverged; stop it)"
    step = last_step
    now = time.time()
    if step and (not STEP_TIMES or STEP_TIMES[-1][1] != step):
        STEP_TIMES.append((now, step))
    try:  # resident memory of the running training process
        pid = subprocess.run(["pgrep", "-f", "mlx_lm lora"], capture_output=True, text=True).stdout.split()[0]
        gb = int(subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True).stdout) / 1e6
        if not MEM or MEM[-1][0] != step: MEM.append([step, round(gb, 2)])
    except (IndexError, ValueError):
        pass
    d["mem"] = MEM
    eta = None
    if len(STEP_TIMES) >= 2:
        (t0, s0), (t1, s1) = STEP_TIMES[0], STEP_TIMES[-1]
        eta = (400 - s1) * (t1 - t0) / (s1 - s0) / 60
    return {"step": step, "eta": eta, "series": d, "data": data, "status": status, "tail": lines[-4:]}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FongAI training</title><style>
body{margin:0;background:#0b0b0d;color:#e8e8ea;font:14px -apple-system,system-ui,sans-serif;padding:16px}
h1{font-size:20px;margin:0 0 4px}.sub{color:#8a8a95;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card{background:#0f0f12;border:1px solid #26262c;border-radius:6px;padding:12px}
.card h2{font-weight:500;font-size:16px;text-align:center;margin:4px 0 2px}
.leg{text-align:center;font-size:13px;margin-bottom:4px}.leg span{margin:0 8px}
canvas{width:100%;height:220px;display:block}
pre{background:#0f0f12;border:1px solid #26262c;border-radius:6px;padding:10px;overflow-x:auto;color:#aaa;font-size:12px}
.bar{height:8px;background:#26262c;border-radius:4px;overflow:hidden;margin:6px 0 14px;max-width:520px}.bar i{display:block;height:100%;background:#9acd5a}
</style></head><body>
<h1>FongAI training</h1><div class="sub" id="st">loading…</div><div class="bar"><i id="pb" style="width:0"></i></div>
<div class="grid" id="g"></div><pre id="tail"></pre>
<script>
const G='#9acd5a',R='#e0605a',B='#5aa0e0';
const charts=[["loss",[["train_loss","train",G],["val_loss","val",R]]],["memory of training (GB)",[["mem","RAM",B]]],
 ["tokens/sec",[["tok_sec","speed",G]]],["trained tokens (k)",[["tokens_k","tokens",R]]]];
const g=document.getElementById('g');
for(const [t,s] of charts){g.insertAdjacentHTML('beforeend',`<div class="card"><h2>${t}</h2><div class="leg">${s.map(x=>`<span style="color:${x[2]}">— ${x[1]}</span>`).join('')}</div><canvas data-t="${t}"></canvas></div>`)}
function draw(cv,sets){const r=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*r;cv.height=H*r;const c=cv.getContext('2d');c.scale(r,r);
 const pts=sets.flatMap(s=>s.pts);const L=46,Rt=10,T=8,Bm=24;c.font='11px system-ui';c.fillStyle='#777';
 if(!pts.length){c.fillText('no data yet',W/2-30,H/2);return}
 let x1=Math.max(400,...pts.map(p=>p[0])),y0=Math.min(...pts.map(p=>p[1])),y1=Math.max(...pts.map(p=>p[1]));if(y0==y1){y0-=1;y1+=1}const pad=(y1-y0)*.08;y0-=pad;y1+=pad;
 const X=v=>L+v/x1*(W-L-Rt),Y=v=>T+(1-(v-y0)/(y1-y0))*(H-T-Bm);
 c.strokeStyle='#26262c';for(let i=0;i<=4;i++){const v=y0+(y1-y0)*i/4,y=Y(v);c.beginPath();c.moveTo(L,y);c.lineTo(W-Rt,y);c.stroke();c.fillText(Math.abs(v)<.01&&v!=0?v.toExponential(1):v.toFixed(2),2,y+4)}
 for(let i=0;i<=4;i++){const v=x1*i/4;c.fillText(Math.round(v),X(v)-8,H-6)}
 for(const s of sets){if(!s.pts.length)continue;c.strokeStyle=s.col;c.lineWidth=2;c.beginPath();s.pts.forEach((p,i)=>i?c.lineTo(X(p[0]),Y(p[1])):c.moveTo(X(p[0]),Y(p[1])));c.stroke();
  const p=s.pts.at(-1);c.fillStyle=s.col;c.beginPath();c.arc(X(p[0]),Y(p[1]),3,0,7);c.fill();c.fillStyle='#777'}}
async function tick(){try{const d=await (await fetch('/data')).json();const S=d.series;
 const it=d.step||0;let msg='status: '+d.status;
 if(d.status=='making data'&&d.data){msg+=` — ${d.data[0]}/${d.data[1]} answers (training starts after this)`;pb.style.width=d.data[0]/d.data[1]*100+'%'}
 else{msg+=` — step ${it}/400`;pb.style.width=it/4+'%';const tl=S.train_loss.at(-1),vl=S.val_loss.at(-1);
  if(tl)msg+=` · train loss ${tl[1]}`;if(vl)msg+=` · val loss ${vl[1]}`;if(d.eta!=null&&it<400)msg+=` · ~${Math.round(d.eta)} min left`}
 st.textContent=msg;tail.textContent=d.tail.join('\n');
 document.querySelectorAll('canvas').forEach(cv=>{const def=charts.find(c=>c[0]==cv.dataset.t)[1];draw(cv,def.map(([k,,col])=>({pts:S[k],col})))})}catch(e){st.textContent='chart server stopped'}}
tick();setInterval(tick,5000);addEventListener('resize',tick);
</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body, ctype = (json.dumps(parse()).encode(), "application/json") if self.path == "/data" else (PAGE.encode(), "text/html")
        self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a): pass


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"FongAI charts at {url}  (Ctrl+C to stop; training keeps running)")
    webbrowser.open(url)
    srv.serve_forever()
