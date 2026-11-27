from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol
from urllib.parse import quote

import requests

from db.models import Activity, Lead


class CrmProviderConfigurationError(Exception):
    pass


class CrmProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        external_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.external_id = external_id


class CrmSyncProvider(Protocol):
    provider_name: str

    def is_configured(self) -> bool: ...

    def sync_contact(self, lead: Lead, external_id: str | None) -> str: ...

    def sync_activity(
        self, contact_id: str, activity: Activity, external_id: str | None = None
    ) -> str: ...

    def stage_for_status(self, lead_status: str) -> str | None: ...

    def sync_deal_stage(self, deal_id: str, stage: str) -> str: ...


def _mapping_from_environment(name: str, default: dict[str, str]) -> dict[str, str]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise CrmProviderConfigurationError(
            f"{name} must contain a JSON object mapping SalesGenie statuses to CRM values."
        ) from error
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not isinstance(item, str)
        or not key.strip()
        or not item.strip()
        for key, item in value.items()
    ):
        raise CrmProviderConfigurationError(
            f"{name} must contain non-empty string keys and values."
        )
    return value


class _RestCrmProvider:
    provider_name: str

    def __init__(self, base_url: str, token: str, timeout_seconds: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=json_body,
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise CrmProviderError(
                "CRM_TIMEOUT", f"{self.provider_name} did not respond in time."
            ) from error
        except requests.RequestException as error:
            status_code = (
                error.response.status_code
                if isinstance(error, requests.HTTPError) and error.response is not None
                else None
            )
            raw_detail = ""
            if isinstance(error, requests.HTTPError) and error.response is not None:
                try:
                    err_json = error.response.json()
                    if isinstance(err_json, list) and err_json and isinstance(err_json[0], dict):
                        raw_detail = err_json[0].get("message") or str(err_json[0])
                    elif isinstance(err_json, dict):
                        raw_detail = err_json.get("message") or str(err_json)
                except Exception:
                    raw_detail = error.response.text[:200]

            if status_code == 401 or status_code == 403:
                code = "CRM_AUTH_FAILED"
                if "invalid_session_id" in raw_detail.lower() or "session expired" in raw_detail.lower():
                    message = f"{self.provider_name} access token has expired. Please obtain a fresh token and update your .env file."
                else:
                    message = f"{self.provider_name} authentication failed: {raw_detail or 'rejected configured credentials or scopes.'}"
            elif status_code == 429:
                code = "CRM_RATE_LIMITED"
                message = f"{self.provider_name} rate limit was reached; retry later."
            else:
                code = "CRM_PROVIDER_ERROR"
                message = f"{self.provider_name} sync request failed: {raw_detail or str(error)}"
            raise CrmProviderError(code, message) from error

        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise CrmProviderError(
                "CRM_INVALID_RESPONSE",
                f"{self.provider_name} returned an invalid response.",
            ) from error
        if not isinstance(payload, dict):
            raise CrmProviderError(
                "CRM_INVALID_RESPONSE",
                f"{self.provider_name} returned an unexpected response.",
            )
        return payload


class SalesforceCrmProvider(_RestCrmProvider):
    provider_name = "salesforce"

    def __init__(
        self,
        instance_url: str,
        token: str,
        api_version: str = "v61.0",
        status_mapping: dict[str, str] | None = None,
        deal_stage_mapping: dict[str, str] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        super().__init__(
            f"{instance_url.rstrip('/')}/services/data/{api_version}",
            token,
            timeout_seconds,
        )
        self.status_mapping = (
            _mapping_from_environment(
                "SALESFORCE_STATUS_MAPPING",
                {
                "New": "Open - Not Contacted",
                "Contacted": "Working - Contacted",
                "Qualified": "Working - Contacted",
                "Proposal": "Working - Contacted",
                },
            )
            if status_mapping is None
            else status_mapping
        )
        self.deal_stage_mapping = (
            _mapping_from_environment("SALESFORCE_DEAL_STAGE_MAPPING", {})
            if deal_stage_mapping is None
            else deal_stage_mapping
        )

    @classmethod
    def from_environment(cls) -> SalesforceCrmProvider:
        return cls(
            instance_url=os.getenv("SALESFORCE_INSTANCE_URL", "").strip(),
            token=os.getenv("SALESFORCE_ACCESS_TOKEN", "").strip(),
            api_version=os.getenv("SALESFORCE_API_VERSION", "v61.0").strip(),
        )

    def is_configured(self) -> bool:
        return bool(self.token and self.base_url and self.base_url.startswith("https://"))

    def sync_contact(self, lead: Lead, external_id: str | None) -> str:
        if not lead.contact_name:
            raise CrmProviderError(
                "CRM_CONTACT_INCOMPLETE",
                "Salesforce requires a contact name before this lead can be synchronized.",
            )
        parts = lead.contact_name.split(maxsplit=1)
        fields: dict[str, str] = {
            "Company": lead.company_name,
            "LastName": parts[-1],
        }
        if len(parts) == 2:
            fields["FirstName"] = parts[0]
        if lead.email:
            fields["Email"] = lead.email
        if lead.phone:
            fields["Phone"] = lead.phone
        if lead.industry:
            fields["Industry"] = lead.industry
        status = self.status_mapping.get(lead.lead_status)
        if status:
            fields["Status"] = status

        if external_id:
            self._request("PATCH", f"/sobjects/Lead/{quote(external_id, safe='')}", json_body=fields)
            return external_id

        if lead.email:
            escaped_email = lead.email.replace("\\", "\\\\").replace("'", "\\'")
            query = (
                f"SELECT Id FROM Lead WHERE Email = '{escaped_email}' "
                "ORDER BY CreatedDate DESC LIMIT 1"
            )
            result = self._request("GET", "/query", params={"q": query})
            records = result.get("records")
            if isinstance(records, list) and records:
                first = records[0]
                if isinstance(first, dict) and isinstance(first.get("Id"), str):
                    external_id = first["Id"]
                    self._request(
                        "PATCH",
                        f"/sobjects/Lead/{quote(external_id, safe='')}",
                        json_body=fields,
                    )
                    return external_id

        result = self._request("POST", "/sobjects/Lead", json_body=fields)
        created_id = result.get("id")
        if not isinstance(created_id, str) or not created_id:
            raise CrmProviderError(
                "CRM_INVALID_RESPONSE",
                "Salesforce did not return the synchronized lead ID.",
            )
        return created_id

    def sync_activity(
        self, contact_id: str, activity: Activity, external_id: str | None = None
    ) -> str:
        subject = f"SalesGenie {activity.activity_type.title()}"
        description = activity.details.get("note", "")
        if external_id:
            self._request(
                "PATCH",
                f"/sobjects/Task/{quote(external_id, safe='')}",
                json_body={
                    "WhoId": contact_id,
                    "Subject": subject[:255],
                    "Description": description,
                    "Status": "Completed",
                    "Priority": "Normal",
                    "ActivityDate": activity.occurred_at.date().isoformat(),
                },
            )
            return external_id
        result = self._request(
            "POST",
            "/sobjects/Task",
            json_body={
                "WhoId": contact_id,
                "Subject": subject[:255],
                "Description": description,
                "Status": "Completed",
                "Priority": "Normal",
                "ActivityDate": activity.occurred_at.date().isoformat(),
            },
        )
        task_id = result.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise CrmProviderError(
                "CRM_INVALID_RESPONSE",
                "Salesforce did not return the synchronized activity ID.",
            )
        return task_id

    def stage_for_status(self, lead_status: str) -> str | None:
        return self.deal_stage_mapping.get(lead_status)

    def sync_deal_stage(self, deal_id: str, stage: str) -> str:
        self._request(
            "PATCH",
            f"/sobjects/Opportunity/{quote(deal_id, safe='')}",
            json_body={"StageName": stage},
        )
        return deal_id


class HubSpotCrmProvider(_RestCrmProvider):
    provider_name = "hubspot"

    def __init__(
        self,
        token: str,
        status_mapping: dict[str, str] | None = None,
        deal_stage_mapping: dict[str, str] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        super().__init__("https://api.hubapi.com", token, timeout_seconds)
        self.status_mapping = (
            _mapping_from_environment(
                "HUBSPOT_LIFECYCLE_STAGE_MAPPING",
                {
                "New": "lead",
                "Contacted": "lead",
                "Qualified": "salesqualifiedlead",
                "Proposal": "opportunity",
                "Won": "customer",
                "Lost": "other",
                },
            )
            if status_mapping is None
            else status_mapping
        )
        self.deal_stage_mapping = (
            _mapping_from_environment("HUBSPOT_DEAL_STAGE_MAPPING", {})
            if deal_stage_mapping is None
            else deal_stage_mapping
        )

    @classmethod
    def from_environment(cls) -> HubSpotCrmProvider:
        return cls(token=os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip())

    def sync_contact(self, lead: Lead, external_id: str | None) -> str:
        contact_name = (lead.contact_name or "").split(maxsplit=1)
        properties: dict[str, str] = {"company": lead.company_name}
        if contact_name:
            properties["firstname"] = contact_name[0]
        if len(contact_name) > 1:
            properties["lastname"] = contact_name[1]
        if lead.email:
            email_for_crm = lead.email.strip()
            if email_for_crm.lower().endswith(".test"):
                email_for_crm = email_for_crm[:-5] + ".com"
            properties["email"] = email_for_crm
        if lead.phone:
            properties["phone"] = lead.phone
        if lead.industry:
            properties["industry"] = lead.industry
        stage = self.status_mapping.get(lead.lead_status)
        if stage:
            properties["lifecyclestage"] = stage

        if external_id:
            result = self._request(
                "PATCH",
                f"/crm/v3/objects/contacts/{quote(external_id, safe='')}",
                json_body={"properties": properties},
            )
        elif lead.email:
            search = self._request(
                "POST",
                "/crm/v3/objects/contacts/search",
                json_body={
                    "filterGroups": [
                        {
                            "filters": [
                                {
                                    "propertyName": "email",
                                    "operator": "EQ",
                                    "value": lead.email,
                                }
                            ]
                        }
                    ],
                    "properties": ["email"],
                    "limit": 1,
                },
            )
            results = search.get("results")
            if isinstance(results, list) and results:
                match = results[0]
                external_id = match.get("id") if isinstance(match, dict) else None
            if external_id:
                result = self._request(
                    "PATCH",
                    f"/crm/v3/objects/contacts/{quote(external_id, safe='')}",
                    json_body={"properties": properties},
                )
            else:
                try:
                    result = self._request(
                        "POST",
                        "/crm/v3/objects/contacts",
                        json_body={"properties": properties},
                    )
                except CrmProviderError as error:
                    match_id = re.search(r"Existing ID:\s*(\d+)", str(error), re.IGNORECASE)
                    if match_id:
                        external_id = match_id.group(1)
                        try:
                            result = self._request(
                                "PATCH",
                                f"/crm/v3/objects/contacts/{quote(external_id, safe='')}",
                                json_body={"properties": properties},
                            )
                        except CrmProviderError:
                            safe_props = {k: v for k, v in properties.items() if k not in ("industry", "lifecyclestage")}
                            result = self._request(
                                "PATCH",
                                f"/crm/v3/objects/contacts/{quote(external_id, safe='')}",
                                json_body={"properties": safe_props},
                            )
                    elif "not a valid option" in str(error) or "Property values were not valid" in str(error):
                        safe_properties = {k: v for k, v in properties.items() if k not in ("industry", "lifecyclestage")}
                        result = self._request(
                            "POST",
                            "/crm/v3/objects/contacts",
                            json_body={"properties": safe_properties},
                        )
                    else:
                        raise
        else:
            try:
                result = self._request(
                    "POST",
                    "/crm/v3/objects/contacts",
                    json_body={"properties": properties},
                )
            except CrmProviderError as error:
                if "not a valid option" in str(error) or "Property values were not valid" in str(error):
                    safe_properties = {k: v for k, v in properties.items() if k not in ("industry", "lifecyclestage")}
                    result = self._request(
                        "POST",
                        "/crm/v3/objects/contacts",
                        json_body={"properties": safe_properties},
                    )
                else:
                    raise

        contact_id = result.get("id") or external_id
        if not isinstance(contact_id, str) or not contact_id:
            raise CrmProviderError(
                "CRM_INVALID_RESPONSE",
                "HubSpot did not return the synchronized contact ID.",
            )
        return contact_id

    def sync_activity(
        self, contact_id: str, activity: Activity, external_id: str | None = None
    ) -> str:
        task_type = {
            "call": "CALL",
            "email": "EMAIL",
            "meeting": "MEETING",
            "reply": "EMAIL",
            "note": "TODO",
        }.get(activity.activity_type, "TODO")
        description = activity.details.get("note", "")
        if external_id:
            task_id = external_id
        else:
            result = self._request(
                "POST",
                "/crm/v3/objects/tasks",
                json_body={
                    "properties": {
                        "hs_timestamp": str(
                            int(activity.occurred_at.timestamp() * 1000)
                        ),
                        "hs_task_subject": (
                            f"SalesGenie {activity.activity_type.title()}"
                        ),
                        "hs_task_body": description,
                        "hs_task_status": "COMPLETED",
                        "hs_task_type": task_type,
                    }
                },
            )
            task_id = result.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise CrmProviderError(
                    "CRM_INVALID_RESPONSE",
                    "HubSpot did not return the synchronized activity ID.",
                )
        try:
            self._request(
                "PUT",
                f"/crm/v4/objects/tasks/{quote(task_id, safe='')}/associations/default/"
                f"contacts/{quote(contact_id, safe='')}",
            )
        except CrmProviderError as error:
            raise CrmProviderError(
                error.code,
                str(error),
                external_id=task_id,
            ) from error
        return task_id

    def stage_for_status(self, lead_status: str) -> str | None:
        return self.deal_stage_mapping.get(lead_status)

    def sync_deal_stage(self, deal_id: str, stage: str) -> str:
        self._request(
            "PATCH",
            f"/crm/v3/objects/deals/{quote(deal_id, safe='')}",
            json_body={"properties": {"dealstage": stage}},
        )
        return deal_id
