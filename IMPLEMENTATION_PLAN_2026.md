# HANNA OSINT Adapter Expansion — Implementation Plan (2026-04-07)

## Baseline Inventory

### Already Integrated as HANNA Adapters (14)
| Adapter | Category | Status |
|---------|----------|--------|
| ua_leak | Person/Leaks | ✅ Working |
| ru_leak | Person/Leaks | ✅ Working |
| vk_graph | Social | ✅ Working |
| avito | Marketplace | ✅ Working |
| ua_phone | Phone/GetContact | ✅ Working (AES encrypted) |
| maryam | Web/OSINT framework | ✅ Working (CLI wrapper) |
| ashok | Infrastructure | ✅ Working (CLI wrapper) |
| ghunt | Google OSINT | ✅ Working (CLI wrapper) |
| social_analyzer | Username 1000+ | ✅ Working (CLI wrapper) |
| satintel | GEOINT/EXIF | ✅ Working |
| search4faces | Face recognition | ✅ Working (API) |
| web_search | DDG + Playwright | ✅ Working |
| opendatabot | UA business registry | ✅ Working (API + web fallback) |
| firms | NASA satellite | ✅ Working (API) |

### Installed on System but NOT Integrated as Adapters
| Tool | Category | Path |
|------|----------|------|
| sherlock | Username OSINT | /opt/homebrew/bin/sherlock |
| maigret | Username OSINT | /opt/homebrew/bin/maigret |
| holehe | Email discovery | /opt/homebrew/bin/holehe |
| phoneinfoga | Phone OSINT | /opt/homebrew/bin/phoneinfoga |
| theHarvester | Email/Domain | ~/.local/bin/theHarvester |
| amass | Subdomain enum | /opt/homebrew/bin/amass |
| subfinder | Subdomain enum | /opt/homebrew/bin/subfinder |
| dnsx | DNS resolution | ~/go/bin/dnsx |
| assetfinder | Asset discovery | ~/go/bin/assetfinder |
| nmap | Port scan | /opt/homebrew/bin/nmap |
| masscan | Port scan | /opt/homebrew/bin/masscan |
| shodan | Internet search | /opt/homebrew/bin/shodan |
| ffuf | Dir brute-force | /opt/homebrew/bin/ffuf |
| nikto | Web vuln scan | /opt/homebrew/bin/nikto |
| exiftool | Metadata | /opt/homebrew/bin/exiftool |
| spiderfoot | OSINT framework | ~/.local/bin/spiderfoot |
| httpx | HTTP probing | /opt/homebrew/bin/httpx |

### NOT Installed, Need Installation
| Tool | Category | Install Method |
|------|----------|---------------|
| **nuclei** | Vuln scan (шаблонний) | `go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest` |
| **katana** | Web crawler | `go install github.com/projectdiscovery/katana/cmd/katana@latest` |
| **naabu** | Port scan | `go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest` |
| **censys** | Internet search | `pip3 install censys` |
| **recon-ng** | OSINT framework | repo-local checkout under `tools/recon-ng` or explicit `RECONNG_BIN` |
| **blackbird** | Username OSINT | repo-local checkout under `tools/blackbird` or explicit `BLACKBIRD_BIN` |
| **metagoofil** | Doc metadata | repo-local checkout under `tools/metagoofil` or explicit `METAGOOFIL_BIN` |
| **gobuster** | Dir brute-force | `go install github.com/OJ/gobuster/v3@latest` |
| **eyewitness** | Web screenshots | repo-local checkout under `tools/EyeWitness` or explicit `EYEWITNESS_BIN` |

---

## Architecture Decision: What Gets an Adapter vs What Stays External

### Gets a HANNA Adapter (produces ReconHit, runs in worker pool)
Tools that return **observable data** (phones, emails, usernames, URLs, IPs, coordinates):
- nuclei → infrastructure hits, vuln findings
- katana → crawled URLs, discovered endpoints
- httpx → tech fingerprints, status probing
- censys → certificates, hosts, shadow IT
- naabu → open ports per IP
- blackbird → username → platform URLs
- holehe → email → registered services
- recon-ng → modular data feeds
- metagoofil → doc metadata (emails, names, usernames)
- eyewitness → screenshot + tech detection
- subfinder → subdomains (wrap existing binary)
- amass → subdomains + ASN (wrap existing binary)

