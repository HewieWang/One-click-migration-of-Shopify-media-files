import streamlit as st
import requests
import time
import json
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 网页基础配置 ---
st.set_page_config(page_title="Shopify 媒体文件搬家工具", layout="wide")

# --- 侧边栏：统一参数配置 ---
st.sidebar.header("⚙️ 核心参数配置")

SOURCE_SHOP = st.sidebar.text_input("源店铺域名 (SOURCE_SHOP)", value="xxxx.myshopify.com")
SOURCE_TOKEN = st.sidebar.text_input("源店铺 Token (SOURCE_TOKEN)", value="xxxx", type="password")

# 默认提供图片目标，用户可自行修改
DEST_SHOP = st.sidebar.text_input("目标店铺域名 (DEST_SHOP)", value="xxxx.myshopify.com")
DEST_TOKEN = st.sidebar.text_input("目标店铺 Token (DEST_TOKEN)", value="xxxx", type="password")

st.sidebar.markdown("---")
st.sidebar.header("📦 高级设置")
API_VERSION = st.sidebar.text_input("API 版本 (API_VERSION)", value="2024-04")
IMAGE_CACHE_FILE = st.sidebar.text_input("图片缓存文件", value="synced_files_cache2.json")
VIDEO_CACHE_FILE = st.sidebar.text_input("视频缓存文件", value="synced_videos_cache.json")

# --- 统一网络请求 Session 配置 ---
def get_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

session = get_session()

