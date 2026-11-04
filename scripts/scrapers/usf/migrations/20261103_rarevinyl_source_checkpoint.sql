-- Source-only checkpoint. No product, price, release or matching writes.
begin;
set local lock_timeout='3s';
create table if not exists public.rarevinyl_source_checkpoint (
  name text primary key,
  next_page integer not null check(next_page>0),
  cycle_complete boolean not null default false,
  last_page_signature text,
  updated_at timestamptz not null default now()
);
alter table public.rarevinyl_source_checkpoint enable row level security;
revoke all on public.rarevinyl_source_checkpoint from public, anon, authenticated;
grant select, insert, update on public.rarevinyl_source_checkpoint to service_role;
commit;
