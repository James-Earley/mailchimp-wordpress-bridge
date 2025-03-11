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
        5. Filter unwanted images
        6. Exclude top & bottom image if there's more than 2 total
        7. Capture CTA if there's an .mcnButton
        """
        html = campaign_data.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        structured = {
            "title": campaign_data.get("subject_line", ""),
            "text_blocks": [],
            "images": [],
            "call_to_action": None
        }

        # Extract text blocks (headings, paragraphs, lists)
        structured["text_blocks"] = self._extract_text_blocks(soup)
        
        # Extract and filter images
        structured["images"] = self._extract_images(soup)
        
        # Extract call to action
        structured["call_to_action"] = self._extract_cta(soup)

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
    
    def _extract_images(self, soup):
        """Extract and filter images from the HTML."""
        # Filter images by skipping any with certain keywords
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
            filtered_images.append({
                "url": img.get("src"),
                "alt": img.get("alt","")
            })

        # Exclude the top & bottom image if there's more than 2 total
        if len(filtered_images) > 2:
            filtered_images = filtered_images[1:-1]

        return filtered_images
    
    def _extract_cta(self, soup):
        """Extract call to action button from the HTML."""
        cta = soup.select_one("a.mcnButton")
        if cta:
            return {
                "text": cta.get_text(strip=True),
                "url": cta.get("href","")
            }
        return None