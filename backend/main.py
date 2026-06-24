from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import json
from pathlib import Path
from urllib.parse import urlparse

# ===== PyInstaller 路径修正 =====
# 打包后 sys._MEIPASS 是解压的临时目录；源码运行时则使用项目根目录
if hasattr(sys, '_MEIPASS'):
    # 打包环境：静态文件在 _MEIPASS，history 写入 EXE 旁边的 data 目录（持久化）
    _STATIC_BASE = Path(sys._MEIPASS)
    _DATA_BASE = Path(sys.executable).parent
else:
    # 开发环境：直接使用项目目录
    _STATIC_BASE = Path(__file__).parent.parent
    _DATA_BASE = Path(__file__).parent.parent

STATIC_DIR = _STATIC_BASE / "frontend" / "static"
HISTORY_PATH = _DATA_BASE / "data" / "history.jsonl"

from backend.services.ccswitch_reader import load_stations, find_ccswitch_db
from backend.services.health_checker import check_all_stations

app = FastAPI(title="AI Proxy Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_raw_group_cache: list[dict] = []
_check_cache: list[dict] = []


def _host_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return url.lower()


def _price_item_count(group: dict) -> int:
    price_map = group.get("price_map", {})
    return len(price_map) if isinstance(price_map, dict) else 0


def _model_count(group: dict) -> int:
    models = group.get("available_models", [])
    return len(models) if isinstance(models, list) else 0


def _public_group_data(group: dict) -> dict:
    return {
        "id": group["id"],
        "group_name": group["name"],
        "base_url": group["base_url"],
        "category": group["category"],
        "is_current": group["is_current"],
        "provider_type": group["provider_type"],
        "website_url": group["website_url"],
        "notes": group["notes"],
        "status": group.get("status", "unknown"),
        "status_reason": group.get("status_reason", "未知，需验证"),
        "last_check": group.get("last_check"),
        "response_time_ms": group.get("response_time_ms"),
        "model_count": _model_count(group),
        "price_item_count": _price_item_count(group),
        "checked_at": group.get("checked_at"),
    }


def _build_station_view(groups: list[dict]) -> dict:
    first = groups[0]
    
    # 查找是否有抓取到的真实分组
    real_groups = None
    for g in groups:
        if g.get("groups_info"):
            real_groups = g["groups_info"]
            break
            
    # 计算当前激活的分组
    current_groups_in_db = [g["name"] for g in groups if g.get("is_current")]
    
    # 计算站点在线、异常状态 (基于原始检测的状态)
    status_counts = {"online": 0, "unknown": 0, "error": 0}
    for g in groups:
        status = g.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        
    if status_counts["error"] > 0:
        station_status = "error"
    elif status_counts["unknown"] > 0 and status_counts["online"] == 0:
        station_status = "unknown"
    elif status_counts["online"] > 0:
        station_status = "online"
    else:
        station_status = "unknown"
        
    checked_times = [g.get("checked_at") for g in groups if g.get("checked_at")]
    latest_check = max(checked_times) if checked_times else None
    
    balances = [g.get("balance") for g in groups if g.get("balance") is not None]
    station_balance = balances[0] if balances else None
    
    # 提取官网地址 website_url
    station_website_url = None
    for g in groups:
        if g.get("website_url"):
            station_website_url = g["website_url"]
            break

    # 构建展示用的分组列表
    public_groups = []
    if real_groups:
        # 如果有网页抓取的真实分组，根据倍率从低到高排序
        sorted_real = sorted(real_groups.items(), key=lambda x: x[1]["ratio"])
        
        for grp_id, info in sorted_real:
            is_current = grp_id in [c.lower() for c in current_groups_in_db] or info["name"] in current_groups_in_db
            
            model_count = len(first.get("available_models", []))
            price_item_count = len(first.get("price_map", {}))
            
            public_groups.append({
                "id": f"{first['id']}_{grp_id}",
                "group_name": f"{info['name']} ({info['ratio']}x)",
                "base_url": first["base_url"],
                "category": f"倍率: {info['ratio']}",
                "is_current": is_current,
                "provider_type": first["provider_type"],
                "website_url": first["website_url"],
                "notes": first["notes"],
                "status": first.get("status", "unknown"),
                "status_reason": first.get("status_reason", "网页校验成功"),
                "last_check": latest_check,
                "response_time_ms": first.get("response_time_ms"),
                "model_count": model_count,
                "price_item_count": price_item_count,
                "checked_at": latest_check,
            })
    else:
        # 兜底：使用 ccswitch 的记录作为分组
        for g in groups:
            public_groups.append(_public_group_data(g))
            
    summary_parts = []
    g_status_counts = {"online": 0, "unknown": 0, "error": 0}
    for pg in public_groups:
        g_status_counts[pg["status"]] = g_status_counts.get(pg["status"], 0) + 1
        
    if g_status_counts["online"]:
        summary_parts.append(f"在线 {g_status_counts['online']} 个")
    if g_status_counts["unknown"]:
        summary_parts.append(f"需验证 {g_status_counts['unknown']} 个")
    if g_status_counts["error"]:
        summary_parts.append(f"异常 {g_status_counts['error']} 个")
    status_reason = "，".join(summary_parts) if summary_parts else first.get("status_reason", "尚未检测")
    
    return {
        "station_key": _host_from_url(first["base_url"]),
        "station_name": _host_from_url(first["base_url"]),
        "host": _host_from_url(first["base_url"]),
        "balance": station_balance,
        "status": station_status,
        "status_reason": status_reason,
        "last_check": latest_check,
        "group_count": len(public_groups),
        "online_count": g_status_counts["online"],
        "unknown_count": g_status_counts["unknown"],
        "error_count": g_status_counts["error"],
        "current_group_names": current_groups_in_db,
        "website_url": station_website_url,
        "alias": first["name"],
        "groups": public_groups,
    }


def _build_station_list(groups: list[dict]) -> list[dict]:
    grouped_by_host: dict[str, list[dict]] = {}
    for group in groups:
        host = _host_from_url(group["base_url"])
        grouped_by_host.setdefault(host, []).append(group)
        
    stations = [_build_station_view(host_groups) for host_groups in grouped_by_host.values()]
    stations.sort(key=lambda station: (station["status"] != "error", station["status"] != "unknown", not station["current_group_names"], station["host"]))
    return stations



def _save_check_history(groups: list[dict]):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        for group in groups:
            f.write(json.dumps({
                "ts": group.get("checked_at"),
                "id": group["id"],
                "name": group["name"],
                "host": _host_from_url(group["base_url"]),
                "status": group.get("status"),
                "status_reason": group.get("status_reason"),
                "balance": group.get("balance"),
                "rt_ms": group.get("response_time_ms"),
                "model_count": _model_count(group),
                "price_item_count": _price_item_count(group),
            }, ensure_ascii=False) + "\n")


def initialize():
    global _raw_group_cache
    try:
        stations = load_stations()
        _raw_group_cache = [{
            "id": station.id,
            "name": station.name,
            "base_url": station.base_url,
            "api_key": station.api_key,
            "category": station.category,
            "is_current": station.is_current,
            "in_failover": station.in_failover,
            "provider_type": station.provider_type,
            "website_url": station.website_url,
            "notes": station.notes,
            "status": "unknown",
            "status_reason": "尚未检测",
            "last_check": None,
            "response_time_ms": None,
            "balance": None,
            "available_models": [],
            "price_map": {},
        } for station in stations if ".fcapp.run" not in station.base_url.lower() and "xiaomimimo.com" not in station.base_url.lower()]
        print(f"[init] loaded {len(_raw_group_cache)} groups from ccswitch")
    except Exception as exc:
        print(f"[init] failed: {exc}")
        _raw_group_cache = []


initialize()


@app.get("/api/providers")
def get_providers():
    return [_public_group_data(group) for group in _raw_group_cache]


@app.get("/api/health")
async def run_health_check():
    global _check_cache
    if not _raw_group_cache:
        return {"error": "no providers loaded"}

    _check_cache = await check_all_stations(_raw_group_cache, concurrency=6)
    _save_check_history(_check_cache)
    return _build_station_list(_check_cache)


@app.get("/api/login_channel")
async def login_channel(url: str):
    """
    拉起前台 Chrome 浏览器或在已有的 9222 Chrome 中新建标签页，共享 A:\\ChromeDevToolsProfile 登录态，
    方便用户扫码或重新登录。程序阻塞等待用户登录页面关闭。
    """
    from backend.services.health_checker import _find_chrome_path, is_port_open
    from playwright.async_api import async_playwright
    import asyncio
    
    chrome_path = _find_chrome_path()
    if not chrome_path and not is_port_open("127.0.0.1", 9222):
        return {"success": False, "error": "在系统默认路径中未检测到 Chrome 浏览器，无法弹出窗口。"}

    print(f"[login_helper] Spawning/connecting Chrome session for: {url}")
    async with async_playwright() as p:
        context = None
        try:
            # 1. 优先检测 9222 端口，若用户已经打开了调试版 Chrome，则直接在其中新建标签页，实现零冲突免登
            if is_port_open("127.0.0.1", 9222):
                print("[login_helper] Port 9222 is active. Connecting over CDP and opening a new tab...")
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                page = await context.new_page()
                await page.set_viewport_size({"width": 1200, "height": 800})
                await page.goto(url, timeout=20000)
                
                # 轮询等待用户关闭该标签页
                while True:
                    try:
                        if page.is_closed():
                            break
                        await asyncio.sleep(0.8)
                    except Exception:
                        break
                
                print("[login_helper] User closed the login tab.")
                return {"success": True, "message": "登录标签页已关闭。"}

            # 自适应获取 Chrome 调试 Profile 路径（兼容 A 盘和无 A 盘的系统）
            profile_dir = "A:\\ChromeDevToolsProfile"
            if not (os.path.exists("A:\\") or os.path.isdir("A:\\")):
                profile_dir = os.path.expanduser("~/.ai-proxy-monitor/ChromeDevToolsProfile")

            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                executable_path=chrome_path,
                headless=False,
                args=[
                    "--remote-debugging-port=9222",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu-sandbox",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-breakpad",
                ]
            )
            
            # 若已有打开的页面则复用，否则新开一页
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()
            
            await page.set_viewport_size({"width": 1200, "height": 800})
            await page.goto(url, timeout=20000)
            
            # 持续轮询，直到用户把这个登录调试浏览器页面关闭
            while True:
                try:
                    if page.is_closed():
                        break
                    if len(context.pages) == 0:
                        break
                    await asyncio.sleep(0.8)
                except Exception:
                    break
                
            print("[login_helper] Visible Chrome session closed. Cookie updated.")
            return {"success": True, "message": "登录会话已成功关闭，已同步 Cookie 登录态。"}
        except Exception as err:
            print(f"[login_helper] Visible Chrome session failed: {err}")
            return {"success": False, "error": str(err)}



@app.get("/api/status")
def get_status():
    merged = {group["id"]: {**group} for group in _raw_group_cache}
    for checked in _check_cache:
        if checked["id"] in merged:
            merged[checked["id"]].update(checked)
            merged[checked["id"]]["last_check"] = checked.get("checked_at")

    station_list = _build_station_list(list(merged.values()))
    return {
        "stations": station_list,
        "db": find_ccswitch_db(),
        "total": len(station_list),
        "online": sum(1 for station in station_list if station.get("status") == "online"),
        "unknown": sum(1 for station in station_list if station.get("status") == "unknown"),
        "error": sum(1 for station in station_list if station.get("status") == "error"),
    }


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/style.css")
def style_css():
    return FileResponse(str(STATIC_DIR / "style.css"))


@app.get("/app.js")
def app_js():
    return FileResponse(str(STATIC_DIR / "app.js"))


from fastapi import Response

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


