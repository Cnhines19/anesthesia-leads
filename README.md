# 🏥 Anesthesia Staffing Lead Finder

> An agentic GenAI tool that turns hours of manual lead research into a 6–11 minute, ranked, evidence-backed lead list for an anesthesia staffing company.

Built as a final project for an MBA Generative AI course.

---

## 1. Context, User, and Problem

**The user:** Casey, a nurse anesthesiologist and partner at a small anesthesia staffing company that wants to grow — first locally, then beyond. Clinicians at small staffing shops wear every hat: clinical work, scheduling, billing, *and* business development. Lead research falls to whoever can carve out the time, which usually means it doesn't happen at all.

**The workflow being improved:** Finding accredited ambulatory surgery centers (ASCs) within a given geography so the staffing company can pitch its anesthesia services. Today this is a manual workflow that involves:

1. Visiting each of three accreditation bodies' websites (AAAHC, The Joint Commission, QUAD A) and trying to search their directories — none of which have a unified public API and at least one of which is regularly down or blocks automation.
2. Cross-referencing with Google, Yelp, Healthgrades, and US News listings.
3. Manually pulling contact information one website at a time.
4. Eyeballing whether facilities are within driving distance.
5. Trying to remember which facilities already have a dedicated anesthesia group (a major signal that they are unlikely to switch providers).

**Why it matters:** Clinician time is the most expensive input at a small staffing company. 4 hours a week of manual lead research is 2 fewer OR days per month. **This is a high-volume, repetitive, multi-source workflow** — the exact shape of task where an agentic AI tool can deliver real value.

---

## 2. Solution and Design

### What was built

A Python tool with a Streamlit web UI. The user enters a zip code and selects a radius (5/10/15 miles); the tool runs a five-stage agentic pipeline and outputs a ranked, evidence-backed CSV of surgery center leads.

### Pipeline overview
Stage 1   Discover surgery centers near the zip code (Claude + web search)
Stage 1.5 Drill down on each address for co-located facilities (medical office buildings often host multiple distinct ASCs)
Stage 3   Geocode every facility and filter to the actual radius
Stage 2   For each in-radius facility:
- Fetch the facility's website directly
- Triple-search across AAAHC, Joint Commission, and QUAD A
- Detect anesthesia partnership signals (with verbatim quotes)
Stage 4   Compute a 0–100 warmth score and rank

### Key design choices

**Discover-then-verify, not directory-then-filter.** I initially tried to scrape AAAHC's accredited-facilities portal directly. Their site was timing out / blocked. Pivoting to a discover-then-verify pattern (find all surgery centers in the area first, then check each one's accreditation) turned out to be more robust *and* more useful: it surfaces leads that aren't in any single accreditor's directory.

**Claude + web search as the agent.** The professor's brief explicitly warned against unnecessary complexity. I considered building this with Playwright browser automation, but each accreditation body's site has different forms, anti-bot measures, and brittleness. Using Claude with web search as the reasoning layer is simpler, more adaptive, and aligns with the agentic AI theme of the course.

**Direct website fetch in verification.** Search snippets often miss accreditation badges that appear in body text on a facility's own site. The agent fetches the homepage and common sub-pages (`/about`, `/accreditation`, `/quality`, `/anesthesia`) and passes the full text into the verification prompt. This was the single biggest accuracy lift — confirmation rate went from 35% (v3) to 47% (v4) on the same test set.

**Quotes, not just booleans, for anesthesia signals.** The user (Casey) pointed out that some facilities say "we work with anesthesia partners" loosely while others have a named, deeply-integrated anesthesia group. A binary flag would force the agent into judgment calls a clinician should make. The tool captures the exact website quote so the clinician can decide whether the facility is truly off-limits.

**Warmth score built from clinical priorities.** The 0–100 score weights factors in the order Casey actually ranks leads: accreditation > contact completeness > service type > distance > specific accreditor. Plastic, GI, ortho, vascular, ophthalmology, spine, and urology are ranked per Casey's specialty preferences for anesthesia volume.

### Tools and libraries

