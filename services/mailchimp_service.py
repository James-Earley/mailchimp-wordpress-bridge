import base64
import requests
from .. import config

class MailchimpService:
    def __init__(self):
        """Initialize the Mailchimp service with configuration."""
        self.api_key = config.MAILCHIMP_API_KEY
        config_data = config.validate_config()
        self.data_center = config_data["mailchimp_data_center"]
        
        # Prepare authentication
        auth = base64.b64encode(f"anystring:{self.api_key}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        }
    
    def get_campaign_content(self, campaign_id):
        """Fetch campaign content from Mailchimp API."""
        content_url = f"https://{self.data_center}.api.mailchimp.com/3.0/campaigns/{campaign_id}/content"
        
        content_res = requests.get(content_url, headers=self.headers)
        content_res.raise_for_status()
        return content_res.json()
    
    def get_campaign_details(self, campaign_id):
        """Fetch campaign details from Mailchimp API."""
        details_url = f"https://{self.data_center}.api.mailchimp.com/3.0/campaigns/{campaign_id}"
        
        details_res = requests.get(details_url, headers=self.headers)
        details_res.raise_for_status()
        return details_res.json()
    
    def get_complete_campaign(self, campaign_id):
        """Fetch both content and details, combining them into one object."""
        content = self.get_campaign_content(campaign_id)
        details = self.get_campaign_details(campaign_id)
        
        # Add subject line to content object
        content['subject_line'] = details.get('settings', {}).get('subject_line', '')
        return content