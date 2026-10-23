"""Visual layer: animated CSS, branded hero, page headers, stepper and small widgets.

All user-supplied text is HTML-escaped before it reaches st.html.
"""
from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from . import branding
from .profiles import ACCENTS

esc = html.escape


def _rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def inject_css(accent: str = "Indigo", landing: bool = False):
    a, b = ACCENTS.get(accent, ACCENTS["Indigo"])
    dark = is_dark()
    t = {
        "card": "rgba(18,26,46,.78)" if dark else "rgba(255,255,255,.86)",
        "card_solid": "#121a2e" if dark else "#ffffff",
        "text": "#e2e8f0" if dark else "#0f172a",
        "muted": "#94a3b8" if dark else "#64748b",
        "line": "rgba(148,163,184,.16)" if dark else "rgba(15,23,42,.08)",
        "shadow": "0 18px 40px -22px rgba(0,0,0,.65)" if dark else "0 18px 40px -24px rgba(30,41,90,.35)",
        "soft": "rgba(255,255,255,.04)" if dark else "rgba(15,23,42,.025)",
    }
    ar, br = _rgb(a), _rgb(b)
    landing_css = f"""
    .stApp::before, .stApp::after {{
        content:""; position:fixed; width:46vmax; height:46vmax; border-radius:50%;
        filter:blur(70px); opacity:{.22 if dark else .28}; pointer-events:none; z-index:0;
        animation: imsOrb 22s ease-in-out infinite alternate;
    }}
    .stApp::before {{ background: radial-gradient(circle, rgba({ar},.9), transparent 65%); top:-18vmax; left:-14vmax; }}
    .stApp::after  {{ background: radial-gradient(circle, rgba({br},.85), transparent 65%); bottom:-20vmax; right:-16vmax;
                      animation-duration: 28s; animation-direction: alternate-reverse; }}
    [data-testid="stMainBlockContainer"] {{ position:relative; z-index:1; max-width: 1180px; }}
    """ if landing else ""
    st.html(f"""
<style>
:root {{ --ims-a:{a}; --ims-b:{b}; --ims-ar:{ar}; --ims-br:{br}; --ims-card:{t['card']}; --ims-card-solid:{t['card_solid']};
        --ims-text:{t['text']}; --ims-muted:{t['muted']}; --ims-line:{t['line']}; --ims-shadow:{t['shadow']}; --ims-soft:{t['soft']}; }}
@keyframes imsRise {{ from {{ opacity:0; transform: translateY(14px) scale(.99); }} to {{ opacity:1; transform:none; }} }}
@keyframes imsFade {{ from {{ opacity:0; }} to {{ opacity:1; }} }}
@keyframes imsGradient {{ 0% {{ background-position:0% 50%; }} 50% {{ background-position:100% 50%; }} 100% {{ background-position:0% 50%; }} }}
@keyframes imsFloat {{ 0%,100% {{ transform: translate(0,0) scale(1); }} 50% {{ transform: translate(18px,-16px) scale(1.06); }} }}
@keyframes imsShine {{ 0% {{ transform: translateX(-120%) skewX(-18deg); }} 60%,100% {{ transform: translateX(260%) skewX(-18deg); }} }}
@keyframes imsPulse {{ 0% {{ box-shadow:0 0 0 0 rgba({ar},.45); }} 70% {{ box-shadow:0 0 0 14px rgba({ar},0); }} 100% {{ box-shadow:0 0 0 0 rgba({ar},0); }} }}
@keyframes imsOrb {{ 0% {{ transform: translate(0,0) rotate(0deg); }} 100% {{ transform: translate(8vmax,6vmax) rotate(40deg); }} }}
@keyframes imsBar {{ from {{ width:0; }} }}
@keyframes imsPop {{ 0% {{ transform: scale(.6); opacity:0; }} 70% {{ transform: scale(1.08); }} 100% {{ transform: scale(1); opacity:1; }} }}

[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; }}
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
[data-testid="stMainBlockContainer"] [data-testid="stLayoutWrapper"] {{ animation: imsRise .55s cubic-bezier(.2,.8,.2,1) both; }}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] > :nth-child(2) {{ animation-delay:.04s; }}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] > :nth-child(3) {{ animation-delay:.08s; }}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] > :nth-child(4) {{ animation-delay:.12s; }}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] > :nth-child(5) {{ animation-delay:.16s; }}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] > :nth-child(n+6) {{ animation-delay:.2s; }}

/* metric cards */
[data-testid="stMetric"] {{
    background: var(--ims-card); border:1px solid var(--ims-line); border-radius:18px; padding:16px 18px 12px;
    box-shadow: var(--ims-shadow); position:relative; overflow:hidden; backdrop-filter: blur(8px);
    transition: transform .28s cubic-bezier(.2,.8,.2,1), box-shadow .28s;
}}
[data-testid="stMetric"]::before {{ content:""; position:absolute; inset:0 0 auto 0; height:3px;
    background: linear-gradient(90deg, var(--ims-a), var(--ims-b), var(--ims-a)); background-size:200% 100%;
    animation: imsGradient 6s linear infinite; }}
[data-testid="stMetric"]:hover {{ transform: translateY(-4px); box-shadow: 0 22px 44px -20px rgba({ar},.45); }}
[data-testid="stMetricValue"] {{ font-weight: 750; letter-spacing:-.02em; }}

/* bordered containers */
[data-testid="stVerticalBlock"][class*="border"], .ims-card-wrap {{ transition: box-shadow .25s, transform .25s; }}

/* buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {{
    border-radius: 12px; font-weight: 600; transition: transform .18s ease, box-shadow .18s ease, filter .18s; }}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
    transform: translateY(-2px); box-shadow: 0 10px 22px -12px rgba({ar},.6); }}
.stButton > button:active, .stFormSubmitButton > button:active {{ transform: translateY(0) scale(.98); }}
button[kind="primary"], button[kind="primaryFormSubmit"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b)) !important; border: 0 !important; color: #fff !important;
    position: relative; overflow: hidden; }}
button[kind="primary"]::after, button[kind="primaryFormSubmit"]::after {{
    content:""; position:absolute; top:0; left:0; width:40%; height:100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent); animation: imsShine 3.8s ease-in-out infinite; }}

/* tabs */
[role="tab"] {{ transition: color .2s, background .2s; border-radius: 10px 10px 0 0; }}
[role="tab"]:hover {{ background: rgba({ar},.07); }}
[role="tab"][aria-selected="true"] {{ color: var(--ims-a); font-weight: 650; }}

/* inputs */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{ transition: box-shadow .2s, border-color .2s; }}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within {{
    box-shadow: 0 0 0 4px rgba({ar},.15); }}

/* expander + dataframe */
[data-testid="stExpander"] details {{ border-radius: 14px; transition: box-shadow .25s; }}
[data-testid="stExpander"] details:hover {{ box-shadow: 0 10px 26px -18px rgba({ar},.5); }}
[data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}

/* sidebar */
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, rgba({ar},.07), rgba({br},.04) 60%, transparent); }}
[data-testid="stSidebarNavLink"] {{ border-radius: 10px; transition: transform .18s, background .18s; }}
[data-testid="stSidebarNavLink"]:hover {{ transform: translateX(4px); background: rgba({ar},.10); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: linear-gradient(90deg, rgba({ar},.18), rgba({br},.06)); }}

/* ---------- custom components ---------- */
.ims-hero {{ position:relative; overflow:hidden; border-radius:24px; padding:26px 28px; color:#fff;
    background: linear-gradient(120deg, var(--ims-a), var(--ims-b), var(--ims-a)); background-size:220% 220%;
    animation: imsGradient 14s ease infinite; box-shadow: 0 26px 50px -28px rgba({ar},.75); }}
.ims-hero::after {{ content:""; position:absolute; top:0; left:0; width:35%; height:100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,.18), transparent); animation: imsShine 7s ease-in-out infinite; }}
.ims-blob {{ position:absolute; border-radius:50%; background: rgba(255,255,255,.14); filter: blur(2px); animation: imsFloat 9s ease-in-out infinite; }}
.ims-hero-row {{ position:relative; z-index:1; display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
.ims-hero-logo {{ width:74px; height:74px; border-radius:20px; background:#fff; padding:6px; object-fit:contain;
    box-shadow:0 10px 24px -10px rgba(0,0,0,.45); animation: imsPop .7s cubic-bezier(.2,.8,.2,1) both, imsPulse 2.8s 1s infinite; }}
.ims-eyebrow {{ font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; opacity:.85; font-weight:600; }}
.ims-hero h1 {{ color:#fff !important; font-size: clamp(1.45rem, 3vw, 2.15rem); margin:.15rem 0 .1rem; padding:0; line-height:1.15; font-weight:800; }}
.ims-hero p {{ margin:0; opacity:.9; }}
.ims-hero-stats {{ position:relative; z-index:1; display:flex; gap:12px; flex-wrap:wrap; margin-top:18px; }}
.ims-hero-stat {{ background: rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.22); border-radius:14px;
    padding:10px 14px; min-width:120px; backdrop-filter: blur(6px); animation: imsRise .6s both; }}
.ims-hero-stat b {{ display:block; font-size:1.35rem; line-height:1.2; }}
.ims-hero-stat span {{ font-size:.78rem; opacity:.85; }}

.ims-ph {{ margin: 0 0 1.1rem; animation: imsRise .5s both; }}
.ims-ph-title {{ font-size: clamp(1.5rem, 2.6vw, 2rem); font-weight: 800; letter-spacing:-.02em; color: var(--ims-text); line-height:1.2; }}
.ims-ph-title .ims-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:10px; vertical-align:middle;
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); animation: imsPulse 2.4s infinite; }}
.ims-ph-sub {{ color: var(--ims-muted); margin-top:4px; }}
.ims-ph-bar {{ height:3px; width:84px; margin-top:10px; border-radius:3px; background: linear-gradient(90deg, var(--ims-a), var(--ims-b));
    animation: imsBar .9s cubic-bezier(.2,.8,.2,1) both; }}

.ims-gradient-text {{ background: linear-gradient(90deg, var(--ims-a), var(--ims-b), #06b6d4, var(--ims-a)); background-size:300% 100%;
    -webkit-background-clip:text; background-clip:text; color:transparent; animation: imsGradient 8s linear infinite; }}
.ims-landing-title {{ text-align:center; font-size: clamp(1.9rem, 4.6vw, 3.1rem); font-weight:850; letter-spacing:-.03em; line-height:1.1; margin: .4rem 0 .4rem; }}
.ims-landing-sub {{ text-align:center; color: var(--ims-muted); font-size:1.05rem; margin-bottom: 1.4rem; }}
.ims-chip {{ display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:999px; font-size:.78rem; font-weight:600;
    background: rgba({ar},.10); color: var(--ims-a); border:1px solid rgba({ar},.22); }}
.ims-center {{ text-align:center; }}

/* institution type cards: the whole card is a button */
.ims-type {{ position:relative; padding: 26px 22px 22px; border-radius:22px; min-height: 285px; background: var(--ims-card);
    border: 1.5px solid var(--ims-line); box-shadow: var(--ims-shadow); transition: transform .3s cubic-bezier(.2,.8,.2,1), box-shadow .3s, border-color .3s;
    overflow:hidden; }}
.ims-type::before {{ content:""; position:absolute; inset:-1px; border-radius:22px; padding:1.5px; opacity:0; transition: opacity .3s;
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b), #06b6d4); background-size:200% 200%; animation: imsGradient 5s linear infinite;
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude; }}
.ims-type-icon {{ width:64px; height:64px; border-radius:18px; display:grid; place-items:center; color:#fff;
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); box-shadow: 0 14px 26px -14px rgba({ar},.9);
    transition: transform .45s cubic-bezier(.2,.8,.2,1); }}
.ims-type-title {{ margin-top:18px; font-weight:800; font-size:1.02rem; letter-spacing:.04em; color: var(--ims-text); }}
.ims-type-desc {{ margin-top:8px; color: var(--ims-muted); font-size:.9rem; line-height:1.5; }}
.ims-type-tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; }}
.ims-type-tags span {{ font-size:.72rem; padding:3px 9px; border-radius:999px; background: var(--ims-soft); border:1px solid var(--ims-line); color: var(--ims-muted); }}
.ims-type-check {{ position:absolute; top:16px; right:16px; width:30px; height:30px; border-radius:50%; display:grid; place-items:center;
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); color:#fff; font-weight:800; animation: imsPop .45s both; }}
.ims-type.selected {{ border-color: transparent; transform: translateY(-4px); box-shadow: 0 26px 50px -24px rgba({ar},.65); }}
.ims-type.selected::before {{ opacity:1; }}
[class*="st-key-typecard_"]:hover .ims-type {{ transform: translateY(-6px); box-shadow: 0 30px 56px -26px rgba({ar},.6); }}
[class*="st-key-typecard_"]:hover .ims-type-icon {{ transform: rotate(-8deg) scale(1.08); }}
[class*="st-key-typecard_"] .stButton button {{ height: 46px; font-size: 1rem; }}

/* quick action tiles (st.page_link inside keyed containers) */
[class*="st-key-qa_"] {{ background: var(--ims-card); border:1px solid var(--ims-line); border-radius:18px; padding:14px 12px 10px;
    box-shadow: var(--ims-shadow); transition: transform .28s cubic-bezier(.2,.8,.2,1), box-shadow .28s, border-color .28s;
    position:relative; overflow:hidden; min-width: 185px; flex: 1 1 185px; }}
[class*="st-key-qa_"]::before {{ content:""; position:absolute; inset:auto -40% -60% auto; width:140px; height:140px; border-radius:50%;
    background: radial-gradient(circle, rgba({ar},.16), transparent 70%); transition: transform .4s; pointer-events:none; }}
[class*="st-key-qa_"]:hover {{ transform: translateY(-5px); border-color: rgba({ar},.45); box-shadow: 0 22px 44px -22px rgba({ar},.6); }}
[class*="st-key-qa_"]:hover::before {{ transform: scale(1.6); }}
[class*="st-key-qa_"] a {{ font-weight:700 !important; }}
[class*="st-key-qa_"] [data-testid="stCaptionContainer"] {{ margin-top:-6px; }}

/* getting-started checklist */
.ims-ring {{ --p: 0; width:92px; height:92px; border-radius:50%; display:grid; place-items:center; flex:none;
    background: conic-gradient(var(--ims-a) calc(var(--p) * 1%), var(--ims-line) 0); animation: imsPop .7s both; }}
.ims-ring > div {{ width:72px; height:72px; border-radius:50%; background: var(--ims-card-solid); display:grid; place-items:center;
    font-weight:800; font-size:1.15rem; color: var(--ims-text); }}
.ims-check {{ display:flex; gap:10px; align-items:center; padding:6px 0; color: var(--ims-text); font-size:.92rem; }}
.ims-check i {{ font-style:normal; width:22px; height:22px; border-radius:50%; display:grid; place-items:center; font-size:.75rem; flex:none;
    border:2px solid var(--ims-line); color: transparent; }}
.ims-check.done i {{ background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); border-color: transparent; color:#fff; animation: imsPop .5s both; }}
.ims-check.done span {{ color: var(--ims-muted); text-decoration: line-through; }}

/* password strength */
.ims-strength {{ height:6px; border-radius:6px; background: var(--ims-line); overflow:hidden; margin:-4px 0 4px; }}
.ims-strength > div {{ height:100%; border-radius:6px; transition: width .4s cubic-bezier(.2,.8,.2,1), background .4s; }}

/* toasts */
[data-testid="stToast"] {{ border-radius:14px !important; box-shadow: 0 18px 40px -18px rgba({ar},.55) !important;
    border-left: 4px solid var(--ims-a) !important; }}

/* maker credit */
.ims-credit-line {{ text-align:center; margin-top: 2.4rem; font-size:.85rem; font-weight:600; letter-spacing:.02em; animation: imsFade 1s .3s both; }}
.ims-credit-line {{ background: linear-gradient(90deg, var(--ims-a), var(--ims-b), #06b6d4, var(--ims-a)); background-size:300% 100%; -webkit-background-clip:text; background-clip:text; color:transparent; animation: imsGradient 8s linear infinite; }}
.ims-credit {{ display:flex; align-items:center; justify-content:center; gap:14px; margin: 1.6rem auto .4rem; padding: 12px 18px;
    max-width: 520px; border-radius: 18px; background: var(--ims-card); border:1px solid var(--ims-line); box-shadow: var(--ims-shadow);
    animation: imsRise .7s .2s both; position:relative; overflow:hidden; }}
.ims-credit::after {{ content:""; position:absolute; top:0; left:0; width:30%; height:100%; pointer-events:none;
    background: linear-gradient(90deg, transparent, rgba({ar},.12), transparent); animation: imsShine 6s ease-in-out infinite; }}
.ims-credit .ims-avatar {{ width:42px; height:42px; animation: imsPulse 2.6s infinite; }}
.ims-credit b {{ display:block; color: var(--ims-text); font-size:.95rem; }}
.ims-credit span {{ color: var(--ims-muted); font-size:.8rem; }}
.ims-credit em {{ font-style:normal; font-size:.7rem; letter-spacing:.12em; text-transform:uppercase; color: var(--ims-a); font-weight:700; }}

/* stepper */
.ims-steps {{ display:flex; align-items:flex-start; justify-content:center; gap:0; margin: .4rem auto 1.6rem; max-width: 760px; }}
.ims-step {{ flex:1; text-align:center; position:relative; }}
.ims-step:not(:last-child)::after {{ content:""; position:absolute; top:17px; left:calc(50% + 22px); right:calc(-50% + 22px); height:3px;
    border-radius:3px; background: var(--ims-line); }}
.ims-step.done:not(:last-child)::before {{ content:""; position:absolute; top:17px; left:calc(50% + 22px); right:calc(-50% + 22px); height:3px;
    border-radius:3px; z-index:1; background: linear-gradient(90deg, var(--ims-a), var(--ims-b)); animation: imsBar .8s both; }}
.ims-step-dot {{ width:36px; height:36px; margin:0 auto; border-radius:50%; display:grid; place-items:center; font-weight:700;
    background: var(--ims-card-solid); border:2px solid var(--ims-line); color: var(--ims-muted); transition: all .3s; position:relative; z-index:2; }}
.ims-step.done .ims-step-dot {{ background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); color:#fff; border-color:transparent; }}
.ims-step.active .ims-step-dot {{ border-color: var(--ims-a); color: var(--ims-a); animation: imsPulse 2s infinite; }}
.ims-step-label {{ font-size:.76rem; margin-top:6px; color: var(--ims-muted); }}
.ims-step.active .ims-step-label {{ color: var(--ims-text); font-weight:650; }}

/* misc */
.ims-glass {{ background: var(--ims-card); border:1px solid var(--ims-line); border-radius:22px; padding: 22px 24px;
    box-shadow: var(--ims-shadow); backdrop-filter: blur(10px); animation: imsRise .55s both; }}
.ims-user {{ display:flex; gap:10px; align-items:center; padding:10px 12px; border-radius:14px; background: var(--ims-card);
    border:1px solid var(--ims-line); }}
.ims-avatar {{ width:36px; height:36px; border-radius:50%; display:grid; place-items:center; color:#fff; font-weight:700; font-size:.85rem;
    background: linear-gradient(135deg, var(--ims-a), var(--ims-b)); flex: none; }}
.ims-user b {{ display:block; font-size:.88rem; color: var(--ims-text); line-height:1.2; }}
.ims-user span {{ font-size:.74rem; color: var(--ims-muted); }}
.ims-feature {{ display:flex; gap:12px; align-items:flex-start; padding: 10px 0; }}
.ims-feature i {{ font-style:normal; width:34px; height:34px; border-radius:10px; flex:none; display:grid; place-items:center;
    background: rgba({ar},.12); color: var(--ims-a); font-weight:700; }}
.ims-feature b {{ display:block; color: var(--ims-text); font-size:.92rem; }}
.ims-feature span {{ color: var(--ims-muted); font-size:.84rem; }}
.ims-progress {{ height:8px; border-radius:8px; background: var(--ims-line); overflow:hidden; }}
.ims-progress > div {{ height:100%; border-radius:8px; background: linear-gradient(90deg, var(--ims-a), var(--ims-b)); animation: imsBar 1.1s cubic-bezier(.2,.8,.2,1) both; }}
.ims-footer {{ text-align:center; color: var(--ims-muted); font-size:.78rem; margin-top: 2.5rem; opacity:.8; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}
{landing_css}
</style>""")


