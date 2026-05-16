-- Job Autopilot v2 — initial schema
-- Run this in the Supabase SQL editor.
-- Requires: pgvector extension enabled (Dashboard → Database → Extensions → vector)

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- jobs  (shared across all users — one row per unique posting)
-- ---------------------------------------------------------------------------
create table if not exists jobs (
    id            uuid primary key default gen_random_uuid(),
    url           text unique not null,
    title         text not null,
    company       text not null,
    description   text,
    salary        text,
    job_level     text,
    -- generated column for title+company dedup
    title_company text generated always as (lower(title) || '::' || lower(company)) stored,
    embedding     vector(768),
    created_at    timestamptz default now()
);

create index if not exists jobs_title_company_idx on jobs (title_company);
create index if not exists jobs_embedding_idx on jobs using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- RLS: jobs readable by all authenticated users, writable only by service role
alter table jobs enable row level security;
create policy "jobs_select" on jobs for select to authenticated using (true);
create policy "jobs_insert" on jobs for insert to service_role with check (true);
create policy "jobs_update" on jobs for update to service_role using (true);

-- ---------------------------------------------------------------------------
-- resumes  (per-user, multiple versions)
-- ---------------------------------------------------------------------------
create table if not exists resumes (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    label        text not null default 'default',
    storage_path text not null,        -- Supabase Storage path
    parsed_json  jsonb,
    is_active    boolean not null default false,
    created_at   timestamptz default now()
);

create index if not exists resumes_user_id_idx on resumes (user_id);

alter table resumes enable row level security;
create policy "resumes_owner" on resumes for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- resume_chunks  (per-user, one row per section chunk + embedding)
-- Chunks are section-level: experience, education, skills, projects, summary.
-- Gemini Embedding 2 supports up to 8192 tokens — each section fits easily.
-- ---------------------------------------------------------------------------
create table if not exists resume_chunks (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    resume_id   uuid not null references resumes(id) on delete cascade,
    chunk_index int not null,
    section     text,                  -- "experience" | "skills" | "projects" | "education" | "summary"
    content     text not null,
    embedding   vector(768),
    created_at  timestamptz default now()
);

create index if not exists resume_chunks_user_id_idx  on resume_chunks (user_id);
create index if not exists resume_chunks_resume_id_idx on resume_chunks (resume_id);
create index if not exists resume_chunks_embedding_idx on resume_chunks
    using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table resume_chunks enable row level security;
create policy "resume_chunks_owner" on resume_chunks for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- user_projects  (per-user — portfolio projects used as cover-letter hooks)
-- ---------------------------------------------------------------------------
create table if not exists user_projects (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    name         text not null,
    description  text not null,
    technologies text[],
    url          text,
    embedding    vector(768),
    created_at   timestamptz default now()
);

create index if not exists user_projects_user_id_idx  on user_projects (user_id);
create index if not exists user_projects_embedding_idx on user_projects
    using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table user_projects enable row level security;
create policy "user_projects_owner" on user_projects for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- applications  (per-user — one row per user+job pair)
-- ---------------------------------------------------------------------------
create table if not exists applications (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references auth.users(id) on delete cascade,
    job_id          uuid not null references jobs(id) on delete cascade,
    resume_id       uuid references resumes(id) on delete set null,
    status          text not null default 'not_applied',
    fit_score       int,
    strengths       text[],
    gaps            text[],
    summary_text    text,
    cover_letter    text,
    pdf_path        text,              -- Supabase Storage path for generated PDF
    hook_project_id uuid references user_projects(id) on delete set null,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now(),
    unique (user_id, job_id)
);

create index if not exists applications_user_id_idx on applications (user_id);
create index if not exists applications_status_idx  on applications (user_id, status);

alter table applications enable row level security;
create policy "applications_owner" on applications for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- RPC helpers
-- ---------------------------------------------------------------------------

-- Retrieve resume chunks most semantically similar to a query embedding
create or replace function match_resume_chunks(
    p_user_id   uuid,
    p_resume_id uuid,
    p_embedding vector(768),
    p_limit     int default 10
)
returns table (
    id          uuid,
    chunk_index int,
    section     text,
    content     text,
    similarity  float
)
language sql stable
as $$
    select
        rc.id,
        rc.chunk_index,
        rc.section,
        rc.content,
        1 - (rc.embedding <=> p_embedding) as similarity
    from resume_chunks rc
    where rc.user_id   = p_user_id
      and rc.resume_id = p_resume_id
      and rc.embedding is not null
    order by rc.embedding <=> p_embedding
    limit p_limit;
$$;

-- Find the user's project whose embedding is closest to a job embedding
create or replace function match_best_project(
    p_user_id   uuid,
    p_embedding vector(768)
)
returns table (
    id           uuid,
    name         text,
    description  text,
    technologies text[],
    url          text,
    similarity   float
)
language sql stable
as $$
    select
        up.id,
        up.name,
        up.description,
        up.technologies,
        up.url,
        1 - (up.embedding <=> p_embedding) as similarity
    from user_projects up
    where up.user_id   = p_user_id
      and up.embedding is not null
    order by up.embedding <=> p_embedding
    limit 1;
$$;

-- Semantic job search across the shared jobs table
create or replace function match_jobs(
    p_embedding vector(768),
    p_limit     int   default 20,
    p_threshold float default 0.5
)
returns table (
    id          uuid,
    url         text,
    title       text,
    company     text,
    description text,
    similarity  float
)
language sql stable
as $$
    select
        j.id,
        j.url,
        j.title,
        j.company,
        j.description,
        1 - (j.embedding <=> p_embedding) as similarity
    from jobs j
    where j.embedding is not null
      and 1 - (j.embedding <=> p_embedding) >= p_threshold
    order by j.embedding <=> p_embedding
    limit p_limit;
$$;
