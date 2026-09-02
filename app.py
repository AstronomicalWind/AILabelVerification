import streamlit as st
import re
import os
import io
import time
import base64
import json
import pandas as pd
from difflib import SequenceMatcher
from typing import Optional
from PIL import Image
from pydantic import BaseModel, Field
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
env_groq_key = os.getenv("GROQ_API_KEY")

st.set_page_config(page_title="TTB Label Compliance Verifier", page_icon="⚖️", layout="wide")

# 27 CFR Part 16 Standard Warning Text
STANDARD_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. "
    "(2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR "
    "OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)

class LabelExtraction(BaseModel):
    brand_name: Optional[str] = Field(description="Detected brand name on artwork")
    class_type: Optional[str] = Field(description="Detected class/type (e.g., Kentucky Straight Bourbon Whiskey)")
    alcohol_content: Optional[str] = Field(description="Detected ABV statement (e.g., 45% Alc./Vol.)")
    net_contents: Optional[str] = Field(description="Detected volume (e.g., 750 mL)")
    country_of_origin: Optional[str] = Field(description="Detected country of origin statement, if present")
    warning_text: Optional[str] = Field(description="Exact raw warning text transcribed from the image")
    is_header_all_caps: bool = Field(description="True if 'GOVERNMENT WARNING:' is strictly capitalized")

def fuzzy_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()

def extract_label_data_groq_profiled(pil_image: Image.Image, api_key: str):
    # 1. Preprocessing & Compression profiling
    t_prep_start = time.perf_counter()
    img = pil_image.copy()
    img.thumbnail((768, 768), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70)
    image_bytes = buffer.getvalue()
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    prep_time = round(time.perf_counter() - t_prep_start, 3)

    # 2. Network & Model Inference profiling
    t_model_start = time.perf_counter()
    client = Groq(api_key=api_key)

    prompt = (
        "Extract TTB alcohol beverage label details verbatim. "
        "Return ONLY valid JSON with exactly these keys: "
        "brand_name, class_type, alcohol_content, net_contents, country_of_origin, warning_text, "
        "is_header_all_caps. "
        "Use null when a text field is not visible. "
        "Transcribe warning_text exactly as shown. "
        "is_header_all_caps must be true only when the GOVERNMENT WARNING header is fully capitalized."
    )

    response = client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
        reasoning_effort="none",
        temperature=0.0,
        max_completion_tokens=400,
    )

    model_time = round(time.perf_counter() - t_model_start, 3)

    result = json.loads(response.choices[0].message.content)
    extracted = LabelExtraction(**result)
    return extracted, prep_time, model_time

