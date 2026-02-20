# Bangladesh-Beauty-Product-Price-Scrap

## Setup Instructions

1. **Create a virtual environment:**
   ```bash
   python -m venv venv
   ```

2. **Activate the virtual environment:**
   - On Windows:
     ```bash
     .\venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

3. **Install Dependencies:**
   Install required packages (like Playwright):
   ```bash
   pip install playwright
   playwright install chromium
   ```

## Running the Scrapers

To run the scrapers (e.g., TokBD), ensure your virtual environment is activated and run:
```bash
python tokbd.py
```

## Comparing Prices (Fuzzy Matchting)

You can compare product prices extracted from two different scraper JSON files using the `compare_prices.py` script. The script uses intelligent fuzzy matching to align products with slightly different names (e.g., *“Anua Heartleaf Toner 30ml”* vs *“Heartleaf Anua Toner”*) and exports the results to a CSV file.

### Prerequisites for Comparison
You need the fuzzy matching package `thefuzz` and its `speedup` extension:
```bash
pip install thefuzz[speedup]
```

### Running the Comparison
Run the script by providing the paths to your two JSON files:
```bash
python compare_prices.py skinnora_products_20260220_230921.json tokbd_products.json
```

**Advanced Usage:**
By default, the script looks for an 85% match confidence. You can make it stricter or looser using the `--threshold` flag. You can also specify a custom output filename:
```bash
python compare_prices.py file1.json file2.json --threshold 90 --output my_comparison.csv
```
