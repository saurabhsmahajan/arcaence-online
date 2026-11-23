-- 013: policy_reader, the login of the second MCP server (policy_mcp). Synthetic data only.
-- No password is set here: set it yourself, outside git.
-- This login can do exactly one thing: call public.search_policy(). It has no table rights at all,
-- so it cannot read customer data, the ops schema or the knowledge tables directly.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'policy_reader') then
    create role policy_reader login;
  end if;
end
$$;

-- every session of this login is read-only and short-lived, whatever the client asks for
alter role policy_reader set default_transaction_read_only = on;
alter role policy_reader set statement_timeout = '5s';

grant usage on schema public to policy_reader;
revoke all on all tables in schema public from policy_reader;
revoke all on all functions in schema public from policy_reader;
revoke all on schema ops from policy_reader;

-- the one door
grant execute on function public.search_policy(vector, int) to policy_reader;
