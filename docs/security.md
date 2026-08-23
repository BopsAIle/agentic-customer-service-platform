# Identity, Authorization, and Execution Boundaries

Authentication establishes who is calling the platform. Authorization resolves what that identity
may access. Neither step grants an LLM execution authority: the Decision Compiler, policy engine,
confirmation lifecycle, tool validation, and idempotent runtime remain separate deterministic
boundaries.

## Production OIDC boundary

Production configuration uses `AUTH_MODE=oidc`. The backend discovers the provider JWKS URI from
the configured issuer, accepts only the configured RSA signing algorithm, refreshes cached keys for
unknown or rotated key IDs, and verifies signature, issuer, audience, subject, and expiration before
constructing an application `Principal`.

Required deployment settings are:

```text
AUTH_MODE=oidc
OIDC_ISSUER=https://identity.example.com
OIDC_AUDIENCE=agent-control-plane
```

`OIDC_DISCOVERY_URL` may override the standard issuer discovery location. Claim names, recognized
roles, bounded clock skew, HTTP timeout, and JWKS cache duration are configurable. Production
issuer and discovery URLs must use HTTPS.

The default claim mapping expects:

- `sub`: stable provider subject;
- `email`: optional identity metadata, excluded from checkpoint serialization and logs;
- `roles`: exactly one recognized actor role (`support_operator`, `customer`, or `service`);
- `groups`: non-authoritative group metadata;
- `tenant_id`: required tenant scope metadata;
- `customer_ids`: explicit positive customer scopes for customer and support identities.

Subject values are converted to a stable one-way actor identifier for runtime correlation. Tokens,
authorization headers, raw claims, subject values, and email addresses are not metric attributes or
authentication log fields.

## Server-owned authorization

Validated JWT claims become a bounded `Principal`, then an `ExecutionContext`. The existing
`resolve_customer_scope()` function remains the final customer boundary:

```text
Verified OIDC token
    -> Application Principal
    -> resolve_customer_scope()
    -> ExecutionContext
```

An OIDC support operator can select only customer IDs present in its validated scope. A customer
identity is bound to exactly one customer ID. Cross-scope requests fail as not found. Group names,
email, tenant labels, and model output never select an effective customer by themselves.

## Development and compatibility modes

`local_demo` is restricted to development, demo, test, and integration environments. It uses a
configured opaque local credential and is not production IAM. `static` remains available as an
explicit non-production compatibility/test adapter. Production settings reject both modes and fail
closed unless OIDC issuer and audience are configured.

The browser Operator Console still expects a trusted external session adapter in production. OIDC
token acquisition, Authorization Code + PKCE, identity-provider provisioning, and logout/session
operations belong to that deployment-owned frontend or BFF boundary; this repository validates the
access token presented to the backend.

## Bounded observability

`authentication_attempts_total` records only:

- `auth_success`;
- a bounded `auth_failure_reason` category;
- `principal_type`.

It never records bearer values, headers, raw claims, email, groups, customer lists, or provider error
payloads. Authentication errors returned to callers remain credential-safe.
