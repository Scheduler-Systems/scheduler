# Examples

Runnable examples for the Scheduler open core.

## `create-a-schedule.sh` — your first schedule in seconds

The fastest way to see Scheduler work from a clean clone. It starts the
**dependency-free engine** (`packages/core`), creates a schedule, lists it, and
shuts the server back down.

**Requirements:** Node 20+ and `curl`. No `npm install`, no Firebase, no database.

```sh
./examples/create-a-schedule.sh
# or pick a port:
PORT=4180 ./examples/create-a-schedule.sh
```

Expected: a created schedule (HTTP 201) followed by a list containing it.

> The standalone engine authorizes from request headers, so any bearer token
> works for this demo. The production Go API (`services/api`) verifies real
> Firebase ID tokens — see the top-level README.
