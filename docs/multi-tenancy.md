# Multi-tenancy and data isolation

The platform treats tenant isolation as a persistence boundary in addition to
the existing customer-scope authorization boundary.

## Boundary model

Authentication identifies the principal. Authorization resolves the customer
scope that the principal may act on. The persistence layer then requires the
tenant scope on reads and writes, so a valid principal cannot use a customer
identifier from another tenant to widen access.

The effective flow is:

```text
OIDC or local principal
        |
        v
ExecutionContext (tenant + customer scope)
        |
        v
Tenant-scoped repositories and database constraints
```

Tenant-owned relational resources carry a `tenant_id` foreign key and indexed
scope. Customer identity uniqueness and idempotency receipt uniqueness include
the tenant scope. Agent-run projections, policy audit records, memory records,
and business resources are filtered by tenant before customer-specific filters
are applied.

The migration creates a `default` compatibility tenant and backfills existing
rows into it while adding non-null tenant foreign keys. This is safe for the
existing local dataset; production tenant assignment should be an explicit,
reviewed mapping rather than an inference from customer data.

Conversation and message state is carried by the agent checkpoint namespace;
the namespace includes the tenant for non-default deployments. Evidence kept
inside operator projections is likewise stored under its tenant-scoped run.

## Privacy and observability

Tenant isolation telemetry contains only bounded outcomes such as accepted,
rejected, tenant-scoped, or missing-context. It does not record tenant names,
customer data, PII, tokens, or authorization headers.

The `default` tenant is a compatibility scope for existing local fixtures and
legacy development data. Production identities should provide an explicit
tenant through the authenticated principal. A tenant context is never inferred
from a customer record or from model output.

Tenant isolation is not an authorization replacement: authentication identifies
the principal, authorization determines allowed scope, and database/repository
isolation enforces the tenant boundary.
