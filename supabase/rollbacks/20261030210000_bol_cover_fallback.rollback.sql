-- Retire discovery privileges without deleting evidence or weakening quarantine.
-- First set BOL_COVER_FALLBACK_ENABLED=false and wait for active runs to finish.
begin;
revoke execute on function public.bol_cover_next(text,boolean,uuid[]),
  public.bol_cover_record(uuid,jsonb),public.bol_cover_counts() from bol_cover_worker;
-- Keep additive columns, evidence, unique index and quarantine constraint.
-- Do not drop the constraint while rejected Bol candidates still exist.
commit;
