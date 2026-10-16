-- FoodLoop Supabase schema. Run in the Supabase SQL Editor before enabling credentials.
create extension if not exists pgcrypto;

create table if not exists public.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    verification_status text not null default 'PENDING'
        check (verification_status in ('PENDING', 'VERIFIED', 'REJECTED')),
    preferred_categories jsonb not null default '[]'::jsonb,
    minimum_quantity numeric not null default 1 check (minimum_quantity > 0),
    maximum_quantity numeric not null default 10000 check (maximum_quantity >= minimum_quantity),
    available boolean not null default true,
    pickup_capacity numeric not null default 100 check (pickup_capacity >= 0),
    location text not null,
    latitude double precision check (latitude between -90 and 90),
    longitude double precision check (longitude between -180 and 180),
    estimated_pickup_minutes integer not null default 30 check (estimated_pickup_minutes >= 0),
    created_at timestamptz not null default now()
);

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    role text not null check (role in ('donor', 'recipient', 'admin')),
    display_name text not null,
    organization_id uuid references public.organizations(id),
    created_at timestamptz not null default now(),
    check ((role = 'recipient' and organization_id is not null) or role <> 'recipient')
);

create table if not exists public.donations (
    id uuid primary key default gen_random_uuid(),
    donor_id uuid not null references public.profiles(id),
    title text not null check (length(trim(title)) >= 2),
    category text not null,
    description text not null default '',
    quantity numeric not null check (quantity > 0),
    unit text not null,
    prepared_at timestamptz not null,
    pickup_deadline timestamptz not null,
    donor_confirms_edible boolean not null check (donor_confirms_edible),
    storage_conditions text not null,
    allergens jsonb not null default '[]'::jsonb,
    allergen_info_known boolean not null,
    location text not null,
    latitude double precision check (latitude between -90 and 90),
    longitude double precision check (longitude between -180 and 180),
    minimum_quantity numeric check (minimum_quantity > 0),
    maximum_quantity numeric check (maximum_quantity > 0),
    status text not null default 'AVAILABLE'
        check (status in ('AVAILABLE', 'REQUESTED', 'ACCEPTED', 'READY_FOR_PICKUP',
                          'COMPLETED', 'CANCELLED', 'WITHDRAWN', 'EXPIRED')),
    safety_status text not null default 'PENDING_REVIEW'
        check (safety_status in ('PENDING_REVIEW', 'ELIGIBLE', 'FLAGGED', 'EXPIRED')),
    safety_warnings jsonb not null default '[]'::jsonb,
    review_note text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (pickup_deadline > prepared_at),
    check (minimum_quantity is null or maximum_quantity is null or minimum_quantity <= maximum_quantity)
);

