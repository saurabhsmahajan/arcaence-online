-- 011: data export requests. Synthetic data only.
-- The AI can ask for an export and is told what it would contain (counts only). It never holds the data.
-- A human checks the customer's identity (clause 5.2) and fulfils the request through a separate script.
--
--   requested -> fulfilled | rejected          (both final, both by a human, not by ops_writer)

create table if not exists ops.export_requests (
  request_id   uuid primary key default gen_random_uuid(),
  customer_id  text not null,
  status       text not null default 'requested' check (status in ('requested', 'fulfilled', 'rejected')),
  requested_at timestamptz not null default now(),
  decided_by   text,
  decided_at   timestamptz,
  constraint decided_has_facts check (status = 'requested' or (decided_by is not null and decided_at is not null))
);

-- at most one open export request per customer
create unique index if not exists export_requests_one_open
  on ops.export_requests (customer_id) where status = 'requested';

create or replace function ops.export_requests_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' or tg_op = 'TRUNCATE' then
    raise exception 'ops.export_requests records are never deleted';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'requested' or new.decided_by is not null or new.decided_at is not null then
      raise exception 'an export request starts as requested, with no decision';
    end if;
    new.requested_at := now();
    return new;
  end if;
  -- UPDATE
  if old.request_id <> new.request_id or old.customer_id <> new.customer_id or old.requested_at <> new.requested_at then
    raise exception 'request id, customer and time cannot be changed';
  end if;
  if old.status <> 'requested' then
    raise exception 'a % export request is final', old.status;
  end if;
  if current_user = 'ops_writer' then
    raise exception 'ops_writer cannot decide an export request';
  end if;
  if new.status not in ('fulfilled', 'rejected') then
    raise exception 'an export request goes from requested to fulfilled or rejected';
  end if;
  if new.decided_by is null then
    raise exception 'a decision needs decided_by';
  end if;
  new.decided_at := now();
  return new;
end;
$$;

drop trigger if exists export_requests_row_guard on ops.export_requests;
create trigger export_requests_row_guard
  before insert or update or delete on ops.export_requests
  for each row execute function ops.export_requests_guard();

drop trigger if exists export_requests_no_truncate on ops.export_requests;
create trigger export_requests_no_truncate
  before truncate on ops.export_requests
  for each statement execute function ops.export_requests_guard();

-- the write login may create a request and read the list. It cannot change one.
revoke all on ops.export_requests from public, anon, authenticated;
revoke all on ops.export_requests from ops_writer;
grant select, insert on ops.export_requests to ops_writer;
