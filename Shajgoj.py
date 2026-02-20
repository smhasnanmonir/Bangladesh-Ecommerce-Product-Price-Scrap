import asyncio
import json
from playwright.async_api import async_playwright

async def run_playwright():
    async with async_playwright() as p:
        # Launch Firefox browser (headless=False for debugging)
        browser = await p.firefox.launch(headless=False)
        page = await browser.new_page()
        page.set_default_timeout(60000)

        # Go to the page
        await page.goto('https://shop.shajgoj.com/product-category/body-1?page=1')

        products_list = []

        # Wait for the product container to load
        try:
            await page.wait_for_selector("p.text-gray-700[title]")
        except Exception as e:
            print(f"Error waiting for product container: {e}")
            return

        # Scroll every 15 seconds by 100vh (100% of the viewport height)
        while True:
            # Calculate 100vh in pixels
            vh = await page.evaluate("window.innerHeight")  # Full viewport height in pixels
            print(f"Scrolling by {vh}px (100vh)...")
            await page.evaluate(f"window.scrollBy(0, {vh});")

            # Wait for 15 seconds before the next scroll
            await asyncio.sleep(3)

            # After scrolling, query the products and prices
            try:
                products = await page.query_selector_all("p.text-gray-700[title]")
                prices = await page.query_selector_all("span.text-sg-pink.font-semibold")

                print(f"Found {len(products)} products and {len(prices)} prices.")

                # Iterate through products and prices and extract the required information
                for product, price in zip(products, prices):
                    try:
                        product_name = await product.get_attribute("title")
                        product_price = await price.inner_text()
                        print(f"Product: {product_name}, Price: {product_price}")

                        # Store the product name and price as a dictionary
                        products_list.append({
                            "product_name": product_name,
                            "price": product_price
                        })
                    except Exception as e:
                        print(f"Error extracting product data: {e}")

            except Exception as e:
                print(f"Error querying product elements: {e}")

            # Add a break condition or a timeout after a certain number of scrolls or when no new content is loaded
            # For now, we will stop after collecting 50 products
            if len(products_list) > 800:  # Adjust this number based on the expected number of products
                break

        # Save the collected data to a JSON file
        
        file_name = input("Enter name of file: ")

        with open(file_name, 'w', encoding='utf-8') as json_file:
            json.dump(products_list, json_file, ensure_ascii=False, indent=4)

        # Close the browser
        await browser.close()

    # Print the collected product names and prices
    print("Collected product names and prices:", products_list)

# Function to run the asyncio event loop
def main():
    asyncio.run(run_playwright())

if __name__ == "__main__":
    main()
