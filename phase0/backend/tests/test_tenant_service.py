from backend.app.tenant import TenantService, TenantQuota


def test_create_and_get_tenant(tmp_path):
    store_file = tmp_path / "tenants.json"
    from backend.app.tenant.store import TenantStore
    store = TenantStore(file_path=store_file)
    service = TenantService(store=store)

    tenant = service.create_tenant(
        tenant_id="tenant_x",
        name="Tenant X",
        api_keys=["key_x_123"],
    )
    assert tenant.id == "tenant_x"
    assert tenant.name == "Tenant X"

    retrieved = service.get_tenant("tenant_x")
    assert retrieved is not None
    assert retrieved.name == "Tenant X"


def test_resolve_api_key(tmp_path):
    store_file = tmp_path / "tenants.json"
    from backend.app.tenant.store import TenantStore
    store = TenantStore(file_path=store_file)
    service = TenantService(store=store)

    service.create_tenant(
        tenant_id="tenant_y",
        name="Tenant Y",
        api_keys=["key_y_abc"],
    )

    tenant = service.resolve_api_key("key_y_abc")
    assert tenant is not None
    assert tenant.id == "tenant_y"

    invalid = service.resolve_api_key("key_nonexistent")
    assert invalid is None


def test_list_tenants(tmp_path):
    store_file = tmp_path / "tenants.json"
    from backend.app.tenant.store import TenantStore
    store = TenantStore(file_path=store_file)
    service = TenantService(store=store)

    service.create_tenant("t1", "Tenant 1", api_keys=["k1"])
    service.create_tenant("t2", "Tenant 2", api_keys=["k2"])

    all_t = service.list_tenants()
    assert len(all_t) == 2
    ids = [t.id for t in all_t]
    assert "t1" in ids and "t2" in ids
