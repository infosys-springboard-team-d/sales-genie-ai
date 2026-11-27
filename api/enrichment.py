from __future__ import annotations

from typing import Any


_INDUSTRY_PROFILES: dict[str, dict[str, Any]] = {
    "software": {
        "sizes": ["250-500 employees", "100-250 employees", "500-1,000 employees"],
        "revenues": ["$45M - $60M", "$20M - $35M", "$75M - $110M"],
        "locations": ["San Francisco, CA", "Seattle, WA", "Austin, TX"],
        "stages": ["Series C • $28M", "Series B • $18M", "Series D • $55M"],
        "stack": ["AWS", "Python", "React", "Node.js", "Kubernetes", "PostgreSQL"],
    },
    "technology": {
        "sizes": ["250-500 employees", "150-300 employees", "500-1,000 employees"],
        "revenues": ["$40M - $60M", "$25M - $40M", "$80M - $120M"],
        "locations": ["San Jose, CA", "Austin, TX", "Seattle, WA"],
        "stages": ["Series C • $32M", "Series B • $22M", "Growth Equity"],
        "stack": ["AWS", "Python", "TypeScript", "Docker", "Kubernetes", "PostgreSQL"],
    },
    "cloud": {
        "sizes": ["200-500 employees", "100-250 employees"],
        "revenues": ["$35M - $55M", "$18M - $30M"],
        "locations": ["Seattle, WA", "San Francisco, CA"],
        "stages": ["Series C • $30M", "Series B • $16M"],
        "stack": ["AWS", "Go", "Terraform", "Kubernetes", "Prometheus", "PostgreSQL"],
    },
    "biotech": {
        "sizes": ["150-350 employees", "100-250 employees", "300-600 employees"],
        "revenues": ["$30M - $50M", "$15M - $28M", "$60M - $95M"],
        "locations": ["Boston, MA", "San Diego, CA", "Raleigh, NC"],
        "stages": ["Series C • $40M", "Series B • $24M", "Private / R&D"],
        "stack": ["Python", "AWS", "Snowflake", "Veeva", "R", "PostgreSQL"],
    },
    "health": {
        "sizes": ["250-500 employees", "500-1,000 employees", "100-250 employees"],
        "revenues": ["$45M - $75M", "$80M - $120M", "$20M - $35M"],
        "locations": ["Boston, MA", "Minneapolis, MN", "Nashville, TN"],
        "stages": ["Series C • $35M", "Private Growth", "Series B • $20M"],
        "stack": ["Azure", "FHIR API", "Python", "Snowflake", "React", "PostgreSQL"],
    },
    "finance": {
        "sizes": ["200-500 employees", "500-1,000 employees", "100-250 employees"],
        "revenues": ["$50M - $85M", "$90M - $140M", "$25M - $45M"],
        "locations": ["New York, NY", "Chicago, IL", "Charlotte, NC"],
        "stages": ["Private Equity", "Series C • $45M", "Growth Stage"],
        "stack": ["AWS", "Java", "Python", "Snowflake", "Kafka", "PostgreSQL"],
    },
    "manufacturing": {
        "sizes": ["500-1,000 employees", "250-500 employees", "1,000+ employees"],
        "revenues": ["$75M - $120M", "$40M - $65M", "$150M+"],
        "locations": ["Detroit, MI", "Cleveland, OH", "Pittsburgh, PA"],
        "stages": ["Established Private", "Growth Equity", "Mid-Market"],
        "stack": ["SAP", "Azure", "Oracle ERP", "Python", "Power BI", "SQL Server"],
    },
    "logistics": {
        "sizes": ["250-500 employees", "500-1,000 employees", "150-300 employees"],
        "revenues": ["$45M - $70M", "$80M - $115M", "$25M - $40M"],
        "locations": ["Chicago, IL", "Atlanta, GA", "Dallas, TX"],
        "stages": ["Series C • $25M", "Private Growth", "Series B • $15M"],
        "stack": ["AWS", "Python", "React", "Kafka", "PostgreSQL", "Snowflake"],
    },
    "aerospace": {
        "sizes": ["500-1,000 employees", "250-500 employees"],
        "revenues": ["$90M - $150M", "$50M - $80M"],
        "locations": ["Los Angeles, CA", "Huntsville, AL", "Seattle, WA"],
        "stages": ["Series C • $50M", "Private Defense/Tech"],
        "stack": ["AWS GovCloud", "C++", "Python", "MATLAB", "Kubernetes", "PostgreSQL"],
    },
    "consulting": {
        "sizes": ["100-250 employees", "250-500 employees", "50-150 employees"],
        "revenues": ["$18M - $35M", "$40M - $65M", "$10M - $18M"],
        "locations": ["New York, NY", "Washington, DC", "Chicago, IL"],
        "stages": ["Partner-Owned", "Mid-Market", "Private Growth"],
        "stack": ["Salesforce", "HubSpot", "Python", "React", "Snowflake", "PostgreSQL"],
    },
    "education": {
        "sizes": ["250-500 employees", "100-250 employees", "500-1,000 employees"],
        "revenues": ["$20M - $40M", "$12M - $22M", "$50M - $80M"],
        "locations": ["Chennai, IN", "Boston, MA", "Austin, TX"],
        "stages": ["Institutional", "Series B • $15M", "Established"],
        "stack": ["AWS", "Python", "React", "Canvas LMS", "Node.js", "PostgreSQL"],
    },
    "hospitality": {
        "sizes": ["100-250 employees", "250-500 employees", "50-150 employees"],
        "revenues": ["$15M - $30M", "$35M - $55M", "$8M - $15M"],
        "locations": ["Miami, FL", "Las Vegas, NV", "Denver, CO"],
        "stages": ["Private Growth", "Mid-Market", "Series B • $12M"],
        "stack": ["AWS", "Stripe", "Salesforce", "React", "Node.js", "PostgreSQL"],
    },
    "beauty": {
        "sizes": ["25-75 employees", "50-150 employees"],
        "revenues": ["$3M - $8M", "$8M - $16M"],
        "locations": ["Los Angeles, CA", "New York, NY", "Austin, TX"],
        "stages": ["Seed • $3.5M", "Bootstrapped Growth"],
        "stack": ["Shopify", "HubSpot", "Stripe", "React", "Square", "PostgreSQL"],
    },
    "retail": {
        "sizes": ["150-350 employees", "250-500 employees"],
        "revenues": ["$25M - $45M", "$45M - $75M"],
        "locations": ["Austin, TX", "New York, NY", "Portland, OR"],
        "stages": ["Series B • $18M", "Private Growth"],
        "stack": ["Shopify Plus", "AWS", "React", "Snowflake", "Stripe", "PostgreSQL"],
    },
}

