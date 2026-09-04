# MCP auth

stdio remains the default transport and is unauthenticated — same as 0.2.0.

When a bind address is configured the server is an **OAuth 2.1 / OIDC resource server**. It validates incoming tokens and nothing more. Token issuance belongs to a separate authorization server. Do not roll a custom one.

**Binding without a configured issuer is a startup error, not a warning.** There is no anonymous mode on a network interface. Auth gates access; it does not add verbs. The read-only allow-list is unchanged: `list_nodes`, `get_node`, `walk_chronological`, `query`, `reverse_pointers`, `replica_status`. Every `write_*`, `summarize`, `compact`, and `saliency_detect` remains a validation failure, even with a perfectly valid token.

## TLS

Loopback (`127.0.0.1`, `::1`, `localhost`) may bind bare. Any other bind requires TLS or it is a startup error — same shape as the issuer check. `0.0.0.0:8080` without certs will not start.

| Variable | Required | Meaning |
| --- | --- | --- |
| `OKF_MCP_TLS_CERT` | non-loopback | PEM certificate path |
| `OKF_MCP_TLS_KEY` | non-loopback | PEM private key path |

## Environment

| Variable | Required on bind | Meaning |
| --- | --- | --- |
| `OKF_MCP_ISSUER` | yes | Authorization-server issuer URL. Startup fails if missing when `--bind` is set. |
| `OKF_MCP_AUDIENCE` | yes | Expected `aud`. Wrong-audience tokens are rejected. |
| `OKF_MCP_JWKS` | yes | JWKS URL or file path. |

```bash
# stdio — unchanged, no token
python3 scripts/remote_mcp.py query --root "$OKF_REPLICA_ROOT"

# network — refuses to start without issuer
python3 scripts/remote_mcp.py serve --bind 127.0.0.1:8765 --root "$OKF_REPLICA_ROOT"
```

## Authorization server

| Option | Use when |
| --- | --- |
| `@mcpauth/auth` | Default recommendation. Purpose-built for MCP, self-hosted, minimal surface. Right for a small fleet. |
| Keycloak | Existing enterprise identity, complex roles, browser login flows and metadata discovery needed out of the box. |

Audience binding, short-lived tokens, and strict scope validation are easy to get subtly wrong. Let the authorization server do that work.

## Still to decide (do not pick in code)

- Scope granularity — one read scope, or per-verb scopes?
- Is `agent.role` a filter or a permission boundary? Recommendation, not implemented: keep role a **filter, not a boundary**, for v1. Auth gates access to the server; it does not partition the bundle by identity.
