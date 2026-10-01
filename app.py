import copy
import json
import re
import time
import random
import streamlit as st
from google import genai

st.set_page_config(page_title="ProGen AI Review V7.4", page_icon="🛡️", layout="wide")

SYSTEM = """You are an HSE Incident Investigation Review Assistant.
Review supplied ProGen incident data and prepare a structured investigation draft for human review.

ABSOLUTE RULES
1. Never invent facts.
2. Existing investigation text is not automatically evidence.
3. TEST DATA must never be evidence.
4. If information is absent, use exactly: NOT PROVIDED — USER INPUT REQUIRED
5. If information exists but cannot be established as fact, use: VERIFY
6. If directly supported by supplied source information, use: SUPPORTED
7. Detect contradictions and never silently resolve them.
8. Never assume injury status/count, vehicle speed, mechanical failure, driver behaviour,
   witness evidence, CCTV findings, regulatory notification, police involvement,
   responsible person, risk rating, deadline, training completion, root cause, or immediate cause.
9. Similar incidents are reference only, not proof.
10. Distinguish recommendations from completed actions.
11. Return ONLY valid JSON. No Markdown fences or commentary.
12. Human investigator has final authority."""

SCHEMA = """Return one JSON object with these top-level keys:
schema_version, incident_identity, review_status, verified_facts, conflicts,
missing_information, classification_review, consequence_review, investigation,
actions_recommendations, lesson_learned, risk_assessment_review, regulatory_review,
evidence_review, corrective_training, executive_summary, questions_for_investigator,
progen_write_plan.

Use schema_version "1.0".

review_status: overall, critical_conflicts, missing_critical_information, verification_items.
verified_facts items: fact, status, source, confidence.
conflicts items: field_a, value_a, field_b, value_b, severity, question_for_user.
missing_information items: item, importance, reason, required_action.

classification_review: current_concern_type, current_osha_category,
current_damage_categories, issues_found, proposed_change, status.

consequence_review: human_injury, property_damage, fire, spill, road_accident.

investigation: finding_summary, chronology, primary_causes, secondary_causes,
immediate_causes, root_causes, why_why, other_factors, summary_statement.
Do not fabricate causes to populate arrays. Empty arrays are valid.

actions_recommendations items: action, type, priority, basis, status,
responsibility, deadline. Unknown responsibility/deadline = USER INPUT REQUIRED.

lesson_learned: primary, process_system, behavioural, leadership, communication, other.

risk_assessment_review: review_required, reason, hazard_identified_in_existing_ra,
existing_controls, proposed_controls, ra_update_required.

regulatory_review: review_required, authorities_notified, notification_reference, legal_action.
evidence_review: available, missing_or_required.
corrective_training: recommended, reason, proposals.
executive_summary: text, status, blocked_by.
questions_for_investigator: array.

progen_write_plan items: section, target, operation, proposed_value, status,
requires_user_approval. requires_user_approval must always be true.
Do not add write-plan entries whose value is only NOT PROVIDED — USER INPUT REQUIRED.

Allowed statuses: SUPPORTED, VERIFY, USER INPUT REQUIRED, DRAFT."""

REQUIRED = [
    "incident_identity", "review_status", "verified_facts", "conflicts",
    "missing_information", "classification_review", "consequence_review",
    "investigation", "actions_recommendations", "lesson_learned",
    "risk_assessment_review", "regulatory_review", "evidence_review",
    "corrective_training", "executive_summary", "questions_for_investigator",
    "progen_write_plan"
]

TEST_FIELDS = {"P9_OTHER_CAUSES", "P9_SUMMARY_STATMENT", "P9_EXECUTIVE_SUMMARY"}
TECH_FIELDS = {"P9_DAMAGE_ID", "P9_DETAILS_ID", "P9_DETAILS_COUNT", "P9_READ_ONLY", "P9_BTN_LABEL"}
TEST_REPORT_PREFIXES = ("ChronologyAdd Event", "Primary Causes", "Immediate Cause", "Root Cause", "Action CAPA")

def parse_json_loose(text):
    if not text or not text.strip():
        raise ValueError("Empty JSON/AI response.")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object found in Gemini response.")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])

    raise ValueError("Incomplete or invalid JSON returned by Gemini.")

