# Authentication Outage Runbook

## Symptoms

- Login or token validation failures increase.
- OIDC discovery/JWKS refresh errors occur.
- `/health/details` reports the authentication boundary as degraded.

## Investigation

1. Confirm issuer, audience, algorithm, clock, and deployment identity.
2. Check the identity provider and JWKS endpoint through the approved network
   path; do not paste tokens or claims into logs.
3. Distinguish key rotation/cache errors from provider unavailability.
4. Confirm tenant/customer scope resolution remains server-owned.

## Recovery

Restore the identity provider or correct the configured discovery/key path,
then validate a test principal with a non-production token. Do not switch a
production service to local demo/static authentication as an emergency bypass.
