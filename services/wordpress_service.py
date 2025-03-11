import base64
import json
import requests
import config  
from utils.image_utils import ImageUtils  

class WordPressService:
    def __init__(self):
        """Initialize the WordPress service with configuration."""
        self.wp_url = config.WORDPRESS_URL
        self.wp_user = config.WORDPRESS_USERNAME
        self.wp_pass = config.WORDPRESS_APP_PASSWORD
        
        # Validate config
        config.validate_config()
        
        # Prepare authentication headers
        auth_str = f"{self.wp_user}:{self.wp_pass}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()
        self.auth_headers = {
            "Authorization": f"Basic {auth_b64}"
        }
    
    def upload_to_media_library(self, image_binary, filename, alt_text):
        """
        Upload image to WordPress Media Library.
        
        Args:
            image_binary (bytes): The binary content of the image
            filename (str): Filename to use for the uploaded image
            alt_text (str): Alt text for the image
            
        Returns:
            dict: WordPress media object with 'id' and 'source_url'
            
        Raises:
            requests.exceptions.RequestException: If the upload fails
        """
        media_url = f"{self.wp_url}/wp-json/wp/v2/media"
        
        # Determine content type from filename
        content_type = ImageUtils.get_content_type(filename)
        
        files = {
            'file': (filename, image_binary, content_type)
        }
        data = {
            'title': filename,
            'alt_text': alt_text
        }

        resp = requests.post(media_url, headers=self.auth_headers, files=files, data=data)
        resp.raise_for_status()
        return resp.json()
    
    def create_post(self, title, text_blocks, images, call_to_action, embedded_links=None):
        """
        Create a WordPress post with custom meta fields.
        
        Args:
            title (str): Title for the post
            text_blocks (list): List of structured text blocks
            images (list): List of image data
            call_to_action (dict): CTA data
            embedded_links (list, optional): List of embedded links found in the email
            
        Returns:
            dict: WordPress post object
            
        Raises:
            requests.exceptions.RequestException: If the post creation fails
        """
        post_data = {
            "title": title,
            "status": "draft",
            "content": "",  # empty
            "meta": {
                "newsletter_text_blocks": json.dumps(text_blocks),
                "newsletter_images": json.dumps(images),
                "newsletter_cta": json.dumps(call_to_action)
            }
        }
        
        # Add embedded links if provided
        if embedded_links:
            post_data["meta"]["newsletter_embedded_links"] = json.dumps(embedded_links)

        # Create draft post
        resp = requests.post(
            f"{self.wp_url}/wp-json/wp/v2/posts",
            headers={**self.auth_headers, "Content-Type": "application/json"},
            json=post_data
        )
        resp.raise_for_status()
        return resp.json()
    
    def process_and_upload_images(self, image_data_list):
        """
        Process a list of image data, download each image and upload to WordPress.
        
        Args:
            image_data_list (list): List of image data with 'url' and 'alt' fields
            
        Returns:
            list: List of uploaded image data with 'media_id', 'url', and 'alt' fields
        """
        uploaded_images = []
        
        for img in image_data_list:
            remote_url = img["url"]
            alt_text = img["alt"]
            
            try:
                # Download the image
                img_data = ImageUtils.download_image(remote_url)
                
                # Extract filename from URL
                filename = ImageUtils.extract_filename(remote_url)
                
                # Upload to WordPress
                media_item = self.upload_to_media_library(img_data, filename, alt_text)
                
                # Add to our list of uploaded images
                uploaded_images.append({
                    "media_id": media_item.get("id"),
                    "url": media_item.get("source_url"),
                    "alt": alt_text
                })
            except Exception as e:
                print(f"Error processing image {remote_url}: {e}")
                continue
        
        return uploaded_images