def sanitize(src):
    data = copy.deepcopy(src)

    if isinstance(data.get("page"), dict):
        data["page"].pop("url", None)

    fields = data.setdefault("fields", {})
    excluded = list(data.get("excludedTestData", []))

    for key in list(fields):
        k = key.lower()
        remove = (
            key in {"pSalt", "pContext", "pReloadOnSubmit"}
            or any(x in k for x in ["session", "checksum", "csrf", "token",
                                    "worksheet_id", "report_id", "row_select"])
            or k.endswith("_app_user")
            or k.endswith("_view_mode")
            or k.startswith("control_")
            or k == "apexcbmdummyselection"
        )
        if remove:
            fields.pop(key, None)

    fields.pop("P9_JSON", None)

    for key in TEST_FIELDS:
        if key in fields:
            excluded.append({
                "source": key,
                "reason": "Known mapping/test data; value excluded from AI evidence."
            })
            fields.pop(key, None)

    for key in TECH_FIELDS:
        fields.pop(key, None)

    for key in list(fields):
        value = fields[key].get("value", "") if isinstance(fields[key], dict) else fields[key]
        value = str(value).strip()
        if not value or value in {"Select-", "- Select -"}:
            fields.pop(key, None)

    kept = []
    for report in data.get("reports", []) or []:
        title = str(report.get("title", "")).strip()
        if any(title == p or title.startswith(p) for p in TEST_REPORT_PREFIXES):
            excluded.append({
                "source": "Report: " + title,
                "reason": "Mapping/test records excluded from AI evidence."
            })
        else:
            kept.append(report)
    data["reports"] = kept

    if isinstance(data.get("whyWhy"), list) and data["whyWhy"]:
        excluded.append({
            "source": "Why Why Analysis Tree",
            "reason": f"{len(data['whyWhy'])} mapping/test nodes excluded from AI evidence."
        })
    data["whyWhy"] = []
    data["excludedTestData"] = excluded

    data["aiEvidenceRules"] = {
        "test": "Excluded test data must never be reconstructed or assumed.",
        "uncertain": "Use VERIFY when evidence is insufficient.",
        "missing": "Use NOT PROVIDED — USER INPUT REQUIRED when required information is absent.",
        "no_invention": "Never invent facts, causes, injuries, witnesses, CCTV, notifications or completed actions."
    }
    return data

def validate_review(data):
    if not isinstance(data, dict):
        raise ValueError("AI Review must be a JSON object.")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError("Gemini response missing sections: " + ", ".join(missing))
    for item in data.get("progen_write_plan", []):
        if isinstance(item, dict):
            item["requires_user_approval"] = True
    return data

def api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return ""

def interaction_text(interaction):
    # google-genai 2.x new Interactions schema: model text is in model_output steps.
    parts = []
    for step in getattr(interaction, "steps", []) or []:
        step_type = getattr(step, "type", None)
        if step_type != "model_output":
            continue
        for content in getattr(step, "content", []) or []:
            if getattr(content, "type", None) == "text":
                txt = getattr(content, "text", None)
                if txt:
                    parts.append(txt)

    # Keep a compatibility fallback in case a newer 2.x SDK exposes output_text.
    if not parts:
        txt = getattr(interaction, "output_text", None)
        if txt:
            parts.append(txt)

    if not parts:
        raise RuntimeError("Gemini interaction completed but no model text was returned.")
    return "\n".join(parts)

def _error_status(exc):
    """Best-effort extraction of HTTP/status code from google-genai exceptions."""
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            m = re.search(r"\b(\d{3})\b", value)
            if m:
                return int(m.group(1))

    text = str(exc)
    for pattern in (
        r"Error code:\s*(\d{3})",
        r"'code'\s*:\s*(\d{3})",
        r'"code"\s*:\s*(\d{3})',
        r"\b(408|429|5\d\d)\b",
    ):
        m = re.search(pattern, text)
        if m:
            return int(m.group(1))
    return None


def _error_machine_code(exc):
    text = str(exc)
    # New Interactions API commonly returns these machine-readable codes.
    for code in (
        "quota_exceeded", "rate_limit_exceeded", "too_many_requests",
        "service_unavailable", "deadline_exceeded", "api_error",
        "invalid_request", "permission_denied", "not_found"
    ):
        if code.lower() in text.lower():
            return code
    return ""


