-- 008: read-only role for the MCP server, plus synthetic contact data to mask.
-- Synthetic data only. No password is set here: set it yourself, outside git.

-- 1. Contact columns so PII masking has something to mask
alter table customers add column if not exists email text;
alter table customers add column if not exists phone text;

update customers set email = 'anna.keller@example.com', phone = '+00 5550 1001' where customer_id = 'cust_001';
update customers set email = 'brian.otieno@example.com', phone = '+00 5550 1002' where customer_id = 'cust_002';

-- 2. The login role (no password yet)
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ops_reader') then
    create role ops_reader login;
  end if;
end
$$;

-- Every session of this role is read-only and short-lived, whatever the client asks for
alter role ops_reader set default_transaction_read_only = on;
alter role ops_reader set statement_timeout = '5s';

-- 3. Grants: select on three tables, nothing else
grant usage on schema public to ops_reader;
revoke all on all tables in schema public from ops_reader;
grant select on customers, orders, invoices to ops_reader;

-- 4. RLS: the desk reads any customer, but only through these three tables
drop policy if exists ops_reader_select_customers on customers;
drop policy if exists ops_reader_select_orders on orders;
drop policy if exists ops_reader_select_invoices on invoices;

create policy ops_reader_select_customers on customers for select to ops_reader using (true);
create policy ops_reader_select_orders on orders for select to ops_reader using (true);
create policy ops_reader_select_invoices on invoices for select to ops_reader using (true);
