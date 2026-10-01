import copy
import json
import re
import time
import random
import streamlit as st
from google import genai

st.set_page_config(page_title="ProGen AI Review V7.6", page_icon="🛡️", layout="wide")

SYSTEM = """You are an HSE Incident Investigation Review Assistant.
Review supplied ProGen incident data and prepare a structured investigation draft for human review.

ABSOLUTE EVIDENCE AND PROVENANCE RULES
1. Never invent facts.
2. Never strengthen, embellish, reinterpret, or upgrade source wording.
   Examples:
   - "vehicle collision" must not become "vehicle lost control" unless the source explicitly says so.
   - a record saying "no injuries" must not become "witness testimony confirmed no injuries"
     unless its provenance is explicitly established as a witness statement.
   - equipment damage must not become failure of a shear valve, emergency stop, bollard,
     protective system, maintenance system, or design unless the source explicitly supports it.
3. Existing investigation analysis, causes, summaries, recommendations, CAPA, Why-Why,
   or AI-generated text are NOT independent evidence merely because they exist in ProGen.
4. TEST DATA must never be evidence and must never be reconstructed from context.
5. Historical/similar incidents are reference only. They are not evidence that the same cause,
   failure, classification, or control applies to the current incident.
6. Preserve source provenance. If provenance is unclear, say so and use VERIFY.
7. Do not call a statement "witness testimony", "CCTV evidence", "police evidence",
   "engineering finding", or similar unless the supplied source explicitly establishes that provenance.
8. A SOURCE CONFLICT exists only when two supplied sources make incompatible factual claims.
   A classification question, possible business-rule mismatch, missing field, or AI suggestion is NOT a source conflict.
9. CRITICAL MISSING INFORMATION is information demonstrably necessary to resolve an existing
   material issue in the supplied record. Do not place speculative investigation ideas here.
10. VERIFICATION REQUIRED means information exists but its accuracy, provenance, interpretation,
    terminology, or applicability cannot be established from the supplied data.
11. AI-SUGGESTED INVESTIGATION CHECK means an additional line of inquiry proposed by the AI.
    It is not evidence, not a fact, not a confirmed deficiency, and not automatically required.
12. Never assume injury status/count, vehicle speed, tyre/mechanical failure, driver behaviour,
    loss of control, witness evidence, CCTV findings, police involvement, regulatory notification,
    responsible person, risk rating, deadline, training completion, root cause, immediate cause,
    emergency shutdown response, shear-valve performance, bollard presence/adequacy, or control failure.
13. Do not infer that two differently named ProGen fields mean the same business concept.
    Example: "Recordable Incident" and "OSHA Category" may be related, but unless the supplied
    data defines their relationship, flag terminology/applicability for verification rather than
    declaring a contradiction.
14. For classification, describe the current recorded value and the factual basis for review.
    Do not decide applicability when the governing ProGen/OSHA/business rule is not supplied.
15. Recommendations must be clearly distinguished from actions already completed.
16. If information is absent and genuinely required, use exactly:
    "NOT PROVIDED — USER INPUT REQUIRED"
17. If information exists but cannot be established as fact, use:
    "VERIFY"
18. If directly supported by supplied source information, use:
    "SUPPORTED"
19. Draft narrative or proposed investigation content must use:
    "DRAFT"
20. Return ONLY valid JSON. No Markdown fences or commentary.
21. The human investigator has final authority over all investigation content."""