COUNT_UP_JS = """
<script>
(function () {
  function run() {
    var els = document.querySelectorAll('.ims-count:not([data-done])');
    els.forEach(function (el) {
      el.setAttribute('data-done', '1');
      var to = parseFloat(el.getAttribute('data-to')) || 0;
      var dec = parseInt(el.getAttribute('data-dec') || '0', 10);
      var pre = el.getAttribute('data-pre') || '';
      var suf = el.getAttribute('data-suf') || '';
      var t0 = null, dur = 1100;
      function step(ts) {
        if (t0 === null) { t0 = ts; }
        var p = Math.min((ts - t0) / dur, 1);
        var e = 1 - Math.pow(1 - p, 3);
        el.textContent = pre + (to * e).toLocaleString(undefined, {minimumFractionDigits: dec, maximumFractionDigits: dec}) + suf;
        if (p !== 1) { requestAnimationFrame(step); }
      }
      requestAnimationFrame(step);
    });
  }
  setTimeout(run, 60);
  setTimeout(run, 600);
})();
</script>
"""


def count_up():
    st.html(COUNT_UP_JS, unsafe_allow_javascript=True)


def count_span(value: float, decimals: int = 0, prefix: str = "", suffix: str = "") -> str:
    shown = f"{prefix}{value:,.{decimals}f}{suffix}"
    return (f'<span class="ims-count" data-to="{value}" data-dec="{decimals}" '
            f'data-pre="{esc(prefix)}" data-suf="{esc(suffix)}">{esc(shown)}</span>')