def evaluate_compliance(form_data: dict, extracted: LabelExtraction):
    t_eval_start = time.perf_counter()
    checks = []

    # 1. Brand Name (Fuzzy Check)
    b_ratio = fuzzy_ratio(form_data["brand_name"], extracted.brand_name or "")
    if b_ratio >= 0.95:
        b_status, b_note = "PASS", "Exact / case-insensitive match."
    elif b_ratio >= 0.75:
        b_status, b_note = "REVIEW", f"Minor variance ({int(b_ratio*100)}% match)."
    else:
        b_status, b_note = "FAIL", f"Expected '{form_data['brand_name']}', found '{extracted.brand_name}'."
    checks.append({"Field": "Brand Name", "Application Form": form_data["brand_name"], "Detected Artwork": extracted.brand_name or "Not Found", "Status": b_status, "Notes": b_note})

    # 2. Class / Type Designation
    c_ratio = fuzzy_ratio(form_data["class_type"], extracted.class_type or "")
    c_status = "PASS" if c_ratio >= 0.85 else ("REVIEW" if c_ratio >= 0.60 else "FAIL")
    checks.append({"Field": "Class/Type", "Application Form": form_data["class_type"], "Detected Artwork": extracted.class_type or "Not Found", "Status": c_status, "Notes": f"Match score: {int(c_ratio*100)}%"})

    # 3. ABV Numeric Check (Parsed numerically to prevent 13 vs 13.0 mismatches)
    f_num = re.findall(r"\d+(?:\.\d+)?", str(form_data["alcohol_content"]))
    a_num = re.findall(r"\d+(?:\.\d+)?", extracted.alcohol_content or "")

    if f_num and a_num:
        try:
            form_val = float(f_num[0])
            art_val = float(a_num[0])
            if abs(form_val - art_val) <= 0.15:
                abv_status, abv_note = "PASS", f"ABV value ({art_val}%) matches declared ({form_val}%)."
            elif abs((form_val * 2.0) - art_val) <= 0.2:
                abv_status, abv_note = "PASS", f"Proof equivalent verified ({art_val} Proof = {form_val}% ABV)."
            else:
                abv_status, abv_note = "FAIL", f"Mismatch: Form={form_data['alcohol_content']}, Label={extracted.alcohol_content}"
        except ValueError:
            abv_status, abv_note = "FAIL", "Invalid numeric format."
    else:
        abv_status, abv_note = "FAIL", f"Mismatch: Form={form_data['alcohol_content']}, Label={extracted.alcohol_content}"
    checks.append({"Field": "Alcohol Content (ABV)", "Application Form": str(form_data["alcohol_content"]), "Detected Artwork": extracted.alcohol_content or "Not Found", "Status": abv_status, "Notes": abv_note})

    # 4. Net Contents
    n_ratio = fuzzy_ratio(form_data["net_contents"], extracted.net_contents or "")
    n_status = "PASS" if n_ratio >= 0.85 else "FAIL"
    checks.append({"Field": "Net Contents", "Application Form": form_data["net_contents"], "Detected Artwork": extracted.net_contents or "Not Found", "Status": n_status, "Notes": "Volume statement verified." if n_status == "PASS" else "Volume mismatch."})

    # 5. Country of Origin (only when applicable)
    if form_data.get("origin_required"):
        expected_origin = (form_data.get("country_of_origin") or "").strip()
        detected_origin = (extracted.country_of_origin or "").strip()
        o_ratio = fuzzy_ratio(expected_origin, detected_origin)

        if not expected_origin:
            o_status = "REVIEW"
            o_note = "Country of origin is marked as required, but no application value was entered."
        elif not detected_origin:
            o_status = "FAIL"
            o_note = "Country of origin is required but was not detected on the artwork."
        elif o_ratio >= 0.85:
            o_status = "PASS"
            o_note = "Country of origin verified."
        elif o_ratio >= 0.60:
            o_status = "REVIEW"
            o_note = f"Possible country-of-origin variance ({int(o_ratio*100)}% match)."
        else:
            o_status = "FAIL"
            o_note = f"Expected '{expected_origin}', found '{detected_origin}'."

        checks.append({
            "Field": "Country of Origin",
            "Application Form": expected_origin or "Required - not entered",
            "Detected Artwork": detected_origin or "Not Found",
            "Status": o_status,
            "Notes": o_note,
        })

    # 6. Government Warning (Strict check)
    raw_w = (extracted.warning_text or "").strip().upper()
    std_w = STANDARD_WARNING.strip()
    w_ratio = fuzzy_ratio(re.sub(r"\s+", " ", raw_w), re.sub(r"\s+", " ", std_w))
    
    if not extracted.is_header_all_caps or not (extracted.warning_text or "").strip().startswith("GOVERNMENT WARNING"):
        w_status = "FAIL"
        w_note = "Header must begin with capitalized 'GOVERNMENT WARNING:'."
    elif w_ratio >= 0.95:
        w_status = "PASS"
        w_note = "Mandatory 27 CFR Part 16 statement text compliant."
    else:
        w_status = "FAIL"
        w_note = f"Warning text deviates from federal statute ({int(w_ratio*100)}% match)."
    checks.append({"Field": "Government Warning", "Application Form": "27 CFR Part 16 Mandated", "Detected Artwork": extracted.warning_text[:60] + "..." if extracted.warning_text else "Not Found", "Status": w_status, "Notes": w_note})

    overall = "FAIL" if any(c["Status"] == "FAIL" for c in checks) else ("REVIEW" if any(c["Status"] == "REVIEW" for c in checks) else "PASS")
    eval_time = round(time.perf_counter() - t_eval_start, 4)
    return checks, overall, eval_time

# --- UI Setup ---
st.title("⚖️ TTB Alcohol Label AI Verification Assistant")
st.caption("Automated COLA compliance review prototype (Target latency < 5s)")

with st.sidebar:
    st.header("⚙️ Configuration")
    user_key = st.text_input(
        "Groq API Key (Optional)",
        type="password",
        help="Leave blank if using GROQ_API_KEY from .env",
    )
    active_key = user_key.strip() if user_key.strip() else env_groq_key

