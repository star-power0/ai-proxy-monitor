import asyncio
import json

async def diagnose_keys_api(context, name, url):
    print(f"\n=================== Diagnosing Keys Page for {name}: {url} ===================")
    page = await context.new_page()
    
    captured_responses = []
    
    async def handle_response(response):
        url = response.url.lower()
        if "/api/" in url:
            try:
                data = await response.json()
                captured_responses.append({
                    "url": response.url,
                    "method": response.request.method,
                    "status": response.status,
                    "data": data
                })
            except Exception:
                pass
                
    page.on("response", handle_response)
    
    try:
        await page.goto(url, timeout=25000, wait_until="domcontentloaded")
        await asyncio.sleep(8.0) # Wait for page and key options to load completely
        
        print(f"Loaded page: {page.url}")
        
        print(f"\nCaptured API Responses ({len(captured_responses)}):")
        for req in captured_responses:
            u = req["url"].lower()
            data_str = json.dumps(req["data"], ensure_ascii=False)
            print(f"  {req['method']} {req['url']} (Status {req['status']})")
            print(f"  Response Preview: {data_str[:500]}...")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await page.close()

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        try:
            print("Launching persistent context...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=r"A:\ChromeDevToolsProfile",
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True
            )
            print("Launched successfully.")
        except Exception as e:
            print(f"Failed to launch persistent context: {e}")
            return
            
        await diagnose_keys_api(context, "qlcode", "https://api.qlcodeapi.com/keys")
        await diagnose_keys_api(context, "tygzs", "https://sub2api.tygzs.cn/keys")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