def hero(inst: dict, accent: str, eyebrow: str, title: str, subtitle: str = "",
         stats: list[tuple[str, str]] | None = None):
    logo = branding.data_uri(branding.logo_bytes(inst, accent))
    stats_html = ""
    if stats:
        stats_html = '<div class="ims-hero-stats">' + "".join(
            f'<div class="ims-hero-stat" style="animation-delay:{.1 + i * .08:.2f}s"><b>{v}</b><span>{esc(k)}</span></div>'
            for i, (k, v) in enumerate(stats)) + "</div>"
    st.html(f"""
<div class="ims-hero">
  <div class="ims-blob" style="width:220px;height:220px;right:-60px;top:-80px"></div>
  <div class="ims-blob" style="width:140px;height:140px;right:180px;bottom:-70px;animation-delay:-3s"></div>
  <div class="ims-blob" style="width:70px;height:70px;left:46%;top:14px;animation-delay:-6s"></div>
  <div class="ims-hero-row">
    <img class="ims-hero-logo" src="{logo}" alt="logo">
    <div style="flex:1;min-width:220px">
      <div class="ims-eyebrow">{esc(eyebrow)}</div>
      <h1>{esc(title)}</h1>
      <p>{esc(subtitle)}</p>
    </div>
  </div>
  {stats_html}
</div>""")
    if stats:
        count_up()


