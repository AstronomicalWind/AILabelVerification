# ⚖️ TTB Alcohol Beverage Label Compliance Verifier


An automated, compliance-first verification platform built for **Alcohol and Tobacco Tax and Trade Bureau (TTB)** regulatory workflows. The system screens Certificate of Label Approval (COLA) applications directly against physical beverage artwork using an ultra-low-latency **Groq LPU vision pipeline** paired with **deterministic statutory validation rules**, returning auditable, field-by-field verdicts in under 5 seconds.

---


## Overview

Human review of beverage artwork is manual, repetitive, and vulnerable to missed typography details. This engine eliminates friction across two primary ingestion paths:

* **Mode 1: Single Application Review**  
  Interactive sandbox with live parameter declarations, artwork inspection, detailed field status checks, and a granular breakdown of latency profiling (image prep, API inference, and deterministic rules engine execution).
* **Mode 2: Batch Verification (CSV Manifest + Image Folder Matching)**  
  Processes multi-label queues directly for high-volume importers. Reviewers upload a manifest (`applications.csv`) alongside a folder of label artwork (`1.jpg`, `2.png`, etc.). The system links each row to its corresponding image file by name, executes compliance audits across the entire batch, and exports an audit-ready CSV.

> **Zero-Persistence Notice:** This application functions purely as an in-memory decision-support utility. It does not store user uploads, write images to local disk, or alter official COLA records.

---

## 🏗️ System Architecture

```
                         ┌────────────────────────────────────────────────────────┐
                         │              Streamlit Web Interface                   │
                         │  (Single Label Review & Batch Image Manifest Queue)   │
                         └───────────┬────────────────────────────────┬───────────┘
                                     │                                │
                [Mode 1: Single Review]               [Mode 2: Batch CSV + Images]
                                     │                                │
                                     ▼                                ▼
                         ┌───────────────────────┐        ┌───────────────────────┐
                         │ Form Inputs + Artwork │        │  CSV + Image Pairer   │
                         │ (Manual declarations) │        │ • Manifest (.csv)     │
                         └───────────┬───────────┘        │ • Multiple Files      │
                                     │                    │   (1.jpg, 2.png, ...) │
                                     │                    └───────────┬───────────┘
                                     │                                │
                                     └────────────────┬───────────────┘
                                                      │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │     Pillow Preprocessor     │
                                       │ • Thumbnail resize (768px)  │
                                       │ • RGB conversion & compress │
                                       │ • Base64 payload encoding   │
                                       └──────────────┬──────────────┘
                                                      │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │  Groq Vision Engine (LPU)   │
                                       │  • Model: Qwen 3.6 27B      │
                                       │  • Output: Constrained JSON │
                                       │  • Latency: ~1.5 - 3.0s     │
                                       └──────────────┬──────────────┘
                                                      │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │ Deterministic Rules Engine  │
                                       │ • Fuzzy Brand (SequenceMatch│
                                       │ • Numeric ABV & Proof Match │
                                       │ • Liquid Volume Normalizer  │
                                       │ • 27 CFR Part 16 Strict Rule│
                                       └──────────────┬──────────────┘
                                                      │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │ PASS / REVIEW / FAIL Verdict│
                                       │ + Latency Breakdown Metrics │
                                       │ + Audit CSV Export Engine   │
                                       └─────────────────────────────┘
```

---

## ⚖️ Traditional OCR vs. Vision LPU

| Operational Metric | Traditional Local OCR *(Tesseract / EasyOCR)* | Vision LPU Pipeline *(This System)* |
| :--- | :--- | :--- |
| **Non-Linear Typography** | ❌ Fails on curved bottles, angled text, and foil reflection without extensive OpenCV tuning. | ✅ **Native spatial awareness**; reliably transcribes circular, skewed, and low-contrast labels. |
| **Output Structure** | ❌ Raw, unstructured bounding boxes requiring complex heuristic parsers. | ✅ **Structured JSON**; returns type-safe fields directly through Pydantic validation. |
| **Container Footprint** | ❌ Heavy (~2.5 GB+). Requires PyTorch CPU libraries, language packs, and C-binaries. | ✅ **Ultra-lightweight (<180 MB)**. Pure Python footprint with zero local model weights. |
| **Auditability** | ⚠️ High, but brittle due to dropped punctuation and incomplete transcriptions. | ✅ **Hybrid separation**: AI transcribes; deterministic Python code computes legal verdicts. |
| **Throughput & Speed** | ⚠️ 3–10s per file on CPU; scales poorly during concurrent multi-file queues. | ✅ **<5s end-to-end** sustained throughput via Groq Language Processing Units. |

---

## 📜 Regulatory Rules & Statutory Logic

The rules engine applies asymmetric tolerances: **lenient** on commercial layout differences, but **strictly literal** on mandatory statutory notices.

### 1. Brand Name Matching
* Case-insensitive sequence similarity comparison.
* **$\ge 95\%$ Match** $\rightarrow$ `PASS` (accommodates punctuation variances like `Old Tom Distillery` vs `OLD TOM DISTILLERY, INC.`).
* **$75\% - 94\%$ Match** $\rightarrow$ `REVIEW` (flags possible brand extensions or DBA variances).
* **$< 75\%$ Match** $\rightarrow$ `FAIL`.

