# Manual QA Checklist

## Backend
- [ ] `curl -fsS http://localhost:3000/health` returns 200
- [ ] `npm run benchmark:multi` reports throughput close to or above target environment threshold
- [ ] Process memory remains under configured production limit (512MB)

## Frontend TUI
- [ ] `npm run tui:test` passes smoke checks
- [ ] Search panel opens and parses sample query (`Ctrl+S`, `Ctrl+Enter`)
- [ ] Debug panel toggles and updates (`Ctrl+D`, `F12`)

## System
- [ ] `npm run system-verify` reports green checks on Linux systemd host
- [ ] `journalctl -u hanna-parser -n 100 --no-pager` has no crash loops
- [ ] `npm run master-test` ends with `SYSTEM PRODUCTION READY`
