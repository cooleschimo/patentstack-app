#!/usr/bin/env python3
"""
PatentStack - Custom Patent Classification System
Allows users to:
1. Configure CPC codes and domains
2. Pull patent data from USPTO and Google Patents
3. Define custom classification labels
4. View results in interactive charts
"""

import streamlit as st
import pandas as pd
import numpy as np
import yaml
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional
import requests
from io import StringIO

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from src.data_fetch.patentdata_fetcher import CPCParser, HybridPatentPuller

# Page config
st.set_page_config(
    page_title="PatentStack",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'cpc_config' not in st.session_state:
    st.session_state.cpc_config = {
        'domains': {},
        'user_inputs': {
            'companies': [],
            'date_range': {'start_year': 2020, 'end_year': 2024}
        }
    }

if 'api_keys' not in st.session_state:
    st.session_state.api_keys = {
        'uspto_key': '',
        'google_project_id': '',
        'google_credentials': None
    }

if 'fetched_data' not in st.session_state:
    st.session_state.fetched_data = None

if 'classifications' not in st.session_state:
    st.session_state.classifications = {}

if 'cleaned_data' not in st.session_state:
    st.session_state.cleaned_data = None

# Helper functions for data fetching

def save_config_to_yaml(config: Dict):
    """Save configuration to YAML file"""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "cpc_codes_custom.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    return config_path

def load_example_config():
    """Load example CPC configuration"""
    example_config = {
        'domains': {
            'quantum_computing': {
                'description': 'Quantum information processing and computing',
                'cpc_codes': [
                    # Class-level codes (broader coverage)
                    {'code': 'G06N10', 'description': 'Quantum computing - all quantum algorithms'},
                    {'code': 'H04L9', 'description': 'Cryptographic mechanisms including quantum'},
                    # Subgroup-level codes (specific technologies)
                    {'code': 'G06N10/20', 'description': 'Quantum algorithms for solving problems'},
                    {'code': 'G06N10/60', 'description': 'Quantum error correction'},
                    {'code': 'H04L9/0852', 'description': 'Quantum key distribution'}
                ]
            },
            'artificial_intelligence': {
                'description': 'Machine learning and AI technologies',
                'cpc_codes': [
                    # Class-level codes
                    {'code': 'G06N3', 'description': 'Neural networks and computing systems'},
                    {'code': 'G06N20', 'description': 'Machine learning'},
                    {'code': 'G06F40', 'description': 'Natural language processing'},
                    # Subgroup-level codes
                    {'code': 'G06N3/04', 'description': 'Architecture of neural networks'},
                    {'code': 'G06N3/08', 'description': 'Learning methods for neural networks'},
                    {'code': 'G06F40/30', 'description': 'Semantic analysis in NLP'}
                ]
            }
        },
        'user_inputs': {
            'companies': ['IBM', 'Google', 'Microsoft'],
            'date_range': {'start_year': 2020, 'end_year': 2024}
        }
    }
    return example_config

def create_api_configuration():
    """UI for API credentials"""
    st.markdown("## 🔑 API Configuration")
    st.info("Your API keys are only used locally and never stored permanently.")
    
    col1, col2 = st.columns(2)
    with col1:
        uspto_key = st.text_input(
            "USPTO API Key (Optional)",
            value=st.session_state.api_keys['uspto_key'],
            type="password",
            help="Get your key from https://developer.uspto.gov/"
        )
        st.session_state.api_keys['uspto_key'] = uspto_key
    
    with col2:
        st.markdown("### Google Cloud Setup")
        google_project = st.text_input(
            "Google Cloud Project ID (Optional)",
            value=st.session_state.api_keys['google_project_id'],
            placeholder="my-project-id",
            help="Required for Google Patents BigQuery"
        )
        st.session_state.api_keys['google_project_id'] = google_project
        
        if google_project:
            # Check if running on Streamlit Cloud with secrets
            has_streamlit_secrets = False
            try:
                if 'gcp_service_account' in st.secrets:
                    has_streamlit_secrets = True
                    # Use Streamlit secrets
                    try:
                        from google.oauth2 import service_account
                        credentials = service_account.Credentials.from_service_account_info(
                            st.secrets["gcp_service_account"],
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        st.session_state.api_keys['google_credentials'] = credentials
                        st.success("✅ Using Streamlit Cloud secrets for authentication")
                    except Exception as e:
                        st.error(f"Error using Streamlit secrets: {e}")
                        has_streamlit_secrets = False
            except:
                pass
            
            if not has_streamlit_secrets:
                # Google authentication options
                auth_method = st.radio(
                    "Google Authentication Method",
                    ["Paste Service Account JSON", "Upload Service Account JSON File", "Use Public BigQuery (Limited)"],
                    help="Choose how to authenticate with Google Cloud"
                )
            
                if auth_method == "Paste Service Account JSON":
                    st.info("📋 Paste your service account JSON content below")
                    json_input = st.text_area(
                        "Service Account JSON",
                        height=200,
                        placeholder='{\n  "type": "service_account",\n  "project_id": "your-project",\n  ...\n}',
                        help="Paste the entire contents of your service account JSON file"
                    )
                    
                    if json_input:
                        try:
                            # Import Google auth libraries
                            try:
                                from google.oauth2 import service_account
                            except ImportError:
                                st.error("Google Cloud libraries not installed. Run: pip install google-cloud-bigquery")
                                st.session_state.api_keys['google_credentials'] = None
                                return False
                            
                            # Parse the JSON
                            credentials_dict = json.loads(json_input)
                            
                            # Create credentials object
                            credentials = service_account.Credentials.from_service_account_info(
                                credentials_dict,
                                scopes=["https://www.googleapis.com/auth/cloud-platform"]
                            )
                            st.session_state.api_keys['google_credentials'] = credentials
                            st.success("✅ Google credentials loaded successfully!")
                        except json.JSONDecodeError:
                            st.error("Invalid JSON format. Please paste valid service account JSON.")
                            st.session_state.api_keys['google_credentials'] = None
                        except Exception as e:
                            st.error(f"Error loading credentials: {e}")
                            st.session_state.api_keys['google_credentials'] = None
            
                elif auth_method == "Upload Service Account JSON File":
                    uploaded_file = st.file_uploader(
                        "Upload Service Account JSON",
                        type=['json'],
                        help="Upload your Google Cloud service account credentials JSON file"
                    )
                    if uploaded_file:
                        try:
                            # Import Google auth libraries
                            try:
                                from google.oauth2 import service_account
                            except ImportError:
                                st.error("Google Cloud libraries not installed. Run: pip install google-cloud-bigquery")
                                st.session_state.api_keys['google_credentials'] = None
                                return False
                            
                            # Read and parse the JSON file
                            credentials_dict = json.loads(uploaded_file.read())
                            
                            # Create credentials object
                            credentials = service_account.Credentials.from_service_account_info(
                                credentials_dict,
                                scopes=["https://www.googleapis.com/auth/cloud-platform"]
                            )
                            st.session_state.api_keys['google_credentials'] = credentials
                            st.success("✅ Google credentials loaded successfully!")
                        except Exception as e:
                            st.error(f"Error loading credentials: {e}")
                            st.session_state.api_keys['google_credentials'] = None
            
                else:  # Use Public BigQuery
                    st.warning("⚠️ Using public BigQuery access has limitations and may not work for all queries")
                    st.info("For full access, please use a service account")
                    st.session_state.api_keys['google_credentials'] = None
            
                # Instructions on how to get service account
                with st.expander("📖 How to get a Service Account JSON for BigQuery"):
                    st.markdown("""
                    ### Quick Setup Guide:
                    
                    ⚠️ **IMPORTANT: Enable Billing to Avoid Free Tier Limits**
                    
                    If you see "Quota exceeded" errors, your project is using the free sandbox mode.
                    To use your credits:
                    1. Go to **Billing** → **Link a billing account** 
                    2. Select your billing account with credits
                    3. Link it to your project
                    
                    ### Step-by-Step Setup:
                    
                    1. **Go to Google Cloud Console**: https://console.cloud.google.com
                    
                    2. **Create or select a project**:
                       - Click the project dropdown at the top
                       - Click "New Project" if needed
                       - Name it (e.g., "patent-analysis")
                       - **IMPORTANT**: Link a billing account during creation or after
                    
                    3. **Enable Billing** (Required to use credits):
                       - Go to **Billing** in the navigation menu
                       - Click **Link a billing account**
                       - Select your billing account (with credits)
                       - Confirm linking
                    
                    4. **Enable BigQuery API**:
                       - Go to **APIs & Services** → **Enable APIs and Services**
                       - Search for **"BigQuery API"**
                       - Click on it and press **Enable**
                    
                    4. **Create Service Account** (via API Credentials):
                       - Go to **APIs & Services** → **Credentials**
                       - Click **"+ CREATE CREDENTIALS"** → **Service Account**
                       - When asked "Which API are you using?" → Select **BigQuery API**
                       - When asked "What data will you be accessing?" → Select **Application data**
                       - Fill in service account details:
                         - Name: `patent-app-service-account` (or any name)
                         - ID: (auto-generated)
                         - Description: "Service account for patent app BigQuery access"
                       - Click **CREATE AND CONTINUE**
                    
                    5. **Grant Permissions**:
                       - In "Grant this service account access" step
                       - Select role: **BigQuery User** (or BigQuery Data Viewer for read-only)
                       - Click **CONTINUE** → **DONE**
                    
                    6. **Create and Download JSON Key**:
                       - Find your new service account in the list
                       - Click on it (email link)
                       - Go to **Keys** tab
                       - Click **ADD KEY** → **Create new key**
                       - Select **JSON** format
                       - Click **CREATE**
                       - **Save the downloaded JSON file securely!**
                    
                    7. **Use in this app**:
                       - Either **paste** the JSON contents in the text area above
                       - Or **upload** the JSON file
                    
                    ### Important Notes:
                    - ✅ Select **"Application data"** when creating credentials (not "User data")
                    - ✅ The service account needs **BigQuery User** or **BigQuery Data Viewer** role
                    - ⚠️ Keep your JSON key secure - it's like a password!
                    - ⚠️ Never commit it to GitHub or share publicly
                    - 💡 You can create multiple keys if needed
                    - 💡 You can revoke keys anytime from the Console
                    
                    ### Troubleshooting:
                    - **"Permission denied"**: Make sure the service account has BigQuery User role
                    - **"API not enabled"**: Enable BigQuery API in your project
                    - **"Invalid JSON"**: Make sure you're pasting the entire JSON content
                    """)
    
    if not uspto_key and not google_project:
        st.warning("⚠️ At least one API configuration is required to fetch patents")
        return False
    return True

def create_cpc_configuration_ui():
    """UI for configuring CPC codes and domains"""
    st.markdown("## 📋 Step 1: Configure Patent Search")
    
    # API Configuration first
    with st.expander("🔑 API Configuration", expanded=True):
        has_api = create_api_configuration()
    
    # Load existing config option
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### Define Technology Domains and CPC Codes")
    with col2:
        if st.button("Load Example Config"):
            example_config = load_example_config()
            st.session_state.cpc_config = example_config
            st.success("Loaded example configuration!")
            st.rerun()
    
    # Company inputs
    st.markdown("#### Target Companies")
    companies_input = st.text_area(
        "Enter company names (one per line)",
        value="\n".join(st.session_state.cpc_config.get('user_inputs', {}).get('companies', [])),
        height=100,
        help="e.g., IBM, Google, Microsoft, Apple, Samsung"
    )
    companies = [c.strip() for c in companies_input.split('\n') if c.strip()]
    
    # Date range
    col1, col2 = st.columns(2)
    with col1:
        start_year = st.number_input(
            "Start Year",
            min_value=2000,
            max_value=2024,
            value=st.session_state.cpc_config.get('user_inputs', {}).get('date_range', {}).get('start_year', 2020)
        )
    with col2:
        default_end_year = st.session_state.cpc_config.get('user_inputs', {}).get('date_range', {}).get('end_year', 2024)
        default_end_year = min(default_end_year, 2024)
        
        end_year = st.number_input(
            "End Year",
            min_value=2000,
            max_value=2024,
            value=default_end_year
        )
    
    # Domain configuration
    st.markdown("#### Technology Domains")
    
    # Add new domain
    with st.expander("➕ Add New Domain"):
        new_domain_name = st.text_input("Domain Name", placeholder="e.g., quantum_computing")
        new_domain_desc = st.text_input("Description", placeholder="e.g., Quantum information processing")
        
        if st.button("Add Domain"):
            if new_domain_name and new_domain_name not in st.session_state.cpc_config['domains']:
                st.session_state.cpc_config['domains'][new_domain_name] = {
                    'description': new_domain_desc,
                    'cpc_codes': []
                }
                st.success(f"Added domain: {new_domain_name}")
                st.rerun()
    
    # Edit existing domains
    if st.session_state.cpc_config['domains']:
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_domain = st.selectbox(
                "Select domain to edit",
                options=list(st.session_state.cpc_config['domains'].keys())
            )
        with col2:
            if st.button("🗑️ Delete Domain", type="secondary"):
                if selected_domain in st.session_state.cpc_config['domains']:
                    del st.session_state.cpc_config['domains'][selected_domain]
                    st.success(f"Deleted domain: {selected_domain}")
                    st.rerun()
        
        if selected_domain and selected_domain in st.session_state.cpc_config['domains']:
            st.markdown(f"##### Editing: {selected_domain}")
            domain_data = st.session_state.cpc_config['domains'][selected_domain]
            
            # CPC codes for this domain
            st.markdown("**CPC Codes:**")
            
            # Add new CPC code
            col1, col2, col3 = st.columns([2, 3, 1])
            with col1:
                new_cpc = st.text_input("CPC Code", placeholder="e.g., G06N10/20", key=f"cpc_{selected_domain}")
            with col2:
                new_cpc_desc = st.text_input("Description", placeholder="Optional", key=f"desc_{selected_domain}")
            with col3:
                if st.button("Add CPC", key=f"add_{selected_domain}"):
                    if new_cpc:
                        new_cpc = new_cpc.strip().upper()
                        if not domain_data.get('cpc_codes'):
                            domain_data['cpc_codes'] = []
                        
                        domain_data['cpc_codes'].append({
                            'code': new_cpc,
                            'description': new_cpc_desc
                        })
                        st.success(f"Added CPC code: {new_cpc}")
                        st.rerun()
            
            # Display existing CPC codes
            if domain_data.get('cpc_codes'):
                st.markdown("**Existing CPC Codes:**")
                cpc_df = pd.DataFrame([
                    {
                        'CPC Code': c['code'] if isinstance(c, dict) else c,
                        'Description': c.get('description', '') if isinstance(c, dict) else ''
                    }
                    for c in domain_data['cpc_codes']
                ])
                st.dataframe(cpc_df, use_container_width=True)
    
    # Update session state
    st.session_state.cpc_config['user_inputs']['companies'] = companies
    st.session_state.cpc_config['user_inputs']['date_range'] = {
        'start_year': start_year,
        'end_year': end_year
    }
    
    # Save configuration
    if st.button("💾 Save Configuration", type="primary"):
        config_path = save_config_to_yaml(st.session_state.cpc_config)
        st.success(f"Configuration saved to {config_path}")
        return True
    
    return False

def fetch_patent_data():
    """UI for fetching patent data using HybridPatentPuller"""
    st.markdown("## 🔍 Step 2: Fetch Patent Data")
    
    # Check if configuration is ready
    if not st.session_state.cpc_config['domains']:
        st.warning("Please configure domains and CPC codes first!")
        return None
    
    # Check API keys
    if not st.session_state.api_keys['uspto_key'] and not st.session_state.api_keys['google_project_id']:
        st.error("Please configure at least one API key in Step 1!")
        return None
    
    # Display current configuration
    with st.expander("Current Configuration"):
        st.json(st.session_state.cpc_config)
    
    # Fetch options
    col1, col2 = st.columns(2)
    with col1:
        fetch_us = st.checkbox("Fetch US Patents (USPTO)", value=True, 
                              disabled=not st.session_state.api_keys['uspto_key'])
    with col2:
        fetch_intl = st.checkbox("Fetch International Patents (BigQuery)", value=False,
                                disabled=not st.session_state.api_keys['google_project_id'])
    
    max_cost = 10.0
    if fetch_intl and st.session_state.api_keys['google_project_id']:
        max_cost = st.number_input(
            "Max BigQuery Cost (USD)",
            min_value=0.0,
            max_value=100.0,
            value=10.0,
            step=1.0
        )
    
    # Fetch button
    if st.button("🚀 Fetch Patents", type="primary"):
        status_container = st.container()
        progress_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        try:
            # Set API credentials as environment variables
            if st.session_state.api_keys['uspto_key']:
                os.environ['USPTO_API_KEY'] = st.session_state.api_keys['uspto_key']
            if st.session_state.api_keys['google_project_id']:
                os.environ['GOOGLE_CLOUD_PROJECT'] = st.session_state.api_keys['google_project_id']
            
            # Save config and use it
            config_path = save_config_to_yaml(st.session_state.cpc_config)
            
            # Initialize fetcher with API keys from session state
            cpc_parser = CPCParser(str(config_path))
            try:
                puller = HybridPatentPuller(
                    cpc_parser,
                    uspto_api_key=st.session_state.api_keys['uspto_key'] if st.session_state.api_keys['uspto_key'] else None,
                    google_project_id=st.session_state.api_keys['google_project_id'] if st.session_state.api_keys['google_project_id'] else None,
                    google_credentials=st.session_state.api_keys.get('google_credentials')
                )
            except ValueError as e:
                if "authentication" in str(e).lower():
                    st.error(f"🔐 Google Cloud Authentication Error: {str(e)}")
                    st.info("Please go back to Step 1 and either upload a service account JSON file or ensure you have run 'gcloud auth application-default login'")
                    return None
                else:
                    raise e
            
            # Get parameters
            companies = st.session_state.cpc_config['user_inputs']['companies']
            start_year = st.session_state.cpc_config['user_inputs']['date_range']['start_year']
            end_year = st.session_state.cpc_config['user_inputs']['date_range']['end_year']
            domains = list(st.session_state.cpc_config['domains'].keys())
            
            # Fetch data - this will pull data year by year, company by company
            all_data = []
            fetch_errors = []
            
            # Use pull_patents_recent_first which handles multiple companies and years
            try:
                progress_bar.progress(10)
                status_text.text("Starting patent extraction...")
                
                # Create temp output directory
                output_dir = Path("temp_patent_data")
                output_dir.mkdir(exist_ok=True)
                
                # Pull patents (this creates multiple files)
                results = puller.pull_patents_recent_first(
                    companies=companies,
                    start_year=start_year,
                    end_year=end_year,
                    domains=domains,
                    max_international_cost=max_cost if fetch_intl else 0,
                    output_dir=str(output_dir)
                )
                
                # Combine all US patent files
                if fetch_us and results.get('us_patents'):
                    progress_bar.progress(40)
                    status_text.text("Combining US patent data...")
                    us_dfs = results['us_patents']
                    if us_dfs:
                        us_combined = pd.concat(us_dfs, ignore_index=True)
                        all_data.append(us_combined)
                        with status_container:
                            st.success(f"✅ Fetched {len(us_combined)} US patents")
                
                # Combine all international patent files
                if fetch_intl and results.get('international_patents'):
                    progress_bar.progress(60)
                    status_text.text("Combining international patent data...")
                    intl_dfs = results['international_patents']
                    if intl_dfs:
                        intl_combined = pd.concat(intl_dfs, ignore_index=True)
                        all_data.append(intl_combined)
                        with status_container:
                            st.success(f"✅ Fetched {len(intl_combined)} international patents")
                
            except Exception as e:
                fetch_errors.append(f"Data fetch error: {str(e)}")
                with status_container:
                    st.error(f"❌ Patent fetch failed: {str(e)}")
            
            # Combine data
            progress_bar.progress(75)
            if all_data:
                status_text.text("Combining and deduplicating data...")
                combined_df = pd.concat(all_data, ignore_index=True)
                
                # Deduplicate
                if 'patent_id' in combined_df.columns:
                    combined_df = combined_df.drop_duplicates(subset=['patent_id'])
                
                st.session_state.fetched_data = combined_df
                
                progress_bar.progress(100)
                status_text.text("Complete!")
                
                with status_container:
                    st.success(f"✅ Total unique patents fetched: {len(combined_df)}")
                    if fetch_errors:
                        st.info("Note: Some sources failed but data was retrieved from others")
                
                # Show sample
                st.markdown("### Sample Data")
                st.dataframe(combined_df.head(), use_container_width=True)
                
                # Offer download
                csv_data = combined_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Patent Data",
                    data=csv_data,
                    file_name=f"patents_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            else:
                progress_bar.progress(100)
                if fetch_errors:
                    st.error("❌ All data sources failed. Please check your API configurations.")
                    for error in fetch_errors:
                        st.error(error)
                else:
                    st.warning("No patents fetched. Please select at least one data source.")
                    
        except Exception as e:
            st.error(f"Critical error: {str(e)}")
            st.info("Please check your API credentials and internet connection")
    
    return st.session_state.fetched_data

def clean_and_deduplicate_data():
    """UI for cleaning and deduplicating patent data"""
    st.markdown("## 🧹 Step 3: Clean and Deduplicate Data")
    
    if st.session_state.fetched_data is None:
        st.warning("Please fetch patent data first!")
        return None
    
    df = st.session_state.fetched_data.copy()
    
    # Show initial statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Records", len(df))
    with col2:
        st.metric("Unique Patent IDs", df['patent_id'].nunique() if 'patent_id' in df.columns else "N/A")
    with col3:
        missing_titles = df['title'].isna().sum() if 'title' in df.columns else 0
        st.metric("Missing Titles", missing_titles)
    
    st.markdown("### Data Cleaning Options")
    
    # Simplified cleaning options
    st.markdown("### Deduplication Settings")
    st.info("Patents filed in different regions will have different IDs and will be kept as separate entries.")
    
    dedup_by_id = st.checkbox(
        "Remove duplicates by patent ID", 
        value=True,
        help="Removes exact duplicate patent IDs (keeps first occurrence)"
    )
    
    # Assignee filtering
    st.markdown("### Assignee Filtering")
    
    # Function to normalize company names
    def normalize_company_name(name):
        """Normalize company names for better matching"""
        if pd.isna(name):
            return ''
        # Convert to uppercase
        normalized = str(name).upper()
        # Remove common punctuation
        normalized = normalized.replace(',', '').replace('.', '').replace('!', '')
        # Remove common suffixes/words that might vary
        for suffix in [' INC', ' LLC', ' LTD', ' CORP', ' CORPORATION', ' COMPANY', ' CO', ' LIMITED', ' INCORPORATED']:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        # Remove extra spaces
        normalized = ' '.join(normalized.split())
        return normalized.strip()
    
    # Get the companies from config
    configured_companies = st.session_state.cpc_config.get('user_inputs', {}).get('companies', [])
    
    if configured_companies and 'assignee' in df.columns:
        # Show all unique assignees in the data
        unique_assignees = df['assignee'].dropna().unique()
        
        st.info(f"Found {len(unique_assignees)} unique assignees in the data")
        st.info("📝 Company name matching ignores punctuation and common suffixes (Inc, LLC, Corp, etc.)")
        
        # Company consolidation feature
        st.markdown("#### 🔄 Company Name Consolidation")
        with st.expander("Combine company variations into single names", expanded=False):
            st.write("Map different company name variations to a single company name.")
            st.info("💡 Tip: This helps combine variations like 'Microsoft', 'Microsoft Licensing', 'Microsoft Co.' into a single 'Microsoft' entry")
            
            # Initialize consolidation mapping in session state if not exists
            if 'company_mapping' not in st.session_state:
                st.session_state.company_mapping = {}
            
            # Quick auto-detect button
            if st.button("🔍 Auto-detect Company Variations"):
                # Clear existing mappings before auto-detecting
                st.session_state.company_mapping = {}
                for target_company in configured_companies:
                    normalized_target = normalize_company_name(target_company)
                    auto_matches = []
                    for assignee in unique_assignees:
                        normalized_assignee = normalize_company_name(assignee)
                        # More aggressive matching for auto-detect
                        if (normalized_target in normalized_assignee and 
                            assignee != target_company):
                            auto_matches.append(assignee)
                    if auto_matches:
                        st.session_state.company_mapping[target_company] = auto_matches
                if st.session_state.company_mapping:
                    st.success("✅ Auto-detected potential variations. Review and adjust below.")
                else:
                    st.info("No variations detected. Company names may already be consolidated.")
                st.rerun()
            
            # For each configured company, find potential matches
            for target_company in configured_companies:
                st.markdown(f"**{target_company}**")
                normalized_target = normalize_company_name(target_company)
                
                # Find all assignees that might be variations of this company
                potential_matches = []
                for assignee in unique_assignees:
                    normalized_assignee = normalize_company_name(assignee)
                    # Check if the normalized assignee contains the target company name
                    if (normalized_target in normalized_assignee or 
                        normalized_assignee in normalized_target or
                        # Also check if they share significant parts
                        (len(normalized_target) > 3 and 
                         len(normalized_assignee) > 3 and
                         normalized_target[:4] == normalized_assignee[:4])):
                        if assignee != target_company:
                            potential_matches.append(assignee)
                
                if potential_matches:
                    # Show potential matches with checkboxes
                    # Filter default values to only include those that still exist in potential_matches
                    current_defaults = st.session_state.company_mapping.get(target_company, [])
                    valid_defaults = [d for d in current_defaults if d in potential_matches]
                    
                    selected_matches = st.multiselect(
                        f"Select variations to combine into '{target_company}':",
                        options=potential_matches,
                        default=valid_defaults,
                        key=f"combine_{target_company}"
                    )
                    st.session_state.company_mapping[target_company] = selected_matches
                else:
                    st.write(f"No variations found for {target_company}")
            
            # Apply the mapping to the dataframe
            if st.session_state.company_mapping:
                st.markdown("---")
                if st.button("Apply Company Consolidation", type="primary"):
                    # Create a mapping dictionary
                    assignee_map = {}
                    for target, variations in st.session_state.company_mapping.items():
                        for variation in variations:
                            assignee_map[variation] = target
                    
                    # Apply the mapping
                    df['assignee'] = df['assignee'].replace(assignee_map)
                    # Update the session state data
                    st.session_state.fetched_data['assignee'] = df['assignee']
                    # Clear the company mapping after applying to prevent stale data
                    st.session_state.company_mapping = {}
                    st.success(f"✅ Consolidated {len(assignee_map)} company variations!")
                    st.rerun()
        
        filter_assignees = st.checkbox(
            "Filter to only configured companies", 
            value=True,
            help=f"Keep patents from: {', '.join(configured_companies)}"
        )
        
        if filter_assignees:
            # Normalize both configured companies and assignees in data
            normalized_config = [normalize_company_name(c) for c in configured_companies]
            df['assignee_normalized'] = df['assignee'].apply(normalize_company_name)
            
            # Match using normalized names
            matching_assignees = df[df['assignee_normalized'].isin(normalized_config)]
            non_matching = df[~df['assignee_normalized'].isin(normalized_config)]
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Patents from configured companies", len(matching_assignees))
            with col2:
                st.metric("Patents from other assignees (will be removed)", len(non_matching))
            
            if len(non_matching) > 0:
                with st.expander("Preview assignees to be removed (showing top 20)"):
                    removed_assignees = non_matching['assignee'].value_counts().head(20)
                    st.dataframe(removed_assignees)
                    st.caption("These will be removed. If you want to keep any, add them to your configuration.")
    
    # Show what will be cleaned
    st.markdown("### Data Summary")
    
    # Check for duplicate IDs
    if 'patent_id' in df.columns:
        dup_ids = df[df.duplicated(subset=['patent_id'], keep=False)]
        if not dup_ids.empty:
            st.warning(f"📋 {len(dup_ids)} duplicate patent IDs found - these will be removed")
        else:
            st.success("✅ No duplicate patent IDs detected")
    
    # Show data statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        if 'title' in df.columns:
            missing_titles = df['title'].isna().sum()
            st.metric("Patents without titles", missing_titles, help="These will be kept")
    with col2:
        if 'abstract' in df.columns:
            missing_abstracts = df['abstract'].isna().sum()
            st.metric("Patents without abstracts", missing_abstracts, help="These will be kept")
    with col3:
        if 'assignee' in df.columns:
            unique_assignees = df['assignee'].nunique()
            st.metric("Unique assignees", unique_assignees)
    
    # Clean button
    if st.button("🚀 Clean and Deduplicate", type="primary"):
        with st.spinner("Cleaning data..."):
            cleaned_df = df.copy()
            cleaning_log = []
            
            # Step 1: Filter assignees if configured (with normalization)
            initial_count = len(cleaned_df)
            if configured_companies and 'assignee' in cleaned_df.columns and 'filter_assignees' in locals() and filter_assignees:
                # Define normalization function
                def normalize_company_name(name):
                    if pd.isna(name):
                        return ''
                    normalized = str(name).upper()
                    normalized = normalized.replace(',', '').replace('.', '').replace('!', '')
                    for suffix in [' INC', ' LLC', ' LTD', ' CORP', ' CORPORATION', ' COMPANY', ' CO', ' LIMITED', ' INCORPORATED']:
                        if normalized.endswith(suffix):
                            normalized = normalized[:-len(suffix)]
                    normalized = ' '.join(normalized.split())
                    return normalized.strip()
                
                # Normalize and filter
                normalized_config = [normalize_company_name(c) for c in configured_companies]
                cleaned_df['assignee_normalized'] = cleaned_df['assignee'].apply(normalize_company_name)
                before = len(cleaned_df)
                cleaned_df = cleaned_df[cleaned_df['assignee_normalized'].isin(normalized_config)]
                # Drop the normalized column after filtering
                cleaned_df = cleaned_df.drop('assignee_normalized', axis=1)
                removed = before - len(cleaned_df)
                if removed > 0:
                    cleaning_log.append(f"Removed {removed} patents from non-configured companies")
            
            # Step 2: Deduplication by patent ID only
            if dedup_by_id and 'patent_id' in cleaned_df.columns:
                before = len(cleaned_df)
                cleaned_df = cleaned_df.drop_duplicates(subset=['patent_id'], keep='first')
                removed = before - len(cleaned_df)
                if removed > 0:
                    cleaning_log.append(f"Removed {removed} duplicate patent IDs")
            
            # Reset index
            cleaned_df = cleaned_df.reset_index(drop=True)
            
            # Store cleaned data
            st.session_state.cleaned_data = cleaned_df
            
            # Show results
            st.success(f"✅ Cleaning complete! {len(df)} → {len(cleaned_df)} patents")
            
            # Show cleaning log
            if cleaning_log:
                st.markdown("### Cleaning Summary")
                for log_entry in cleaning_log:
                    st.info(f"• {log_entry}")
            
            # Show statistics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Original Patents", len(df))
            with col2:
                st.metric("Cleaned Patents", len(cleaned_df))
            with col3:
                st.metric("Removed", len(df) - len(cleaned_df))
            with col4:
                reduction_pct = ((len(df) - len(cleaned_df)) / len(df) * 100) if len(df) > 0 else 0
                st.metric("Reduction %", f"{reduction_pct:.1f}%")
            
            # Show sample of cleaned data
            st.markdown("### Sample of Cleaned Data")
            st.dataframe(cleaned_df.head(), use_container_width=True)
            
            # Offer download
            csv_data = cleaned_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Cleaned Data",
                data=csv_data,
                file_name=f"cleaned_patents_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    
    # Option to save to database (future enhancement)
    with st.expander("💾 Storage Options", expanded=False):
        st.info("Currently, data is stored in your browser session and can be downloaded as CSV.")
        st.markdown("**Future storage options:**")
        st.markdown("- PostgreSQL database connection")
        st.markdown("- SQLite local database")
        st.markdown("- Cloud storage (S3, GCS)")
        st.markdown("- Direct BigQuery export")
    
    return st.session_state.cleaned_data

def create_classification_ui():
    """UI for defining custom classifications"""
    st.markdown("## 🏷️ Step 4: Define Technology Stack Classifications")
    
    # Use cleaned data if available, otherwise use fetched data
    if st.session_state.cleaned_data is not None:
        df = st.session_state.cleaned_data
        st.info(f"Working with {len(df)} cleaned patents")
    elif st.session_state.fetched_data is not None:
        df = st.session_state.fetched_data
        st.warning("Using uncleaned data. Consider cleaning first for better results!")
    else:
        st.warning("Please fetch patent data first!")
        return None
    
    # Define two-tier classification hierarchy
    st.markdown("### Two-Tier Technology Stack Hierarchy")
    
    # Tier 1: Main Tech Stack Categories
    st.markdown("#### Tier 1: Main Technology Categories")
    tech_stack_input = st.text_area(
        "Define main technology categories (one per line)",
        value="hardware\nsoftware\nmiddleware",
        height=100
    )
    tech_stacks = [t.strip() for t in tech_stack_input.split('\n') if t.strip()]
    
    # Tier 2: Subcategories
    st.markdown("#### Tier 2: Subcategories")
    
    if not st.session_state.classifications:
        st.session_state.classifications = {
            'tech_stacks': tech_stacks,
            'subcategories': {},
            'keywords': {}
        }
    
    st.session_state.classifications['tech_stacks'] = tech_stacks
    
    # Add subcategories for each tech stack
    for tech_stack in tech_stacks:
        with st.expander(f"📂 Configure '{tech_stack}' subcategories", expanded=True):
            subcat_key = f"subcat_{tech_stack}"
            subcats_text = st.text_area(
                f"Subcategories for {tech_stack} (one per line)",
                key=subcat_key,
                height=150,
                placeholder="e.g., processors, memory, sensors"
            )
            subcats = [s.strip() for s in subcats_text.split('\n') if s.strip()]
            st.session_state.classifications['subcategories'][tech_stack] = subcats
    
    # Keyword-based classification
    st.markdown("### Keywords for Classification")
    
    keyword_mappings = {}
    for tech_stack in tech_stacks:
        for subcat in st.session_state.classifications['subcategories'].get(tech_stack, []):
            key = f"{tech_stack}_{subcat}"
            with st.expander(f"🔑 Keywords for {tech_stack} → {subcat}"):
                keywords_text = st.text_area(
                    "Enter keywords/phrases (one per line)",
                    key=f"kw_{key}",
                    height=120
                )
                keywords = [k.strip() for k in keywords_text.split('\n') if k.strip()]
                keyword_mappings[key] = keywords
    
    st.session_state.classifications['keywords'] = keyword_mappings
    
    # ML Classification settings
    st.markdown("### Classification Settings")
    
    col1, col2 = st.columns(2)
    with col1:
        ml_threshold = st.slider(
            "ML Similarity Threshold",
            min_value=0.15,
            max_value=0.60,
            value=0.30,  # Corrected based on actual normalized BERT ranges
            step=0.05,
            help="Recommended: 0.30 for balanced results, 0.25 for broader coverage, 0.35 for higher precision. Even with normalization, BERT similarities are lower than expected."
        )
    
    with col2:
        st.info("""
        **📊 Real BERT Similarity Ranges:**
        - **0.20-0.25**: Loosely related
        - **0.25-0.30**: Related technology
        - **0.30-0.35**: Strong match ✓
        - **0.35-0.40**: Very similar
        - **0.40+**: Nearly identical
        
        💡 Even normalized, BERT gives lower scores
        """)
    
    # Cache the model loading function
    @st.cache_resource
    def load_ml_model():
        """Load and cache the BERT model for patent classification"""
        from transformers import AutoTokenizer, AutoModel
        
        # Try models in order of preference
        models_to_try = [
            ("anferico/bert-for-patents", "patent-specific (Google BERT for Patents)"),
            ("prithivida/bert-for-patents-64d", "patent-specific (64d embeddings)"),
            ("AI-Growth-Lab/PatentSBERTa", "patent-specific (PatentSBERTa)"),
            ("allenai/scibert_scivocab_uncased", "scientific text"),
            ("bert-base-uncased", "general fallback")
        ]
        
        for model_name, model_type in models_to_try:
            try:
                tokenizer = AutoTokenizer.from_pretrained(model_name)
                model = AutoModel.from_pretrained(model_name)
                model.eval()
                return tokenizer, model, model_name, model_type
            except Exception as e:
                continue
        
        raise Exception("Could not load any BERT model. Please check your internet connection.")
    
    # Apply classification using ML
    with st.expander("ℹ️ How Self-Learning Classification Works"):
        st.markdown("""
        **Adaptive Learning Process:**
        1. **Initial Phase**: Uses keyword similarities to classify first patents
        2. **Learning Phase**: Each confident classification becomes a reference point
        3. **Mature Phase**: New patents are compared to both keywords AND previously classified patents
        4. **Result**: The model gets better at recognizing patterns specific to your domain as it processes more patents
        
        **No manual labeling needed!** The system learns from its own high-confidence predictions.
        """)
    
    if st.button("🎯 Apply ML Classification with Self-Learning", type="primary"):
        with st.spinner("Loading ML model... This may take a moment on first run."):
            try:
                import torch
                from sklearn.metrics.pairwise import cosine_similarity
                
                # Load cached model
                tokenizer, model, model_name, model_type = load_ml_model()
                
                if "patent-specific" in model_type:
                    st.success(f"✅ Loaded {model_type}: {model_name}")
                elif "scientific" in model_type:
                    st.info(f"ℹ️ Using scientific text model: {model_name}")
                else:
                    st.warning(f"⚠️ Using general model: {model_name}. Results may be less accurate for patent classification.")
                
                def get_embedding(text, max_length=512):
                    inputs = tokenizer(text, return_tensors="pt", max_length=max_length, 
                                      truncation=True, padding=True)
                    with torch.no_grad():
                        outputs = model(**inputs)
                    
                    # IMPORTANT: Use mean pooling instead of just [CLS] token for better similarity
                    # Mean pooling: average all token embeddings (except padding)
                    token_embeddings = outputs.last_hidden_state
                    attention_mask = inputs['attention_mask']
                    
                    # Expand attention mask for broadcasting
                    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                    
                    # Sum embeddings for non-padding tokens
                    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
                    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                    
                    # Calculate mean
                    mean_pooled = sum_embeddings / sum_mask
                    
                    # Normalize for better cosine similarity
                    normalized = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
                    
                    return normalized.numpy()
                
                st.success("✅ Model loaded successfully!")
                
                # Pre-compute keyword embeddings - use multiple embeddings per category
                st.info("Computing keyword embeddings for each category...")
                keyword_embeddings = {}
                category_patent_embeddings = {}  # Store embeddings of classified patents
                
                for key, keywords in keyword_mappings.items():
                    if keywords:
                        # Start with keyword embeddings
                        embeddings = []
                        for keyword in keywords[:10]:  # Limit to top 10 keywords to avoid memory issues
                            embeddings.append(get_embedding(keyword))
                        keyword_embeddings[key] = embeddings
                        
                        # Initialize empty list for patents that will be classified into this category
                        category_patent_embeddings[key] = []
                
                # Classify patents
                classified_df = df.copy()
                classified_df['tech_stack'] = ''
                classified_df['subcategory'] = ''
                classified_df['confidence'] = 0.0
                
                progress_bar = st.progress(0)
                total_patents = len(classified_df)
                
                # Debug info
                classifications_made = 0
                similarity_scores = []
                
                for idx, row in classified_df.iterrows():
                    if idx % 10 == 0:
                        progress_bar.progress(idx / total_patents)
                    
                    patent_text = str(row.get('title', '')) + ' ' + str(row.get('abstract', ''))
                    
                    if len(patent_text.strip()) > 10:
                        patent_embedding = get_embedding(patent_text)
                        
                        best_match = None
                        best_score = ml_threshold  # Use user-selected threshold
                        
                        for key, keyword_embs in keyword_embeddings.items():
                            # Calculate similarity with keyword embeddings
                            max_keyword_similarity = 0
                            for keyword_emb in keyword_embs:
                                similarity = cosine_similarity(patent_embedding, keyword_emb)[0][0]
                                max_keyword_similarity = max(max_keyword_similarity, similarity)
                            
                            # LEARNING: Also check similarity with previously classified patents in this category
                            max_patent_similarity = 0
                            if category_patent_embeddings[key]:  # If we have classified patents
                                for patent_emb in category_patent_embeddings[key]:
                                    similarity = cosine_similarity(patent_embedding, patent_emb)[0][0]
                                    max_patent_similarity = max(max_patent_similarity, similarity)
                            
                            # Combine both similarities (weighted average)
                            # As we classify more patents, patent similarity becomes more important
                            n_classified = len(category_patent_embeddings[key])
                            patent_weight = min(0.7, n_classified * 0.1)  # Up to 70% weight for patent similarity
                            keyword_weight = 1.0 - patent_weight
                            
                            final_similarity = (keyword_weight * max_keyword_similarity + 
                                              patent_weight * max_patent_similarity)
                            
                            if final_similarity > best_score:
                                best_score = final_similarity
                                best_match = key
                        
                        if best_match:
                            parts = best_match.split('_')
                            if len(parts) >= 2:
                                classified_df.at[idx, 'tech_stack'] = parts[0]
                                classified_df.at[idx, 'subcategory'] = '_'.join(parts[1:])
                            else:
                                classified_df.at[idx, 'tech_stack'] = best_match
                                classified_df.at[idx, 'subcategory'] = ''
                            classified_df.at[idx, 'confidence'] = float(best_score)
                            classifications_made += 1
                            
                            # LEARNING STEP: Add this patent's embedding to the category
                            # Only add high-confidence classifications to avoid drift
                            if best_score > ml_threshold + 0.05:  # Higher threshold for learning
                                # Limit stored embeddings to prevent memory issues
                                if len(category_patent_embeddings[best_match]) < 20:
                                    category_patent_embeddings[best_match].append(patent_embedding)
                        
                        # Debug: Show scores for first few patents
                        if idx < 3:
                            similarity_scores.append(f"Patent {idx}: best_score={best_score:.3f}, match={best_match}")
                
                progress_bar.progress(1.0)
                
                # Show debug information and learning progress
                if similarity_scores:
                    with st.expander("🔍 Debug: Classification & Learning Progress"):
                        for score_info in similarity_scores[:5]:
                            st.write(score_info)
                        st.info(f"Total classified: {classifications_made}/{total_patents}")
                        st.info(f"Threshold used: {ml_threshold}")
                        
                        # Show how many patents were learned from each category
                        st.write("**Learning Progress (patents added as references):**")
                        for key, embeddings in category_patent_embeddings.items():
                            if embeddings:
                                st.write(f"- {key}: {len(embeddings)} reference patents learned")
                
            except ImportError:
                st.error("Please install required packages: pip install transformers torch scikit-learn")
                
                # Fallback to keyword matching
                classified_df = df.copy()
                classified_df['tech_stack'] = ''
                classified_df['subcategory'] = ''
                classified_df['confidence'] = 0.0
                
                for idx, row in classified_df.iterrows():
                    text = (str(row.get('title', '')) + ' ' + str(row.get('abstract', ''))).lower()
                    
                    best_match = None
                    best_score = 0
                    
                    for key, keywords in keyword_mappings.items():
                        score = sum(1 for kw in keywords if kw.lower() in text)
                        if score > best_score:
                            best_score = score
                            best_match = key
                    
                    if best_match:
                        parts = best_match.split('_')
                        if len(parts) >= 2:
                            classified_df.at[idx, 'tech_stack'] = parts[0]
                            classified_df.at[idx, 'subcategory'] = '_'.join(parts[1:])
                            classified_df.at[idx, 'confidence'] = min(best_score / 5, 1.0)
        
        st.session_state.classified_data = classified_df
        
        # Show results
        st.success("✅ Classification complete!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Patents Classified", 
                     f"{len(classified_df[classified_df['tech_stack'] != ''])} / {len(classified_df)}")
        with col2:
            avg_confidence = classified_df['confidence'].mean()
            st.metric("Average Confidence", f"{avg_confidence:.2%}")
        
        # Offer download
        csv_data = classified_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Classified Patents",
            data=csv_data,
            file_name=f"classified_patents_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
        
        return classified_df
    
    return None

def create_visualization_tabs():
    """Create visualization tabs for results"""
    st.markdown("## 📊 Step 5: Visualize Results")
    
    if 'classified_data' not in st.session_state or st.session_state.classified_data is None:
        st.warning("Please classify patents first!")
        return
    
    df = st.session_state.classified_data
    
    # Create tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Overview",
        "🏢 Company Analysis", 
        "🔧 Tech Stack",
        "📊 Subcategories",
        "📅 Timeline"
    ])
    
    with tab1:
        st.markdown("### Patent Classification Overview")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Patents", len(df))
        with col2:
            st.metric("Companies", df['assignee'].nunique() if 'assignee' in df.columns else 0)
        with col3:
            st.metric("Tech Stacks", df['tech_stack'].nunique())
        with col4:
            st.metric("Subcategories", df['subcategory'].nunique())
        
        # Classification distribution
        col1, col2 = st.columns(2)
        
        with col1:
            tech_dist = df['tech_stack'].value_counts()
            if not tech_dist.empty:
                fig = px.pie(
                    values=tech_dist.values,
                    names=tech_dist.index,
                    title="Tech Stack Distribution"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            subcat_dist = df['subcategory'].value_counts().head(10)
            if not subcat_dist.empty:
                fig = px.bar(
                    x=subcat_dist.values,
                    y=subcat_dist.index,
                    orientation='h',
                    title="Top 10 Subcategories"
                )
                st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.markdown("### Company Analysis")
        
        if 'assignee' in df.columns:
            # Company comparison
            company_tech = df.groupby(['assignee', 'tech_stack']).size().reset_index(name='count')
            
            fig = px.bar(
                company_tech,
                x='assignee',
                y='count',
                color='tech_stack',
                title='Tech Stack by Company',
                barmode='stack'
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.markdown("### Tech Stack Analysis")
        
        selected_tech = st.selectbox("Select Tech Stack", df['tech_stack'].unique())
        
        tech_df = df[df['tech_stack'] == selected_tech]
        
        col1, col2 = st.columns(2)
        
        with col1:
            subcat_dist = tech_df['subcategory'].value_counts()
            if not subcat_dist.empty:
                fig = px.pie(
                    values=subcat_dist.values,
                    names=subcat_dist.index,
                    title=f"Subcategories in {selected_tech}"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            if 'assignee' in tech_df.columns:
                company_dist = tech_df['assignee'].value_counts().head(10)
                if not company_dist.empty:
                    fig = px.bar(
                        x=company_dist.index,
                        y=company_dist.values,
                        title=f"Top Companies in {selected_tech}"
                    )
                    st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.markdown("### Subcategory Deep Dive")
        
        selected_subcat = st.selectbox("Select Subcategory", df['subcategory'].unique())
        
        subcat_df = df[df['subcategory'] == selected_subcat]
        
        st.info(f"Found {len(subcat_df)} patents in {selected_subcat}")
        
        # Show sample patents
        st.markdown("#### Sample Patents")
        sample_cols = ['patent_id', 'title', 'assignee', 'filing_date']
        available_cols = [col for col in sample_cols if col in subcat_df.columns]
        if available_cols:
            st.dataframe(subcat_df[available_cols].head(10), use_container_width=True)
    
    with tab5:
        st.markdown("### Timeline Analysis")
        
        if 'filing_date' in df.columns:
            # Parse dates
            df['year'] = pd.to_datetime(df['filing_date'], errors='coerce').dt.year
            
            # Yearly trends
            yearly_tech = df.groupby(['year', 'tech_stack']).size().reset_index(name='count')
            
            fig = px.line(
                yearly_tech,
                x='year',
                y='count',
                color='tech_stack',
                title='Patent Filing Trends by Tech Stack',
                markers=True
            )
            st.plotly_chart(fig, use_container_width=True)

def main():
    """Main application"""
    st.title("🔬 PatentStack")
    st.markdown("### Classify patents into technology stack categories")
    st.markdown("---")
    
    # Sidebar navigation
    with st.sidebar:
        st.markdown("## Navigation")
        step = st.radio(
            "Select Step",
            ["1️⃣ Configure", "2️⃣ Fetch Data", "3️⃣ Clean Data", "4️⃣ Classify", "5️⃣ Visualize"],
            index=0
        )
        
        st.markdown("---")
        st.markdown("### Quick Actions")
        
        if st.button("🔄 Reset All"):
            for key in ['cpc_config', 'fetched_data', 'classifications', 'classified_data']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    # Main content based on selected step
    if "Configure" in step:
        create_cpc_configuration_ui()
    
    elif "Fetch" in step:
        fetch_patent_data()
    
    elif "Clean" in step:
        clean_and_deduplicate_data()
    
    elif "Classify" in step:
        create_classification_ui()
    
    elif "Visualize" in step:
        create_visualization_tabs()

if __name__ == "__main__":
    main()