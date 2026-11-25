-- 016: desk_service, the login the desk service uses. Synthetic data only.
-- No password is set here: set it yourself, outside git.
-- It can read the knowledge tables, call search_policy(), add review queue items and read them.
-- It cannot decide an item (no update, no delete), cannot read customer data, the audit log or any
-- other ops table, and cannot write the knowledge tables. Deciding an item is for a person, connected
-- as the database owner through a separate script. The owner login never goes into the service.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'desk_service') then
    create role desk_service login;
  end if;
end
$$;

alter role desk_service set statement_timeout = '10s';

grant usage on schema public to desk_service;
revoke all on all tables in schema public from desk_service;
revoke all on all functions in schema public from desk_service;
revoke all on schema ops from desk_service;

-- read access to the knowledge tables (row level security is on, so each needs a policy)
grant select on documents, chunks, clause_registry, plans_fees to desk_service;

drop policy if exists desk_service_read on documents;
drop policy if exists desk_service_read on chunks;
drop policy if exists desk_service_read on clause_registry;
drop policy if exists desk_service_read on plans_fees;
create policy desk_service_read on documents       for select to desk_service using (true);
create policy desk_service_read on chunks          for select to desk_service using (true);
create policy desk_service_read on clause_registry for select to desk_service using (true);
create policy desk_service_read on plans_fees      for select to desk_service using (true);

-- the guarded door
grant execute on function public.search_policy(vector, int) to desk_service;

-- the review queue: add and read, never decide
grant usage on schema ops to desk_service;
revoke all on ops.review_items from desk_service;
grant select, insert on ops.review_items to desk_service;
