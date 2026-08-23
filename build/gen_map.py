#!/usr/bin/env python3
"""Rebuild the payroll customer map HTML from the Snowflake extract.

Reads build/map_data.csv (the map_build.sql extract) and writes the plaintext
map to map.source.html at the repo root. Run encrypt.py afterwards to produce
the password-gated index.html.
"""
import csv, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, 'build', 'map_data.csv')
OUT_PATH = os.path.join(ROOT, 'map.source.html')

ROWS = list(csv.DictReader(open(CSV_PATH)))

# Auto Payroll enrollment is not represented anywhere in Snowflake; the original
# map's values were hand-curated. Carry that curated set forward.
AP_YES = {'yankeelobstercompany'}

CRIT = [('tips','E_TIPS'),('active','E_ACTIVE'),('pos','E_POS'),('tax','E_TAX'),
        ('tsAuto','E_TSAUTO'),('live3','E_LIVE3'),('bounce','E_BOUNCE'),('post','E_POST')]

def f1(v):
    """Trim trailing .0 so distances render as 6.4 / 3 rather than 6.4 / 3.0."""
    x = round(float(v), 1)
    return int(x) if x == int(x) else x

elig, data = {}, []
for r in ROWS:
    cc = r['CC']
    if cc and cc not in elig:
        elig[cc] = {k: r[col] for k, col in CRIT}

    name = (r['REST_NAME'] or '').strip()
    locname = (r['REST_LOC_NAME'] or '').strip()
    if locname and locname.lower() != name.lower():
        name = f"{name} - {locname}" if name else locname

    data.append({
        'dh': f1(r['DH']), 'do': f1(r['DO']),
        'lat': float(r['LAT']), 'lon': float(r['LON']),
        'name': name, 'addr': (r['ADDR'] or '').strip(), 'city': (r['CITY'] or '').strip(), 'zip': (r['ZIP'] or '').strip(),
        'locs': int(r['LOCS']),
        'pnps': int(r['PNPS']) if r['PNPS'] else None,
        'nps': r['NPS'] or '',
        'tickets': int(r['TICKETS']),
        'sched': r['SCHED'], 'tips': r['TIPS'],
        'ap': 'Yes' if cc in AP_YES else 'No',
        'pname': (r['POSTER_NAME'] or '').strip(), 'pemail': (r['POSTER_EMAIL'] or '').strip(),
        'fp': r['FIRST_PAYROLL'] or '',
        'rep': (r['REP'] or '').strip(), 'email': (r['REP_EMAIL'] or '').strip(),
        'cc': cc,
    })

data.sort(key=lambda d: (d['name'] or '').lower())

def js_obj(d):
    """Compact JS object literal, keys unquoted, matching the original style."""
    parts = []
    for k, v in d.items():
        if v is None:
            s = 'null'
        elif isinstance(v, bool):
            s = 'true' if v else 'false'
        elif isinstance(v, (int, float)):
            s = repr(v)
        else:
            s = json.dumps(v, ensure_ascii=False)
        parts.append(f'{k}:{s}')
    return '{' + ','.join(parts) + '}'

elig_js = '\n'.join(
    f'  {json.dumps(cc)}: {js_obj(v)},' for cc, v in sorted(elig.items())
)
data_js = '\n'.join(f'  {js_obj(d)},' for d in data)

n_locs = len(data)
n_cust = len(elig)
n_office = sum(1 for d in data if d['do'] <= 6)
n_home = sum(1 for d in data if d['dh'] <= 3)
n_ap = sum(1 for d in data if d['ap'] == 'Yes')

HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payroll Customers — Boston Area</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --surface-1:     #fcfcfb; --surface-2:    #f9f9f7;
    --text-primary:  #0b0b0b; --text-secondary:#52514e; --text-muted:#898781;
    --gridline:      #e1e0d9;
    --promoter:      #0ca30c; --passive:#eda100; --detractor:#d03b3b; --no-nps:#898781;
    --home-pin:      #2a78d6; --office-pin:#4a3aa7; --auto-ring:#eda100;
    --good: #0ca30c; --bad: #d03b3b; --unknown: #c3c2b7;
  }}
  body {{ font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--surface-2); color:var(--text-primary); height:100vh; display:flex; flex-direction:column; }}
  header {{ padding:7px 14px; background:var(--surface-1); border-bottom:1px solid var(--gridline); display:flex; align-items:center; gap:11px; flex-shrink:0; flex-wrap:wrap; }}
  header h1 {{ font-size:13px; font-weight:600; white-space:nowrap; }}
  .fg {{ display:flex; align-items:center; gap:5px; flex-wrap:wrap; }}
  .fl {{ font-size:11px; color:var(--text-secondary); white-space:nowrap; }}
  .dv {{ width:1px; height:18px; background:var(--gridline); flex-shrink:0; }}
  .fb {{ font-size:11px; padding:3px 8px; border-radius:4px; border:1px solid var(--gridline); background:var(--surface-1); color:var(--text-secondary); cursor:pointer; white-space:nowrap; transition:background .1s,color .1s; }}
  .fb:hover {{ background:var(--surface-2); }}
  .fb.active {{ background:var(--text-primary); color:var(--surface-1); border-color:var(--text-primary); }}
  .legend {{ display:flex; gap:9px; align-items:center; margin-left:auto; flex-wrap:wrap; }}
  .li {{ display:flex; align-items:center; gap:4px; font-size:10px; color:var(--text-secondary); }}
  .ld {{ width:8px; height:8px; border-radius:50%; border:1.5px solid rgba(0,0,0,0.15); flex-shrink:0; }}
  .lr {{ width:10px; height:10px; border-radius:50%; border:2px solid var(--auto-ring); flex-shrink:0; }}
  #map {{ flex:1; min-height:0; }}

  /* Popup */
  .leaflet-popup-content-wrapper {{ border-radius:8px; box-shadow:0 4px 18px rgba(0,0,0,0.16); padding:0; overflow:hidden; min-width:290px; }}
  .leaflet-popup-content {{ margin:0; width:auto !important; }}
  .leaflet-popup-tip-container {{ display:none; }}
  .pu {{ padding:12px 14px; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .pu-name {{ font-size:13px; font-weight:600; color:#0b0b0b; margin-bottom:2px; line-height:1.3; }}
  .pu-addr {{ font-size:11px; color:#52514e; margin-bottom:7px; }}
  .pu-dists {{ display:flex; gap:14px; margin-bottom:7px; }}
  .pu-dist {{ font-size:11px; }}
  .pu-dist-label {{ color:#898781; }}
  .pu-dist-val {{ font-weight:600; color:#0b0b0b; }}
  .pu-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; margin-bottom:7px; }}
  .pu-label {{ font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#898781; margin-bottom:1px; }}
  .pu-val {{ font-size:12px; font-weight:500; color:#0b0b0b; }}
  .pu-poster {{ border-top:1px solid #e1e0d9; padding-top:7px; margin-bottom:7px; }}
  .pu-poster a {{ color:#2a78d6; text-decoration:none; font-size:11px; }}
  .pu-poster a:hover {{ text-decoration:underline; }}
  .pu-chips {{ display:flex; gap:4px; flex-wrap:wrap; margin-bottom:7px; }}
  .chip {{ font-size:10px; padding:2px 6px; border-radius:3px; background:#f0efec; color:#52514e; font-weight:500; }}
  .chip.on {{ background:#e8f2ff; color:#1c5cab; }}
  .chip.auto {{ background:#fff4e0; color:#7a5000; border:1px solid #eda100; }}
  .pu-elig {{ border-top:1px solid #e1e0d9; padding-top:7px; margin-bottom:7px; }}
  .pu-elig-title {{ font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#898781; margin-bottom:5px; display:flex; align-items:center; gap:6px; }}
  .pu-elig-title span {{ font-weight:600; font-size:11px; color:#0b0b0b; text-transform:none; letter-spacing:0; }}
  .pu-elig-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:3px 8px; }}
  .pu-elig-row {{ display:flex; align-items:center; gap:5px; font-size:11px; color:#52514e; }}
  .dot {{ width:7px; height:7px; border-radius:50%; flex-shrink:0; }}
  .dot-yes {{ background:#0ca30c; }}
  .dot-no  {{ background:#d03b3b; }}
  .dot-unk {{ background:#c3c2b7; }}
  .pu-rep {{ font-size:11px; color:#52514e; border-top:1px solid #e1e0d9; padding-top:7px; }}
  .pu-rep a {{ color:#2a78d6; text-decoration:none; }}
  .pu-rep a:hover {{ text-decoration:underline; }}

  /* Pins */
  .map-pin {{ position:relative; width:24px; height:32px; cursor:pointer; }}
  .map-pin svg {{ width:24px; height:32px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.22)); transition:transform .1s; }}
  .map-pin:hover svg {{ transform:scale(1.15); }}
  .count-badge {{ position:absolute; top:3px; left:50%; transform:translateX(-50%); font-size:8px; font-weight:700; color:white; line-height:1; pointer-events:none; }}
  .auto-ring {{ position:absolute; top:-3px; left:-3px; width:30px; height:30px; border-radius:50%; border:2.5px solid var(--auto-ring); pointer-events:none; }}
</style>
</head>
<body>
<header>
  <h1>Payroll Customers — Boston Area</h1>

  <div class="fg">
    <span class="fl">NPS:</span>
    <button class="fb active" data-nps="all">All</button>
    <button class="fb" data-nps="Promoter">Promoters</button>
    <button class="fb" data-nps="Passive">Passives</button>
    <button class="fb" data-nps="Detractor">Detractors</button>
    <button class="fb" data-nps="none">No NPS</button>
  </div>

  <div class="dv"></div>

  <div class="fg">
    <span class="fl">Auto Payroll:</span>
    <button class="fb active" data-ap="all">All</button>
    <button class="fb" data-ap="Yes">Enabled*</button>
    <button class="fb" data-ap="No">Not enabled</button>
  </div>

  <div class="dv"></div>

  <div class="fg">
    <span class="fl">Eligibility:</span>
    <button class="fb active" data-elig="all">All</button>
    <button class="fb" data-elig="eligible">Fully eligible</button>
    <button class="fb" data-elig="1miss">1 criterion missing</button>
    <button class="fb" data-elig="unknown">Data unknown</button>
  </div>

  <div class="dv"></div>

  <div class="fg">
    <span class="fl">Area:</span>
    <button class="fb active" data-area="all">All</button>
    <button class="fb" data-area="home">Near home (≤3 mi)</button>
    <button class="fb" data-area="office">Near office (≤2 mi)</button>
  </div>

  <div class="legend">
    <div class="li"><div class="ld" style="background:#0ca30c"></div>Promoter</div>
    <div class="li"><div class="ld" style="background:#eda100"></div>Passive</div>
    <div class="li"><div class="ld" style="background:#d03b3b"></div>Detractor</div>
    <div class="li"><div class="ld" style="background:#898781"></div>No NPS</div>
    <div class="li"><div class="lr"></div>Auto Payroll*</div>
    <div class="li"><div class="ld" style="background:#2a78d6"></div>Home</div>
    <div class="li"><div class="ld" style="background:#4a3aa7"></div>Office</div>
  </div>
</header>

<div id="map"></div>

<script>
// Eligibility per company code from Snowflake
// fields: [tips, active, pos, tax, tsAuto, live3mo, noBounce, allowPost]
// 'Y'=Yes, 'N'=No, '?'=unknown/not found in system
const ELIG = {{
{elig_js}
}};

// cc = company code key into ELIG. null = data unavailable
const DATA = [
{data_js}
];

const CRIT_LABELS = {{tips:"Tips integration",active:"Active status",pos:"POS customer",tax:"Tax tasks complete",tsAuto:"TS auto-approval",live3:"Live 3+ months",bounce:"No bounces 6mo",post:"Allowed to post"}};

const NPS_COLOR = {{Promoter:"#0ca30c",Passive:"#eda100",Detractor:"#d03b3b","":"#898781"}};

function eligScore(cc) {{
  if (!cc || !ELIG[cc]) return null;
  const e = ELIG[cc];
  const vals = Object.values(e);
  if (vals.some(v => v === '?')) return -1; // unknown
  return vals.filter(v => v === 'Y').length;
}}

function pinColor(c) {{ return NPS_COLOR[c.nps] || "#898781"; }}

function makePinIcon(color, locs, isAuto) {{
  const badge = locs > 1 ? `<span class="count-badge">${{locs > 9 ? "9+" : locs}}</span>` : "";
  const ring  = isAuto ? '<div class="auto-ring"></div>' : "";
  const svg   = `<svg viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg"><path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 20 12 20s12-11 12-20C24 5.373 18.627 0 12 0z" fill="${{color}}" stroke="rgba(0,0,0,0.18)" stroke-width="0.75"/><circle cx="12" cy="12" r="4.5" fill="rgba(255,255,255,0.85)"/></svg>`;
  return L.divIcon({{html:`<div class="map-pin">${{ring}}${{svg}}${{badge}}</div>`,className:"",iconSize:[24,32],iconAnchor:[12,32],popupAnchor:[0,-36]}});
}}

function makeSpecialIcon(color, label) {{
  const svg = `<svg viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg"><path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 20 12 20s12-11 12-20C24 5.373 18.627 0 12 0z" fill="${{color}}" stroke="rgba(0,0,0,0.18)" stroke-width="0.75"/><text x="12" y="16" text-anchor="middle" font-size="9" font-weight="800" fill="white" font-family="system-ui">${{label}}</text></svg>`;
  return L.divIcon({{html:`<div class="map-pin">${{svg}}</div>`,className:"",iconSize:[24,32],iconAnchor:[12,32],popupAnchor:[0,-36]}});
}}

function npsHtml(c) {{
  if (c.pnps === null) return '<span style="color:#898781">—</span>';
  const col = NPS_COLOR[c.nps] || "#898781";
  return `<span style="color:${{col}};font-weight:600">${{c.pnps}}</span>&nbsp;<span style="color:${{col}};font-size:10px">${{c.nps}}</span>`;
}}

function posterHtml(c) {{
  if (!c.pname && !c.pemail) return '<span style="color:#898781;font-size:11px">—</span>';
  const nm = c.pname ? `<span style="font-size:12px;font-weight:500;color:#0b0b0b">${{c.pname}}</span>` : "";
  const em = c.pemail ? `<a href="mailto:${{c.pemail}}">${{c.pemail}}</a>` : "";
  return nm + (nm && em ? "<br>" : "") + em;
}}

function eligHtml(cc) {{
  if (!cc) return '<div style="font-size:11px;color:#898781;font-style:italic">Company code not found — eligibility unavailable</div>';
  const e = ELIG[cc];
  if (!e) return '<div style="font-size:11px;color:#898781;font-style:italic">Eligibility data not available</div>';
  const passing = Object.values(e).filter(v => v === 'Y').length;
  const total = Object.keys(e).length;
  const allPass = passing === total;
  const scoreColor = allPass ? '#0ca30c' : passing >= 6 ? '#eda100' : '#d03b3b';
  const rows = Object.entries(CRIT_LABELS).map(([k, label]) => {{
    const v = e[k];
    const cls = v === 'Y' ? 'dot-yes' : v === 'N' ? 'dot-no' : 'dot-unk';
    const text = v === 'Y' ? label : v === 'N' ? `<span style="color:#d03b3b">${{label}}</span>` : label;
    return `<div class="pu-elig-row"><div class="dot ${{cls}}"></div>${{text}}</div>`;
  }}).join('');
  return `
    <div class="pu-elig-title">Auto Payroll Eligibility&nbsp;<span style="color:${{scoreColor}}">${{passing}}/${{total}}</span></div>
    <div class="pu-elig-grid">${{rows}}</div>`;
}}

function makePopup(c) {{
  return `<div class="pu">
    <div class="pu-name">${{c.name}}</div>
    <div class="pu-addr">${{c.addr}}, ${{c.city}} ${{c.zip}}</div>
    <div class="pu-dists">
      <div class="pu-dist"><span class="pu-dist-label">🏠 Home: </span><span class="pu-dist-val">${{c.dh}} mi</span></div>
      <div class="pu-dist"><span class="pu-dist-label">🏢 Office: </span><span class="pu-dist-val">${{c.do}} mi</span></div>
    </div>
    <div class="pu-grid">
      <div><div class="pu-label">pNPS</div><div class="pu-val">${{npsHtml(c)}}</div></div>
      <div><div class="pu-label">Locations</div><div class="pu-val">${{c.locs}}</div></div>
      <div><div class="pu-label">Care tickets (12mo)</div><div class="pu-val">${{c.tickets}}</div></div>
      <div><div class="pu-label">First payroll</div><div class="pu-val">${{c.fp||"—"}}</div></div>
    </div>
    <div class="pu-poster">
      <div class="pu-label">Last processed payroll</div>
      ${{posterHtml(c)}}
    </div>
    <div class="pu-chips">
      <span class="chip on">Payroll</span>
      ${{c.ap==="Yes"?'<span class="chip auto">Auto Payroll*</span>':""}}
      ${{c.sched==="Yes"?'<span class="chip on">Scheduling</span>':'<span class="chip">Scheduling</span>'}}
      ${{c.tips==="Yes"?'<span class="chip on">Tips Mgr</span>':'<span class="chip">Tips Mgr</span>'}}
    </div>
    <div class="pu-elig">${{eligHtml(c.cc)}}</div>
    <div class="pu-rep"><strong>${{c.rep}}</strong> &middot; <a href="mailto:${{c.email}}">${{c.email}}</a></div>
  </div>`;
}}

const map = L.map("map").setView([42.383, -71.07], 12);
L.tileLayer("https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png",{{
  attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains:"abcd",maxZoom:19
}}).addTo(map);

L.marker([42.4073,-71.1454],{{icon:makeSpecialIcon("#2a78d6","H")}})
  .addTo(map).bindPopup('<div class="pu"><div class="pu-name">Your Home</div><div class="pu-addr">East Arlington, MA 02474</div></div>');
L.marker([42.3498,-71.0484],{{icon:makeSpecialIcon("#4a3aa7","O")}})
  .addTo(map).bindPopup('<div class="pu"><div class="pu-name">Toast HQ</div><div class="pu-addr">333 Summer Street, Boston, MA 02210</div></div>');

const noteCtrl = L.control({{position:"bottomleft"}});
noteCtrl.onAdd = () => {{
  const d = L.DomUtil.create("div");
  d.style.cssText = "background:rgba(252,252,251,0.93);padding:6px 10px;border-radius:6px;font-size:10px;color:#52514e;border:1px solid #e1e0d9;max-width:300px;line-height:1.45;";
  d.innerHTML = "{n_locs} payroll-Live locations ({n_cust} customers) — {n_office} within 6 mi of the office, {n_home} within 3 mi of home. &bull; <strong>Auto Payroll</strong>: best-effort proxy — not tracked in Snowflake; {n_ap} hand-confirmed. &bull; Eligibility from live Snowflake data; <em>Tax tasks complete</em> is a proxy (~82% agreement with prior values). &bull; <strong>Last processed payroll</strong> = user of the most recent successful payroll open.";
  return d;
}};
noteCtrl.addTo(map);

const markerLayer = L.layerGroup().addTo(map);
let activeNps="all", activeAp="all", activeElig="all", activeArea="all";

function renderMarkers() {{
  markerLayer.clearLayers();
  DATA.forEach(c => {{
    if (activeNps!=="all" && activeNps!=="none" && c.nps!==activeNps) return;
    if (activeNps==="none" && c.nps!=="") return;
    if (activeAp!=="all" && c.ap!==activeAp) return;
    if (activeArea==="home"   && c.dh>3) return;
    if (activeArea==="office" && c.do>2) return;
    if (activeElig !== "all") {{
      const score = eligScore(c.cc);
      if (activeElig === "eligible"   && score !== 8) return;
      if (activeElig === "1miss"      && score !== 7) return;
      if (activeElig === "unknown"    && score !== null && score !== -1) return;
    }}
    L.marker([c.lat,c.lon],{{icon:makePinIcon(pinColor(c),c.locs,c.ap==="Yes")}})
      .bindPopup(makePopup(c),{{maxWidth:340,minWidth:300}})
      .addTo(markerLayer);
  }});
}}

renderMarkers();

[["nps",v=>activeNps=v],["ap",v=>activeAp=v],["elig",v=>activeElig=v],["area",v=>activeArea=v]].forEach(([attr,setter])=>{{
  document.querySelectorAll(`[data-${{attr}}]`).forEach(btn=>{{
    btn.addEventListener("click",()=>{{
      document.querySelectorAll(`[data-${{attr}}]`).forEach(b=>b.classList.remove("active"));
      btn.classList.add("active");
      setter(btn.dataset[attr]);
      renderMarkers();
    }});
  }});
}});
</script>
</body>
</html>
'''

open(OUT_PATH, 'w').write(HTML)
print(f"wrote {OUT_PATH}  locations={n_locs} customers={n_cust} "
      f"office<=6mi={n_office} home<=3mi={n_home} ap_yes={n_ap}")