def page_header(title: str, subtitle: str = "", tips: list[str] | None = None):
    head, help_col = st.columns([12, 2], vertical_alignment="center")
    with head:
        st.html(f"""<div class="ims-ph"><div class="ims-ph-title"><span class="ims-dot"></span>{esc(title)}</div>
        {f'<div class="ims-ph-sub">{esc(subtitle)}</div>' if subtitle else ''}<div class="ims-ph-bar"></div></div>""")
    if tips:
        with help_col.popover("How to use", icon=":material/help:", width="stretch"):
            for i, tip in enumerate(tips, 1):
                st.markdown(f"**{i}.** {tip}")


def quick_actions(items: list[tuple[str, str, str, str]]):
    """items: (page path, label, material icon, caption). Animated tiles that open pages."""
    if not items:
        return
    row = st.container(horizontal=True, gap="small")
    for i, (path, label, icon, caption) in enumerate(items):
        with row.container(key=f"qa_{i}", width="stretch"):
            st.page_link(path, label=label, icon=icon)
            st.caption(caption)


def checklist(steps: list[tuple[str, bool, str | None]], title="Getting started"):
    """steps: (text, done, page path to open). Shows a progress ring + clickable remaining steps."""
    done = sum(1 for _, d, _ in steps if d)
    pct = round(done / len(steps) * 100)
    with st.container(border=True):
        c1, c2 = st.columns([1, 4], vertical_alignment="center")
        c1.html(f'<div class="ims-ring" style="--p:{pct}"><div>{pct}%</div></div>')
        with c2:
            st.markdown(f"**{title}** · {done} of {len(steps)} done")
            st.html("".join(f'<div class="ims-check {"done" if d else ""}"><i>✓</i><span>{esc(t)}</span></div>'
                            for t, d, _ in steps))
        todo = [(t, p) for t, d, p in steps if not d and p]
        if todo:
            row = st.container(horizontal=True)
            for t, p in todo[:4]:
                row.page_link(p, label=t, icon=":material/arrow_forward:")


