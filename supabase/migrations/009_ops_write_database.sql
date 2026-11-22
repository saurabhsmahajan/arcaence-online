-- 009: server-owned write database for the MCP write tools, and the ops_writer login.
-- Synthetic data only. No password is set here: set it yourself, outside git.

-- 1. A schema that only the MCP server's write login can use. It is not in the API's exposed schemas.
create schema if not exists ops;
revoke all on schema ops from public, anon, authenticated;

-- 2. The audit log: every attempt, allowed or refused. No personal contact data goes in here.
create table if not exists ops.audit_log (
  audit_id    bigserial primary key,
  at          timestamptz not null default now(),
  server_role text not null,
  tool        text not null,
  mode        text not null check (mode in ('dry_run', 'commit')),
  outcome     text not null check (outcome in ('allowed', 'refused', 'error')),
  reason      text,
  customer_id text,
  order_id    text,
  amount      numeric(12, 2),
  currency    text,
  clause_id   text,
  args        jsonb
);

-- 3. What the write tools actually did. Every action names the clause that allows it.
create table if not exists ops.refunds (
  refund_id   uuid primary key default gen_random_uuid(),
  at          timestamptz not null default now(),
  order_id    text not null,
  customer_id text not null,
  amount      numeric(12, 2) not null check (amount > 0),
  currency    text not null check (currency in ('EUR', 'USD', 'INR')),
  clause_doc  text not null,
  clause_id   text not null,
  reason      text
);
create index if not exists refunds_customer_idx on ops.refunds (customer_id);
create index if not exists refunds_order_idx on ops.refunds (order_id);

create table if not exists ops.cancellations (
  cancellation_id uuid primary key default gen_random_uuid(),
  at              timestamptz not null default now(),
  customer_id     text not null,
  order_id        text,
  clause_doc      text not null,
  clause_id       text not null,
  reason          text
);
create index if not exists cancellations_customer_idx on ops.cancellations (customer_id);

-- 4. Single-use confirmation tokens. Only a hash is stored, never the token itself.
create table if not exists ops.confirm_tokens (
  token_hash text primary key,
  tool       text not null,
  args_hash  text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  used_at    timestamptz
);

-- 5. The audit log can only grow: a trigger stops update, delete and truncate, even for the owner role.
create or replace function ops.audit_log_no_change() returns trigger
language plpgsql as $$
begin
  raise exception 'ops.audit_log is append-only';
end;
$$;

drop trigger if exists audit_log_no_row_change on ops.audit_log;
create trigger audit_log_no_row_change
  before update or delete on ops.audit_log
  for each row execute function ops.audit_log_no_change();

drop trigger if exists audit_log_no_truncate on ops.audit_log;
create trigger audit_log_no_truncate
  before truncate on ops.audit_log
  for each statement execute function ops.audit_log_no_change();

-- 6. The login (no password yet)
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ops_writer') then
    create role ops_writer login;
  end if;
end
$$;

alter role ops_writer set statement_timeout = '5s';

-- 7. Grants: only what the write tools need, and no more
grant usage on schema ops to ops_writer;
grant usage on schema public to ops_writer;
revoke all on all tables in schema public from ops_writer;
revoke all on all tables in schema ops from ops_writer;

-- reads from the customer tables, without the contact columns
grant select (customer_id, display_name, plan, billing, currency, status, created_at) on customers to ops_writer;
grant select on orders, invoices to ops_writer;

-- writes only into the server-owned schema
grant select, insert on ops.audit_log, ops.refunds, ops.cancellations, ops.confirm_tokens to ops_writer;
grant update (used_at) on ops.confirm_tokens to ops_writer;
grant usage, select on sequence ops.audit_log_audit_id_seq to ops_writer;

-- 8. Row-level security still applies to the customer tables: one select policy each for this role
drop policy if exists ops_writer_select_customers on customers;
drop policy if exists ops_writer_select_orders on orders;
drop policy if exists ops_writer_select_invoices on invoices;

create policy ops_writer_select_customers on customers for select to ops_writer using (true);
create policy ops_writer_select_orders on orders for select to ops_writer using (true);
create policy ops_writer_select_invoices on invoices for select to ops_writer using (true);