### Stays External (used through reconFTW or manual)
Tools that are **consumers** of data rather than producers of observables:
- reconFTW (orchestrator that calls our tools)
- SpiderFoot (parallel system — feeds data via export)
- Maltego (visualization layer — reads RunResult JSON)
- gobuster/feroxbuster (directory brute — too noisy for auto-integration)

---

## Implementation Phases

### Phase 1 — ProjectDiscovery Stack (highest ROI)
**Install + Adapt:** nuclei, katana, httpx, naabu
**Why first:** These form the `subfinder → dnsx → httpx → nuclei + katana` pipeline that's the 2026 infrastructure recon gold standard. httpx already installed.

#### New Adapters:
1. **`adapters/nuclei.py`** — NucleiAdapter
   - Input: domain, URL, IP
   - Output: ReconHit(type=vulnerability, infrastructure)
   - Wraps CLI: `nuclei -u {target} -j -silent`
   - Parses JSON output → hits with CVE/template references
   - Lane: slow (template-based scanning is heavy)
   - Priority: P1

2. **`adapters/katana.py`** — KatanaAdapter
   - Input: URL/domain
   - Output: ReconHit(type=url, endpoint)
   - Wraps CLI: `katana -u {target} -j -d 3 -silent`
   - Discovers JS endpoints, forms, APIs
   - Lane: slow (crawling)
   - Priority: P2

3. **`adapters/httpx_probe.py`** — HttpxAdapter
   - Input: domain list (from subfinder/amass)
   - Output: ReconHit(type=infrastructure) — tech stack, status, titles
   - Wraps CLI: `httpx -u {target} -j -silent -tech-detect`
   - Lane: fast
   - Priority: P1

4. **`adapters/naabu.py`** — NaabuAdapter
   - Input: IP/domain
   - Output: ReconHit(type=port, infrastructure)
   - Wraps CLI: `naabu -host {target} -j -silent`
   - Fast port scanning, replaces masscan for typical use
   - Lane: fast
   - Priority: P1

#### New Preset:
```python
"pd-infra": ["httpx_probe", "katana", "nuclei", "naabu"]
"pd-full":  ["httpx_probe", "katana", "nuclei", "naabu", "ashok"]
"pd-infra-quick": ["httpx_probe", "katana", "nuclei", "naabu"]
"pd-infra-deep":  ["httpx_probe", "katana", "nuclei", "naabu"]
```

---

### Phase 2 — Person OSINT Expansion
**Install + Adapt:** blackbird, holehe (wrap), censys
**Why second:** Directly augments person OSINT — the core use case.

#### New Adapters:
5. **`adapters/blackbird.py`** — BlackbirdAdapter
   - Input: username
   - Output: ReconHit(type=url) — platform profile URLs
   - Wraps CLI: `blackbird -u {username} --json`
   - Complements social_analyzer (different platform coverage)
   - Lane: fast
   - Priority: P2

6. **`adapters/holehe_adapter.py`** — HoleheAdapter
   - Input: email
   - Output: ReconHit(type=url, username) — services where email is registered
   - Wraps CLI: `holehe {email} --only-used --no-color`
   - Essential for email → service mapping
   - Lane: fast
   - Priority: P1

7. **`adapters/censys_adapter.py`** — CensysAdapter
   - Input: domain, IP, certificate
   - Output: ReconHit(type=infrastructure) — certs, hosts, cloud assets
   - Uses Python SDK: `from censys.search import CensysHosts`
   - Complements Shodan (different data sources, especially certs)
   - Env: `CENSYS_API_ID`, `CENSYS_API_SECRET`
   - Lane: fast
   - Priority: P1

8. **`adapters/metagoofil_adapter.py`** — MetagoofilAdapter
   - Input: domain
   - Output: ReconHit(type=email, username) — metadata from public docs
   - Wraps CLI: `metagoofil -d {domain} -t pdf,docx,xlsx -l 50`
   - Lane: slow
   - Priority: P2

#### New Presets:
```python
"person-deep": ["ua_phone", "ghunt", "holehe", "blackbird", "search4faces", "social_analyzer"]
"email-chain": ["holehe", "ghunt", "metagoofil"]
```

