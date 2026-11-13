-- 002: record "not offered" cells from Schedule A as explicit rows.
-- A price table has cells that hold a fact but no number ("not offered on annual billing").
-- Without a row for them the fact is lost when the table becomes rows.

alter table plans_fees add column if not exists note text;
alter table plans_fees alter column price drop not null;

alter table plans_fees drop constraint if exists plans_fees_price_or_note;
alter table plans_fees add constraint plans_fees_price_or_note
  check (price is not null or note is not null);

insert into plans_fees (plan, billing, currency, price, note) values
  ('Extra seat','annual','EUR',null,'not offered on annual billing'),
  ('Extra seat','annual','USD',null,'not offered on annual billing'),
  ('Extra seat','annual','INR',null,'not offered on annual billing')
on conflict (plan, billing, currency) do nothing;
