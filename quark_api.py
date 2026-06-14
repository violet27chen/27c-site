from urllib.parse import quote
#!/usr/bin/env python3
"""
Quark Cloud Drive API Wrapper
解析夸克网盘分享链接，获取文件信息和下载地址
"""

import re
import json
import time
import logging
import requests

logger = logging.getLogger(__name__)

# 夸克 API 基础配置
BASE_URL = "https://drive-pc.quark.cn"
HEADERS = {
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 "
                  "Electron/24.1.3.8 Safari/537.36 Channel/pckk_other_ch",
}
COMMON_PARAMS = "pr=ucpro&fr=pc"


class QuarkAPIError(Exception):
    """夸克 API 错误"""
    pass


class QuarkAPI:
    def __init__(self, cookie: str):
        self.cookie = cookie
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["cookie"] = cookie

    @staticmethod
    def extract_share_id(url: str) -> str:
        """从分享链接中提取 share id (pwd_id)"""
        # 支持格式: https://pan.quark.cn/s/xxxxxx
        match = re.search(r"pan\.quark\.cn/s/([a-zA-Z0-9]+)", url)
        if not match:
            raise QuarkAPIError(f"无效的夸克分享链接: {url}")
        return match.group(1)

    def get_stoken(self, pwd_id: str) -> str:
        """获取 stoken（验证分享链接）"""
        url = f"{BASE_URL}/1/clouddrive/share/sharepage/token?{COMMON_PARAMS}"
        payload = {"pwd_id": pwd_id, "passcode": ""}

        try:
            resp = self.session.post(url, json=payload, timeout=15)
            data = resp.json()
        except requests.RequestException as e:
            raise QuarkAPIError(f"网络请求失败: {e}")

        if data.get("code") != 0:
            msg = data.get("message", "未知错误")
            raise QuarkAPIError(f"获取 stoken 失败: {msg}")

        stoken = data.get("data", {}).get("stoken")
        if not stoken:
            raise QuarkAPIError("未返回 stoken")
        return stoken

    def get_share_files(self, pwd_id: str, stoken: str) -> list:
        stoken = quote(stoken, safe="")
        """获取分享链接中的文件列表"""
        url = (
            f"{BASE_URL}/1/clouddrive/share/sharepage/detail?"
            f"{COMMON_PARAMS}&pwd_id={pwd_id}&stoken={stoken}"
            f"&pdir_fid=0&force=0&_page=1&_size=50&_fetch_banner=0"
            f"&_fetch_share=0&_fetch_total=1&_sort=file_type:asc,updated_at:desc"
            f"&ver=2&fetch_share_full_path=0"
        )

        try:
            resp = self.session.get(url, timeout=15)
            data = resp.json()
        except requests.RequestException as e:
            raise QuarkAPIError(f"网络请求失败: {e}")

        if data.get("code") != 0:
            msg = data.get("message", "未知错误")
            raise QuarkAPIError(f"获取文件列表失败: {msg}")

        files = data.get("data", {}).get("list", [])
        total = data.get("metadata", {}).get("_total", 0)
        logger.info(f"获取到 {len(files)} 个文件，共 {total} 个")

        return files

    def get_download_url(self, fid: str) -> dict:
        """获取文件下载地址"""
        url = f"{BASE_URL}/1/clouddrive/file/download?{COMMON_PARAMS}&uc_param_str="
        payload = {"fids": [fid]}

        try:
            resp = self.session.post(url, json=payload, timeout=15)
            data = resp.json()
        except requests.RequestException as e:
            raise QuarkAPIError(f"网络请求失败: {e}")

        if data.get("code") != 0:
            msg = data.get("message", "未知错误")
            raise QuarkAPIError(f"获取下载地址失败: {msg}")

        download_list = data.get("data", [])
        if not download_list:
            raise QuarkAPIError("未返回下载地址")

        item = download_list[0]
        download_url = item.get("download_url")
        if not download_url:
            raise QuarkAPIError("下载地址为空")

        return {
            "fid": item.get("fid"),
            "file_name": item.get("file_name"),
            "download_url": download_url,
        }


    def get_folder_files(self, pwd_id: str, stoken: str, folder_fid: str) -> list:
        stoken = quote(stoken, safe="")
        """获取文件夹内的文件列表"""
        url = (
            f"{BASE_URL}/1/clouddrive/share/sharepage/detail?"
            f"{COMMON_PARAMS}&pwd_id={pwd_id}&stoken={stoken}"
            f"&pdir_fid={folder_fid}&force=0&_page=1&_size=50&_fetch_banner=0"
            f"&_fetch_share=0&_fetch_total=1&_sort=file_type:asc,updated_at:desc"
            f"&ver=2&fetch_share_full_path=0"
        )

        try:
            resp = self.session.get(url, timeout=15)
            data = resp.json()
        except requests.RequestException as e:
            raise QuarkAPIError(f"网络请求失败: {e}")

        if data.get("code") != 0:
            msg = data.get("message", "未知错误")
            raise QuarkAPIError(f"获取文件列表失败: {msg}")

        files = data.get("data", {}).get("list", [])
        return files

    def parse_link(self, url: str) -> dict:
        """完整流程：解析链接 → 获取 stoken → 获取文件列表（支持文件夹）"""
        pwd_id = self.extract_share_id(url)
        stoken = self.get_stoken(pwd_id)
        files = self.get_share_files(pwd_id, stoken)

        # 整理文件信息
        result = []
        for f in files:
            is_dir = f.get("dir", False)
            result.append({
                "fid": f.get("fid", ""),
                "share_fid_token": f.get("share_fid_token", ""),
                "file_name": f.get("file_name", "未知文件"),
                "file_size": f.get("size", 0),
                "file_type": f.get("file_type", 0),
                "is_dir": is_dir,
                "format_size": _format_size(f.get("size", 0)),
            })

        return {
            "pwd_id": pwd_id,
            "stoken": stoken,
            "files": result,
            "total": len(result),
        }

def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def calculate_price(file_size: int) -> float:
    """根据文件大小计算价格（元）"""
    size_mb = file_size / (1024 * 1024)
    if size_mb < 100:
        return 2.0
    elif size_mb < 1024:
        return 5.0
    else:
        return 10.0