- **Anthropic API** (Claude Sonnet 4.5 with the `web_search` tool) — discovery, drill-down, accreditation verification
- **Playwright** — *initially*, abandoned in favor of Claude+search (documented as a key design pivot)
- **`requests` + `BeautifulSoup`** — direct website fetching for accreditation evidence
- **`geopy` + Nominatim** — free geocoding and radius distance calculation
- **`pandas`** — CSV export
- **Streamlit** — web UI with sortable results table, summary cards, CSV download, prior-run loading

---

## 3. Evaluation and Results

### Test cases

The tool was evaluated on three deliberately different markets:

| Zip   | Market profile                        | Why chosen                                    |
|-------|---------------------------------------|-----------------------------------------------|
| 94507 | Alamo, CA — affluent East Bay suburb  | Casey's home market, easy to ground-truth     |
| 75205 | Highland Park, Dallas — dense urban   | Out-of-state, hospital-system-dominated       |
| 92647 | Huntington Beach, CA — cosmetic hub   | Plastic-surgery-heavy, QUAD A territory       |

### Baseline comparison

The baseline is the current manual workflow: a clinician sitting down with Google and the three accreditor websites. In practice this work often doesn't happen at all — clinicians defer it or do it incompletely. A motivated, thorough manual baseline (visiting all three accreditor portals, cross-referencing Google/Yelp/Healthgrades, pulling contact info per facility, estimating distances by hand) realistically takes **multiple hours per market**, not minutes. The figures below come from a simulated 25-minute run on zip 94507 — already a generous estimate that understates the real-world time cost.

| Metric                                | Manual baseline | Tool (94507, 10 mi) |
|---------------------------------------|-----------------|---------------------|
| Research time (simulated)             | ~25 min         | ~6 min              |
| Research time (realistic, thorough)   | 2–3+ hours      | ~6 min              |
| Facilities found                      | 9               | 17                  |
| Facilities with confirmed accreditation | 6 (weak evidence) | 7                 |
| Facilities with phone numbers         | 0               | 14+                 |
| Facilities with addresses             | ~3 (city only)  | 17                  |
| Distance verified                     | No              | Yes (geocoded)      |
| Co-located facilities at 1320 El Capitan Drive | 0 of 4 | 4 of 4              |
| Anesthesia partnership detection      | Impossible      | 2 flagged           |
| Sortable, exportable CSV              | No              | Yes                 |

**Time savings are at minimum 75%; in realistic conditions where a clinician would spend multiple hours per market, savings approach 95%+. Coverage roughly doubles. Data completeness goes from city-only listings to fully geocoded, contact-rich leads.**

### Three-zip summary

| Zip   | Runtime  | Leads | Confirmed accreditation | % Confirmed |
|-------|----------|-------|-------------------------|-------------|
| 94507 | 6.0 min  | 17    | 7                       | 41%         |
| 75205 | 5.7 min  | 12    | 10                      | 83%         |
| 92647 | 11.3 min | 22    | 12                      | 55%         |

**A finding in itself:** confirmation rates vary by market. Dense urban markets like Highland Park have facilities with stronger web presences and clearer public accreditation claims. Affluent suburban California (94507) has more small plastic-surgery practices that don't advertise accreditation publicly. The tool is more powerful in some markets than others — a real limitation worth knowing.

### What worked

- **The four-stage agent pipeline.** Each stage measurably improves the output: drill-down recovered all four co-located facilities at one Danville address (0/4 → 4/4 vs. baseline). Triple-verification raised confirmation rate. Radius filtering removed Castro Valley/Fremont/Pleasanton facilities the user didn't want.
- **Direct website fetch (v4 upgrade).** Cleanest single accuracy gain.
- **Anesthesia signals with quotes.** During testing, the tool correctly flagged Iron Horse, Diablo Plaza, San Ramon Regional and others as having named anesthesia partners — and captured the actual quote so Casey can decide whether the relationship is locked in or worth pitching anyway.

### What failed (and where humans must stay involved)