def password_meter(pw: str):
    score = sum([len(pw) >= 8, len(pw) >= 12, any(c.isdigit() for c in pw), any(c.isalpha() for c in pw),
                 any(not c.isalnum() for c in pw), any(c.isupper() for c in pw) and any(c.islower() for c in pw)])
    labels = ["Too short", "Weak", "Weak", "Fair", "Good", "Strong", "Excellent"]
    colors = ["#ef4444", "#ef4444", "#f97316", "#eab308", "#22c55e", "#16a34a", "#059669"]
    width = max(6, score / 6 * 100) if pw else 0
    st.html(f'<div class="ims-strength"><div style="width:{width:.0f}%;background:{colors[score]}"></div></div>'
            f'<div style="font-size:.75rem;color:{colors[score]};margin-bottom:6px">{labels[score] if pw else ""}</div>')


def stepper(labels: list[str], current: int):
    parts = []
    for i, label in enumerate(labels):
        cls = "done" if i < current else "active" if i == current else ""
        mark = "✓" if i < current else str(i + 1)
        parts.append(f'<div class="ims-step {cls}"><div class="ims-step-dot">{mark}</div>'
                     f'<div class="ims-step-label">{esc(label)}</div></div>')
    st.html(f'<div class="ims-steps">{"".join(parts)}</div>')


