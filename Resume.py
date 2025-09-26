import streamlit as st
from openai import OpenAI
import pdfplumber
from docx import Document
import re
import json

# Setup OpenAI client for OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets['API_KEY'],  # Replace with your API key or use os.getenv
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
            {{ "full_name": "", "email": "", "mobile_no": "", "date_of_birth": "dd-mm-yyyy", "father_name": "", "gender": "Male|Female", "address": "", "city": "", "latest_company_name": "", "industry": "", "department": "", "key_responsibilities": [], "profile_title": "", "education": [ {{ "degree": "", "branch_or_board": "", "school_or_institute": "", "passing_year": "dd-mm-yyyy", "grade_type": "", "grade_value": "" }} ], "total_work_experience": 0.0, "current_ctc": "", "experience": [ {{ "job_title": "", "company": "", "start_date": "dd-mm-yyyy", "end_date": "dd-mm-yyyy" | "current_time", "is_current": true | false, "location": "", "total_experience": 0.0 }} ], "skills": [], "languages": [], "hobbies": [] }}
            Rules:
            1. All dates must be in dd-mm-yyyy format. If a date is not found or cannot be accurately converted, leave it as an empty string "".
            2. Return only valid JSON. Do NOT use markdown (no triple backticks), comments, or extra explanation — just the pure JSON object.
            3. If the industry or department is not explicitly mentioned, infer them from company names or job titles where appropriate. If inference is not possible, leave as empty string "".
            4. For any field or sub-field that is missing or not mentioned in the resume text, leave it as an empty string "", null, 0.0 (for numbers), false (for booleans), or empty array [] as appropriate. Do NOT invent or provide any dummy data, placeholders, or assumptions.
            5. If no relevant information is found for a field, strictly adhere to leaving it empty as specified above. Do not fabricate any data.
            6. Only extract information directly from or reasonably inferred from the provided resume text. Do not add external knowledge or guesses.

        Resume Text:
        {resume_text}
        """
        
        # Call the model
        with st.spinner("Parsing resume..."):
            completion = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "<YOUR_SITE_URL>",  # Optional
                    "X-Title": "<YOUR_SITE_NAME>",     # Optional
                },
                model="qwen/qwen-2.5-72b-instruct:free",
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            raw_response = completion.choices[0].message.content
        
        # Clean the response to extract valid JSON
        json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if json_match:
            result = json_match.group(0)
            # Parse and re-dump to ensure validity and pretty-print
            parsed_json = json.loads(result)
            st.subheader("Extracted Details")
            st.json(parsed_json)
        else:
            raise ValueError("No valid JSON found in the response")
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
else:
    st.info("Please upload a resume to parse.")
