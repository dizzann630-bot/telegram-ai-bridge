"""Small looping CSS animations that show where to tap (no screenshots, no personal data)."""

CSS = """
<style>
.guide{margin:12px 0 18px;padding:14px;border-radius:14px;background:#f2f2f7}
.guide .cap{font-size:13px;color:#6e6e73;margin-top:8px;text-align:center}
@media (prefers-color-scheme:dark){.guide{background:#2c2c2e}}
/* phone */
.phone{position:relative;width:190px;height:300px;margin:0 auto;border-radius:26px;background:#1c1c1e;padding:10px;box-sizing:border-box}
.scr{position:absolute;inset:10px;border-radius:18px;background:#fff;overflow:hidden;opacity:0;animation:tgshow 9s infinite}
.scr h4{margin:0;padding:10px 12px;font:600 14px system-ui;background:#f7f7f7;border-bottom:1px solid #e5e5ea;color:#1c1c1e}
.row{display:flex;align-items:center;gap:8px;padding:9px 12px;font:13px system-ui;color:#1c1c1e;border-bottom:1px solid #f0f0f0}
.ico{width:18px;height:18px;border-radius:5px;background:#c7c7cc;flex:none}
.s1{animation-delay:0s}.s2{animation-delay:-6s}.s3{animation-delay:-3s}
.btn{margin:14px 12px;padding:10px;border-radius:10px;background:#2a7de1;color:#fff;font:600 13px system-ui;text-align:center}
.tap{position:absolute;width:28px;height:28px;border-radius:50%;background:rgba(42,125,225,.35);border:2px solid #2a7de1;pointer-events:none}
.s1 .tap{left:112px;top:150px}.s2 .tap{left:72px;top:52px}.s3 .tap{display:none}
.tap{animation:tgtap 3s infinite}
@keyframes tgshow{0%,33%{opacity:1}34%,100%{opacity:0}}
@keyframes tgtap{0%,40%{transform:scale(.4);opacity:0}55%{transform:scale(1);opacity:1}75%{transform:scale(1.3);opacity:0}100%{opacity:0}}
/* render */
.rd{position:relative;display:flex;height:190px;border-radius:12px;overflow:hidden;background:#fff;font:12px system-ui;color:#1c1c1e;border:1px solid #d1d1d6}
.rd .side{width:96px;background:#f7f7f7;border-right:1px solid #e5e5ea;padding:8px 0}
.rd .side div{padding:6px 10px}.rd .env{animation:rdenv 8s infinite}
.rd .main{flex:1;padding:10px;position:relative}
.rd .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-weight:600}
.rd .edit{padding:4px 10px;border-radius:6px;background:#1c1c1e;color:#fff;animation:rdedit 8s infinite}
.rd .kv{display:flex;gap:6px;margin:4px 0}
.rd .k{width:110px;padding:5px;background:#f2f2f7;border-radius:4px;font-family:ui-monospace,monospace;font-size:10px}
.rd .v{flex:1;padding:5px;background:#f2f2f7;border-radius:4px;font-family:ui-monospace,monospace;font-size:10px;overflow:hidden;white-space:nowrap}
.rd .target .v{animation:rdfield 8s infinite}
.rd .typed{display:inline-block;overflow:hidden;vertical-align:bottom;width:0;animation:rdtype 8s infinite steps(14)}
.rd .dash{animation:rddash 8s infinite}
.rd .save{position:absolute;right:10px;bottom:10px;padding:5px 12px;border-radius:6px;background:#7c3aed;color:#fff;font-weight:600;animation:rdsave 8s infinite}
@keyframes rdenv{0%,10%{background:none}12%,100%{background:#ece5ff;color:#6d28d9}}
@keyframes rdedit{0%,20%{box-shadow:none}24%,30%{box-shadow:0 0 0 4px rgba(124,58,237,.45)}34%,100%{box-shadow:none}}
@keyframes rdfield{0%,36%{outline:none}40%,80%{outline:2px solid #7c3aed;background:#fff}84%,100%{outline:none}}
@keyframes rddash{0%,42%{opacity:1}44%,100%{opacity:0}}
@keyframes rdtype{0%,46%{width:0}66%,100%{width:14ch}}
@keyframes rdsave{0%,72%{box-shadow:none;opacity:.6}76%,86%{box-shadow:0 0 0 4px rgba(124,58,237,.45);opacity:1}90%,100%{opacity:.6}}
@media (prefers-reduced-motion:reduce){.guide *{animation:none!important}.scr.s3{opacity:1}}
</style>"""

RENDER = """<div class="guide"><div class="rd">
<div class="side"><div>Events</div><div>Logs</div><div class="env"><b>Environment</b></div><div>Settings</div></div>
<div class="main"><div class="top">Environment Variables <span class="edit">Edit</span></div>
<div class="kv"><span class="k">ADMIN_PASSWORD</span><span class="v">••••••••</span></div>
<div class="kv"><span class="k">SECRET_KEY</span><span class="v">••••••••</span></div>
<div class="kv target"><span class="k">TELEGRAM_SESSION</span><span class="v"><span class="dash">-</span><span class="typed">ваша_строка…</span></span></div>
<span class="save">Save, rebuild, and deploy</span></div></div>
<div class="cap">Render → ваш сервис → Environment → Edit → TELEGRAM_SESSION → вставить → Save, rebuild, and deploy</div></div>"""
