-- 007: search_policy(), the single guarded door to the policy knowledge.
-- The status filter and the authority tiebreak live here, once. Callers cannot skip
-- them: there is no parameter to turn the filter off, and the knowledge tables are
-- closed to the API roles, so the function is the only way in.

create or replace function public.search_policy(
  query_embedding vector(384),
  match_count int default 8
)
returns table (
  doc_id text,
  clause_id text,
  status text,
  content text,
  score double precision
)
language sql
stable
security definer
set search_path = public
as $$
  select c.doc_id, c.clause_id, d.status, c.content,
         1 - (c.embedding <=> query_embedding) as score
  from chunks c
  join documents d on d.doc_id = c.doc_id
  where d.status = 'approved'
  order by c.embedding <=> query_embedding, d.authority_rank
  limit least(greatest(match_count, 1), 50)
$$;

revoke all on function public.search_policy(vector, int) from public, anon;
grant execute on function public.search_policy(vector, int) to authenticated, service_role;

-- Close the knowledge tables to the API roles. Deny by default: RLS on, no policies,
-- no direct rights. The database owner (used by ingestion, the scorer and the
-- evaluation-only unfiltered path) bypasses RLS and is not affected.
alter table documents enable row level security;
alter table chunks enable row level security;
alter table clause_registry enable row level security;
alter table plans_fees enable row level security;

revoke all on documents, chunks, clause_registry, plans_fees from anon, authenticated;
