# HSE ProGen AI Streamlit V7

## Deploy
1. Extract the ZIP and upload its contents to a GitHub repository.
2. Do not upload a real `.streamlit/secrets.toml`.
3. In Streamlit Cloud, deploy the repository with `app.py` as the main file.
4. In App Settings > Secrets add:
   `GEMINI_API_KEY = "YOUR_REAL_KEY"`
5. Save/reboot the app.

## Use
On the ProGen page, after running the tested extractor/sanitizer:
`copy(JSON.stringify(window.PROGEN_FINAL_AI_PAYLOAD, null, 2))`
Paste that JSON into V7 and click **Prepare / Validate**, then **Generate AI Review**.

You may also paste the earlier raw `PROGEN_AI_INPUT`; V7 sanitizes again server-side.

## Safety / workflow
V7 removes common ProGen session/authentication fields before the AI call. It excludes the known mapping-test fields, cause/CAPA reports, and test Why-Why nodes for the current mapped incident. Gemini uses plain JSON text; no fragile `response_schema` is used. The parser strips code fences and extracts the first complete JSON object if needed.

V7 is read-only: it does not Save, Submit, Accept, Reject, or write back to ProGen. The ProGen write plan is only a human-review preview.

## Files
- `app.py`
- `requirements.txt`
- `.streamlit/secrets.toml.example`
- `.gitignore`
- `README.md`
