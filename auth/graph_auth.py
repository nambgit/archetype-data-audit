"""
Handle Microsoft Graph API authentication using Client Credentials Flow.
Returns access tokens for app-only access to SharePoint.
"""

import requests
from config.settings import settings

def get_graph_token():
    """
    Acquire an access token for Microsoft Graph API using client credentials.
    
    Returns:
        str: Access token valid for 1 hour
    
    Raises:
        requests.HTTPError: If token request fails
    """
    url = f"https://login.microsoftonline.com/{settings.GRAPH_TENANT_ID}/oauth2/v2.0/token"
    
    payload = {
        'client_id': settings.GRAPH_CLIENT_ID,
        'scope': 'https://graph.microsoft.com/.default',
        'client_secret': settings.GRAPH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    
    response = requests.post(url, data=payload)
    response.raise_for_status()  # Raise exception for HTTP errors
    
    token_data = response.json()
    return token_data['access_token']