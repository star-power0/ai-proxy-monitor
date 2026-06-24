import asyncio

CDP_URL = "http://127.0.0.1:9222"

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = await context.new_page()
        
        requests = []
        async def handle_request(request):
            requests.append((request.method, request.url))
            
        page.on("request", handle_request)
        
        try:
            print("Navigating to https://sub2api.tygzs.cn/dashboard...")
            await page.goto("https://sub2api.tygzs.cn/dashboard", timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(5.0)
            
            # Print page text
            text = await page.evaluate("() => document.body.innerText")
            print("--- Dashboard Text Snippet ---")
            print(text[:1000])
            
            # Find all links on the page
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.href
                }));
            }""")
            print("--- Links found on page ---")
            for link in links:
                if link['text'] or link['href']:
                    print(f"  [{link['text']}] -> {link['href']}")
            
            # Let's try navigating to a few guessed paths
            for path in ["/models", "/pricing", "/prices", "/rates"]:
                test_url = f"https://sub2api.tygzs.cn{path}"
                print(f"\nNavigating to {test_url}...")
                try:
                    await page.goto(test_url, timeout=10000, wait_until="domcontentloaded")
                    await asyncio.sleep(2.0)
                    print(f"Success. Current URL is: {page.url}")
                except Exception as ne:
                    print(f"Failed to navigate to {path}: {ne}")
            
            print("\n--- Captured Requests during guessed paths ---")
            for method, url in requests:
                if any(kw in url.lower() for kw in ("/api/", "model", "price", "rate", "group")):
                    print(f"  {method} {url}")
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await page.close()

if __name__ == "__main__":
    asyncio.run(main())
