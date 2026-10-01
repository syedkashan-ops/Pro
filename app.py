import copy,json,re,streamlit as st
from google import genai
st.set_page_config(page_title="ProGen AI Review V7.1",page_icon="🛡️",layout="wide")
SYSTEM="""You are an HSE Incident Investigation Review Assistant. Review supplied ProGen incident data and prepare a structured investigation draft for human review.
RULES: Never invent facts. Existing investigation text is not automatically evidence. TEST DATA must never be evidence. If absent use exactly 'NOT PROVIDED — USER INPUT REQUIRED'. If present but unverified use 'VERIFY'. If directly supported use 'SUPPORTED'. Detect contradictions and never silently resolve them. Never assume injuries/count, speed, mechanical failure, driver behaviour, witnesses, CCTV, regulatory notifications, police involvement, responsibility, risk rating, deadlines, training, immediate cause or root cause. Similar incidents are reference only. Distinguish recommendations from completed actions. Return ONLY valid JSON, no markdown. Human investigator has final authority."""
SCHEMA="""Return one JSON object with keys: schema_version, incident_identity, review_status, verified_facts, conflicts, missing_information, classification_review, consequence_review, investigation, actions_recommendations, lesson_learned, risk_assessment_review, regulatory_review, evidence_review, corrective_training, executive_summary, questions_for_investigator, progen_write_plan.
schema_version='1.0'. review_status: overall,critical_conflicts,missing_critical_information,verification_items.
verified_facts items: fact,status,source,confidence. conflicts items: field_a,value_a,field_b,value_b,severity,question_for_user. missing_information items: item,importance,reason,required_action.
classification_review: current_concern_type,current_osha_category,current_damage_categories,issues_found,proposed_change,status.
consequence_review: human_injury,property_damage,fire,spill,road_accident.
investigation: finding_summary,chronology,primary_causes,secondary_causes,immediate_causes,root_causes,why_why,other_factors,summary_statement. Do not fabricate causes to populate arrays; empty arrays are valid.
actions_recommendations items: action,type,priority,basis,status,responsibility,deadline; unknown responsibility/deadline='USER INPUT REQUIRED'.
lesson_learned: primary,process_system,behavioural,leadership,communication,other.
risk_assessment_review: review_required,reason,hazard_identified_in_existing_ra,existing_controls,proposed_controls,ra_update_required.
regulatory_review: review_required,authorities_notified,notification_reference,legal_action.
evidence_review: available,missing_or_required. corrective_training: recommended,reason,proposals.
executive_summary: text,status,blocked_by. questions_for_investigator: array.
progen_write_plan items: section,target,operation,proposed_value,status,requires_user_approval; always true. Do not add a write-plan item whose value is only NOT PROVIDED — USER INPUT REQUIRED.
Statuses: SUPPORTED, VERIFY, USER INPUT REQUIRED, DRAFT."""
REQ=["incident_identity","review_status","verified_facts","conflicts","missing_information","classification_review","consequence_review","investigation","actions_recommendations","lesson_learned","risk_assessment_review","regulatory_review","evidence_review","corrective_training","executive_summary","questions_for_investigator","progen_write_plan"]
TEST_FIELDS={"P9_OTHER_CAUSES","P9_SUMMARY_STATMENT","P9_EXECUTIVE_SUMMARY"}
TECH={"P9_DAMAGE_ID","P9_DETAILS_ID","P9_DETAILS_COUNT","P9_READ_ONLY","P9_BTN_LABEL"}
TEST_REPORTS=("ChronologyAdd Event","Primary Causes","Immediate Cause","Root Cause","Action CAPA")
def parse_json(text):
    if not text or not text.strip(): raise ValueError("Empty JSON/AI response.")
    t=text.strip(); t=re.sub(r"^```(?:json)?\s*","",t,flags=re.I); t=re.sub(r"\s*```$","",t)
    try:return json.loads(t)
    except json.JSONDecodeError:pass
    start=t.find("{")
    if start<0: raise ValueError("No JSON object found.")
    depth=0; ins=False; esc=False
    for i in range(start,len(t)):
        c=t[i]
        if ins:
            if esc:esc=False
            elif c=="\\":esc=True
            elif c=='"':ins=False
        else:
            if c=='"':ins=True
            elif c=="{":depth+=1
            elif c=="}":
                depth-=1
                if depth==0:return json.loads(t[start:i+1])
    raise ValueError("Incomplete/invalid JSON.")
