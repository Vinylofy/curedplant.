-- Apply explicitly to the shared Vinylofy database. No production activation.
begin;
alter table public.product_cover_queue
  add column if not exists bol_checked_at timestamptz,
  add column if not exists bol_next_attempt_at timestamptz,
  add column if not exists bol_attempt_count integer not null default 0,
  add column if not exists bol_result jsonb;
alter table public.product_cover_candidates
  add column if not exists bol_evidence jsonb;

-- NULL executable URL is intentional: retry/recovery cannot fetch this image.
-- The external URL exists only in evidence until rights + publisher are reviewed.
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid = 'public.product_cover_candidates'::regclass
                 and conname = 'bol_cover_quarantine_chk') then
    alter table public.product_cover_candidates add constraint bol_cover_quarantine_chk check (
      source_type <> 'bol_affiliate' or (
        candidate_status = 'rejected' and is_selected = false and image_url is null
        and product_url is null and source_rank = 0 and bol_evidence is not null
      )
    );
  end if;
end $$;
create unique index if not exists bol_cover_product_unique
  on public.product_cover_candidates(product_id) where source_type = 'bol_affiliate';
create index if not exists bol_cover_due_idx
  on public.product_cover_queue(bol_next_attempt_at, created_at, product_id)
  where status in ('review','failed') and last_error_code = 'no_candidates';

-- Not an HTTP RPC permission: only a dedicated direct Postgres login may inherit
-- this NOLOGIN role. No membership, password or Supabase API grants are installed.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'bol_cover_worker') then
    create role bol_cover_worker nologin;
  end if;
end $$;
grant usage on schema public to bol_cover_worker;

create or replace function public.bol_cover_eligible(_id uuid) returns boolean
language sql stable security definer set search_path = pg_catalog, public as $$
  select exists (
    select 1 from public.products p join public.product_cover_queue q on q.product_id=p.id
    where p.id=_id and p.cover_status <> 'blocked'
      and nullif(btrim(p.cover_storage_path),'') is null
      and nullif(btrim(p.cover_url),'') is null
      and nullif(btrim(p.cover_source_url),'') is null
      and q.status in ('review','failed') and q.last_error_code='no_candidates'
      and not exists (select 1 from public.product_cover_candidates c where c.product_id=p.id
                      and c.source_type <> 'bol_affiliate' and c.candidate_status <> 'rejected')
  )
$$;

create or replace function public.bol_cover_next(_lane text, _lock boolean, _seen uuid[])
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare r record;
begin
  if _lane not in ('new','historical') then raise exception 'Invalid lane'; end if;
  -- Each committed row is its own checkpoint; positive and negative cache expiry
  -- are both durable. New queue arrivals do not wait for a catalogue cursor wrap.
  if _lock then
    select p.id,p.ean,p.format_label,p.gtin_normalized,p.title into r
    from public.product_cover_queue q join public.products p on p.id=q.product_id
    where public.bol_cover_eligible(p.id)
      and q.status in ('review','failed') and q.last_error_code='no_candidates'
      and not (p.id=any(coalesce(_seen,array[]::uuid[])))
      and (q.bol_next_attempt_at is null or q.bol_next_attempt_at <= now())
      and (q.created_at >= now()-interval '7 days') = (_lane='new')
    order by q.bol_checked_at asc nulls first, q.created_at desc, q.product_id
    limit 1 for update of q skip locked;
  else
    select p.id,p.ean,p.format_label,p.gtin_normalized,p.title into r
    from public.product_cover_queue q join public.products p on p.id=q.product_id
    where public.bol_cover_eligible(p.id)
      and q.status in ('review','failed') and q.last_error_code='no_candidates'
      and not (p.id=any(coalesce(_seen,array[]::uuid[])))
      and (q.bol_next_attempt_at is null or q.bol_next_attempt_at <= now())
      and (q.created_at >= now()-interval '7 days') = (_lane='new')
    order by q.bol_checked_at asc nulls first, q.created_at desc, q.product_id limit 1;
  end if;
  if r.id is null then return null; end if;
  return jsonb_build_object('id',r.id,'ean',r.ean,'format_label',r.format_label,
                           'gtin_normalized',r.gtin_normalized,'title',r.title);
end $$;

