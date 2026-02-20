import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import json
import logging
import sys
from datetime import datetime
import traceback
from typing import List, Dict
from pathlib import Path

# Configure logging to handle utf-8 properly
# This prevents cp1252 errors on Windows when printing emojis like ✅, ❌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tokbd_scraper.log', encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Force stdout to utf-8 if on windows (handle emoji printing)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

class TokBDScraper:
    def __init__(self, headless: bool = False, max_retries: int = 3, timeout: int = 30000):
        self.base_url = "https://tokbd.com"
        self.headless = headless
        self.max_retries = max_retries
        self.timeout = timeout
        self.all_products = []
        self.failed_pages = []
        self.seen_urls = set()
        self.current_page = 1
        
    async def setup_browser(self):
        """Initialize browser with proper error handling"""
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process'
                ]
            )
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            # Set default timeout
            page.set_default_timeout(self.timeout)
            
            # Add error handlers
            page.on('pageerror', lambda err: logger.error(f"Page error: {err}"))
            page.on('requestfailed', lambda request: logger.warning(f"Request failed: {request.url} - {request.failure}"))
            
            return playwright, browser, context, page
            
        except Exception as e:
            logger.error(f"Failed to setup browser: {e}")
            logger.error(traceback.format_exc())
            raise

    async def safe_goto(self, page, url: str, retry_count: int = 0) -> bool:
        """Navigate to URL with retry logic"""
        try:
            logger.info(f"Navigating to: {url} (attempt {retry_count + 1}/{self.max_retries})")
            
            strategies = ['networkidle', 'domcontentloaded', 'load']
            
            for strategy in strategies:
                try:
                    await page.goto(url, wait_until=strategy, timeout=self.timeout)
                    logger.info(f"Successfully loaded with {strategy} strategy")
                    return True
                except Exception as e:
                    logger.warning(f"Failed with {strategy} strategy: {str(e)}")
                    continue
            
            await page.goto(url, wait_until='commit', timeout=self.timeout)
            await asyncio.sleep(2)
            return True
            
        except PlaywrightTimeoutError:
            logger.error(f"Timeout loading {url}")
            if retry_count < self.max_retries - 1:
                logger.info(f"Retrying... ({retry_count + 2}/{self.max_retries})")
                await asyncio.sleep(5 * (retry_count + 1))
                return await self.safe_goto(page, url, retry_count + 1)
            return False
            
        except Exception as e:
            logger.error(f"Failed to load {url}: {e}")
            logger.error(traceback.format_exc())
            return False

    async def safe_wait_for_selector(self, page, selector: str, timeout: int = 15000) -> bool:
        """Wait for selector with error handling"""
        try:
            await page.wait_for_selector(selector, timeout=timeout, state='visible')
            return True
        except PlaywrightTimeoutError:
            logger.warning(f"Timeout waiting for selector: {selector}")
            return False
        except Exception as e:
            logger.error(f"Error waiting for selector {selector}: {e}")
            return False

    async def extract_product_data(self, page) -> List[Dict]:
        """Extract product data exactly like the original code"""
        try:
            # Check if products exist before extracting
            product_count = await page.evaluate('''() => document.querySelectorAll('div.grid > div.flex.flex-col.h-full.w-full.bg-white').length''')
            
            if product_count == 0:
                logger.warning("No products found on page")
                return []
            
            logger.info(f"Found {product_count} product cards on page")
            
            products = await page.evaluate(r'''(baseUrl) => {
                const data = [];
                const productCards = document.querySelectorAll('div.grid > div.flex.flex-col.h-full.w-full.bg-white');
                
                productCards.forEach((card, index) => {
                    try {
                        const linkEl = card.querySelector('a[href^="/products/"]');
                        if (!linkEl) return;
                        
                        const relativeUrl = linkEl.getAttribute('href');
                        const fullUrl = new URL(relativeUrl, baseUrl).href;
                        
                        // We need the literal string to have a proper formatted query selector in javascript
                        // so we search for element with `[14px]` text by using double slash escape
                        const nameEl = card.querySelector('h3.line-clamp-2, h3.text-\\[14px\\]');
                        const name = nameEl ? nameEl.textContent.trim() : '';
                        
                        const priceEl = card.querySelector('p.font-semibold.text-\\[18px\\]');
                        let price = '';
                        let currency = 'BDT';
                        
                        if (priceEl) {
                            const priceText = priceEl.textContent.trim();
                            const match = priceText.match(/([\d,]+)\s*Taka/i);
                            if (match) {
                                price = match[1].replace(/,/g, '');
                            }
                        }
                        
                        const imgEl = card.querySelector('img[src*="cdn.tokbd.shop"]');
                        const image_url = imgEl ? imgEl.src : '';
                        
                        const stockEl = card.querySelector('span.bg-emerald-100, span.text-emerald-700');
                        const in_stock = stockEl ? stockEl.textContent.toLowerCase().includes('in stock') : false;
                        
                        if (name && relativeUrl) {
                            data.push({
                                index: index + 1,
                                name: name,
                                price: price,
                                currency: currency,
                                price_formatted: price ? `${price} Taka` : '',
                                url: fullUrl,
                                relative_url: relativeUrl,
                                image_url: image_url,
                                in_stock: in_stock,
                                scraped_at: new Date().toISOString()
                            });
                        }
                    } catch (err) {
                        console.error('Error parsing card:', err);
                    }
                });
                return data;
            }''', self.base_url)
            
            logger.info(f"Successfully extracted {len(products)} products")
            return products
        except Exception as e:
            logger.error(f"Failed to extract product data: {e}")
            logger.error(traceback.format_exc())
            return []

    async def scrape_page(self, page, page_num: int) -> bool:
        """Scrape a single page with comprehensive error handling"""
        try:
            url = f"{self.base_url}/products?page={page_num}"
            logger.info(f"Processing page {page_num}: {url}")
            
            if not await self.safe_goto(page, url):
                self.failed_pages.append(page_num)
                logger.error(f"Failed to load page {page_num}")
                return False
            
            content_found = False
            content_selectors = [
                'div.grid > div.flex.flex-col',
                'div.grid'
            ]
            
            for selector in content_selectors:
                if await self.safe_wait_for_selector(page, selector, timeout=5000):
                    content_found = True
                    logger.info(f"Content found with selector: {selector}")
                    break
            
            if not content_found:
                logger.warning(f"No content found on page {page_num}")
                await page.screenshot(path=f'tokbd_error_page_{page_num}.png')
                return False
                
            if page_num % 10 == 0:
                await page.screenshot(path=f'tokbd_page_{page_num}_verification.png')
                logger.info(f"Verification screenshot saved for page {page_num}")
                
            await page.wait_for_timeout(1000)
            products = await self.extract_product_data(page)
            
            new_products = []
            for p in products:
                if p['url'] not in self.seen_urls:
                    self.seen_urls.add(p['url'])
                    new_products.append(p)
            
            if new_products:
                self.all_products.extend(new_products)
                logger.info(f"Page {page_num}: Scraped {len(new_products)} products (Total: {len(self.all_products)})")
                return True
            else:
                logger.warning(f"Page {page_num}: No new products extracted")
                if len(products) == 0:
                    # No duplicate overlap - definitely no products at all
                    return False
                return True
                
        except Exception as e:
            logger.error(f"Unexpected error scraping page {page_num}: {e}")
            logger.error(traceback.format_exc())
            self.failed_pages.append(page_num)
            return False

    async def save_progress(self):
        """Save current progress to JSON file"""
        try:
            filename = 'tokbd_products.json'
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    'source': self.base_url,
                    'scraped_at': datetime.now().isoformat(),
                    'total_products': len(self.all_products),
                    'pages_scraped': self.current_page - 1,
                    'failed_pages': self.failed_pages,
                    'currency': 'BDT (Taka)',
                    'products': self.all_products
                }, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Progress saved to {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
            return None

    def load_progress(self) -> bool:
        """Load progress from file instead of starting over"""
        filename = 'tokbd_products.json'
        if Path(filename).exists():
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.all_products = data.get('products', [])
                    self.seen_urls = {p['url'] for p in self.all_products}
                    self.current_page = data.get('pages_scraped', 0) + 1
                    self.failed_pages = data.get('failed_pages', [])
                    logger.info(f"📂 Loaded progress! Starting from page {self.current_page} with {len(self.all_products)} products.")
                    return True
            except Exception as e:
                logger.error(f"Failed to load progress: {e}")
        return False

    async def scrape_all_pages(self, max_pages=150):
        """Main method to scrape all pages with error handling"""
        playwright, browser, context, page = None, None, None, None
        
        try:
            playwright, browser, context, page = await self.setup_browser()
            
            logger.info("Starting scrape of TOKBD...")
            
            for page_num in range(self.current_page, max_pages + 1):
                self.current_page = page_num
                
                success = await self.scrape_page(page, page_num)
                
                if not success:
                    # Let's check next page to be absolutely sure we've reached the end
                    logger.info(f"Checking if page {page_num + 1} has products to confirm end of catalog...")
                    test_success = await self.scrape_page(page, page_num + 1)
                    if not test_success:
                        logger.warning(f"Confirmed end of products. Stopping scrape.")
                        break
                    else:
                        logger.info(f"Page {page_num + 1} had products, continuing...")
                        self.current_page = page_num + 1
                
                if page_num % 5 == 0:
                    await self.save_progress()
                
                await asyncio.sleep(2)
            
            final_file = await self.save_progress()
            
            logger.info("=" * 60)
            logger.info("SCRAPE COMPLETED")
            logger.info("=" * 60)
            logger.info(f"Total products scraped: {len(self.all_products)}")
            logger.info(f"Pages processed: {self.current_page}")
            logger.info(f"Failed pages: {len(self.failed_pages)}")
            if self.failed_pages:
                logger.info(f"Failed page numbers: {self.failed_pages}")
            logger.info(f"Data saved to: {final_file}")
            
            products_in_stock = sum(1 for p in self.all_products if p.get('in_stock'))
            logger.info(f"Products in stock: {products_in_stock}")
            logger.info(f"Out of stock: {len(self.all_products) - products_in_stock}")
            
        except Exception as e:
            logger.error(f"Fatal error during scraping: {e}")
            logger.error(traceback.format_exc())
            
            if self.all_products:
                emergency_file = f'tokbd_emergency_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                with open(emergency_file, 'w', encoding='utf-8') as f:
                    json.dump(self.all_products, f, indent=2, ensure_ascii=False)
                logger.info(f"Emergency backup saved to {emergency_file}")
            
        finally:
            if page: await page.close()
            if context: await context.close()
            if browser: await browser.close()
            if playwright: await playwright.stop()

async def test_scraper():
    """Quick test function"""
    scraper = TokBDScraper(headless=False, max_retries=2)
    playwright, browser, context, page = None, None, None, None
    
    try:
        playwright, browser, context, page = await scraper.setup_browser()
        
        logger.info("Running quick test on page 1...")
        url = f"{scraper.base_url}/products?page=1"
        
        if await scraper.safe_goto(page, url):
            if await scraper.safe_wait_for_selector(page, 'div.grid > div.flex.flex-col', timeout=15000):
                products = await scraper.extract_product_data(page)
                logger.info(f"Test successful! Found {len(products)} products on page 1")
                
                for i, product in enumerate(products[:3], 1):
                    logger.info(f"Sample {i}: {product['name']} - {product['price_formatted']}")
                
                return True
            else:
                logger.error("Test failed: No products found")
                return False
        else:
            logger.error("Test failed: Could not load page")
            return False
            
    finally:
        if page: await page.close()
        if context: await context.close()
        if browser: await browser.close()
        if playwright: await playwright.stop()

async def main():
    logger.info("=" * 60)
    logger.info("TOKBD SCRAPER - ENHANCED VERSION")
    logger.info("=" * 60)
    
    print("\nSelect mode:")
    print("1. Run test only")
    print("2. Run full scrape (from beginning)")
    print("3. Resume from last saved progress")
    
    choice = input("Enter choice (1/2/3): ").strip()
    
    if choice == "1":
        logger.info("Running test mode...")
        success = await test_scraper()
        if success:
            logger.info("✅ Test passed! Ready for full scrape.")
        else:
            logger.error("❌ Test failed! Check the website and your connection.")
            
    elif choice == "2":
        logger.info("Running full scrape...")
        scraper = TokBDScraper(headless=False)
        await scraper.scrape_all_pages(max_pages=200)
        
    elif choice == "3":
        logger.info("Attempting to resume scrape...")
        scraper = TokBDScraper(headless=False)
        if scraper.load_progress():
            await scraper.scrape_all_pages(max_pages=200)
        else:
            logger.info("No saved progress found. Starting full scrape from beginning...")
            await scraper.scrape_all_pages(max_pages=200)
            
    else:
        logger.error("Invalid choice")

if __name__ == "__main__":
    asyncio.run(main())
