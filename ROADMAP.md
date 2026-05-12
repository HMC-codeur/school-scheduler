# ROADMAP — Smart School Scheduling SaaS

## Context and current baseline (Phase 1 MVP)

This project already has a solid MVP foundation:

- **Backend**: FastAPI with modular routers for classes, teachers, subjects, slots, schedule, conditions, and time settings.
- **Frontend**: vanilla HTML/CSS/JS dashboard for data entry, schedule generation, and table display.
- **Scheduling engine**: CSP/backtracking generator with constraints for teacher/class slot collisions, unavailable slots, and daily lesson limits.
- **Storage**: in-memory `MemoryStore` (no persistence yet).

This roadmap evolves the existing MVP into a production-ready SaaS in incremental, safe phases.

---

## Phase 1 — Current MVP (stabilize and document)

### Goal
Consolidate the existing MVP as a stable baseline before adding bigger capabilities.

### Backend changes
- Keep the current API surface and scheduling logic intact.
- Add stronger validation/error consistency (uniform error payloads).
- Introduce API versioning convention (`/api/v1`) without breaking existing routes (compatibility alias period).
- Add structured logging around schedule generation inputs/results.

### Frontend changes
- Keep current dashboard layout.
- Improve copy consistency (English/French labels currently mixed).
- Add clearer empty states and validation feedback messages.

### Risks
- Regressions from refactoring router paths.
- Hidden assumptions in frontend calls if endpoint paths change.

### Test plan
- Unit tests for scheduler success/failure scenarios.
- API contract tests for all existing endpoints.
- Smoke test: create data -> generate schedule -> render table.

---

## Phase 2 — Clean dashboard and UX

### Goal
Make the interface clearer, faster, and safer for non-technical school staff.

### Backend changes
- Add lightweight summary endpoints (counts + health/status) to reduce frontend parallel requests.
- Add server-side pagination/search hooks for future scale.

### Frontend changes
- Redesign dashboard sections into guided steps:
  1) Configure time
  2) Add academic entities
  3) Add constraints
  4) Generate schedule
- Improve form accessibility (labels, keyboard flow, error anchors).
- Add optimistic UI + fine-grained loaders instead of full-page refresh behavior.

### Risks
- UI rewrite can accidentally break current workflow.
- Complexity creep if visual redesign and feature additions happen together.

### Test plan
- Manual UX checklist (all forms usable with keyboard only).
- Browser compatibility checks (Chrome/Edge/Firefox).
- Basic frontend regression tests (Playwright/Cypress smoke flow).

---

## Phase 3 — User-created constraints (stored, structured-ready)

### Goal
Support free-text user constraints reliably now, while preparing for future AI parsing.

### Backend changes
- Evolve `Condition` model:
  - `id`, `text`, `status` (`draft|active|archived`), `scope` (`teacher|class|global|unknown`), timestamps.
- Add CRUD endpoints with update and archive support.
- Add optional metadata fields (`tags`, `priority`) entered manually (not AI inferred).
- Keep scheduler unchanged initially; constraints are stored and auditable first.

### Frontend changes
- Constraints panel with create/edit/archive/search.
- Filter chips by status/scope.
- “Not yet enforced by scheduler” badge to set expectations.

### Risks
- Users may assume free-text constraints are already enforced.
- Data model may need migration once parsing starts.

### Test plan
- API tests for constraints CRUD lifecycle.
- UI tests for create/edit/archive behavior.
- Copy/usability test to verify users understand enforcement status.

---

## Phase 4 — Configurable time settings (core scheduling surface)

### Goal
Make school calendar/time parameters first-class and fully integrated.

### Backend changes
- Normalize time settings domain model:
  - school day bounds
  - lesson duration
  - break policy
  - lunch break window
  - working days/calendar presets.
- Validate edge cases (overlapping lunch, impossible windows, zero generated slots).
- Expose slot preview endpoint before save.
- Add “regenerate slots only” vs “regenerate full schedule” endpoints.

### Frontend changes
- Time configuration wizard with real-time slot preview.
- Warnings for destructive actions (changing times may invalidate schedules).
- One-click apply to regenerate slot grid.

### Risks
- Time math bugs (overlaps, DST assumptions, malformed inputs).
- Users losing schedule work after major time changes.

### Test plan
- Deterministic unit tests for slot generation edge cases.
- API tests for invalid configurations.
- UI tests for preview/apply flows.

---

## Phase 5 — Database persistence

### Goal
Replace in-memory state with durable, multi-entity persistence.

### Backend changes
- Introduce PostgreSQL + SQLAlchemy/Alembic migrations.
- Create normalized tables for schools (future-safe), classes, teachers, subjects, slots, constraints, schedules, time settings.
- Repository/service layer abstraction so scheduler logic remains isolated.
- Add seed/demo data pipeline.

### Frontend changes
- Minimal changes initially (same API contracts).
- Add persistence affordances: “last saved”, save errors, retry hints.

