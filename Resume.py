import streamlit as st
from openai import OpenAI
import pdfplumber
from docx import Document
import re
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
import dateutil.parser as date_parser
import calendar

import calendar

# >>> Add helpers here (Part 1) <<<
def extract_json_block(text: str):
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
    return None

def strip_trailing_commas(s: str) -> str:
    out, in_str, esc = [], False, False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in "}]" :
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


# Setup OpenAI client for OpenRouter
api_key = st.secrets['API_KEY']
if not api_key:
    st.error("API key is missing. Please configure it in Streamlit secrets.")
    st.stop()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

# Function to extract text from PDF or DOCX
def extract_text(uploaded_file):
    if uploaded_file.name.lower().endswith('.pdf'):
        with pdfplumber.open(uploaded_file) as pdf:
            return '\n'.join(page.extract_text() or '' for page in pdf.pages)
    elif uploaded_file.name.lower().endswith('.docx'):
        doc = Document(uploaded_file)
        return '\n'.join(para.text for para in doc.paragraphs)
    else:
        raise ValueError("Unsupported file format. Please upload PDF or DOCX.")

# Function to normalize and validate date (returns "dd-mm-yyyy" or "")
def normalize_date(date_str):
    if not date_str or date_str == "":
        return ""
    try:
        # Handle year ranges like "2022-2023" -> assume start of first to start of second
        if re.match(r'^\d{4}-\d{4}$', date_str):
            start_year, end_year = date_str.split('-')
            if int(end_year) > int(start_year):
                return f"01-01-{start_year}"
            return ""
        # Check for duration mentions to flag as invalid date (e.g., "Five years")
        if re.search(r'\d+\s*(year|month)s?', date_str, re.IGNORECASE):
            return ""
        # Parse various formats
        parsed = date_parser.parse(date_str, fuzzy=True, dayfirst=True)
        year = parsed.year
        month = parsed.month
        # If it's end of month, determine last day (including leap for Feb)
        if parsed.day == calendar.monthrange(year, month)[1]:
            day = calendar.monthrange(year, month)[1]  # Handles leap years
        else:
            day = parsed.day
        return f"{day:02d}-{month:02d}-{year}"
    except:
        return ""

# Function to calculate experience duration in years
def calculate_duration(start_date, end_date, is_current=False, exp_text=None):
    if not start_date or not end_date:
        if exp_text:
            # Parse explicit duration from text (e.g., "Five years" or "2 Year")
            duration_match = re.search(r'(\d+)\s*(year|month)s?', exp_text, re.IGNORECASE)
            if duration_match:
                num = int(duration_match.group(1))
                unit = duration_match.group(2).lower()
                if unit.startswith('year'):
                    return num
                elif unit.startswith('month'):
                    return num / 12
        return 0.0
    try:
        start = datetime.strptime(start_date, "%d-%m-%Y")
        if end_date == "current_time":
            end = datetime.now()
        else:
            end = datetime.strptime(end_date, "%d-%m-%Y")
        delta = relativedelta(end, start)
        return delta.years + (delta.months / 12) + (delta.days / 365.25)
    except:
        return 0.0

# Function to format experience from decimal years to "X years Y months"
def format_experience(decimal_years):
    if decimal_years <= 0:
        return "0 years 0 months"
    years = int(decimal_years)
    months = int((decimal_years - years) * 12)
    return f"{years} years {months} months"

