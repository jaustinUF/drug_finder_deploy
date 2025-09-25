# 🩺 Drug Finder (MCP + NiceGUI)

Consumer-friendly drug/medication lookup app built with:
- **MCP** (Model Context Protocol) client/host
- **NiceGUI** front end
- **RxNav / RxNorm** APIs under the hood

> **Live demo:** https://drugfinderdeploy-production.up.railway.app/  
> **Origin:** enhanced successor to `medical_project_deploy` (same architecture; more tools, stronger docs, nicer UX).

---

## What’s new (v2)
- **Six new MCP tools** (in addition to the original two):
  - `get_spelling_suggestions` – typo help
  - `find_rxcui` – exact + approximate match (fallback) to RxCUI
  - `get_all_related_info` – brand/generic, forms, strengths (grouped by TTY)
  - `get_ndc_properties` – NDC → product/package info
  - `get_rxcui_history_status` – Active / Obsolete / Remapped
  - `get_rxterms_info` – consumer-friendly display (name, strength, route, dose form)
- **System prompt** for consistent, consumer tone and routing (no tool-narration). Includes safety warning.
- **Structured tool docstrings** (Purpose / When / Inputs / Returns / Notes / Example).
- **UI:** added **Clear** button (wipe transcript), moved **Ask** for better ergonomics.
- **Reliability:** graceful **429 rate-limit** handling; optional **tool-use audit** print; optional **history clipping** (keep recent pairs + last 1–2 tool turns).
- **Noise control:** silenced verbose logs in the MCP server process.

---

## Architecture
- See README.md file in `medical_project_deploy` repo 