def user_chip(name: str, role: str):
    ini = "".join(w[0] for w in name.split()[:2]).upper() or "U"
    st.html(f'<div class="ims-user"><div class="ims-avatar">{esc(ini)}</div>'
            f'<div><b>{esc(name)}</b><span>{esc(role)}</span></div></div>')


def progress(pct: float, label: str = ""):
    pct = max(0.0, min(100.0, pct or 0))
    st.html(f'<div style="margin:4px 0 10px"><div style="display:flex;justify-content:space-between;font-size:.82rem;'
            f'color:var(--ims-muted);margin-bottom:4px"><span>{esc(label)}</span><span>{pct:.1f}%</span></div>'
            f'<div class="ims-progress"><div style="width:{pct:.1f}%"></div></div></div>')


def footer(text: str):
    st.html(f'<div class="ims-footer">{esc(text)}</div>')


def maker_credit():
    from . import MAKER_LINE
    st.html(f'<div class="ims-credit-line">{esc(MAKER_LINE)}</div>')


TYPE_ICONS = {
    "school": '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10l9-6 9 6"/><path d="M5 10v9h14v-9"/><path d="M10 19v-5h4v5"/><path d="M12 4v-2"/><path d="M12 2h3v2h-3"/></svg>',
    "college": '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 7l10-4 10 4-10 4z"/><path d="M6 9v5c0 1.7 2.7 3 6 3s6-1.3 6-3V9"/><path d="M22 7v6"/></svg>',
    "university": '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-5 9 5"/><path d="M4 9h16"/><path d="M6 9v8M10 9v8M14 9v8M18 9v8"/><path d="M3 20h18"/><path d="M4 17h16"/></svg>',
}


