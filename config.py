import os

# Mailchimp configuration
MAILCHIMP_API_KEY = os.environ.get('MAILCHIMP_API_KEY')

# WordPress configuration
WORDPRESS_URL = os.environ.get('WORDPRESS_URL')
WORDPRESS_USERNAME = os.environ.get('WORDPRESS_USERNAME')
WORDPRESS_APP_PASSWORD = os.environ.get('WORDPRESS_APP_PASSWORD')

# Server configuration
PORT = int(os.environ.get('PORT', 5000))

def validate_config():
    """Validate that all required configuration is present."""
    if not MAILCHIMP_API_KEY or '-' not in MAILCHIMP_API_KEY:
        raise Exception("MAILCHIMP_API_KEY not set or invalid.")
    
    if not (WORDPRESS_URL and WORDPRESS_USERNAME and WORDPRESS_APP_PASSWORD):
        raise Exception("WordPress environment variables not set properly.")
    
    # Extract Mailchimp data center from API key
    data_center = MAILCHIMP_API_KEY.split('-')[1]
    
    return {
        "mailchimp_data_center": data_center
    }