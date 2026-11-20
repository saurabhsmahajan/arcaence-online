-- 004: shared customer tables (customers, orders, invoices) with synthetic data.
-- All data below is invented. Row-level security is switched on with no policies,
-- so the API can read nothing until migration 005 grants access on purpose.

create table customers (
  customer_id   text primary key,
  display_name  text not null,
  plan          text not null check (plan in ('Starter', 'Pro', 'Team')),
  billing       text not null check (billing in ('monthly', 'annual')),
  currency      text not null check (currency in ('EUR', 'USD', 'INR')),
  status        text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  auth_user_id  uuid unique references auth.users (id) on delete set null,
  created_at    timestamptz not null default now()
);

create table orders (
  order_id      text primary key,
  customer_id   text not null references customers (customer_id),
  item          text not null,
  kind          text not null check (kind in ('one_off', 'subscription')),
  amount        numeric(10, 2) not null,
  currency      text not null check (currency in ('EUR', 'USD', 'INR')),
  purchased_at  date not null,
  downloaded    boolean not null default false
);

-- customer_id is repeated here on purpose: one-column ownership keeps the
-- row-level security rule a single comparison with no join.
create table invoices (
  invoice_id    text primary key,
  order_id      text not null references orders (order_id),
  customer_id   text not null references customers (customer_id),
  amount        numeric(10, 2) not null,
  currency      text not null check (currency in ('EUR', 'USD', 'INR')),
  issued_on     date not null
);

create index orders_customer_idx on orders (customer_id);
create index invoices_customer_idx on invoices (customer_id);

insert into customers (customer_id, display_name, plan, billing, currency) values
  ('cust_001', 'Customer One (synthetic)', 'Pro', 'monthly', 'EUR'),
  ('cust_002', 'Customer Two (synthetic)', 'Team', 'annual', 'USD');

insert into orders (order_id, customer_id, item, kind, amount, currency, purchased_at, downloaded) values
  ('ord_1001', 'cust_001', 'Pro plan, monthly', 'subscription', 19.00, 'EUR', '2026-11-01', false),
  ('ord_1002', 'cust_001', 'Course: Support Desk Basics', 'one_off', 49.00, 'EUR', '2026-10-31', true),
  ('ord_2001', 'cust_002', 'Team plan, annual', 'subscription', 540.00, 'USD', '2026-09-15', false);

insert into invoices (invoice_id, order_id, customer_id, amount, currency, issued_on) values
  ('inv_1001', 'ord_1001', 'cust_001', 19.00, 'EUR', '2026-11-01'),
  ('inv_1002', 'ord_1002', 'cust_001', 49.00, 'EUR', '2026-10-31'),
  ('inv_2001', 'ord_2001', 'cust_002', 540.00, 'USD', '2026-09-15');

alter table customers enable row level security;
alter table orders enable row level security;
alter table invoices enable row level security;
