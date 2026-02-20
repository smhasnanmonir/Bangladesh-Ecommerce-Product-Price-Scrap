import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import json
import logging
from datetime import datetime
import os
from typing import List, Dict, Optional
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SkinnoraScraper:
    def __init__(self, headless: bool = False, max_retries: int = 3, timeout: int = 30000):
        self.base_url = "https://www.skinnora.com/shop"
        self.headless = headless
        self.max_retries = max_retries
        self.timeout = timeout
        self.all_products = []
        self.failed_pages = []
        self.current_page = 1
        self.total_pages = None
        
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
            
            # Try different wait strategies
            strategies = ['networkidle', 'domcontentloaded', 'load']
            
            for strategy in strategies:
                try:
                    await page.goto(url, wait_until=strategy, timeout=self.timeout)
                    logger.info(f"Successfully loaded with {strategy} strategy")
                    return True
                except Exception as e:
                    logger.warning(f"Failed with {strategy} strategy: {str(e)}")
                    continue
            
            # If all strategies fail, try one last time with minimal waiting
            await page.goto(url, wait_until='commit', timeout=self.timeout)
            await asyncio.sleep(2)  # Give it some time to load
            return True
            
        except PlaywrightTimeoutError:
            logger.error(f"Timeout loading {url}")
            if retry_count < self.max_retries - 1:
                logger.info(f"Retrying... ({retry_count + 2}/{self.max_retries})")
                await asyncio.sleep(5 * (retry_count + 1))  # Exponential backoff
                return await self.safe_goto(page, url, retry_count + 1)
            return False
            
        except Exception as e:
            logger.error(f"Failed to load {url}: {e}")
            logger.error(traceback.format_exc())
            return False

    async def safe_wait_for_selector(self, page, selector: str, timeout: int = 10000) -> bool:
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
        """Extract product data with error handling"""
        try:
            # Check if products exist
            product_count = await page.evaluate('''
                () => {
                    const products = document.querySelectorAll('.products li.product');
                    return products.length;
                }
            ''')
            
            if product_count == 0:
                logger.warning("No products found on page")
                return []
            
            logger.info(f"Found {product_count} products on page")
            
            # Extract data with detailed error handling
            products = await page.evaluate('''
                () => {
                    const products = [];
                    const productElements = document.querySelectorAll('.products li.product');
                    
                    productElements.forEach((product, index) => {
                        try {
                            // Get product name with multiple selector attempts
                            const nameSelectors = [
                                '.woocommerce-loop-product__title',
                                'h2',
                                '.product-title',
                                '[itemprop="name"]'
                            ];
                            
                            let name = '';
                            for (const selector of nameSelectors) {
                                const element = product.querySelector(selector);
                                if (element && element.textContent) {
                                    name = element.textContent.trim();
                                    break;
                                }
                            }
                            
                            // Get price with multiple selector attempts
                            const priceSelectors = [
                                '.price',
                                '.amount',
                                '.woocommerce-Price-amount'
                            ];
                            
                            let regularPrice = '';
                            let salePrice = '';
                            
                            for (const selector of priceSelectors) {
                                const priceElement = product.querySelector(selector);
                                if (priceElement) {
                                    const saleIns = priceElement.querySelector('ins');
                                    const saleDel = priceElement.querySelector('del');
                                    
                                    if (saleIns && saleDel) {
                                        regularPrice = saleDel.textContent.trim();
                                        salePrice = saleIns.textContent.trim();
                                    } else {
                                        regularPrice = priceElement.textContent.trim();
                                    }
                                    break;
                                }
                            }
                            
                            // Get product URL
                            const linkSelectors = [
                                'a.woocommerce-LoopProduct-link',
                                'a[href*="product"]',
                                '.product-title a'
                            ];
                            
                            let productUrl = '';
                            for (const selector of linkSelectors) {
                                const element = product.querySelector(selector);
                                if (element && element.href) {
                                    productUrl = element.href;
                                    break;
                                }
                            }
                            
                            // Get image URL
                            const imageSelectors = [
                                'img',
                                '.wp-post-image',
                                '.attachment-woocommerce_thumbnail'
                            ];
                            
                            let imageUrl = '';
                            for (const selector of imageSelectors) {
                                const element = product.querySelector(selector);
                                if (element && element.src) {
                                    imageUrl = element.src;
                                    break;
                                }
                            }
                            
                            // Get categories
                            const categoriesElement = product.querySelector('.loop-product-categories');
                            const categories = categoriesElement ? categoriesElement.textContent.trim() : '';
                            
                            // Get sale badge
                            const saleBadge = !!product.querySelector('.onsale');
                            
                            // Get SKU if available
                            const skuElement = product.querySelector('.product-sku');
                            const sku = skuElement ? skuElement.textContent.replace('SKU:', '').trim() : '';
                            
                            if (name) {
                                products.push({
                                    index: index + 1,
                                    name: name,
                                    regular_price: regularPrice,
                                    sale_price: salePrice,
                                    is_on_sale: saleBadge,
                                    product_url: productUrl,
                                    image_url: imageUrl,
                                    categories: categories,
                                    sku: sku,
                                    scraped_at: new Date().toISOString()
                                });
                            } else {
                                console.log(`Product ${index + 1} has no name, skipping`);
                            }
                            
                        } catch (error) {
                            console.log(`Error parsing product ${index + 1}:`, error);
                        }
                    });
                    
                    return products;
                }
            ''')
            
            logger.info(f"Successfully extracted {len(products)} products")
            return products
            
        except Exception as e:
            logger.error(f"Failed to extract product data: {e}")
            logger.error(traceback.format_exc())
            return []

    async def get_total_pages(self, page) -> int:
        """Get total number of pages with error handling"""
        try:
            total_pages = await page.evaluate('''
                () => {
                    try {
                        const pagination = document.querySelector('nav.woocommerce-pagination');
                        if (!pagination) return 1;
                        
                        const pageNumbers = new Set();
                        
                        // Get all page number links
                        pagination.querySelectorAll('.page-numbers').forEach(el => {
                            const text = el.textContent.trim();
                            const num = parseInt(text);
                            if (!isNaN(num)) {
                                pageNumbers.add(num);
                            }
                        });
                        
                        // Also check for last page link
                        const lastLink = pagination.querySelector('a.page-numbers:not(.next):not(.prev)');
                        if (lastLink) {
                            const lastNum = parseInt(lastLink.textContent);
                            if (!isNaN(lastNum)) {
                                pageNumbers.add(lastNum);
                            }
                        }
                        
                        // Check current page indicator
                        const currentSpan = pagination.querySelector('span.page-numbers.current');
                        if (currentSpan) {
                            const currentNum = parseInt(currentSpan.textContent);
                            if (!isNaN(currentNum)) {
                                pageNumbers.add(currentNum);
                            }
                        }
                        
                        const numbers = Array.from(pageNumbers);
                        return numbers.length > 0 ? Math.max(...numbers) : 1;
                        
                    } catch (error) {
                        console.log('Error getting total pages:', error);
                        return 1;
                    }
                }
            ''')
            
            logger.info(f"Total pages detected: {total_pages}")
            return total_pages
            
        except Exception as e:
            logger.error(f"Failed to get total pages: {e}")
            return 1  # Assume single page if detection fails

    async def scrape_page(self, page, page_num: int) -> bool:
        """Scrape a single page with comprehensive error handling"""
        try:
            # Construct URL
            url = self.base_url if page_num == 1 else f"{self.base_url}/page/{page_num}/"
            logger.info(f"Processing page {page_num}: {url}")
            
            # Navigate to page
            if not await self.safe_goto(page, url):
                self.failed_pages.append(page_num)
                logger.error(f"Failed to load page {page_num}")
                return False
            
            # Wait for content with multiple attempts
            content_found = False
            content_selectors = [
                '.products li.product',
                '.products',
                '.woocommerce-loop-product__title',
                '.product'
            ]
            
            for selector in content_selectors:
                if await self.safe_wait_for_selector(page, selector, timeout=5000):
                    content_found = True
                    logger.info(f"Content found with selector: {selector}")
                    break
            
            if not content_found:
                logger.warning(f"No content found on page {page_num}")
                # Take screenshot for debugging
                await page.screenshot(path=f'error_page_{page_num}.png')
                return False
            
            # Take screenshot for verification (optional)
            if page_num % 10 == 0:  # Every 10th page
                await page.screenshot(path=f'page_{page_num}_verification.png')
                logger.info(f"Verification screenshot saved for page {page_num}")
            
            # Extract product data
            products = await self.extract_product_data(page)
            
            if products:
                self.all_products.extend(products)
                logger.info(f"Page {page_num}: Scraped {len(products)} products (Total: {len(self.all_products)})")
                return True
            else:
                logger.warning(f"Page {page_num}: No products extracted")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error scraping page {page_num}: {e}")
            logger.error(traceback.format_exc())
            self.failed_pages.append(page_num)
            return False

    async def save_progress(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = 'skinnora_products.json'
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    'scraped_at': timestamp,
                    'total_products': len(self.all_products),
                    'pages_scraped': self.current_page - 1,
                    'failed_pages': self.failed_pages,
                    'products': self.all_products
                }, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Progress saved to {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
            return None

    async def scrape_all_pages(self):
        """Main method to scrape all pages with comprehensive error handling"""
        playwright, browser, context, page = None, None, None, None
        
        try:
            # Setup browser
            playwright, browser, context, page = await self.setup_browser()
            
            # Get first page to determine total pages
            logger.info("Loading first page to determine total pages...")
            if not await self.safe_goto(page, self.base_url):
                raise Exception("Failed to load first page")
            
            if not await self.safe_wait_for_selector(page, '.products li.product'):
                logger.warning("No products found on first page")
            
            self.total_pages = await self.get_total_pages(page)
            logger.info(f"Starting scrape of {self.total_pages} pages")
            
            # Scrape each page
            for page_num in range(1, self.total_pages + 1):
                self.current_page = page_num
                
                success = await self.scrape_page(page, page_num)
                
                if not success:
                    logger.warning(f"Page {page_num} failed, continuing to next page")
                
                # Save progress every 10 pages
                if page_num % 10 == 0:
                    await self.save_progress()
                
                # Be respectful to server
                await asyncio.sleep(2)
            
            # Final save
            final_file = await self.save_progress()
            
            # Print summary
            logger.info("=" * 60)
            logger.info("SCRAPE COMPLETED")
            logger.info("=" * 60)
            logger.info(f"Total products scraped: {len(self.all_products)}")
            logger.info(f"Pages processed: {self.current_page}")
            logger.info(f"Failed pages: {len(self.failed_pages)}")
            if self.failed_pages:
                logger.info(f"Failed page numbers: {self.failed_pages}")
            logger.info(f"Data saved to: {final_file}")
            
            # Calculate statistics
            products_on_sale = sum(1 for p in self.all_products if p.get('is_on_sale'))
            logger.info(f"Products on sale: {products_on_sale}")
            logger.info(f"Regular price products: {len(self.all_products) - products_on_sale}")
            
        except Exception as e:
            logger.error(f"Fatal error during scraping: {e}")
            logger.error(traceback.format_exc())
            
            # Save whatever we have
            if self.all_products:
                emergency_file = f'emergency_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                with open(emergency_file, 'w', encoding='utf-8') as f:
                    json.dump(self.all_products, f, indent=2, ensure_ascii=False)
                logger.info(f"Emergency backup saved to {emergency_file}")
            
        finally:
            # Clean up
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

async def test_scraper():
    """Quick test function"""
    scraper = SkinnoraScraper(headless=False, max_retries=2)
    
    playwright, browser, context, page = None, None, None, None
    
    try:
        playwright, browser, context, page = await scraper.setup_browser()
        
        logger.info("Running quick test on first page...")
        
        if await scraper.safe_goto(page, scraper.base_url):
            if await scraper.safe_wait_for_selector(page, '.products li.product', timeout=5000):
                products = await scraper.extract_product_data(page)
                logger.info(f"Test successful! Found {len(products)} products on first page")
                
                # Display first 3 products
                for i, product in enumerate(products[:3], 1):
                    logger.info(f"Sample {i}: {product['name']} - {product['regular_price']}")
                
                return True
            else:
                logger.error("Test failed: No products found")
                return False
        else:
            logger.error("Test failed: Could not load page")
            return False
            
    finally:
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()

async def main():
    """Main function with error recovery options"""
    logger.info("=" * 60)
    logger.info("SKINNORA SCRAPER - ENHANCED VERSION")
    logger.info("=" * 60)
    
    # Ask user for mode
    print("\nSelect mode:")
    print("1. Run test only")
    print("2. Run full scrape")
    print("3. Resume from failed pages")
    
    choice = input("Enter choice (1/2/3): ").strip()
    
    if choice == "1":
        # Run test only
        logger.info("Running test mode...")
        success = await test_scraper()
        if success:
            logger.info("✅ Test passed! Ready for full scrape.")
        else:
            logger.error("❌ Test failed! Check the website and your connection.")
            
    elif choice == "2":
        # Run full scrape
        logger.info("Running full scrape...")
        scraper = SkinnoraScraper(headless=False, max_retries=3)
        await scraper.scrape_all_pages()
        
    elif choice == "3":
        # Resume from failed pages
        # This would need previous failed pages data
        logger.info("Resume functionality requires previous run data")
        logger.info("Please run full scrape instead")
        
    else:
        logger.error("Invalid choice")

if __name__ == "__main__":
    asyncio.run(main())