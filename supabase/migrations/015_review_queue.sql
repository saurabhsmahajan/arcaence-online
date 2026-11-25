-- 015: the review queue. Synthetic data only.
-- It holds two kinds of item: an answer a person should look at (a hostile message, an answer that
-- could not be verified) and an action an agent proposes but may not carry out (a refund, a cancellation).
-- The database enforces who may do what, so no service, script or agent can skip a step:
--
--   kind answer:           open -> resolved
--   kind proposed_action:  open -> approved | rejected
--
-- Nothing here runs an action. Approving a proposed action only records a person's decision.
-- The desk service will get a login that can add items and read them, never decide them.
-- Deciding is for a person, connected as the database owner through a separate script.

create schema if not exists ops;

create table if not exists ops.review_items (
  item_id       uuid primary key default gen_random_uuid(),
  case_id       text not null check (case_id ~ '^case_[0-9]{8}_[0-9a-f]{12}$'),
  kind          text not null check (kind in ('answer', 'proposed_action')),
  reason        text not null check (reason in ('hostile', 'verification_failed', 'proposed_action')),
  status        text not null default 'open'
                check (status in ('open', 'resolved', 'approved', 'rejected')),
  created_at    timestamptz not null default now(),
  question      text not null,
  summary       text not null,
  proposed      jsonb,
  decided_by    text,
  decided_at    timestamptz,
  decision_note text,
  -- an action item carries the action; an answer item does not
  constraint action_has_proposal check ((kind = 'proposed_action') = (proposed is not null)),
  constraint action_reason check ((kind = 'proposed_action') = (reason = 'proposed_action')),
  -- a state cannot exist without the facts that got it there
  constraint decided_has_facts check (status = 'open' or (decided_by is not null and decided_at is not null)),
  constraint open_has_no_decision check (status <> 'open' or (decided_by is null and decided_at is null))
);

create index if not exists review_items_status_idx on ops.review_items (status, created_at);
create index if not exists review_items_case_idx on ops.review_items (case_id);

-- one answer item per case, so a retry cannot fill the queue with copies
create unique index if not exists review_items_one_answer_per_case
  on ops.review_items (case_id) where kind = 'answer';

create or replace function ops.review_items_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' or tg_op = 'TRUNCATE' then
    raise exception 'ops.review_items records are never deleted';
  end if;

  if tg_op = 'INSERT' then
    if new.status <> 'open' then
      raise exception 'a review item starts as open';
    end if;
    if new.decided_by is not null or new.decided_at is not null or new.decision_note is not null then
      raise exception 'a new review item cannot carry decision data';
    end if;
    new.created_at := now();
    return new;
  end if;

  -- UPDATE: only the decision may change, and only once
  if old.item_id <> new.item_id or old.case_id <> new.case_id or old.kind <> new.kind
     or old.reason <> new.reason or old.created_at <> new.created_at
     or old.question <> new.question or old.summary <> new.summary
     or old.proposed is distinct from new.proposed then
    raise exception 'only the decision of a review item can change';
  end if;
  if old.status <> 'open' then
    raise exception 'a % review item is final', old.status;
  end if;
  if new.decided_by is null or length(trim(new.decided_by)) = 0 then
    raise exception 'a decision needs decided_by';
  end if;

  if old.kind = 'answer' and new.status = 'resolved' then
    null;
  elsif old.kind = 'proposed_action' and new.status in ('approved', 'rejected') then
    null;
  else
    raise exception 'a % item cannot go from % to %', old.kind, old.status, new.status;
  end if;

  new.decided_at := now();
  return new;
end;
$$;

drop trigger if exists review_items_row_guard on ops.review_items;
create trigger review_items_row_guard
  before insert or update or delete on ops.review_items
  for each row execute function ops.review_items_guard();

drop trigger if exists review_items_no_truncate on ops.review_items;
create trigger review_items_no_truncate
  before truncate on ops.review_items
  for each statement execute function ops.review_items_guard();

-- Only the owner touches this table for now. The desk service login is made with the service wrapper.
revoke all on ops.review_items from public, anon, authenticated;
