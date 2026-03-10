-- >>> BEGIN JO_AI_TRACKING_SCHEMA
-- JO AI Supabase tracking schema (idempotent reconciliation script).
-- Safe to run multiple times in Supabase SQL Editor.

create table if not exists public.users (
  telegram_id bigint primary key,
  username text,
  first_name text,
  last_name text,
  first_seen_at timestamptz not null default timezone('utc', now()),
  last_seen_at timestamptz not null default timezone('utc', now()),
  total_messages integer not null default 0 check (total_messages >= 0),
  total_images integer not null default 0 check (total_images >= 0)
);

alter table public.users
  add column if not exists telegram_id bigint,
  add column if not exists username text,
  add column if not exists first_name text,
  add column if not exists last_name text,
  add column if not exists first_seen_at timestamptz,
  add column if not exists last_seen_at timestamptz,
  add column if not exists total_messages integer,
  add column if not exists total_images integer;

update public.users
set
  first_seen_at = coalesce(first_seen_at, timezone('utc', now())),
  last_seen_at = coalesce(last_seen_at, timezone('utc', now())),
  total_messages = greatest(0, coalesce(total_messages, 0)),
  total_images = greatest(0, coalesce(total_images, 0));

alter table public.users
  alter column telegram_id set not null,
  alter column first_seen_at set default timezone('utc', now()),
  alter column first_seen_at set not null,
  alter column last_seen_at set default timezone('utc', now()),
  alter column last_seen_at set not null,
  alter column total_messages set default 0,
  alter column total_messages set not null,
  alter column total_images set default 0,
  alter column total_images set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_pkey'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users add constraint users_pkey primary key (telegram_id);
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_total_messages_check'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_total_messages_check check (total_messages >= 0);
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_total_images_check'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_total_images_check check (total_images >= 0);
  end if;
end;
$$;

create table if not exists public.history (
  id bigint generated always as identity primary key,
  telegram_id bigint not null references public.users(telegram_id) on delete cascade,
  message_type text not null,
  user_message text,
  bot_reply text,
  model_used text,
  success boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

alter table public.history
  add column if not exists id bigint,
  add column if not exists telegram_id bigint,
  add column if not exists message_type text,
  add column if not exists user_message text,
  add column if not exists bot_reply text,
  add column if not exists model_used text,
  add column if not exists success boolean,
  add column if not exists created_at timestamptz;

update public.history
set
  message_type = coalesce(message_type, 'unknown'),
  success = coalesce(success, false),
  created_at = coalesce(created_at, timezone('utc', now()));

alter table public.history
  alter column telegram_id set not null,
  alter column message_type set not null,
  alter column success set default false,
  alter column success set not null,
  alter column created_at set default timezone('utc', now()),
  alter column created_at set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'history_telegram_id_fkey'
      and conrelid = 'public.history'::regclass
  ) then
    alter table public.history
      add constraint history_telegram_id_fkey
      foreign key (telegram_id)
      references public.users(telegram_id)
      on delete cascade
      not valid;
  end if;
end;
$$;

create index if not exists idx_history_telegram_created_at
  on public.history (telegram_id, created_at desc);

create index if not exists idx_history_message_type
  on public.history (message_type);

-- Grants for server-side tracking when using service_role.
grant usage on schema public to service_role;
grant select, insert, update on public.users to service_role;
grant select, insert, update on public.history to service_role;

-- <<< END JO_AI_TRACKING_SCHEMA