def shopify_graphql(shop, token, query, variables=None):
    url = f"https://{shop}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    try:
        response = session.post(url, json={'query': query, 'variables': variables}, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- 主页面布局 ---
col_main, col_sponsor = st.columns([3, 1])

with col_main:
    st.title("🛍️ Shopify 媒体文件一键搬家工具")
    st.markdown("配置左侧参数后，点击下方对应按钮开始同步。系统支持断点续传，中途断开重新运行即可。")
    
    # 创建两个标签页
    tab1, tab2 = st.tabs(["🖼️ 搬运图片", "🎬 搬运视频"])

# --- 赞助区逻辑 ---
with col_sponsor:
    st.markdown("### ☕ 友情赞助")
    st.caption("如果您觉得本工具好用，欢迎请作者喝杯咖啡，支持后续开发维护~")
    
    if os.path.exists("qr_code.png"):
        st.image("qr_code.png", caption="扫码赞助作者", use_container_width=True)
    else:
        st.info("📌 赞助说明：\n请在脚本同级目录下放置一张名为 `qr_code.png` 的收款二维码图片，网页将自动在此处展示。")

# =====================================================================
# 逻辑一：图片搬运方案
# =====================================================================
with tab1:
    st.subheader("图片同步控制台")
    img_run_btn = st.button("🚀 开始一键搬运所有图片", type="primary", key="img_btn")
    img_log_area = st.empty()
    img_logs = []

    def img_log(msg):
        current_time = time.strftime("%H:%M:%S", time.localtime())
        img_logs.append(f"[{current_time}] {msg}")
        img_log_area.code("\n".join(img_logs[-50:]), language="text")

    def fetch_source_files():
        all_urls = []
        cursor = None
        has_next = True
        query = """
        query ($cursor: String) {
          files(first: 50, after: $cursor) {
            pageInfo { hasNextPage }
            edges {
              cursor
              node {
                ... on MediaImage { image { url } }
                ... on GenericFile { url }
              }
            }
          }
        }
        """
        img_log(f"开始从 {SOURCE_SHOP} 提取图片文件列表...")
        while has_next:
            result = shopify_graphql(SOURCE_SHOP, SOURCE_TOKEN, query, {"cursor": cursor})
            if not result or 'data' not in result or not result['data']['files']:
                break
            edges = result['data']['files']['edges']
            for edge in edges:
                node = edge['node']
                raw_url = node.get('url') or (node.get('image', {}).get('url') if 'image' in node else None)
                if raw_url:
                    all_urls.append(raw_url.split('?')[0])
            has_next = result['data']['files']['pageInfo']['hasNextPage']
            if has_next and edges:
                cursor = edges[-1]['cursor']
                img_log(f"已扫描 {len(all_urls)} 个图片文件...")
        return list(set(all_urls))

    def sync_images_to_destination(urls):
        synced_urls = set()
        if os.path.exists(IMAGE_CACHE_FILE):
            try:
                with open(IMAGE_CACHE_FILE, 'r') as f:
                    synced_urls = set(json.load(f))
            except: pass
        to_sync = [u for u in urls if u not in synced_urls]
        img_log(f"待同步图片: {len(to_sync)} / 总计: {len(urls)}")
        if not to_sync:
            img_log("所有图片均已同步过。")
            return
            
        img_progress = st.progress(0.0, text="正在搬运图片...")
        mutation = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) { userErrors { field message } }
        }
        """
        for i in range(0, len(to_sync), 10):
            batch = to_sync[i:i+10]
            input_files = [{"originalSource": url, "contentType": "IMAGE"} for url in batch]
            result = shopify_graphql(DEST_SHOP, DEST_TOKEN, mutation, {"files": input_files})
            if result and 'data' in result:
                errors = result['data']['fileCreate']['userErrors']
                if errors:
                    img_log(f"批次 {i//10 + 1} 部分失败: {errors}")
                else:
                    img_log(f"成功推送第 {i+1} - {min(i+10, len(to_sync))} 个图片")
                synced_urls.update(batch)
                with open(IMAGE_CACHE_FILE, 'w') as f:
                    json.dump(list(synced_urls), f)
            img_progress.progress(min((i + 10) / len(to_sync), 1.0), text=f"进度: {min(i+10, len(to_sync))}/{len(to_sync)}")
            time.sleep(0.6)

    if img_run_btn:
        img_logs = []
        start_t = time.time()
        with st.status("图片同步任务执行中...", expanded=True) as status:
            file_list = fetch_source_files()
            if file_list:
                sync_images_to_destination(file_list)
            else:
                img_log("❌ 未能抓取到有效图片文件。")
            duration = round((time.time() - start_t)/60, 2)
            img_log(f"🎉 图片同步完成！总耗时: {duration} 分钟")
            status.update(label=f"图片同步完成，耗时 {duration} 分钟", state="complete")

# =====================================================================
# 逻辑二：视频搬运方案
# =====================================================================
with tab2:
    st.subheader("视频同步控制台")
    vdo_run_btn = st.button("🚀 开始一键搬运所有视频", type="primary", key="vdo_btn")
    vdo_log_area = st.empty()
    vdo_logs = []

    def vdo_log(msg):
        current_time = time.strftime("%H:%M:%S", time.localtime())
        vdo_logs.append(f"[{current_time}] {msg}")
        vdo_log_area.code("\n".join(vdo_logs[-50:]), language="text")

    def fetch_source_videos():
        video_files = []
        cursor = None
        has_next = True
        query = """
        query ($cursor: String) {
          files(first: 50, after: $cursor) {
            pageInfo { hasNextPage }
            edges {
              cursor
              node {
                __typename
                ... on Video { filename sources { url format } }
              }
            }
          }
        }
        """
        vdo_log(f"🎬 开始从 {SOURCE_SHOP} 提取视频列表...")
        while has_next:
            result = shopify_graphql(SOURCE_SHOP, SOURCE_TOKEN, query, {"cursor": cursor})
            if not result or 'data' not in result or not result['data']['files']:
                break
            edges = result['data']['files']['edges']
            for edge in edges:
                node = edge['node']
                if node.get('__typename') == 'Video':
                    filename = node.get('filename') or "video.mp4"
                    sources = node.get('sources', [])
                    mp4_sources = [s for s in sources if 'mp4' in s.get('format', '').lower() or 'mp4' in s.get('url', '').lower()]
                    if mp4_sources:
                        video_files.append({
                            "url": mp4_sources[0].get('url').split('?')[0],
                            "filename": filename
                        })
            has_next = result['data']['files']['pageInfo']['hasNextPage']
            if has_next and edges:
                cursor = edges[-1]['cursor']
                vdo_log(f"已扫描到 {len(video_files)} 个 MP4 视频...")
        seen = set()
        unique_videos = []
        for v in video_files:
            if v['url'] not in seen:
                seen.add(v['url'])
                unique_videos.append(v)
        return unique_videos

    def sync_videos_to_destination(videos):
        synced_urls = set()
        # 🟢 已修复：将 VIDEO_CACHE 改为顶部定义的 VIDEO_CACHE_FILE 并且修正了缩进
        if os.path.exists(VIDEO_CACHE_FILE):
            try:
                with open(VIDEO_CACHE_FILE, 'r') as f:
                    synced_urls = set(json.load(f))
            except: 
                pass
        to_sync = [v for v in videos if v['url'] not in synced_urls]
        vdo_log(f"📦 待同步视频: {len(to_sync)} / 总计: {len(videos)}")
        if not to_sync:
            vdo_log("所有视频均已同步过。")
            return

        vdo_progress = st.progress(0.0)
        staged_mutation = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }
        """
        create_mutation = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) { userErrors { field message } }
        }
        """

        for idx, item in enumerate(to_sync):
            origin_url = item['url']
            filename = item['filename']
            vdo_log(f"正在处理 [{idx+1}/{len(to_sync)}]: {filename}")
            try:
                # 1. 下载
                file_res = session.get(origin_url, timeout=60)
                if file_res.status_code != 200:
                    vdo_log(f"   ❌ 下载失败，HTTP 状态码: {file_res.status_code}")
                    continue
                file_data = file_res.content
                
                # 2. 申请通道
                staged_input = {"fileSize": str(len(file_data)), "filename": filename, "mimeType": "video/mp4", "resource": "VIDEO"}
                staged_res = shopify_graphql(DEST_SHOP, DEST_TOKEN, staged_mutation, {"input": [staged_input]})
                if not staged_res or 'data' not in staged_res or not staged_res['data']['stagedUploadsCreate']['stagedTargets']:
                    vdo_log(f"   ❌ 申请通道失败: {staged_res}")
                    continue
                    
                # 🟢 已修复：stagedTargets 是列表，需要通过 [0] 索引访问对象
                target = staged_res['data']['stagedUploadsCreate']['stagedTargets'][0]
                form_data = [(p['name'], p['value']) for p in target['parameters']]
                upload_files = [*form_data, ('file', (filename, file_data, "video/mp4"))]
                
                # 3. 推送云端
                s3_res = requests.post(target['url'], files=upload_files, timeout=120)
                if s3_res.status_code not in [200, 201, 204]:
                    vdo_log(f"   ❌ 云存储拒绝，状态码: {s3_res.status_code}")
                    continue

                # 4. 激活视频
                file_input = {"originalSource": target['resourceUrl'], "contentType": "VIDEO", "alt": filename.split('.')[0]}
                create_res = shopify_graphql(DEST_SHOP, DEST_TOKEN, create_mutation, {"files": [file_input]})
                
                if create_res and 'data' in create_res and create_res['data']['fileCreate']:
                    errors = create_res['data']['fileCreate']['userErrors']
                    if errors:
                        vdo_log(f"   ⚠️ 激活失败，尝试不带类型进行兜底激活...")
                        del file_input["contentType"]
                        retry_res = shopify_graphql(DEST_SHOP, DEST_TOKEN, create_mutation, {"files": [file_input]})
                        if retry_res and 'data' in retry_res and not retry_res['data']['fileCreate']['userErrors']:
                            vdo_log(f"   ✅ 兜底激活成功！已进入处理队列。")
                            synced_urls.add(origin_url)
                        else:
                            vdo_log(f"   ❌ 激活最终失败: {errors}")
                    else:
                        vdo_log(f"   ✅ 同步成功！已进入处理队列。")
                        synced_urls.add(origin_url)
                    
                    with open(VIDEO_CACHE_FILE, 'w') as f:
                        json.dump(list(synced_urls), f)
                else:
                    vdo_log(f"   ❌ 激活接口返回异常。")
            except Exception as e:
                vdo_log(f"   ❌ 运行时异常: {e}")
                
            vdo_progress.progress((idx + 1) / len(to_sync), text=f"视频进度: {idx+1}/{len(to_sync)}")
            time.sleep(1.0)

    if vdo_run_btn:
        vdo_logs = []
        start_t = time.time()
        with st.status("视频同步任务执行中...", expanded=True) as status:
            video_list = fetch_source_videos()
            if video_list:
                sync_videos_to_destination(video_list)
            else:
                vdo_log("❌ 未能抓取到有效视频文件。")
            duration = round((time.time() - start_t)/60, 2)
            vdo_log(f"🎉 视频同步完成！总耗时: {duration} 分钟")
            status.update(label=f"视频同步完成，耗时 {duration} 分钟", state="complete")
