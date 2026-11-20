-- 006: row-level security policies. A customer reads only their own rows.
-- anon (not logged in) gets no table rights. Logged-in users get select only;
-- there is no insert, update or delete policy, so writes are denied.

-- Maps the logged-in user (from the signed token) to a customer id.
-- security definer so it can read customers, which is itself protected by RLS.
create or replace function public.current_customer_id()
returns text
language sql
stable
security definer
set search_path = public
as $$
  select customer_id from public.customers where auth_user_id = auth.uid()
$$;

revoke all on function public.current_customer_id() from public, anon;
grant execute on function public.current_customer_id() to authenticated;

revoke all on customers, orders, invoices from anon;
grant select on customers, orders, invoices to authenticated;

create policy customers_select_own on customers
  for select to authenticated
  using (customer_id = public.current_customer_id());

create policy orders_select_own on orders
  for select to authenticated
  using (customer_id = public.current_customer_id());

create policy invoices_select_own on invoices
  for select to authenticated
  using (customer_id = public.current_customer_id());