---

### Phase 3 — Existing Tool Wrappers (already installed, just need adapters)
**Adapt only (no install):** subfinder, amass, nmap, shodan

#### New Adapters:
9. **`adapters/subfinder_adapter.py`** — SubfinderAdapter
    - Wraps: `subfinder -d {domain} -silent`
    - Output: ReconHit(type=domain) — subdomains
    - Lane: fast, Priority: P1

10. **`adapters/amass_adapter.py`** — AmassAdapter
    - Wraps: `amass enum -d {domain} -passive`
    - Output: ReconHit(type=domain, ip) — subdomains + ASN
    - Lane: slow, Priority: P1

11. **`adapters/nmap_adapter.py`** — NmapAdapter
    - Wraps: `nmap -sV -T4 --top-ports 1000 -oX - {target}`
    - Output: ReconHit(type=port, infrastructure) — service fingerprints
    - Lane: slow, Priority: P0

12. **`adapters/shodan_adapter.py`** — ShodanAdapter
    - Uses Python SDK or CLI: `shodan host {ip}`
    - Output: ReconHit(type=infrastructure, port) — banners, vulns, tech
    - Env: `SHODAN_API_KEY`
    - Lane: fast, Priority: P1

#### New Presets:
```python
"subdomain-full": ["subfinder", "amass", "ashok"]
"port-scan": ["naabu", "nmap"]
"infra-deep": ["subfinder", "httpx_probe", "nuclei", "nmap", "shodan", "censys"]
"recon-auto-quick": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"]
"recon-auto-deep": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"]
```

---

### Phase 4 — Framework & Automation Integration
**Install + Configure:** recon-ng, reconFTW, SpiderFoot activation

#### New Adapters:
13. **`adapters/reconng.py`** — ReconNGAdapter
    - Wraps recon-ng workspaces via CLI
    - Input: domain/email/username
    - Runs selected recon-ng modules, parses DB output
    - Lane: slow, Priority: P2

14. **`adapters/eyewitness_adapter.py`** — EyewitnessAdapter
    - Wraps: `eyewitness --web -f urls.txt --no-prompt`
    - Input: URL list (from httpx/subfinder)
    - Output: ReconHit(type=url) — screenshots + tech classification
    - Lane: slow, Priority: P3

#### Pipeline Scripts (not adapters — orchestration layer):
- `pipelines/infra_recon.py` — subfinder → dnsx → httpx → nuclei + katana
- `pipelines/person_recon.py` — holehe → ghunt → blackbird → social_analyzer
- `pipelines/full_spectrum.py` — both pipelines + all existing adapters

---

## Updated Registry After All Phases

```python
# registry.py — After expansion (28 adapters)
MODULES = {
    # === Existing 14 ===
    "ua_leak", "ru_leak", "vk_graph", "avito", "ua_phone",
    "maryam", "ashok", "ghunt", "social_analyzer", "satintel",
    "search4faces", "web_search", "opendatabot", "firms",
    # === Phase 1: ProjectDiscovery ===
    "nuclei", "katana", "httpx_probe", "naabu",
    # === Phase 2: Person OSINT ===
    "blackbird", "holehe", "censys", "metagoofil",
    # === Phase 3: Existing Tool Wrappers ===
    "subfinder", "amass", "nmap", "shodan",
    # === Phase 4: Frameworks ===
    "reconng", "eyewitness",
}

MODULE_PRIORITY = {
    # ... existing ...
    "nmap": 0,         # P0 — service fingerprinting
    "nuclei": 1,       # P1 — vuln scanning
    "httpx_probe": 1,  # P1 — tech detection
    "naabu": 1,        # P1 — fast port scan
    "subfinder": 1,    # P1 — subdomain enum
    "amass": 1,        # P1 — subdomain + ASN
    "shodan": 1,       # P1 — internet search
    "censys": 1,       # P1 — cert + host search
    "holehe": 1,       # P1 — email service mapping
    "katana": 2,       # P2 — crawling
    "blackbird": 2,    # P2 — username search
    "metagoofil": 2,   # P2 — doc metadata
    "reconng": 2,      # P2 — modular recon
    "eyewitness": 3,   # P3 — screenshots
}

MODULE_PRESETS = {
    # ... existing ...
    # Phase 1
    "pd-infra": ["httpx_probe", "katana", "nuclei", "naabu"],
    # Phase 2
    "person-deep": ["ua_phone", "ghunt", "holehe", "blackbird", "search4faces", "social_analyzer"],
    "email-chain": ["holehe", "ghunt", "metagoofil"],
    # Phase 3
    "subdomain-full": ["subfinder", "amass", "ashok"],
    "port-scan": ["naabu", "nmap"],
    "infra-deep": ["subfinder", "httpx_probe", "nuclei", "nmap", "shodan", "censys"],
    # Phase 4
    "recon-auto": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"],
    # Combined
    "full-spectrum-2026": [*ALL_28_ADAPTERS],
}
```

