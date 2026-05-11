"""
Anesthesia Staffing Lead Finder v5.1
Five-stage agent:
  Stage 1: Discover ambulatory surgery centers near a zip code.
  Stage 1.5: Drill down on addresses to find co-located facilities.
  Stage 3: Geocode and filter to radius.
  Stage 2: Triple-verify accreditation + detect anesthesia signals (with quotes & alias hints).
  Stage 4: Compute warmth score and rank leads.
Saves results to CSV.

Usage:
  python lead_finder.py                 # defaults to 94507 / 10 mi
  python lead_finder.py <zip> <radius>  # e.g. python lead_finder.py 75205 10
"""

import os
import sys
import time
import json
import re
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from anthropic import Anthropic
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import pandas as pd
import requests
from bs4 import BeautifulSoup

load_dotenv()
client = Anthropic()

MODEL = "claude-sonnet-4-5"

geocoder = Nominatim(user_agent="anesthesia-leads-mba-project")


# ---------- UTILITIES ----------

def call_claude_with_search(prompt: str, max_uses: int = 5) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_uses
        }],
        messages=[{"role": "user", "content": prompt}]
    )
    text_blocks = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_blocks).strip()


def extract_json_array(text: str) -> list:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return []


def extract_json_object(text: str) -> dict:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def fetch_website_text(url: str, max_chars: int = 8000) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url

    paths = ["", "/about", "/about-us", "/accreditation", "/quality", "/our-facility",
             "/team", "/physicians", "/staff", "/anesthesia"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    collected = []
    base = url.rstrip("/")

    for path in paths:
        full_url = base + path
        try:
            r = requests.get(full_url, headers=headers, timeout=8, allow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            collected.append(f"--- {full_url} ---\n{text[:3000]}")
        except Exception:
            continue
        if sum(len(c) for c in collected) > max_chars:
            break

    return "\n\n".join(collected)[:max_chars]


def geocode_address(query: str):
    time.sleep(1.1)
    try:
        location = geocoder.geocode(query, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"    Geocoding error for '{query}': {e}")
    return None


# ---------- STAGE 1: DISCOVERY ----------

def discover_surgery_centers(zip_code: str, radius_miles: int) -> list:
    prompt = f"""You are a research assistant for an anesthesia staffing company.

TASK: Find ambulatory surgery centers (ASCs) and office-based surgery centers within approximately {radius_miles} miles of zip code {zip_code} in the United States.

Use web search aggressively. Search for:
- "ambulatory surgery centers near [city]"
- "office-based surgery [city]"
- "plastic surgery center [city]"
- "endoscopy center [city]"
- Healthgrades, Yelp, Google, US News, Leapfrog listings of surgery centers

Include all types: plastic surgery, GI/endoscopy, orthopedic, pain management, ophthalmology, oral surgery, podiatric, cardiovascular, etc.

IMPORTANT — Multi-tenant medical buildings:
Many medical office buildings host MULTIPLE distinct surgery centers operated by different organizations. If you see signals of this (e.g., multiple NPIs at the same address, different suite numbers, different phone numbers), list each surgery center as a SEPARATE entry. Do not deduplicate facilities that share an address but operate independently.

Do NOT filter by accreditation at this stage. Find as many candidate facilities as you can.

OUTPUT INSTRUCTIONS:
- Return ONLY a valid JSON array. No prose. No markdown fences.
- Use null for unknown values.
- Aim for 10-20 facilities.

Each object must have:
  - name (string)
  - address (string or null)
  - suite (string or null - e.g., "Suite 100", "#440")
  - city (string)
  - state (string, 2-letter code)
  - zip (string or null)
  - phone (string or null)
  - website (string or null)
  - services (string or null - e.g., "plastic surgery, dermatology")
  - notes (string or null)

Begin. Output ONLY the JSON array."""

    print(f"  [Stage 1] Discovering surgery centers near {zip_code}...")
    text = call_claude_with_search(prompt, max_uses=6)
    facilities = extract_json_array(text)
    print(f"  [Stage 1] Found {len(facilities)} initial candidates.")
    return facilities


# ---------- STAGE 1.5: ADDRESS DRILL-DOWN ----------

def find_colocated_facilities(address: str, known_names: list) -> list:
    known_str = ", ".join(known_names) if known_names else "(none yet)"
    prompt = f"""You are researching co-located surgery centers for an anesthesia staffing company.

ADDRESS: {address}
ALREADY KNOWN FACILITIES AT THIS ADDRESS: {known_str}

TASK: Find any OTHER ambulatory surgery centers, office-based surgery centers, or surgical suites operating at this same address that are NOT in the "already known" list above. Medical office buildings often host multiple distinct surgery centers with different suite numbers, NPIs, and operators.

Use web search. Try:
- "[address] surgery center"
- NPI registry sites (npino.com, ehealthscores.com) for the address
- "[building name] surgery centers" if you can identify the building
- Yelp, Google, healthgrades searches by address

OUTPUT INSTRUCTIONS:
- Return ONLY a valid JSON array of any ADDITIONAL surgery centers found at this address.
- Do not include facilities already listed in "already known".
- If none found, return [].
- No prose, no markdown.

Each object must have:
  - name (string)
  - address (string)
  - suite (string or null)
  - city (string)
  - state (string)
  - zip (string or null)
  - phone (string or null)
  - website (string or null)
  - services (string or null)
  - notes (string or null - mention how you found it)

Begin. Output ONLY the JSON array."""

    text = call_claude_with_search(prompt, max_uses=3)
    return extract_json_array(text)


def address_drill_down(facilities: list) -> list:
    print(f"\n  [Stage 1.5] Drilling down on addresses for co-located facilities...")

    by_address = defaultdict(list)
    for f in facilities:
        addr = f.get("address")
        if not addr:
            continue
        addr_clean = re.sub(r",?\s*(suite|ste|#|unit)\s*\S+", "", addr, flags=re.IGNORECASE).strip()
        by_address[addr_clean].append(f)

    new_facilities = []
    for addr, group in by_address.items():
        known_names = [f.get("name", "") for f in group]
        full_addr = f"{addr}, {group[0].get('city', '')}, {group[0].get('state', '')}"
        print(f"    Checking: {full_addr}")
        found = find_colocated_facilities(full_addr, known_names)
        if found:
            print(f"      Found {len(found)} additional co-located facilities.")
            new_facilities.extend(found)

    print(f"  [Stage 1.5] Discovered {len(new_facilities)} additional facilities.")
    return new_facilities


# ---------- STAGE 3: GEOCODE + RADIUS FILTER ----------

def filter_by_radius(facilities: list, origin_zip: str, radius_miles: int) -> list:
    print(f"\n  [Stage 3] Geocoding and filtering to {radius_miles}-mile radius...")

    origin = geocode_address(f"{origin_zip}, USA")
    if not origin:
        print(f"  [Stage 3] Could not geocode origin zip {origin_zip}. Skipping radius filter.")
        return facilities

    print(f"    Origin {origin_zip}: ({origin[0]:.4f}, {origin[1]:.4f})")

    filtered = []
    for f in facilities:
        parts = [f.get("address"), f.get("city"), f.get("state"), f.get("zip")]
        query = ", ".join(p for p in parts if p)
        if not query:
            f["distance_miles"] = None
            f["within_radius"] = False
            continue

        coords = geocode_address(query)
        if not coords:
            f["distance_miles"] = None
            f["within_radius"] = False
            continue

        distance = geodesic(origin, coords).miles
        f["distance_miles"] = round(distance, 2)
        f["within_radius"] = distance <= radius_miles

        name_short = (f.get("name") or "?")[:40]
        if f["within_radius"]:
            filtered.append(f)
            print(f"    [keep] {name_short:40s} {distance:.1f} mi")
        else:
            print(f"    [drop] {name_short:40s} {distance:.1f} mi  (out of radius)")

    print(f"  [Stage 3] {len(filtered)} of {len(facilities)} facilities within {radius_miles} miles.")
    return filtered


# ---------- STAGE 2: ACCREDITATION + ANESTHESIA SIGNAL DETECTION ----------

def verify_accreditation(facility: dict) -> dict:
    """Research accreditation AND detect anesthesia signals (with quote extraction)."""
    name = facility.get("name", "")
    city = facility.get("city", "")
    state = facility.get("state", "")
    website = facility.get("website") or ""
    address = facility.get("address") or "(unknown)"

    site_text = ""
    if website:
        site_text = fetch_website_text(website)

    site_block = ""
    if site_text:
        site_block = f"""
FACILITY WEBSITE CONTENT (already fetched for you — scan this first):
\"\"\"
{site_text}
\"\"\"
"""

    prompt = f"""You are verifying surgery center accreditation AND detecting anesthesia partnership signals for an anesthesia staffing company.

FACILITY:
- Name: {name}
- Address: {address}
- Location: {city}, {state}
- Website: {website or "(none)"}
{site_block}

TASKS:

A) ACCREDITATION — Determine if this facility is accredited by AAAHC, The Joint Commission (JCAHO/TJC), or QUAD A (formerly AAAASF). Consider all three separately.

   IMPORTANT — ACCREDITATION NAME ALIASES (very important to recognize):
   - AAAHC may appear as: "Accreditation Association for Ambulatory Health Care", "Association for Ambulatory Health Care", just "Accreditation Association", or AAAHC.
   - Joint Commission may appear as: "The Joint Commission", JCAHO, TJC, or "Joint Commission on Accreditation of Healthcare Organizations".
   - QUAD A may appear as: AAAASF, "American Association for Accreditation of Ambulatory Surgery Facilities", "Quad A", or QUAD-A.
   Treat any of these aliases as referring to the same body.

   Strategy:
   1. Check the facility website content above (if provided) for accreditation mentions and all aliases.
   2. Search for "[facility name] AAAHC" and check the AAAHC directory if findable.
   3. Search for "[facility name] Joint Commission" or "[facility name] JCAHO" and check qualitycheck.org if findable.
   4. Search for "[facility name] QUAD A" or "[facility name] AAAASF" and check quada.org if findable.
   5. Look for press releases.

B) ANESTHESIA SIGNALS — Determine if this facility has signals of dedicated anesthesia coverage. Specifically:
   - "Anesthesia Medical Director" or "Director of Anesthesia" named on website/directories → has_anesthesia_director: true
   - A specific anesthesia group named as their provider (e.g., "Empire Anesthesia provides our services", "our partners at XYZ Anesthesia") → has_named_anesthesia_group: true
   - Generic mentions ("anesthesia provided by board-certified anesthesiologists", "our anesthesia team") → do NOT flag (these are noncommittal).

   For ANY anesthesia mention you find (even weak/generic), extract:
   - anesthesia_quote: the exact phrase from the website that mentions anesthesia, max 250 chars. Include this even for weak/generic mentions so a human can review.
   - anesthesia_partner_name: the specific group or director name if explicitly stated; otherwise null.

   This lets a human reviewer make the final judgment about how committed the facility is to its current anesthesia arrangement.

OUTPUT INSTRUCTIONS:
- Return ONLY a valid JSON object. No prose, no markdown fences.
- Format:
{{
  "aaahc": "confirmed" | "likely" | "no" | "unknown",
  "joint_commission": "confirmed" | "likely" | "no" | "unknown",
  "quad_a": "confirmed" | "likely" | "no" | "unknown",
  "has_anesthesia_director": true | false | null,
  "has_named_anesthesia_group": true | false | null,
  "anesthesia_quote": "exact text from website mentioning anesthesia, or empty string if none found",
  "anesthesia_partner_name": "specific group or director name if named, or null",
  "evidence": "1-2 sentence summary of accreditation evidence"
}}

Use null for the anesthesia booleans if you cannot determine either way.

Begin. Output ONLY the JSON object."""

    text = call_claude_with_search(prompt, max_uses=8)
    return extract_json_object(text)


def summarize_accreditation(accred: dict):
    bodies = []
    highest_confidence = "unknown"
    confidence_rank = {"confirmed": 3, "likely": 2, "no": 1, "unknown": 0}

    for body_key, body_name in [("aaahc", "AAAHC"), ("joint_commission", "Joint Commission"), ("quad_a", "QUAD A")]:
        status = accred.get(body_key, "unknown")
        if status == "confirmed":
            bodies.append(f"{body_name} (confirmed)")
            if confidence_rank[status] > confidence_rank[highest_confidence]:
                highest_confidence = "confirmed"
        elif status == "likely":
            bodies.append(f"{body_name} (likely)")
            if confidence_rank[status] > confidence_rank[highest_confidence]:
                highest_confidence = "likely"

    if not bodies:
        return ("None / Unknown", "unknown")
    return (", ".join(bodies), highest_confidence)


# ---------- STAGE 4: WARMTH SCORE ----------

SERVICE_PRIORITY = [
    ("plastic", 20), ("cosmetic", 20),
    ("gi", 18), ("gastro", 18), ("endoscop", 18), ("colonoscop", 18),
    ("ortho", 16),
    ("vascular", 14), ("cardiovascular", 14),
    ("ophthal", 12), ("eye", 12), ("cataract", 12),
    ("spine", 10),
    ("urolog", 8),
]


def score_services(services_text: str) -> int:
    if not services_text:
        return 2
    s = services_text.lower()
    for keyword, points in SERVICE_PRIORITY:
        if keyword in s:
            return points
    return 5


def compute_warmth_score(facility: dict, radius_miles: int) -> tuple:
    reasoning = {}
    score = 0

    # 1. Accreditation (max 30)
    conf = facility.get("overall_confidence", "unknown")
    if conf == "confirmed":
        accred_pts = 30
    elif conf == "likely":
        accred_pts = 18
    else:
        accred_pts = 0
    score += accred_pts
    reasoning["accreditation_pts"] = accred_pts

    # 2. Contact info (max 25)
    has_phone = bool(facility.get("phone"))
    has_website = bool(facility.get("website"))
    if has_phone and has_website:
        contact_pts = 25
    elif has_phone or has_website:
        contact_pts = 12
    else:
        contact_pts = 0
    score += contact_pts
    reasoning["contact_pts"] = contact_pts

    # 3. Service type (max 20)
    service_pts = score_services(facility.get("services") or "")
    score += service_pts
    reasoning["service_pts"] = service_pts

    # 4. Distance (max 15)
    distance = facility.get("distance_miles")
    if distance is None:
        dist_pts = 0
    elif distance <= 5:
        dist_pts = 15
    elif distance <= 10:
        dist_pts = 10
    elif distance <= 15:
        dist_pts = 5
    else:
        dist_pts = 2
    score += dist_pts
    reasoning["distance_pts"] = dist_pts

    # 5. Accreditor type (max 10)
    accred_type_pts = 0
    if conf in ("confirmed", "likely"):
        if facility.get("accreditation_aaahc") in ("confirmed", "likely") or \
           facility.get("accreditation_joint_commission") in ("confirmed", "likely"):
            accred_type_pts = 10
        elif facility.get("accreditation_quad_a") in ("confirmed", "likely"):
            accred_type_pts = 6
    score += accred_type_pts
    reasoning["accreditor_type_pts"] = accred_type_pts

    # Penalties
    penalty = 0
    if facility.get("has_anesthesia_director") is True:
        penalty -= 40
    if facility.get("has_named_anesthesia_group") is True:
        penalty -= 40
    score += penalty
    reasoning["anesthesia_penalty"] = penalty

    score = max(0, min(100, score))
    reasoning["final"] = score
    return (score, reasoning)


# ---------- CSV EXPORT ----------

def save_to_csv(facilities: list, zip_code: str, radius: int) -> str:
    os.makedirs("results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results/leads_{zip_code}_{radius}mi_{timestamp}.csv"

    columns = [
        "warmth_score",
        "name", "address", "suite", "city", "state", "zip",
        "phone", "website", "services",
        "accreditation_summary", "overall_confidence",
        "accreditation_aaahc", "accreditation_joint_commission", "accreditation_quad_a",
        "has_anesthesia_director", "has_named_anesthesia_group",
        "anesthesia_partner_name", "anesthesia_quote",
        "distance_miles", "within_radius",
        "evidence", "notes",
    ]
    df = pd.DataFrame(facilities)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df = df[columns + [c for c in df.columns if c not in columns]]
    df = df.sort_values("warmth_score", ascending=False, na_position="last")
    df.to_csv(filename, index=False)
    print(f"\n  Saved to: {filename}")
    return filename


# ---------- MAIN PIPELINE ----------

def find_leads(zip_code: str, radius_miles: int) -> list:
    candidates = discover_surgery_centers(zip_code, radius_miles)
    additional = address_drill_down(candidates)
    candidates.extend(additional)

    seen = set()
    unique = []
    for f in candidates:
        key = (f.get("name", "").lower().strip(), (f.get("address") or "").lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    candidates = unique
    print(f"\n  Total unique candidates after drill-down: {len(candidates)}")

    candidates = filter_by_radius(candidates, zip_code, radius_miles)

    print(f"\n  [Stage 2] Verifying accreditation + detecting anesthesia signals...")
    enriched = []
    for i, facility in enumerate(candidates, 1):
        print(f"    ({i}/{len(candidates)}) {facility.get('name', '?')}")
        result = verify_accreditation(facility)
        summary, overall_conf = summarize_accreditation(result)
        facility["accreditation_aaahc"] = result.get("aaahc", "unknown")
        facility["accreditation_joint_commission"] = result.get("joint_commission", "unknown")
        facility["accreditation_quad_a"] = result.get("quad_a", "unknown")
        facility["accreditation_summary"] = summary
        facility["overall_confidence"] = overall_conf
        facility["has_anesthesia_director"] = result.get("has_anesthesia_director")
        facility["has_named_anesthesia_group"] = result.get("has_named_anesthesia_group")
        facility["anesthesia_quote"] = result.get("anesthesia_quote", "")
        facility["anesthesia_partner_name"] = result.get("anesthesia_partner_name")
        facility["evidence"] = result.get("evidence", "")
        enriched.append(facility)

    print(f"\n  [Stage 4] Computing warmth scores...")
    for f in enriched:
        score, _ = compute_warmth_score(f, radius_miles)
        f["warmth_score"] = score

    enriched.sort(key=lambda x: x.get("warmth_score", 0), reverse=True)
    return enriched


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        zip_code = sys.argv[1]
        try:
            radius = int(sys.argv[2])
        except ValueError:
            print(f"Error: radius must be a whole number (got '{sys.argv[2]}')")
            sys.exit(1)
    else:
        zip_code = "94507"
        radius = 10
        print("(No args provided — using defaults: zip=94507, radius=10)")
        print("Usage: python lead_finder.py <zip_code> <radius_miles>")
        print()

    print(f"Searching for surgery centers near {zip_code} (radius: {radius} mi)\n")
    leads = find_leads(zip_code, radius)

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(leads)} facilities within {radius} miles (sorted by warmth)")
    print(f"{'='*60}\n")

    for f in leads:
        addr_full = f.get("address") or ""
        if f.get("suite"):
            addr_full += f" {f['suite']}"
        flags = []
        if f.get("has_anesthesia_director"):
            flags.append("HAS ANES DIRECTOR")
        if f.get("has_named_anesthesia_group"):
            flags.append("HAS ANES GROUP")
        flag_str = f"  [{' | '.join(flags)}]" if flags else ""
        print(f"[Warmth {f.get('warmth_score', 0)}] {f.get('name', '?')} ({f.get('city', '?')}, {f.get('state', '?')}) — {f.get('distance_miles', '?')} mi{flag_str}")
        print(f"  Address: {addr_full or 'N/A'}")
        print(f"  Accreditation: {f.get('accreditation_summary', '?')}")
        print(f"  Phone: {f.get('phone') or 'N/A'}")
        print(f"  Website: {f.get('website') or 'N/A'}")
        print(f"  Services: {f.get('services') or 'N/A'}")
        if f.get("anesthesia_quote"):
            print(f"  Anesthesia quote: \"{f.get('anesthesia_quote', '')[:150]}\"")
        if f.get("anesthesia_partner_name"):
            print(f"  Anesthesia partner: {f.get('anesthesia_partner_name')}")
        print(f"  Evidence: {(f.get('evidence') or '')[:120]}")
        print()

    save_to_csv(leads, zip_code, radius)
    