_DEFAULT_PROFILE: dict[str, Any] = {
    "sizes": ["100-250 employees", "250-500 employees", "50-150 employees"],
    "revenues": ["$20M - $35M", "$45M - $60M", "$10M - $20M"],
    "locations": ["San Francisco, CA", "New York, NY", "Austin, TX"],
    "stages": ["Series B • $18M", "Series C • $28M", "Growth Stage"],
    "stack": ["AWS", "Python", "React", "Node.js", "Docker", "PostgreSQL"],
}


def get_lead_firmographics(
    lead_id: int, industry: str | None, email: str | None = None
) -> dict[str, Any]:
    """Return consistent, industry-aligned company profile attributes for any lead."""
    ind_lower = (industry or "").lower()
    profile = _DEFAULT_PROFILE
    for key, candidate in _INDUSTRY_PROFILES.items():
        if key in ind_lower:
            profile = candidate
            break

    idx = abs(int(lead_id))
    sizes = profile["sizes"]
    revenues = profile["revenues"]
    locations = profile["locations"]
    stages = profile["stages"]

    if email and "@" in email:
        domain = email.split("@")[-1].lower()
        if any(free in domain for free in ("gmail", "yahoo", "hotmail", "outlook")):
            lead_source = "Inbound Web Inquiry"
        else:
            lead_source = "Corporate Website / Direct Inbound"
    else:
        lead_source = "B2B Direct Referral"

    return {
        "company_size": sizes[idx % len(sizes)],
        "annual_revenue": revenues[idx % len(revenues)],
        "location": locations[idx % len(locations)],
        "funding_stage": stages[idx % len(stages)],
        "tech_stack": list(profile["stack"]),
        "lead_source": lead_source,
    }
