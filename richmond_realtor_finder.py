import os
import requests
import re
import json
import time
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, jsonify

# === ENVIRONMENT ===
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_LIST_ID = 4  # Your secure Brevo List ID
PORT = int(os.getenv("PORT", 10000))

if not BREVO_API_KEY:
    raise ValueError("Missing BREVO_API_KEY environment variable. Please set it in Render.")

# === SEARCH TERMS (Target Local Broker & Realtor Pages) ===
SEARCH_TERMS = [
    "real estate agency Richmond VA contact",
    "real estate office Henrico VA contact",
    "realtors near Richmond VA site:kw.com OR site:longandfoster.com OR site:remax.com",
    "real estate broker Chesterfield VA contact",
    "real estate team Ashland VA contact",
    "realty company Goochland VA contact",
]

HEADERS = {"User-Agent": "Mozilla/5.0"}
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# === APP STATE ===
app = Flask(__name__)
uploaded_emails, log_lines = set(), []
uploaded_count, current_status = 0, "Idle"

def log(msg):
    """Print and store a log line."""
    global log_lines
    print(msg)
    log_lines.append(msg)
    if len(log_lines) > 250:
        log_lines.pop(0)

def set_status(s):
    global current_status
    current_status = s
    log(f"📍 {s}")

# === SEARCH & SCRAPE ===
def duckduckgo_search(term):
    set_status(f"Searching: {term}")
    try:
        q = term.replace(" ", "+")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if "http" in h and "duckduckgo" not in h:
                links.append(h)
        return list(set(links))[:25]
    except Exception as e:
        log(f"⚠️ Search failed: {e}")
        return []

def scrape_page(url):
    """Scrape the given page for emails, phones, and names."""
    try:
        set_status(f"Scanning: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        emails = list(set(re.findall(EMAIL_PATTERN, text)))
        phones = list(set(re.findall(PHONE_PATTERN, text)))

        name = ""
        for tag in soup.find_all(["h1", "h2", "strong", "p"]):
            if any(k in tag.text.lower() for k in ["realtor", "agent", "team", "broker", "staff", "about"]):
                name = tag.text.strip()[:60]
                break

        company = soup.title.string.strip() if soup.title else "Unknown Realtor"
        return {"name": name, "email": emails, "phone": phones, "company": company, "url": url}
    except Exception as e:
        log(f"⚠️ Error scraping {url}: {e}")
        return None

def add_to_brevo(c):
    """Upload a valid contact to Brevo."""
    global uploaded_count
    if not c["email"]:
        return
    e = c["email"][0]
    if e in uploaded_emails:
        return

    uploaded_emails.add(e)
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_API_KEY}
    data = {
        "email": e,
        "attributes": {
            "FIRSTNAME": c.get("name", ""),
            "COMPANY": c.get("company", ""),
            "PHONE": c["phone"][0] if c["phone"] else "",
            "WEBSITE": c["url"],
        },
        "listIds": [BREVO_LIST_ID],
    }

    try:
        r = requests.post("https://api.brevo.com/v3/contacts", headers=headers, data=json.dumps(data))
        if r.status_code in [200, 201]:
            uploaded_count += 1
            log(f"✅ Uploaded: {e} ({uploaded_count} total)")
        else:
            log(f"⚠️ Brevo {r.status_code}: {r.text}")
    except Exception as e:
        log(f"❌ Upload failed: {e}")

def run_scraper():
    """Run the full scraping loop."""
    global uploaded_count
    uploaded_count = 0
    log("🚀 Scraper started.")
    for term in SEARCH_TERMS:
        links = duckduckgo_search(term)
        for link in links:
            info = scrape_page(link)
            if info and info["email"]:
                add_to_brevo(info)
            time.sleep(1)
    set_status("✅ Completed all search terms.")
    log("🎯 Run finished.")

# === HTML FRONTEND ===
HTML = """
<!DOCTYPE html><html><head><title>Richmond Realtor Finder</title>
<style>
body{background:#0d0d0d;color:#f44336;font-family:Arial;text-align:center;margin:0}
h1{color:#ff5555}
button{background:#f44336;color:white;border:none;padding:14px 28px;font-size:18px;border-radius:8px;cursor:pointer;margin:20px}
button:hover{background:#ff6659}
#status{font-size:18px;margin-top:10px}
#counter{font-size:20px;margin:10px}
#log{width:85%;height:400px;margin:20px auto;background:#111;color:#ff5555;padding:15px;border-radius:8px;overflow-y:scroll;text-align:left;font-size:14px}
</style>
<script>
async function startScraper(){
  document.getElementById('status').innerText='🚀 Starting scraper...';
  await fetch('/run');
  update();
}
async function update(){
  const r=await fetch('/logs');
  const d=await r.json();
  document.getElementById('log').innerText=d.logs.join('\\n');
  document.getElementById('counter').innerText='Uploaded Leads: '+d.count;
  document.getElementById('status').innerText=d.status;
  document.getElementById('log').scrollTop=document.getElementById('log').scrollHeight;
  setTimeout(update,3000);
}
</script></head>
<body onload="update()">
<h1>Richmond Realtor Finder</h1>
<button onclick="startScraper()">Start Scraper</button>
<div id="status">{{status}}</div>
<div id="counter">Uploaded Leads: {{count}}</div>
<div id="log"></div>
</body></html>
"""

@app.route("/")
def home():
    return render_template_string(HTML,status=current_status,count=uploaded_count)

@app.route("/run")
def run_now():
    log("🟢 Manual start triggered.")
    run_scraper()
    return jsonify({"status":"running"})

@app.route("/logs")
def logs():
    return jsonify({"logs":log_lines,"status":current_status,"count":uploaded_count})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=PORT)