def sanitize(src):
    d=copy.deepcopy(src)
    if isinstance(d.get("page"),dict):d["page"].pop("url",None)
    f=d.setdefault("fields",{}); excluded=list(d.get("excludedTestData",[]))
    for key in list(f):
        k=key.lower()
        if key in {"pSalt","pContext","pReloadOnSubmit"} or any(x in k for x in ["session","checksum","csrf","token","worksheet_id","report_id","row_select"]) or k.endswith("_app_user") or k.endswith("_view_mode") or k.startswith("control_") or k=="apexcbmdummyselection": f.pop(key,None)
    f.pop("P9_JSON",None)
    for key in TEST_FIELDS:
        if key in f:
            excluded.append({"source":key,"reason":"Known mapping/test data; value excluded from AI evidence."}); f.pop(key,None)
    for key in TECH:f.pop(key,None)
    for key in list(f):
        v=str(f[key].get("value","") if isinstance(f[key],dict) else f[key]).strip()
        if not v or v in {"Select-","- Select -"}:f.pop(key,None)
    kept=[]
    for r in d.get("reports",[]) or []:
        title=str(r.get("title","")).strip()
        if any(title==p or title.startswith(p) for p in TEST_REPORTS): excluded.append({"source":"Report: "+title,"reason":"Mapping/test records excluded."})
        else:kept.append(r)
    d["reports"]=kept
    if isinstance(d.get("whyWhy"),list) and d["whyWhy"]:excluded.append({"source":"Why Why Analysis Tree","reason":f"{len(d['whyWhy'])} mapping/test nodes excluded."})
    d["whyWhy"]=[]; d["excludedTestData"]=excluded
    d["aiEvidenceRules"]={"test":"Excluded test data must never be reconstructed or assumed.","uncertain":"Use VERIFY when evidence is insufficient.","missing":"Use NOT PROVIDED — USER INPUT REQUIRED when required information is absent.","no_invention":"Never invent facts, causes, injuries, witnesses, CCTV, notifications or completed actions."}
    return d
def validate(x):
    if not isinstance(x,dict):raise ValueError("AI Review must be a JSON object.")
    m=[k for k in REQ if k not in x]
    if m:raise ValueError("Missing sections: "+", ".join(m))
    for it in x.get("progen_write_plan",[]):
        if isinstance(it,dict):it["requires_user_approval"]=True
    return x
def key():
    try:return st.secrets["GEMINI_API_KEY"]
    except:return ""
def gemini(payload):
    if not key():
        raise RuntimeError("GEMINI_API_KEY is not configured in Streamlit Secrets.")
    client = genai.Client(api_key=key())
    prompt = SCHEMA + "\n\nPROGEN INCIDENT DATA:\n" + json.dumps(payload, ensure_ascii=False)
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        system_instruction=SYSTEM,
        input=prompt
    )
    raw = getattr(interaction, "output_text", None)
    if not raw:
        raise RuntimeError("Gemini returned no text.")
    return raw

def items(title,a):
    st.subheader(title)
    if not a:st.caption("No items returned.");return
    for i,x in enumerate(a,1):
        if isinstance(x,dict):
            txt=x.get("text") or x.get("fact") or x.get("item") or x.get("action") or x.get("question_for_user") or str(x)
            st.markdown(f"**{i}. {txt}**")
            if x.get("status"):st.caption(x["status"])
            extra={k:v for k,v in x.items() if k not in {"text","fact","item","action","question_for_user","status"} and v not in ("",None,[],{})}
            if extra:st.json(extra,expanded=False)
        else:st.write(f"{i}. {x}")
