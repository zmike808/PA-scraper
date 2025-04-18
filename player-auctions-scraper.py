import bs4
import requests
import re
import sys
import os
import random
import time
import traceback
import csv
import datetime
import logging
from pathlib import Path
from collections import namedtuple

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set more specific log levels
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('bs4').setLevel(logging.WARNING)

Row = namedtuple('Row', ["Name", "Price"])
df = []

# Headers to mimic a real browser
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:93.0) Gecko/20100101 Firefox/93.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Referer': 'https://www.playerauctions.com/',
        'Cache-Control': 'max-age=0',
    }

def get_results(soup, target_class="offer-price-tag"):
    """Try different possible class names to find the data"""
    results = soup.findAll(class_=target_class)
    logger.info(f"Found {len(results)} results for class '{target_class}'")
    
    # If no results with the original class, try common alternatives
    if len(results) <= 0:
        possible_classes = [
            "product-price", 
            "price-tag",
            "price",
            "listing-price",
            "offer-price"
        ]
        
        for alt_class in possible_classes:
            alt_results = soup.findAll(class_=alt_class)
            logger.info(f"Trying alternative class '{alt_class}': found {len(alt_results)} results")
            
            if len(alt_results) > 0:
                logger.info(f"Using alternative class '{alt_class}' instead of '{target_class}'")
                return alt_results
    
    return results

def get_soup(df, url_index, price_limit=2000.00, rating_limit=5.0):
    soup_url = f"https://www.playerauctions.com/osrs-account/?SortField=least-reviews&PageIndex={url_index}&Serverid=5568"
    logger.info(f"Fetching URL: {soup_url}")
    
    try:
        headers = get_headers()
        logger.info(f"Using User-Agent: {headers['User-Agent'][:30]}...")
        
        # Add a session to manage cookies
        session = requests.Session()
        response = session.get(soup_url, headers=headers, timeout=30)
        response.raise_for_status()  # Raise an exception for bad status codes
        logger.info(f"Response status code: {response.status_code}")
        
        # Log the first 500 characters of the response to check the content
        logger.info(f"Response preview: {response.text[:500]}")
        
        # Save the HTML response for debugging if necessary
        # with open(f"debug_page_{url_index}.html", "w", encoding="utf-8") as f:
        #     f.write(response.text)
            
        soup = bs4.BeautifulSoup(response.text, "html.parser")
        
        # Debug: Print all available classes in the HTML
        all_classes = set()
        for tag in soup.find_all(class_=True):
            all_classes.update(tag["class"])
        logger.info(f"Available classes in HTML: {all_classes}")

        try:
            # Try to find the results with different possible class combinations
            price_results = get_results(soup)
            rating_results = get_results(soup, "offer-rating offer-item-rating")
            
            # If we couldn't find ratings with the original class, try alternatives
            if len(rating_results) <= 0:
                rating_classes = [
                    "rating", 
                    "user-rating",
                    "seller-rating",
                    "item-rating"
                ]
                
                for alt_class in rating_classes:
                    alt_results = soup.findAll(class_=alt_class)
                    logger.info(f"Trying alternative rating class '{alt_class}': found {len(alt_results)} results")
                    
                    if len(alt_results) > 0:
                        logger.info(f"Using alternative rating class '{alt_class}'")
                        rating_results = alt_results
                        break
            
            if len(price_results) <= 0 or len(rating_results) <= 0:
                logger.warning(f"Could not find price results ({len(price_results)}) or rating results ({len(rating_results)})")
                return df, False
                
            # Try to pair price and rating results
            try:
                results = list(zip(price_results, rating_results))
                logger.info(f"Found {len(results)} paired results")
                
                # Process the paired results as before
                for r in results:
                    try:
                        price_text = r[0].text.strip()
                        rating_text = r[1].text.strip()
                        
                        if not price_text or not rating_text:
                            logger.warning("Skipping result with empty price or rating")
                            continue
                        
                        # Extract numeric price value (handle different formats)
                        price_match = re.search(r'\$?([\d,.]+)', price_text)
                        if not price_match:
                            logger.warning(f"Could not parse price from: {price_text}")
                            continue
                        price_value = float(price_match.group(1).replace(',', ''))
                        
                        # Extract numeric rating value
                        rating_match = re.search(r'([\d.]+)', rating_text)
                        if not rating_match:
                            logger.warning(f"Could not parse rating from: {rating_text}")
                            continue
                        rating = float(rating_match.group(1))
                        
                        if price_value < price_limit and rating <= rating_limit:
                            for h in r[0].parent.findAll(href=True):
                                url = h['href']
                                if not url.startswith('http'):
                                    url = f"https://www.playerauctions.com{url}"
                                logger.info(f"Adding listing: URL={url}, Price={price_value}, Rating={rating}")
                                forbidden = ["pure","iron","stake","obby","level-3","1def","ironman","zerker","hcim","hardcore","g-maul-pure"]
                                if any(forbidden in url.lower() for forbidden in forbidden):
                                    logger.info(f"Skipping listing: URL={url}, Price={price_value}, Rating={rating}")
                                    continue
                                df.append({"url": url, "price": price_value, "rating": rating})
                    except (ValueError, IndexError, AttributeError) as e:
                        logger.error(f"Error processing result: {str(e)}")
                        continue
                
                return df, True
            except Exception as e:
                logger.error(f"Error pairing results: {str(e)}")
                # If we can't pair the results, try to find product containers instead
                product_containers = soup.findAll(class_="product-item") or soup.findAll(class_="offer-item") or soup.findAll(class_="listing-item")
                if product_containers:
                    logger.info(f"Found {len(product_containers)} product containers")
                    # Process these containers instead
                    for container in product_containers:
                        try:
                            price_elem = container.findAll(class_="offer-price-tag") or container.findAll(class_="price") or container.findAll(class_="product-price")
                            rating_elem = container.findAll(class_="rating") or container.findAll(class_="offer-rating") or container.findAll(class_="user-rating")
                            
                            if price_elem and rating_elem:
                                price_text = price_elem[0].text.strip()
                                rating_text = rating_elem[0].text.strip()
                                
                                # Process each item as before
                                # Extract numeric price value (handle different formats)
                                price_match = re.search(r'\$?([\d,.]+)', price_text)
                                if not price_match:
                                    logger.warning(f"Could not parse price from: {price_text}")
                                    continue
                                price_value = float(price_match.group(1).replace(',', ''))
                                
                                # Extract numeric rating value
                                rating_match = re.search(r'([\d.]+)', rating_text)
                                if not rating_match:
                                    logger.warning(f"Could not parse rating from: {rating_text}")
                                    continue
                                rating = float(rating_match.group(1))
                                
                                if price_value < price_limit and rating <= rating_limit:
                                    for h in container.findAll(href=True):
                                        url = h['href']
                                        if not url.startswith('http'):
                                            url = f"https://www.playerauctions.com{url}"
                                        logger.info(f"Adding listing: URL={url}, Price={price_value}, Rating={rating}")
                                        forbidden = ["pure","iron","stake","obby","level-3","1def","ironman","zerker","hcim","hardcore","g-maul-pure"]
                                        if any(forbidden in url.lower() for forbidden in forbidden):
                                            logger.info(f"Skipping listing: URL={url}, Price={price_value}, Rating={rating}")
                                            continue
                                        df.append({"url": url, "price": price_value, "rating": rating})
                        except Exception as e:
                            logger.error(f"Error processing container: {str(e)}")
                    
                    return df, True
                return df, False
                
        except Exception as e:
            logger.error(f"Error processing page: {str(e)}")
            traceback.print_exc()
            return df, False

        return df, True
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error: {e}")
        traceback.print_exc()
        return df, False
    except Exception as e:
        logger.error(f"Error connecting to site: {str(e)}")
        traceback.print_exc()
        return df, False