def svg_uri(svg: str, color: str = "#ffffff") -> str:
    """st.html strips inline <svg>, so icons are embedded as data-URI images."""
    import base64
    svg = svg.replace('stroke="currentColor"', f'stroke="{color}"').replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def type_card(kind: str, title: str, desc: str, tags: list[str], selected: bool):
    check = '<div class="ims-type-check">✓</div>' if selected else ""
    st.html(f"""<div class="ims-type {'selected' if selected else ''}">{check}
      <div class="ims-type-icon"><img src="{svg_uri(TYPE_ICONS[kind])}" width="32" height="32" alt=""></div>
      <div class="ims-type-title">{esc(title.upper())}</div>
      <div class="ims-type-desc">{esc(desc)}</div>
      <div class="ims-type-tags">{''.join(f'<span>{esc(t)}</span>' for t in tags)}</div></div>""")


def badge_md(state: str) -> str:
    colors = {"paid": "green", "published": "green", "approved": "green", "active": "green", "accepted": "green",
              "present": "green", "partial": "orange", "reviewed": "violet", "submitted": "blue", "pending": "orange",
              "under_review": "blue", "unpaid": "red", "rejected": "red", "absent": "red", "overdue": "red",
              "cancelled": "gray", "draft": "gray", "waitlisted": "orange", "withdrawn": "gray",
              "transferred": "gray", "graduated": "violet", "on_leave": "orange", "late": "orange"}
    return f":{colors.get(state, 'gray')}-badge[{state.replace('_', ' ').title()}]"


def fmt_date(value, settings: dict) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)[:19]).strftime(settings.get("date_format", "%d-%b-%Y"))
    except ValueError:
        return str(value)


def money(value, settings: dict) -> str:
    return f"{settings.get('currency', '')} {float(value or 0):,.2f}"