### 2. Alcohol by Volume (ABV) & Proof
* Normalizes international comma notation before evaluating (`14,5%` $\rightarrow$ `14.5%`).
* Applies a $\pm 0.15\%$ tolerance to handle statutory numeric rounding.
* Accounts for proof equivalencies ($2\times \text{ABV}$), verifying that `80 Proof` matches a declared `40.0% ABV`.

### 3. Net Contents & Standard of Fill
* Standardizes liquid volumes to milliliters ($\text{mL}$) across measurement units:
  * **Liters ($1\,\text{L} = 1000\,\text{mL}$)**
  * **Centiliters ($75\,\text{cL} = 750\,\text{mL}$)**
  * **Fluid Ounces ($1\,\text{fl oz} \approx 29.57\,\text{mL}$)**
* Variances under $1.0\,\text{mL}$ pass automatically, preventing false flags between `750 mL` and `0.75 L`.

### 4. Mandatory Government Warning (27 CFR Part 16)
* **Header Requirement:** The title `GOVERNMENT WARNING:` must appear in capital letters. A title-cased header (`Government Warning:`) triggers an immediate `FAIL`.
* **Statutory Phrasing Check:** Verifies transcribed text against federal statute:
  > *GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS.*
* $\ge 95\%$ phrase match with validated uppercase header $\rightarrow$ `PASS`.
* Lowercase header, missing warning text, or phrasing $< 95\%$ $\rightarrow$ `FAIL`.

---

## 🗂️ Batch Manifest Verification (CSV + Image Matching)

Reviewers can verify whole product catalogs in bulk by uploading application metadata alongside the corresponding image files:

```
[Uploaded manifest.csv]
  ├── Row 1: "1.jpg", "OLD TOM DISTILLERY", "Bourbon", 45.0, 750 mL
  └── Row 2: "2.png", "CASTORO CELLARS", "Cabernet", 13.0, 750 mL
                               │
                               ▼ (Matched by filename)
[Uploaded Label Files] ──▶ 1.jpg, 2.png, 3.jpeg
                               │
                               ▼
                   [Groq Vision + Rule Engine]
```

### Manifest Format (`cola_batch_template.csv`)
```csv
filename,brand_name,class_type,alcohol_content,net_contents,country_of_origin
1.jpg,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45.0,750 mL,
2.png,CASTORO CELLARS,Cabernet Sauvignon,13.0,750 mL,
3.jpg,CHATEAU MARGAUX,Red Wine,13.5,750 mL,France
```

### Exportable Compliance Audit Report
```csv
Filename,Brand,Declared ABV,Detected ABV,Overall Verdict,Flags / Deficiencies,Latency (s)
1.jpg,OLD TOM DISTILLERY,45.0,45% Alc./Vol.,PASS,All checks passed,1.94
2.png,CASTORO CELLARS,13.0,12.5%,FAIL,FAIL: Alcohol Content (ABV),2.12
3.jpg,CHATEAU MARGAUX,13.5,13.5%,FAIL,FAIL: Government Warning,2.05
```

---

## ⚡ Quick Start

### Prerequisites
* Python 3.10 or higher
* Groq API Key ([console.groq.com](https://console.groq.com))

### Local Installation
```powershell
# 1. Clone repository
git clone [https://github.com/](https://github.com/)<your-username>/ttb-label-verifier.git
cd ttb-label-verifier

# 2. Set up virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1    # macOS/Linux: source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment key
echo "GROQ_API_KEY=gsk_your_groq_api_key_here" > .env

# 5. Launch web interface
streamlit run app.py
```

---

## 🚀 Deployment Configuration

### Option A: Streamlit Community Cloud (Recommended)
1. Push this repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io) and select your repository.
3. Under **Advanced Settings $\rightarrow$ Secrets**, provide your API key:
   ```toml
   GROQ_API_KEY = "gsk_your_groq_api_key_here"
   ```
4. Click **Deploy**.

### Option B: Containerized Deployment (Docker / Azure Container Apps)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

---

## 🔒 Data Privacy & Zero-Persistence Posture

* **Ephemeral Memory Model:** Uploaded artwork and CSV records are processed strictly in RAM and cleared from memory when the active session closes.
* **No Database Storage:** The system uses no database, local file cache, or permanent image storage.
* **Isolated Egress:** Network transmission is restricted to inference calls to Groq's endpoint; no applicant metadata, PII, or internal tracking details are sent.

---

## 🗺️ Production Roadmap

- [ ] **Asynchronous Message Queue:** Implement Celery/Redis workers to ingest enterprise batches (300+ items) without risk of client-side HTTP timeouts.
- [ ] **Physical Typography Inspection:** Use image DPI/scale data to verify the statutory 2 mm (8 pt) minimum type size on printed warnings.
- [ ] **Direct Public COLA Integration:** Retrieve public registry data via application IDs to cross-reference pending submittals directly against official agency records.
