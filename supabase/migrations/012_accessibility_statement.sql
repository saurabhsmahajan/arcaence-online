-- 012: accessibility_statement(), one narrow door for the accessibility read tool.
-- It returns the approved accessibility clause (tos_v3 6.4) and nothing else. It takes no arguments,
-- so a caller cannot ask it for any other clause, and it reads only approved documents.
-- Same pattern as search_policy() in 007: the knowledge tables stay closed, this function is the way in.

create or replace function public.accessibility_statement()
returns table (doc_id text, clause_id text, content text)
language sql
stable
security definer
set search_path = public
as $$
  select c.doc_id, c.clause_id, c.content
  from chunks c
  join documents d on d.doc_id = c.doc_id
  where d.status = 'approved'
    and c.doc_id = 'tos_v3'
    and c.clause_id = '6.4'
$$;

revoke all on function public.accessibility_statement() from public, anon, authenticated;
grant execute on function public.accessibility_statement() to ops_reader, service_role;