- **Hallucinated facility names.** The tool returned "Iron Horse Surgery Center at 1320 El Capitan Drive, Danville." A local clinician (Casey) recognized this as suspect; the verification stage later noted the address actually belongs to Executive Surgery Center. **The agent partially detected its own hallucination, but did not drop the entry.** A clinician reviewing the output catches this in seconds. *Mitigation:* an NPI/NPPES registry cross-check would deterministically filter spurious entries. Documented as future work.
- **Geocoder occasionally mismatches facility names to wrong locations.** "BASS Surgery Center" got initially geocoded to a result ~1700 miles from the origin zip. The radius filter correctly dropped the spurious match, but lost a real local lead. More specific geocoding queries (address + state) reduce but don't eliminate this.
- **Confirmation rate is market-dependent.** ~40–80% range across the three test zips. Where facilities don't publish their accreditation, no automation can find what isn't online.
- **AAAHC's own directory is unreliable.** During both automated and manual baseline attempts, the AAAHC accredited-organization search portal was unreachable. The tool depends on indirect evidence (facility sites, press releases, regional aggregator pages) when the primary source is down.
- **Non-deterministic output.** Two runs on the same zip return overlapping but not identical sets of facilities, because LLM discovery is non-deterministic. The agent should be used as a starting point for clinician outreach, not as a complete enumeration.

### Where the human stays in the loop

1. **Final accreditation verification by phone** for "Unknown" rows — 30 seconds per lead.
2. **Sanity check on facility names** the clinician doesn't recognize.
3. **Interpretation of anesthesia partnership quotes** — the tool surfaces them; the clinician decides whether the relationship is exclusive.
4. **Choosing which leads to actually pursue** based on local knowledge of the market.

---

## 4. Artifact Snapshot

Screenshots and a sample CSV are included in this repository under `/screenshots` and `/results`.

- **Web UI (`/screenshots/ui_94507.png`):** the Streamlit app showing 17 ranked leads from zip 94507 with summary metrics across the top.
- **Sample CSV (`results/leads_94507_10mi_*.csv`):** a complete lead list with warmth score, accreditation across all three bodies, anesthesia signals, distance, and evidence.
- **Sample evidence row:** *"Walnut Creek Endoscopy and Surgery Center — Warmth 85, AAAHC confirmed. Evidence: 'Facility website explicitly states accreditation by AAAHC and also won AAAHC Kershner QI Award in 2025.'"*

---

## Setup and Usage

### Prerequisites

- macOS, Linux, or Windows
- Python 3.9+
- An Anthropic API key with credits (~$1–3 per zip-code run)

### Install

```bash
# Clone or download this repository
cd anesthesia-leads

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate    # on Windows: venv\Scripts\activate

# Install dependencies
pip install playwright anthropic python-dotenv geopy pandas streamlit requests beautifulsoup4
```

### Configure your API key

Create a file called `.env` in the project root (same folder as `lead_finder.py`) with one line:
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

The `.env` file is git-ignored and never committed.

### Run the command-line tool

```bash
python lead_finder.py 94507 10    # zip code, radius in miles
```

Output: a sorted CSV in `results/leads_<zip>_<radius>mi_<timestamp>.csv`.

### Run the web UI

```bash
streamlit run app.py
```

Opens automatically at `http://localhost:8501`. Enter a zip, choose a radius, click **Find Leads**. Past runs are available from the "Load a previous run" dropdown.

### Notes for the grader

- Use any U.S. zip code. The three demo zips used in the writeup are 94507 (Alamo CA), 75205 (Highland Park TX), and 92647 (Huntington Beach CA).
- Each run takes 6–12 minutes and uses ~$1–3 of Anthropic API credit.
- If you don't want to spend credits, load any saved CSV from `/results` via the **Previous results** dropdown in the sidebar — full UI is functional without a fresh run.

---

## Future Work

- **NPI/NPPES verification step.** A federal registry cross-check would deterministically filter hallucinated facility names. Highest-value next improvement.
- **Multi-zip batch mode.** Casey often needs to research several adjacent markets at once.
- **Lead refresh tracking.** Track which leads have been contacted and which need a follow-up.
- **Specialty filter at the UI level.** Quickly narrow to only plastic surgery centers, only GI, etc.

---

## Acknowledgments

Built with Claude (Anthropic) as both the agentic reasoning layer inside the tool and a pair-programming collaborator during development. All clinical judgment, scoring weights, and failure-mode interpretations come from the user's anesthesia practice.