# Function to refine skills to 1-3 words per entry
def refine_skills(skills_list):
    trailing_stops = {"and", "of", "in", "to", "with", "at", "for", "on", "by", "the", "&"}
    leading_phrases = [
        "ability to", "knowledge of", "proven", "excellent", "strong",
        "sound", "high", "good", "demonstrated", "extensive", "solid"
    ]

    def preserve_acronyms(s: str) -> str:
        acronyms = {"ai", "ml", "nlp", "sql", "crm", "sap", "aws", "gcp", "api", "ui", "ux", "etl", "bi"}
        def fix_token(t):
            return t.upper() if t.lower() in acronyms else t.capitalize()
        return " ".join(fix_token(t) for t in s.split())

    cleaned = []
    for raw in skills_list or []:
        if not raw:
            continue

        s = re.sub(r"[,:;|/\\\-–—]+", " ", str(raw))
        s = re.sub(r"\s+", " ", s).strip(" .–—,:;")

        low = s.lower()
        for p in leading_phrases:
            if low.startswith(p + " "):
                s = s[len(p) + 1:]
                low = s.lower()
                break

        tokens = low.split()
        while tokens and tokens[-1] in trailing_stops:
            tokens.pop()
        if not tokens:
            continue

        tokens = tokens[:3]
        phrase = " ".join(tokens)
        phrase = re.sub(r"\s+", " ", phrase).strip()
        phrase = re.sub(r"\b(?:and|of|in|to|with|at|for|on|by|the)\s*$", "", phrase, flags=re.I).strip()
        if not phrase:
            continue

        cleaned.append(preserve_acronyms(phrase))

    seen = set()
    out = []
    for c in cleaned:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out

# Function for post-processing the parsed JSON
def post_process_json(parsed_json):
    # Fix dates in education
    for edu in parsed_json.get("education", []):
        edu["passing_year"] = normalize_date(edu.get("passing_year", ""))
        # Standardize grade_type
        grade_type = edu.get("grade_type", "").lower()
        if '%' in grade_type or '%' in edu.get("grade_value", ""):
            edu["grade_type"] = "percentage"
        elif 'cgpa' in grade_type:
            edu["grade_type"] = "CGPA"
        # Clean grade_value (remove symbols)
        edu["grade_value"] = re.sub(r'[^0-9.]', '', edu.get("grade_value", ""))

    # Fix dates and calculate durations in experience
    total_exp = 0.0
    for exp in parsed_json.get("experience", []):
        exp["start_date"] = normalize_date(exp.get("start_date", ""))
        if exp.get("end_date", "") not in ["", "current_time"]:
            exp["end_date"] = normalize_date(exp.get("end_date", ""))
        # Use original text from resume for duration if dates are missing
        exp_text = f"{exp.get('job_title', '')} {exp.get('company', '')} {exp.get('location', '')}"
        duration = calculate_duration(exp["start_date"], exp["end_date"], exp.get("is_current", False), exp_text)
        exp["total_experience"] = round(duration, 2)
        # Add formatted experience
        exp["formatted_experience"] = format_experience(exp["total_experience"])
        total_exp += duration
        # Check for conflict and flag
        calculated_duration = exp["total_experience"]
        duration_match = re.search(r'(\d+)\s*(year|month)s?', exp_text, re.IGNORECASE)
        if duration_match and calculated_duration > 0:
            num = int(duration_match.group(1))
            unit = duration_match.group(2).lower()
            explicit_duration = num if unit.startswith('year') else num / 12
            if abs(calculated_duration - explicit_duration) / explicit_duration > 0.2:  # >20% variance
                if "experience_flags" not in parsed_json:
                    parsed_json["experience_flags"] = []
                parsed_json["experience_flags"].append(f"Potential duration inconsistency in entry: {exp.get('company', 'Unknown')}")

    parsed_json["total_work_experience"] = round(total_exp, 2)
    # Add formatted total work experience
    parsed_json["formatted_total_experience"] = format_experience(parsed_json["total_work_experience"])

    # Refine skills to 1-3 words per entry

    for field in ["skills", "key_responsibilities"]:
        if field in parsed_json and isinstance(parsed_json[field], list):
            parsed_json[field] = refine_skills(parsed_json[field])
    

    # Clean Unicode in degrees/etc.
    for key in ["full_name", "profile_title", "latest_company_name", "industry", "department"]:
        if parsed_json.get(key):
            parsed_json[key] = parsed_json[key].replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')

    for edu in parsed_json.get("education", []):
        edu["degree"] = edu.get("degree", "").replace("\u2019", "'")

    # Department: If multiple, take the first/primary
    if ',' in parsed_json.get("department", ""):
        parsed_json["department"] = parsed_json["department"].split(',')[0].strip()

    return parsed_json

