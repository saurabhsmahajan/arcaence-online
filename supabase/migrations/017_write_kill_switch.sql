-- 017: the kill switch for write tools. Synthetic data only.
-- One flag, ops.system_flags 'writes'. While it is not exactly 'on', the database refuses every change to the
-- tables that hold money and customer-data requests: refunds, cancellations, deletion requests and export
-- requests. The check is in a trigger, so it covers every path (the MCP server, the desk's local tools, a script)
-- and it is read on every statement, so flipping it needs no restart.
--
-- Fails closed: a missing row, a missing table row or any other value means writes are OFF.
-- Left open on purpose: reads, dry runs, the audit log and the review queue. A person must still be able to see
-- what happened and what is waiting while writes are off.
-- Only the database owner can change the flag (a person, with a reason). The service logins cannot even read it.

create table if not exists ops.system_flags (
  name       text primary key check (name in ('writes')),
  value      text not null check (value in ('on', 'off')),
  reason     text,
  changed_by text not null default current_user,
  changed_at timestamptz not null default now()
);

create table if not exists ops.system_flag_history (
  id         bigserial primary key,
  name       text not null,
  old_value  text,
  new_value  text,
  reason     text,
  changed_by text not null,
  changed_at timestamptz not null default now()
);

create or replace function ops.log_system_flag() returns trigger
language plpgsql as $$
begin
  insert into ops.system_flag_history (name, old_value, new_value, reason, changed_by)
  values (coalesce(new.name, old.name),
          case when tg_op = 'INSERT' then null else old.value end,
          case when tg_op = 'DELETE' then null else new.value end,
          case when tg_op = 'DELETE' then 'flag row deleted' else new.reason end,
          current_user);
  return coalesce(new, old);
end;
$$;

drop trigger if exists system_flags_history on ops.system_flags;
create trigger system_flags_history
  after insert or update or delete on ops.system_flags
  for each row execute function ops.log_system_flag();

-- true only when the row exists and says 'on'. Security definer, so the service logins need no access to the table.
create or replace function ops.writes_enabled() returns boolean
language sql stable security definer set search_path = pg_catalog, ops
as $$
  select coalesce((select value = 'on' from ops.system_flags where name = 'writes'), false)
$$;

create or replace function ops.block_writes_when_off() returns trigger
language plpgsql as $$
begin
  if not ops.writes_enabled() then
    -- sqlstate 55000 (object_not_in_prerequisite_state) so callers can tell this apart from a bug
    raise exception 'writes_disabled' using errcode = '55000', hint = 'the write kill switch is off';
  end if;
  return null;
end;
$$;

-- Statement level, so it fires before any row is looked at, before constraints and before the other guards.
drop trigger if exists kill_switch on ops.refunds;
create trigger kill_switch before insert or update or delete or truncate on ops.refunds
  for each statement execute function ops.block_writes_when_off();

drop trigger if exists kill_switch on ops.cancellations;
create trigger kill_switch before insert or update or delete or truncate on ops.cancellations
  for each statement execute function ops.block_writes_when_off();

drop trigger if exists kill_switch on ops.deletion_requests;
create trigger kill_switch before insert or update or delete or truncate on ops.deletion_requests
  for each statement execute function ops.block_writes_when_off();

drop trigger if exists kill_switch on ops.export_requests;
create trigger kill_switch before insert or update or delete or truncate on ops.export_requests
  for each statement execute function ops.block_writes_when_off();

-- Nobody but the owner touches the flag or its history.
revoke all on ops.system_flags, ops.system_flag_history from public, anon, authenticated, service_role;
do $$
declare r text;
begin
  foreach r in array array['ops_writer', 'ops_reader', 'desk_service', 'ci_eval', 'policy_reader'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on ops.system_flags, ops.system_flag_history from %I', r);
    end if;
  end loop;
end
$$;

-- Writes start ON, so applying this migration changes nothing until a person flips it.
insert into ops.system_flags (name, value, reason, changed_by)
values ('writes', 'on', 'initial state', 'migration 017')
on conflict (name) do nothing;
