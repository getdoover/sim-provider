"""Smoke tests: importable, config schema serialises, helpers behave."""
from integration.app_config import M2MOneIntegrationConfig
from integration.application import M2MOneIntegrationApplication
from integration.m2mone_client import LookupStatus, SimLookup


def test_application_importable():
    assert M2MOneIntegrationApplication


def test_config_schema_serialisable():
    schema = M2MOneIntegrationConfig.to_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "dv_proc_extended_permissions" in schema["properties"]
    assert "dv_proc_schedules" in schema["properties"]
    assert "api_base_url" in schema["properties"]


def test_simlookup_payload_shape():
    lookup = SimLookup(iccid="89610000000000012345", status=LookupStatus.IN_ACCOUNT, details={"accountId": "100020620"})
    payload = lookup.to_dict()
    assert payload["iccid"] == "89610000000000012345"
    assert payload["in_account"] is True
    assert payload["status"] == "in_account"


def test_simlookup_not_in_account_flag():
    payload = SimLookup(iccid="x", status=LookupStatus.NOT_IN_ACCOUNT).to_dict()
    assert payload["in_account"] is False
    assert payload["status"] == "not_in_account"
