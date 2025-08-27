# PatentStack - Custom Patent Classification System

Classify patents into technology stack categories using ML-powered semantic similarity matching with Google BERT for Patents.

## Features

- Define custom technology domains and CPC codes
- Two-tier classification (main categories + subcategories)  
- ML-based classification using Google BERT for Patents
- Fetch patents from USPTO and Google Patents BigQuery
- Interactive visualizations and analytics
- Export results as CSV

## How to Use

### Option 1: Use Online App (Easiest)

🚀 **[Click here to use PatentStack online](https://patentstack.streamlit.app)** - No installation needed!

### Option 2: Run Locally

1. Clone this repo:
```bash
git clone https://github.com/cooleschimo/patentstack-app.git
cd patentstack-app
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run:
```bash
streamlit run patent_classifier_app.py
```

## Quick Guide

1. **Get API Key**: Sign up at https://developer.uspto.gov/ (free)
2. **Configure Search**: Add companies and CPC codes  
3. **Fetch Patents**: Pull data from USPTO/BigQuery
4. **Clean Data**: Remove duplicates and filter companies
5. **Define Categories**: Set up your tech stack hierarchy
6. **Classify**: Use ML to categorize patents
7. **Visualize**: Explore results with interactive charts

## Requirements

- USPTO API Key (free): https://developer.uspto.gov/
- Optional: Google Cloud Project for international patents

## Google Cloud Setup (Optional - for International Patents)

### For Deployed Apps (Streamlit Cloud)

Users have three options to authenticate with Google Cloud:

1. **Paste Service Account JSON** - Copy and paste your service account JSON directly into the app
2. **Upload Service Account JSON** - Upload your service account JSON file
3. **Use Streamlit Secrets** (App Owner Only) - Add your service account to Streamlit Cloud secrets:
   - Go to your app settings on Streamlit Cloud
   - Add a new secret called `gcp_service_account`
   - Paste your service account JSON content

### Getting a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Enable BigQuery API (APIs & Services → Enable APIs → Search "BigQuery API")
4. Create Service Account:
   - Go to APIs & Services → Credentials
   - Click "+ CREATE CREDENTIALS" → Service Account
   - Select **BigQuery API** when asked which API
   - Select **Application data** when asked what data type
   - Grant "BigQuery User" role
5. Create and download JSON key:
   - Click on the service account
   - Go to Keys tab → ADD KEY → Create new key → JSON
6. Use this JSON in the app (paste or upload)

**Security Note**: Never commit service account keys to GitHub!

## License

MIT