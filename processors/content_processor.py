from bs4 import BeautifulSoup

class ContentProcessor:
    def parse_email_content(self, campaign_data):
        """
        Parse Mailchimp email HTML content and structure it for WordPress.
        
        Processing steps:
        1. Extract headings, paragraphs, and lists in DOM order
        2. For each list, create a single "list" block with all <li>
        3. Merge consecutive paragraphs into one block
        4. Label headings with "level"=1..6
        5. Extract content images using smart filtering logic
        6. Capture CTAs with improved detection logic
        7. Extract useful embedded links (excluding generic/tracking links)
        """
        html = campaign_data.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        structured = {
            "title": campaign_data.get("subject_line", ""),
            "text_blocks": [],
            "images": [],
            "call_to_action": None,
            "embedded_links": []  # New feature for embedded links
        }

        # Extract text blocks (headings, paragraphs, lists)
        structured["text_blocks"] = self._extract_text_blocks(soup)
        
        # Extract and filter images with smart logic
        structured["images"] = self._extract_content_images(soup)
        
        # Extract call to action with improved detection
        structured["call_to_action"] = self._extract_cta(soup)
        
        # Extract embedded user links (new feature)
        structured["embedded_links"] = self._extract_embedded_links(soup)

        return structured
    
    def _extract_text_blocks(self, soup):
        """Extract and process text blocks from the HTML."""
        # 1) Gather headings, paragraphs, and lists in DOM order
        node_list = soup.find_all(["h1","h2","h3","h4","h5","h6","p","ul","ol"])
        raw_blocks = []

        for node in node_list:
            tag = node.name.lower()
            if tag in ["h1","h2","h3","h4","h5","h6"]:
                text = node.get_text(strip=True)
                if text:
                    level = int(tag[-1])  # e.g. h2 -> level=2
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
                # Build a single "list" block containing all <li>
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

        return merged
    
    def _extract_content_images(self, soup):
        """
        Extract content images with smart filtering.
        
        This method uses multiple signals to identify content vs. non-content images:
        1. Position in document (structural analysis)
        2. Image size and dimensions
        3. CSS classes and containers
        4. Keywords in URLs and alt text
        5. Context analysis (e.g., images inside content blocks)
        """
        # First pass: Find all images and collect metadata about each
        all_images = soup.select('img')
        image_data = []
        
        # Get email body container for position analysis
        body_container = soup.select_one('table#bodyTable') or soup
        
        for i, img in enumerate(all_images):
            src = img.get('src', '')
            if not src:
                continue
                
            # Get parent containers that might indicate context
            parent_classes = []
            parent = img.parent
            max_depth = 5  # Don't go too far up
            depth = 0
            
            while parent and depth < max_depth:
                if parent.get('class'):
                    parent_classes.extend(parent.get('class'))
                parent = parent.parent
                depth += 1
            
            # Analyze the image
            img_data = {
                'url': src,
                'alt': img.get('alt', ''),
                'width': self._parse_dimension(img.get('width', '')),
                'height': self._parse_dimension(img.get('height', '')),
                'position': i,  # Position in document order
                'position_ratio': i / len(all_images) if len(all_images) > 0 else 0,  # Relative position (0-1)
                'classes': img.get('class', []) if img.get('class') else [],
                'parent_classes': parent_classes,
                # Calculate approximate vertical position in the document
                'y_position': self._estimate_vertical_position(img, body_container),
                'is_small': False  # Will set below
            }
            
            # Check if this is a small image (likely UI element)
            if img_data['width'] and img_data['height']:
                img_data['is_small'] = img_data['width'] < 50 or img_data['height'] < 50
            
            # Check for content image indicators
            img_data['is_likely_content'] = self._is_likely_content_image(img_data)
            
            # Check for UI element indicators
            img_data['is_likely_ui'] = self._is_likely_ui_element(img_data)
            
            image_data.append(img_data)
        
        # Second pass: Use structural analysis to identify content images
        total_images = len(image_data)
        content_images = []
        
        # If we have 1-2 images only, include all of them that aren't clear UI elements
        if total_images <= 2:
            content_images = [img for img in image_data if not img['is_likely_ui']]
        
        # If we have more than 2 images:
        elif total_images > 2:
            # Sort by vertical position (top to bottom)
            sorted_by_position = sorted(image_data, key=lambda x: x['y_position'])
            
            # Skip the first image if it looks like a header/logo
            start_idx = 1 if self._is_likely_header(sorted_by_position[0]) else 0
            
            # Skip the last image if it looks like a footer element
            end_idx = -1 if self._is_likely_footer(sorted_by_position[-1]) else None
            
            # Select the middle portion of images
            middle_images = sorted_by_position[start_idx:end_idx]
            
            # From the middle, filter out clear UI elements
            content_images = [img for img in middle_images if not img['is_likely_ui']]
            
            # If we filtered everything out, try to keep at least one image
            if not content_images and middle_images:
                # Find the largest image as a fallback
                largest_img = max(middle_images, key=lambda x: (x['width'] or 0) * (x['height'] or 0))
                content_images = [largest_img]
        
        # Convert to the expected format
        return [{'url': img['url'], 'alt': img['alt']} for img in content_images]

    def _parse_dimension(self, value):
        """Parse dimension value (width/height) to integer if possible."""
        if not value:
            return None
        try:
            # Remove 'px' if present and convert to int
            return int(value.replace('px', ''))
        except (ValueError, TypeError):
            return None

    def _estimate_vertical_position(self, img, container):
        """Estimate vertical position of an image in the document."""
        # Get all elements in document order
        all_elements = container.find_all()
        if img in all_elements:
            return all_elements.index(img)
        return 0  # Default to top if not found

    def _is_likely_content_image(self, img_data):
        """Determine if an image is likely to be content based on multiple signals."""
        # Keywords that suggest content images
        content_keywords = ['content', 'article', 'story', 'banner', 'hero', 'featured']
        
        # Check for content-related classes
        has_content_class = any(cls in content_keywords for cls in img_data['classes'])
        has_content_parent = any(cls in content_keywords for cls in img_data['parent_classes'])
        
        # Check for typical content image classes in Mailchimp
        mailchimp_content_classes = ['mceImage', 'imageDropZone']
        has_mc_content_class = any(cls in mailchimp_content_classes for cls in img_data['classes'])
        
        # Size-based heuristic: content images tend to be larger
        is_large_enough = (img_data['width'] or 0) > 200 or (img_data['height'] or 0) > 200
        
        # Position-based heuristic: content images are usually in the middle section
        in_middle_section = 0.2 <= img_data['position_ratio'] <= 0.8
        
        # Combine signals
        return (has_content_class or has_content_parent or has_mc_content_class or 
                (is_large_enough and in_middle_section))

    def _is_likely_ui_element(self, img_data):
        """Determine if an image is likely to be a UI element rather than content."""
        # Keywords that suggest UI elements
        ui_keywords = ['logo', 'footer', 'header', 'icon', 'social', 'facebook', 
                      'twitter', 'instagram', 'linkedin', 'youtube', 'button',
                      'pixel', 'tracking', 'spacer', 'signature']
        
        # Check URL and alt text for UI keywords
        has_ui_keyword_url = any(kw in img_data['url'].lower() for kw in ui_keywords)
        has_ui_keyword_alt = any(kw in img_data['alt'].lower() for kw in ui_keywords)
        
        # Check for small dimensions (likely icons or UI elements)
        is_small = img_data['is_small']
        
        # Check for tracking pixels and similar
        tracking_indicators = ['pixel', 'tracking', 'spacer', 'transparent.gif', 
                              'mailchimp.com', 'list-manage.com']
        is_tracking = any(ind in img_data['url'].lower() for ind in tracking_indicators)
        
        # Combine signals
        return has_ui_keyword_url or has_ui_keyword_alt or is_small or is_tracking

    def _is_likely_header(self, img_data):
        """Determine if an image is likely to be a header/logo."""
        # Header images are typically at the top
        at_top = img_data['position_ratio'] < 0.2
        
        # Logo keywords
        logo_keywords = ['logo', 'header', 'brand']
        has_logo_keyword = (
            any(kw in img_data['url'].lower() for kw in logo_keywords) or
            any(kw in img_data['alt'].lower() for kw in logo_keywords)
        )
        
        # Header images often have specific classes
        header_classes = ['logo', 'header', 'brand', 'mceLogo']
        has_header_class = any(cls in header_classes for cls in img_data['classes'])
        
        # Header containers
        header_containers = ['mceHeader', 'mceSectionHeader']
        in_header_container = any(cls in header_containers for cls in img_data['parent_classes'])
        
        # Header images are often smaller than content images
        right_size_for_logo = ((img_data['width'] or 0) < 200) if img_data['width'] else False
        
        # Combine signals
        return (at_top and (has_logo_keyword or has_header_class or 
                           in_header_container or right_size_for_logo))

    def _is_likely_footer(self, img_data):
        """Determine if an image is likely to be a footer element."""
        # Footer images are typically at the bottom
        at_bottom = img_data['position_ratio'] > 0.8
        
        # Footer keywords
        footer_keywords = ['footer', 'social', 'facebook', 'twitter', 'instagram',
                          'linkedin', 'youtube', 'contact', 'signature']
        has_footer_keyword = (
            any(kw in img_data['url'].lower() for kw in footer_keywords) or
            any(kw in img_data['alt'].lower() for kw in footer_keywords)
        )
        
        # Footer containers
        footer_containers = ['mceFooter', 'mceSectionFooter', 'socialFollow']
        in_footer_container = any(cls in footer_containers for cls in img_data['parent_classes'])
        
        # Footer images are often small (social icons, etc.)
        is_small = img_data['is_small']
        
        # Combine signals
        return (at_bottom and (has_footer_keyword or in_footer_container or is_small))
    
    def _extract_cta(self, soup):
        """
        Extract call to action buttons from the HTML with improved detection.
        Returns the primary CTA or the first CTA found.
        """
        # Look for possible CTA elements with various button classes and attributes
        button_classes = [
            "mcnButton",                # Standard Mailchimp button
            "button",                   # Generic button class
            "btn",                      # Bootstrap-style button
            "cta",                      # Explicit CTA class
            "action",                   # Action button
            "primary-button",           # Primary button variant
            "mc-button"                 # Another Mailchimp variant
        ]
        
        # Try class-based button selectors (combine with CSS OR selector)
        class_selector = ", ".join(f"a.{cls}" for cls in button_classes)
        class_buttons = soup.select(class_selector)
        
        # Try attribute and style-based button detection
        attribute_buttons = []
        
        # Look for elements with button-like styling
        for a_tag in soup.find_all('a'):
            # Skip if we already found it via class
            if a_tag in class_buttons:
                continue
                
            # Check for button-like styling in style attribute
            style = a_tag.get('style', '').lower()
            if any(s in style for s in ['padding', 'border-radius', 'background']):
                if any(s in style for s in ['block', 'inline-block', 'center']):
                    attribute_buttons.append(a_tag)
                    continue
            
            # Check for button-like parent elements
            parent = a_tag.parent
            if parent and parent.name == 'td':
                parent_style = parent.get('style', '').lower()
                if any(s in parent_style for s in ['padding', 'border-radius', 'background', 'center']):
                    attribute_buttons.append(a_tag)
                    continue
            
            # Check for role attribute
            if a_tag.get('role') == 'button':
                attribute_buttons.append(a_tag)
                continue
        
        # Combine all found buttons
        all_buttons = class_buttons + attribute_buttons
        
        if not all_buttons:
            return None
            
        # Process all buttons to prioritize them
        button_data = []
        for btn in all_buttons:
            text = btn.get_text(strip=True)
            url = btn.get("href", "")
            
            # Skip obvious non-CTA links (social, unsubscribe, etc.)
            if self._is_utility_link(text, url):
                continue
                
            # Calculate priority score
            score = self._calculate_cta_priority(btn, text)
            
            button_data.append({
                "text": text,
                "url": url,
                "priority_score": score
            })
        
        # Sort by priority and take the highest
        if button_data:
            sorted_buttons = sorted(button_data, key=lambda x: x["priority_score"], reverse=True)
            result = sorted_buttons[0]
            # Remove the score from final result
            del result["priority_score"]
            return result
            
        return None

    def _calculate_cta_priority(self, button, text):
        """Calculate a priority score for a potential CTA button."""
        score = 0
        
        # Prioritize buttons with explicit CTA classes
        cls = ' '.join(button.get('class', []))
        if any(c in cls.lower() for c in ['cta', 'action', 'primary', 'main']):
            score += 10
        
        # Prioritize based on common CTA text patterns
        cta_phrases = ['learn more', 'read more', 'sign up', 'register', 'buy now', 
                       'get started', 'join', 'subscribe', 'download', 'shop', 
                       'view', 'click here', 'discover']
        
        lower_text = text.lower()
        if any(phrase in lower_text for phrase in cta_phrases):
            score += 5
            
        # Prioritize standalone buttons with short text (typical for CTAs)
        if len(text) < 30:
            score += 3
            
        # Check for visual prominence indicators
        style = button.get('style', '').lower()
        if 'bold' in style or 'weight' in style:
            score += 2
        if any(color in style for color in ['background', 'bg', 'color']):
            score += 2
            
        # Check parent for centering (centered buttons are often CTAs)
        parent = button.parent
        if parent:
            parent_style = parent.get('style', '').lower()
            parent_class = ' '.join(parent.get('class', []))
            if any(align in parent_style or align in parent_class 
                   for align in ['center', 'align', 'margin:auto']):
                score += 2
                
        return score
    
    def _is_utility_link(self, text, url):
        """Check if a link is a utility link rather than a content link."""
        utility_patterns = [
            # Social media
            'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
            'youtube.com', 'pinterest.com', 'tiktok.com',
            
            # Mailchimp and email utility links
            'mailchimp.com', 'list-manage.com', 'forward to a friend', 
            'unsubscribe', 'preferences', 'view in browser',
            
            # Common site utility links
            'privacy policy', 'terms', 'contact us', 'help', 'faq'
        ]
        
        lower_text = text.lower()
        lower_url = url.lower()
        
        return any(pattern in lower_text or pattern in lower_url 
                  for pattern in utility_patterns)
    
    def _extract_embedded_links(self, soup):
        """
        Extract embedded user links from the email content.
        Excludes utility links, tracking links, and other non-content links.
        """
        # Find all links in content areas (typical for text content)
        content_containers = [
            'mcnTextContent',           # Mailchimp text content block
            'mcnTextContentContainer',  # Mailchimp text container
            'contentContainer',         # Generic content container
            'bodyContainer',            # Email body container
            'contentBlock',             # Generic content block
        ]
        
        # Combined selector for content areas
        content_selector = ", ".join(f".{cls}" for cls in content_containers)
        content_areas = soup.select(content_selector)
        
        # If we found content areas, look for links in them
        links_in_content = []
        if content_areas:
            for area in content_areas:
                links_in_content.extend(area.find_all('a'))
        else:
            # If we couldn't find content areas, take all links
            # We'll filter them later
            links_in_content = soup.find_all('a')
        
        # Process and filter the links
        user_links = []
        for link in links_in_content:
            text = link.get_text(strip=True)
            url = link.get('href', '')
            
            # Skip empty links
            if not text or not url:
                continue
                
            # Skip utility and known non-content links
            if self._is_utility_link(text, url):
                continue
                
            # Skip tracking links and internal anchors
            if self._is_tracking_or_anchor_link(url):
                continue
                
            # Skip if it's likely a button (already handled in CTA)
            if self._is_likely_button(link):
                continue
                
            # Add the valid user link
            user_links.append({
                "text": text,
                "url": url
            })
        
        # Remove duplicates (same URL)
        unique_links = []
        seen_urls = set()
        
        for link in user_links:
            url = link["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique_links.append(link)
        
        return unique_links
    
    def _is_tracking_or_anchor_link(self, url):
        """Check if a URL is a tracking link or internal anchor."""
        # Check for tracking pixels or empty URLs
        if not url or url == '#' or url.startswith('javascript:'):
            return True
            
        # Check for internal anchors
        if url.startswith('#'):
            return True
            
        # Check for common tracking domains
        tracking_domains = [
            'doubleclick.net', 'google-analytics.com', 'mailchimp.com/track',
            'list-manage.com/track', 'analytics', 'pixel', 'beacon'
        ]
        
        lower_url = url.lower()
        return any(domain in lower_url for domain in tracking_domains)
    
    def _is_likely_button(self, link):
        """Check if a link is likely to be a button rather than a text link."""
        # Check classes for button indicators
        cls = ' '.join(link.get('class', []))
        if any(btn in cls.lower() for btn in ['button', 'btn', 'cta']):
            return True
            
        # Check style for button-like properties
        style = link.get('style', '').lower()
        if any(prop in style for prop in ['padding:', 'background-color:', 'border-radius:']):
            return True
            
        # Check for role attribute
        if link.get('role') == 'button':
            return True
            
        # Check parent elements for button containers
        parent = link.parent
        if parent:
            parent_cls = ' '.join(parent.get('class', []))
            if any(btn in parent_cls.lower() for btn in ['button', 'btn', 'cta']):
                return True
        
        return False