create or replace function public.bol_cover_record(_id uuid, _evidence jsonb)
returns integer language plpgsql security definer set search_path = pg_catalog, public as $$
declare registered boolean := false; attempts integer; delay interval; p public.products;
begin
  -- Row locking also coordinates with the private worker's SKIP LOCKED claims.
  perform 1 from public.product_cover_queue where product_id=_id for update;
  select * into p from public.products where id=_id for update;
  -- Use the freshly locked version too: a concurrent publisher may have
  -- committed after the outer statement's snapshot was taken.
  if nullif(btrim(p.cover_url),'') is not null
     or nullif(btrim(p.cover_storage_path),'') is not null
     or nullif(btrim(p.cover_source_url),'') is not null
     or p.cover_status='blocked' then return -1; end if;
  if not public.bol_cover_eligible(_id) then return -1; end if;
  if _evidence->>'source' is distinct from 'bol_affiliate'
     or _evidence->>'country' is distinct from 'NL'
     or _evidence->>'ean' is distinct from p.ean
     or _evidence->>'publication_eligible' is distinct from 'false'
     or _evidence->>'rights_status' is distinct from 'unconfirmed' then
    raise exception 'Invalid Bol evidence';
  end if;
  select bol_attempt_count+1 into attempts from public.product_cover_queue where product_id=_id;
  delay := case when _evidence->>'error_status'='api_failure'
    then make_interval(secs=>least(86400, 3600*power(2,least(attempts-1,5)))::integer)
    when _evidence->>'match_status'='exact_variant' then interval '30 days'
    else interval '7 days' end;
  update public.product_cover_queue set bol_checked_at=now(),bol_next_attempt_at=now()+delay,
    bol_attempt_count=attempts,bol_result=_evidence where product_id=_id;
  if _evidence->>'match_status'='exact_variant' then
    insert into public.product_cover_candidates
      (product_id,ean,source_type,source_rank,candidate_status,is_selected,
       image_url,product_url,last_error_code,bol_evidence)
    values (_id,p.ean,'bol_affiliate',0,'rejected',false,null,null,'bol_rights_unconfirmed',_evidence)
    on conflict (product_id) where source_type='bol_affiliate' do nothing;
    registered := found;
    -- Preserve rejection and operator decisions; refresh evidence only.
    update public.product_cover_candidates set bol_evidence=_evidence,last_checked_at=now()
      where product_id=_id and source_type='bol_affiliate';
  end if;
  return case when registered then 1 else 0 end;
end $$;

create or replace function public.bol_cover_counts() returns jsonb
language sql stable security definer set search_path = pg_catalog, public as $$
  with eligible as materialized (
    select q.created_at,q.bol_checked_at from public.product_cover_queue q
    where q.status in ('review','failed') and q.last_error_code='no_candidates'
      and public.bol_cover_eligible(q.product_id)
  )
  select jsonb_build_object(
    'missing_covers',(select count(*) from public.products p where nullif(btrim(p.cover_url),'') is null
                                       and nullif(btrim(p.cover_storage_path),'') is null),
    'eligible',count(*),
    'historical_unchecked',count(*) filter (where created_at < now()-interval '7 days' and bol_checked_at is null),
    'new_unchecked',count(*) filter (where created_at >= now()-interval '7 days' and bol_checked_at is null),
    'checked',(select count(*) from public.product_cover_queue where bol_checked_at is not null))
  from eligible
$$;

revoke all on function public.bol_cover_eligible(uuid) from public;
revoke all on function public.bol_cover_next(text,boolean,uuid[]) from public;
revoke all on function public.bol_cover_record(uuid,jsonb) from public;
revoke all on function public.bol_cover_counts() from public;
-- Supabase installations can have explicit default grants as well as PUBLIC.
do $$ declare r text; f text; begin
  foreach r in array array['anon','authenticated','service_role'] loop
    if exists (select 1 from pg_roles where rolname=r) then
      foreach f in array array['bol_cover_eligible(uuid)','bol_cover_next(text,boolean,uuid[])',
                              'bol_cover_record(uuid,jsonb)','bol_cover_counts()'] loop
        execute format('revoke all on function public.%s from %I',f,r);
      end loop;
    end if;
  end loop;
end $$;
grant execute on function public.bol_cover_next(text,boolean,uuid[]),
  public.bol_cover_record(uuid,jsonb),public.bol_cover_counts() to bol_cover_worker;
commit;
