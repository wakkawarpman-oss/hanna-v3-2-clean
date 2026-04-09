# HANNA OPSEC Runbook

This runbook defines the canonical safe operator paths for proxy-only and Tor-routed execution.

## Canonical Routing Modes

### Direct mode

Use only when OPSEC policy allows clearnet traffic.

```bash
./scripts/hanna agg --target example.com --modules pd-infra
```

### Explicit proxy mode

Use when the route must be pinned to a known proxy endpoint.

```bash
./scripts/hanna ch --target example.com --modules full-spectrum --proxy socks5h://127.0.0.1:9055
```

### Tor shortcut mode

`--tor` is the canonical operator shortcut for the default SOCKS endpoint.

```bash
./scripts/hanna man --module social_analyzer --target example.com --usernames account-exists --tor
./scripts/hanna ui --tor --plain
```

Equivalent routing:

```text
--tor == --proxy socks5h://127.0.0.1:9050
```

The default endpoint can be overridden with `HANNA_TOR_PROXY`.

## Hard Policy Gate

Use `HANNA_REQUIRE_PROXY=1` when no direct network access is acceptable.

```bash
HANNA_REQUIRE_PROXY=1 ./scripts/hanna agg --target example.com --modules pd-infra --tor
```

Effect:

- Direct HTTP requests without proxy are blocked.
- CLI-backed tools launched without proxy are blocked.
- The run fails before collection rather than silently degrading to clearnet.

## Invalid Combinations

Do not combine `--tor` and `--proxy`.

Invalid:

```bash
./scripts/hanna ch --target example.com --tor --proxy socks5h://127.0.0.1:9055
```

Expected failure:

```text
Use either --tor or --proxy, not both
```

## Early Failure Signatures

### Tor endpoint is down

Expected failure:

```text
Tor proxy endpoint is unreachable at 127.0.0.1:9050
```

Meaning:

- `--tor` was requested.
- HANNA could not connect to the configured SOCKS endpoint.
- No collection should be considered started safely.

### Proxy required but missing

Expected failure examples:

```text
HANNA_REQUIRE_PROXY=1 but no proxy provided for HTTP request
HANNA_REQUIRE_PROXY=1 but no proxy provided for CLI execution
HANNA_REQUIRE_PROXY=1 but no proxy provided to WebSearchAdapter
```

Meaning:

- Strict proxy policy is active.
- A code path attempted direct execution.
- Treat as a blocking OPSEC failure.

### Proxy/Tor unsupported adapter

Expected failure example:

```text
nmap cannot be executed safely with proxy/Tor routing; remove nmap from the module set or run it only in direct mode
```

Meaning:

- The adapter performs activity that is not safely honor-bound to the selected proxy route.
- This is a design-time incompatibility, not a transient network failure.

## Operator Rules

1. Use `--tor` for the default safe SOCKS route.
2. Use `--proxy` only when you intentionally need a non-default route.
3. Use `HANNA_REQUIRE_PROXY=1` for environments where clearnet execution is forbidden.
4. Treat early routing failures as hard blockers.
5. Do not include proxy-unsafe modules in Tor-routed module sets.

## Recommended Safe Examples

### Tor-routed manual username pivot

```bash
./scripts/hanna man --module social_analyzer --target example.com --usernames account-exists --tor --json-summary-only
```

### Tor-routed aggregate run

```bash
./scripts/hanna agg --target example.com --modules httpx_probe,katana,shodan --tor --json-summary-only
```

### Strict proxy chain run

```bash
HANNA_REQUIRE_PROXY=1 \
./scripts/hanna ch --target example.com --modules full-spectrum --tor --report-mode shareable --json-summary-only
```

## Release Gate Interpretation

For readiness claims, OPSEC is green only when:

- `--tor` resolves predictably.
- The Tor endpoint is validated before launch.
- Proxy-required enforcement blocks all direct execution paths.
- Proxy propagation is verified for CLI-backed modules.
- Proxy-unsafe adapters fail explicitly rather than running ambiguously.