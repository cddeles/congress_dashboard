#!/usr/bin/env python3
"""Build a public, normalized Congress dashboard snapshot.

Congress.gov is the primary source for the current member roster. The
unitedstates/congress-legislators public dataset supplements committee
assignments and service details. Chamber leadership is extracted from the
official House Clerk and Senate leadership pages.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "congress.json"
API_BASE = "https://api.congress.gov/v3"
SUPPLEMENT_ROOT = "https://unitedstates.github.io/congress-legislators/"
SOURCES = {
    "members": f"{API_BASE}/member",
    "legislators": SUPPLEMENT_ROOT + "legislators-current.json",
    "committees": SUPPLEMENT_ROOT + "committees-current.json",
    "committee_membership": SUPPLEMENT_ROOT + "committee-membership-current.json",
    "house_leadership": "https://clerk.house.gov/Members/ViewLeadership",
    "senate_leadership": "https://www.senate.gov/senators/leadership.htm",
}
TIMEOUT = 35
HEADERS = {"User-Agent": "CongressDashboard/1.0 (public civic-information project)"}

STATE_NAMES = {
    "AL":"Alabama", "AK":"Alaska", "AZ":"Arizona", "AR":"Arkansas", "CA":"California",
    "CO":"Colorado", "CT":"Connecticut", "DE":"Delaware", "FL":"Florida", "GA":"Georgia",
    "HI":"Hawaii", "ID":"Idaho", "IL":"Illinois", "IN":"Indiana", "IA":"Iowa", "KS":"Kansas",
    "KY":"Kentucky", "LA":"Louisiana", "ME":"Maine", "MD":"Maryland", "MA":"Massachusetts",
    "MI":"Michigan", "MN":"Minnesota", "MS":"Mississippi", "MO":"Missouri", "MT":"Montana",
    "NE":"Nebraska", "NV":"Nevada", "NH":"New Hampshire", "NJ":"New Jersey", "NM":"New Mexico",
    "NY":"New York", "NC":"North Carolina", "ND":"North Dakota", "OH":"Ohio", "OK":"Oklahoma",
    "OR":"Oregon", "PA":"Pennsylvania", "RI":"Rhode Island", "SC":"South Carolina", "SD":"South Dakota",
    "TN":"Tennessee", "TX":"Texas", "UT":"Utah", "VT":"Vermont", "VA":"Virginia", "WA":"Washington",
    "WV":"West Virginia", "WI":"Wisconsin", "WY":"Wyoming", "DC":"District of Columbia",
    "AS":"American Samoa", "GU":"Guam", "MP":"Northern Mariana Islands", "PR":"Puerto Rico",
    "VI":"U.S. Virgin Islands",
}
NAME_TO_STATE = {v.lower(): k for k, v in STATE_NAMES.items()}

HOUSE_ROLE_LABELS = {
    "Speaker of the House": "Speaker of the House",
    "Majority Leader": "Majority Leader",
    "Majority Whip": "Majority Whip",
    "Republican Conference Chair": "Republican Conference Chair",
    "Republican Conference Chairman": "Republican Conference Chair",
    "Republican Policy Committee Chair": "Republican Policy Committee Chair",
    "Minority Leader": "Minority Leader",
    "Democratic Leader": "Minority Leader",
    "Minority Whip": "Minority Whip",
    "Democratic Caucus Chair": "Democratic Caucus Chair",
    "Democratic Caucus Chairman": "Democratic Caucus Chair",
    "Democratic Caucus Vice Chair": "Democratic Caucus Vice Chair",
    "Assistant Democratic Leader": "Assistant Democratic Leader",
}
SENATE_ROLE_LABELS = {
    "President Pro Tempore": "President pro tempore",
    "Senate Majority Leader": "Majority Leader",
    "Majority Whip": "Majority Whip",
    "Republican Conference Chair": "Republican Conference Chair",
    "Republican Policy Committee Chair": "Republican Policy Committee Chair",
    "Vice Chair of the Republican Conference": "Vice Chair, Republican Conference",
    "Vice Chair, Republican Conference": "Vice Chair, Republican Conference",
    "Republican Senatorial Committee Chair": "Republican Senatorial Committee Chair",
    "Democratic Leader Chair of the Conference": "Democratic Leader / Conference Chair",
    "Democratic Leader": "Democratic Leader / Conference Chair",
    "Democratic Whip": "Democratic Whip",
    "Chair of Steering & Policy Committee": "Chair, Democratic Steering & Policy",
    "Chair of Strategic Communications Committee": "Chair, Strategic Communications Committee",
    "Vice Chair of the Conference": "Vice Chair of the Conference",
    "Chair of Outreach": "Chair of Outreach",
    "Democratic Conference Secretary": "Democratic Conference Secretary",
    "Vice Chair of Outreach": "Vice Chair of Outreach",
    "Deputy Democratic Conference Secretary": "Deputy Democratic Conference Secretary",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
    response = session.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    return response.json(), {k.lower(): v for k, v in response.headers.items()}


def get_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    return response.text


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        item = value.get("item")
        if isinstance(item, list):
            return [x for x in item if isinstance(x, dict)]
        if isinstance(item, dict):
            return [item]
        return [value]
    return []


def active_congress(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    relevant_year = today.year if (today.month > 1 or today.day >= 3) else today.year - 1
    start_year = relevant_year if relevant_year % 2 == 1 else relevant_year - 1
    number = ((start_year - 1789) // 2) + 1
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return {"number": number, "startYear": start_year, "endYear": start_year + 2, "ordinal": f"{number}{suffix}"}


def normalize_party(value: str | None) -> str:
    party = (value or "").strip().lower()
    if "republic" in party or party == "r":
        return "Republican"
    if "independent" in party or party in {"i", "id"}:
        return "Independent"
    if "democrat" in party or party == "d":
        return "Democratic"
    if "libertarian" in party or party == "l":
        return "Libertarian"
    return value or "Unknown"


def normalize_name(raw: str) -> str:
    raw = re.sub(r"\b(Rep\.|Sen\.|Senator|Representative)\s*", "", raw, flags=re.I)
    raw = re.sub(r"\([^)]*\)", "", raw).strip(" ,|\t")
    if "," in raw:
        last, first = raw.split(",", 1)
        raw = f"{first.strip()} {last.strip()}"
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def name_key(raw: str) -> tuple[str, str] | None:
    name = normalize_name(raw)
    tokens = re.findall(r"[a-z]+", name.lower())
    tokens = [t for t in tokens if len(t) > 1 and t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    if len(tokens) < 2:
        return None
    return tokens[0], tokens[-1]


def get_api_committees(session: requests.Session, api_key: str, congress_number: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    committees: list[dict[str, Any]] = []
    offset = 0
    limit = 250
    headers_seen: dict[str, str] = {}
    while True:
        payload, headers = get_json(session, f"{API_BASE}/committee/{congress_number}", {
            "api_key": api_key, "format": "json", "limit": limit, "offset": offset
        })
        headers_seen.update(headers)
        batch = as_list(payload.get("committees"))
        if not batch:
            break
        committees.extend(batch)
        pagination = payload.get("pagination") or {}
        count = pagination.get("count")
        offset += len(batch)
        if len(batch) < limit or (count is not None and offset >= int(count)):
            break
        if offset > 2000:
            raise RuntimeError("Committee pagination exceeded the safety limit; refusing to publish partial data.")
    if len(committees) < 10:
        raise RuntimeError(f"Congress.gov returned only {len(committees)} committees for Congress {congress_number}.")
    return committees, headers_seen


def get_api_members(session: requests.Session, api_key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    members: list[dict[str, Any]] = []
    offset = 0
    limit = 250
    headers_seen: dict[str, Any] = {}
    while True:
        payload, headers = get_json(session, SOURCES["members"], {
            "api_key": api_key, "format": "json", "currentMember": "true", "limit": limit, "offset": offset
        })
        headers_seen.update(headers)
        batch = as_list(payload.get("members"))
        if not batch:
            break
        members.extend(batch)
        pagination = payload.get("pagination") or {}
        count = pagination.get("count")
        offset += len(batch)
        if len(batch) < limit or (count is not None and offset >= int(count)):
            break
        if offset > 2000:
            raise RuntimeError("Member pagination exceeded the safety limit; refusing to publish partial data.")
    if len(members) < 400:
        raise RuntimeError(f"Congress.gov returned only {len(members)} current members; refusing to publish a partial roster.")
    unique = {m.get("bioguideId"): m for m in members if m.get("bioguideId")}
    if len(unique) < 400:
        raise RuntimeError("Congress.gov member response did not contain enough unique Bioguide IDs.")
    return list(unique.values()), headers_seen


def fetch_supplement(session: requests.Session) -> tuple[list[dict[str, Any]], Any, dict[str, Any], dict[str, Any]]:
    legislators, legislators_headers = get_json(session, SOURCES["legislators"])
    committees, committees_headers = get_json(session, SOURCES["committees"])
    membership, membership_headers = get_json(session, SOURCES["committee_membership"])
    if not isinstance(legislators, list) or len(legislators) < 400:
        raise RuntimeError("Supplemental current-legislators dataset is empty or incomplete.")
    if not isinstance(membership, dict) or len(membership) < 10:
        raise RuntimeError("Supplemental committee assignment dataset is empty or incomplete.")
    headers = {
        "legislators": legislators_headers,
        "committees": committees_headers,
        "committee_membership": membership_headers,
    }
    return legislators, committees, membership, headers


def committee_lookup(raw: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    items = raw if isinstance(raw, list) else list(raw.values()) if isinstance(raw, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("thomas_id") or item.get("systemCode") or item.get("id")
        if key:
            result[str(key)] = item
    return result


def current_supplement_term(record: dict[str, Any], congress_number: int) -> dict[str, Any]:
    terms = record.get("terms") or []
    if not isinstance(terms, list):
        return {}
    for term in reversed(terms):
        start = str(term.get("start") or "")
        if start[:4].isdigit() and int(start[:4]) <= date.today().year:
            return term
    return terms[-1] if terms else {}


def current_api_term(member: dict[str, Any], congress_number: int) -> dict[str, Any]:
    terms = as_list(member.get("terms"))
    for term in reversed(terms):
        try:
            if int(term.get("congress", -1)) == congress_number:
                return term
        except (TypeError, ValueError):
            pass
    return terms[-1] if terms else {}


def continuous_service_start(record: dict[str, Any], current_term: dict[str, Any]) -> str:
    """Return start of the current uninterrupted service in this chamber."""
    terms = record.get("terms") or []
    if not isinstance(terms, list):
        return str(current_term.get("start") or "")
    wanted_type = current_term.get("type")
    valid = []
    for term in terms:
        if not isinstance(term, dict) or (wanted_type and term.get("type") != wanted_type):
            continue
        try:
            start = date.fromisoformat(str(term.get("start", ""))[:10])
            end = date.fromisoformat(str(term.get("end", ""))[:10])
        except ValueError:
            continue
        valid.append((start, end))
    valid.sort(key=lambda pair: pair[0])
    try:
        cursor = date.fromisoformat(str(current_term.get("start", ""))[:10])
    except ValueError:
        return str(current_term.get("start") or "")
    chain_start = cursor
    for start, end in reversed(valid):
        if start > cursor:
            continue
        if end >= cursor - timedelta(days=3):
            chain_start = min(chain_start, start)
            cursor = start
        elif end < cursor - timedelta(days=3):
            break
    return chain_start.isoformat()


def parse_leadership_page(html: str, roles: dict[str, str],
                          members_by_name: dict[tuple[str, str], str],
                          member_ids: set[str], side: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    extracted: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def normalize_label(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def match_member(node) -> str | None:
        # First try official Biographical Directory links.
        for ancestor in [node, *list(node.parents)[:7]]:
            links = ancestor.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                for member_id in member_ids:
                    if member_id.lower() in href.lower():
                        return member_id

            # Fall back to matching the linked senator's displayed name.
            for link in links:
                key = name_key(link.get_text(" ", strip=True))
                if key and key in members_by_name:
                    return members_by_name[key]

        return None

    for text_node in soup.find_all(string=True):
        label = normalize_label(str(text_node))
        if not label:
            continue

        for original_label, role in roles.items():
            if label != normalize_label(original_label):
                continue

            member_id = match_member(text_node.parent)

            if member_id and member_id in member_ids:
                if (member_id, role) not in seen:
                    extracted.append({
                        "id": member_id,
                        "role": role,
                        "chamber": "Senate" if side == "senate" else "House"
                    })
                    seen.add((member_id, role))

    return extracted

def fetch_leadership(session: requests.Session, members: list[dict[str, Any]]) -> list[dict[str, str]]:
    members_by_name: dict[tuple[str, str], str] = {}
    for m in members:
        key = name_key(m["name"])
        if key:
            members_by_name[key] = m["id"]
    ids = {m["id"] for m in members}
    house_html = get_text(session, SOURCES["house_leadership"])
    senate_html = get_text(session, SOURCES["senate_leadership"])
    house = parse_leadership_page(house_html, HOUSE_ROLE_LABELS, members_by_name, ids, "house")
    senate = parse_leadership_page(senate_html, SENATE_ROLE_LABELS, members_by_name, ids, "senate")
    # Guard against silently publishing an empty/partially parsed leadership structure.
    if len([x for x in house if x["chamber"] == "House"]) < 5:
        raise RuntimeError(f"House leadership parser found only {len(house)} roles. Official page may have changed; no data was published.")
    if len([x for x in senate if x["chamber"] == "Senate"]) < 4:
        raise RuntimeError(f"Senate leadership parser found only {len(senate)} roles. Official page may have changed; no data was published.")
    return house + senate


def build_snapshot() -> dict[str, Any]:
    api_key = os.environ.get("CONGRESS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing CONGRESS_API_KEY. Add it as a GitHub Actions repository secret.")
    session = requests.Session()
    congress = active_congress()
    api_members, api_headers = get_api_members(session, api_key)
    api_committees, api_committee_headers = get_api_committees(session, api_key, congress["number"])
    supplement, raw_committees, raw_membership, supplement_headers = fetch_supplement(session)

    supplement_by_id: dict[str, dict[str, Any]] = {}
    for record in supplement:
        bioguide = (record.get("id") or {}).get("bioguide")
        if bioguide:
            supplement_by_id[bioguide] = record

    committees = committee_lookup(raw_committees)
    assignments: dict[str, list[dict[str, Any]]] = {}
    membership_rows = 0
    for committee_id, rows in raw_membership.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not row.get("bioguide"):
                continue
            bioguide = row["bioguide"]
            assignments.setdefault(bioguide, []).append({
                "committeeId": str(committee_id), "party": row.get("party", ""),
                "rank": row.get("rank"), "title": row.get("title") or "",
            })
            membership_rows += 1
    if membership_rows < 200:
        raise RuntimeError(f"Only {membership_rows} committee assignment rows found; refusing to publish incomplete data.")

    normalized: list[dict[str, Any]] = []
    for api_member in api_members:
        bioguide = api_member.get("bioguideId")
        if not bioguide:
            continue
        supplement_record = supplement_by_id.get(bioguide, {})
        supp_term = current_supplement_term(supplement_record, congress["number"])
        api_term = current_api_term(api_member, congress["number"])
        member_type = str(api_term.get("memberType") or supp_term.get("type") or "").lower()
        chamber_raw = str(api_term.get("chamber") or "").lower()
        if "senator" in member_type or chamber_raw == "senate" or supp_term.get("type") == "sen":
            chamber = "Senate"
            member_type = "sen"
        elif any(x in member_type for x in ("delegate", "resident commissioner")) or supp_term.get("type") == "del":
            chamber = "Non-voting"
            member_type = "del"
        else:
            chamber = "House"
            member_type = "rep"

        raw_name = str(api_member.get("name") or "")
        name = normalize_name(raw_name)
        # Prefer the curated first/middle/last name components where available.
        n = supplement_record.get("name") or {}
        curated_name = " ".join(str(n.get(k) or "").strip() for k in ("first", "middle", "last", "suffix") if str(n.get(k) or "").strip())
        if curated_name:
            name = re.sub(r"\s+", " ", curated_name).strip()
        words = name.split()
        first = words[0] if words else ""
        last = words[-1] if words else ""
        current_party = normalize_party(api_member.get("partyName") or api_term.get("partyName") or supp_term.get("party"))

        state_code = str(api_term.get("stateCode") or supp_term.get("state") or "").upper()
        if len(state_code) != 2:
            state_raw = str(api_member.get("state") or api_term.get("stateName") or "")
            state_code = NAME_TO_STATE.get(state_raw.lower(), state_raw.upper() if len(state_raw) == 2 else "")
        state_name = STATE_NAMES.get(state_code, str(api_member.get("state") or state_code))
        district = api_member.get("district")
        if district is None:
            district = api_term.get("district", supp_term.get("district"))
        class_number = supp_term.get("class")
        start = str(supp_term.get("start") or "")
        if not start and api_term.get("startYear"):
            start = f"{api_term['startYear']}-01-03"
        service_start = continuous_service_start(supplement_record, supp_term) or start
        end = str(supp_term.get("end") or "")
        if not end and api_term.get("endYear"):
            end = f"{api_term['endYear']}-01-03"
        try:
            years = max(0.0, (date.today() - date.fromisoformat(service_start[:10])).days / 365.2425) if service_start else 0.0
        except ValueError:
            years = 0.0

        member_committees: list[dict[str, Any]] = []
        leadership: list[str] = []
        for a in assignments.get(bioguide, []):
            committee = committees.get(a["committeeId"], {})
            committee_name = committee.get("name") or a["committeeId"]
            committee_chamber = str(committee.get("type") or "").title()
            if not committee_chamber:
                committee_chamber = chamber
            member_committees.append({
                **a, "name": committee_name, "chamber": committee_chamber,
                "committeeId": a["committeeId"],
                "url": committee.get("url") or "",
            })
            title = str(a.get("title") or "")
            if "chair" in title.lower() or "ranking member" in title.lower():
                leadership.append(f"{title} · {committee_name}")

        depiction = api_member.get("depiction") or {}
        photo = depiction.get("imageUrl") or f"https://bioguide.congress.gov/bioguide/photo/{bioguide[0]}/{bioguide}.jpg"
        normalized.append({
            "id": bioguide, "name": name, "first": first, "last": last,
            "chamber": chamber, "type": member_type, "party": current_party,
            "caucus": supp_term.get("caucus") or "", "state": state_code,
            "stateName": state_name, "district": district, "class": class_number,
            "start": start, "serviceStart": service_start, "end": end, "years": years,
            "url": supp_term.get("url") or f"https://www.congress.gov/member/{bioguide}",
            "office": supp_term.get("office") or "", "phone": supp_term.get("phone") or "",
            "fax": supp_term.get("fax") or "", "contact": supp_term.get("contact_form") or "",
            "committees": member_committees, "leadership": list(dict.fromkeys(leadership)),
            "photo": photo, "bio": supplement_record.get("bio") or {},
            "voting": chamber in ("House", "Senate"),
        })

    if len(normalized) < 400:
        raise RuntimeError(f"Only {len(normalized)} member records could be normalized; refusing to publish.")
    member_ids = {m["id"] for m in normalized}
    leadership_rows = fetch_leadership(session, normalized)
    leadership_by_id: dict[str, list[str]] = {}
    for row in leadership_rows:
        leadership_by_id.setdefault(row["id"], []).append(row["role"])
    for m in normalized:
        m["leadership"] = list(dict.fromkeys(leadership_by_id.get(m["id"], []) + m["leadership"]))

    house_count = sum(1 for m in normalized if m["chamber"] == "House" and m["voting"])
    senate_count = sum(1 for m in normalized if m["chamber"] == "Senate")
    nonvoting_count = sum(1 for m in normalized if m["chamber"] == "Non-voting")
    if house_count < 400 or senate_count < 90:
        raise RuntimeError(f"Roster validation failed (House={house_count}, Senate={senate_count}); no data was published.")

    normalized.sort(key=lambda m: (m.get("last", "").lower(), m.get("first", "").lower()))
    clean_committee_map = {
        key: {
            "name": value.get("name") or key,
            "chamber": str(value.get("type") or "").title(),
            "url": value.get("url") or "",
        }
        for key, value in committees.items()
    }
    return {
        "generatedAt": utc_now(),
        "congress": congress,
        "memberCount": len(normalized),
        "committeeCount": len(clean_committee_map),
        "officialCommitteeCount": len(api_committees),
        "officialCommittees": api_committees,
        "committeeAssignmentCount": membership_rows,
        "leadershipCount": len(leadership_rows),
        "stats": {"houseMembers": house_count, "senators": senate_count, "nonVoting": nonvoting_count},
        "sources": SOURCES,
        "sourceHeaders": {
            "congressApiRateLimit": api_headers.get("x-ratelimit-limit"),
            "congressApiRateRemaining": api_headers.get("x-ratelimit-remaining"),
            "congressApiCommitteeRateRemaining": api_committee_headers.get("x-ratelimit-remaining"),
            "supplementalLastModified": {k: v.get("last-modified") for k, v in supplement_headers.items()},
        },
        "members": normalized,
        "committeeMap": clean_committee_map,
    }


def main() -> int:
    try:
        snapshot = build_snapshot()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        temp = OUT.with_suffix(".json.tmp")
        temp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(OUT)
        print(
            f"Published {OUT}: {snapshot['memberCount']} members, "
            f"{snapshot['committeeCount']} committees, "
            f"{snapshot['committeeAssignmentCount']} committee assignments, "
            f"{snapshot['leadershipCount']} chamber leadership roles."
        )
        return 0
    except Exception as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
