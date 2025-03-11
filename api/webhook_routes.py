from threading import Thread
from flask import Blueprint, request, jsonify, Response
from services.mailchimp_service import MailchimpService  
from services.wordpress_service import WordPressService  
from processors.content_processor import ContentProcessor  

# Create Blueprint
webhook_bp = Blueprint('webhook', __name__, url_prefix='/webhook')

# Initialize services
mailchimp_service = MailchimpService()
wordpress_service = WordPressService()
content_processor = ContentProcessor()

@webhook_bp.route('/mailchimp', methods=['GET', 'POST', 'HEAD'])
def mailchimp_webhook():
    """
    Handle Mailchimp webhook requests.
    - GET/HEAD: Used by Mailchimp to validate the webhook
    - POST: Process the campaign and send to WordPress
    """
    print(">>> MAILCHIMP WEBHOOK CALLED!")
    print("Method is:", request.method)
    
    # Handle GET/HEAD requests from Mailchimp validator
    if request.method in ['GET', 'HEAD']:
        return Response("OK", status=200, mimetype="text/plain")
    
    # Debug incoming request
    print("Content-Type:", request.headers.get('Content-Type'))
    print("Form data:", request.form)
    print("JSON data:", request.get_json(silent=True))

    try:
        # Extract campaign ID from request
        campaign_id = _extract_campaign_id(request)
        if not campaign_id:
            return jsonify({"error": "No campaign ID found"}), 400

        thread = Thread(target=_process_campaign_async, args=(campaign_id,))
        thread.daemon = True
        thread.start()
        
        print(f"Campaign {campaign_id} queued for processing")
        return jsonify({"status": "queued", "campaign_id": campaign_id}), 200
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

def _extract_campaign_id(request):
    """Extract campaign ID from either form data or JSON."""
    if request.form:
        return request.form.get('data[id]')
    else:
        data = request.get_json(silent=True) or {}
        return data.get('data', {}).get('id')

def _process_campaign_async(campaign_id):
    """Process a Mailchimp campaign asynchronously."""
    try:
        print(f"Starting async processing of campaign {campaign_id}")
        
        # 1. Fetch campaign data from Mailchimp
        campaign_data = mailchimp_service.get_complete_campaign(campaign_id)
        print(f"Campaign data fetched for {campaign_id}")
        
        # 2. Parse and structure the content
        structured_content = content_processor.parse_email_content(campaign_data)
        print(f"Content processed for {campaign_id}. Found:")
        print(f"- Text blocks: {len(structured_content.get('text_blocks', []))}")
        print(f"- Images: {len(structured_content.get('images', []))}")
        print(f"- CTA: {'Yes' if structured_content.get('call_to_action') else 'No'}")
        print(f"- Links: {len(structured_content.get('embedded_links', []))}")
        
        # 3. Process and upload images to WordPress
        uploaded_images = wordpress_service.process_and_upload_images(structured_content["images"])
        print(f"Uploaded {len(uploaded_images)} images for campaign {campaign_id}")
        
        # 4. Create WordPress post with structured content
        wp_response = wordpress_service.create_post(
            structured_content["title"],
            structured_content["text_blocks"],
            uploaded_images,
            structured_content["call_to_action"],
            structured_content.get("embedded_links", [])
        )
        
        print(f"Successfully processed campaign {campaign_id}")
        print(f"WordPress post created: {wp_response.get('link', wp_response.get('id'))}")
    except Exception as e:
        import traceback
        print(f"Error processing campaign {campaign_id}: {e}")
        print(traceback.format_exc())