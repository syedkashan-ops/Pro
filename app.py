import copy
import json
import re
import time
import random
import streamlit as st
from google import genai


def v83_review_backup_controls():
    st.sidebar.markdown("### Review Backup")
    review=st.session_state.get("review")
    if review:
        st.sidebar.download_button(
            "Download Current Review JSON",
            data=json.dumps(review,ensure_ascii=False,indent=2),
            file_name="progen_ai_review_backup.json",
            mime="application/json",
            key="v83_sidebar_download"
        )
        source_payload=st.session_state.get("payload")
        if source_payload:
            bundle={"backup_version":"V8.8","review":review,"sanitized_payload":source_payload}
            st.sidebar.download_button(
                "Download Review + Source Bundle",
                data=json.dumps(bundle,ensure_ascii=False,indent=2),
                file_name="progen_v87_review_source_bundle.json",
                mime="application/json",
                key="v87_bundle_download"
            )
    uploaded=st.sidebar.file_uploader(
        "Restore Previous Review JSON",
        type=["json"],
        key="v83_restore_file",
        help="Restores an earlier generated review without calling Gemini."
    )
    if uploaded is not None:
        signature=f"{uploaded.name}:{getattr(uploaded,'size','')}"
        if st.session_state.get("_v83_restored_signature")!=signature:
            try:
                restored=json.loads(uploaded.getvalue().decode("utf-8"))
                if not isinstance(restored,dict):
                    raise ValueError("The backup must contain a JSON object.")
                if isinstance(restored.get("review"),dict) and isinstance(restored.get("sanitized_payload"),dict):
                    st.session_state.review=restored["review"]
                    st.session_state.payload=restored["sanitized_payload"]
                else:
                    known={"incident_identity","review_status","verified_facts","investigation",
                           "executive_summary","progen_write_plan","evidence_guard","classification_review"}
                    if not any(k in restored for k in known):
                        raise ValueError("This does not look like a ProGen AI review backup.")
                    st.session_state.review=restored
                st.session_state._v83_restored_signature=signature
                st.session_state._v83_restore_notice=True
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Restore failed: {e}")
    if st.session_state.pop("_v83_restore_notice",False):
        st.sidebar.success("Previous review restored. No Gemini call was made.")

st.set_page_config(page_title="ProGen AI Review V8.8", page_icon="🛡️", layout="wide")