SCHEMA = """Return one JSON object with these top-level keys:
schema_version, incident_identity, review_status, verified_facts, source_conflicts,
critical_missing_information, verification_required, ai_suggested_investigation_checks,
classification_review, consequence_review, investigation, actions_recommendations,
lesson_learned, risk_assessment_review, regulatory_review, evidence_review,
corrective_training, executive_summary, questions_for_investigator, progen_write_plan.

Use schema_version "1.1".

review_status:
- overall
- critical_conflicts
- missing_critical_information
- verification_items
- suggested_investigation_checks

EVERY factual/proposed analytical item should include provenance where practical:
- statement or fact
- evidence_basis: the exact factual basis without adding facts
- source: source field/report/table when identifiable
- confidence: HIGH, MEDIUM, or LOW
- status: SUPPORTED, VERIFY, USER INPUT REQUIRED, or DRAFT

verified_facts:
Only facts directly supported by supplied incident/consequence data.
Each item:
{
  "fact": "",
  "evidence_basis": "",
  "source": "",
  "confidence": "HIGH|MEDIUM|LOW",
  "status": "SUPPORTED"
}

source_conflicts:
ONLY incompatible factual claims in supplied sources.
Each item:
{
  "claim_a": "",
  "source_a": "",
  "claim_b": "",
  "source_b": "",
  "why_conflict": "",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "question_for_user": "",
  "status": "VERIFY"
}

critical_missing_information:
Only information demonstrably needed to resolve a material issue already present in the record.
Each item:
{
  "item": "",
  "evidence_basis": "",
  "source": "",
  "importance": "CRITICAL|HIGH|MEDIUM|LOW",
  "reason": "",
  "required_action": "USER INPUT REQUIRED",
  "status": "USER INPUT REQUIRED"
}

verification_required:
Existing information whose truth, provenance, terminology, interpretation, or applicability is uncertain.
Each item:
{
  "item": "",
  "evidence_basis": "",
  "source": "",
  "reason": "",
  "question_for_user": "",
  "status": "VERIFY"
}

ai_suggested_investigation_checks:
Optional AI-proposed lines of inquiry. These MUST NOT be presented as known deficiencies or missing facts.
Each item:
{
  "check": "",
  "why_it_may_help": "",
  "triggering_fact": "",
  "status": "DRAFT",
  "disclaimer": "AI-SUGGESTED CHECK — NOT EVIDENCE"
}

classification_review:
- current_concern_type
- current_osha_category
- current_damage_categories
- recorded_values
- issues_found
- terminology_or_rule_uncertainties
- proposed_change
- evidence_basis
- source
- status
Do not declare a classification conflict unless governing definitions supplied in the payload establish it.

consequence_review contains:
human_injury, property_damage, fire, spill, road_accident.
Each consequence should include:
- status
- known
- unknown
- conflicts
- evidence_basis
- source
Do not convert a collision involving a vehicle into "loss of control", "roadway event", or Road Accident
unless explicitly supported.

investigation:
- finding_summary
- chronology
- primary_causes
- secondary_causes
- immediate_causes
- root_causes
- why_why
- other_factors
- summary_statement
Do not fabricate causes to populate arrays. Empty arrays are valid and preferred over unsupported causes.
Every proposed cause/finding must include evidence_basis, source, confidence, and status.
If causation is not established, use VERIFY or leave the cause array empty.

actions_recommendations:
Each item:
- action
- type
- priority
- basis
- evidence_basis
- source
- status
- responsibility
- deadline
Unknown responsibility/deadline = USER INPUT REQUIRED.
A proposed action is DRAFT unless supplied data proves it is already completed.

lesson_learned:
primary, process_system, behavioural, leadership, communication, other.
Each may be blank when evidence is insufficient. Do not create behavioural/leadership lessons without basis.

risk_assessment_review:
review_required, reason, hazard_identified_in_existing_ra, existing_controls,
proposed_controls, ra_update_required, evidence_basis, source, status.

regulatory_review:
review_required, authorities_notified, notification_reference, legal_action,
evidence_basis, source, status.
Do not assume police/regulator notification is required unless the applicable rule is supplied.

evidence_review:
- available: only evidence explicitly shown as available
- missing_or_required: only evidence demonstrably referenced/required by the supplied record
- suggested_evidence_checks: optional AI suggestions clearly marked DRAFT

corrective_training:
recommended, reason, proposals, evidence_basis, source, status.
Do not recommend training merely because an incident occurred.

executive_summary:
text, status, blocked_by, evidence_basis.
The summary must not contain any factual statement stronger than the supported source data.

questions_for_investigator:
Questions should identify their category:
SOURCE_CONFLICT, CRITICAL_MISSING, VERIFICATION, or AI_SUGGESTED_CHECK.

progen_write_plan:
Each item:
- section
- target
- operation
- proposed_value
- evidence_basis
- source
- confidence
- status
- requires_user_approval
requires_user_approval must always be true.
Do not add write-plan entries whose value is only NOT PROVIDED — USER INPUT REQUIRED.
Do not propose writing AI-suggested checks into factual ProGen fields.

Allowed statuses:
SUPPORTED
VERIFY
USER INPUT REQUIRED
DRAFT
"""

