import json
import re
import argparse
import sys
from pathlib import Path

try:
    from thefuzz import fuzz
    from thefuzz import process
except ImportError:
    print("Error: 'thefuzz' package is required.")
    print("Please install it by running: pip install thefuzz[speedup]")
    sys.exit(1)

def normalize_name(name):
    """
    Standardize the product name to improve fuzzy matching ratios.
    Removes weights, volumes, and special characters.
    """
    if not isinstance(name, str):
        return ""
        
    # Lowercase
    name = name.lower()
    
    # Remove volume, weight, etc. (e.g. - 30ml, 50g, 1oz, 30 ml)
    name = re.sub(r'(?:-?\s*)\b\d+(?:\.\d+)?\s*(?:ml|g|oz|kg|l)\b', '', name)
    
    # Remove special characters except alphanumeric and spaces
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    
    # Remove extra spaces
    name = ' '.join(name.split())
    
    return name

def extract_price(product_dict):
    """
    Try to extract a numeric price from possible price fields across different scrapers.
    """
    price_fields = ['price', 'sale_price', 'regular_price', 'price_formatted']
    
    for field in price_fields:
        val = product_dict.get(field)
        if val:
            # Extract number from string like "৳ 1,200", "550 Taka", "1,200"
            match = re.search(r'([\d,]+(?:\.\d+)?)', str(val))
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except ValueError:
                    continue
    return None

def load_products(filepath):
    """
    Reads a JSON file and attempts to extract a list of products.
    Handles different JSON structures (list of dicts, or dict with 'products' list).
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Handle dicts with a 'products' array vs raw arrays
        products = data.get('products', data) if isinstance(data, dict) else data
        
        parsed = []
        for p in products:
            if not isinstance(p, dict):
                continue
                
            name = p.get('name', '')
            if not name:
                continue
                
            price = extract_price(p)
            parsed.append({
                'original_name': name,
                'normalized_name': normalize_name(name),
                'price': price,
                'url': p.get('url') or p.get('product_url') or p.get('relative_url') or 'N/A'
            })
            
        return parsed
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return []

def print_progress(current, total):
    """Print a simple progress bar."""
    percent = (current / total) * 100
    bar = '=' * int(percent / 2) + '-' * (50 - int(percent / 2))
    sys.stdout.write(f'\rComparing: [{bar}] {percent:.1f}%')
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser(description="Compare product prices using fuzzy matching.")
    parser.add_argument("file1", help="Path to first JSON file")
    parser.add_argument("file2", help="Path to second JSON file")
    parser.add_argument("--threshold", type=int, default=85, help="Fuzzy match threshold (0-100), default 85")
    parser.add_argument("--output", default="price_comparison.csv", help="Output CSV file (default: price_comparison.csv)")
    
    args = parser.parse_args()
    
    file1_path = Path(args.file1)
    file2_path = Path(args.file2)
    
    if not file1_path.exists():
        print(f"Error: {file1_path} does not exist.")
        return
    if not file2_path.exists():
        print(f"Error: {file2_path} does not exist.")
        return
        
    print(f"Loading {file1_path.name}...")
    products1 = load_products(file1_path)
    print(f"Loaded {len(products1)} products.")
    
    print(f"Loading {file2_path.name}...")
    products2 = load_products(file2_path)
    print(f"Loaded {len(products2)} products.")
    
    if not products1 or not products2:
        print("Error: One or both files had no readable products.")
        return
        
    print(f"Comparing products with fuzzy threshold >= {args.threshold}...")
    
    matches = []
    
    # We use token_set_ratio which handles string lengths and word order excellently.
    # Ex: token_set_ratio("Anua Heartleaf", "Heartleaf Anua Toner - 30ml") is robust.
    
    # Keep track of matched indices in file 2 to prevent duplicates mapping to the same product
    matched_file2_indices = set()
    total_products = len(products1)
    
    for i, p1 in enumerate(products1):
        if i % 10 == 0 or i == total_products - 1:
            print_progress(i + 1, total_products)
            
        best_match = None
        best_score = 0
        best_idx = -1
        
        for j, p2 in enumerate(products2):
            if j in matched_file2_indices:
                continue
                
            score = fuzz.token_set_ratio(p1['normalized_name'], p2['normalized_name'])
            
            if score > best_score:
                best_score = score
                best_match = p2
                best_idx = j
                
            if best_score == 100:
                break
                
        if best_match and best_score >= args.threshold:
            matches.append({
                'score': best_score,
                'f1_name': p1['original_name'],
                'f1_price': p1['price'],
                'f2_name': best_match['original_name'],
                'f2_price': best_match['price'],
                'f1_url': p1['url'],
                'f2_url': best_match['url'],
                'diff': (p1['price'] - best_match['price']) if (p1['price'] and best_match['price']) else None
            })
            matched_file2_indices.add(best_idx)
            
    print(f"\nFound {len(matches)} matching products!")
    
    # Sort matches by score descending
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    # Write to CSV
    import csv
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Match Score', 
            f'{file1_path.stem} Name', 
            f'{file1_path.stem} Price', 
            f'{file2_path.stem} Name', 
            f'{file2_path.stem} Price', 
            'Price Diff (F1 - F2)',
            f'{file1_path.stem} URL',
            f'{file2_path.stem} URL'
        ])
                         
        for m in matches:
            diff_str = f"৳ {round(m['diff'], 2)}" if m['diff'] is not None else 'N/A'
            f1_price_str = f"৳ {m['f1_price']}" if m['f1_price'] is not None else 'N/A'
            f2_price_str = f"৳ {m['f2_price']}" if m['f2_price'] is not None else 'N/A'
            
            writer.writerow([
                m['score'], 
                m['f1_name'], f1_price_str, 
                m['f2_name'], f2_price_str, 
                diff_str,
                m['f1_url'], m['f2_url']
            ])
            
    print(f"Comparison saved to {args.output}")
    print(f"To view it easily, you can open {args.output} in Excel.")

if __name__ == "__main__":
    main()