---

## Execution Order & Dependencies

```
Phase 1 (ProjectDiscovery)          Phase 2 (Person)
  ┌─────────────────┐                ┌──────────────┐
  │ Install:        │                │ Install:     │
  │  nuclei         │                │  blackbird   │
  │  katana         │                │  censys      │
  │  naabu          │                │  metagoofil  │
  │ (httpx: done)   │                │ (holehe:done)│
  ├─────────────────┤                ├──────────────┤
  │ Adapters:       │                │ Adapters:    │
  │  nuclei.py      │                │  blackbird   │
  │  katana.py      │                │  holehe      │
  │  httpx_probe.py │                │  censys      │
  │  naabu.py       │                │  metagoofil  │
  └────────┬────────┘                └──────┬───────┘
           │                                │
           ▼                                ▼
  Phase 3 (Wrap Existing)           Phase 4 (Frameworks)
  ┌─────────────────┐                ┌──────────────┐
  │ Adapters only:  │                │ Install:     │
  │  subfinder.py   │                │  recon-ng    │
  │  amass.py       │                │  eyewitness  │
  │  nmap.py        │                │  (reconFTW)  │
  │  shodan.py      │                ├──────────────┤
  └────────┬────────┘                │ Adapters:    │
           │                         │  reconng.py  │
           │                         │  eyewitness  │
           ▼                         └──────┬───────┘
  ┌──────────────────────────────────────────┘
  │ Final: Update registry.py, presets, cli.py
  │ Test full-spectrum-2026 preset
  └─────────────────────────────────────────────
```

---

## Implementation Rule per Adapter

Every new adapter MUST follow this contract:
```python
class XxxAdapter(ReconAdapter):
    name = "xxx"
    region = "global"  # or "ua" / "ru"

    def search(self, target_name, known_phones, known_usernames) -> list[ReconHit]:
        # 1. Determine input type (domain? email? username? phone?)
        # 2. Call tool (subprocess or SDK)
        # 3. Parse output
        # 4. Return list[ReconHit] with proper observable_type, confidence, source_detail
```

After creating adapter:
1. Import in `adapters/__init__.py`
2. Add to `ADAPTER_REGISTRY`
3. Add to `registry.py`: MODULE_PRIORITY, MODULE_LANE
4. Add to relevant presets
5. Add env var docs to `.env.example`
6. Smoke test: `python3 cli.py manual --module xxx --target test`
7. Run `python3 src/cli.py preflight --strict` before operational rollout
8. For infrastructure presets, explicitly validate the intended nuclei profile (`quick` vs `deep`) before running broad scans

---

## What NOT to Integrate (and Why)

| Tool | Reason |
|------|--------|
| reconFTW | External orchestrator — runs OUR tools, not an adapter |
| Maltego | GUI-only visualization — reads our JSON exports |
| gobuster/feroxbuster | Too noisy for auto; use manually via terminal |
| OSINT Framework (site) | Reference website, not a tool |
| Kagi/Perplexity | Search engines, not scriptable OSINT tools |
| RustScan | Redundant with naabu (same niche, naabu has JSON output) |
| alterx/gotator | Subdomain mutation — use *inside* subfinder/amass config |
| puredns/massdns | Bulk DNS — too aggressive for automated pipeline |
| ct-exposer/certipy | crt.sh — already covered by ashok adapter (crt.sh fallback) |
