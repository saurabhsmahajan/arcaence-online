-- 014: ci_eval, the login GitHub Actions uses to run the evaluation gate. Synthetic data only.
-- No password is set here: set it yourself, outside git.
-- It can read the four knowledge tables and call search_policy(), nothing else. It cannot
-- write, cannot read customer data or the ops schema, and every session is read-only
-- and short-lived. The database owner login never goes into GitHub.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ci_eval') then
    create role ci_eval login;
  end if;
end
$$;

alter role ci_eval set default_transaction_read_only = on;
alter role ci_eval set statement_timeout = '15s';

grant usage on schema public to ci_eval;
revoke all on all tables in schema public from ci_eval;
revoke all on all functions in schema public from ci_eval;
revoke all on schema ops from ci_eval;

-- read access to the knowledge tables (these have row level security on, so each needs a policy)
grant select on documents, chunks, clause_registry, plans_fees to ci_eval;

drop policy if exists ci_eval_read on documents;
drop policy if exists ci_eval_read on chunks;
drop policy if exists ci_eval_read on clause_registry;
drop policy if exists ci_eval_read on plans_fees;
create policy ci_eval_read on documents       for select to ci_eval using (true);
create policy ci_eval_read on chunks          for select to ci_eval using (true);
create policy ci_eval_read on clause_registry for select to ci_eval using (true);
create policy ci_eval_read on plans_fees      for select to ci_eval using (true);

-- the guarded door
grant execute on function public.search_policy(vector, int) to ci_eval;
