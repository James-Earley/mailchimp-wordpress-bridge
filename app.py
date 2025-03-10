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
    """
    Extract structured content from the campaign HTML.
    Broad approach: gather text from all <p> and <li>, gather images, optionally CTA.
    """
    html = campaign_data.get('html', '')
    soup = BeautifulSoup(html, 'html.parser')

    structured = {
        'title': campaign_data.get('subject_line', ''),
        'text_blocks': [],
        'images': [],
        'call_to_action': None
    }

    # Grab paragraphs + list items
    for elem in soup.find_all(['p', 'li']):
        text = elem.get_text(strip=True)
        if text:
            structured['text_blocks'].append({
                'type': 'paragraph',
                'content': text
            })

    # Grab images
    for img in soup.select('img'):
        src = img.get('src')
        alt = img.get('alt', '')
        if src and not any(keyword in src.lower() for keyword in ['logo', 'icon', 'footer']):
            structured['images'].append({
                'url': src,
                'alt': alt
            })

    # Optional: parse CTA if there's a specific button class
    cta = soup.select_one('a.mcnButton')
    if cta:
        structured['call_to_action'] = {
            'text': cta.get_text(strip=True),
            'url': cta.get('href', '')
        }

    return structured


def build_gutenberg_blocks(structured_content):
    """
    Turn text blocks, images, and CTA into valid Gutenberg block HTML
    so you can drag them around in the WP editor.
    """
    blocks_html = []

    # 1) Paragraph blocks
    for block in structured_content["text_blocks"]:
        text_escaped = block["content"].replace('"', '\\"')  # escape quotes for JSON
        # Gutenberg paragraph block markup:
        # <!-- wp:paragraph -->
        # <p>Paragraph text</p>
        # <!-- /wp:paragraph -->
        paragraph_block = (
            f'<!-- wp:paragraph -->'
            f'<p>{text_escaped}</p>'
            f'<!-- /wp:paragraph -->'
        )
        blocks_html.append(paragraph_block)

    # 2) Image blocks
    for img in structured_content["images"]:
        url_escaped = img["url"].replace('"', '\\"')
        alt_escaped = img["alt"].replace('"', '\\"')
        # Gutenberg image block markup:
        # <!-- wp:image {"alt":"ALT","url":"URL"} -->
        # <figure class="wp-block-image size-full"><img src="URL" alt="ALT"/></figure>
        # <!-- /wp:image -->
        image_block = (
            f'<!-- wp:image {{"alt":"{alt_escaped}","url":"{url_escaped}"}} -->'
            f'<figure class="wp-block-image size-full">'
            f'<img src="{url_escaped}" alt="{alt_escaped}"/>'
            f'</figure>'
            f'<!-- /wp:image -->'
        )
        blocks_html.append(image_block)

    # 3) CTA as a button block (if present)
    cta = structured_content.get("call_to_action")
    if cta and cta["url"]:
        text_escaped = cta["text"].replace('"', '\\"')
        url_escaped = cta["url"].replace('"', '\\"')
        # Gutenberg button block markup:
        # <!-- wp:button -->
        # <div class="wp-block-button"><a class="wp-block-button__link" href="URL">CTA Text</a></div>
        # <!-- /wp:button -->
        button_block = (
            f'<!-- wp:button -->'
            f'<div class="wp-block-button">'
            f'<a class="wp-block-button__link" href="{url_escaped}">{text_escaped}</a>'
            f'</div>'
            f'<!-- /wp:button -->'
        )
        blocks_html.append(button_block)

    # Finally, join everything into one big string
    return "\n".join(blocks_html)


def send_to_wordpress(structured_content):
    """
    Create a draft post in WordPress via REST API,
    but store everything as real Gutenberg blocks in post_content.
    """
    wp_url = os.environ.get('WORDPRESS_URL')
    wp_user = os.environ.get('WORDPRESS_USERNAME')
    wp_pass = os.environ.get('WORDPRESS_APP_PASSWORD')

    if not (wp_url and wp_user and wp_pass):
        raise Exception("WordPress environment variables not set properly.")

    # Build Gutenberg block markup from text_blocks, images, CTA
    block_markup = build_gutenberg_blocks(structured_content)

    # Put it directly into the 'content' field so it appears in WP
    post_data = {
        'title': structured_content['title'],
        'status': 'draft',
        'content': block_markup
        # We can skip the meta fields, or still store them if you want.
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
    if request.method in ['GET', 'HEAD']:
        return "OK", 200

    try:
        campaign_id = None
        if request.form:
            campaign_id = request.form.get('data[id]')
        else:
            data = request.get_json(silent=True) or {}
            campaign_id = data.get('data', {}).get('id')

        if not campaign_id:
            return jsonify({"error": "No campaign ID found in payload"}), 400

        # 1. Fetch the campaign content from Mailchimp
        campaign_data = get_mailchimp_campaign(campaign_id)
        # 2. Parse it into structured text_blocks/images/cta
        structured_content = parse_email_content(campaign_data)
        # 3. Send to WordPress as Gutenberg blocks
        wp_response = send_to_wordpress(structured_content)

        return jsonify({"status": "success", "wordpress_response": wp_response}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