df = list()
url_index = 1
hasMore = True
max_retries = 3
retry_count = 0

while hasMore and retry_count < max_retries:
    try:
        logger.info(f"Processing page {url_index}")
        df, hasMore = get_soup(df, url_index, price_limit=2500.00, rating_limit=5.0)
        
        if not hasMore and len(df) == 0:
            retry_count += 1
            logger.warning(f"No results found. Retry {retry_count}/{max_retries}")
            sleep_time = 2 * (2 ** retry_count)  # Exponential backoff
            logger.info(f"Waiting {sleep_time} seconds before retry")
            time.sleep(sleep_time)  # Add exponential delay between retries
        else:
            url_index += 1
            retry_count = 0  # Reset retry count on success
            time.sleep(random.uniform(1, 3))  # Random delay between successful requests
            
    except Exception as e:
        logger.error(f"Error processing page {url_index}: {str(e)}")
        retry_count += 1
        sleep_time = 2 * (2 ** retry_count)  # Exponential backoff
        logger.info(f"Waiting {sleep_time} seconds before retry")
        time.sleep(sleep_time)

logger.info(f"Final results: {len(df)} listings found across {url_index-1} pages")

# Create output filename with current date and time
current_time = datetime.datetime.now()
output_file = Path(f'pa_accounts_{current_time.strftime("%Y-%m-%d_%H-%M-%S")}.csv')

try:
    with output_file.open('w', newline='') as csvfile:
        fieldnames = ['url', 'price', 'rating']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in df:
            writer.writerow(row)
    logger.info(f"Results saved to {output_file}")
except Exception as e:
    logger.error(f"Error saving results: {str(e)}")

# def print_hi(name):
#     # Use a breakpoint in the code line below to debug your script.
#     print(f'Hi, {name}')  # Press ⌘F8 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
# if __name__ == '__main__':
    # print_hi('PyCharm')

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
