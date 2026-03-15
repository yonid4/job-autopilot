-- Atomic resume activation — deactivates all resumes for the user then activates the given one.
-- Called via RPC from app/core/database.py:set_active_resume

create or replace function set_active_resume(p_user_id uuid, p_resume_id uuid)
returns void
language plpgsql
security definer
as $$
begin
    update resumes
    set is_active = false
    where user_id = p_user_id;

    update resumes
    set is_active = true
    where id = p_resume_id
      and user_id = p_user_id;
end;
$$;