def _retry_after_seconds(exc):
    text = str(exc)
    patterns = (
        r"retry(?:Delay|_delay| after)?[^\d]{0,20}(\d+(?:\.\d+)?)\s*s",
        r"retry in\s+(\d+(?:\.\d+)?)\s*s",
        r"try again in\s+(\d+(?:\.\d+)?)\s*s",
    )
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _quota_diagnostic(exc):
    text = str(exc)
    low = text.lower()
    machine = _error_machine_code(exc)
    retry_after = _retry_after_seconds(exc)

    if "quota_exceeded" in low or "requestsperday" in low or "perday" in low or "daily quota" in low:
        kind = "Daily quota"
        advice = "Do not retry now. Wait for the project quota to reset, then try once."
    elif "token" in low and ("perminute" in low or "per minute" in low or "tpm" in low):
        kind = "Token-per-minute limit"
        advice = "Wait before trying again. Reducing the incident payload can also help."
    elif "rate_limit_exceeded" in low or "too_many_requests" in low or "perminute" in low or "per minute" in low or "rpm" in low:
        kind = "Short-term rate limit"
        advice = "Wait before trying again. V7.4 will not automatically send more requests."
    else:
        kind = "Gemini quota/rate limit"
        advice = "Check the project's active limits in Google AI Studio before retrying."

    return {
        "http_status": _error_status(exc),
        "machine_code": machine or "not supplied",
        "category": kind,
        "retry_after_seconds": retry_after,
        "advice": advice,
    }


def _capacity_diagnostic(exc):
    return {
        "http_status": _error_status(exc),
        "machine_code": _error_machine_code(exc) or "service_unavailable",
        "category": "Temporary Gemini capacity",
        "retry_after_seconds": _retry_after_seconds(exc),
        "advice": "V7.4 permits only one delayed application-level retry for a 503.",
    }


def call_gemini(payload):
    if not api_key():
        raise RuntimeError("GEMINI_API_KEY is not configured in Streamlit Secrets.")

    client = genai.Client(api_key=api_key())
    prompt = SYSTEM + "\n\n" + SCHEMA + "\n\nPROGEN INCIDENT DATA:\n" + json.dumps(payload, ensure_ascii=False)

    status_box = st.empty()
    st.session_state.pop("api_diagnostic", None)

    # Quota-safe application policy:
    # - 429: stop immediately at app level.
    # - 503: one app-level delayed retry only.
    # - Other errors: fail immediately.
    # Note: the official SDK may itself perform transient retries internally.
    max_app_attempts = 2

    for attempt in range(1, max_app_attempts + 1):
        try:
            if attempt == 1:
                status_box.info("Sending incident to Gemini…")
            else:
                status_box.info("One quota-safe retry is being sent to Gemini…")

            interaction = client.interactions.create(
                model="gemini-3.8-flash",
                input=prompt
            )

            status_box.success(f"Gemini responded successfully on application attempt {attempt}/{max_app_attempts}.")
            return interaction_text(interaction)

        except Exception as exc:
            code = _error_status(exc)

            if code == 429:
                diag = _quota_diagnostic(exc)
                st.session_state.api_diagnostic = diag
                status_box.error(
                    f"Gemini returned HTTP 429 — {diag['category']}. "
                    "V7.4 stopped immediately and did not send another application-level request."
                )
                raise RuntimeError(
                    f"Gemini quota/rate limit reached (HTTP 429; {diag['category']}). "
                    f"{diag['advice']} Your prepared ProGen payload remains available."
                ) from exc

            if code == 503:
                diag = _capacity_diagnostic(exc)
                st.session_state.api_diagnostic = diag

                if attempt >= max_app_attempts:
                    status_box.error(
                        "Gemini is still at temporary capacity after the single V7.4 retry."
                    )
                    raise RuntimeError(
                        "Gemini is temporarily unavailable (HTTP 503) after one quota-safe retry. "
                        "Your prepared ProGen payload remains available; try again later."
                    ) from exc

                # Prefer server-supplied delay if present; otherwise wait 15 seconds.
                delay = diag.get("retry_after_seconds") or 15.0
                delay = max(5.0, min(float(delay), 60.0))
                status_box.warning(
                    f"Gemini is temporarily at capacity (HTTP 503). "
                    f"V7.4 will make one retry in about {int(round(delay))} seconds. "
                    "Please keep this page open."
                )
                time.sleep(delay)
                continue

            # Do not add app-level retries for 408/500/504 etc.; the SDK already
            # provides transient retry handling and extra app retries can consume quota.
            st.session_state.api_diagnostic = {
                "http_status": code or "unknown",
                "machine_code": _error_machine_code(exc) or "not supplied",
                "category": "Non-429/503 API error",
                "retry_after_seconds": _retry_after_seconds(exc),
                "advice": "No additional V7.4 application-level retry was sent."
            }
            raise


