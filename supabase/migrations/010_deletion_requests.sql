-- 010: account deletion as a process, not an action. Synthetic data only.
-- The database itself enforces the order of steps, so no tool, script or person can skip one.
--
--   requested -> approved -> completed      (approved starts a cooling-off window)
--   requested -> rejected
--   requested or approved -> cancelled
--
-- ops_writer (the MCP write login) can create a request and cancel one. It can never approve, reject or complete.
-- Those three steps are for a human, who connects as the database owner through a separate script.

create table if not exists ops.deletion_requests (
  request_id       uuid primary key default gen_random_uuid(),
  customer_id      text not null,
  status           text not null default 'requested'
                   check (status in ('requested', 'approved', 'rejected', 'cancelled', 'completed')),
  requested_at     timestamptz not null default now(),
  reason           text,
  decided_by       text,
  decided_at       timestamptz,
  cooling_off_until timestamptz,
  cancelled_by     text,
  cancelled_at     timestamptz,
  completed_by     text,
  completed_at     timestamptz,
  -- a state cannot exist without the facts that got it there
  constraint approved_has_facts check (status <> 'approved' or (decided_by is not null and decided_at is not null and cooling_off_until is not null)),
  constraint rejected_has_facts check (status <> 'rejected' or (decided_by is not null and decided_at is not null)),
  constraint cancelled_has_facts check (status <> 'cancelled' or (cancelled_by is not null and cancelled_at is not null)),
  constraint completed_has_facts check (status <> 'completed' or (completed_by is not null and completed_at is not null and cooling_off_until is not null))
);

-- at most one open request per customer
create unique index if not exists deletion_requests_one_open
  on ops.deletion_requests (customer_id) where status in ('requested', 'approved');

-- The length of the cooling-off window. Clause 5.2 promises completion within 30 days of the request.
create or replace function ops.deletion_cooling_off() returns interval
language sql immutable as $$ select interval '7 days' $$;

create or replace function ops.deletion_requests_guard() returns trigger
language plpgsql as $$
declare
  is_writer boolean := (current_user = 'ops_writer');
begin
  if tg_op = 'DELETE' or tg_op = 'TRUNCATE' then
    raise exception 'ops.deletion_requests records are never deleted';
  end if;

  if tg_op = 'INSERT' then
    if new.status <> 'requested' then
      raise exception 'a deletion request starts as requested';
    end if;
    if new.decided_by is not null or new.decided_at is not null or new.cooling_off_until is not null
       or new.cancelled_by is not null or new.cancelled_at is not null
       or new.completed_by is not null or new.completed_at is not null then
      raise exception 'a new deletion request cannot carry decision, cancellation or completion data';
    end if;
    new.requested_at := now();
    return new;
  end if;

  -- UPDATE
  if old.request_id <> new.request_id or old.customer_id <> new.customer_id
     or old.requested_at <> new.requested_at or old.reason is distinct from new.reason then
    raise exception 'request id, customer, time and reason cannot be changed';
  end if;
  if old.status in ('rejected', 'cancelled', 'completed') then
    raise exception 'a % deletion request is final', old.status;
  end if;

  if old.status = 'requested' and new.status = 'approved' then
    if is_writer then raise exception 'ops_writer cannot approve a deletion'; end if;
    if new.decided_by is null then raise exception 'approval needs decided_by'; end if;
    new.decided_at := now();
    new.cooling_off_until := now() + ops.deletion_cooling_off();
  elsif old.status = 'requested' and new.status = 'rejected' then
    if is_writer then raise exception 'ops_writer cannot reject a deletion'; end if;
    if new.decided_by is null then raise exception 'rejection needs decided_by'; end if;
    new.decided_at := now();
  elsif old.status in ('requested', 'approved') and new.status = 'cancelled' then
    if new.cancelled_by is null then raise exception 'cancellation needs cancelled_by'; end if;
    new.cancelled_at := now();
  elsif old.status = 'approved' and new.status = 'completed' then
    if is_writer then raise exception 'ops_writer cannot complete a deletion'; end if;
    if now() < old.cooling_off_until then
      raise exception 'the cooling-off window is not over until %', old.cooling_off_until;
    end if;
    if new.completed_by is null then raise exception 'completion needs completed_by'; end if;
    new.completed_at := now();
  else
    raise exception 'a deletion request cannot go from % to %', old.status, new.status;
  end if;

  -- once approved, the decision and the window are fixed, whatever the next step is
  if old.status = 'approved' then
    new.decided_by := old.decided_by;
    new.decided_at := old.decided_at;
    new.cooling_off_until := old.cooling_off_until;
  end if;
  return new;
end;
$$;

drop trigger if exists deletion_requests_row_guard on ops.deletion_requests;
create trigger deletion_requests_row_guard
  before insert or update or delete on ops.deletion_requests
  for each row execute function ops.deletion_requests_guard();

drop trigger if exists deletion_requests_no_truncate on ops.deletion_requests;
create trigger deletion_requests_no_truncate
  before truncate on ops.deletion_requests
  for each statement execute function ops.deletion_requests_guard();

-- Grants: the write login may create a request and mark one cancelled. Nothing else.
revoke all on ops.deletion_requests from public, anon, authenticated;
revoke all on ops.deletion_requests from ops_writer;
grant select, insert on ops.deletion_requests to ops_writer;
grant update (status, cancelled_by) on ops.deletion_requests to ops_writer;
