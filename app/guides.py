"""Looping CSS animation of the Render Environment page (where to paste TELEGRAM_SESSION).

Drawn to match Render's real layout: the 5 variables appear in the same order,
TELEGRAM_SESSION is the 5th row.
"""

CSS = """
<style>
.guide{margin:12px 0 18px;padding:12px;border-radius:14px;background:#f2f2f7}
.guide .cap{font-size:13px;color:#6e6e73;margin-top:8px;text-align:center}
.rd{display:flex;border-radius:10px;overflow:hidden;background:#fff;border:1px solid #d1d1d6;
  font:11px system-ui,sans-serif;color:#1c1c1e;height:260px}
.rd .side{width:92px;flex:none;background:#fafafa;border-right:1px solid #e5e5ea;padding:8px 0}
.rd .side .grp{font-size:9px;letter-spacing:.08em;color:#8e8e93;padding:8px 10px 3px}
.rd .side .it{padding:4px 10px;color:#3a3a3c}
.rd .side .env{animation:g-env 10s infinite}
.rd .main{flex:1;padding:10px;position:relative;min-width:0}
.rd .hd{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.rd .hd b{flex:1;font-size:12px}
.rd .exp{padding:3px 7px;border:1px solid #d1d1d6;border-radius:5px;color:#3a3a3c}
.rd .edit{padding:3px 8px;border-radius:5px;background:#1c1c1e;color:#fff;animation:g-edit 10s infinite}
.rd .th{display:flex;font-size:9px;color:#8e8e93;letter-spacing:.06em;padding:0 0 4px 18px}
.rd .th span:first-child{width:46%}
.rd .r{display:flex;align-items:center;gap:4px;margin:3px 0;border-radius:6px}
.rd .n{width:14px;flex:none;text-align:center;font-size:9px;color:#aeaeb2}
.rd .k,.rd .v{padding:5px;border-radius:4px;background:#f2f2f7;font:9px ui-monospace,monospace;
  white-space:nowrap;overflow:hidden}
.rd .k{width:44%;flex:none}.rd .v{flex:1;animation:g-field 10s infinite}
.rd .r5{animation:g-row 10s infinite}
.rd .r5 .n{animation:g-num 10s infinite;border-radius:7px}
.rd .r5 .v{animation:g-field 10s infinite,g-focus 10s infinite}
.rd .dots{animation:g-dots 10s infinite}
.rd .typed{display:inline-block;overflow:hidden;vertical-align:bottom;width:0;animation:g-type 10s infinite steps(14)}
.rd .tag{margin:4px 0 0 18px;font-size:10px;font-weight:600;color:#7c3aed;opacity:0;animation:g-tag 10s infinite}
.rd .bar{position:absolute;left:10px;right:10px;bottom:8px;display:flex;gap:6px;opacity:0;animation:g-bar 10s infinite}
.rd .save{flex:1;padding:6px;border-radius:6px;background:#7c3aed;color:#fff;text-align:center;font-weight:600;
  animation:g-save 10s infinite}
.rd .cancel{padding:6px 10px;border:1px solid #d1d1d6;border-radius:6px;color:#3a3a3c}
@keyframes g-env{0%,4%{background:none;color:#3a3a3c}8%,100%{background:#ede7ff;color:#6d28d9;font-weight:600}}
@keyframes g-edit{0%,14%{box-shadow:none}18%,26%{box-shadow:0 0 0 4px rgba(124,58,237,.5)}30%,100%{box-shadow:none}}
@keyframes g-field{0%,29%{background:#f2f2f7;outline:0}31%,100%{background:#fff;outline:1px solid #d1d1d6}}
@keyframes g-row{0%,33%{background:none}37%,92%{background:#f3edff}96%,100%{background:none}}
@keyframes g-num{0%,33%{background:none;color:#aeaeb2}37%,100%{background:#7c3aed;color:#fff;font-weight:700}}
@keyframes g-focus{0%,29%{outline:0}31%,43%{outline:1px solid #d1d1d6}46%,72%{outline:2px solid #7c3aed}76%,100%{outline:1px solid #d1d1d6}}
@keyframes g-tag{0%,33%{opacity:0}37%,92%{opacity:1}96%,100%{opacity:0}}
@keyframes g-dots{0%,47%{display:inline}48%,100%{display:none}}
@keyframes g-type{0%,48%{width:0}66%,100%{width:14ch}}
@keyframes g-bar{0%,29%{opacity:0}31%,100%{opacity:1}}
@keyframes g-save{0%,74%{box-shadow:none}78%,90%{box-shadow:0 0 0 4px rgba(124,58,237,.5)}94%,100%{box-shadow:none}}
@media (prefers-reduced-motion:reduce){.guide *{animation:none!important}}
</style>"""

RENDER = """<div class="guide"><div class="rd">
<div class="side"><div class="it">Deploys</div><div class="it">Settings</div>
<div class="grp">MONITOR</div><div class="it">Events</div><div class="it">Logs</div><div class="it">Metrics</div>
<div class="grp">MANAGE</div><div class="it">Compute</div><div class="it env">Environment</div><div class="it">Shell</div></div>
<div class="main">
<div class="hd"><b>Environment Variables</b><span class="exp">Export</span><span class="edit">Edit</span></div>
<div class="th"><span>KEY</span><span>VALUE</span></div>
<div class="r"><span class="n">1</span><span class="k">ADMIN_PASSWORD</span><span class="v">•••••••••</span></div>
<div class="r"><span class="n">2</span><span class="k">SECRET_KEY</span><span class="v">•••••••••</span></div>
<div class="r"><span class="n">3</span><span class="k">TELEGRAM_API_HASH</span><span class="v">•••••••••</span></div>
<div class="r"><span class="n">4</span><span class="k">TELEGRAM_API_ID</span><span class="v">•••••••••</span></div>
<div class="r r5"><span class="n">5</span><span class="k">TELEGRAM_SESSION</span><span class="v"><span class="dots">•••••••••</span><span class="typed">ваша_строка…</span></span></div>
<div class="tag">↑ 5-я строка — сюда вставить строку</div>
<div class="bar"><span class="save">Save, rebuild, and deploy</span><span class="cancel">Cancel</span></div>
</div></div>
<div class="cap">Environment → Edit → <b>5-я строка TELEGRAM_SESSION</b> → вставить → Save, rebuild, and deploy</div></div>"""