def show_api_diagnostic():
    diag = st.session_state.get("api_diagnostic")
    if not diag:
        return

    st.subheader("Gemini API diagnostic")
    cols = st.columns(3)
    cols[0].metric("HTTP status", str(diag.get("http_status", "—")))
    cols[1].metric("Category", str(diag.get("category", "—")))
    cols[2].metric("API code", str(diag.get("machine_code", "—")))

    retry_after = diag.get("retry_after_seconds")
    if retry_after:
        st.info(f"Google response indicated a retry delay of approximately {retry_after:g} seconds.")

    st.write(diag.get("advice", ""))

    if diag.get("http_status") == 429:
        st.caption(
            "Gemini limits may be RPM, TPM or RPD and are applied per project. "
            "Daily request quotas reset at midnight Pacific time."
        )

def show_items(title, items):
    st.subheader(title)
    if not items:
        st.caption("No items returned.")
        return
    for i, item in enumerate(items, 1):
        if isinstance(item, dict):
            text = (item.get("text") or item.get("fact") or item.get("item")
                    or item.get("action") or item.get("question_for_user") or str(item))
            st.markdown(f"**{i}. {text}**")
            if item.get("status"):
                st.caption(item["status"])
            extra = {k: v for k, v in item.items()
                     if k not in {"text", "fact", "item", "action", "question_for_user", "status"}
                     and v not in ("", None, [], {})}
            if extra:
                st.json(extra, expanded=False)
        else:
            st.write(f"{i}. {item}")

def show_review(r):
    ident = r.get("incident_identity", {})
    st.header("AI Review — " + str(ident.get("reference_no", "Incident")))
    st.caption(" | ".join(str(ident.get(k, "")) for k in ["title", "incident_date", "location"]))

    status = r.get("review_status", {})
    cols = st.columns(4)
    metrics = [
        ("Status", "overall"),
        ("Critical Conflicts", "critical_conflicts"),
        ("Critical Missing", "missing_critical_information"),
        ("Verify Items", "verification_items"),
    ]
    for col, (label, key) in zip(cols, metrics):
        col.metric(label, status.get(key, "—"))

    tabs = st.tabs([
        "Priority", "Facts & Consequences", "Investigation", "Actions / Lessons",
        "Risk / Regulatory / Evidence", "Executive Summary", "ProGen Write Plan", "Raw JSON"
    ])

    with tabs[0]:
        show_items("Conflicts", r.get("conflicts", []))
        show_items("Missing Information", r.get("missing_information", []))
        show_items("Questions for Investigator", r.get("questions_for_investigator", []))

    with tabs[1]:
        show_items("Verified Facts", r.get("verified_facts", []))
        st.subheader("Classification")
        st.json(r.get("classification_review", {}))
        st.subheader("Consequences")
        st.json(r.get("consequence_review", {}))

    with tabs[2]:
        inv = r.get("investigation", {})
        for key, label in [
            ("finding_summary", "Finding Summary"), ("chronology", "Chronology"),
            ("primary_causes", "Primary Causes"), ("secondary_causes", "Secondary Causes"),
            ("immediate_causes", "Immediate Causes"), ("root_causes", "Root Causes"),
            ("why_why", "Why-Why"), ("other_factors", "Other Factors")
        ]:
            show_items(label, inv.get(key, []))
        st.subheader("Summary Statement")
        st.json(inv.get("summary_statement", {}))

    with tabs[3]:
        show_items("Actions & Recommendations", r.get("actions_recommendations", []))
        st.subheader("Lesson Learned")
        st.json(r.get("lesson_learned", {}))
        st.subheader("Corrective Training")
        st.json(r.get("corrective_training", {}))

    with tabs[4]:
        st.subheader("Risk Assessment")
        st.json(r.get("risk_assessment_review", {}))
        st.subheader("Regulatory")
        st.json(r.get("regulatory_review", {}))
        st.subheader("Evidence")
        st.json(r.get("evidence_review", {}))

    with tabs[5]:
        e = r.get("executive_summary", {})
        st.caption(str(e.get("status", "DRAFT")))
        st.text_area("Draft Executive Summary", str(e.get("text", "")), height=260)
        if e.get("blocked_by"):
            st.warning("Blocked by: " + "; ".join(map(str, e["blocked_by"])))

    with tabs[6]:
        st.warning("V7.4 never writes or submits to ProGen. Final Save/Submit remains manual.")
        for i, item in enumerate(r.get("progen_write_plan", [])):
            with st.expander(f"{i+1}. {item.get('section','Section')} — {item.get('target','')}"):
                st.write("Status:", item.get("status", ""))
                st.write("Operation:", item.get("operation", ""))
                value = item.get("proposed_value", "")
                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.text_area("Proposed value", str(value), height=120, key=f"plan_{i}")
                st.checkbox("Reviewed / approved for later application", key=f"approve_{i}")

    with tabs[7]:
        st.json(r, expanded=False)

