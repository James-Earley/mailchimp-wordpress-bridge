import requests

class ImageUtils:
    @staticmethod
    def download_image(image_url):
        """
        Download remote image bytes.
        
        Args:
            image_url (str): URL of the image to download
            
        Returns:
            bytes: The binary content of the image
            
        Raises:
            requests.exceptions.RequestException: If the download fails
        """
        resp = requests.get(image_url)
        resp.raise_for_status()
        return resp.content
    
    @staticmethod
    def get_content_type(filename):
        """
        Guess the content type from the filename extension.
        
        Args:
            filename (str): Filename with extension
            
        Returns:
            str: The MIME type for the image
        """
        if filename.lower().endswith(".png"):
            return "image/png"
        elif filename.lower().endswith(".gif"):
            return "image/gif"
        elif filename.lower().endswith(".webp"):
            return "image/webp"
        else:
            # Default to JPEG
            return "image/jpeg"
    
    @staticmethod
    def extract_filename(url):
        """
        Extract a filename from an image URL.
        
        Args:
            url (str): The URL of the image
            
        Returns:
            str: A filename, with fallback to default if none found
        """
        try:
            return url.split("/")[-1] or "mailchimp-image.jpg"
        except:
            return "mailchimp-image.jpg"