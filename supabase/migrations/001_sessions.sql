-- Apply once in a NEW Supabase project via SQL Editor. No browser access to state.
begin;
create table public.rally_sessions (
    id text primary key,
    revision bigint not null check (revision > 0),
    body jsonb not null,
    updated_at timestamptz not null default now(),
    constraint body_identity check (jsonb_typeof(body) = 'object' and body ? 'id'
        and body ? 'revision' and body->>'id' = id and (body->>'revision')::bigint = revision)
);
alter table public.rally_sessions enable row level security;
revoke all on public.rally_sessions from public, anon, authenticated;
grant select, insert, update on public.rally_sessions to service_role;

-- Atomic compare-and-swap: a stale writer cannot overwrite a newer snapshot.
create function public.rally_save_session(p_body jsonb, p_expected_revision bigint)
returns boolean
language plpgsql security invoker
set search_path = ''
as $$
begin
    if p_expected_revision < 0 or p_expected_revision is null
       or jsonb_typeof(p_body) is distinct from 'object'
       or jsonb_typeof(p_body->'id') is distinct from 'string'
       or jsonb_typeof(p_body->'revision') is distinct from 'number'
       or (p_body->>'revision')::bigint is distinct from p_expected_revision + 1 then
        raise exception 'Invalid session revision';
    end if;
    if p_expected_revision = 0 then
        insert into public.rally_sessions (id,revision,body)
        values (p_body->>'id',1,p_body)
        on conflict (id) do nothing;
    else
        update public.rally_sessions
        set body=p_body, revision=p_expected_revision+1, updated_at=now()
        where id=p_body->>'id' and revision=p_expected_revision;
    end if;
    return found;
end;
$$;
revoke all on function public.rally_save_session(jsonb,bigint) from public, anon, authenticated;
grant execute on function public.rally_save_session(jsonb,bigint) to service_role;
commit;