### Risks
- Data migration complexity from ad hoc in-memory assumptions.
- Transaction boundaries during schedule generation writes.

### Test plan
- Migration tests (upgrade/downgrade).
- Integration tests with test DB.
- Load test: concurrent reads/writes around schedule generation.

---

## Phase 6 — Exports PDF/Excel

### Goal
Enable schools to share schedules externally in common formats.

### Backend changes
- Export service layer:
  - `GET /exports/schedule.pdf`
  - `GET /exports/schedule.xlsx`
- Template-driven formatting (school header, class columns, slot rows).
- Async/background generation for large schedules.

### Frontend changes
- Export buttons with format selector.
- Export status/toast + download history list.

### Risks
- Formatting inconsistency across printers/spreadsheets.
- Long-running exports affecting API responsiveness.

### Test plan
- Golden-file tests for PDF/XLSX structure.
- Manual print preview verification.
- Performance test for large timetables.

---

## Phase 7 — AI constraint parser

### Goal
Convert natural-language constraints into structured, machine-enforceable rules.

### Backend changes
- Add `constraint_parser` service behind feature flag.
- Parse free text into structured schema (actor, action, time window, polarity, confidence).
- Human-in-the-loop review flow: parsed suggestion requires user confirmation.
- Store raw prompt/result/audit metadata.

### Frontend changes
- “Parse constraint” action per condition.
- Review card: proposed structured rule + confidence + accept/edit/reject.
- Visual mapping between accepted rules and enforced scheduler constraints.

### Risks
- Parsing mistakes causing invalid or unfair schedules.
- Trust/safety concerns if AI results auto-apply.

### Test plan
- Evaluation set of representative school rules.
- Precision/recall tracking for parsed fields.
- Mandatory manual approval test (no silent auto-enforcement).

---

## Phase 8 — SaaS accounts and school profiles

### Goal
Support secure multi-tenant usage across many schools.

### Backend changes
- AuthN/AuthZ: account signup/login, roles (admin/planner/viewer).
- Multi-tenancy model (`school_id` scoping on all core tables).
- Session/token handling, password reset, audit logs.
- Tenant-aware rate limiting and quotas.

### Frontend changes
- Login/logout, account settings, school profile pages.
- Role-based UI visibility.
- School switcher (for district-level users, optional later).

### Risks
- Cross-tenant data leakage (highest risk).
- Permission model complexity.

### Test plan
- Security tests for tenant isolation.
- Role matrix tests for endpoint access.
- Pen-test checklist (auth/session vulnerabilities).

---

## Phase 9 — Notifications

### Goal
Proactively inform teachers/staff when schedules change.

### Backend changes
- Event system for schedule lifecycle events.
- Notification channels abstraction (email first, push/SMS later).
- Preference center per user (opt-in/out, digest settings).

### Frontend changes
- Notification settings UI.
- Change summary views before sending.
- In-app notification feed.

### Risks
- Notification spam or incorrect recipients.
- Delivery failures and compliance issues.

### Test plan
- Event-to-notification integration tests.
- Template rendering tests.
- Retry/dead-letter queue behavior tests.

---

## Phase 10 — PWA/mobile experience

### Goal
Deliver reliable mobile access for teachers and admins.

### Backend changes
- Optimize endpoints for mobile payload size.
- Add caching headers/ETag support.

### Frontend changes
- Responsive redesign for small screens.
- PWA setup: manifest, service worker, offline shell.
- Mobile-first views for “my schedule today/this week”.

### Risks
- Offline cache staleness leading to outdated schedules.
- Increased QA matrix across devices.

### Test plan
- Lighthouse PWA audits.
- Offline/poor-network scenario tests.
- Device lab checks on iOS/Android browsers.

---

## Cross-phase architecture decisions (recommended)

1. **Keep scheduler logic isolated** in service layer so API/UI/storage can evolve independently.
2. **Adopt domain models now** (schedule, constraint, time config) to reduce future migration pain.
3. **Use feature flags** for risky capabilities (AI parser, notifications).
4. **Define observability early** (structured logs, metrics, trace IDs for generation runs).
5. **Prioritize tenant isolation** as a non-negotiable rule once SaaS accounts begin.

---

## Next immediate task

**Safest next coding step:** implement a **read-only scheduling “dry-run diagnostics” endpoint** that explains *why* generation fails (e.g., missing teacher for subject, insufficient slots, impossible daily caps) without changing current generation behavior.

Why this is safest now:
- It reuses existing scheduler validations.
- It improves UX immediately.
- It reduces risk before adding new constraints/time complexity.
- It does not require database/auth/AI changes.

Suggested concrete ticket:
- Add `POST /schedule/diagnose` returning:
  - `can_generate: bool`
  - `blocking_issues: string[]`
  - `warnings: string[]`
  - `stats` (classes, teachers, subjects, slots, required_sessions, available_sessions).
