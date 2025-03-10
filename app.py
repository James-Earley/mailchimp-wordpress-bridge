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

    # 1) Get HTML content
    content_res = requests.get(content_url, headers=headers)
    content_res.raise_for_status()
    content_json = content_res.json()

    # 2) Get subject line
    details_res = requests.get(details_url, headers=headers)
    details_res.raise_for_status()
    subject_line = details_res.json().get('settings', {}).get('subject_line', '')

    content_json['subject_line'] = subject_line
    return content_json


def parse_email_content(campaign_data):
    """
    Extract text blocks, images, and CTA from Mailchimp HTML,
    skipping logos, signatures, social icons, etc.
    """
    html = campaign_data.get('html', '')
    soup = BeautifulSoup(html, 'html.parser')

    structured = {
        'title': campaign_data.get('subject_line', ''),
        'text_blocks': [],
        'images': [],
        'call_to_action': None
    }

    # 1) Text
    for elem in soup.find_all(['p', 'li']):
        text = elem.get_text(strip=True)
        if text:
            structured['text_blocks'].append({
                'type': 'paragraph',
                'content': text
            })

    # 2) Images (filter out known unwanted items)
    all_imgs = soup.select('img')
    filtered_images = []
    for img in all_imgs:
        src = img.get('src') or ''
        alt = img.get('alt', '')
        src_lower = src.lower()
        alt_lower = alt.lower()

        # If either alt/src mention these, skip
        unwanted = ['logo', 'signature', 'facebook', 'twitter', 'instagram', 'footer', 'social']
        if any(uw in src_lower for uw in unwanted) or any(uw in alt_lower for uw in unwanted):
            continue

        if src:
            filtered_images.append({
                'url': src,
                'alt': alt
            })

    structured['images'] = filtered_images

    # 3) CTA
    cta = soup.select_one('a.mcnButton')
    if cta:
        structured['call_to_action'] = {
            'text': cta.get_text(strip=True),
            'url': cta.get('href', '')
        }

    return structured


def download_image(image_url):
    """Download the remote image bytes."""
    resp = requests.get(image_url)
    resp.raise_for_status()
    return resp.content


def upload_to_wp_media(image_binary, filename, alt_text, wp_url, headers):
    """
    Upload image data to WP Media Library. Return JSON (including 'id', 'source_url').
    """
    media_url = f"{wp_url}/wp-json/wp/v2/media"

    # Guess content type from extension
    content_type = "image/jpeg"
    if filename.lower().endswith(".png"):
        content_type = "image/png"

    files = {
        'file': (filename, image_binary, content_type)
    }
    data = {
        'title': filename,
        'alt_text': alt_text
    }

    upload_resp = requests.post(media_url, headers=headers, files=files, data=data)
    upload_resp.raise_for_status()
    return upload_resp.json()


def send_to_wordpress(structured_content):
    """
    Create a WP draft post with:
      - no content
      - custom meta fields (newsletter_text_blocks, newsletter_images, newsletter_cta)
      - images are uploaded to the media library first
    """
    wp_url = os.environ.get('WORDPRESS_URL')
    wp_user = os.environ.get('WORDPRESS_USERNAME')
    wp_pass = os.environ.get('WORDPRESS_APP_PASSWORD')

    if not (wp_url and wp_user and wp_pass):
        raise Exception("WordPress environment variables not set properly.")

    # Auth
    auth_str = f"{wp_user}:{wp_pass}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}"
    }

    # 1) Upload each image to WP
    uploaded_images_info = []
    for img in structured_content["images"]:
        remote_url = img["url"]
        alt_text = img["alt"]
        try:
            img_data = download_image(remote_url)
        except Exception as e:
            print(f"Error downloading {remote_url}: {e}")
            continue

        filename = remote_url.split("/")[-1] or "mailchimp-image.jpg"
        try:
            media_item = upload_to_wp_media(img_data, filename, alt_text, wp_url, headers)
        except Exception as e:
            print(f"Error uploading to WP media: {e}")
            continue

        # Store the final WP ID & URL, plus alt text
        uploaded_images_info.append({
            "media_id": media_item.get("id"),
            "url": media_item.get("source_url"),
            "alt": alt_text
        })

    # 2) Build meta data
    post_data = {
        "title": structured_content["title"],
        "status": "draft",
        "content": "",  # empty main content
        "meta": {
            "newsletter_text_blocks": json.dumps(structured_content["text_blocks"]),
            "newsletter_images": json.dumps(uploaded_images_info),
            "newsletter_cta": json.dumps(structured_content["call_to_action"])
        }
    }

    # 3) Create the draft post
    post_resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts",
        headers={**headers, "Content-Type": "application/json"},
        json=post_data
    )
    post_resp.raise_for_status()
    return post_resp.json()


@app.route('/webhook/mailchimp', methods=['GET','POST','HEAD'])
def mailchimp_webhook():
    """Mailchimp POSTs here when a campaign is sent."""
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
            return jsonify({"error": "No campaign ID found"}), 400

        # 1) Fetch campaign data from Mailchimp
        campaign_data = get_mailchimp_campaign(campaign_id)

        # 2) Parse out text, images, cta
        structured_content = parse_email_content(campaign_data)

        # 3) Create WP draft: images -> media library, text -> custom fields, content = ""
        wp_response = send_to_wordpress(structured_content)

        return jsonify({"status": "success", "wordpress_response": wp_response}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
