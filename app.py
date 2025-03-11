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
    1. Gather headings (h1..h6), paragraphs (p), lists (ul/ol) in DOM order.
    2. For each list, create a single "list" block with all <li>.
    3. Merge consecutive paragraphs into one block.
    4. Label headings with "level"=1..6.
    5. Skip unwanted images; gather the rest.
    6. Capture CTA if there's an .mcnButton.
    """
    html = campaign_data.get("html", "")
    soup = BeautifulSoup(html, "html.parser")

    # We'll store final text blocks in `structured["text_blocks"]`.
    structured = {
        "title": campaign_data.get("subject_line", ""),
        "text_blocks": [],    # headings, paragraphs, lists
        "images": [],
        "call_to_action": None
    }

    # 1) Gather headings, paragraphs, lists in DOM order
    node_list = soup.find_all(["h1","h2","h3","h4","h5","h6","p","ul","ol"])
    raw_blocks = []

    for node in node_list:
        tag = node.name.lower()
        if tag in ["h1","h2","h3","h4","h5","h6"]:
            text = node.get_text(strip=True)
            if text:
                level = int(tag[-1])  # e.g. h2 -> level = 2
                raw_blocks.append({
                    "type": "header",
                    "level": level,
                    "content": text
                })
        elif tag == "p":
            text = node.get_text(strip=True)
            if text:
                raw_blocks.append({
                    "type": "paragraph",
                    "content": text
                })
        elif tag in ["ul","ol"]:
            # Build a single "list" block with <li> children
            items = []
            lis = node.find_all("li", recursive=False)
            for li in lis:
                li_text = li.get_text(strip=True)
                if li_text:
                    items.append(li_text)
            if items:
                style = "ordered" if tag == "ol" else "unordered"
                raw_blocks.append({
                    "type": "list",
                    "style": style,
                    "items": items
                })

    # 2) Merge consecutive paragraph blocks
    merged = []
    for block in raw_blocks:
        if block["type"] == "paragraph" and merged:
            last = merged[-1]
            if last["type"] == "paragraph":
                # Merge them with a blank line
                last["content"] += "\n\n" + block["content"]
                continue
        merged.append(block)

    # These text blocks go into structured["text_blocks"]
    structured["text_blocks"] = merged

    # 3) Filter images
    unwanted = ["logo","signature","facebook","twitter","instagram","social","footer"]
    all_imgs = soup.select("img")
    filtered_images = []
    for img in all_imgs:
        src = (img.get("src") or "").lower()
        alt = (img.get("alt") or "").lower()
        if not src:
            continue
        if any(uw in src for uw in unwanted) or any(uw in alt for uw in unwanted):
            continue
        # Keep it
        filtered_images.append({
            "url": img.get("src"),
            "alt": img.get("alt","")
        })
    structured["images"] = filtered_images

    # 4) CTA from .mcnButton
    cta = soup.select_one("a.mcnButton")
    if cta:
        structured["call_to_action"] = {
            "text": cta.get_text(strip=True),
            "url": cta.get("href","")
        }

    return structured


def download_image(image_url):
    """Download remote image bytes."""
    resp = requests.get(image_url)
    resp.raise_for_status()
    return resp.content


def upload_to_wp_media(image_binary, filename, alt_text, wp_url, headers):
    """Upload image to WP Media Library. Return JSON with 'id','source_url'."""
    media_url = f"{wp_url}/wp-json/wp/v2/media"

    # Guess content type
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

    resp = requests.post(media_url, headers=headers, files=files, data=data)
    resp.raise_for_status()
    return resp.json()


def send_to_wordpress(structured_content):
    """
    Create WP draft with:
      - no main content
      - meta fields: newsletter_text_blocks, newsletter_images, newsletter_cta
      - images are uploaded to media first.
    """
    wp_url = os.environ.get('WORDPRESS_URL')
    wp_user = os.environ.get('WORDPRESS_USERNAME')
    wp_pass = os.environ.get('WORDPRESS_APP_PASSWORD')

    if not (wp_url and wp_user and wp_pass):
        raise Exception("WordPress environment variables not set properly.")

    auth_str = f"{wp_user}:{wp_pass}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}"
    }

    # Upload images
    uploaded_images = []
    for img in structured_content["images"]:
        remote_url = img["url"]
        alt_text   = img["alt"]
        try:
            data = download_image(remote_url)
        except Exception as e:
            print(f"Error downloading {remote_url}: {e}")
            continue

        filename = remote_url.split("/")[-1] or "mailchimp-image.jpg"
        try:
            media_item = upload_to_wp_media(data, filename, alt_text, wp_url, headers)
        except Exception as e:
            print(f"Error uploading to WP media: {e}")
            continue

        uploaded_images.append({
            "media_id": media_item.get("id"),
            "url": media_item.get("source_url"),
            "alt": alt_text
        })

    # Build post data
    post_data = {
        "title": structured_content["title"],
        "status": "draft",
        "content": "",  # empty
        "meta": {
            # We'll store text_blocks, images, call_to_action
            "newsletter_text_blocks": json.dumps(structured_content["text_blocks"]),
            "newsletter_images": json.dumps(uploaded_images),
            "newsletter_cta": json.dumps(structured_content["call_to_action"])
        }
    }

    # Create draft post
    resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts",
        headers={**headers, "Content-Type": "application/json"},
        json=post_data
    )
    resp.raise_for_status()
    return resp.json()


@app.route('/webhook/mailchimp', methods=['GET','POST','HEAD'])
def mailchimp_webhook():
    """
    Mailchimp calls this with form-encoded data when a campaign is sent.
    We'll parse, upload images, store as WP draft with custom fields.
    """
    if request.method in ['GET', 'HEAD']:
        return "OK", 200

    try:
        if request.form:
            campaign_id = request.form.get('data[id]')
        else:
            data = request.get_json(silent=True) or {}
            campaign_id = data.get('data', {}).get('id')

        if not campaign_id:
            return jsonify({"error": "No campaign ID found"}), 400

        # Fetch & parse
        campaign_data = get_mailchimp_campaign(campaign_id)
        structured_content = parse_email_content(campaign_data)

        # Send to WP
        wp_response = send_to_wordpress(structured_content)
        return jsonify({"status": "success", "wordpress_response": wp_response}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
