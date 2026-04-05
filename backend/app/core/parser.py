import re
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from loguru import logger
from datetime import datetime


class EHParser:
    @staticmethod
    def parse_gallery_list(html: str) -> Tuple[List[Dict], Optional[str]]:
        """
        Parses favorites or search result page.
        Returns tuple of (list of gallery dicts, next_page_url or None).
        Based on reference implementation using correct selectors.
        """
        soup = BeautifulSoup(html, "lxml")
        galleries = []
        
        # Find the main gallery table (correct selector from reference)
        table = soup.select_one("table.itg.gltc")
        if not table:
            # Try alternative: compact table format
            table = soup.select_one("table.itg")
            
        if not table:
            logger.warning("No gallery table found in HTML")
            return [], None
            
        for tr in table.select("tr"):
            try:
                # Find gallery link (correct selector from reference)
                a = tr.select_one("td.gl3c.glname a[href^='https://']")
                if not a:
                    # Try alternative selector
                    a = tr.select_one("td.gl3c a[href*='/g/']")
                if not a:
                    a = tr.select_one("a[href*='/g/']")
                if not a:
                    continue
                    
                href = a.get("href", "")
                m = re.search(r"/g/(\d+)/(\w+)/", href)
                if not m:
                    continue
                    
                gid = int(m.group(1))
                token = m.group(2)
                
                # Debug: log anchor HTML
                logger.debug(f"Anchor HTML for gid={gid}: {str(a)[:200]}...")
                
                # Get title - simple approach from reference project
                glink = a.select_one("div.glink")
                if glink:
                    title = glink.get_text(strip=True)
                else:
                    # Check for thumbnail view: title is in img alt attribute
                    img = a.select_one("img[alt]")
                    if img and img.get("alt"):
                        title = img.get("alt", "").strip()
                    else:
                        # Fallback: get entire anchor text, then remove tag text
                        title = a.get_text(strip=True)
                        # Remove any tag content
                        for tag_div in a.select("div.gt, div.gtl"):
                            tag_text = tag_div.get_text(strip=True)
                            if tag_text and tag_text in title:
                                title = title.replace(tag_text, '').strip()
                
                if not title:
                    title = f"Gallery {gid}"
                    logger.warning(f"Could not extract title for gid={gid}")
                else:
                    logger.debug(f"Extracted title for {gid}: {title[:50]}...")
                
                # Get tags (separate from title)
                tags = [t.get_text(strip=True) for t in a.select("div.gt")]
                
                # Get favorited time
                fav = None
                tds = tr.find_all("td", recursive=False)
                if len(tds) >= 2:
                    fav_td = tds[-2]
                    block = fav_td.get_text(" ", strip=True)
                    m_fav = re.search(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b", block)
                    if m_fav:
                        fav = m_fav.group(0)
                
                # Fallback for favorited time
                if not fav:
                    published_td = tr.select_one("td.gl2c")
                    for td in tds:
                        if published_td is not None and td is published_td:
                            continue
                        block = td.get_text(" ", strip=True)
                        m_fav = re.search(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b", block)
                        if m_fav:
                            fav = m_fav.group(0)
                            break
                
                galleries.append({
                    "gid": gid,
                    "token": token,
                    "title": title,
                    "tags": tags,
                    "favorited": fav,
                    "posted_str": fav or ""
                })
            except Exception as e:
                logger.warning(f"Failed to parse row: {e}")
                continue
        
        # Find next page URL
        next_url = None
        nxt = soup.select_one("#unext")
        if nxt and nxt.get("href"):
            next_url = nxt.get("href")
        
        if not next_url:
            for sc in soup.select("script"):
                txt = sc.text or ""
                m = re.search(r'nexturl="([^"]+)"', txt)
                if m:
                    next_url = m.group(1)
                    break
        
        logger.debug(f"Parsed {len(galleries)} galleries from HTML, next_url: {next_url is not None}")
        return galleries, next_url

    @staticmethod
    def parse_gallery_detail(html: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        info = {}
        
        # Titles
        gn = soup.select_one("#gn")
        info["title"] = gn.get_text(strip=True) if gn else ""
        gj = soup.select_one("#gj")
        info["title_jpn"] = gj.get_text(strip=True) if gj else ""
        
        # Category & Uploader
        cat = soup.select_one("#gdc")
        info["category"] = cat.get_text(strip=True) if cat else "Unknown"
        upl = soup.select_one("#gdn")
        info["uploader"] = upl.get_text(strip=True) if upl else "Unknown"
        
        # Meta
        gdd = soup.select("#gdd tr")
        for row in gdd:
            cols = row.find_all("td")
            if len(cols) != 2: continue
            label = cols[0].get_text(strip=True).replace(":", "")
            value = cols[1].get_text(strip=True)
            if label == "Length":
                match = re.search(r"(\d+)", value)
                info["filecount"] = int(match.group(1)) if match else 0
            elif label == "Posted":
                try:
                    info["posted"] = datetime.strptime(value, "%Y-%m-%d %H:%M")
                except:
                    info["posted"] = None

        # Tags
        tags = []
        for tr in soup.select("#taglist tr"):
            ns_td = tr.select_one("td.tc, td.tc1")
            if not ns_td:
                continue

            ns = ns_td.get_text(strip=True).replace(":", "")
            value_td = ns_td.find_next_sibling("td")
            if value_td is None:
                cols = tr.find_all("td")
                value_td = cols[1] if len(cols) > 1 else None

            if value_td is None:
                continue

            for a in value_td.select("a"):
                tag_text = a.get_text(strip=True)
                if tag_text:
                    tags.append(f"{ns}:{tag_text}")
        info["tags"] = tags

        # Newer Versions
        info["is_outdated"] = False
        info["replaced_by"] = None
        full_text = soup.get_text()
        if "There are newer versions of this gallery available" in full_text:
            info["is_outdated"] = True
            # The newer version info is in div#gnd
            gnd = soup.select_one("#gnd")
            if gnd:
                links = gnd.find_all("a")
                if links:
                    # Get the last link (newest version)
                    info["replaced_by"] = links[-1].get("href")

        # Archive Link
        info["archiver_key"] = None
        for a in soup.find_all("a"):
            onclick = a.get("onclick", "")
            if "archiver.php" in onclick:
                match = re.search(r"or=([a-zA-Z0-9]+)", onclick)
                if match:
                    info["archiver_key"] = match.group(1)
                    break
        return info

    @staticmethod
    def parse_archiver_page(html: str) -> Dict[str, Dict]:
        soup = BeautifulSoup(html, "lxml")
        options = {}
        for form in soup.find_all("form"):
            submit = form.select_one("input[type='submit']")
            if not submit: continue
            val = submit.get("value", "")
            inp = form.select_one("input[name='dltype']")
            if not inp: continue
            
            action = form.get("action", "")
            if "Original" in val:
                options["original"] = {"dltype": inp["value"], "action": action}
            elif "Resample" in val:
                options["resample"] = {"dltype": inp["value"], "action": action}
        return options
