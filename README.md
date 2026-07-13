# The Invisible Labor Index

Measuring Emotional Work in Public Service Jobs — a data project quantifying the emotional and psychological labor embedded in public-facing professions (nurses, teachers, drivers, sales associates, social services workers) using NLP-based analysis of Glassdoor worker reviews.

## Project Overview

Public-facing jobs carry significant emotional labor — managing difficult interactions, absorbing distress, staying composed under pressure — that goes largely unmeasured by conventional metrics like star ratings or salary. This project builds a composite **Invisible Labor Index (ILI)** from worker review text, using zero-shot NLP classification, and compares it against occupation, pay, region, and company-level demographic data to surface where emotional labor concentrates and whether it's compensated fairly.

## Repository Structure

```
Project_InvisibleLabourIndex/
├── ExtractingJobreviewData/          # Step 1: data collection
│   ├── get_review_data.py            # Glassdoor review scraper
│   ├── get_demograph.py              # Glassdoor demographic ratings scraper
│   ├── Payment_data.py               # Salary data scraper
│   ├── review classifier.ipynb
│   ├── reviews.parquet / .csv / .json
│   ├── demographics.parquet / .csv
│   ├── salaries.parquet / .csv
│   └── classified_reviews.csv
│
├── Scoring_and_preparing data/       # Step 2: NLP classification + merge
│   ├── Scoring_Reviews_via_model.ipynb   # Zero-shot classification (BART-MNLI)
│   ├── merging_data.ipynb                # Joins reviews + salary + demographics
│   ├── classified_reviews_zeroshot.csv
│   └── final_data.csv                    # Final merged dataset used by the dashboard
│
└── Streamlit_application/            # Step 3: interactive dashboard
    ├── Home.py                       # KPI overview page
    ├── utils.py                      # Shared data loading, cleaning, region mapping
    ├── charts/                       # Chart-rendering functions (not standalone pages)
    │   ├── occupation_chart.py
    │   ├── gender_chart.py
    │   └── salary_chart.py
    └── pages/                        # Streamlit auto-detected dashboard pages
        ├── 1_Invisible_Labor_Index.py
        ├── 2_Data_Explorer.py
        ├── 4_Average_Pay_by_Region.py
        ├── 5_Pay_Within_a_Region.py
        └── 6_Correlation_Heatmap.py
```

## Pipeline

### 1. Data Collection (`ExtractingJobreviewData/`)

Worker reviews, company demographic ratings, and salary ranges were collected from Glassdoor.

**Note on collection method:** Glassdoor does not provide a public API and blocks conventional automated scraping. Data was collected via browser-based automation (driving an actual browser session) rather than direct HTTP requests, to render pages the way a normal user would. This project follows the ethical framework below regardless of collection method.

**Ethical framework** (per project plan):
- Only publicly available data was collected
- No personally identifiable information (PII) about individual reviewers was captured — reviews are already anonymized by Glassdoor
- Analysis operates on aggregate trends (by occupation, region, company), not individual-level conclusions
- Model biases, limitations, and assumptions are disclosed in the summary report and below

### 2. Scoring & Preparation (`Scoring_and_preparing data/`)

- Review text (`pros`/`cons`) was classified using **zero-shot NLP classification** (`facebook/bart-large-mnli` via Hugging Face Transformers) against nine emotional-labor constructs: burnout/exhaustion, compassion fatigue, management frustration, pay dissatisfaction, staff turnover, job satisfaction, team support, pride/purpose, and work-life balance.
- Each construct receives an independent probability score (0–1) per review (`multi_label=True`), since a single review can score high on multiple constructs simultaneously (e.g. "exhausting but rewarding").
- Two composite scores are derived: **Invisible Labor Score** (weighted sum of negative constructs) and **Positive Experience Score** (weighted sum of positive constructs).
- Reviews were merged with salary data (occupation-mapped via keyword matching on job title) and company-level demographic ratings (race/ethnicity, gender, sexual orientation, disability, veteran status, caregiver status).
- Region was derived from review location (state → U.S. Census region mapping).

### 3. Dashboard (`Streamlit_application/`)

An interactive multi-page Streamlit app (Plotly visualizations) for exploring the results:

| Page | Shows |
|---|---|
| Home | KPI overview (avg ILI, avg positive score, avg rating, review count) |
| Invisible Labor Index | ILI by occupation, by company gender-rating gap, vs. salary |
| Data Explorer | Freely pick any categorical × numeric column pair to explore |
| Average Pay by Region | Regional salary comparison |
| Pay Within a Region | Occupation-level pay breakdown within a selected region |
| Correlation Heatmap | Full correlation matrix across all constructs, scores, rating, and salary |

Run with:
```bash
cd Streamlit_application
streamlit run Home.py
```

## Key Findings

See `ILI_Summary_Report.docx` for the full write-up. Headline results:

- **Driver** has the highest average Invisible Labor Score (0.560) of any occupation studied — higher than Nurse, which scored lowest (0.415).
- The three strongest drivers of a high Invisible Labor Score are **management frustration** (r=0.75), **burnout/exhaustion** (r=0.72), and **staff turnover** (r=0.67).
- Star rating (r=-0.53) and salary (r=-0.03) each capture only part of the emotional labor picture — direct evidence that conventional metrics under-measure this dimension of work.
- At the occupation level, the lowest-paid occupation (Driver, $49,927 avg) has the highest emotional labor score, while the highest-paid (Nurse, $96,406 avg) has one of the lowest — suggesting emotional labor is not compensated proportionally to its intensity.

## Limitations

- **Company-level, not individual-level, demographics**: gender/race/etc. ratings come from Glassdoor's aggregate company breakdown, not the individual reviewer.
- **Classification is model-based, not ground truth**: zero-shot scores are model confidence, not verified human judgment.
- **Glassdoor selection bias**: reviewers self-select, skewing toward strongly positive/negative experiences.
- **Missing data**: 38.2% of reviews have no region (mostly missing location data at the source), 27.5% have no gender-rating comparison available.
- **Salary-to-occupation mapping** uses keyword matching on free-text job titles and may misclassify some roles.
- **Composite score weights** are researcher-chosen, not empirically optimized.

## Tech Stack

Python (pandas), Hugging Face Transformers (zero-shot classification, BART-MNLI), Streamlit + Plotly (dashboard), PyTorch (CUDA-accelerated on local GPU).

*(Power BI dashboard and AWS Glue/Athena/S3 ETL pipeline: in progress.)*
