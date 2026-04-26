CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS duedatehq;
SET search_path TO duedatehq, public;

CREATE OR REPLACE FUNCTION duedatehq.current_tenant_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '');
$$;

CREATE OR REPLACE FUNCTION duedatehq.require_tenant_id()
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    tenant_value text;
BEGIN
    tenant_value := duedatehq.current_tenant_id();
    IF tenant_value IS NULL THEN
        RAISE EXCEPTION 'tenant_id is required';
    END IF;
    RETURN tenant_value;
END;
$$;

CREATE TABLE IF NOT EXISTS duedatehq.tenants (
    tenant_id text PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    is_deleted boolean NOT NULL DEFAULT false,
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.clients (
    client_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    name text NOT NULL,
    entity_type text NOT NULL,
    registered_states jsonb NOT NULL,
    tax_year integer NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS client_type text NOT NULL DEFAULT 'business';
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS legal_name text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS home_jurisdiction text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS primary_contact_name text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS primary_contact_email text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS primary_contact_phone text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS preferred_communication_channel text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS responsible_cpa text;
ALTER TABLE duedatehq.clients ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

CREATE TABLE IF NOT EXISTS duedatehq.client_tax_profiles (
    profile_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    tax_year integer NOT NULL,
    entity_election text,
    first_year_filing boolean,
    final_year_filing boolean,
    extension_requested boolean,
    extension_filed boolean,
    estimated_tax_required boolean,
    payroll_present boolean,
    contractor_reporting_required boolean,
    notice_received boolean,
    intake_status text NOT NULL,
    source text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (client_id, tax_year)
);

CREATE TABLE IF NOT EXISTS duedatehq.client_jurisdictions (
    client_jurisdiction_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    tax_year integer NOT NULL,
    jurisdiction text NOT NULL,
    jurisdiction_type text NOT NULL,
    active boolean NOT NULL,
    source text NOT NULL,
    notes text,
    created_at timestamptz NOT NULL,
    UNIQUE (client_id, tax_year, jurisdiction, jurisdiction_type)
);

CREATE TABLE IF NOT EXISTS duedatehq.client_contacts (
    contact_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    name text NOT NULL,
    role text,
    email text,
    phone text,
    preferred_channel text,
    is_primary boolean NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS duedatehq.tasks (
    task_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    title text NOT NULL,
    description text,
    task_type text NOT NULL,
    status text NOT NULL,
    priority text NOT NULL,
    source_type text NOT NULL,
    source_id text,
    owner_user_id text,
    due_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    completed_at timestamptz,
    dismissed_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.blockers (
    blocker_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    title text NOT NULL,
    description text,
    blocker_type text NOT NULL,
    status text NOT NULL,
    source_type text NOT NULL,
    source_id text,
    owner_user_id text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    resolved_at timestamptz,
    dismissed_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.notices (
    notice_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    title text NOT NULL,
    source_url text NOT NULL,
    source_label text,
    summary text,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    read_at timestamptz,
    dismissed_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.rules (
    rule_id text PRIMARY KEY,
    tax_type text NOT NULL,
    jurisdiction text NOT NULL,
    entity_types jsonb NOT NULL,
    deadline_date date NOT NULL,
    effective_from date NOT NULL,
    source_url text NOT NULL,
    confidence_score numeric(4,3) NOT NULL,
    status text NOT NULL,
    version integer NOT NULL,
    created_at timestamptz NOT NULL,
    superseded_by text,
    raw_text text,
    fetched_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.rule_review_queue (
    review_id text PRIMARY KEY,
    source_url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    raw_text text NOT NULL,
    confidence_score numeric(4,3) NOT NULL,
    parse_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS duedatehq.fetch_runs (
    fetch_run_id text PRIMARY KEY,
    source_key text NOT NULL,
    source_url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    rule_id text,
    review_id text,
    notes text
);

CREATE TABLE IF NOT EXISTS duedatehq.job_queue (
    job_id text PRIMARY KEY,
    tenant_id text,
    job_type text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    claimed_at timestamptz,
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.notification_routes (
    route_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    channel text NOT NULL,
    destination text NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS duedatehq.notification_deliveries (
    delivery_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    deadline_id text NOT NULL REFERENCES duedatehq.deadlines(deadline_id),
    reminder_id text NOT NULL REFERENCES duedatehq.reminders(reminder_id),
    channel text NOT NULL,
    destination text NOT NULL,
    subject text NOT NULL,
    body text NOT NULL,
    status text NOT NULL,
    provider_message_id text,
    error_message text,
    created_at timestamptz NOT NULL,
    sent_at timestamptz
);

CREATE TABLE IF NOT EXISTS duedatehq.deadlines (
    deadline_id text PRIMARY KEY,
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    rule_id text NOT NULL REFERENCES duedatehq.rules(rule_id),
    tax_type text NOT NULL,
    jurisdiction text NOT NULL,
    due_date date NOT NULL,
    status text NOT NULL,
    reminder_type text NOT NULL,
    override_date date,
    snoozed_until timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (client_id, tax_type, jurisdiction)
);

CREATE TABLE IF NOT EXISTS duedatehq.deadline_transitions (
    transition_id text PRIMARY KEY,
    deadline_id text NOT NULL REFERENCES duedatehq.deadlines(deadline_id),
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    previous_status text NOT NULL,
    new_status text NOT NULL,
    action text NOT NULL,
    actor text NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS duedatehq.reminders (
    reminder_id text PRIMARY KEY,
    deadline_id text NOT NULL REFERENCES duedatehq.deadlines(deadline_id),
    tenant_id text NOT NULL REFERENCES duedatehq.tenants(tenant_id),
    client_id text NOT NULL REFERENCES duedatehq.clients(client_id),
    scheduled_at timestamptz NOT NULL,
    triggered_at timestamptz,
    status text NOT NULL,
    reminder_day text NOT NULL,
    reminder_type text NOT NULL,
    responded_at timestamptz,
    response text
);

CREATE TABLE IF NOT EXISTS duedatehq.audit_log (
    log_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    actor text NOT NULL,
    actor_ip text NOT NULL,
    action_type text NOT NULL,
    object_type text NOT NULL,
    object_id text NOT NULL,
    before_json jsonb NOT NULL,
    after_json jsonb NOT NULL,
    correlation_id text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE OR REPLACE FUNCTION duedatehq.audit_log_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$;

DROP TRIGGER IF EXISTS audit_log_no_update ON duedatehq.audit_log;
CREATE TRIGGER audit_log_no_update
BEFORE UPDATE ON duedatehq.audit_log
FOR EACH ROW
EXECUTE FUNCTION duedatehq.audit_log_append_only();

DROP TRIGGER IF EXISTS audit_log_no_delete ON duedatehq.audit_log;
CREATE TRIGGER audit_log_no_delete
BEFORE DELETE ON duedatehq.audit_log
FOR EACH ROW
EXECUTE FUNCTION duedatehq.audit_log_append_only();

ALTER TABLE duedatehq.clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.client_tax_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.client_jurisdictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.client_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.blockers ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.notices ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.deadlines ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.deadline_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.notification_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE duedatehq.notification_deliveries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS clients_tenant_isolation ON duedatehq.clients;
CREATE POLICY clients_tenant_isolation ON duedatehq.clients
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS client_tax_profiles_tenant_isolation ON duedatehq.client_tax_profiles;
CREATE POLICY client_tax_profiles_tenant_isolation ON duedatehq.client_tax_profiles
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS client_jurisdictions_tenant_isolation ON duedatehq.client_jurisdictions;
CREATE POLICY client_jurisdictions_tenant_isolation ON duedatehq.client_jurisdictions
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS client_contacts_tenant_isolation ON duedatehq.client_contacts;
CREATE POLICY client_contacts_tenant_isolation ON duedatehq.client_contacts
    USING (tenant_id = duedatehq.require_tenant_id())
    WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS tasks_tenant_isolation ON duedatehq.tasks;
CREATE POLICY tasks_tenant_isolation ON duedatehq.tasks
    USING (tenant_id = duedatehq.require_tenant_id())
    WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS blockers_tenant_isolation ON duedatehq.blockers;
CREATE POLICY blockers_tenant_isolation ON duedatehq.blockers
    USING (tenant_id = duedatehq.require_tenant_id())
    WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS notices_tenant_isolation ON duedatehq.notices;
CREATE POLICY notices_tenant_isolation ON duedatehq.notices
    USING (tenant_id = duedatehq.require_tenant_id())
    WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS deadlines_tenant_isolation ON duedatehq.deadlines;
CREATE POLICY deadlines_tenant_isolation ON duedatehq.deadlines
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS transitions_tenant_isolation ON duedatehq.deadline_transitions;
CREATE POLICY transitions_tenant_isolation ON duedatehq.deadline_transitions
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS reminders_tenant_isolation ON duedatehq.reminders;
CREATE POLICY reminders_tenant_isolation ON duedatehq.reminders
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS audit_log_tenant_isolation ON duedatehq.audit_log;
CREATE POLICY audit_log_tenant_isolation ON duedatehq.audit_log
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS notification_routes_tenant_isolation ON duedatehq.notification_routes;
CREATE POLICY notification_routes_tenant_isolation ON duedatehq.notification_routes
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());

DROP POLICY IF EXISTS notification_deliveries_tenant_isolation ON duedatehq.notification_deliveries;
CREATE POLICY notification_deliveries_tenant_isolation ON duedatehq.notification_deliveries
USING (tenant_id = duedatehq.require_tenant_id())
WITH CHECK (tenant_id = duedatehq.require_tenant_id());