if not active_key:
    st.error("Groq API key missing. Add GROQ_API_KEY to your .env file or enter it in the sidebar.")
    st.stop()

tab1, tab2 = st.tabs(["Single Application Review", "Batch Processing (Bulk)"])

with tab1:
    col_left, col_right = st.columns([1, 1], gap="medium")

    with col_left:
        st.subheader("1. Application Form (COLA Data)")
        brand_in = st.text_input("Brand Name", value="OLD TOM DISTILLERY")
        class_in = st.text_input("Class / Type", value="Kentucky Straight Bourbon Whiskey")
        abv_in = st.text_input("Alcohol by Volume (ABV)", value="45% Alc./Vol.")
        net_in = st.text_input("Net Contents", value="750 mL")

        origin_required = st.checkbox(
            "Imported Product / Country of Origin Required",
            help="Enable this for imported products where country of origin should appear on the label.",
        )
        country_in = None
        if origin_required:
            country_in = st.text_input(
                "Country of Origin",
                placeholder="e.g., France",
            )
        
        uploaded_image = st.file_uploader("Upload Label Artwork", type=["png", "jpg", "jpeg"])
        if uploaded_image:
            image_obj = Image.open(uploaded_image)
            st.image(image_obj, caption="Submitted Label Image", use_container_width=True)

    with col_right:
        st.subheader("2. Compliance Check Results")
        if uploaded_image and st.button("Run AI Verification", type="primary"):
            t_total_start = time.perf_counter()
            with st.spinner("Processing label artwork with Groq Qwen 3.6 27B..."):
                try:
                    extracted, prep_time, model_time = extract_label_data_groq_profiled(image_obj, active_key)
                    form_dict = {
                        "brand_name": brand_in,
                        "class_type": class_in,
                        "alcohol_content": abv_in,
                        "net_contents": net_in,
                        "origin_required": origin_required,
                        "country_of_origin": country_in,
                    }
                    checks, overall, eval_time = evaluate_compliance(form_dict, extracted)
                    total_time = round(time.perf_counter() - t_total_start, 2)
                    
                    if overall == "PASS":
                        st.success(f"✅ Verdict: PASS (Total: {total_time}s)")
                    elif overall == "REVIEW":
                        st.warning(f"⚠️ Verdict: NEEDS HUMAN REVIEW (Total: {total_time}s)")
                    else:
                        st.error(f"❌ Verdict: REJECT / NON-COMPLIANT (Total: {total_time}s)")
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Image Prep", f"{prep_time}s")
                    m2.metric("API Latency", f"{model_time}s")
                    m3.metric("Rule Engine", f"{eval_time}s")
                    m4.metric("Total Latency", f"{total_time}s")

                    st.table(checks)
                except Exception as e:
                    st.error(f"Processing error: {e}")

with tab2:
    st.subheader("Batch Queue Processor (Importers / High Volume)")
    st.write("Upload multiple label images to process and triage them in bulk.")
    batch_files = st.file_uploader("Select multiple label images", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    
    if batch_files and st.button("Process Batch Queue"):
        progress_bar = st.progress(0)
        summary_rows = []
        for i, file in enumerate(batch_files):
            try:
                img = Image.open(file)
                extracted, _, m_time = extract_label_data_groq_profiled(img, active_key)
                summary_rows.append({
                    "Filename": file.name,
                    "Detected Brand": extracted.brand_name,
                    "Detected ABV": extracted.alcohol_content,
                    "Detected Country of Origin": extracted.country_of_origin or "Not Found",
                    "Warning Header OK": "PASS" if extracted.is_header_all_caps else "FAIL",
                    "Latency (s)": m_time
                })
            except Exception:
                summary_rows.append({
                    "Filename": file.name, 
                    "Detected Brand": "ERROR", 
                    "Detected ABV": "ERROR", 
                    "Detected Country of Origin": "ERROR", 
                    "Warning Header OK": "ERROR", 
                    "Latency (s)": "N/A"
                })
            progress_bar.progress((i + 1) / len(batch_files))
        
        df_results = pd.DataFrame(summary_rows)
        st.dataframe(df_results, use_container_width=True)

        csv_data = df_results.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Results to CSV (Excel Compatible)",
            data=csv_data,
            file_name="ttb_batch_audit_results.csv",
            mime="text/csv",
            type="primary"
        )
