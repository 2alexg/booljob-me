-- Locations and skills taxonomy (design doc §5.C, §5.D).
-- Seed data is loaded in S1-09 (localities) and S1-11 (skills).

create table public.regions (
  code text primary key,
  name_he text not null,
  name_en text not null
);

-- id is the CBS locality code.
create table public.localities (
  id integer primary key,
  name_he text not null,
  name_en text,
  district text,
  region_code text references public.regions (code),
  -- Locality-level point from government data or OpenStreetMap.
  -- Never store coordinates obtained from Google.
  location extensions.geography(Point, 4326),
  location_source text,

  constraint localities_location_source_valid
    check (location_source is null or location_source in ('gov', 'osm'))
);

create index localities_location_idx on public.localities using gist (location);
create index localities_region_idx on public.localities (region_code);

create table public.locality_aliases (
  alias_normalized text primary key,
  locality_id integer not null references public.localities (id) on delete cascade
);

create table public.skills (
  id bigint generated always as identity primary key,
  key text not null unique,
  label_he text,
  label_en text not null,
  category text,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint skills_status_valid check (status in ('approved', 'pending', 'rejected'))
);

create trigger skills_set_updated_at
  before update on public.skills
  for each row execute function public.set_updated_at();

create table public.skill_aliases (
  alias_normalized text primary key,
  skill_id bigint not null references public.skills (id) on delete cascade
);
