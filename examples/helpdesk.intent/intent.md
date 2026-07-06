# Helpdesk — Intent (greenfield)

## Purpose
An internal IT ticketing system. Users raise tickets; tickets auto-route to
the IT analyst best suited by specialty and current load; user and analyst
converse on the ticket with file attachments; either party closes it; closed
tickets archive on a schedule for later reporting.

## Users (three roles)
- **administrator** — manages user accounts and analyst specialties; full read
  across all tickets; cannot be auto-assigned tickets.
- **it_analyst** — has one or more specialties; receives auto-assigned tickets
  matching a specialty; converses, attaches files, closes tickets.
- **user** — creates tickets, converses on their own tickets, attaches files,
  closes their own tickets; sees only their own tickets.

## Core jobs
1. **Login** with username + password (Argon2id-verified; see policy/security).
2. **Account management** (administrator): create/disable users, assign roles,
   set analyst specialties.
3. **Create ticket** (user): subject, body, category. On creation the ticket
   is auto-assigned to the least-loaded active analyst whose specialties
   include the ticket's category. If no analyst matches, it assigns to the
   least-loaded analyst overall and is flagged `unrouted`.
4. **Converse**: user and assigned analyst post messages on the ticket, in
   order; each message may carry attachments (files/screenshots).
5. **Attachments**: upload to a ticket message; download by ticket
   participants and administrators only.
6. **Close**: the ticket's user OR its assigned analyst sets status CLOSED.
   Closing records who closed it and when.
7. **Archive** (scheduled): a daily job moves tickets CLOSED for >= 24h to
   status ARCHIVED. Archived tickets are read-only and are the reporting set.

## Ticket status lifecycle
OPEN -> IN_PROGRESS (first analyst reply) -> CLOSED (either party) -> ARCHIVED
(scheduled). No status skips backward; ARCHIVED is terminal. Reopening is out
of scope for v1 (a closed ticket's user opens a new ticket).

## Authorization summary (see interface/api.openapi.yaml x-auth + roles)
- A user reads/writes ONLY tickets where they are the creator.
- An analyst reads/writes ONLY tickets assigned to them.
- An administrator reads all tickets; administrators do NOT post messages or
  get auto-assigned (separation of duties for v1).
- Cross-role access failures return 404 (not 403) to avoid leaking existence,
  EXCEPT unauthenticated requests, which return 401.

## What breaks if it vanishes
The org's IT support pipeline and the archived-ticket reporting history.

## Non-goals (v1)
Ticket reopening, SLA timers/escalation, email ingestion, ticket reassignment
by analysts, nested comment threads, public/anonymous tickets.
