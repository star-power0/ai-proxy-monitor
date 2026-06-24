import asyncio
import os
import sys

CDP_URL = "http://127.0.0.1:9222"

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            print("Connected.")
        except Exception as e:
            print(f"Failed: {e}")
            return
            
        page = await context.new_page()
        
        requests = []
        async def handle_request(request):
            requests.append((request.method, request.url))
                
        page.on("request", handle_request)
        
        try:
            print("Navigating to https://svip.riyuexy.cc/dashboard...")
            await page.goto("https://svip.riyuexy.cc/dashboard", timeout=20000, wait_until="networkidle")
            await asyncio.sleep(4.0)
            
            print(f"Final URL: {page.url}")
            print(f"Page Title: {await page.title()}")
            print("\nCaptured API/Data requests on riyue:")
            for method, url in requests:
                if "/api/" in url or "prices" in url or "user" in url or "pricing" in url or "info" in url:
                    print(f"  {method} {url}")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await page.close()

if __name__ == "__main__":
    asyncio.run(main())
