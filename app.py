import os
import base64
import requests
import json

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)

def get_mailchimp_campaign(campaign_id):
    """Fetch campaign content from Mailchimp API."""
    api_key = os.environ.get('MAILCHIMP_API_KEY')
    if not api_key or '-' not in api_key:
        raise Exception("MAILCHIMP_API_KEY not set or invalid.")

    data_center = api_key.split('-')[1]

    # Content endpoint
    content_url = f"https://{data_center}.api.mailchimp.com/3.0/campaigns/{campaign_id}/content"
    # Campaign details endpoint
    details_url = f"https://{data_center}.api.mailchimp.com/3.0/campaigns/{campaign_id}"

    auth = base64.b64encode(f"anystring:{api_key}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json"
    }

    # Get HTML content
    content_res = requests.get(content_url, headers=headers)
    content_res.raise_for_status()
    content_json = content_res.json()

    # Get subject line
    details_res = requests.get(details_url, headers=headers)
    details_res.raise_for_status()
    subject_line = details_res.json().get('settings', {}).get('subject_line', '')

    content_json['subject_line'] = subject_line
    return content_json

def parse_email_content(campaign_data):
    """Extract structured content from the campaign HTML."""
    html = campaign_data.get('html', '')
    soup = BeautifulSoup(html, 'html.parser')

    structured = {
        'title': campaign_data.get('subject_line', ''),
        'text_blocks': [],
        'images': [],
        'call_to_action': None
    }

    # Example parsing paragraphs inside .mcnTextContent
    for paragraph in soup.select('td.mcnTextContent p'):
        text = paragraph.get_text(strip=True)
        if text:
            structured['text_blocks'].append({
                'type': 'paragraph',
                'content': text
            })

    # Example: parse images, skipping logos/icons
    for img in soup.select('img'):
        src = img.get('src')
        alt = img.get('alt', '')
        if src and not any(keyword in src.lower() for keyword in ['logo', 'icon', 'footer']):
            structured['images'].append({
                'url': src,
                'alt': alt
            })

    # Example: parse CTA button
    cta = soup.select_one('a.mcnButton')
    if cta:
        structured['call_to_action'] = {
            'text': cta.get_text(strip=True),
            'url': cta.get('href', '')
        }

    return structured

def send_to_wordpress(structured_content):
    """Create a draft post in WordPress via REST API."""
    wp_url = os.environ.get('WORDPRESS_URL')  # e.g. https://yourdomain.com
    wp_user = os.environ.get('WORDPRESS_USERNAME')
    wp_pass = os.environ.get('WORDPRESS_APP_PASSWORD')

    if not (wp_url and wp_user and wp_pass):
        raise Exception("WordPress environment variables not set properly.")

    post_data = {
        'title': structured_content['title'],
        'status': 'draft',
        'content': '',  # main content empty; rely on custom fields
        'meta': {
            'newsletter_text_blocks': json.dumps(structured_content['text_blocks']),
            'newsletter_images': json.dumps(structured_content['images']),
            'newsletter_cta': json.dumps(structured_content['call_to_action'])
        }
    }

    # Basic Auth
    auth = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json"
    }

    response = requests.post(f"{wp_url}/wp-json/wp/v2/posts", headers=headers, json=post_data)
    response.raise_for_status()
    return response.json()

@app.route('/webhook/mailchimp', methods=['GET','POST','HEAD'])
def mailchimp_webhook():
    """
    Handles Mailchimp webhook validation (GET/HEAD)
    and incoming campaign notifications (POST).
    Mailchimp typically sends form-encoded data by default.
    """
    # Respond to GET/HEAD so Mailchimp can verify the endpoint:
    if request.method in ['GET', 'HEAD']:
        return "OK", 200

    try:
        campaign_id = None
        
        # Mailchimp usually sends data in form-encoded format:
        if request.form:
            # E.g. request.form might have keys like "type", "data[id]", "fired_at", etc.
            campaign_id = request.form.get('data[id]')
        else:
            # If JSON is ever used, fallback to parsing JSON:
            data = request.get_json(silent=True) or {}
            campaign_id = data.get('data', {}).get('id')

        if not campaign_id:
            return jsonify({"error": "No campaign ID found in payload"}), 400

        # 1. Fetch the campaign content from Mailchimp
        campaign_data = get_mailchimp_campaign(campaign_id)
        # 2. Parse it
        structured_content = parse_email_content(campaign_data)
        # 3. Send to WordPress
        wp_response = send_to_wordpress(structured_content)

        return jsonify({
            "status": "success",
            "wordpress_response": wp_response
        }), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
