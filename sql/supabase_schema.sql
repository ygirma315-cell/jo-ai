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

alter table public.users
  add column if not exists has_started boolean,
  add column if not exists started_at timestamptz,
  add column if not exists is_active boolean,
  add column if not exists status text,
  add column if not exists is_blocked boolean,
  add column if not exists blocked_at timestamptz,
  add column if not exists unreachable_count integer,
  add column if not exists last_delivery_error text,
  add column if not exists last_frontend_source text,
  add column if not exists started_via_referral text,
  add column if not exists referral_code text,
  add column if not exists referred_by bigint,
  add column if not exists last_engagement_sent_at timestamptz,
  add column if not exists engagement_count integer;

update public.users
set
  has_started = coalesce(has_started, false),
  is_active = coalesce(is_active, true),
  status = coalesce(nullif(status, ''), case when coalesce(is_blocked, false) then 'blocked' else 'active' end),
  is_blocked = coalesce(is_blocked, false),
  unreachable_count = greatest(0, coalesce(unreachable_count, 0)),
  engagement_count = greatest(0, coalesce(engagement_count, 0));

alter table public.users
  alter column has_started set default false,
  alter column has_started set not null,
  alter column is_active set default true,
  alter column is_active set not null,
  alter column status set default 'active',
  alter column status set not null,
  alter column is_blocked set default false,
  alter column is_blocked set not null,
  alter column unreachable_count set default 0,
  alter column unreachable_count set not null,
  alter column engagement_count set default 0,
  alter column engagement_count set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_unreachable_count_check'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_unreachable_count_check check (unreachable_count >= 0);
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_engagement_count_check'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_engagement_count_check check (engagement_count >= 0);
  end if;
end;
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_referred_by_fkey'
      and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_referred_by_fkey
      foreign key (referred_by)
      references public.users(telegram_id)
      on delete set null
      not valid;
  end if;
end;
$$;

create unique index if not exists idx_users_referral_code_unique
  on public.users (referral_code)
  where referral_code is not null;

create index if not exists idx_users_status_last_seen
  on public.users (status, last_seen_at desc);

create index if not exists idx_users_last_engagement_sent_at
  on public.users (last_engagement_sent_at);

alter table public.history
  add column if not exists frontend_source text,
  add column if not exists feature_used text,
  add column if not exists conversation_id text,
  add column if not exists text_content text,
  add column if not exists media_type text,
  add column if not exists media_url text,
  add column if not exists storage_path text,
  add column if not exists mime_type text,
  add column if not exists media_width integer,
  add column if not exists media_height integer,
  add column if not exists provider_source text,
  add column if not exists media_origin text,
  add column if not exists media_status text,
  add column if not exists media_error_reason text;

update public.history
set
  frontend_source = coalesce(nullif(frontend_source, ''), 'unknown'),
  feature_used = coalesce(nullif(feature_used, ''), message_type),
  conversation_id = coalesce(nullif(conversation_id, ''), concat(telegram_id::text, ':', coalesce(message_type, 'unknown'))),
  text_content = coalesce(text_content, user_message);

alter table public.history
  alter column frontend_source set default 'unknown',
  alter column frontend_source set not null;

create index if not exists idx_history_frontend_source
  on public.history (frontend_source, created_at desc);

create index if not exists idx_history_feature_used
  on public.history (feature_used, created_at desc);

create index if not exists idx_history_conversation_id
  on public.history (conversation_id, created_at desc);

create index if not exists idx_history_media_type_created_at
  on public.history (media_type, created_at desc);

create table if not exists public.referrals (
  id bigint generated always as identity primary key,
  referral_code text not null,
  inviter_telegram_id bigint not null references public.users(telegram_id) on delete cascade,
  invitee_telegram_id bigint not null references public.users(telegram_id) on delete cascade,
  frontend_source text,
  created_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists idx_referrals_invitee_unique
  on public.referrals (invitee_telegram_id);

create index if not exists idx_referrals_inviter_created_at
  on public.referrals (inviter_telegram_id, created_at desc);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'referrals_no_self_referral_check'
      and conrelid = 'public.referrals'::regclass
  ) then
    alter table public.referrals
      add constraint referrals_no_self_referral_check
      check (inviter_telegram_id <> invitee_telegram_id);
  end if;
end;
$$;

create table if not exists public.admin_config (
  config_key text primary key,
  value_json jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default timezone('utc', now())
);

insert into public.admin_config (config_key, value_json)
values
  (
    'engagement',
    jsonb_build_object(
      'enabled', true,
      'message_template', 'What do you want to do with your chat bot today?',
      'inactivity_minutes', 240,
      'cooldown_minutes', 720,
      'batch_size', 30
    )
  )
on conflict (config_key) do nothing;

-- Grants for server-side tracking when using service_role.
grant usage on schema public to service_role;
grant select, insert, update on public.users to service_role;
grant select, insert, update on public.history to service_role;
grant select, insert, update on public.referrals to service_role;
grant select, insert, update on public.admin_config to service_role;

-- <<< END JO_AI_TRACKING_SCHEMA
