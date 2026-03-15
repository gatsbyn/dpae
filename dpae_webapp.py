#!/usr/bin/env python3
"""
DPAE Webapp - Interface web locale pour envoyer vos DPAE
Lancez: python3 dpae_webapp.py
Ouvrez: http://localhost:5000
"""

import configparser, gzip, json, os, sys, webbrowser, xml.etree.ElementTree as ET
from datetime import datetime
from threading import Timer

try:
    import requests as req
except ImportError:
    print("pip3 install requests flask")
    sys.exit(1)

try:
    from flask import Flask, request, jsonify, Response
except ImportError:
    print("Installez Flask: pip3 install flask")
    sys.exit(1)

app = Flask(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

def load_config():
    if os.environ.get("DPAE_SIRET"):
        return {"siret": os.environ.get("DPAE_SIRET", ""), "nom": os.environ.get("DPAE_NOM", ""), "prenom": os.environ.get("DPAE_PRENOM", ""), "motdepasse": os.environ.get("DPAE_MDP", ""), "service": os.environ.get("DPAE_SERVICE", "25")}
    if not os.path.exists(CONFIG_FILE):
        return {}
    c = configparser.RawConfigParser()
def save_config(data):
    c = configparser.RawConfigParser()
    c.add_section("URSSAF")
    for k, v in data.items():
        c.set("URSSAF", k, v)
    c.add_section("URLS")
    c.set("URLS", "authentification", "https://mon.urssaf.fr/authentifier_dpae")
    c.set("URLS", "depot", "https://depot.dpae-edi.urssaf.fr/deposer-dsn/1.0/")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        c.write(f)

# ── API Routes ──

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_config()
    if "motdepasse" in cfg:
        cfg["motdepasse_set"] = bool(cfg["motdepasse"])
        cfg["motdepasse"] = ""
    return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json
    old = load_config()
    if not data.get("motdepasse") and old.get("motdepasse"):
        data["motdepasse"] = old["motdepasse"]
    if "service" not in data:
        data["service"] = "25"
    save_config(data)
    return jsonify({"ok": True})

@app.route("/api/send", methods=["POST"])
def send_dpae():
    cfg = load_config()
    if not cfg.get("siret") or not cfg.get("motdepasse"):
        return jsonify({"error": "Identifiants non configurés"}), 400

    xml_content = request.form.get("xml", "")
    test_mode = request.form.get("test", "false") == "true"
    filename = request.form.get("filename", "dpae.xml")

    if not xml_content:
        f = request.files.get("file")
        if f:
            xml_content = f.read().decode("iso-8859-1")
            filename = f.filename

    if not xml_content:
        return jsonify({"error": "Aucun fichier XML"}), 400

    # Test mode
    if test_mode:
        xml_content = xml_content.replace(
            "<FR_DUE_Upload.Test.Indicator>120</FR_DUE_Upload.Test.Indicator>",
            "<FR_DUE_Upload.Test.Indicator>TST</FR_DUE_Upload.Test.Indicator>",
        )

    # Auth
    auth_body = f"<identifiants><siret>{cfg['siret']}</siret><nom>{cfg['nom']}</nom><prenom>{cfg['prenom']}</prenom><motdepasse>{cfg['motdepasse']}</motdepasse><service>{cfg.get('service','25')}</service></identifiants>"
    try:
        r = req.post("https://mon.urssaf.fr/authentifier_dpae",
            data=auth_body.encode("utf-8"),
            headers={"Content-Type": "application/xml"}, timeout=30)
    except Exception as e:
        return jsonify({"error": f"Connexion impossible: {e}"}), 500

    if r.status_code != 200:
        msgs = {401: "Identifiants incorrects", 422: "Compte non autorisé", 500: "Erreur serveur Urssaf"}
        return jsonify({"error": msgs.get(r.status_code, f"Erreur auth HTTP {r.status_code}")}), 400

    token = r.text.strip()

    # Deposit
    try:
        xml_bytes = xml_content.encode("utf-8")
        xml_text = xml_bytes.decode("utf-8")
        xml_iso = xml_text.encode("iso-8859-1", errors="xmlcharrefreplace")
    except:
        xml_iso = xml_content.encode("iso-8859-1", errors="replace")
    gz = gzip.compress(xml_iso)
    try:
        r2 = req.post("https://depot.dpae-edi.urssaf.fr/deposer-dsn/1.0/",
            data=gz,
            headers={
                "Authorization": f"DSNLogin jeton={token}",
                "Content-Type": "text/plain",
                "Content-Encoding": "gzip",
                "Accept-Encoding": "gzip",
            }, timeout=60)
    except Exception as e:
        return jsonify({"error": f"Erreur dépôt: {e}"}), 500

    # Parse response
    resp_text = r2.text
    etat = "INCONNU"
    idflux = ""
    date_r = ""
    heure_r = ""
    essai = ""
    try:
        doc = ET.fromstring(resp_text.encode("utf-8"))
        for el in doc.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "envoi_etat": etat = el.text or ""
            elif tag == "idflux": idflux = el.text or ""
            elif tag == "date_reception": date_r = el.text or ""
            elif tag == "heure_reception": heure_r = el.text or ""
            elif tag == "essai_reel": essai = el.text or ""
    except:
        pass

    return jsonify({
        "ok": r2.status_code == 200 and etat == "OK",
        "status": r2.status_code,
        "etat": etat,
        "idflux": idflux,
        "date": date_r,
        "heure": heure_r,
        "mode": "TEST" if essai == "01" else "PRODUCTION",
        "raw": resp_text,
        "filename": filename,
    })


# ── HTML Page ──

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DPAE</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
::selection{background:#e8e0d4}
body{font-family:'Instrument Sans','SF Pro Display',-apple-system,sans-serif;background:#fafaf8;color:#1c1c1a;letter-spacing:-.01em;min-height:100vh}
.mono{font-family:'IBM Plex Mono',monospace}
a{color:inherit}
button{font-family:inherit;letter-spacing:-.01em;cursor:pointer;transition:opacity .12s}
button:hover{opacity:.85}
button:active{transform:scale(.98)}
input{font-family:inherit}
input:focus{outline:none;border-color:#1c1c1a}

nav{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid #ebe8e2}
.logo{display:flex;align-items:center;gap:10px;cursor:pointer}
.logo-icon{width:28px;height:28px;border-radius:8px;background:#1c1c1a;display:flex;align-items:center;justify-content:center}
.nav-tabs{display:flex;gap:4px}
.nav-tab{padding:6px 14px;border-radius:8px;border:none;font-size:13px;font-weight:500;background:transparent;color:#8a8880}
.nav-tab.active{background:#1c1c1a;color:#fafaf8}

.container{max-width:720px;margin:0 auto;padding:32px 20px}

h1{font-size:28px;font-weight:700;letter-spacing:-.03em}
.sub{color:#8a8880;font-size:14px;margin-top:6px}

.alert{padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;animation:slideUp .4s cubic-bezier(.16,1,.3,1)}
.alert-error{background:#fef2f2;border:1px solid #fecaca;color:#991b1b}
.alert-warn{background:#fefce8;border:1px solid #fde68a;color:#854d0e;cursor:pointer}
.alert .close{cursor:pointer;opacity:.5}

.dropzone{border:2px dashed #ddd8d0;border-radius:14px;padding:64px 32px;text-align:center;cursor:pointer;transition:all .2s}
.dropzone.over{border-color:#1c1c1a;background:#f5f3ef}
.dropzone-icon{width:48px;height:48px;border-radius:12px;background:#f0ede8;display:inline-flex;align-items:center;justify-content:center;margin-bottom:16px}

.pill{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;letter-spacing:.3px}
.pill-green{background:#dcfce7;color:#166534}
.pill-red{background:#fee2e2;color:#991b1b}
.pill-amber{background:#fef9c3;color:#854d0e}
.pill-blue{background:#dbeafe;color:#1e40af}
.pill-neutral{background:#f0ede8;color:#6b6960}

table{width:100%;border-collapse:collapse;font-size:13px}
th{padding:10px 14px;text-align:left;font-weight:500;color:#a8a49c;font-size:11px;text-transform:uppercase;letter-spacing:.05em;background:#fafaf8}
td{padding:11px 14px}
.table-wrap{border-radius:14px;border:1px solid #ebe8e2;overflow:hidden;margin-bottom:24px}
tbody tr{border-bottom:1px solid #f0ede8;transition:background .1s}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:#f5f3ef}
thead tr{border-bottom:1px solid #ebe8e2}

.btn{padding:11px 24px;border-radius:10px;font-size:14px;font-weight:600;border:none}
.btn-primary{background:#1c1c1a;color:#fafaf8}
.btn-outline{background:transparent;border:1.5px solid #ddd8d0;color:#6b6960;font-weight:500}
.btn-ghost{background:transparent;border:none;color:#a8a49c;font-size:13px;padding:11px 18px}
.btn:disabled{opacity:.4;cursor:not-allowed}

.field{margin-bottom:18px}
.field label{display:block;font-size:12px;font-weight:600;color:#8a8880;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}
.field input{width:100%;padding:10px 14px;border-radius:10px;border:1.5px solid #e0ddd6;font-size:14px;background:#fff;transition:border .15s}
.field .pwd-wrap{position:relative}
.field .pwd-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);cursor:pointer;font-size:13px;color:#a8a49c;user-select:none}

.result-icon{width:56px;height:56px;border-radius:16px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:16px}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px}
.stat-card{padding:14px 18px;border-radius:12px;border:1px solid #ebe8e2;background:#fff}
.stat-label{font-size:11px;color:#a8a49c;font-weight:500;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}

.history-item{padding:13px 18px;display:flex;align-items:center;gap:14px;transition:background .1s;border-bottom:1px solid #f0ede8}
.history-item:last-child{border-bottom:none}
.history-item:hover{background:#f5f3ef}
.history-dot{width:8px;height:8px;border-radius:4px;flex-shrink:0}

details summary{font-size:13px;color:#a8a49c;cursor:pointer;margin-bottom:8px}
pre.raw{background:#1c1c1a;color:#ccc8bf;padding:18px;border-radius:10px;font-size:11px;font-family:'IBM Plex Mono',monospace;overflow-x:auto;white-space:pre-wrap;line-height:1.7;max-height:240px}

.spinner{width:16px;height:16px;border:2px solid #ddd8d0;border-top-color:#1c1c1a;border-radius:50%;animation:spin .7s linear infinite;display:inline-block}

@keyframes slideUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes spin{to{transform:rotate(360deg)}}
.anim{animation:slideUp .5s cubic-bezier(.16,1,.3,1) both}
.d1{animation-delay:.06s}.d2{animation-delay:.12s}.d3{animation-delay:.18s}

.hidden{display:none}
</style>
</head>
<body>

<nav>
  <div class="logo" onclick="go('home')">
    <div class="logo-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fafaf8" stroke-width="2.5" stroke-linecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
    </div>
    <span style="font-size:15px;font-weight:600">DPAE</span>
  </div>
  <div class="nav-tabs">
    <button class="nav-tab active" data-view="home" onclick="go('home')">Envoyer</button>
    <button class="nav-tab" data-view="config" onclick="go('config')">Identifiants</button>
    <button class="nav-tab" data-view="history" onclick="go('history')">Historique</button>
  </div>
</nav>

<div class="container">
  <div id="error-bar" class="alert alert-error hidden"><span id="error-msg"></span><span class="close" onclick="hideError()">✕</span></div>
  <div id="config-warn" class="alert alert-warn hidden" onclick="go('config')"><span>Configurez vos identifiants pour commencer</span><span style="margin-left:auto;font-weight:600">Configurer →</span></div>

  <!-- HOME -->
  <div id="view-home" class="anim">
    <div style="margin-bottom:32px">
      <h1>Envoyer des DPAE</h1>
      <p class="sub">Déposez votre fichier XML pour déclarer vos embauches via l'API Urssaf</p>
    </div>
    <div id="dropzone" class="dropzone" onclick="document.getElementById('file-input').click()">
      <div class="dropzone-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#8a8880" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      </div>
      <div style="font-size:15px;font-weight:500">Glissez votre fichier ici</div>
      <div style="font-size:13px;color:#a8a49c;margin-top:4px">ou cliquez pour parcourir — format .xml</div>
    </div>
    <input type="file" id="file-input" accept=".xml" style="display:none">
  </div>

  <!-- CONFIG -->
  <div id="view-config" class="anim hidden">
    <h1>Identifiants</h1>
    <p class="sub" style="margin-bottom:28px">Mon profil → Gérer mes coordonnées sur urssaf.fr</p>
    <div class="field"><label>SIRET</label><input id="cfg-siret" class="mono" placeholder="14 chiffres"></div>
    <div class="field"><label>Nom</label><input id="cfg-nom" placeholder="Tel qu'affiché sur urssaf.fr"></div>
    <div class="field"><label>Prénom</label><input id="cfg-prenom" placeholder="Tel qu'affiché sur urssaf.fr"></div>
    <div class="field"><label>Mot de passe</label><div class="pwd-wrap"><input id="cfg-mdp" type="password"><span class="pwd-toggle" onclick="togglePwd()">voir</span></div></div>
    <button class="btn btn-primary" onclick="saveConfig()" style="margin-top:8px">Enregistrer</button>
    <div style="margin-top:16px;padding:10px 14px;border-radius:10px;background:#f5f3ef;font-size:12px;color:#8a8880">Stocké dans config.ini sur votre machine uniquement</div>
  </div>

  <!-- REVIEW -->
  <div id="view-review" class="anim hidden">
    <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:4px">
      <h1 id="rev-count"></h1>
      <span id="rev-mode" class="pill"></span>
    </div>
    <p class="sub" id="rev-info" style="margin-bottom:24px"></p>
    <div class="table-wrap anim d1">
      <table><thead><tr><th>Salarié</th><th>Naissance</th><th>Embauche</th><th>Fin</th><th></th></tr></thead>
      <tbody id="rev-tbody"></tbody></table>
    </div>
    <div id="rev-actions" class="anim d2" style="display:flex;gap:10px">
      <button class="btn btn-primary" onclick="sendDPAE(false)">Envoyer</button>
      <button class="btn btn-outline" onclick="sendDPAE(true)">Test</button>
      <button class="btn btn-ghost" onclick="go('home')" style="margin-left:auto">Annuler</button>
    </div>
    <div id="rev-sending" class="hidden" style="display:flex;align-items:center;gap:10px;padding:12px 0">
      <div class="spinner"></div>
      <span id="rev-progress" style="font-size:14px;color:#6b6960"></span>
    </div>
  </div>

  <!-- DONE -->
  <div id="view-done" class="anim hidden">
    <div style="text-align:center;padding:40px 0 24px">
      <div id="done-icon" class="result-icon"></div>
      <h1 id="done-title" style="font-size:24px;margin-bottom:6px"></h1>
      <p id="done-sub" class="sub" style="margin-top:0"></p>
    </div>
    <div id="done-stats" class="stat-grid anim d1"></div>
    <details class="anim d2" style="margin-bottom:28px">
      <summary>Réponse brute</summary>
      <pre id="done-raw" class="raw"></pre>
    </details>
    <div class="anim d3" style="display:flex;gap:10px">
      <button class="btn btn-primary" onclick="go('home')">Nouvelle déclaration</button>
      <a href="https://www.urssaf.fr" target="_blank" class="btn btn-outline" style="text-decoration:none;display:inline-block">Vérifier sur urssaf.fr</a>
    </div>
  </div>

  <!-- HISTORY -->
  <div id="view-history" class="anim hidden">
    <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:24px">
      <h1>Historique</h1>
      <span id="hist-clear" style="font-size:13px;color:#a8a49c;cursor:pointer" onclick="clearHistory()">Effacer</span>
    </div>
    <div id="hist-empty" style="color:#a8a49c;font-size:14px">Aucun envoi pour le moment</div>
    <div id="hist-list" style="border-radius:14px;border:1px solid #ebe8e2;overflow:hidden"></div>
  </div>
</div>

<script>
let currentView = 'home';
let xmlContent = '';
let xmlFilename = '';
let parsedData = null;
let configOk = false;
let history = JSON.parse(localStorage.getItem('dpae_hist') || '[]');

// Nav
function go(view) {
  document.querySelectorAll('[id^="view-"]').forEach(el => el.classList.add('hidden'));
  document.getElementById('view-' + view).classList.remove('hidden');
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
  currentView = view;
  hideError();
  if (view === 'config') loadConfigForm();
  if (view === 'history') renderHistory();
  if (view === 'home') { xmlContent = ''; parsedData = null; }
}

function showError(msg) {
  document.getElementById('error-msg').textContent = msg;
  document.getElementById('error-bar').classList.remove('hidden');
}
function hideError() { document.getElementById('error-bar').classList.add('hidden'); }

// Config
async function loadConfigForm() {
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    document.getElementById('cfg-siret').value = d.siret || '';
    document.getElementById('cfg-nom').value = d.nom || '';
    document.getElementById('cfg-prenom').value = d.prenom || '';
    document.getElementById('cfg-mdp').value = '';
    document.getElementById('cfg-mdp').placeholder = d.motdepasse_set ? '••••••• (déjà configuré)' : '';
  } catch {}
}

async function saveConfig() {
  const data = {
    siret: document.getElementById('cfg-siret').value.trim(),
    nom: document.getElementById('cfg-nom').value.trim(),
    prenom: document.getElementById('cfg-prenom').value.trim(),
    motdepasse: document.getElementById('cfg-mdp').value,
  };
  await fetch('/api/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
  configOk = data.siret.length === 14 && data.nom && data.prenom;
  checkConfig();
  go('home');
}

function togglePwd() {
  const inp = document.getElementById('cfg-mdp');
  const tog = inp.parentElement.querySelector('.pwd-toggle');
  if (inp.type === 'password') { inp.type = 'text'; tog.textContent = 'masquer'; }
  else { inp.type = 'password'; tog.textContent = 'voir'; }
}

async function checkConfig() {
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    configOk = d.siret && d.siret.length === 14 && d.nom && d.prenom && (d.motdepasse_set || d.motdepasse);
    document.getElementById('config-warn').classList.toggle('hidden', configOk || currentView === 'config');
  } catch {}
}

// File handling
function fmtDate(d) {
  if (!d) return '';
  const p = d.split('-');
  return p.length === 3 ? p[2]+'.'+p[1]+'.'+p[0] : d;
}

function parseXML(xml) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, 'text/xml');
  const nsO = 'http://www.repxml.org/Organization';
  const nsP = 'http://www.repxml.org/Person_Identity';
  const ind = doc.querySelector('[nodeName="FR_DUE_Upload.Test.Indicator"]') || doc.getElementsByTagName('FR_DUE_Upload.Test.Indicator')[0];
  const mode = ind && ind.textContent === '120' ? 'PRODUCTION' : 'TEST';
  const siret = (doc.getElementsByTagNameNS(nsO, 'FR_Organization.SIRET.Identifier')[0] || {}).textContent || '';
  const raison = (doc.getElementsByTagNameNS(nsO, 'FR_Organization.Designation.Text')[0] || {}).textContent || '';
  const emps = [];
  doc.querySelectorAll('FR_EmployeeGroup').forEach(g => {
    emps.push({
      nom: (g.getElementsByTagNameNS(nsP, 'FR_PersonIdentity.Surname.Text')[0]||{}).textContent||'',
      prenom: (g.getElementsByTagNameNS(nsP, 'FR_PersonIdentity.ChristianName.Text')[0]||{}).textContent||'',
      dateNaiss: (g.getElementsByTagNameNS(nsP, 'FR_Birth.Date')[0]||{}).textContent||'',
      dateEmb: (g.querySelector('[nodeName="FR_Contract.StartContract.Date"]')||g.getElementsByTagName('FR_Contract.StartContract.Date')[0]||{}).textContent||'',
      dateFin: (g.querySelector('[nodeName="FR_Contract.EndContract.Date"]')||g.getElementsByTagName('FR_Contract.EndContract.Date')[0]||{}).textContent||'',
      type: (g.querySelector('[nodeName="FR_Contract.Nature.Code"]')||g.getElementsByTagName('FR_Contract.Nature.Code')[0]||{}).textContent||'',
    });
  });
  return { mode, siret, raison, employees: emps };
}

function handleFile(file) {
  if (!file) return;
  xmlFilename = file.name;
  const reader = new FileReader();
  reader.onload = e => {
    xmlContent = e.target.result;
    try {
      parsedData = parseXML(xmlContent);
      showReview();
    } catch (err) { showError('Fichier XML invalide'); }
  };
  reader.readAsText(file, 'ISO-8859-1');
}

function showReview() {
  const d = parsedData;
  document.getElementById('rev-count').textContent = d.employees.length + ' DPAE';
  const modeEl = document.getElementById('rev-mode');
  modeEl.textContent = d.mode;
  modeEl.className = 'pill pill-' + (d.mode === 'PRODUCTION' ? 'blue' : 'amber');
  document.getElementById('rev-info').textContent = d.raison + ' · ' + d.siret + ' · ' + xmlFilename;
  const tbody = document.getElementById('rev-tbody');
  tbody.innerHTML = d.employees.map(e =>
    '<tr><td><span style="font-weight:600">'+e.nom+'</span> <span style="color:#6b6960">'+e.prenom+'</span></td>' +
    '<td class="mono" style="font-size:12px;color:#8a8880">'+fmtDate(e.dateNaiss)+'</td>' +
    '<td class="mono" style="font-size:12px">'+fmtDate(e.dateEmb)+'</td>' +
    '<td class="mono" style="font-size:12px;color:#8a8880">'+fmtDate(e.dateFin)+'</td>' +
    '<td><span class="pill pill-neutral">'+e.type+'</span></td></tr>'
  ).join('');
  go('review');
}

// Send
async function sendDPAE(test) {
  document.getElementById('rev-actions').classList.add('hidden');
  const sendingEl = document.getElementById('rev-sending');
  sendingEl.classList.remove('hidden');
  sendingEl.style.display = 'flex';
  document.getElementById('rev-progress').textContent = 'Authentification...';
  hideError();

  const form = new FormData();
  form.append('xml', xmlContent);
  form.append('test', test ? 'true' : 'false');
  form.append('filename', xmlFilename);

  try {
    document.getElementById('rev-progress').textContent = 'Envoi des ' + parsedData.employees.length + ' DPAE...';
    const r = await fetch('/api/send', { method: 'POST', body: form });
    const d = await r.json();

    if (d.error) { showError(d.error); }
    else {
      history.unshift({ ts: Date.now(), file: xmlFilename, n: parsedData.employees.length, flux: d.idflux, etat: d.etat, test, mode: d.mode });
      localStorage.setItem('dpae_hist', JSON.stringify(history.slice(0, 30)));
      showResult(d);
      return;
    }
  } catch (err) { showError('Erreur réseau: ' + err.message); }

  sendingEl.classList.add('hidden');
  document.getElementById('rev-actions').classList.remove('hidden');
}

function showResult(d) {
  const iconEl = document.getElementById('done-icon');
  iconEl.style.background = d.ok ? '#dcfce7' : '#fee2e2';
  iconEl.innerHTML = d.ok
    ? '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#166534" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>'
    : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#991b1b" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  document.getElementById('done-title').textContent = d.ok ? 'Envoi réussi' : 'Échec';
  const modePill = d.mode === 'TEST' ? '<span class="pill pill-amber">TEST</span>' : '<span class="pill pill-blue">PROD</span>';
  document.getElementById('done-sub').innerHTML = d.date + ' à ' + d.heure + ' · ' + (parsedData?.employees?.length||0) + ' DPAE · ' + modePill;
  const etatPill = d.etat === 'OK' ? '<span class="pill pill-green">OK</span>' : '<span class="pill pill-red">'+d.etat+'</span>';
  document.getElementById('done-stats').innerHTML =
    '<div class="stat-card"><div class="stat-label">État</div>'+etatPill+'</div>' +
    '<div class="stat-card"><div class="stat-label">ID Flux</div><div class="mono" style="font-size:14px;font-weight:600">'+d.idflux+'</div></div>';
  document.getElementById('done-raw').textContent = d.raw;
  go('done');
}

// History
function renderHistory() {
  const list = document.getElementById('hist-list');
  const empty = document.getElementById('hist-empty');
  document.getElementById('hist-clear').style.display = history.length ? '' : 'none';
  if (!history.length) { empty.style.display = ''; list.style.display = 'none'; list.innerHTML = ''; return; }
  empty.style.display = 'none'; list.style.display = '';
  list.innerHTML = history.map(h =>
    '<div class="history-item">' +
    '<div class="history-dot" style="background:'+(h.etat==='OK'?'#22c55e':'#ef4444')+'"></div>' +
    '<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:500">'+h.n+' DPAE <span style="color:#a8a49c;font-weight:400">· '+h.file+'</span></div>' +
    '<div class="mono" style="font-size:12px;color:#a8a49c;margin-top:2px">'+(h.flux||'').slice(0,20)+'</div></div>' +
    '<div style="text-align:right;flex-shrink:0"><div style="font-size:12px;color:#8a8880">'+new Date(h.ts).toLocaleDateString('fr-FR')+'</div>' +
    '<div style="margin-top:3px"><span class="pill pill-'+(h.test?'amber':'blue')+'">'+(h.test?'TEST':'PROD')+'</span></div></div></div>'
  ).join('');
}
function clearHistory() { history = []; localStorage.removeItem('dpae_hist'); renderHistory(); }

// Drag & drop
const dz = document.getElementById('dropzone');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
dz.addEventListener('dragleave', () => dz.classList.remove('over'));
dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); handleFile(e.dataTransfer.files[0]); });
document.getElementById('file-input').addEventListener('change', e => handleFile(e.target.files[0]));

// Init
checkConfig();
</script>
</body>
</html>
"""

def open_browser():
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    print()
    print("  DPAE Webapp")
    print("  http://localhost:5000")
    print("  Ctrl+C pour arrêter")
    print()
    Timer(1.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)