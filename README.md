# PatentStack - Custom Patent Classification System

A powerful patent classification system that allows you to classify patents into technology stack categories using machine learning-based semantic similarity matching with Google BERT for Patents.

## Features

- **Custom Domain Configuration**: Define your own technology domains and CPC codes
- **Two-Tier Classification**: Organize patents into main categories and subcategories  
- **ML-Based Classification**: Uses Google BERT for Patents model for semantic similarity
- **Multiple Data Sources**: Fetch from USPTO PatentsView API
- **Interactive Visualizations**: Comprehensive charts and analytics
- **Privacy-First**: All processing happens locally, API keys never stored permanently

## Quick Start

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Installation

1. Clone this repository or download the files:
```bash
git clone https://github.com/yourusername/patentstack-app.git
cd patentstack-app
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the app:
```bash
streamlit run patent_classifier_app.py
```

The app will open in your browser at `http://localhost:8501`

## Usage Guide

### Step 1: API Configuration

You'll need at least one API source:

#### USPTO API Key (Free)
- Get from https://developer.uspto.gov/
- Free to use, no credit card required
- Provides access to US patent data

#### Google Cloud BigQuery (Optional - for International Patents)
1. **Create Google Cloud Project**:
   - Go to https://console.cloud.google.com
   - Create a new project or select existing
   - Enable billing (required for BigQuery)

2. **Enable BigQuery API**:
   - In Cloud Console, go to "APIs & Services" → "Enable APIs"
   - Search for "BigQuery API" and enable it

3. **Create Service Account** (for local/server deployment):
   - Go to "IAM & Admin" → "Service Accounts"
   - Create new service account
   - Download JSON key file
   - Set path in `.env` file as `GOOGLE_APPLICATION_CREDENTIALS`

4. **For Streamlit Cloud**: 
   - Just use your Project ID
   - Add credentials in Streamlit secrets (see deployment section)

### Step 2: Configure Patent Search

1. **Add Companies**: Enter target company names (e.g., IBM, Google, Microsoft)
2. **Set Date Range**: Choose patent filing date range (2000-2024)
3. **Define Domains**: Create technology domains with CPC codes
   - Click "Load Example Config" for a quick start
   - Or manually add domains and their CPC codes

### Step 3: Fetch Patent Data

- Click "Fetch Patents" to retrieve data from USPTO
- View sample data and download as CSV if needed
- Processing time depends on the number of patents

### Step 4: Define Technology Stack

1. **Tier 1 Categories**: Define main technology areas
   - Default: Hardware, Software, Middleware
   - Customize based on your domain

2. **Tier 2 Subcategories**: Add specific areas within each category
   - For Hardware: processors, memory, sensors, etc.
   - For Software: applications, algorithms, analytics, etc.

3. **Keywords**: Define keywords for each subcategory
   - The ML model finds patents semantically similar to these keywords
   - Be specific and comprehensive

### Step 5: Apply ML Classification

- Click "Apply ML Classification" to classify all patents
- First run downloads the BERT model (~400MB)
- Classification uses semantic similarity with 0.3 threshold
- Falls back to keyword matching if ML fails

### Step 6: Visualize Results

Explore your classified patents through:
- **Overview**: High-level statistics and distributions
- **Company Analysis**: Tech stack by company
- **Tech Stack**: Deep dive into each category
- **Subcategories**: Detailed subcategory analysis
- **Timeline**: Temporal trends and patterns

## Deployment Options

### Local Deployment

The app runs entirely on your machine by default. Simply follow the Quick Start guide above.

### Streamlit Community Cloud (Recommended for Sharing)

1. **Push to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/patentstack-app.git
   git push -u origin main
   ```

2. **Deploy on Streamlit Cloud**:
   - Go to https://streamlit.io/cloud
   - Sign in with GitHub
   - Click "New app"
   - Select your repository: `patentstack-app`
   - Set main file path: `patent_classifier_app.py`
   - Click "Deploy"

3. **Configure Secrets**:
   - In Streamlit Cloud dashboard, go to App Settings → Secrets
   - Add your API keys:
   
   For USPTO only:
   ```toml
   USPTO_API_KEY = "your-key-here"
   ```
   
   For Google BigQuery (if using):
   ```toml
   GOOGLE_CLOUD_PROJECT = "your-project-id"
   
   # If using service account (paste entire JSON content):
   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "key-id"
   private_key = "-----BEGIN PRIVATE KEY-----\nYour-Key-Here\n-----END PRIVATE KEY-----\n"
   client_email = "service-account@project.iam.gserviceaccount.com"
   client_id = "12345"
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
   ```

### Docker Deployment

Create a `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "patent_classifier_app.py", "--server.address=0.0.0.0"]
```

Build and run:
```bash
docker build -t patentstack .
docker run -p 8501:8501 patentstack
```

### Heroku Deployment

1. Create `setup.sh`:
```bash
mkdir -p ~/.streamlit/
echo "[server]\nheadless = true\nport = $PORT\n" > ~/.streamlit/config.toml
```

2. Create `Procfile`:
```
web: sh setup.sh && streamlit run patent_classifier_app.py
```

3. Deploy:
```bash
heroku create your-app-name
git push heroku main
```

## Configuration

### CPC Codes

The app accepts various CPC code formats:
- Section level: `G` (all G-section patents)
- Class level: `G06` (all computing patents)
- Subclass level: `G06N` (all ML/AI patents)
- Group level: `G06N10/20` (specific quantum computing)

See `config/example_cpc_codes.yaml` for examples.

### Classification Threshold

The default similarity threshold is 0.3 (30%). You can modify this in the code if needed:
- Lower values (0.2): More patents classified, potentially less accurate
- Higher values (0.4): Fewer patents classified, potentially more accurate

## Troubleshooting

### "Model loading takes too long"
- First run downloads ~400MB BERT model from HuggingFace
- Subsequent runs use cached model
- Consider pre-downloading if deploying to production

### "Classification is slow"
- BERT inference on CPU can be slow for large datasets
- Consider using GPU if available
- Fallback keyword matching is much faster

### "API fetch failed"
- Check your API credentials
- Verify internet connection
- USPTO may have rate limits
- Ensure you have at least one API configured

### "No patents found"
- Verify your CPC codes are correct
- Check date range includes recent patents
- Try broader CPC codes (e.g., `G06` instead of `G06N10/20`)

## Data Privacy

### What stays local:
- Your API credentials (only in session, never saved)
- Fetched patent data
- Classification results
- All ML processing

### What goes external:
- API requests to USPTO (if configured)
- Model download from HuggingFace (first run only)

## Technical Stack

- **Frontend**: Streamlit
- **Data Processing**: Pandas, NumPy
- **ML/NLP**: Transformers (Google BERT for Patents), PyTorch
- **Visualization**: Plotly
- **APIs**: USPTO PatentsView

## Contributing

Feel free to submit issues or pull requests. For major changes, please open an issue first to discuss what you would like to change.

## License

MIT License - feel free to use this for your own projects!

## Support

For issues or questions:
- Create an issue on GitHub
- Check the Troubleshooting section above
- Review the example configuration in `config/example_cpc_codes.yaml`

## Acknowledgments

- Google BERT for Patents model
- USPTO PatentsView API
- Streamlit framework
- The open-source community