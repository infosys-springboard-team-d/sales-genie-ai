from __future__ import annotations

import os
from math import ceil

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 10
ANALYSIS_TIMEOUT = 180
STATUSES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]


class ApiRequestError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def api_request(
    method: str,
    path: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    **kwargs: object,
) -> dict | list:
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            timeout=timeout,
            **kwargs,
        )
    except requests.Timeout as error:
        raise ApiRequestError("The API request timed out. Please retry.") from error
    except requests.ConnectionError as error:
        raise ApiRequestError(
            f"Cannot reach the SalesGenie API at {API_BASE_URL}."
        ) from error
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        error_body = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error_body, dict):
            error_body = {}
        message = error_body.get("message", f"API request failed ({response.status_code}).")
        raise ApiRequestError(message, code=error_body.get("code"))
    if not isinstance(body, (dict, list)):
        raise ApiRequestError("The API returned an unexpected response.")
    return body


def show_api_error(error: ApiRequestError) -> None:
    st.error(str(error))




def fetch_all_leads() -> list[dict]:
    first_page = api_request(
        "GET", "/api/v1/leads", params={"page": 1, "page_size": 100}
    )
    leads = first_page["items"]
    page_count = ceil(first_page["total"] / 100)
    for page_number in range(2, page_count + 1):
        page_result = api_request(
            "GET",
            "/api/v1/leads",
            params={"page": page_number, "page_size": 100},
        )
        leads.extend(page_result["items"])
    return leads


