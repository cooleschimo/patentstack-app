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
        'google_project_id': ''
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
        google_project = st.text_input(
            "Google Cloud Project ID (Optional)",
            value=st.session_state.api_keys['google_project_id'],
            placeholder="my-project-id",
            help="Required for Google Patents BigQuery. Set up at https://console.cloud.google.com"
        )
        st.session_state.api_keys['google_project_id'] = google_project
    
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
            puller = HybridPatentPuller(
                cpc_parser,
                uspto_api_key=st.session_state.api_keys['uspto_key'],
                google_project_id=st.session_state.api_keys['google_project_id'] if st.session_state.api_keys['google_project_id'] else None
            )
            
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
    ml_threshold = st.slider(
        "ML Similarity Threshold",
        min_value=0.3,
        max_value=0.7,
        value=0.5,
        step=0.05,
        help="Higher values = stricter matching (fewer but more accurate classifications). Lower values = more inclusive (more classifications but potentially less accurate). 50% is recommended for best precision."
    )
    
    # Apply classification using ML
    if st.button("🎯 Apply ML Classification", type="primary"):
        with st.spinner("Loading ML model... This may take a moment on first run."):
            try:
                from transformers import AutoTokenizer, AutoModel
                import torch
                from sklearn.metrics.pairwise import cosine_similarity
                
                # Load model
                model_name = "google/bert_for_patents"
                tokenizer = AutoTokenizer.from_pretrained(model_name)
                model = AutoModel.from_pretrained(model_name)
                model.eval()
                
                def get_embedding(text, max_length=512):
                    inputs = tokenizer(text, return_tensors="pt", max_length=max_length, 
                                      truncation=True, padding=True)
                    with torch.no_grad():
                        outputs = model(**inputs)
                    return outputs.last_hidden_state[:, 0, :].numpy()
                
                st.success("✅ Model loaded successfully!")
                
                # Pre-compute keyword embeddings
                keyword_embeddings = {}
                for key, keywords in keyword_mappings.items():
                    if keywords:
                        keyword_text = " ".join(keywords)
                        keyword_embeddings[key] = get_embedding(keyword_text)
                
                # Classify patents
                classified_df = df.copy()
                classified_df['tech_stack'] = ''
                classified_df['subcategory'] = ''
                classified_df['confidence'] = 0.0
                
                progress_bar = st.progress(0)
                total_patents = len(classified_df)
                
                for idx, row in classified_df.iterrows():
                    if idx % 10 == 0:
                        progress_bar.progress(idx / total_patents)
                    
                    patent_text = str(row.get('title', '')) + ' ' + str(row.get('abstract', ''))
                    
                    if len(patent_text.strip()) > 10:
                        patent_embedding = get_embedding(patent_text)
                        
                        best_match = None
                        best_score = ml_threshold  # Use user-selected threshold
                        
                        for key, keyword_emb in keyword_embeddings.items():
                            similarity = cosine_similarity(patent_embedding, keyword_emb)[0][0]
                            
                            if similarity > best_score:
                                best_score = similarity
                                best_match = key
                        
                        if best_match:
                            parts = best_match.split('_')
                            if len(parts) >= 2:
                                classified_df.at[idx, 'tech_stack'] = parts[0]
                                classified_df.at[idx, 'subcategory'] = '_'.join(parts[1:])
                                classified_df.at[idx, 'confidence'] = float(best_score)
                
                progress_bar.progress(1.0)
                
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