-- Run after the migration in SQL Editor or psql as the project owner.
-- All test data is rolled back. A failure aborts the transaction.
begin;
do $test$
begin
    if has_table_privilege('anon','public.rally_sessions','select')
       or has_table_privilege('authenticated','public.rally_sessions','select')
       or has_function_privilege('anon','public.rally_save_session(jsonb,bigint)','execute')
       or has_function_privilege('authenticated','public.rally_save_session(jsonb,bigint)','execute') then
        raise exception 'Client roles must not access session state or RPC';
    end if;
    if not (select relrowsecurity from pg_class where oid='public.rally_sessions'::regclass) then
        raise exception 'RLS must be enabled';
    end if;
end;
$test$;
set local role service_role;
do $test$
declare
    sid text := 'sql-contract-' || gen_random_uuid()::text;
    first jsonb;
    second jsonb;
begin
    first := jsonb_build_object('id',sid,'revision',1);
    second := jsonb_build_object('id',sid,'revision',2);
    if not public.rally_save_session(first,0) then raise exception 'Insert failed'; end if;
    if public.rally_save_session(first,0) then raise exception 'Duplicate create succeeded'; end if;
    if not public.rally_save_session(second,1) then raise exception 'CAS update failed'; end if;
    if public.rally_save_session(second,1) then raise exception 'Stale write succeeded'; end if;
    if (select revision from public.rally_sessions where id=sid) <> 2 then
        raise exception 'Winner was not preserved';
    end if;
end;
$test$;
reset role;
set local role anon;
do $test$
begin
    begin
        perform 1 from public.rally_sessions limit 1;
        raise exception 'Anonymous read unexpectedly succeeded';
    exception when insufficient_privilege then null;
    end;
    begin
        perform public.rally_save_session('{"id":"denied","revision":1}'::jsonb,0);
        raise exception 'Anonymous write unexpectedly succeeded';
    exception when insufficient_privilege then null;
    end;
end;
$test$;
reset role;
rollback;