REQUIRED = [
    "incident_identity", "review_status", "verified_facts", "source_conflicts",
    "critical_missing_information", "verification_required",
    "ai_suggested_investigation_checks", "classification_review",
    "consequence_review", "investigation", "actions_recommendations",
    "lesson_learned", "risk_assessment_review", "regulatory_review",
    "evidence_review", "corrective_training", "executive_summary",
    "questions_for_investigator", "progen_write_plan"
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


def redact_sensitive_identifiers(data):
    """
    Remove/redact obvious personal identifiers before sending the payload to Gemini.
    Operational incident facts, dates, locations, equipment and consequence data are retained.
    """
    clean = copy.deepcopy(data)
    stats = {
        "emails_redacted": 0,
        "phone_numbers_redacted": 0,
        "person_name_fields_redacted": 0,
        "user_identifiers_redacted": 0,
    }

    email_re = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    phone_re = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")

    sensitive_key_fragments = (
        "email", "mobile", "phone", "contact_no", "contact_number",
        "employee_name", "person_name", "affected_person", "witness_name",
        "driver_name", "cnic", "national_id", "passport"
    )
    user_key_fragments = (
        "app_user", "initiated_by", "created_by", "updated_by",
        "reported_by", "responded_by"
    )

    def redact_text(value):
        if not isinstance(value, str):
            return value
        new, n1 = email_re.subn("[EMAIL REDACTED]", value)
        stats["emails_redacted"] += n1
        new, n2 = phone_re.subn("[PHONE REDACTED]", new)
        stats["phone_numbers_redacted"] += n2
        return new

    def walk(obj, parent_key=""):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                kl = str(k).lower()

                if any(frag in kl for frag in sensitive_key_fragments):
                    if v not in ("", None, [], {}):
                        stats["person_name_fields_redacted"] += 1
                    out[k] = "[PERSONAL IDENTIFIER REDACTED]"
                    continue

                if any(frag in kl for frag in user_key_fragments):
                    if v not in ("", None, [], {}):
                        stats["user_identifiers_redacted"] += 1
                    out[k] = "[USER IDENTIFIER REDACTED]"
                    continue

                out[k] = walk(v, kl)
            return out

        if isinstance(obj, list):
            return [walk(v, parent_key) for v in obj]

        if isinstance(obj, str):
            return redact_text(obj)

        return obj

    redacted = walk(clean)
    redacted["privacySanitization"] = {
        "enabled": True,
        "purpose": "Reduce unnecessary personal identifiers before external AI processing.",
        "redaction_counts": stats,
        "note": "Operational incident facts are retained where possible."
    }
    return redacted


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
    outbound = redact_sensitive_identifiers(payload)
    st.session_state.outbound_payload = outbound

    prompt = SYSTEM + "\n\n" + SCHEMA + "\n\nPROGEN INCIDENT DATA:\n" + json.dumps(outbound, ensure_ascii=False)

    # Conservative free-tier fallback chain: one application-level attempt per model.
    # No repeated retry of the same model.
    models = [
        ("gemini-3.8-flash", "Primary"),
        ("gemini-3.7-flash", "Quality fallback"),
        ("gemini-3.5-flash-lite", "Capacity fallback"),
    ]

    status_box = st.empty()
    st.session_state.pop("api_diagnostic", None)
    st.session_state.pop("model_used", None)
    failures = []

    for index, (model, role) in enumerate(models, start=1):
        try:
            status_box.info(f"{role}: sending review to {model} ({index}/{len(models)})…")

            interaction = client.interactions.create(
                model=model,
                input=prompt
            )

            text = interaction_text(interaction)
            st.session_state.model_used = model
            st.session_state.api_diagnostic = {
                "http_status": 200,
                "machine_code": "success",
                "category": "AI Review generated",
                "retry_after_seconds": None,
                "advice": f"Review generated using {model}.",
                "model_used": model,
                "fallback_used": index > 1,
                "model_attempts": index,
                "failures": failures,
            }
            status_box.success(
                f"AI Review generated using {model}"
                + (" (fallback model)." if index > 1 else ".")
            )
            return text

        except Exception as exc:
            code = _error_status(exc)
            machine = _error_machine_code(exc) or "not supplied"
            failures.append({
                "model": model,
                "http_status": code or "unknown",
                "machine_code": machine,
            })

            # Only 429 and 503 are allowed to advance to another model.
            if code not in (429, 503):
                st.session_state.api_diagnostic = {
                    "http_status": code or "unknown",
                    "machine_code": machine,
                    "category": "Non-fallback API error",
                    "retry_after_seconds": _retry_after_seconds(exc),
                    "advice": f"V7.5 stopped on {model}; fallback is only allowed for HTTP 429/503.",
                    "model_used": None,
                    "fallback_used": index > 1,
                    "model_attempts": index,
                    "failures": failures,
                }
                raise

            # Stop if all three models have been tried.
            if index >= len(models):
                category = "Quota/rate limit" if code == 429 else "Temporary Gemini capacity"
                st.session_state.api_diagnostic = {
                    "http_status": code,
                    "machine_code": machine,
                    "category": category,
                    "retry_after_seconds": _retry_after_seconds(exc),
                    "advice": "All V7.5 free-tier model choices returned 429/503. No more application-level requests were sent.",
                    "model_used": None,
                    "fallback_used": True,
                    "model_attempts": index,
                    "failures": failures,
                }
                raise RuntimeError(
                    f"All V7.5 Gemini models were unavailable after {index} application-level attempts "
                    f"(last HTTP {code}). Your prepared ProGen payload remains available."
                ) from exc

            next_model = models[index][0]
            status_box.warning(
                f"{model} returned HTTP {code}. "
                f"Trying one different free-tier fallback model: {next_model}. "
                "No repeat request will be sent to the same model."
            )

    raise RuntimeError("No Gemini model produced a review.")

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

    if diag.get("model_used"):
        st.success("AI model used: " + str(diag["model_used"]))
        if diag.get("fallback_used"):
            st.caption("A fallback model was used because an earlier model returned HTTP 429/503.")

    failures = diag.get("failures") or []
    if failures:
        st.caption("Model attempts:")
        for f in failures:
            st.write(f"- {f.get('model')}: HTTP {f.get('http_status')} · {f.get('machine_code')}")

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
    cols = st.columns(5)
    metrics = [
        ("Status", "overall"),
        ("Source Conflicts", "critical_conflicts"),
        ("Critical Missing", "missing_critical_information"),
        ("Verify Items", "verification_items"),
        ("AI Checks", "suggested_investigation_checks"),
    ]
    for col, (label, key) in zip(cols, metrics):
        col.metric(label, status.get(key, "—"))

    tabs = st.tabs([
        "Priority", "Facts & Consequences", "Investigation", "Actions / Lessons",
        "Risk / Regulatory / Evidence", "Executive Summary", "ProGen Write Plan", "Raw JSON"
    ])

    with tabs[0]:
        st.info(
            "Priority separates actual source contradictions from missing information, "
            "verification items, and optional AI-suggested investigation checks."
        )
        show_items("Source Conflicts", r.get("source_conflicts", []))
        show_items("Critical Missing Information", r.get("critical_missing_information", []))
        show_items("Verification Required", r.get("verification_required", []))
        show_items("AI-Suggested Investigation Checks", r.get("ai_suggested_investigation_checks", []))
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
        if e.get("evidence_basis"):
            st.caption("Evidence basis: " + str(e.get("evidence_basis")))

    with tabs[6]:
        st.warning("V7.6 never writes or submits to ProGen. Final Save/Submit remains manual.")
        for i, item in enumerate(r.get("progen_write_plan", [])):
            with st.expander(f"{i+1}. {item.get('section','Section')} — {item.get('target','')}"):
                st.write("Status:", item.get("status", ""))
                st.write("Source:", item.get("source", ""))
                st.write("Confidence:", item.get("confidence", ""))
                st.write("Evidence basis:", item.get("evidence_basis", ""))
                st.write("Operation:", item.get("operation", ""))
                value = item.get("proposed_value", "")
                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.text_area("Proposed value", str(value), height=120, key=f"plan_{i}")
                st.checkbox("Reviewed / approved for later application", key=f"approve_{i}")

    with tabs[7]:
        st.json(r, expanded=False)

st.title("🛡️ ProGen AI Incident Review — V7.6")
st.caption("Read → sanitize → Gemini review → human approval. Nothing is written to ProGen.")

with st.sidebar:
    st.caption("Models: 3.8 Flash → 3.7 Flash → 3.5 Flash-Lite")
    st.caption("SDK 2.x · Conservative fallback · Strict provenance rules")
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

if "outbound_payload" in st.session_state:
    with st.expander("Privacy-sanitized payload sent to Gemini"):
        privacy = st.session_state.outbound_payload.get("privacySanitization", {})
        counts = privacy.get("redaction_counts", {})
        st.caption(
            "Emails redacted: {0} | Phone numbers redacted: {1} | "
            "Person-name fields redacted: {2} | User identifiers redacted: {3}".format(
                counts.get("emails_redacted", 0),
                counts.get("phone_numbers_redacted", 0),
                counts.get("person_name_fields_redacted", 0),
                counts.get("user_identifiers_redacted", 0),
            )
        )
        st.json(st.session_state.outbound_payload, expanded=False)

if "review" in st.session_state:
    if st.session_state.get("model_used"):
        st.info("AI model used for this review: " + st.session_state.model_used)
    show_review(st.session_state.review)
