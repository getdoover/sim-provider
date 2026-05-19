"""Smoke tests: importable, config schemas serialise, helpers behave."""
from sim_provider_m2mone.app_config import M2MOneSimProviderConfig
from sim_provider_m2mone.application import M2MOneSimProviderApp
from sim_provider_m2mone.m2mone_client import LookupStatus, SimLookup
from sim_dashboard.app_config import SimDashboardConfig
from sim_dashboard.application import SimDashboardApp


def test_provider_application_importable():
    assert M2MOneSimProviderApp


def test_dashboard_application_importable():
    assert SimDashboardApp


def test_provider_config_schema_serialisable():
    schema = M2MOneSimProviderConfig.to_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "dv_proc_extended_permissions" in schema["properties"]
    assert "dv_proc_schedules" in schema["properties"]
    assert "api_base_url" in schema["properties"]


def test_dashboard_config_schema_serialisable():
    schema = SimDashboardConfig.to_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "dv_proc_extended_permissions" in schema["properties"]


def test_simlookup_payload_shape():
    lookup = SimLookup(iccid="89610000000000012345", status=LookupStatus.IN_ACCOUNT, details={"accountId": "100020620"})
    payload = lookup.to_dict()
    assert payload["iccid"] == "89610000000000012345"
    assert payload["status"] == "in_account"
    assert payload["details"] == {"accountId": "100020620"}


def test_simlookup_not_in_account_status():
    payload = SimLookup(iccid="x", status=LookupStatus.NOT_IN_ACCOUNT).to_dict()
    assert payload["status"] == "not_in_account"
    assert payload["details"] is None
