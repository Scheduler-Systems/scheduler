# API Boundaries

Scheduler API is the tenant-scoped backend surface for native clients and
Schedgy bridges.

## Tenant Routing

All routes start with `/v1/tenants/{tenantId}`. Every request must carry a
verified Firebase ID token in the `Authorization: Bearer <token>` header plus an
`x-correlation-id` header for tracing.

The actor's **identity (user id), tenant, and role are derived only from the
verified token claims** — never from request headers. The token's `tenant_id`
claim must match the `{tenantId}` path segment, or the request is rejected with
`403 tenant_mismatch`. The token's `role` custom claim (Scheduler model:
`employer`/`employee`, plus `owner`) is mapped to the authorization role; any
unrecognized value fails closed to `employee`.

The legacy `x-user-id`, `x-user-role`, and `x-tenant-id` headers are **ignored**
and carry no authority. Trusting them was a privilege-escalation vulnerability
(issue #19): any client could self-claim `manager`/`owner`. Clients must stop
sending a role header and instead send a real Firebase ID token.

For local development against the Firebase Auth emulator
(`FIREBASE_AUTH_EMULATOR_HOST` set), unsigned emulator tokens are accepted but
their claims are still validated; this path is disabled in production.

## Schedule Routes

The skeleton exposes the Scheduler v0.2 route surface:

- `GET /v1/tenants/{tenantId}/schedules`
- `POST /v1/tenants/{tenantId}/schedules`
- `GET /v1/tenants/{tenantId}/schedules/{scheduleId}`
- `POST /v1/tenants/{tenantId}/schedules/{scheduleId}/availability`
- `POST /v1/tenants/{tenantId}/schedules/{scheduleId}/drafts`
- `POST /v1/tenants/{tenantId}/schedules/{scheduleId}/publish`
- `POST /v1/tenants/{tenantId}/schedules/{scheduleId}/requests`
- `POST /v1/tenants/{tenantId}/schedgy/approved-constraints:import`

## Approval Boundary

Schedule creation, draft creation, publication, and Schedgy approved-constraint
imports require a manager or owner actor. Employee-originated availability and
request submissions are accepted as pending approvals.

## Schedgy Boundary

Schedgy does not write Scheduler storage directly. It imports approved,
auditable constraints through Scheduler API, and Scheduler owns validation,
approval state, draft generation, publication, notifications, and audit logs.
