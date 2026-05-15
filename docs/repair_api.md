# Local Repair API

This document describes the backend-only API for local timetable repair.

The repair flow is intentionally experimental and non-destructive by default when used with proposals. It does not change the frontend, does not introduce PostgreSQL, and does not replace the legacy generation endpoint.

## Recommended Workflow

1. Load demo data:

```bash
curl -X POST http://127.0.0.1:8000/schedule/load-demo
```

2. Generate the current timetable:

```bash
curl -X POST http://127.0.0.1:8000/schedule/generate
```

3. Simulate a local repair:

```bash
curl -X POST "http://127.0.0.1:8000/schedule/repair" \
  -H "Content-Type: application/json" \
  -d "{\"repair_type\":\"repair_teacher\",\"teacher_id\":\"teacher-1\",\"repair_policy\":\"balanced\",\"time_budget_seconds\":5,\"commit\":false}"
```

4. Preview the generated proposal:

```bash
curl http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-id
```

5. Accept or reject the proposal:

```bash
curl -X POST http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-id/accept
```

```bash
curl -X DELETE http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-id
```

## POST /schedule/repair

Repairs the current schedule using the OR-Tools repair service.

The endpoint requires an existing schedule. Generate one first with `POST /schedule/generate` or `POST /schedule/generate?engine=ortools`.

### Request Fields

- `repair_type`: required. One of:
  - `repair_class`
  - `repair_teacher`
  - `repair_day`
- `repair_policy`: optional, default `balanced`. One of:
  - `strict`: moves as little as possible.
  - `balanced`: compromise between stability and quality.
  - `flexible`: allows more changes to improve quality.
- `class_id`: required for `repair_class` unless `repair_target` is provided.
- `teacher_id`: required for `repair_teacher` unless `repair_target` is provided.
- `day`: required for `repair_day` unless `repair_target` is provided.
- `repair_target`: optional direct target name.
- `modified_constraints`: optional temporary constraints for this repair.
- `pinned_assignments`: optional sessions that should remain fixed.
- `time_budget_seconds`: optional solver budget, currently limited by API validation.
- `strategy`: optional OR-Tools quality strategy.
- `commit`: optional boolean, default `true`.

### commit=true

`commit=true` repairs and commits immediately.

The current schedule is updated only when:

- the repair succeeds;
- `hard_conflicts == 0`;
- backend validation confirms no hard conflict.

If the repair fails, the current schedule is not overwritten.

### commit=false

`commit=false` simulates the repair.

The endpoint:

- runs the repair solver;
- returns the proposed schedule;
- returns `changed_items`;
- creates a temporary `proposal_id`;
- never modifies `store.schedule`.

The returned proposal can then be previewed, accepted, or deleted.

### Response Fields

Important response fields:

- `success`
- `message`
- `schedule`
- `proposal_id`
- `committed`
- `simulation`
- `changed_sessions`
- `changed_items`
- `changed_items_count`
- `stability_penalty`
- `stability_score`
- `hard_conflicts`
- `quality_score`
- `repair_type`
- `repair_policy`
- `repair_target`
- `final_repair_strategy`
- `diagnostics`

`changed_items` contains the detailed before/after diff for moved or changed sessions. Each item includes `session_id` when available, so repeated courses such as multiple Math sessions can be tracked reliably.

### Example: Simulate repair_teacher

```bash
curl -X POST "http://127.0.0.1:8000/schedule/repair" \
  -H "Content-Type: application/json" \
  -d "{\"repair_type\":\"repair_teacher\",\"teacher_id\":\"teacher-1\",\"repair_policy\":\"balanced\",\"time_budget_seconds\":5,\"commit\":false}"
```

Example response shape:

```json
{
  "success": true,
  "message": "Repair simulated successfully. Current schedule unchanged.",
  "proposal_id": "repair-proposal-abc123",
  "committed": false,
  "simulation": true,
  "changed_sessions": 2,
  "hard_conflicts": 0,
  "stability_score": 96,
  "quality_score": 91,
  "changed_items_count": 2,
  "changed_items": [
    {
      "session_id": "session-grade-7a-math-0001",
      "class_name": "Grade 7A",
      "subject_name": "Math",
      "old_slot": "Mon-08:00",
      "new_slot": "Tue-08:00",
      "old_teacher_name": "Mr. Khan",
      "new_teacher_name": "Mr. Khan",
      "change_type": "slot_changed",
      "reason": "Cours déplacé pendant la réparation"
    }
  ]
}
```

### Example: Direct repair with commit=true

```bash
curl -X POST "http://127.0.0.1:8000/schedule/repair" \
  -H "Content-Type: application/json" \
  -d "{\"repair_type\":\"repair_teacher\",\"teacher_id\":\"teacher-1\",\"repair_policy\":\"strict\",\"time_budget_seconds\":5,\"commit\":true}"
```

### Example: repair_class

```bash
curl -X POST "http://127.0.0.1:8000/schedule/repair" \
  -H "Content-Type: application/json" \
  -d "{\"repair_type\":\"repair_class\",\"class_id\":\"class-1\",\"repair_policy\":\"balanced\",\"time_budget_seconds\":5,\"commit\":false}"
```

### Example: repair_day

```bash
curl -X POST "http://127.0.0.1:8000/schedule/repair" \
  -H "Content-Type: application/json" \
  -d "{\"repair_type\":\"repair_day\",\"day\":\"Mon\",\"repair_policy\":\"flexible\",\"time_budget_seconds\":5,\"commit\":false}"
```

## GET /schedule/repair/proposals/{proposal_id}

Previews a temporary repair proposal.

This endpoint is read-only. It never modifies the current schedule.

### Response Fields

- `proposal_id`
- `proposed_schedule`
- `changed_items`
- `changed_items_count`
- `diagnostics`
- `repair_type`
- `repair_policy`
- `created_at`
- `stability_score`
- `hard_conflicts`
- `quality_score`

### Example

```bash
curl http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-abc123
```

If the proposal does not exist, the endpoint returns `404`.

## POST /schedule/repair/proposals/{proposal_id}/accept

Accepts a temporary repair proposal and applies it to the current schedule.

The endpoint:

- verifies that the proposal exists;
- verifies `hard_conflicts == 0`;
- revalidates the proposed schedule;
- applies the proposed schedule to `store.schedule`;
- removes the proposal after successful acceptance.

### Example

```bash
curl -X POST http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-abc123/accept
```

If the proposal is unknown, the endpoint returns `404`.

If the proposal has hard conflicts or fails validation, the endpoint returns an error and the current schedule remains unchanged.

## DELETE /schedule/repair/proposals/{proposal_id}

Deletes a temporary repair proposal.

This is the reject path. It never modifies the current schedule.

### Example

```bash
curl -X DELETE http://127.0.0.1:8000/schedule/repair/proposals/repair-proposal-abc123
```

If the proposal is unknown, the endpoint returns `404`.

## Safety Guarantees

- Existing endpoints remain compatible.
- `/schedule/generate` remains legacy by default.
- `commit=false` never modifies the current schedule.
- Failed repairs never overwrite the current schedule.
- Accepting a proposal is refused when `hard_conflicts != 0`.
- Accepting a proposal revalidates hard constraints before committing.
- Deleting a proposal never modifies the current schedule.
- `session_id` is preserved through simulation, preview, acceptance, and diff generation.

## Current Limits

- Repair proposals are temporary and stored in backend memory only.
- Proposals are not persisted in a database.
- Proposals are lost on backend restart or store reset.
- The frontend is not wired to this flow yet.
- An AI assistant is not wired to this flow yet.
- Proposal expiration and user ownership are not implemented yet.
