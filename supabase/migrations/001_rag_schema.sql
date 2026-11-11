create extension if not exists vector;

create table documents (
  doc_id          text primary key,
  filename        text not null,
  source_type     text not null check (source_type in
                    ('official','superseded','email','meeting_notes','draft','spreadsheet','scan','photo')),
  file_format     text not null,
  version         text,
  status          text not null check (status in ('approved','superseded','draft','informal')),
  authority_rank  int  not null,
  effective_date  date,
  created_at      timestamptz not null default now()
);

create table clause_registry (
  clause_id    text not null,
  doc_id       text not null references documents(doc_id),
  section_ref  text not null,
  topic        text,
  primary key (clause_id, doc_id)
);

create table chunks (
  chunk_id     bigserial primary key,
  doc_id       text not null references documents(doc_id),
  chunk_index  int  not null,
  content      text not null,
  section_ref  text,
  page         int,
  clause_id    text,
  is_ocr       boolean not null default false,
  embedding    vector(384),
  created_at   timestamptz not null default now(),
  unique (doc_id, chunk_index)
);

create index chunks_doc_idx on chunks (doc_id);
create index chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);

create table plans_fees (
  plan      text not null,
  billing   text not null check (billing in ('monthly','annual')),
  currency  text not null check (currency in ('EUR','USD','INR')),
  price     numeric not null,
  source    text not null default 'Schedule A (official v3.0)',
  primary key (plan, billing, currency)
);

insert into plans_fees (plan, billing, currency, price) values
  ('Starter','monthly','EUR',9),   ('Starter','monthly','USD',10),   ('Starter','monthly','INR',799),
  ('Pro','monthly','EUR',19),      ('Pro','monthly','USD',21),       ('Pro','monthly','INR',1699),
  ('Team','monthly','EUR',49),     ('Team','monthly','USD',54),      ('Team','monthly','INR',4299),
  ('Extra seat','monthly','EUR',5),('Extra seat','monthly','USD',6), ('Extra seat','monthly','INR',449);

insert into plans_fees (plan, billing, currency, price)
  select plan, 'annual', currency, price * 10
  from plans_fees
  where billing = 'monthly' and plan in ('Starter','Pro','Team');

alter table documents       enable row level security;
alter table clause_registry enable row level security;
alter table chunks          enable row level security;
alter table plans_fees      enable row level security;