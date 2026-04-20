import os

import pytest

from duedatehq.core.postgres import PostgresStorage


DSN = os.getenv("DUEDATEHQ_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not DSN, reason="DUEDATEHQ_TEST_POSTGRES_DSN is not configured")
def test_postgres_healthcheck_and_rls_self_test():
    storage = PostgresStorage(DSN)
    storage.initialize()

    health = storage.healthcheck()
    assert health["database"] == "postgresql"

    rls = storage.run_rls_self_test()
    assert rls["tenant_visible_rows"] == 1
    assert rls["cross_tenant_rows"] == 0
    assert "tenant_id is required" in (rls["missing_tenant_error"] or "")
