-- Supabase schema for JO AI backend tracking

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

create index if not exists idx_history_telegram_created_at
  on public.history (telegram_id, created_at desc);

create index if not exists idx_history_message_type
  on public.history (message_type);