create table if not exists public.claims (
    id uuid primary key default gen_random_uuid(),
    donation_id uuid not null references public.donations(id),
    recipient_id uuid not null references public.organizations(id),
    requested_quantity numeric not null check (requested_quantity > 0),
    status text not null default 'REQUESTED'
        check (status in ('REQUESTED', 'ACCEPTED', 'READY_FOR_PICKUP', 'COMPLETED', 'CANCELLED')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz
);

create unique index if not exists one_active_claim_per_donation
    on public.claims(donation_id)
    where status in ('REQUESTED', 'ACCEPTED', 'READY_FOR_PICKUP');
create index if not exists donations_board_idx
    on public.donations(status, safety_status, pickup_deadline);
create index if not exists donations_donor_idx on public.donations(donor_id);
create index if not exists claims_recipient_idx on public.claims(recipient_id, status);

create table if not exists public.safety_reviews (
    id uuid primary key default gen_random_uuid(),
    donation_id uuid not null references public.donations(id),
    reviewer_id uuid references public.profiles(id),
    action text not null check (action in ('resolve', 'flag', 'withdraw')),
    note text not null default '',
    created_at timestamptz not null default now()
);

create or replace function public.foodloop_is_admin()
returns boolean language sql stable security definer set search_path = public
as $$
    select exists(select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
$$;

create or replace function public.foodloop_is_donation_donor(target_donation uuid)
returns boolean language sql stable security definer set search_path = public
as $$
    select exists(
        select 1 from public.donations d
        where d.id = target_donation and d.donor_id = auth.uid()
    )
$$;

create or replace function public.foodloop_is_claim_recipient(target_organization uuid)
returns boolean language sql stable security definer set search_path = public
as $$
    select exists(
        select 1 from public.profiles p
        where p.id = auth.uid() and p.role = 'recipient' and p.organization_id = target_organization
    )
$$;

alter table public.profiles enable row level security;
alter table public.organizations enable row level security;
alter table public.donations enable row level security;
alter table public.claims enable row level security;
alter table public.safety_reviews enable row level security;

drop policy if exists "profiles are visible to their owner and admins" on public.profiles;
create policy "profiles are visible to their owner and admins"
    on public.profiles for select to authenticated
    using (id = auth.uid() or public.foodloop_is_admin());
drop policy if exists "organizations are visible for discovery" on public.organizations;
create policy "organizations are visible for discovery"
    on public.organizations for select to anon, authenticated
    using (verification_status = 'VERIFIED' or public.foodloop_is_admin());
drop policy if exists "admins manage organizations" on public.organizations;
create policy "admins manage organizations"
    on public.organizations for all to authenticated
    using (public.foodloop_is_admin()) with check (public.foodloop_is_admin());
drop policy if exists "donations are visible unless withdrawn" on public.donations;
create policy "donations are visible unless withdrawn"
    on public.donations for select to anon, authenticated
    using (status <> 'WITHDRAWN');
drop policy if exists "donors create their donations" on public.donations;
create policy "donors create their donations"
    on public.donations for insert to authenticated
    with check (donor_id = auth.uid() and exists (
        select 1 from public.profiles p where p.id = auth.uid() and p.role = 'donor'
    ));
drop policy if exists "donors and admins update donations" on public.donations;
create policy "donors and admins update donations"
    on public.donations for update to authenticated
    using (donor_id = auth.uid() or public.foodloop_is_admin())
    with check (donor_id = auth.uid() or public.foodloop_is_admin());
drop policy if exists "claims visible to participants and admins" on public.claims;
create policy "claims visible to participants and admins"
    on public.claims for select to authenticated
    using (
        public.foodloop_is_admin()
        or public.foodloop_is_claim_recipient(recipient_id)
        or public.foodloop_is_donation_donor(donation_id)
    );
drop policy if exists "claim inserts are backend only" on public.claims;
create policy "claim inserts are backend only"
    on public.claims for insert to service_role with check (true);
drop policy if exists "claim updates are backend only" on public.claims;
create policy "claim updates are backend only"
    on public.claims for update to service_role using (true) with check (true);
drop policy if exists "safety reviews are admin visible" on public.safety_reviews;
create policy "safety reviews are admin visible"
    on public.safety_reviews for select to authenticated
    using (public.foodloop_is_admin());
drop policy if exists "safety reviews are backend written" on public.safety_reviews;
create policy "safety reviews are backend written"
    on public.safety_reviews for all to service_role using (true) with check (true);

create or replace function public.request_donation_claim(
    p_donation_id uuid,
    p_recipient_id uuid,
    p_requested_quantity numeric
) returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    donation_row public.donations%rowtype;
    recipient_row public.organizations%rowtype;
    claim_row public.claims%rowtype;
begin
    select * into donation_row from public.donations where id = p_donation_id for update;
    if not found then raise exception 'Donation not found.' using errcode = 'P0002'; end if;
    select * into recipient_row from public.organizations where id = p_recipient_id;
    if not found then raise exception 'Recipient organization not found.' using errcode = 'P0002'; end if;
    if recipient_row.verification_status <> 'VERIFIED' or not recipient_row.available then
        raise exception 'Only verified, available organizations may request donations.' using errcode = '42501';
    end if;
    if donation_row.status <> 'AVAILABLE' then
        raise exception 'This donation is no longer available.' using errcode = '23505';
    end if;
    if donation_row.safety_status <> 'ELIGIBLE' then
        raise exception 'This donation is not cleared for pickup.' using errcode = '23514';
    end if;
    if donation_row.pickup_deadline <= now() then
        update public.donations set status = 'EXPIRED', safety_status = 'EXPIRED',
            updated_at = now() where id = p_donation_id;
        return jsonb_build_object('error', 'This donation pickup deadline has passed.');
    end if;
    if jsonb_array_length(recipient_row.preferred_categories) > 0
       and not (recipient_row.preferred_categories ? donation_row.category) then
        return jsonb_build_object('error', 'This organization does not accept this food category.');
    end if;
    if recipient_row.estimated_pickup_minutes >=
       extract(epoch from (donation_row.pickup_deadline - now())) / 60 then
        return jsonb_build_object('error', 'This organization cannot collect within the pickup window.');
    end if;
    if p_requested_quantity <= 0
       or p_requested_quantity > donation_row.quantity
       or p_requested_quantity > recipient_row.pickup_capacity
       or p_requested_quantity < recipient_row.minimum_quantity
       or p_requested_quantity > recipient_row.maximum_quantity
       or (donation_row.minimum_quantity is not null and p_requested_quantity < donation_row.minimum_quantity)
       or (donation_row.maximum_quantity is not null and p_requested_quantity > donation_row.maximum_quantity) then
        raise exception 'Requested quantity is outside the accepted range or pickup capacity.' using errcode = '23514';
    end if;
    insert into public.claims(donation_id, recipient_id, requested_quantity)
    values (p_donation_id, p_recipient_id, p_requested_quantity)
    returning * into claim_row;
    update public.donations set status = 'REQUESTED', updated_at = now()
    where id = p_donation_id;
    return to_jsonb(claim_row);
end
$$;

create or replace function public.transition_donation_claim(
    p_claim_id uuid,
    p_new_status text,
    p_actor_id uuid,
    p_actor_role text
) returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    claim_row public.claims%rowtype;
    donation_row public.donations%rowtype;
    actor_role text;
    actor_organization uuid;
    permitted boolean := false;
begin
    select * into claim_row from public.claims where id = p_claim_id for update;
    if not found then raise exception 'Pickup claim not found.' using errcode = 'P0002'; end if;
    select * into donation_row from public.donations where id = claim_row.donation_id for update;
    select role, organization_id into actor_role, actor_organization
      from public.profiles where id = p_actor_id;
    if actor_role is null or actor_role <> p_actor_role then
        raise exception 'Account role is not authorized.' using errcode = '42501';
    end if;
    if donation_row.pickup_deadline <= now() and p_new_status <> 'CANCELLED' then
        update public.donations set status = 'EXPIRED', safety_status = 'EXPIRED',
            updated_at = now() where id = donation_row.id;
        return jsonb_build_object('error', 'Pickup deadline has passed; this claim cannot progress.');
    end if;
    if p_new_status <> 'CANCELLED'
       and (donation_row.status in ('WITHDRAWN', 'COMPLETED', 'EXPIRED')
            or donation_row.safety_status <> 'ELIGIBLE') then
        return jsonb_build_object('error', 'Safety review or an active donation status is required before pickup can progress.');
    end if;
    if p_new_status = 'ACCEPTED' then
        permitted := claim_row.status = 'REQUESTED'
          and ((actor_role = 'donor' and donation_row.donor_id = p_actor_id) or actor_role = 'admin');
    elsif p_new_status = 'READY_FOR_PICKUP' then
        permitted := claim_row.status = 'ACCEPTED'
          and ((actor_role = 'donor' and donation_row.donor_id = p_actor_id) or actor_role = 'admin');
    elsif p_new_status = 'COMPLETED' then
        permitted := claim_row.status = 'READY_FOR_PICKUP'
          and ((actor_role = 'recipient' and actor_organization = claim_row.recipient_id)
            or (actor_role = 'donor' and donation_row.donor_id = p_actor_id)
          );
    elsif p_new_status = 'CANCELLED' then
        permitted := claim_row.status in ('REQUESTED', 'ACCEPTED', 'READY_FOR_PICKUP')
          and ((actor_role = 'recipient' and actor_organization = claim_row.recipient_id)
            or (actor_role = 'donor' and donation_row.donor_id = p_actor_id)
            or actor_role = 'admin');
    end if;
    if not permitted then
        raise exception 'This status transition is not allowed for your role or current status.' using errcode = '42501';
    end if;
    update public.claims set status = p_new_status, updated_at = now(),
        completed_at = case when p_new_status = 'COMPLETED' then now() else completed_at end
      where id = p_claim_id returning * into claim_row;
    update public.donations set status = p_new_status, updated_at = now()
      where id = donation_row.id;
    if p_new_status = 'CANCELLED' and donation_row.pickup_deadline > now() then
        update public.donations set status = 'AVAILABLE', updated_at = now()
          where id = donation_row.id;
    elsif p_new_status = 'CANCELLED' then
        update public.donations set status = 'EXPIRED', safety_status = 'EXPIRED',
            updated_at = now() where id = donation_row.id;
    end if;
    return to_jsonb(claim_row);
end
$$;

create or replace function public.review_food_donation(
    p_donation_id uuid,
    p_action text,
    p_note text,
    p_reviewer_id uuid
) returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    donation_row public.donations%rowtype;
    next_safety_status text;
    next_status text;
begin
    if not exists (
        select 1 from public.profiles
        where id = p_reviewer_id and role = 'admin'
    ) then
        return jsonb_build_object('error', 'An authorized administrator is required.');
    end if;
    select * into donation_row from public.donations where id = p_donation_id for update;
    if not found then
        return jsonb_build_object('error', 'Donation not found.');
    end if;
    next_status := donation_row.status;
    next_safety_status := donation_row.safety_status;
    if p_action = 'withdraw' then
        if donation_row.status = 'COMPLETED' then
            return jsonb_build_object('error', 'Completed donations cannot be withdrawn.');
        end if;
        if exists (
            select 1 from public.claims
            where donation_id = p_donation_id
              and status in ('REQUESTED', 'ACCEPTED', 'READY_FOR_PICKUP')
        ) then
            return jsonb_build_object('error', 'Cancel the active pickup claim before withdrawing this donation.');
        end if;
        next_status := 'WITHDRAWN';
    elsif p_action = 'flag' then
        next_safety_status := 'FLAGGED';
    elsif p_action = 'resolve' then
        if donation_row.pickup_deadline <= now() then
            return jsonb_build_object('error', 'Expired donations cannot be cleared for pickup.');
        end if;
        next_safety_status := 'ELIGIBLE';
    else
        return jsonb_build_object('error', 'Unsupported review action.');
    end if;
    update public.donations set
        status = next_status,
        safety_status = next_safety_status,
        safety_warnings = case
            when p_action = 'resolve' then '[]'::jsonb
            when p_action = 'flag' then safety_warnings || jsonb_build_array(
                coalesce(nullif(trim(p_note), ''), 'Flagged for administrative safety review.')
            )
            else safety_warnings
        end,
        review_note = coalesce(nullif(trim(p_note), ''), review_note),
        updated_at = now()
    where id = p_donation_id returning * into donation_row;
    insert into public.safety_reviews(donation_id, reviewer_id, action, note)
    values (p_donation_id, p_reviewer_id, p_action, coalesce(p_note, ''));
    return to_jsonb(donation_row);
end
$$;

revoke all on function public.request_donation_claim(uuid, uuid, numeric) from public, anon, authenticated;
grant execute on function public.request_donation_claim(uuid, uuid, numeric) to service_role;
revoke all on function public.transition_donation_claim(uuid, text, uuid, text) from public, anon, authenticated;
grant execute on function public.transition_donation_claim(uuid, text, uuid, text) to service_role;
revoke all on function public.review_food_donation(uuid, text, text, uuid) from public, anon, authenticated;
grant execute on function public.review_food_donation(uuid, text, text, uuid) to service_role;

grant usage on schema public to anon, authenticated, service_role;
grant select on public.organizations, public.donations to anon, authenticated;
grant select on public.profiles, public.claims, public.safety_reviews to authenticated;
grant insert, update on public.donations, public.organizations to authenticated;
grant all on public.profiles, public.organizations, public.donations,
    public.claims, public.safety_reviews to service_role;
