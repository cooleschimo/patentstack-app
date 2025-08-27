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

## License

MIT