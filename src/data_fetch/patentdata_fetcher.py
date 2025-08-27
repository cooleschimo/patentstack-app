#!/usr/bin/env python3
"""
# Patent Data Fetcher #
Reads configuration from YAML files and pulls patent data for specified companies
across any technology domains defined in the configuration.
- Uses USPTO API for US patents (FREE, no limits)
- Uses BigQuery for international patents (limits apply)
"""
import os, sys, argparse, yaml, logging, requests, time, json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from typing import Any
from dotenv import load_dotenv

### Set up #####################################################################
# Google Cloud BigQuery client setup
try: 
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound, BadRequest
except ImportError:
    print("Google Cloud libraries not found. Please install them with: pip install google-cloud-bigquery")
    sys.exit(1)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bigquery_pull.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

### CPC Code Configuration Parser ##############################################
class CPCParser:
    """
    Loads and parses CPC code classification configuration from YAML files.
    """
    config_path: Path
    config: dict[str, Any]
    domains: list[str]
    cpc_codes_dict: dict[str, list[str]]
    global_settings: dict[str, Any]

    def __init__(self, config_path: str = "config/cpc_codes.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.domains = self.get_domains()
        self.cpc_codes_dict = self.get_cpc_codes()
        self.global_settings = self.get_global_settings()

    def _load_config(self) -> dict[str, Any]:
        """
        Load configuration from YAML file.
        """
        try:
            with open(self.config_path, 'r') as file:
                config = yaml.safe_load(file)
                logger.info(f"Loaded configuration from {self.config_path}")
                return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            raise

    def get_domains(self) -> list:
        """
        Get list of tech domains defined in the config file.
        """
        if 'domains' not in self.config:
            logger.error("No domains defined in configuration")
            return []
        
        domains: list[str] = list(self.config.get('domains', {}).keys())
        logger.info(f"Found domains: {domains}")
        return domains

    def get_cpc_codes(self, domains: list[str] | None = None) -> dict[str, list[str]]:
        """
        Get CPC codes and keywords for a specific domain or all domains.
        If domain is None, returns all CPC codes across all domains.
        """
        # validity checks
        if domains is None:
            domains_to_process: list[str] = self.domains
        elif isinstance(domains, str):
            domains_to_process: list[str] = [domains]
        else:
            domains_to_process: list[str] = domains
        
        invalid_domains: list[str] = [d for d in domains_to_process if d not in self.domains]
        if invalid_domains:
            raise ValueError(f"Invalid domains: {invalid_domains}. Available: {self.domains}")

        # dict of domain to list of CPC codes under that domain
        cpc_codes_dict: dict[str, list[str]] = {}  
        for dom in domains_to_process:
            # get value (dict of cpc codes) from config dict corresponding to 
            # the key of the dom, then get value (list of cpc codes) from that 
            # dict with key 'cpc_codes'
            cpc_list: list[dict[str, Any]] = self.config['domains'][dom].get('cpc_codes', [])
            codes: list[str] = [cpc['code'] for cpc in cpc_list]
            cpc_codes_dict[dom] = codes

        return cpc_codes_dict

    def get_global_settings(self) -> dict[str, Any]:
        """Get global configuration settings."""
        global_settings: dict[str, Any] = self.config.get('global_settings', {})
        return global_settings

##### USPTO Api Patent Puller ##################################################
class USPTOPatentPuller:
    """
    Handles US patent data extraction using PatentsView API (official USPTO).
    """
    
    def __init__(self, cpc_parser: CPCParser, api_key: str | None = None):
        self.cpc_parser = cpc_parser
        self.api_key: str | None = api_key
        
        # PatentsView API settings
        self.base_url: str = "https://search.patentsview.org/api/v1"
        self.patents_endpoint: str = f"{self.base_url}/patent/"
        self.rate_limit_delay: float = 1.4 # rate limit: 45 requests/minute = 0.75 requests/second

    def _get_api_key(self) -> str:
        """
        Get API key from instance variable, environment, or raise error.
        """
        # First check if we have an API key stored
        if self.api_key and self.api_key.strip():
            return self.api_key
        
        # Try environment variable
        api_key: str | None = os.getenv('PATENTSVIEW_API_KEY')
        if api_key:
            return api_key
       
        logger.error("PatentsView API key not found.\n")
        raise ValueError(
            "\nRequired setup:\n"
            "Either provide API key in the app UI or create a .env file with:\n"
            "PATENTSVIEW_API_KEY=your_actual_api_key_here\n"
            "\nGet API key from: https://www.patentsview.org/api/keyrequest"
        )
    
    def _get_headers(self) -> dict[str, str]:
        """Get request headers with API key."""
        return {
            'X-Api-Key': self._get_api_key(),
            'Content-Type': 'application/json'
        }
        
    def _build_search_query(self, companies: list[str], domains: list[str], 
                        start_date: str, end_date: str) -> dict[str, Any]:
        """
        Build PatentsView API search query using correct field structure.
        """
        # Get CPC codes
        cpc_codes_dict: dict[str, list[str]] = self.cpc_parser.cpc_codes_dict
        all_cpc_codes: list[str] = []
        for dom in domains:
            if dom in cpc_codes_dict:
                all_cpc_codes.extend(cpc_codes_dict[dom])

        # Build query conditions
        query_conditions: list[dict[str, Any]] = [] 

        # 1) Company conditions
        if companies:
            company_conditions: list[dict[str, Any]] = []
            for company in companies:
                company_conditions.append({
                    "_text_any": {
                        "assignees.assignee_organization": company
                    }
                })

            if len(company_conditions) == 1:
                query_conditions.append(company_conditions[0])
            else:
                query_conditions.append({"_or": company_conditions})

        # 2) CPC conditions - FIXED to use correct field structure
        if all_cpc_codes:
            cpc_conditions: list[dict[str, Any]] = []
            for code in all_cpc_codes:
                # Use full group code directly from YAML (G06N10/70, H04L9/0852, etc.)
                cpc_conditions.append({
                    "cpc_at_issue.cpc_group_id": code
                })
            
            if cpc_conditions:
                query_conditions.append({"_or": cpc_conditions})

        # 3) Date conditions
        if start_date and end_date:
            query_conditions.extend([
                {"_gte": {"application.filing_date": start_date}},
                {"_lte": {"application.filing_date": end_date}}
            ])

        # Combine all conditions
        query = {"_and": query_conditions}

        # Fields to return - FIXED field names
        fields: list[str] = [
            "patent_id",
            "patent_title",
            "patent_abstract", 
            "patent_date",
            "patent_type",

            # APPLICATION INFO
            "application.application_number",  # for deduplication
            "application.filing_date",
            
            "assignees.assignee_organization",
            "assignees.assignee_city", 
            "assignees.assignee_state",
            "assignees.assignee_country",
            
            "cpc_at_issue.cpc_subclass_id",
            "cpc_at_issue.cpc_group_id",
            
            "inventors.inventor_name_first",
            "inventors.inventor_name_last",
        ]
        
        # Options
        options: dict[str, Any] = {
            "size": 100,
            "exclude_withdrawn": True
        }

        return {
            "q": query,
            "f": fields,
            "o": options
        }
    
    def _build_publication_search_query(self, companies: list[str], domains: list[str], 
                                  start_date: str, end_date: str) -> dict[str, Any]:
        """Build search query for pre-grant publications - different field names!"""
        
        # Get CPC codes 
        cpc_codes_dict: dict[str, list[str]] = self.cpc_parser.cpc_codes_dict
        all_cpc_codes: list[str] = []
        for dom in domains:
            if dom in cpc_codes_dict:
                all_cpc_codes.extend(cpc_codes_dict[dom])

        query_conditions: list[dict[str, Any]] = [] 

        # 1) Company conditions 
        if companies:
            company_conditions: list[dict[str, Any]] = []
            for company in companies:
                company_conditions.append({
                    "_contains": {
                        "assignees.assignee_organization": company
                    }
                })

            if len(company_conditions) == 1:
                query_conditions.append(company_conditions[0])
            else:
                query_conditions.append({"_or": company_conditions})

        # 2) CPC conditions 
        if all_cpc_codes:
            cpc_conditions: list[dict[str, Any]] = []
            for code in all_cpc_codes:
                cpc_conditions.append({
                    "cpc_at_issue.cpc_group_id": code  
                })
            
            if cpc_conditions:
                query_conditions.append({"_or": cpc_conditions})

        # 3) Date conditions 
        if start_date and end_date:
            query_conditions.extend([
                {"_gte": {"publication_date": start_date}}, 
                {"_lte": {"publication_date": end_date}}
            ])

        query = {"_and": query_conditions}

        # Fields - DIFFERENT FIELD NAMES
        fields: list[str] = [
            "document_number",        # ← Different from patent_id
            "publication_title",      # ← Different from patent_title
            "publication_abstract",   # ← Different from patent_abstract
            "publication_date",       # ← Different from patent_date
            "publication_type",
            
            # APPLICATION INFO
            "granted_pregrant_crosswalk.application_number",
            "granted_pregrant_crosswalk.patent_id",

            # Assignee fields same
            "assignees.assignee_organization",
            "assignees.assignee_city", 
            "assignees.assignee_state",
            "assignees.assignee_country",
            
            # CPC fields different
            "cpc_at_issue.cpc_subclass_id",  # ← Different from cpc_current
            "cpc_at_issue.cpc_group_id",     # ← Different from cpc_current
            
            # Inventor fields same
            "inventors.inventor_name_first",
            "inventors.inventor_name_last"
        ]

        return {"q": query, "f": fields, "o": {"size": 100, "exclude_withdrawn": True}}

    def _make_api_request(self, query: dict[str, Any]) -> dict[str, Any]:
        """
        Make rate-limited request to PatentsView API.
        """
        logger.info(f"USPTO Query: {json.dumps(query, indent=2)}")
        response = None
        try:
            time.sleep(self.rate_limit_delay)
        
            response = requests.post(
                self.patents_endpoint,
                json=query,
                headers=self._get_headers(),
                timeout=30
            )

            # [response status code checks] - rate or auth problems
            if response.status_code == 429:
                retry_after: int = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limit exceeded. Retrying after {retry_after} seconds.")
                time.sleep(retry_after)
                response = requests.post(
                    self.patents_endpoint,
                    json=query,
                    headers=self._get_headers()
                    )
            elif response.status_code == 403:
                logger.error("API authentication failed, check your API key.")
                raise ValueError("Invalid API key.")
        
            response.raise_for_status()

            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response status:{e.response.status_code}")
                logger.error(f"Response text: {e.response.text}")

                if e.response.status_code == 400:
                    logger.error("Bad request, check query format")
                elif e.response.status_code == 403:
                    logger.error("Authentication failed, check your API key")
                elif e.response.status_code == 404:
                    logger.error("Endpoint not found, check URL")

            raise
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse API response: {e}")
            if response is not None and hasattr(response, "text"):
                logger.error(f"Response text: {response.text[:500]}")
            else:
                logger.error("No response text available.")
            raise

    def pull_us_patents(self, companies: list[str], domains: list[str],
                    start_date: str, end_date: str, 
                    max_results: int | None = None) -> pd.DataFrame:
        """
        Pull USPTO US patents AND pre-grant publications for specified companies and domains.
        Combines both granted patents and pre-grant publications.
        """
        logger.info(f"Pulling US patents AND pre-grant publications from USPTO API")
        logger.info(f"Companies: {companies}")
        logger.info(f"Domains: {domains}")
        logger.info(f"Date range: {start_date} to {end_date}")

        all_results: list[dict[str, Any]] = []

        # 1) Pull granted patents
        try:
            logger.info("Fetching granted patents...")
            granted_patents = self._pull_granted_patents(companies, domains, start_date, end_date, max_results)
            logger.info(f"Retrieved {len(granted_patents)} granted patents")
            all_results.extend(granted_patents)
        except Exception as e:
            logger.error(f"Error fetching granted patents: {e}")

        # 2) Pull pre-grant publications
        try:
            logger.info("Fetching pre-grant publications...")
            publications = self._pull_publications(companies, domains, start_date, end_date, max_results)
            logger.info(f"Retrieved {len(publications)} pre-grant publications")
            all_results.extend(publications)
        except Exception as e:
            logger.error(f"Error fetching publications: {e}")

        logger.info(f"Total USPTO records: {len(all_results)}")
        
        # 3) Convert to standardized DataFrame
        df = self._standardize_uspto_data(all_results, companies, domains)
        
        # 4) Remove duplicates (same invention might appear as both publication and patent)
        """
        initial_count = len(df)

        # Sort to prefer granted patents, then deduplicate by application_number
        df = df.sort_values('record_type')  # 'granted_patent' comes before 'pre_grant_publication' alphabetically
        df = df.drop_duplicates(subset=['application_number'], keep='first')

        final_count = len(df)

        if initial_count > final_count:
            logger.info(f"Removed {initial_count - final_count} duplicates by application_number")
            logger.info(f"Final unique applications: {final_count}")
        """
        logger.info(f"Total USPTO records (no deduplication): {len(df)}")

        return df

    def _pull_granted_patents(self, companies: list[str], domains: list[str],
                         start_date: str, end_date: str, max_results: int | None) -> list[dict]:
        """Pull from /api/v1/patent/ endpoint."""
        endpoint = f"{self.base_url}/patent/"
        query = self._build_search_query(companies, domains, start_date, end_date)
        return self._paginate_api_requests(endpoint, query, "patents", max_results)

    def _pull_publications(self, companies: list[str], domains: list[str],
                        start_date: str, end_date: str, max_results: int | None) -> list[dict]:
        """Pull from /api/v1/publication/ endpoint."""
        try:
            endpoint = f"{self.base_url}/publication/"
            query = self._build_publication_search_query(companies, domains, start_date, end_date)
            return self._paginate_api_requests(endpoint, query, "publications", max_results)
        except Exception as e:
            logger.warning(f"Publications endpoint failed: {e}")
            logger.info("Skipping pre-grant publications due to API error")
            return []  # Return empty list instead of raising

    def _paginate_api_requests(self, endpoint: str, base_query: dict, response_key: str, 
                            max_results: int | None) -> list[dict]:
        """Generic pagination handler for both patents and publications."""
        all_records: list[dict[str, Any]] = []
        page_count = 0
        cursor_value = None
        base_page_size = base_query.get('o', {}).get("size", 100)

        while True:
            page_count += 1
            
            query = base_query.copy()
            pagination_options = query.get('o', {}).copy()
            
            if cursor_value is not None:
                pagination_options['after'] = cursor_value
            
            query["o"] = pagination_options

            try: 
                time.sleep(self.rate_limit_delay)
                
                response = requests.post(endpoint, json=query, headers=self._get_headers(), timeout=30)
                response.raise_for_status()
                
                json_response = response.json()
                
                if json_response.get('error', False):
                    logger.error(f"API error: {json_response.get('error', 'Unknown error')}")
                    break

                page_records: list[dict[str, Any]] = json_response.get(response_key, [])
                if not page_records:
                    logger.info(f"No more {response_key} found, reached end of results.")
                    break

                all_records.extend(page_records)

                # Check limits and pagination
                if max_results and len(all_records) >= max_results:
                    all_records = all_records[:max_results]
                    break

                if len(page_records) < base_page_size:
                    break
                    
                # Set cursor for next page
                id_field = 'patent_id' if response_key == 'patents' else 'document_number'
                cursor_value = page_records[-1].get(id_field)
                
                if not cursor_value or page_count > 1000:
                    break

            except Exception as e:
                logger.error(f"Error fetching {response_key} page {page_count}: {e}")
                if page_count == 1:
                    raise
                break

        return all_records

    def _standardize_uspto_data(self, records: list[dict[str, Any]], 
                        companies: list[str], 
                        domains: list[str]) -> pd.DataFrame:
        """
        Standardize raw data - keep original field names, only normalize title/abstract.
        """
        if not records:  # Add this check
        # Return empty DataFrame with all expected columns
            empty_df = pd.DataFrame()
            # Add all expected columns with empty values
            for col in ['patent_id', 'document_number', 'application_number', 
                    'title', 'abstract', 'filing_date', 'publication_date',
                    'country_code', 'kind_code', 'record_type', 'assignee',
                    'assignee_city', 'assignee_state', 'assignee_country',
                    'inventors', 'cpc_codes', 'patent_url', 'extracted_at',
                    'target_domains', 'target_companies', 'data_source']:
                empty_df[col] = []
            for domain in domains:
                empty_df[f'{domain}_relevant'] = []
            return empty_df
            
        standardized_data: list[dict[str, Any]] = []

        for record in records:
            # Detect record type
            is_patent = 'patent_id' in record
            
            # Extract application info from nested structures
            if is_patent:
                # For patents: get from application nested field
                application_info = record.get('application', [{}])
                app_data = application_info[0] if application_info else {}
                application_number = app_data.get('application_number', '')
                actual_filing_date = app_data.get('filing_date', '')
            else:
                # For publications: get from crosswalk nested field
                crosswalk_info = record.get('granted_pregrant_crosswalk', [{}])
                crosswalk_data = crosswalk_info[0] if crosswalk_info else {}
                application_number = crosswalk_data.get('application_number', '')
                actual_filing_date = record.get('publication_date', '')  # filing = publication for publications
            
            standardized_record: dict[str, Any] = {
                # Keep original ID field names separate
                'patent_id': record.get('patent_id', '') if is_patent else '',
                'document_number': record.get('document_number', '') if not is_patent else '',
                'application_number': application_number,  # For deduplication
                
                # Normalize ONLY title and abstract (different field names)
                'title': record.get('patent_title') if is_patent else record.get('publication_title', ''),
                'abstract': record.get('patent_abstract') if is_patent else record.get('publication_abstract', ''),
                
                # Date fields
                'filing_date': actual_filing_date,  # Actual filing date from both sources
                'publication_date': record.get('patent_date', '') if is_patent else record.get('publication_date', ''),
                
                # Geographic/administrative
                'country_code': 'US',
                'kind_code': record.get('patent_type') if is_patent else record.get('publication_type', ''),
                'record_type': 'granted_patent' if is_patent else 'pre_grant_publication',
                
                # People and organizations
                'assignee': self._extract_assignees(record),  # Changed to singular
                'assignee_city': self._extract_assignee_city(record),
                'assignee_state': self._extract_assignee_state(record),
                'assignee_country': self._extract_assignee_country(record),
                'inventors': self._extract_inventors(record),
                
                # Classifications
                'cpc_codes': self._extract_cpc_codes(record),
                
                # URLs and metadata
                'patent_url': f"https://patents.uspto.gov/patent/{record.get('patent_id' if is_patent else 'document_number', '')}",
                'extracted_at': datetime.now().isoformat(),
                'target_domains': ','.join(domains),
                'target_companies': ','.join(companies),
                'data_source': 'USPTO_Patents' if is_patent else 'USPTO_Publications'
            }
            standardized_data.append(standardized_record)

        df = pd.DataFrame(standardized_data)
        
        # Add domain relevance columns
        for domain in domains:
            df[f'{domain}_relevant'] = False

        return df

    def _extract_assignees(self, patent: dict[str, Any]) -> str:  
        """Extract assignee organization name."""
        assignees = patent.get('assignees', [])
        if assignees and len(assignees) > 0:
            return assignees[0].get('assignee_organization', '')
        return ''

    def _extract_assignee_city(self, patent: dict[str, Any]) -> str:
        """Extract assignee city."""
        assignees = patent.get('assignees', [])
        if assignees and len(assignees) > 0:
            return assignees[0].get('assignee_city', '')
        return ''

    def _extract_assignee_state(self, patent: dict[str, Any]) -> str:
        """Extract assignee state."""
        assignees = patent.get('assignees', [])
        if assignees and len(assignees) > 0:
            return assignees[0].get('assignee_state', '')
        return ''

    def _extract_assignee_country(self, patent: dict[str, Any]) -> str:
        """Extract assignee country."""
        assignees = patent.get('assignees', [])
        if assignees and len(assignees) > 0:
            return assignees[0].get('assignee_country', '')
        return ''

    def _extract_inventors(self, patent: dict[str, Any]) -> str:  
        """Extract inventor information from nested structure."""
        inventors = patent.get('inventors', [])
        if inventors and len(inventors) > 0:
            first = inventors[0].get('inventor_name_first', '')
            last = inventors[0].get('inventor_name_last', '')
            return f"{first} {last}".strip()
        return ''

    def _extract_cpc_codes(self, patent: dict[str, Any]) -> str:
        """Extract CPC codes from cpc_at_issue structure."""
        cpc_at_issue = patent.get('cpc_at_issue', [])
        if cpc_at_issue and len(cpc_at_issue) > 0:
            return cpc_at_issue[0].get('cpc_group_id', '')  # Use group_id
        return ''
    
###Google Patent Puller ########################################################
class GooglePatentPuller:
    """
    Handles international patent data extraction using BigQuery.
    """
    project_id: str | None
    cpc_parser: CPCParser
    client: bigquery.Client
    global_settings: dict[str, Any]
    patents_dataset: str

    def __init__(self, cpc_parser: CPCParser, project_id: str | None = None, credentials: Any = None) -> None:
        self.project_id = project_id if project_id else os.getenv('BIGQUERY_PROJECT_ID')
        if not self.project_id or not self.project_id.strip():
            raise ValueError(
                "BigQuery project ID not found or empty. "
                "Please provide a valid project_id parameter."
            )
        self.cpc_parser = cpc_parser
        self.credentials = credentials
        self.client = None
        self.global_settings = cpc_parser.global_settings
        self.patents_dataset = "patents-public-data.patents.publications"
    
    def _get_client(self) -> bigquery.Client:
        """Lazy initialization of BigQuery client."""
        if self.client is None:
            try:
                if self.credentials:
                    # Use provided credentials
                    self.client = bigquery.Client(project=self.project_id, credentials=self.credentials)
                    logger.info(f"BigQuery client initialized with provided credentials for project: {self.project_id}")
                else:
                    # Try to use application default credentials
                    self.client = bigquery.Client(project=self.project_id)
                    logger.info(f"BigQuery client initialized with default credentials for project: {self.project_id}")
            except Exception as e:
                logger.error(f"Failed to initialize BigQuery client: {e}")
                raise ValueError(
                    f"Failed to initialize BigQuery client. \n"
                    f"Please authenticate with Google Cloud or provide credentials.\n"
                    f"Error: {e}"
                )
        return self.client

    def _build_intl_query(self, companies: list[str],
                      domains: list[str],
                      start_date: str, end_date: str,
                      exclude_countries: list[str]) -> str:
        """
        Build working BigQuery SQL using correct field names.
        """
        # Get CPC codes and extract subclass IDs
        cpc_codes_dict: dict[str, list[str]] = self.cpc_parser.cpc_codes_dict
        all_cpc_codes: list[str] = []
        for dom in domains:
            if dom in cpc_codes_dict:
                all_cpc_codes.extend(cpc_codes_dict[dom])

        subclass_ids: set[str] = set()
        for code in all_cpc_codes:
            if len(code) >= 6:
                subclass_ids.add(code[:6])

        # Build CPC conditions
        cpc_conditions: list[str] = []
        for code in all_cpc_codes:
            # Use exact match for all codes from YAML (G06N10/70, H04L9/0852, etc.)
            cpc_conditions.append(f"c.code = '{code}'")

        cpc_filter = ' OR '.join(cpc_conditions)

        # Company conditions
        company_conditions: list[str] = []
        for company in companies:
            company_conditions.append(f"LOWER(a.name) LIKE '%{company.lower()}%'")
        
        company_filter = ' OR '.join(company_conditions)

        # Date filter
        start_date_int = start_date.replace('-', '')
        end_date_int = end_date.replace('-', '')

        query = f"""
        SELECT
            publication_number,
            publication_date,
            filing_date,
            country_code,
            kind_code,
            application_number,
            
            (SELECT a.name FROM UNNEST(assignee_harmonized) a LIMIT 1) AS assignee,
            
            (SELECT i.name FROM UNNEST(inventor_harmonized) i LIMIT 1) AS inventor_name,
            
            ARRAY(
            SELECT c.code
            FROM UNNEST(cpc) AS c
            WHERE {cpc_filter}
            ) AS cpc_codes,
            
            title_localized AS title,
            abstract_localized AS abstract,
            
            CONCAT('https://patents.google.com/patent/', publication_number) as patent_url,
            CURRENT_TIMESTAMP() as extracted_at,
            '{",".join(domains)}' as target_domains,
            '{",".join(companies)}' as target_companies,
            'BigQuery' as data_source
            
        FROM `patents-public-data.patents.publications`
        WHERE filing_date >= {start_date_int}
            AND filing_date <= {end_date_int}
            AND country_code NOT IN ('{"', '".join(exclude_countries)}')
            AND EXISTS (
                SELECT 1
                FROM UNNEST(assignee_harmonized) a
                WHERE {company_filter}
            )
            AND EXISTS (
                SELECT 1
                FROM UNNEST(cpc) c
                WHERE {cpc_filter}
            )
        ORDER BY filing_date DESC
        """

        return query
    
    def _execute_query(self, query: str, max_cost_usd: float | None) -> pd.DataFrame:
        """
        Execute BigQuery and return results in a df (with optional cost limit)
        """
        logger.info(f"BigQuery SQL: {query}")
        # estimate cost
        job_config: bigquery.QueryJobConfig = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

        try:
            job: bigquery.QueryJob = self._get_client().query(query, job_config=job_config)
            bytes_processed: int = job.total_bytes_processed
            gb_processed: float = bytes_processed / (1024**3)
            tb_processed: float = bytes_processed / (1024**4)
            estimated_cost: float = max(0, (tb_processed - 1.0)) * 5.0
            
            logger.info(f"International query will process ~{gb_processed:.2f} GB")
            logger.info(f"Estimated cost: ${estimated_cost:.2f}")
            
            # Only check cost limit if one is provided
            if max_cost_usd is not None and estimated_cost > max_cost_usd:
                raise ValueError(
                    f"Query cost (${estimated_cost:.2f}) exceeds maximum allowed (${max_cost_usd:.2f}). "
                    f"To proceed anyway, set max_cost_usd=None or increase the limit."
                )
            elif max_cost_usd is None:
                logger.info("No cost limit set - proceeding with query execution")
            else:
                logger.info(f"Cost ${estimated_cost:.2f} is within limit ${max_cost_usd:.2f} - proceeding")
            
            # execute query
            logger.info("Executing BigQuery for international patents...")
            start_time: float = time.time()
            
            job = self._get_client().query(query)
            results = job.result()
            df: pd.DataFrame = results.to_dataframe()
            
            execution_time: float = time.time() - start_time
            logger.info(f"BigQuery query completed in {execution_time:.2f} seconds")
            logger.info(f"Retrieved {len(df)} international patent records")
            logger.info(f"Final cost: ${estimated_cost:.2f}")
            
            return df
            
        except Exception as e:
            logger.error(f"Error executing BigQuery query: {e}")
            raise


    def pull_international_patents(self, companies: list[str], 
                                   domains: list[str],
                                   start_date: str, end_date: str, 
                                   exclude_countries: list[str] = ['US'],
                                   max_cost_usd: float | None = None) -> pd.DataFrame:
        """
        Pull international patents (non-US) from BigQuery
        """
        logger.info(f"Pulling international patents using BigQuery")
        logger.info(f"Excluding countries: {exclude_countries}")
        if max_cost_usd is None:
            logger.info("No cost limit set - run query regardless of estimated cost")
        else:
            logger.info(f"Cost limit: ${max_cost_usd}")

        # build query
        query: str = self._build_intl_query(companies, domains, start_date, end_date, exclude_countries)

        df = self._execute_query(query, max_cost_usd)

        df = self._standardize_bigquery_data(df, companies, domains)

        return df

    def _standardize_bigquery_data(self, df: pd.DataFrame, 
                              companies: list[str], domains: list[str]) -> pd.DataFrame:
        """
        Standardize BigQuery data to match USPTO structure exactly.
        """
        standardized_df = df.copy()
        
        # Map BigQuery fields to USPTO field names
        standardized_df['patent_id'] = standardized_df.get('publication_number', '')
        standardized_df['document_number'] = standardized_df.get('application_number', '')
        
        # Assignee fields - already singular 'assignee' from BigQuery
        # No need to rename, just ensure it exists
        if 'assignee' not in standardized_df.columns:
            standardized_df['assignee'] = ''
        standardized_df['assignee_city'] = ''  # International patents don't have city
        standardized_df['assignee_state'] = ''  # International patents don't have state  
        if 'assignee_country' not in standardized_df.columns:
            standardized_df['assignee_country'] = ''
        
        # Inventor field
        standardized_df['inventors'] = standardized_df.get('inventor_name', '')
        
        # Handle CPC codes array - get first code
        if 'cpc_codes' in standardized_df.columns:
            standardized_df['cpc_codes'] = standardized_df['cpc_codes'].apply(
                lambda x: x[0] if isinstance(x, list) and len(x) > 0 else ''
            )
        else:
            standardized_df['cpc_codes'] = ''
        
        # Record type logic - same as USPTO
        standardized_df['record_type'] = standardized_df.apply(
            lambda row: 'granted_patent' if row.get('patent_id', '') else 'pre_grant_publication',
            axis=1
        )
        
        # Ensure all required columns exist with defaults
        required_columns = {
            'patent_id': '',
            'document_number': '',
            'application_number': '',
            'title': '',
            'abstract': '',
            'filing_date': '',
            'publication_date': '',
            'country_code': '',
            'kind_code': '',
            'record_type': 'international_patent',
            'assignee': '',  # Changed to singular
            'assignee_city': '',
            'assignee_state': '', 
            'assignee_country': '',
            'inventors': '',
            'cpc_codes': '',
            'patent_url': '',
            'extracted_at': '',
            'target_domains': '',
            'target_companies': '',
            'data_source': 'BigQuery'
        }
        
        for col, default_value in required_columns.items():
            if col not in standardized_df.columns:
                standardized_df[col] = default_value
        
        # Add domain relevance columns
        for domain in domains:
            standardized_df[f'{domain}_relevant'] = False
        
        return standardized_df
    
### Hybrid Puller #########################################################
class HybridPatentPuller:
    """
    Orchestrates both US and international patent data extraction.
    """
    def __init__(self, cpc_parser: CPCParser, uspto_api_key: str | None = None, 
                 google_project_id: str | None = None, google_credentials: Any = None) -> None:
        self.cpc_parser = cpc_parser
        
        # USPTO puller 
        self.uspto_puller = USPTOPatentPuller(cpc_parser, api_key=uspto_api_key)
        logger.info("USPTO API initialized for US patents (FREE)")

        # BigQuery puller - only initialize if we have a valid project ID
        self.bigquery_puller = None
        if google_project_id and google_project_id.strip():
            try:
                self.bigquery_puller = GooglePatentPuller(cpc_parser, project_id=google_project_id, credentials=google_credentials)
                logger.info("BigQuery initialized for international patents")
            except Exception as e:
                logger.warning(f"BigQuery initialization skipped: {e}")
                logger.info("Continuing with USPTO data only")
                self.bigquery_puller = None
        else:
            logger.info("No Google project ID provided, using USPTO data only")
            self.bigquery_puller = None

    def pull_patents_recent_first(self, companies: list[str], 
                                 start_year: int, end_year: int,
                                 domains: list[str] | None = None,
                                 max_international_cost: float = 10.0,
                                 output_dir: str = "data/raw/") -> dict[str, list[pd.DataFrame]]:
        """
        Pull patents starting from most recent year, working backwards.
        
        Args:
            companies: List of company names to search for
            start_year: Starting year (inclusive)
            end_year: Ending year (inclusive) 
            domains: Technology domains to search (uses all if None)
            max_international_cost: Maximum BigQuery cost in USD
            output_dir: Directory to save CSV files
            
        Returns:
            Dictionary with 'us_patents' and 'international_patents' DataFrames
        """
        
        # Use all domains if none specified
        if domains is None:
            domains = self.cpc_parser.domains
            logger.info(f"Using all configured domains: {domains}")
        
        # Generate years in reverse order (recent first)
        years: list[int] = list(range(end_year, start_year - 1, -1))
        logger.info(f"Processing years: {years} (recent to older)")
        
        results: dict[str, list[pd.DataFrame]] = {
            'us_patents': [],
            'international_patents': []
        }
        
        total_years = len(years)

        for i, year in enumerate(years):
            year_start: str = f"{year}-01-01"
            year_end: str = f"{year}-12-31"
            
            logger.info(f"Processing year {year} ({i+1}/{total_years})")
            
            try:
                # Process each company separately
                for company in companies:
                    logger.info(f"Processing {company} for year {year}")
                    
                    # Always pull US patents
                    try:
                        us_df = self.uspto_puller.pull_us_patents(
                            companies=[company],
                            domains=domains,
                            start_date=year_start,
                            end_date=year_end
                        )
                        
                        if not us_df.empty:
                            us_output_path = f"{output_dir}/US/{company}/{company}_us_patents_{year}.csv"
                            os.makedirs(os.path.dirname(us_output_path), exist_ok=True)
                            us_df.to_csv(us_output_path, index=False)
                            logger.info(f"Saved {len(us_df)} US patents for {company} {year}")
                            results['us_patents'].append(us_df)
                        else:
                            logger.info(f"No US patents found for {company} {year}")
                    
                    except Exception as e:
                        logger.error(f"Failed to get US patents for {company} {year}: {e}")
                    
                    # Pull international patents
                    try:
                        intl_df = self.bigquery_puller.pull_international_patents(
                            companies=[company],
                            domains=domains,
                            start_date=year_start,
                            end_date=year_end,
                            max_cost_usd=max_international_cost
                        )
                        
                        if not intl_df.empty:
                            intl_output_path = f"{output_dir}/International/{company}/{company}_intl_patents_{year}.csv"
                            os.makedirs(os.path.dirname(intl_output_path), exist_ok=True)
                            intl_df.to_csv(intl_output_path, index=False)
                            logger.info(f"Saved {len(intl_df)} international patents for {company} {year}")
                            results['international_patents'].append(intl_df)
                        else:
                            logger.info(f"No international patents found for {company} {year}")
                            
                    except Exception as e:
                        logger.warning(f"Failed to get international patents for {company} {year}: {e}")
                        logger.info("Continuing with US patents only...")
                
            except Exception as e:
                logger.error(f"Critical error processing year {year}: {e}")
                continue

        # Final summary
        total_us = sum(len(df) for df in results['us_patents'])
        total_intl = sum(len(df) for df in results['international_patents'])
        
        logger.info(f"Patent extraction complete!")
        logger.info(f"Total US patents: {total_us}")
        logger.info(f"Total international patents: {total_intl}")
        
        if total_intl > 0:
            estimated_cost = total_intl * 0.01  # Rough estimate
            logger.info(f"Estimated BigQuery cost: ${estimated_cost:.2f}")
        
        logger.info(f"Data saved to: {output_dir}")
        
        return results
    
### MAIN FUNCTION ##############################################################
def main() -> None:
    """Command-line interface for the hybrid patent puller."""
    # Load from .env if available (for command-line usage)
    try:
        load_dotenv('../../.env')
    except:
        pass

    parser = argparse.ArgumentParser(
        description='Patent Data Fetcher - Pull patent data from USPTO and BigQuery',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python patent_fetcher.py --companies "IBM" "Google" --start-year 2022 --end-year 2024 --domains quantum_computing
  
  python patent_fetcher.py --companies "IBM" --start-year 2023 --end-year 2023 --bigquery-project-id my-project-123
        """
    )
    
    # Required arguments
    parser.add_argument('--companies', nargs='+', required=True,
                       help='Company names to search for')
    parser.add_argument('--start-year', type=int, required=True,
                       help='Start year for patents')
    parser.add_argument('--end-year', type=int, required=True,
                       help='End year for patents')
    
    # Optional arguments
    parser.add_argument('--domains', nargs='+',
                       help='Technology domains (default: all domains in config)')
    parser.add_argument('--config', default='../../config/cpc_codes.yaml',
                       help='Path to CPC configuration file')
    parser.add_argument('--max-international-cost', type=float, default=10.0,
                       help='Maximum BigQuery cost in USD')
    parser.add_argument('--output-dir', default='../../data/raw/',
                       help='Output directory for CSV files')
    
    args = parser.parse_args()
    
    # Validation
    if args.start_year > args.end_year:
        parser.error("Start year must be <= end year")
    
    if args.end_year > datetime.now().year:
        parser.error(f"End year cannot be in the future (current year: {datetime.now().year})")
    
    try:
        # Load configuration
        logger.info(f"Loading configuration from: {args.config}")
        cpc_parser = CPCParser(args.config)
        
        # Validate domains
        if args.domains:
            invalid_domains = [d for d in args.domains if d not in cpc_parser.domains]
            if invalid_domains:
                logger.error(f"Invalid domains: {invalid_domains}")
                logger.info(f"Available domains: {cpc_parser.domains}")
                sys.exit(1)
        
        # Initialize hybrid puller
        logger.info("Initializing patent data fetcher...")
        puller = HybridPatentPuller(cpc_parser=cpc_parser)
        
        # Display what we're about to do
        logger.info(f"Companies: {args.companies}")
        logger.info(f"Years: {args.start_year} to {args.end_year}")
        logger.info(f"Domains: {args.domains or cpc_parser.domains}")
        logger.info(f"BigQuery cost limit: ${args.max_international_cost}")
        
        # Pull patents
        logger.info("Starting patent extraction...")
        results = puller.pull_patents_recent_first(
            companies=args.companies,
            start_year=args.start_year,
            end_year=args.end_year,
            domains=args.domains,
            max_international_cost=args.max_international_cost,
            output_dir=args.output_dir
        )
        
        # Final summary
        total_us = sum(len(df) for df in results['us_patents'])
        total_intl = sum(len(df) for df in results['international_patents'])
        
        print(f"Patent extraction completed successfully!")
        print(f"Results:")
        print(f"   US patents: {total_us:,}")
        print(f"   International patents: {total_intl:,}")
        print(f"   Total patents: {total_us + total_intl:,}")
        print(f"Data saved to: {args.output_dir}")
        
        if total_intl > 0:
            estimated_cost = total_intl * 0.01
            print(f"Estimated BigQuery cost: ${estimated_cost:.2f}")
        
        print(f"Next steps:")
        print(f"   1. Check your data: ls {args.output_dir}")
        print(f"   2. Start ML training with the CSV files")
        
    except KeyboardInterrupt:
        logger.info("Extraction cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()