st.title("🛡️ ProGen AI Incident Review — V7.4")
st.caption("Read → sanitize → Gemini review → human approval. Nothing is written to ProGen.")

with st.sidebar:
    st.caption("Model: gemini-3.8-flash")
    st.caption("Google Gen AI SDK 2.x · Interactions API · Quota-safe retry")
    if api_key():
        st.success("Gemini API key configured")
    else:
        st.warning("GEMINI_API_KEY not configured")

uploaded = st.file_uploader("Upload extracted JSON (optional)", type=["json", "txt"])
default = uploaded.getvalue().decode("utf-8", errors="replace") if uploaded else ""

raw = st.text_area(
    "Paste ProGen JSON",
    default,
    height=280,
    placeholder="Paste window.PROGEN_FINAL_AI_PAYLOAD or window.PROGEN_AI_INPUT JSON"
)

c1, c2, c3 = st.columns(3)
prepare_btn = c1.button("1. Prepare / Validate", use_container_width=True)
generate_btn = c2.button("2. Generate AI Review", type="primary", use_container_width=True)
clear_btn = c3.button("Clear", use_container_width=True)

if clear_btn:
    for k in ["payload", "review", "raw_ai"]:
        st.session_state.pop(k, None)
    st.rerun()

def prepare_payload():
    if not raw.strip():
        raise ValueError("Paste or upload ProGen JSON first.")
    return sanitize(parse_json_loose(raw))

if prepare_btn:
    try:
        st.session_state.payload = prepare_payload()
        st.success("Payload prepared and sanitized.")
    except Exception as exc:
        st.error(str(exc))

if generate_btn:
    try:
        payload = prepare_payload()
        st.session_state.payload = payload
        with st.spinner("Gemini is reviewing the incident..."):
            raw_ai = call_gemini(payload)
            st.session_state.raw_ai = raw_ai
            st.session_state.review = validate_review(parse_json_loose(raw_ai))
        st.success("AI Review generated. Nothing was written to ProGen.")
    except Exception as exc:
        st.error("AI Review failed: " + str(exc))
        if st.session_state.get("raw_ai"):
            with st.expander("Raw Gemini response"):
                st.code(st.session_state.raw_ai)

show_api_diagnostic()

if "payload" in st.session_state:
    with st.expander("Sanitized payload sent to Gemini"):
        payload = st.session_state.payload
        st.write(
            f"Reports: {len(payload.get('reports', []))} | "
            f"Why nodes: {len(payload.get('whyWhy', []))} | "
            f"Excluded test sources: {len(payload.get('excludedTestData', []))}"
        )
        st.json(payload, expanded=False)

if "review" in st.session_state:
    show_review(st.session_state.review)