def show(r):
    ident=r.get("incident_identity",{}); st.header("AI Review — "+ident.get("reference_no","Incident")); st.caption(" | ".join(str(ident.get(k,"")) for k in ["title","incident_date","location"]))
    s=r.get("review_status",{}); cols=st.columns(4)
    for c,(n,k) in zip(cols,[("Status","overall"),("Critical Conflicts","critical_conflicts"),("Critical Missing","missing_critical_information"),("Verify Items","verification_items")]):c.metric(n,s.get(k,"—"))
    tabs=st.tabs(["Priority","Facts & Consequences","Investigation","Actions / Lessons","Risk / Regulatory / Evidence","Executive Summary","ProGen Write Plan","Raw JSON"])
    with tabs[0]:items("Conflicts",r.get("conflicts",[]));items("Missing Information",r.get("missing_information",[]));items("Questions for Investigator",r.get("questions_for_investigator",[]))
    with tabs[1]:items("Verified Facts",r.get("verified_facts",[]));st.subheader("Classification");st.json(r.get("classification_review",{}));st.subheader("Consequences");st.json(r.get("consequence_review",{}))
    with tabs[2]:
        inv=r.get("investigation",{})
        for k,n in [("finding_summary","Finding Summary"),("chronology","Chronology"),("primary_causes","Primary Causes"),("secondary_causes","Secondary Causes"),("immediate_causes","Immediate Causes"),("root_causes","Root Causes"),("why_why","Why-Why"),("other_factors","Other Factors")]:items(n,inv.get(k,[]))
        st.subheader("Summary Statement");st.json(inv.get("summary_statement",{}))
    with tabs[3]:items("Actions & Recommendations",r.get("actions_recommendations",[]));st.subheader("Lesson Learned");st.json(r.get("lesson_learned",{}));st.subheader("Corrective Training");st.json(r.get("corrective_training",{}))
    with tabs[4]:st.subheader("Risk Assessment");st.json(r.get("risk_assessment_review",{}));st.subheader("Regulatory");st.json(r.get("regulatory_review",{}));st.subheader("Evidence");st.json(r.get("evidence_review",{}))
    with tabs[5]:
        e=r.get("executive_summary",{});st.caption(e.get("status","DRAFT"));st.text_area("Draft Executive Summary",e.get("text",""),height=260)
        if e.get("blocked_by"):st.warning("Blocked by: "+"; ".join(map(str,e["blocked_by"])))
    with tabs[6]:
        st.warning("V7 never writes or submits to ProGen. Final Save/Submit remains manual.")
        for i,x in enumerate(r.get("progen_write_plan",[])):
            with st.expander(f"{i+1}. {x.get('section','Section')} — {x.get('target','')}"):
                st.write("Status:",x.get("status",""));st.write("Operation:",x.get("operation",""));v=x.get("proposed_value","")
                st.json(v) if isinstance(v,(dict,list)) else st.text_area("Proposed value",str(v),height=120,key=f"p{i}")
                st.checkbox("Reviewed / approved for later application",key=f"a{i}")
    with tabs[7]:st.json(r,expanded=False)
st.title("🛡️ ProGen AI Incident Review — V7.1")
st.caption("Read → sanitize → Gemini review → human approval. V7 does not write or submit to ProGen.")
with st.sidebar:
    st.caption("Model: gemini-3.8-flash · Interactions API")
    st.success("Gemini API key configured") if key() else st.warning("GEMINI_API_KEY not configured")
up=st.file_uploader("Upload extracted JSON (optional)",type=["json","txt"])
default=up.getvalue().decode("utf-8",errors="replace") if up else ""
raw=st.text_area("Paste ProGen JSON",default,height=280,placeholder="Paste window.PROGEN_FINAL_AI_PAYLOAD or PROGEN_AI_INPUT JSON")
c1,c2,c3=st.columns(3); prep=c1.button("1. Prepare / Validate",use_container_width=True); go=c2.button("2. Generate AI Review",type="primary",use_container_width=True); clear=c3.button("Clear",use_container_width=True)
if clear:
    for k in ["payload","review","raw_ai"]:st.session_state.pop(k,None)
    st.rerun()
def prepare():
    if not raw.strip():raise ValueError("Paste or upload ProGen JSON first.")
    return sanitize(parse_json(raw))
if prep:
    try:st.session_state.payload=prepare();st.success("Payload prepared and sanitized.")
    except Exception as e:st.error(str(e))
if go:
    try:
        p=prepare();st.session_state.payload=p
        with st.spinner("Gemini is reviewing the incident..."):
            rr=gemini(p);st.session_state.raw_ai=rr;st.session_state.review=validate(parse_json(rr))
        st.success("AI Review generated. Nothing was written to ProGen.")
    except Exception as e:
        st.error("AI Review failed: "+str(e))
        if st.session_state.get("raw_ai"):
            with st.expander("Raw Gemini response"):st.code(st.session_state.raw_ai)
if "payload" in st.session_state:
    with st.expander("Sanitized payload sent to Gemini"):
        p=st.session_state.payload;st.write(f"Reports: {len(p.get('reports',[]))} | Why nodes: {len(p.get('whyWhy',[]))} | Excluded test sources: {len(p.get('excludedTestData',[]))}");st.json(p,expanded=False)
if "review" in st.session_state:show(st.session_state.review)
