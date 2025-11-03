import os
import requests
import re
import json
import time
from flask import Flask, render_template_string, jsonify

# === ENVIRONMENT VARIABLES ===
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_LIST_ID = 4  # your fixed Brevo list ID
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Google Places API key
PORT = int(os.getenv("PORT", 10000))

if not BREVO_API_KEY:
    raise ValueError("Missing BREVO_API_KEY environment variable. Please set it.")
if not GOOGLE_API_KEY:
    raise ValueError("Missing GOOGLE_API_KEY environment variable. Please set it.")

# === SEARCH SETTINGS ===
# We'll query Google Places API for new real estate related businesses
SEARCH_QUERIES = [
    "real estate agency in Richmond VA",
    "realtor office Richmond Virginia",
    "real estate broker Henrico VA",
    "property management company Richmond VA",
    "real estate firm Chesterfield VA",
    "realty company Goochland VA"
]

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# === APP SETUP ===
app = Flask(__name__)
uploaded_emails = set()
uploaded_count = 0
log_lines = []
current_status = "Idle"

def log(msg):
    global log_lines
    print(msg)
    log_lines.append(msg)
    if len(log_lines) > 200:
        log_lines.pop(0)

def set_status(s):
    global current_status
    current_status = s
    log(f"📍 {s}")

# === GOOGLE PLACES API FUNCTIONS ===
def query_google_places(text_query):
    """Use Google Places Text Search API to get business results."""
    set_status(f"Querying: {text_query}")
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": text_query,
        "key": GOOGLE_API_KEY,
        "region": "us"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        results = data.get("results", [])
        links = []
        for r in results:
            if "website" in r:
                links.append(r["website"])
            elif "place_id" in r:
                # fallback: construct link to place_id
                links.append(f"https://www.google.com/maps/place/?q=place_id:{r['place_id']}")
        return links[:20]
    except Exception as e:
        log(f"⚠️ Google Places query failed: {e}")
        return []

def scrape_page(url):
    """Scrape business page for contact info."""
    try:
        set_status(f"Scanning: {url}")
        resp = requests.get(url, timeout=10)
        text = resp.text
        emails = list(set(EMAIL_PATTERN.findall(text)))
        phones = list(set(PHONE_PATTERN.findall(text)))
        # simple business name retrieval
        name = url.split("//")[-1].split("/")[0]
        return {
            "name": name,
            "email": emails,
            "phone": phones,
            "website": url
        }
    except Exception as e:
        log(f"⚠️ Scrape fail {url}: {e}")
        return None

def add_to_brevo(contact):
    """Upload contact to Brevo if valid and unique."""
    global uploaded_count
    if not contact["email"]:
        return
    email = contact["email"][0]
    if email in uploaded_emails:
        return
    uploaded_emails.add(email)
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_API_KEY
    }
    data = {
        "email": email,
        "attributes": {
            "FIRSTNAME": contact.get("name", ""),
            "COMPANY": contact.get("name", ""),
            "PHONE": contact["phone"][0] if contact["phone"] else "",
            "WEBSITE": contact["website"]
        },
        "listIds": [BREVO_LIST_ID]
    }
    try:
        r = requests.post("https://api.brevo.com/v3/contacts", headers=headers, data=json.dumps(data))
        if r.status_code in [200, 201]:
            uploaded_count += 1
            log(f"✅ Uploaded: {email} ({uploaded_count} total)")
        else:
            log(f"⚠️ Brevo response: {r.status_code} - {r.text}")
    except Exception as e:
        log(f"❌ Brevo upload failed: {e}")

def run_scraper():
    """Main scraper loop."""
    global uploaded_count
    uploaded_count = 0
    log("🚀 Scraper started.")
    for query in SEARCH_QUERIES:
        websites = query_google_places(query)
        for site in websites:
            info = scrape_page(site)
            if info and info["email"]:
                add_to_brevo(info)
            time.sleep(1)
    set_status("✅ Completed all queries.")
    log("🎯 Run finished.")

# === WEB UI ===
HTML = """
<!DOCTYPE html>
<html>
<head><title>Richmond Realtor Lead Finder</title>
<style>
body{background:#0d0d0d;color:#f44336;font-family:Arial;text-align:center;margin:0;padding:20px}
button{background:#f44336;color:white;border:none;padding:14px 28px;font-size:18px;border-radius:8px;cursor:pointer;margin:20px}
button:hover{background:#ff6659}
.status{font-size:18px;margin-top:10px}
.counter{font-size:20px;margin:10px}
.log{width:85%;height:400px;margin:20px auto;background:#111;color:#ff5555;padding:15px;border-radius:8px;overflow-y:scroll;text-align:left;font-size:14px}
</style>
<script>
async function startScraper(){
  document.getElementById('status').innerText='🚀 Starting...';
  await fetch('/run');
  updateLog();
}
async function updateLog(){
  const r = await fetch('/logs');
  const d = await r.json();
  document.getElementById('log').innerText = d.logs.join('\\n');
  document.getElementById('counter').innerText='Uploaded Leads: '+d.count;
  document.getElementById('status').innerText=d.status;
  document.getElementById('log').scrollTop=document.getElementById('log').scrollHeight;
  setTimeout(updateLog,3000);
}
</script>
</head>
<body onload="updateLog()">
<h1>Richmond Realtor Lead Finder</h1>
<button onclick="startScraper()">Start Scraper</button>
<div class="status">{{status}}</div>
<div class="counter">Uploaded Leads: {{count}}</div>
<div class="log" id="log"></div>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML, status=current_status, count=uploaded_count)

@app.route("/run")
def run_now():
    log("🟢 Manual start triggered.")
    run_scraper()
    return jsonify({"status":"running"})

@app.route("/logs")
def get_logs():
    return jsonify({"logs":log_lines,"status":current_status,"count":uploaded_count})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