# Streamlit App
st.title("Resume Parser")

# File uploader
uploaded_file = st.file_uploader("Upload your resume (PDF or DOCX)", type=['pdf', 'docx'])

if uploaded_file is not None:
    try:
        # Extract text directly from uploaded file
        resume_text = extract_text(uploaded_file).strip()
        st.subheader("Extracted Resume Text")
        st.text_area("Text", resume_text, height=200)
        
        if not resume_text:
            raise ValueError("No text could be extracted from the uploaded file. Please check the file content.")
        
        prompt = f"""
       Extract and return the candidate's information in the following strict JSON format:
    {{ "full_name": "", "email": "", "mobile_no": "", "date_of_birth": "dd-mm-yyyy", "father_name": "", "gender": "Male|Female", "address": "", "city": "", "latest_company_name": "", "industry": "", "department": "", "key_responsibilities": [], "profile_title": "", "education": [ {{ "degree": "", "branch_or_board": "", "school_or_institute": "", "passing_year": "dd-mm-yyyy", "grade_type": "", "grade_value": "" }} ], "total_work_experience": 0.0, "current_ctc": "", "experience": [ {{ "job_title": "", "company": "", "start_date": "dd-mm-yyyy", "end_date": "dd-mm-yyyy" | "current_time", "is_current": "true" | "false", "location": "", "total_experience": 0.0 }} ], "skills": [], "languages": [], "hobbies": [] }}
Rules:
1. All dates must be in dd-mm-yyyy format. If a date is not found or cannot be accurately converted, leave it as an empty string "". **For experience dates specifically:**
   - If only years are given (e.g., "2020-2024"), interpret start as "01-01-YYYY1" (first day of start year) and end as "01-01-YYYY2" (first day of end year) for the range YYYY1-YYYY2.
   - If month-year is given (e.g., "July 2020 - June 2024" or "Jul 2020-Aug 2021"), interpret start as "01-MM-YYYY" (first day of start month) and end as the last day of the end month (e.g., "30-06-2024" for June, "31-07-YYYY" for July, "28-02-YYYY" or "29-02-YYYY" for February accounting for leap years if possible; use 28 if undetermined).
   - If full dates are given (e.g., "15 July 2020 - 30 June 2024" or "15-07-2020 - 30-06-2024"), convert directly to "dd-mm-yyyy".
   - For current roles (e.g., "since 2020" or "present"), set start_date based on the given info, end_date to "current_time", and is_current to "true"; do not assume an end date. The current date for calculations is 03-10-2025.
   - Handle variations like "Jul 2020" (abbreviated months), "2020/2024" (slashes), or "from 2020 to present". Always prioritize accuracy—leave blank if ambiguous.** Do not fabricate dates.
   - In exceptional cases where a year range is mentioned alongside a conflicting explicit duration (e.g., "2022-2023 | 2 months" or "2023-2024 (2 months experience)"), prioritize the explicit duration for the total_experience (set to 0.0 initially, but note it for post-processing). Use the year range for contextual placement: assume the experience falls at the end of the range for recency (e.g., for "2022-2023 | 2 months", set start_date "01-11-2022" and end_date "31-12-2022" to fit exactly 2 months within the range). If the conflict is too ambiguous (e.g., 2 months vs. a multi-year range), leave dates as "" and flag by setting total_experience to 0.0.
   - If only a duration is provided without any dates or years (e.g., "3 years experience" or "Five years of experience"), leave start_date and end_date as ""; do not assume dates. Post-processing will calculate based on the explicit duration and current date (03-10-2025) if recency is implied.
2. Return only valid JSON. Do NOT use markdown (no triple backticks), comments, or extra explanation — just the pure JSON object.
3. If the industry or department is not explicitly mentioned, infer them from company names or job titles where appropriate (e.g., 'HDFC Bank' -> industry 'Banking', department from job_title like 'Sales Executive' -> 'Sales'). If inference is not possible or uncertain, leave as empty string "". For department, select only the primary one; do not list multiple.
4. For any field or sub-field that is missing or not mentioned in the resume text, leave it as an empty string "", null, 0.0 (for numbers), false (for booleans), or empty array [] as appropriate. Do NOT invent or provide any dummy data, placeholders, or assumptions. Ensure all personal info like name, email is extracted if present.
5. If no relevant information is found for a field, strictly adhere to leaving it empty as specified above. Do not fabricate any data.
6. Only extract information directly from or reasonably inferred from the provided resume text. Do not add external knowledge or guesses.
7. For grade_type, standardize to 'percentage' if '%' is used, 'CGPA' for scales like /10; clean grade_value to numbers only (e.g., '57%' -> '57').
8. For experience, extract raw dates without calculating durations here; set total_experience to 0.0 initially; if an explicit duration is provided (e.g., "2 months" or "Five years"), use it to inform the experience entry, but set total_experience to 0.0 here—post-processing will calculate accurately based on dates or flag inconsistencies.
9. If experience entries have missing job_titles or companies, still include them if partial data is available, but ensure consistency.
10. If dates are missing but an explicit duration is given (e.g., "3 years at CompanyX" or "2 Year Experience"), extract the entry with start_date and end_date as "", and rely on post-processing to compute total_experience from the duration text if possible. Do not infer dates unless a range or month is explicitly mentioned.

Examples:
- If resume has "Worked at HDFC 2020-2021 as Sales Exec", infer industry "Banking", department "Sales", start_date "01-01-2020", end_date "01-01-2021".
- If education has "B.A. May 2013, 57%", set passing_year "01-05-2013", grade_type "percentage", grade_value "57".
- If experience has "Sales Executive at CompanyX, July 2020 - June 2024", set start_date "01-07-2020", end_date "30-06-2024".
- If experience has "Manager at CompanyY, 2018-2022", set start_date "01-01-2018", end_date "01-01-2022".
- If experience has "Current role since 15-03-2023", set start_date "15-03-2023", end_date "current_time", is_current "true".
- If experience has "Five years of experience as Sales Executive", set start_date "", end_date "", total_experience 0.0 initially.

Resume Text:
{resume_text}
        """
        
        # Call the model with lower temperature for consistency
        with st.spinner("Parsing resume..."):
            completion = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "<YOUR_SITE_URL>",  # Optional
                    "X-Title": "<YOUR_SITE_NAME>",     # Optional
                },
                model="qwen/qwen-2.5-72b-instruct:free",
                temperature=0.05,  # Lowered for stricter adherence to rules
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            raw_response = completion.choices[0].message.content
        
        # Clean the response to extract valid JSON
        candidate = extract_json_block(raw_response)
        if not candidate and "```" in raw_response:
            # if the model wrapped it in code fences, try inside the first fence
            fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, flags=re.DOTALL)
            candidate = fenced[0] if fenced else None

        if not candidate:
            st.error("No valid JSON block found in the response.")
            st.code(raw_response)
            raise ValueError("No valid JSON found in the response")

        candidate = strip_trailing_commas(candidate)

        try:
            parsed_json = json.loads(candidate)
            parsed_json = post_process_json(parsed_json)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON format: {e}")
            st.code(candidate, language="json")
            raise
        
        # Display results
        st.subheader("Extracted Details")
        st.json(parsed_json)
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
else:
    st.info("Please upload a resume to parse.")