v83_review_backup_controls()


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
21. The human investigator has final authority over all investigation content.
22. progen_write_plan must contain only useful candidate ProGen field entries for human review.
23. Never include Save, Submit, Accept, Reject, or workflow-control actions in progen_write_plan.
24. Unresolved factual entries must be VERIFY, never presented as established facts."""

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

def _flatten_strings(obj, path="$"):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten_strings(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_flatten_strings(v, f"{path}[{i}]"))
    elif isinstance(obj, str) and obj.strip():
        out.append((path, obj.strip()))
    return out


def _payload_text(payload):
    return json.dumps(payload, ensure_ascii=False).lower()


def _find_field_value(payload, field_id):
    item = (payload.get("fields") or {}).get(field_id)
    if isinstance(item, dict):
        return str(item.get("value", "")).strip()
    if item is None:
        return ""
    return str(item).strip()


def _report_texts(payload):
    rows = []
    for report in payload.get("reports", []) or []:
        title = str(report.get("title", "")).strip()
        text = json.dumps(report, ensure_ascii=False)
        rows.append((title, text))
    return rows


def _injury_guard(payload):
    """Detect affirmative injury data versus any explicit injury-denial statement."""
    people = _find_field_value(payload, "P9_PEOPLE_INJURED")
    human = _find_field_value(payload, "P9_IS_HUMAN").upper()
    affirmative = []

    try:
        if people and float(people) > 0:
            affirmative.append({"claim": f"People Injured is recorded as {people}.",
                                "source": "$.fields.P9_PEOPLE_INJURED"})
    except Exception:
        pass
    if human in {"YES", "Y", "TRUE", "1"}:
        affirmative.append({"claim": f"Human injury indicator is recorded as {human}.",
                            "source": "$.fields.P9_IS_HUMAN"})

    for path, text in _flatten_strings(payload):
        low = text.lower()
        if ("human injury" in low or "human injury/ illness" in low
                or "human injury / illness" in low):
            affirmative.append({"claim": "Human Injury/Illness is recorded in the supplied data.",
                                "source": path})

    affirmative = list({(x["claim"], x["source"]): x for x in affirmative}.values())

    denial_patterns = (
        r"\bno injuries\b", r"\bno injury\b", r"\bnone injured\b",
        r"\bzero injuries\b", r"\b0 injuries\b",
        r"\bwithout injuries\b", r"\bwithout injury\b"
    )
    denials = []
    for path, text in _flatten_strings(payload):
        if any(re.search(pat, text.lower()) for pat in denial_patterns):
            denials.append({"claim": text, "source": path})
    denials = list({(x["claim"], x["source"]): x for x in denials}.values())

    if affirmative and denials:
        return {
            "claim_a": " | ".join(x["claim"] for x in affirmative[:5]),
            "source_a": " | ".join(x["source"] for x in affirmative[:5]),
            "claim_b": " | ".join(x["claim"] for x in denials[:5]),
            "source_b": " | ".join(x["source"] for x in denials[:5]),
            "why_conflict": (
                "The sanitized source payload contains affirmative injury indicators and "
                "an explicit injury-denial statement. V7.7.1 preserves the conflict and "
                "does not decide which source is correct."
            ),
            "severity": "CRITICAL",
            "question_for_user": (
                "Confirm the actual number of injured persons and identify the authoritative "
                "source for the final injury status."
            ),
            "status": "VERIFY",
            "guard_added": True
        }
    return None


def _provenance_audit(review, payload):
    """
    Flag model wording that uses evidence/provenance labels or factual upgrades
    not clearly present in the sanitized payload. This is an audit, not a rewrite
    of the underlying incident facts.
    """
    source = _payload_text(payload)

    # Phrase -> source evidence terms that must exist before the phrase is trusted.
    rules = [
        ("witness testimony", ("witness testimony",)),
        ("witness statement", ("witness statement",)),
        ("cctv footage", ("cctv",)),
        ("cctv evidence", ("cctv",)),
        ("police report", ("police",)),
        ("police investigation", ("police",)),
        ("roadway", ("roadway",)),
        ("off-site", ("off-site", "off site")),
        ("lost control", ("lost control", "loss of control")),
        ("losing control", ("losing control", "loss of control")),
        ("tyre burst", ("tyre burst", "tire burst")),
        ("rear tyre failure", ("rear tyre failure", "rear tire failure")),
        ("high speed", ("high speed", "excessive speed")),
        ("excessive speed", ("excessive speed", "high speed")),
        ("shear valve", ("shear valve",)),
        ("emergency stop", ("emergency stop", "e-stop", "estop")),
    ]

    findings = []
    seen = set()
    for path, text in _flatten_strings(review):
        low = text.lower()
        for phrase, evidence_terms in rules:
            if phrase in low and not any(term in source for term in evidence_terms):
                key = (path, phrase)
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "path": path,
                    "phrase": phrase,
                    "text": text,
                    "reason": "The AI used wording/provenance that is not directly supported by the sanitized source payload.",
                    "status": "VERIFY",
                    "guard_action": "Do not treat this wording as a supported fact or approve it for ProGen without investigator confirmation."
                })
    return findings


def _suggestion_scope_audit(review):
    """
    Ensure optional AI investigation ideas remain clearly marked as suggestions.
    """
    findings = []
    checks = review.get("ai_suggested_investigation_checks", []) or []
    for i, item in enumerate(checks):
        if not isinstance(item, dict):
            findings.append({
                "path": f"$.ai_suggested_investigation_checks[{i}]",
                "reason": "Suggested check is not structured as an object.",
                "status": "VERIFY"
            })
            continue
        if item.get("status") != "DRAFT" or item.get("disclaimer") != "AI-SUGGESTED CHECK — NOT EVIDENCE":
            item["status"] = "DRAFT"
            item["disclaimer"] = "AI-SUGGESTED CHECK — NOT EVIDENCE"
            findings.append({
                "path": f"$.ai_suggested_investigation_checks[{i}]",
                "reason": "V7.7 normalized the item so an AI suggestion cannot appear as evidence.",
                "status": "DRAFT"
            })
    return findings


def _reclassify_unsupported_evidence_requirements(review, unsupported_findings):
    """Move unsupported provenance-specific requirements to optional AI checks."""
    evidence = review.setdefault("evidence_review", {})
    required = evidence.get("missing_or_required", []) or []
    suggested = evidence.get("suggested_evidence_checks", []) or []
    phrases = {x.get("phrase", "").lower() for x in unsupported_findings if x.get("phrase")}
    kept, moved = [], []

    for item in required:
        txt = json.dumps(item, ensure_ascii=False).lower()
        matched = sorted(p for p in phrases if p in txt)
        if not matched:
            kept.append(item)
            continue
        replacement = {
            "check": "Consider obtaining independent supporting evidence for the relevant third-party vehicle-related claim, if needed and applicable.",
            "why_it_may_help": "The supplied record contains a vehicle-related claim whose factual basis may require investigator verification.",
            "triggering_fact": "A third-party vehicle collision is recorded in the supplied incident data.",
            "status": "DRAFT",
            "disclaimer": "AI-SUGGESTED CHECK — NOT EVIDENCE",
            "guard_reclassified": True,
            "reclassified_from": "evidence_review.missing_or_required",
            "unsupported_terms_removed": matched
        }
        suggested.append(replacement)
        moved.append({
            "original": item, "replacement": replacement,
            "reason": "Unsupported provenance-specific evidence requirement was converted to a neutral optional investigation check."
        })

    evidence["missing_or_required"] = kept
    evidence["suggested_evidence_checks"] = suggested
    return moved


def enforce_evidence_guard(review, payload):
    """
    Post-process Gemini output with deterministic controls.
    Does not resolve factual conflicts; it only preserves them and blocks
    unsupported wording from being treated as approved evidence.
    """
    guarded = copy.deepcopy(review)
    audit = {
        "guard_version": "1.0",
        "deterministic_conflicts_added": [],
        "unsupported_claims": [],
        "suggestion_normalizations": [],
        "write_plan_items_blocked": [],
        "approval_gate": "PASS"
    }

    # 1) Deterministic injury contradiction.
    injury_conflict = _injury_guard(payload)
    if injury_conflict:
        conflicts = guarded.setdefault("source_conflicts", [])
        already = any(
            isinstance(x, dict)
            and "injur" in json.dumps(x, ensure_ascii=False).lower()
            for x in conflicts
        )
        if not already:
            conflicts.insert(0, injury_conflict)
            audit["deterministic_conflicts_added"].append(injury_conflict)

        # Ensure the review counter cannot say zero after the guard finds a conflict.
        rs = guarded.setdefault("review_status", {})
        try:
            rs["critical_conflicts"] = max(int(rs.get("critical_conflicts", 0) or 0), 1)
        except Exception:
            rs["critical_conflicts"] = 1

    # 2) Audit unsupported provenance/factual upgrades.
    audit["unsupported_claims"] = _provenance_audit(guarded, payload)

    # 3) Reclassify unsupported evidence requirements as optional AI checks.
    audit["evidence_requirements_reclassified"] = _reclassify_unsupported_evidence_requirements(
        guarded, audit["unsupported_claims"]
    )

    # 4) Normalize AI suggestions.
    audit["suggestion_normalizations"] = _suggestion_scope_audit(guarded)

    # 5) Block write-plan entries containing unsupported audited wording.
    bad_phrases = {x["phrase"] for x in audit["unsupported_claims"]}
    for i, item in enumerate(guarded.get("progen_write_plan", []) or []):
        if not isinstance(item, dict):
            continue
        text = json.dumps(item, ensure_ascii=False).lower()
        matched = sorted(p for p in bad_phrases if p in text)
        if matched:
            item["requires_user_approval"] = True
            item["guard_blocked"] = True
            item["guard_reason"] = "Contains wording not directly supported by the sanitized source payload: " + ", ".join(matched)
            if item.get("status") == "SUPPORTED":
                item["status"] = "VERIFY"
            audit["write_plan_items_blocked"].append({
                "index": i,
                "section": item.get("section", ""),
                "target": item.get("target", ""),
                "phrases": matched
            })

    if (audit["unsupported_claims"] or audit["write_plan_items_blocked"]
            or audit.get("evidence_requirements_reclassified")):
        audit["approval_gate"] = "REVIEW REQUIRED"

    guarded["evidence_guard"] = audit
    return guarded


def show_evidence_guard(review):
    guard = review.get("evidence_guard") or {}
    st.subheader("Deterministic Evidence Guard")
    if not guard:
        st.caption("No evidence-guard data available.")
        return

    gate = guard.get("approval_gate", "PASS")
    if gate == "PASS":
        st.success("Evidence guard: PASS")
    else:
        st.warning("Evidence guard: REVIEW REQUIRED before any future ProGen application.")

    added = guard.get("deterministic_conflicts_added", []) or []
    unsupported = guard.get("unsupported_claims", []) or []
    blocked = guard.get("write_plan_items_blocked", []) or []

    reclassified = guard.get("evidence_requirements_reclassified", []) or []
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conflicts added", len(added))
    c2.metric("Unsupported wording flags", len(unsupported))
    c3.metric("Evidence items reclassified", len(reclassified))
    c4.metric("Write-plan items blocked", len(blocked))

    if added:
        with st.expander("Deterministic conflicts added", expanded=True):
            for item in added:
                st.json(item)

    if unsupported:
        with st.expander("Unsupported-claim / provenance audit", expanded=True):
            for item in unsupported:
                st.markdown(f"**{item.get('phrase','Flag')}** — `{item.get('path','')}`")
                st.write(item.get("text", ""))
                st.caption(item.get("reason", ""))

    if reclassified:
        with st.expander("Evidence requirements reclassified", expanded=True):
            for item in reclassified:
                st.json(item)

    if blocked:
        with st.expander("Blocked ProGen write-plan items", expanded=True):
            for item in blocked:
                st.json(item)


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

def build_v8_items(review):
    items=[]
    for i,x in enumerate(review.get("progen_write_plan",[]) or []):
        if not isinstance(x,dict): continue
        v=x.get("proposed_value","")
        if isinstance(v,(dict,list)): v=json.dumps(v,ensure_ascii=False,indent=2)
        items.append({"id":f"PLAN_{i+1:03d}","section":str(x.get("section","")),"target":str(x.get("target","")),"operation":str(x.get("operation","FILL")),"value":str(v),"evidence_basis":str(x.get("evidence_basis","")),"source":str(x.get("source","")),"confidence":str(x.get("confidence","")),"status":str(x.get("status","DRAFT")),"guard_blocked":bool(x.get("guard_blocked",False)),"guard_reason":str(x.get("guard_reason",""))})
    return items


def _v82_text(v):
    if v is None: return ""
    if isinstance(v,str): return v.strip()
    if isinstance(v,(int,float,bool)): return str(v)
    if isinstance(v,list): return "\n\n".join(t for t in (_v82_text(x) for x in v) if t)
    if isinstance(v,dict):
        for k in ("text","statement","fact","finding","event","description","cause","action","recommendation","lesson","details","summary"):
            if v.get(k): return _v82_text(v[k])
        return json.dumps(v,ensure_ascii=False,indent=2)
    return str(v)

def _v82_add(items,section,target,v,status="DRAFT"):
    text=_v82_text(v)
    if not text or text=="NOT PROVIDED — USER INPUT REQUIRED": return
    meta=v if isinstance(v,dict) else {}
    items.append({"id":f"AUTO_{len(items)+1:03d}","section":section,"target":target,"operation":"FILL",
        "proposed_value":text,"evidence_basis":str(meta.get("evidence_basis","")),"source":str(meta.get("source","")),
        "confidence":str(meta.get("confidence","")),"status":str(meta.get("status",status) or status),
        "guard_blocked":False,"guard_reason":"","requires_user_approval":True,
        "plan_origin":"PYTHON_FROM_STRUCTURED_AI_REVIEW"})

def build_v82_fallback_plan(r):
    items=[]; inv=r.get("investigation",{}) or {}
    for x in inv.get("finding_summary",[]) or []: _v82_add(items,"Finding Summary","Investigation Finding",x)
    for x in inv.get("chronology",[]) or []: _v82_add(items,"Chronology","Chronology Event",x)
    for key,sec,target in [("primary_causes","Causes","Primary Cause"),("secondary_causes","Causes","Secondary Cause"),
        ("immediate_causes","Causes","Immediate Cause"),("root_causes","Causes","Root Cause"),
        ("why_why","Why Why Analysis Tree","Why-Why Entry"),("other_factors","Causes","Other Factor")]:
        for x in inv.get(key,[]) or []: _v82_add(items,sec,target,x)
    if inv.get("summary_statement"): _v82_add(items,"Causes","Summary Statement",inv["summary_statement"])
    for x in r.get("actions_recommendations",[]) or []: _v82_add(items,"Actions and Recommendations","Action / Recommendation",x)
    lessons=r.get("lesson_learned",{}) or {}
    for k,t in [("primary","Primary Lesson Learned"),("process_system","Process / System Lesson"),("behavioural","Behavioural Lesson"),
                ("leadership","Leadership Lesson"),("communication","Communication Lesson"),("other","Other Lesson")]:
        if lessons.get(k): _v82_add(items,"Lesson Learned",t,lessons[k])
    risk=r.get("risk_assessment_review",{}) or {}
    if risk.get("reason"): _v82_add(items,"Risk Assessment Review","Review Reason",risk["reason"])
    if risk.get("proposed_controls"): _v82_add(items,"Risk Assessment Review","Proposed Controls",risk["proposed_controls"])
    ev=r.get("evidence_review",{}) or {}
    for x in ev.get("suggested_evidence_checks",[]) or []: _v82_add(items,"Evidence & Attachments","Suggested Evidence Check",x)
    tr=r.get("corrective_training",{}) or {}
    for x in tr.get("proposals",[]) or []: _v82_add(items,"Corrective Training","Training Proposal",x)
    ex=r.get("executive_summary",{}) or {}
    if ex.get("text"): _v82_add(items,"Executive Summary","P9_EXECUTIVE_SUMMARY",ex)
    bad={str(x.get("phrase","")).lower() for x in (r.get("evidence_guard",{}) or {}).get("unsupported_claims",[]) or [] if isinstance(x,dict)}
    for item in items:
        matched=sorted(q for q in bad if q and q in item["proposed_value"].lower())
        if matched:
            item["guard_blocked"]=True; item["guard_reason"]="Evidence Guard found unsupported wording: "+", ".join(matched)
            if item["status"]=="SUPPORTED": item["status"]="VERIFY"
    return items


# ---------------- V8.8 HARD APPROVAL GATE ----------------
V84_PROTECTED_TARGETS = {
    "P9_PEOPLE_INJURED", "P9_IS_HUMAN", "P9_IS_PROPERTY", "P9_IS_FIRE",
    "P9_IS_SPILL", "P9_IS_ROAD", "P9_RECORDABLE_INCIDENT", "P9_DAMAGE_TYPE",
    "P9_INCIDENT_ID", "P9_DETAILS_ID", "DAMAGES", "INCIDENT DATE",
    "INCIDENT LOCATION", "INCIDENT TITLE", "OSHA CATEGORY", "CONCERN TYPE",
    "REPORTED DATE", "REGION", "CONCERNED DEPARTMENT", "ACTIVITY AREA"
}

V84_PROTECTED_SECTION_TERMS = {
    "incident consequence fields", "incident header", "reported incident",
    "source incident", "original incident", "incident identity"
}

V84_ALLOWED_INVESTIGATION_SECTION_TERMS = {
    "finding summary", "investigation finding", "chronology", "why why",
    "why-why", "causes", "primary cause", "secondary cause", "immediate cause",
    "root cause", "actions and recommendations", "action", "recommendation",
    "lesson learned", "risk assessment review", "regulatory", "evidence",
    "corrective training", "executive summary"
}

def _v84_norm(x):
    return re.sub(r"\s+"," ",str(x or "").strip()).lower()

def _v84_target_key(x):
    return str(x or "").strip().upper()

def _v84_source_registry_text():
    """Conservative text registry from the sanitized source payload if retained in session."""
    candidates=[]
    for key in ("sanitized_payload","prepared_payload","ai_payload","payload","progen_payload"):
        val=st.session_state.get(key)
        if val:
            try:
                candidates.append(json.dumps(val,ensure_ascii=False) if not isinstance(val,str) else val)
            except Exception:
                pass
    return "\n".join(candidates).lower()

def v84_apply_approval_gate(items):
    """
    Python-enforced gate. Gemini cannot override this.
    Protected original/reporting fields never become approvable.
    VERIFY items never become approvable.
    """
    source_text=_v84_source_registry_text()
    gated=[]
    issues=[]

    for raw in items or []:
        item=dict(raw)
        section=_v84_norm(item.get("section"))
        target_raw=str(item.get("target","")).strip()
        target=_v84_target_key(target_raw)
        status=_v84_target_key(item.get("status"))
        operation=_v84_target_key(item.get("operation"))
        source=str(item.get("source","")).strip()
        evidence=str(item.get("evidence_basis","")).strip()

        reasons=[]
        protected=False

        if target in V84_PROTECTED_TARGETS:
            protected=True
            reasons.append("Original incident/reporting field is protected.")

        if any(term in section for term in V84_PROTECTED_SECTION_TERMS):
            protected=True
            reasons.append("Original incident/reporting section is protected.")

        # Broad P9 protection except explicitly investigation-side fields.
        if target.startswith("P9_") and target not in {
            "P9_EXECUTIVE_SUMMARY","P9_SUMMARY_STATMENT"
        }:
            protected=True
            reasons.append("Source/reporting P9 field is not eligible for AI update.")

        if status=="VERIFY":
            reasons.append("Status is VERIFY — investigator verification is required before any update.")

        # A named evidence source must actually appear in the retained source payload
        # before V8.8 treats the label as source-grounded. If payload isn't retained,
        # do not falsely validate it.
        suspicious_source=False
        source_norm=_v84_norm(source)
        if source_norm and source_norm not in {"source data","progen source data",""}:
            if source_text:
                # Require either the source label or a meaningful evidence fragment.
                evidence_fragment=_v84_norm(evidence)
                evidence_probe=evidence_fragment[:80] if len(evidence_fragment)>=20 else evidence_fragment
                if source_norm not in source_text and (not evidence_probe or evidence_probe not in source_text):
                    suspicious_source=True
                    reasons.append(f"Claimed source '{source}' was not found in the retained source payload.")
            elif "witness" in source_norm:
                suspicious_source=True
                reasons.append("Claimed Witness Statement is not independently validated by V8.8 source registry.")

        blocked=bool(reasons) or bool(item.get("guard_blocked",False))
        if item.get("guard_blocked") and item.get("guard_reason"):
            reasons.append(str(item.get("guard_reason")))

        item["v84_protected_source_field"]=protected
        item["v84_source_validation_issue"]=suspicious_source
        item["guard_blocked"]=blocked
        item["guard_reason"]=" ".join(dict.fromkeys(r for r in reasons if r))
        item["requires_user_approval"]=True

        if blocked:
            issues.append({
                "id":item.get("id",""),
                "section":item.get("section",""),
                "target":target_raw,
                "status":item.get("status",""),
                "operation":item.get("operation",""),
                "source":source,
                "reason":item["guard_reason"],
                "proposed_value":item.get("proposed_value","")
            })
        gated.append(item)

    return gated,issues

def render_v84_source_data_issues(issues):
    if not issues:
        return
    st.subheader("Source Data Issues — Investigator Review Required")
    st.caption(
        "These items are informational only. They are excluded from approval because "
        "they target protected source/reporting data, remain VERIFY, or have an unvalidated source claim."
    )
    for x in issues:
        with st.expander(f'{x.get("id","")} — {x.get("section","")} — {x.get("target","")}',expanded=False):
            st.markdown(f'**Status:** {x.get("status","")}')
            st.markdown(f'**Operation:** {x.get("operation","")}')
            if x.get("source"):
                st.markdown(f'**Claimed source:** {x.get("source")}')
            st.error(x.get("reason","Review required."))
            if x.get("proposed_value") not in (None,""):
                st.text_area(
                    "AI proposed value — NOT APPROVABLE",
                    value=str(x.get("proposed_value","")),
                    height=100,
                    disabled=True,
                    key=f'v84_issue_{x.get("id","")}'
                )




# ---------------- V8.8 GROUNDED DRAFT RECONSTRUCTION ----------------
def _v88_clause_split(text):
    out=[]
    for sent in _v87_claims(text):
        parts=re.split(r"\s+(?:while|whereas|although|however|but)\s+|,\s+(?:while|whereas|although|however|but)\s+",sent,flags=re.I)
        out.extend(p.strip(" ,;") for p in parts if p.strip(" ,;"))
    return out

def v88_reconstruct_candidates(items,registry):
    rebuilt=[]
    for raw in items or []:
        item=dict(raw)
        original=str(item.get("proposed_value",item.get("value","")) or "")
        kept=[]; removed=[]
        if registry:
            for clause in _v88_clause_split(original):
                ids,score=_v87_support(clause,registry)
                rec={"text":clause,"source_ids":ids,"support_score":round(score,2)}
                (kept if ids and score>=0.82 else removed).append(rec)
        item["v88_original_value"]=original
        item["v88_kept_claims"]=kept
        item["v88_removed_claims"]=removed
        item["v88_reconstructed"]=False

        protected=bool(item.get("v84_protected_source_field"))
        verify=str(item.get("status","")).upper()=="VERIFY"
        reason=str(item.get("guard_reason","") or "")
        # Only undo a grounding-only block; never override another guard.
        other_guard=bool(reason and "V8.7" not in reason and "V8.8" not in reason)

        if registry and kept and not protected and not verify and not other_guard:
            pieces=[]
            for x in kept:
                t=x["text"].strip()
                if t and t[-1] not in ".!?": t+="."
                if t: pieces.append(t)
            newtext=" ".join(pieces).strip()
            if _v86_meaningful(newtext):
                item["proposed_value"]=newtext
                item["value"]=newtext
                item["source_ids"]=list(dict.fromkeys(sid for x in kept for sid in x["source_ids"]))
                item["claim_grounding"]=[{"claim":x["text"],"source_ids":x["source_ids"],
                    "support_score":x["support_score"],"grounded":True} for x in kept]
                item["guard_blocked"]=False
                item["guard_reason"]=""
                item["v88_reconstructed"]=bool(removed) or newtext!=original.strip()
                item["plan_origin"]="V88_GROUNDED_RECONSTRUCTION"
        rebuilt.append(item)
    return rebuilt

def render_v88_reconstruction(item):
    if not item.get("v88_reconstructed"): return
    st.success("V8.8 reconstructed this draft using only source-grounded claims.")
    with st.expander("V8.8 Grounded Reconstruction Details",expanded=False):
        kept=item.get("v88_kept_claims") or []
        removed=item.get("v88_removed_claims") or []
        if kept:
            st.markdown("**Retained grounded claims**")
            for x in kept:
                st.markdown("✅ "+x["text"])
                st.caption("Source IDs: "+(", ".join(x["source_ids"]) or "NONE")+f" | support {x['support_score']:.2f}")
        if removed:
            st.markdown("**Removed / not sufficiently grounded**")
            for x in removed:
                st.markdown("⛔ "+x["text"])
                st.caption("Best source IDs: "+(", ".join(x["source_ids"]) or "NONE")+f" | support {x['support_score']:.2f}")

# ---------------- V8.8 SOURCE REGISTRY + CLAIM GROUNDING ----------------
V87_STOP={"the","a","an","and","or","of","to","in","on","at","for","with","by","from","as","is","was","were","be","been","being","that","this","it","its","their","there","into","while","across","based","initial","resulting","remains"}

def _v87_sid(x):
    x=re.sub(r"[^A-Za-z0-9]+","_",str(x or "").strip()).strip("_").upper()
    return x[:80] or "SOURCE"

def _v87_text(v):
    if v is None: return ""
    if isinstance(v,str): return re.sub(r"\s+"," ",v).strip()
    if isinstance(v,(int,float,bool)): return str(v)
    if isinstance(v,list): return " | ".join(_v87_text(x) for x in v if _v87_text(x))
    if isinstance(v,dict): return " | ".join(f"{k}: {_v87_text(val)}" for k,val in v.items() if _v87_text(val))
    return str(v)

def build_v87_source_registry(payload):
    reg={}
    if not isinstance(payload,dict): return reg
    inc=payload.get("incident")
    if inc:
        reg["INCIDENT_HEADER"]={"kind":"incident_header","text":_v87_text(inc),"data":inc}
    for key,val in (payload.get("fields") or {}).items():
        text=_v87_text(val.get("value") if isinstance(val,dict) else val)
        if text:
            sid="FIELD_"+_v87_sid(key)
            reg[sid]={"kind":"field","text":text,"data":val,"field":key}
    for report in payload.get("reports",[]) or []:
        if not isinstance(report,dict): continue
        title=str(report.get("title") or "REPORT")
        base="REPORT_"+_v87_sid(title)
        rows=report.get("rows") or []
        cols=report.get("columns") or []
        for i,row in enumerate(rows,1):
            if isinstance(row,dict):
                data=row
            elif isinstance(row,list) and cols:
                data={str(cols[j]):row[j] for j in range(min(len(cols),len(row)))}
            else:
                data=row
            text=_v87_text(data)
            if text:
                reg[f"{base}_ROW_{i}"]={"kind":"report_row","title":title,"text":text,"data":data}
    return reg

def _v87_tokens(text):
    toks=re.findall(r"[a-z0-9]+",str(text or "").lower())
    return [t for t in toks if t not in V87_STOP and (len(t)>=3 or t.isdigit())]

def _v87_claims(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\s*;\s*",str(text or "")) if x.strip()]

def _v87_support(claim,registry):
    ct=_v87_tokens(claim)
    if not ct: return [],0.0
    unique=list(dict.fromkeys(ct))
    best=[]; bestscore=0.0
    claim_numbers=set(re.findall(r"\b\d+(?:[.,]\d+)*\b",claim))
    for sid,src in registry.items():
        stxt=str(src.get("text","")).lower()
        stok=set(_v87_tokens(stxt))
        source_numbers=set(re.findall(r"\b\d+(?:[.,]\d+)*\b",stxt))
        if claim_numbers and not claim_numbers.issubset(source_numbers):
            continue
        score=sum(1 for t in unique if t in stok)/max(1,len(unique))
        if score>bestscore+0.001:
            bestscore=score; best=[sid]
        elif score>=bestscore-0.001 and score>0:
            best.append(sid)
    return best[:5],bestscore

def v87_ground_candidates(items):
    payload=None
    for key in ("payload","sanitized_payload","prepared_payload","ai_payload","progen_payload"):
        val=st.session_state.get(key)
        if isinstance(val,dict) and (val.get("fields") or val.get("reports") or val.get("incident")):
            payload=val
            break
    registry=build_v87_source_registry(payload)
    grounded=[]
    for raw in items or []:
        item=dict(raw)
        text=str(item.get("proposed_value",item.get("value","")) or "")
        claims=[]; all_ids=[]; failures=[]
        for claim in _v87_claims(text):
            ids,score=_v87_support(claim,registry)
            ok=bool(ids) and score>=0.82
            claims.append({"claim":claim,"source_ids":ids,"support_score":round(score,2),"grounded":ok})
            all_ids.extend(ids)
            if not ok: failures.append(claim)
        item["source_ids"]=list(dict.fromkeys(all_ids))
        item["claim_grounding"]=claims
        item["v87_registry_available"]=bool(registry)
        if not registry:
            item["guard_blocked"]=True
            item["guard_reason"]=(str(item.get("guard_reason","")).strip()+" V8.8 source payload is unavailable; grounding cannot be verified.").strip()
        elif not claims or failures:
            item["guard_blocked"]=True
            detail="; ".join(failures[:3]) if failures else "No atomic claims could be grounded."
            item["guard_reason"]=(str(item.get("guard_reason","")).strip()+" V8.8 grounding failed for: "+detail).strip()
        grounded.append(item)
    return grounded,registry

def render_v87_grounding(item):
    claims=item.get("claim_grounding") or []
    if not claims: return
    with st.expander("V8.8 Evidence Grounding",expanded=False):
        for c in claims:
            mark="✅" if c.get("grounded") else "⛔"
            st.markdown(f"{mark} **{c.get('claim','')}**")
            st.caption("Source IDs: "+(", ".join(c.get("source_ids") or []) or "NONE")+f" | support {c.get('support_score',0):.2f}")

# ---------------- V8.8 SCHEMA-AWARE CANDIDATE BUILDER ----------------
V86_BAD_SCALARS={"","0","1","true","false","yes","no","none","null","n/a","na","-"}
V86_KEYS=("text","narrative","description","finding","finding_text","finding_summary","statement","summary",
          "event","event_description","cause","cause_text","reason","action","recommendation","lesson",
          "lesson_text","details","proposed_value","draft","draft_text","executive_summary")

def _v86_clean(v): return re.sub(r"\s+"," ",str(v or "").strip())

def _v86_meaningful(v):
    if not isinstance(v,str): return False
    t=_v86_clean(v)
    return bool(t and t.lower() not in V86_BAD_SCALARS and len(t)>=8 and re.search(r"[A-Za-z]{3,}",t))

def _v86_pick(obj,preferred=()):
    if isinstance(obj,str): return _v86_clean(obj) if _v86_meaningful(obj) else ""
    if not isinstance(obj,dict): return ""
    keys=list(dict.fromkeys(tuple(preferred)+V86_KEYS))
    for k in keys:
        v=obj.get(k)
        if isinstance(v,str) and _v86_meaningful(v): return _v86_clean(v)
    return ""

def _v86_iter(v):
    if v is None:return []
    return v if isinstance(v,list) else [v]

def _v86_add(items,section,target,obj,text="",status="DRAFT",extra=None):
    text=_v86_clean(text or _v86_pick(obj))
    if not _v86_meaningful(text): return
    meta=obj if isinstance(obj,dict) else {}
    item={"id":f"AUTO_{len(items)+1:03d}","section":section,"target":target,"operation":str(meta.get("operation","FILL") or "FILL"),
          "value":text,"proposed_value":text,"evidence_basis":str(meta.get("evidence_basis","") or ""),
          "source":str(meta.get("source","") or ""),"confidence":str(meta.get("confidence","") or ""),
          "status":str(meta.get("status",status) or status),"guard_blocked":False,"guard_reason":"",
          "requires_user_approval":True,"plan_origin":"V86_SCHEMA_AWARE_STRUCTURED_REVIEW",
          "source_object":obj if isinstance(obj,(dict,list)) else {"raw":obj}}
    if extra:item.update(extra)
    items.append(item)

def build_v86_structured_candidates(r):
    items=[]; inv=r.get("investigation",{}) or {}
    for o in _v86_iter(inv.get("finding_summary")):
        _v86_add(items,"Finding Summary","Investigation Finding",o,_v86_pick(o,("finding","finding_text","text","narrative","description","summary")))
    for o in _v86_iter(inv.get("chronology")):
        extra={}
        if isinstance(o,dict):
            for k in ("event_time","time","date_time"):
                if o.get(k) not in (None,""): extra["event_time"]=o[k]; break
            for k in ("phase","phase_name"):
                if o.get(k) not in (None,""): extra["phase"]=o[k]; break
        _v86_add(items,"Chronology","Chronology Event",o,_v86_pick(o,("event_description","description","event","text","narrative")),extra=extra)
    for key,target,pref in [
        ("primary_causes","Primary Cause",("cause","cause_text","reason","description","text")),
        ("secondary_causes","Secondary Cause",("cause","cause_text","reason","description","text")),
        ("immediate_causes","Immediate Cause",("cause","cause_text","description","text","statement")),
        ("root_causes","Root Cause",("cause","cause_text","description","text","statement")),
        ("other_factors","Other Factor",("description","factor","text","reason"))]:
        for o in _v86_iter(inv.get(key)): _v86_add(items,"Causes",target,o,_v86_pick(o,pref))
    for o in _v86_iter(inv.get("why_why")):
        extra={}
        if isinstance(o,dict):
            for k in ("level","parent_id","parentId","why_id"):
                if o.get(k) not in (None,""): extra[k]=o[k]
        _v86_add(items,"Why Why Analysis Tree","Why-Why Entry",o,_v86_pick(o,("why","why_text","description","text","statement")),extra=extra)
    ss=inv.get("summary_statement")
    if ss: _v86_add(items,"Causes","Summary Statement",ss,_v86_pick(ss,("summary_statement","statement","text","summary")) if isinstance(ss,dict) else ss)
    for o in _v86_iter(r.get("actions_recommendations")):
        _v86_add(items,"Actions and Recommendations","Action / Recommendation",o,_v86_pick(o,("action","recommendation","actions","text","description","proposed_action")))
    lessons=r.get("lesson_learned",{}) or {}
    if isinstance(lessons,dict):
        for k,t in [("primary","Primary Lesson Learned"),("primary_lesson","Primary Lesson Learned"),
                    ("process_system","Process / System Lesson"),("process_system_lesson","Process / System Lesson"),
                    ("behavioural","Behavioural Lesson"),("behavioral","Behavioural Lesson"),
                    ("leadership","Leadership Lesson"),("communication","Communication Lesson"),("other","Other Lesson")]:
            if k in lessons:
                o=lessons[k]; _v86_add(items,"Lesson Learned",t,o,_v86_pick(o,("lesson","lesson_text","text","description","statement")) if isinstance(o,dict) else o)
    risk=r.get("risk_assessment_review",{}) or {}
    if isinstance(risk,dict):
        for k,t in [("reason","Risk Assessment Review Reason"),("review_reason","Risk Assessment Review Reason"),
                    ("proposed_controls","Proposed Controls"),("controls","Proposed Controls"),
                    ("recommendation","Risk Assessment Recommendation")]:
            if k in risk:
                o=risk[k]; _v86_add(items,"Risk Assessment Review",t,o,_v86_pick(o,("text","description","reason","controls","recommendation")) if isinstance(o,dict) else o)
    ev=r.get("evidence_review",{}) or {}
    if isinstance(ev,dict):
        for k in ("suggested_evidence_checks","suggested_checks","recommendations"):
            for o in _v86_iter(ev.get(k)): _v86_add(items,"Evidence & Attachments","Suggested Evidence Check",o,_v86_pick(o,("check","recommendation","text","description","why")))
    tr=r.get("corrective_training",{}) or {}
    if isinstance(tr,dict):
        for o in _v86_iter(tr.get("proposals",tr.get("recommendations",[]))):
            _v86_add(items,"Corrective Training","Training Proposal",o,_v86_pick(o,("training","proposal","recommendation","text","description","course_title")))
    ex=r.get("executive_summary",{}) or {}
    _v86_add(items,"Executive Summary","P9_EXECUTIVE_SUMMARY",ex,_v86_pick(ex,("text","executive_summary","summary","narrative")) if isinstance(ex,dict) else ex)
    return items

# ---------------- V8.8 MERGE + DEDUPLICATION ----------------
def _v85_fingerprint(item):
    section=_v84_norm(item.get("section"))
    target=_v84_norm(item.get("target"))
    value=_v84_norm(item.get("proposed_value"))
    # Strong exact-ish fingerprint. Avoid collapsing different chronology/cause rows.
    return (section,target,value)

def v85_merge_draft_candidates(review):
    """
    Always merge:
      1) Gemini progen_write_plan candidates
      2) deterministic candidates from structured AI review
    Then deduplicate without allowing Gemini's non-empty write plan to suppress
    useful investigation drafts.
    """
    gemini=build_v8_items(review) or []
    deterministic=build_v86_structured_candidates(review) or []

    merged=[]
    seen=set()

    # Gemini first so its richer explicit mapping wins on exact duplicates.
    for origin,collection in [
        ("GEMINI_PROGEN_WRITE_PLAN",gemini),
        ("V86_SCHEMA_AWARE_STRUCTURED_REVIEW",deterministic)
    ]:
        for raw in collection:
            if not isinstance(raw,dict):
                continue
            item=dict(raw)
            item["plan_origin"]=item.get("plan_origin") or origin
            fp=_v85_fingerprint(item)
            if fp in seen:
                continue
            seen.add(fp)
            merged.append(item)

    return merged,len(gemini),len(deterministic)

def v85_split_after_gate(items):
    grounded,_registry=v87_ground_candidates(items)
    reconstructed=v88_reconstruct_candidates(grounded,_registry)
    gated,issues=v84_apply_approval_gate(reconstructed)
    eligible=[]
    blocked=[]
    for item in gated:
        if item.get("guard_blocked"):
            blocked.append(item)
        else:
            eligible.append(item)
    return eligible,blocked,issues

def render_v8_workspace(review):
    st.header("V8 — Edit & Approve ProGen Draft")
    st.info("Edit each proposed value and approve or reject it. V8 does not write, save, submit, accept, reject, or move the incident in ProGen.")
    items, gemini_count, deterministic_count = v85_merge_draft_candidates(review)
    if not st.session_state.get("payload"):
        st.warning("V8.8 needs the sanitized ProGen source payload to verify evidence grounding. Restoring an old review-only backup is not enough. Paste/upload the original ProGen JSON and click Prepare & Validate; no Gemini call is required.")
    st.caption(
        f"Draft sources merged: Gemini write plan ({gemini_count}) + "
        f"structured AI review candidates ({deterministic_count})"
    )
    if not items:
        st.warning("No usable ProGen draft candidates could be built from this AI review.")
        return

    eligible_items, blocked_items, v84_issues = v85_split_after_gate(items)

    # Blocked/source/reporting items appear only here, not again in the approval queue.
    render_v84_source_data_issues(v84_issues)

    c_ok,c_block=st.columns(2)
    c_ok.metric("Eligible for approval",len(eligible_items))
    c_block.metric("Protected / Verify / Blocked",len(blocked_items))

    if eligible_items:
        st.subheader("Investigation Drafts — Edit & Approve")
        st.caption(
            "Only candidates that passed the V8.8 protection and VERIFY gate are shown below."
        )
    else:
        st.info(
            "No investigation draft currently passes the approval gate. "
            "Review the structured Investigation / Executive Summary tabs for missing or VERIFY content."
        )

    items=eligible_items

    decisions=[]
    for item in items:
        iid=item["id"]
        with st.expander(f'{iid} — {item["section"]} — {item["target"]}',expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Status:** {item.get('status', '')}")
            c2.markdown(f"**Confidence:** {item.get('confidence') or '—'}")
            c3.markdown(f"**Operation:** {item.get('operation', '')}")
            if item.get("source"): st.caption("Source: "+str(item.get("source","")))
            if item.get("evidence_basis"): st.caption("Evidence basis: "+str(item.get("evidence_basis","")))
            if item.get("plan_origin")=="V86_SCHEMA_AWARE_STRUCTURED_REVIEW" and item.get("source_object") is not None:
                with st.expander("Source AI object",expanded=False):
                    st.json(item.get("source_object"))
            render_v88_reconstruction(item)
            render_v87_grounding(item)
            draft_value=item.get("value",item.get("proposed_value",""))
            edited=st.text_area("Proposed ProGen value",value=str(draft_value or ""),height=140,key=f"v8val_{iid}")
            if item.get("guard_blocked",False):
                st.error("Evidence Guard blocked this item: "+(item["guard_reason"] or "Verification required."))
                decision="BLOCKED"; st.radio("Decision",["BLOCKED"],disabled=True,key=f"v8dec_{iid}")
            else:
                if item.get("guard_blocked"):
                    st.error("BLOCKED — "+(item.get("guard_reason") or "Investigator verification required."))
                    decision="BLOCKED"
                else:
                    decision=st.radio("Decision",["PENDING","APPROVE","REJECT"],horizontal=True,key=f'dec_{iid}')

            note=st.text_input("Reviewer note (optional)",key=f"v8note_{iid}")
            decisions.append({**item,"approved_value":edited,"decision":decision,"reviewer_note":note})
    approved=[x for x in decisions if x["decision"]=="APPROVE"]; rejected=[x for x in decisions if x["decision"]=="REJECT"]; pending=[x for x in decisions if x["decision"]=="PENDING"]; blocked=[x for x in decisions if x["decision"]=="BLOCKED"]
    st.divider(); a,b,c,d=st.columns(4); a.metric("Approved",len(approved)); b.metric("Rejected",len(rejected)); c.metric("Pending",len(pending)); d.metric("Blocked",len(blocked))
    plan={"version":"V8","incident_identity":review.get("incident_identity",{}),"human_review_required":True,"progen_save_submit":"MANUAL","approved_items":[{k:x.get(k) for k in ["id","section","target","operation","approved_value","evidence_basis","source","source_ids","confidence","reviewer_note"]} for x in approved],"rejected_items":[{"id":x["id"],"section":x["section"],"target":x["target"],"reviewer_note":x["reviewer_note"]} for x in rejected],"blocked_items":[{"id":x["id"],"section":x["section"],"target":x["target"],"reason":x["guard_reason"]} for x in blocked]}
    st.download_button("Download Approved ProGen Plan (JSON)",json.dumps(plan,ensure_ascii=False,indent=2),"progen_v8_approved_plan.json","application/json",disabled=not approved)
    if approved: st.success(f"{len(approved)} item(s) approved. Nothing has been written to ProGen.")

def show_review(r):
    st.download_button(
        "Download This AI Review (Backup)",
        data=json.dumps(r,ensure_ascii=False,indent=2),
        file_name="progen_ai_review_backup.json",
        mime="application/json",
        key="v83_main_review_download"
    )

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
        "V8 Approve / Edit", "Priority", "Facts & Consequences", "Investigation", "Actions / Lessons",
        "Risk / Regulatory / Evidence", "Executive Summary", "Evidence Guard", "ProGen Write Plan", "Raw JSON"
    ])

    with tabs[0]:
        render_v8_workspace(r)

    with tabs[1]:
        st.info(
            "Priority separates actual source contradictions from missing information, "
            "verification items, and optional AI-suggested investigation checks."
        )
        show_items("Source Conflicts", r.get("source_conflicts", []))
        show_items("Critical Missing Information", r.get("critical_missing_information", []))
        show_items("Verification Required", r.get("verification_required", []))
        show_items("AI-Suggested Investigation Checks", r.get("ai_suggested_investigation_checks", []))
        show_items("Questions for Investigator", r.get("questions_for_investigator", []))

    with tabs[2]:
        show_items("Verified Facts", r.get("verified_facts", []))
        st.subheader("Classification")
        st.json(r.get("classification_review", {}))
        st.subheader("Consequences")
        st.json(r.get("consequence_review", {}))

    with tabs[3]:
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

    with tabs[4]:
        show_items("Actions & Recommendations", r.get("actions_recommendations", []))
        st.subheader("Lesson Learned")
        st.json(r.get("lesson_learned", {}))
        st.subheader("Corrective Training")
        st.json(r.get("corrective_training", {}))

    with tabs[5]:
        st.subheader("Risk Assessment")
        st.json(r.get("risk_assessment_review", {}))
        st.subheader("Regulatory")
        st.json(r.get("regulatory_review", {}))
        st.subheader("Evidence")
        st.json(r.get("evidence_review", {}))

    with tabs[6]:
        e = r.get("executive_summary", {})
        st.caption(str(e.get("status", "DRAFT")))
        st.text_area("Draft Executive Summary", str(e.get("text", "")), height=260)
        if e.get("blocked_by"):
            st.warning("Blocked by: " + "; ".join(map(str, e["blocked_by"])))
        if e.get("evidence_basis"):
            st.caption("Evidence basis: " + str(e.get("evidence_basis")))

    with tabs[7]:
        show_evidence_guard(r)

    with tabs[8]:
        st.warning("V8.8 never writes or submits to ProGen. Final Save/Submit remains manual.")
        guard = r.get("evidence_guard") or {}
        if guard.get("approval_gate") == "REVIEW REQUIRED":
            st.error("Evidence Guard requires review. Guard-blocked write-plan items must not be approved until verified.")
        for i, item in enumerate(r.get("progen_write_plan", [])):
            with st.expander(f"{i+1}. {item.get('section','Section')} — {item.get('target','')}"):
                st.markdown(f"**Status:** {item.get('status', '')}")
                st.markdown(f"**Source:** {item.get('source', '')}")
                st.markdown(f"**Confidence:** {item.get('confidence', '')}")
                st.markdown(f"**Evidence basis:** {item.get('evidence_basis', '')}")
                st.markdown(f"**Operation:** {item.get('operation', '')}")
                value = item.get("proposed_value", "")
                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.text_area("Proposed value", str(value), height=120, key=f"plan_{i}")
                if item.get("guard_blocked"):
                    st.error(item.get("guard_reason", "Blocked by Evidence Guard."))
                    st.checkbox("Approval blocked pending verification", value=False, disabled=True, key=f"approve_{i}")
                else:
                    st.checkbox("Reviewed / approved for later application", key=f"approve_{i}")

    with tabs[9]:
        st.json(r, expanded=False)

st.title("🛡️ ProGen AI Incident Review — V8.8")
st.caption("Read → sanitize → Gemini review → human approval. Nothing is written to ProGen.")

with st.sidebar:
    st.caption("Models: 3.8 Flash → 3.7 Flash → 3.5 Flash-Lite")
    st.caption("SDK 2.x · Conservative fallback · Deterministic Evidence Guard")
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
            parsed_review = validate_review(parse_json_loose(raw_ai))
            st.session_state.review = enforce_evidence_guard(parsed_review, payload)
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
